# main.py

import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import uuid

API_URL = "http://localhost:8000"


def build_chart(chart_spec, results):
    """Render the backend's chart_spec locally; no LLM call needed here."""
    if not chart_spec or not results:
        return None

    df = pd.DataFrame(results)
    x_col, y_col = chart_spec["x"], chart_spec["y"]
    if x_col not in df.columns or y_col not in df.columns:
        return None

    chart_type = chart_spec["chart_type"]
    title = chart_spec["title"]

    if chart_type == "line":
        return px.line(df, x=x_col, y=y_col, title=title)
    if chart_type == "pie":
        return px.pie(df, names=x_col, values=y_col, title=title)
    if chart_type == "scatter":
        return px.scatter(df, x=x_col, y=y_col, title=title)
    return px.bar(df, x=x_col, y=y_col, title=title)


@st.cache_data(ttl=5)
def fetch_threads():
    """Cached fetch of the sidebar's conversation list — avoids re-fetching
    /threads on every rerun. Call fetch_threads.clear() right after an action
    that changes the data (new query, delete) so the sidebar doesn't stay stale.
    """
    try:
        res = requests.get(f"{API_URL}/threads", timeout=30)
        return res.json().get("threads", []) if res.status_code == 200 else []
    except requests.RequestException:
        return []


def load_history_into_session(thread_id):
    """Fetch this thread's saved turns from the backend and rebuild
    st.session_state.history from them, so a refresh/switch doesn't start blank.
    """
    try:
        res = requests.get(f"{API_URL}/history/{thread_id}", timeout=30)
        if res.status_code != 200:
            st.session_state.history = []
            return

        turns = res.json().get("history", [])
        history = []
        for turn in turns:
            chart_spec = turn.get("chart_spec")
            results = turn.get("results") or []
            history.append(
                {
                    "question": turn.get("question"),
                    "sql": turn.get("sql"),
                    "results": results,
                    "row_count": turn.get("row_count", 0),
                    "analysis": turn.get("analysis"),
                    "fig": build_chart(chart_spec, results),
                }
            )
        st.session_state.history = history
    except requests.RequestException:
        st.session_state.history = []


def start_new_chat():
    new_id = str(uuid.uuid4())
    st.session_state.thread_id = new_id
    st.session_state.history = []
    st.session_state.used_example_questions = set()
    st.query_params["thread_id"] = new_id
    st.rerun()


def switch_thread(thread_id):
    st.session_state.thread_id = thread_id
    st.query_params["thread_id"] = thread_id
    st.session_state.pop("history", None)  # forces reload with spinner below
    st.rerun()


def delete_thread(thread_id):
    """Delete a conversation from the backend, refresh the cached thread
    list, and fall back to a new chat if the deleted thread was active.
    """
    try:
        requests.delete(f"{API_URL}/history/{thread_id}", timeout=30)
    except requests.RequestException:
        pass
    fetch_threads.clear()

    if thread_id == st.session_state.thread_id:
        start_new_chat()
    else:
        st.rerun()


st.set_page_config(page_title="SalesCo Q&A", layout="wide")
st.title("📊 SalesCo Database Q&A")
st.caption("Ask questions about the SalesCo database in plain English.")

if "thread_id" not in st.session_state:
    existing_thread_id = st.query_params.get("thread_id")
    if existing_thread_id:
        st.session_state.thread_id = existing_thread_id
    else:
        st.session_state.thread_id = str(uuid.uuid4())
        st.query_params["thread_id"] = st.session_state.thread_id

if "history" not in st.session_state:
    with st.spinner("Loading conversation..."):
        load_history_into_session(st.session_state.thread_id)

if "used_example_questions" not in st.session_state:
    st.session_state.used_example_questions = set()

with st.sidebar:
    st.header("Conversations")

    if st.button("+ New chat", use_container_width=True):
        start_new_chat()

    st.divider()

    threads = fetch_threads()

    for t in threads:
        label = t["first_question"] or "(untitled)"
        if len(label) > 40:
            label = label[:40] + "..."
        is_active = t["thread_id"] == st.session_state.thread_id
        button_label = f"{'▶ ' if is_active else ''}{label}"

        row_col, delete_col = st.columns([5, 1])
        with row_col:
            if st.button(button_label, key=f"thread_{t['thread_id']}", use_container_width=True):
                if not is_active:
                    switch_thread(t["thread_id"])
        with delete_col:
            if st.button("🗑", key=f"delete_{t['thread_id']}", use_container_width=True):
                delete_thread(t["thread_id"])

st.markdown("**Try asking:**")

EXAMPLE_QUESTIONS = [
    "Total revenue by product category",
    "Top 5 customers by number of orders",
    "Which sales rep generated the most revenue?",
    "Average delivery time by carrier",
]

remaining_questions = [
    q for q in EXAMPLE_QUESTIONS if q not in st.session_state.used_example_questions
]

if remaining_questions:
    cols = st.columns(len(remaining_questions))
    for col, q in zip(cols, remaining_questions):
        with col:
            if st.button(q, use_container_width=True):
                st.session_state.used_example_questions.add(q)
                st.session_state.pending_question = q
                st.rerun()

st.divider()

for entry in st.session_state.history:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        if entry.get("sql"):
            st.caption(f"SQL: `{entry['sql']}`")
        if entry.get("analysis"):
            st.markdown(entry["analysis"])
        if entry.get("results"):
            st.dataframe(pd.DataFrame(entry["results"]), use_container_width=True)
            st.caption(f"{entry['row_count']} rows returned")
        elif entry.get("sql"):
            st.info("Query returned no results.")
        if entry.get("fig"):
            st.plotly_chart(entry["fig"], use_container_width=True)

question = st.chat_input("Ask a question about the SalesCo data...")

if st.session_state.get("pending_question"):
    question = st.session_state.pop("pending_question")

if question in EXAMPLE_QUESTIONS:
    st.session_state.used_example_questions.add(question)

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                res = requests.post(
                    f"{API_URL}/query",
                    json={"question": question, "thread_id": st.session_state.thread_id},
                    timeout=30,
                )

                if res.status_code != 200:
                    error_detail = res.json().get("detail", "Something went wrong.")
                    st.error(error_detail)
                    st.session_state.history.append({
                        "question": question,
                        "sql": None,
                        "results": [],
                        "row_count": 0,
                        "fig": None,
                    })
                else:
                    data = res.json()
                    sql = data.get("sql")
                    results = data["results"]
                    row_count = data["row_count"]
                    analysis = data.get("analysis")
                    chart_spec = data.get("chart_spec")

                    if sql:
                        st.caption(f"SQL: `{sql}`")
                    if analysis:
                        st.markdown(analysis)

                    if results:
                        st.dataframe(pd.DataFrame(results), use_container_width=True)
                        st.caption(f"{row_count} rows returned")
                    elif sql:
                        st.info("Query returned no results.")

                    fig = build_chart(chart_spec, results)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)

                    st.session_state.history.append({
                        "question": question,
                        "sql": sql,
                        "results": results,
                        "row_count": row_count,
                        "analysis": analysis,
                        "fig": fig,
                    })

                    fetch_threads.clear()
                    st.rerun()

            except requests.RequestException as e:
                st.error(f"Could not reach the backend: {e}")