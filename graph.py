"""Message-based LangGraph agent for SalesCo analytics."""

import json
from decimal import Decimal

from langchain_core.tools import tool
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger

import tools
from prompts import AGENT_SYSTEM_PROMPT

logger.add("logs/graph.log", rotation="10 MB", level="DEBUG")

MAX_SQL_REPAIR_ATTEMPTS = 2
MAX_AGENT_RETRIES = 2


class QueryState(MessagesState):
    """Conversation messages plus the latest structured result for this turn."""
    sql: str | None
    results: list[dict]
    error: str | None
    analysis: str | None


def _json_default(value):
    """json.dumps fallback for DB types it can't serialize natively (Decimal, date, etc.)."""
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


@tool
def query_salesco_database(question: str) -> str:
    """Answer a SalesCo data question by safely generating and running PostgreSQL."""
    sql, error = tools.generate_sql(question)
    if error:
        return json.dumps({"error": error})

    results, error = tools.execute_sql(sql)
    attempts = 0
    while error and attempts < MAX_SQL_REPAIR_ATTEMPTS:
        repaired_sql, repair_error = tools.repair_sql(question, sql, error)
        if repair_error:
            error = repair_error
            break
        sql = repaired_sql
        results, error = tools.execute_sql(sql)
        attempts += 1

    payload = {
        "sql": sql,
        "results": results or [],
        "row_count": len(results or []),
        "error": error,
    }
    # Query rows can contain Decimal/date values that aren't JSON-serializable by
    # default; returning a plain dict here would make ToolNode fall back to Python's
    # str() repr (single-quoted, non-JSON) for the ToolMessage content, which
    # finalize_response can't parse. Serializing explicitly keeps it valid JSON.
    return json.dumps(payload, default=_json_default)


agent_model = tools.llm.bind_tools([query_salesco_database])


def call_agent(state: QueryState) -> dict:
    messages = [SystemMessage(content=AGENT_SYSTEM_PROMPT), *state["messages"]]

    response = None
    last_error = None
    for attempt in range(1, MAX_AGENT_RETRIES + 2):
        try:
            response = agent_model.invoke(messages)
            break
        except Exception as e:
            last_error = e
            logger.warning("agent tool-call attempt {n} failed: {e}", n=attempt, e=str(e))
            messages = messages + [
                HumanMessage(
                    content=(
                        "Your last response failed because the tool call was malformed. "
                        "Call query_salesco_database with a single JSON `question` argument "
                        "containing a plain-language question — not SQL, and not wrapped in "
                        "any markup."
                    )
                )
            ]

    if response is None:
        logger.error("agent gave up after {n} attempts: {e}", n=MAX_AGENT_RETRIES + 1, e=str(last_error))
        response = AIMessage(
            content="I couldn't process that question right now. Please try rephrasing it or ask again."
        )
    elif not isinstance(response, AIMessage):
        response = AIMessage(content=str(response.content))

    return {"messages": [response]}


def finalize_response(state: QueryState) -> dict:
    messages = state["messages"]
    turn_start = next(
        (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
        0,
    )
    turn_messages = messages[turn_start:]

    analysis = next(
        (
            str(message.content)
            for message in reversed(turn_messages)
            if isinstance(message, AIMessage) and not message.tool_calls
        ),
        None,
    )

    for message in reversed(turn_messages):
        if isinstance(message, ToolMessage):
            try:
                payload = json.loads(str(message.content))
            except json.JSONDecodeError:
                return {
                    "sql": None,
                    "results": [],
                    "error": "The database tool returned an unreadable response.",
                    "analysis": analysis,
                }
            return {
                "sql": payload.get("sql"),
                "results": payload.get("results") or [],
                "error": payload.get("error"),
                "analysis": analysis,
            }

    # No tool call this turn (greeting, off-topic question, etc.) — not an error.
    return {"sql": None, "results": [], "error": None, "analysis": analysis}


def build_query_graph():
    workflow = StateGraph(QueryState)
    workflow.add_node("agent", call_agent)
    workflow.add_node(
        "tools", ToolNode([query_salesco_database], handle_tool_errors=True)
    )
    workflow.add_node("finalize", finalize_response)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": "finalize"},
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("finalize", END)

    # InMemorySaver is short-term, per-thread memory for the running API process.
    return workflow.compile(checkpointer=InMemorySaver())


query_graph = build_query_graph()
