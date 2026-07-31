# SalesCo Database Q&A Chatbot

Ask questions about a sales database in plain English, and get back the answer, the SQL that was run, a data table, and a chart, all in a simple chat interface.

## What this project does

You type a question like "Which sales rep generated the most revenue?" and the chatbot:
1. Turns your question into a real PostgreSQL query
2. Runs it safely (read-only, no risk of changing your data)
3. Explains the results in plain English
4. Shows a chart if the data is worth visualizing
5. Remembers your past conversations, even after closing the browser or restarting the app

## How it works (the big picture)

- **Streamlit** (`main.py`) — the chat interface you actually see and use
- **FastAPI** (`app.py`) — the backend server that receives your question and coordinates everything
- **LangGraph** (`graph.py`) — the AI agent that decides when to query the database and how to respond
- **Groq LLM** (`tools.py`) — generates the SQL, decides if a chart is worth showing, and writes short conversation titles
- **PostgreSQL** — where your actual sales data lives
- **MongoDB** (`chat_history.py`) — stores every conversation so it's never lost

## Before you start: things you need installed

- Python 3.10+
- PostgreSQL, running locally, with the sample database loaded
- MongoDB, running locally
- A free Groq API key (for the AI): https://console.groq.com

## Setup (do this once)

### 1. Install Python packages
```bash
pip install -r requirements.txt --break-system-packages
```

### 2. Set up your environment variables
Copy the example file and fill in your real values:
```bash
cp .env.example .env
```
Then open `.env` in any text editor and fill in:
- Your Postgres username, password, host, and database name
- Your MongoDB connection string (usually `mongodb://localhost:27017` if running locally)
- Your Groq API key

**Never share your `.env` file or commit it to GitHub — it has real passwords and API keys in it.**

### 3. Load the sample database
```bash
psql -U your_postgres_user -d your_database_name -f salesco_demo.sql
```
This creates all the tables (employees, customers, products, orders, etc.) and fills them with sample data.

## Running the app (do this every time)

You need **3 things running at the same time**, each in its own terminal tab.

### Terminal 1 — start MongoDB
```bash
mongod --dbpath ~/mongodb-data
```
Wait until you see `Waiting for connections` in the log.

### Terminal 2 — start the backend
```bash
uvicorn app:app --reload --port 8000
```
Wait until you see `connected to mongodb`.

### Terminal 3 — start the chat interface
```bash
streamlit run main.py
```
This should automatically open your browser to `http://localhost:8501`.

**Start them in this order** — Mongo first, then the backend, then Streamlit — since each one depends on the one before it already running.

## Using the app

- Type a question, or click one of the example question buttons
- Your conversation is saved automatically — refreshing the page won't lose it
- Click **+ New chat** in the sidebar to start a fresh conversation
- Click any past conversation in the sidebar to reopen it
- Click the 🗑 icon next to a conversation to delete it

## Project files

| File | What it does |
|---|---|
| `main.py` | The Streamlit chat interface |
| `app.py` | The FastAPI backend and its API endpoints |
| `graph.py` | The LangGraph agent that decides when to query the database |
| `tools.py` | Generates SQL, runs it safely, decides on charts, writes titles |
| `prompts.py` | The instructions given to the AI (schema, rules, safety guardrails) |
| `database.py` | Connects to PostgreSQL and runs queries |
| `chat_history.py` | Saves and loads conversations from MongoDB |
| `salesco_demo.sql` | Sample database schema and data for testing |
| `Salesco Schema Reference.md` | Reference doc describing the database tables |

## Safety notes

This project only allows **read only** questions — it cannot delete, change, or add data, even if you ask it to. Every generated SQL query is checked before it runs, and anything that looks like it could modify data is automatically blocked.

## Troubleshooting

- **"Could not reach the backend"** in Streamlit → make sure `uvicorn` (Terminal 2) is actually running
- **MongoDB connection errors** → make sure `mongod` (Terminal 1) is running first
- **A question fails or gives a weird answer** → check the `logs/` folder for detailed error messages
EOF
