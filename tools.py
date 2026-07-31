import json
import re
from dotenv import load_dotenv
from loguru import logger
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
import database
from prompts import SYSTEM_PROMPT

load_dotenv()

logger.add("logs/tools.log", rotation="10 MB", level="DEBUG")

llm = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")
#llm = ChatGroq(temperature=0, model_name="llama-3.1-8b-instant")


FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
    "ALTER", "CREATE", "REPLACE", "MERGE", "UPSERT",
    "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL",
]

MAX_QUESTION_LENGTH = 500


def is_safe_sql(sql: str):
    # hardcoded guardrail, even if llm ignores the prompt this catches it
    cleaned = re.sub(r'--[^\n]*', '', sql)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().upper()

    # A trailing semicolon is removed before this function is called. Any remaining
    # semicolon means the model attempted to send more than one statement.
    if ";" in cleaned:
        logger.warning("GUARDRAIL TRIGGERED — multiple SQL statements")
        return False, "Only one read-only query is allowed."

    tokens = re.findall(r'\b\w+\b', cleaned)

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in tokens:
            # we are using logs to make sure the information being provided is accurate
            logger.warning("GUARDRAIL TRIGGERED — forbidden keyword: {k}", k=keyword)
            return False, f"Query contains forbidden operation: {keyword}"

    # PostgreSQL CTEs begin with WITH but are still read-only when they end in a
    # SELECT. Forbidden keywords above reject data-modifying CTEs such as
    # `WITH changed AS (UPDATE ... RETURNING ...) SELECT ...`.
    if not re.match(r'^(SELECT|WITH)\b', cleaned):
        logger.warning("GUARDRAIL TRIGGERED — not a read-only query: {s}", s=cleaned[:50])
        return False, "Only read-only SELECT queries are allowed."

    if cleaned.startswith("WITH") and "SELECT" not in tokens:
        logger.warning("GUARDRAIL TRIGGERED — CTE without SELECT")
        return False, "Only read-only SELECT queries are allowed."

    return True, ""


def sanitize_input(question: str):
    if not question or not question.strip():
        return "", "Question cannot be empty."

    cleaned = re.sub(r'\s+', ' ', question.strip())

    if len(cleaned) > MAX_QUESTION_LENGTH:
        return "", f"Question too long. Keep it under {MAX_QUESTION_LENGTH} characters."

    # strip chars that shouldnt be in a natural language question
    cleaned = re.sub(r'[`;\\\x00-\x1f]', '', cleaned)

    # basic sql injection check
    sql_pattern = re.compile(
        r'\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|UNION)\b',
        re.IGNORECASE
    )
    if sql_pattern.search(cleaned):
        # we are using logs to make sure the information being provided is accurate
        logger.warning("possible sql injection in input: {q}", q=cleaned)
        return "", "Input looks like a SQL query. Please ask a natural language question."

    return cleaned, None


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = text.split("```")[1]
        for lang in ("sql", "json"):
            if text.startswith(lang):
                text = text[len(lang):]
                break
        text = text.strip()
    return text


def generate_sql(question: str):
    logger.info("generate_sql called with: {q}", q=question)

    cleaned_question, error = sanitize_input(question)
    if error:
        return None, error

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{question}"),
    ])

    chain = prompt | llm
    result = chain.invoke({"question": cleaned_question})
    sql = result.content.strip()

    # we are using logs to make sure the information being provided is accurate
    logger.debug("raw LLM response: {r}", r=sql)

    sql = _strip_code_fence(sql)
    sql = sql.rstrip(";").strip()

    if sql == "CANNOT_ANSWER":
        logger.warning("LLM returned CANNOT_ANSWER for: {q}", q=cleaned_question)
        return None, "This question cannot be answered from the SalesCo database."

    # we are using logs to make sure the information being provided is accurate
    logger.success("SQL generated: {sql}", sql=sql)
    return sql, None


def execute_sql(sql: str):
    safe, reason = is_safe_sql(sql)
    if not safe:
        logger.error("SQL blocked: {r}", r=reason)
        return None, reason

    try:
        results = database.run_query(sql)
        # we are using logs to make sure the information being provided is accurate
        logger.success("query returned {n} rows", n=len(results))
        logger.debug("first 3 rows: {r}", r=results[:3])
        return results, None
    except Exception as e:
        logger.error("execution failed: {e}", e=str(e))
        return None, f"Query failed: {str(e)}"


def repair_sql(question: str, failed_sql: str, database_error: str):
    """Return one corrected, read-only SQL statement for a failed query."""
    repair_prompt = f"""
You repair PostgreSQL queries for the SalesCo analytics database.

Original user question: {question}
Failed SQL: {failed_sql}
Database or validation error: {database_error}

Use this database schema and its rules:
{SYSTEM_PROMPT}

Return exactly one corrected, read-only PostgreSQL SELECT statement. Do not include
Markdown, an explanation, a semicolon, or a data-changing statement. If the question
cannot be answered using the supplied schema, return exactly CANNOT_ANSWER.
"""
    try:
        response = llm.invoke(repair_prompt)
        sql = response.content.strip()
        logger.debug("raw SQL repair response: {r}", r=sql)

        sql = _strip_code_fence(sql)
        sql = sql.rstrip(";").strip()
        if sql == "CANNOT_ANSWER":
            return None, "This question cannot be answered from the SalesCo database."

        safe, reason = is_safe_sql(sql)
        if not safe:
            return None, reason

        logger.success("SQL repaired: {sql}", sql=sql)
        return sql, None
    except Exception as e:
        logger.error("SQL repair failed: {e}", e=str(e))
        return None, "Could not repair the generated SQL query."


def is_chart_candidate(results: list[dict]) -> bool:
    """Trivial, judgment-free gate: is there even more than one data point to plot?

    Only rules out cases with nothing to decide (no rows, or a single cell) so an
    LLM call isn't wasted on them. Whether the data is actually *worth* charting —
    given the shape of the results and what the question is asking — is the LLM's
    call in decide_chart_spec, not a hardcoded rule here.
    """
    return len(results) > 1 or (len(results) == 1 and len(results[0]) > 1)


def decide_chart_spec(results: list[dict], question: str) -> dict | None:
    """Ask the LLM whether this result is worth charting and, if so, how.

    Returns a JSON-serializable spec (not a figure) so the caller decides how to
    render it, or None if the LLM judges a chart wouldn't help. Call
    is_chart_candidate() first to skip results with nothing to plot at all.
    """
    if not results:
        return None

    columns = list(results[0].keys())
    sample = results[:3]

    decision_prompt = f"""
You are a data visualization expert deciding whether a chart would help answer a question.
Original question: {question}
Columns available: {columns}
Row count: {len(results)}
Sample rows: {json.dumps(sample, default=str)}

Only recommend a chart if it would genuinely help — e.g. comparing values across
categories, a trend over time, or a distribution. Do not recommend one for raw record
listings, single data points, id-only columns, or results better read as text/a table.
Pick a `y` column that actually varies across the rows — never one that's constant
(for example, don't chart a column the query already filtered down to a single value).
Prefer a descriptive/name column over a numeric one for `x` when comparing distinct
entities (e.g. company_name rather than a duplicated count column).

Reply with ONLY a JSON object:
{{
  "should_plot": true | false,
  "chart_type": "bar" | "line" | "pie" | "scatter" | null,
  "x": "<column name>" | null,
  "y": "<column name>" | null,
  "title": "<short title>" | null
}}
"""

    response = llm.invoke(decision_prompt)
    raw = _strip_code_fence(response.content.strip())

    # we are using logs to make sure the information being provided is accurate
    logger.debug("LLM chart decision: {r}", r=raw)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("failed to parse chart JSON: {e}", e=str(e))
        return None

    if not decision.get("should_plot"):
        logger.info("LLM decided not to plot this result")
        return None

    chart_type = decision.get("chart_type") or "bar"
    x_col = decision.get("x")
    y_col = decision.get("y")
    title = decision.get("title") or question

    if x_col not in columns or y_col not in columns:
        logger.warning("columns not in results, skipping chart")
        return None

    # A constant y column produces a chart with nothing visible in it (e.g. every bar
    # at height zero) no matter what the LLM claims — verify instead of trusting it.
    y_values = {row.get(y_col) for row in results}
    if len(y_values) <= 1:
        logger.warning("y column '{c}' has no variation across results, skipping chart", c=y_col)
        return None

    logger.success("chart spec decided: {t}", t=chart_type)
    return {"chart_type": chart_type, "x": x_col, "y": y_col, "title": title}


def generate_thread_title(question: str) -> str:
    """Generate a short 2-4 word title for a new conversation, based on its
    first question. Called once per thread, not per turn.
    """
    prompt = f"""
Generate a short, plain title (2-4 words, no quotes, no trailing punctuation)
summarizing this database question for a conversation list:

{question}
"""
    try:
        response = llm.invoke(prompt)
        title = response.content.strip().strip('"').strip("'")
        logger.debug("generated thread title: {t}", t=title)
        return title or question[:40]
    except Exception as e:
        logger.error("title generation failed: {e}", e=str(e))
        return question[:40]


if __name__ == "__main__":
    question = "What is the total revenue by product category?"

    sql, error = generate_sql(question)
    if error:
        print(f"error: {error}")
    else:
        print(f"sql: {sql}")
        results, error = execute_sql(sql)
        if error:
            print(f"error: {error}")
        else:
            for row in results:
                print(row)
            spec = decide_chart_spec(results, question)
            if spec:
                print(f"chart spec: {spec}")