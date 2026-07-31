# chat_history.py

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from loguru import logger
from pymongo import MongoClient

load_dotenv()

logger.add("logs/chat_history.log", rotation="10 MB", level="DEBUG")

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

logger.debug("connecting to mongodb...")
_client = MongoClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
_chat_history_collection = _db["chat_history"]
logger.success("connected to mongodb: {db}", db=MONGO_DB_NAME)


def get_collection():
    """Return the chat_history collection used for all reads/writes in this module."""
    return _chat_history_collection


def thread_exists(thread_id: str) -> bool:
    """True if this thread already has at least one saved turn."""
    collection = get_collection()
    return collection.count_documents({"thread_id": thread_id}, limit=1) > 0


def save_turn(
    thread_id: str,
    question: str,
    sql: str | None = None,
    results: list[dict] | None = None,
    row_count: int = 0,
    analysis: str | None = None,
    error: str | None = None,
    chart_spec: dict | None = None,
    title: str | None = None,
) -> None:
    """Insert one question/answer turn. One document per turn — a conversation
    is just every document that shares a thread_id, not a single document
    with an array (see list_threads for why that matters for aggregation).

    `title` should only be passed on a thread's first turn (see app.py) — it's
    the short, LLM-generated label shown in the sidebar.
    """
    collection = get_collection()

    document = {
        "thread_id": thread_id,
        "question": question,
        "sql": sql,
        "results": results or [],
        "row_count": row_count,
        "analysis": analysis,
        "error": error,
        "chart_spec": chart_spec,
        "title": title,
        "created_at": datetime.now(timezone.utc),
    }

    result = collection.insert_one(document)
    logger.success(
        "turn saved — thread_id={t} inserted_id={i}",
        t=thread_id,
        i=result.inserted_id,
    )


def get_history(thread_id: str) -> list[dict]:
    """All turns for one thread_id, oldest first — the full back-and-forth
    of a single conversation.
    """
    collection = get_collection()

    cursor = collection.find({"thread_id": thread_id}).sort("created_at", 1)

    history = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])  # ObjectId isn't JSON-serializable
        doc["created_at"] = doc["created_at"].isoformat()  # neither is datetime
        history.append(doc)

    logger.info(
        "get_history returned {n} turns for thread_id={t}",
        n=len(history),
        t=thread_id,
    )
    return history


def list_threads() -> list[dict]:
    """One summary row per conversation (thread_id), most recently active first.

    Turn documents are grouped in the database via aggregation pipeline
    rather than pulled into Python and grouped there.
    """
    collection = get_collection()

    pipeline = [
        {"$sort": {"created_at": 1}},
        {
            "$group": {
                "_id": "$thread_id",
                "first_question": {"$first": "$question"},
                "title": {"$first": "$title"},
                "last_activity": {"$last": "$created_at"},
                "turn_count": {"$sum": 1},
            }
        },
        {"$sort": {"last_activity": -1}},
    ]

    results = list(collection.aggregate(pipeline))

    threads = []
    for r in results:
        threads.append(
            {
                "thread_id": r["_id"],
                # prefer the generated title, fall back to the raw first question
                "first_question": r.get("title") or r["first_question"],
                "last_activity": r["last_activity"].isoformat(),
                "turn_count": r["turn_count"],
            }
        )

    logger.info("list_threads returned {n} conversations", n=len(threads))
    return threads


def delete_history(thread_id: str) -> int:
    """Delete every turn belonging to one thread_id. Returns how many
    documents were removed.
    """
    collection = get_collection()
    result = collection.delete_many({"thread_id": thread_id})
    logger.warning(
        "delete_history removed {n} turns for thread_id={t}",
        n=result.deleted_count,
        t=thread_id,
    )
    return result.deleted_count


if __name__ == "__main__":
    logger.info("testing mongodb connection...")

    _client.admin.command("ping")
    logger.success("ping ok — mongodb is reachable")

    collection = get_collection()
    logger.info("using collection: {c}", c=collection.full_name)
    logger.info("existing document count: {n}", n=collection.count_documents({}))