# app.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
from langchain_core.messages import HumanMessage
from graph import query_graph
import tools
import chat_history

logger.add("logs/app.log", rotation="10 MB", level="DEBUG")

app = FastAPI(title="SalesCo Text-to-SQL API", version="1.0")



class QueryRequest(BaseModel):
    question: str
    thread_id: str


class ChartSpec(BaseModel):
    chart_type: str
    x: str
    y: str
    title: str


class QueryResponse(BaseModel):
    question: str
    sql: str | None = None
    results: list[dict] = []
    row_count: int = 0
    chart_spec: ChartSpec | None = None
    analysis: str | None = None


@app.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest):
    logger.info("question received: {q}", q=payload.question)

    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # === CHANGED: generate a title only on a thread's very first turn ===
    is_new_thread = not chat_history.thread_exists(payload.thread_id)
    thread_title = tools.generate_thread_title(payload.question) if is_new_thread else None
    # === END CHANGED ===

    config = {"configurable": {"thread_id": payload.thread_id}}
    state = await query_graph.ainvoke(
        {"messages": [HumanMessage(content=payload.question)]},
        config,
    )

    analysis = state.get("analysis")

    if error := state.get("error"):
        logger.error("database tool failed: {e}", e=error)
        chat_history.save_turn(
            thread_id=payload.thread_id,
            question=payload.question,
            analysis=analysis,
            error=error,
            title=thread_title,  # === CHANGED ===
        )
        raise HTTPException(status_code=400, detail=error)

    sql = state.get("sql")
    if sql is None:
        # The agent answered directly (greeting, off-topic question, etc.) without
        # calling the database tool — this is expected behavior, not an error.
        logger.info("query graph completed with no tool call")
        chat_history.save_turn(
            thread_id=payload.thread_id,
            question=payload.question,
            analysis=analysis,
            title=thread_title,  # === CHANGED ===
        )
        return QueryResponse(question=payload.question, analysis=analysis)

    results = state.get("results") or []
    logger.success("query graph completed with {n} rows", n=len(results))

    chart_spec = None
    if tools.is_chart_candidate(results):
        chart_spec = tools.decide_chart_spec(results, payload.question)

    chat_history.save_turn(
        thread_id=payload.thread_id,
        question=payload.question,
        sql=sql,
        results=results,
        row_count=len(results),
        analysis=analysis,
        chart_spec=chart_spec,
        title=thread_title,  # === CHANGED ===
    )

    return QueryResponse(
        question=payload.question,
        sql=sql,
        results=results,
        row_count=len(results),
        chart_spec=chart_spec,
        analysis=analysis,
    )


@app.get("/threads")
async def threads():
    return {"threads": chat_history.list_threads()}


@app.get("/history/{thread_id}")
async def history(thread_id: str):
    return {"thread_id": thread_id, "history": chat_history.get_history(thread_id)}


@app.delete("/history/{thread_id}")
async def delete_history_endpoint(thread_id: str):
    deleted_count = chat_history.delete_history(thread_id)
    return {"thread_id": thread_id, "deleted_count": deleted_count}


@app.get("/health")
async def health():
    return {"status": "ok"}