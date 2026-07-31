# database.py

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from loguru import logger
import os

load_dotenv()

logger.add("logs/database.log", rotation="10 MB", level="DEBUG")


def get_connection():
    logger.debug("connecting to postgres...")
    conn = psycopg2.connect(
        host=os.getenv("PGSQL_DATABASE_HOST"),
        dbname=os.getenv("PGSQL_DATABASE_NAME"),
        user=os.getenv("PGSQL_DATABASE_USER"),
        password=os.getenv("PGSQL_DATABASE_PASS"),
        port=os.getenv("PGSQL_DATABASE_PORT"),
    )
    logger.success("connected to: {db}", db=os.getenv("PGSQL_DATABASE_NAME"))
    return conn


def run_query(query: str):
    # we are using logs to make sure the information being provided is accurate
    logger.debug("SQL received: {q}", q=query)
    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            results = cur.fetchall()
            rows = [dict(row) for row in results]
            # we are using logs to make sure the information being provided is accurate
            logger.success("query done — {n} rows", n=len(rows))
            return rows
    except Exception as e:
        logger.error("query failed: {e}", e=str(e))
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logger.info("testing database connection...")

    conn = get_connection()
    logger.info("status: {s}", s=conn.status == psycopg2.extensions.STATUS_READY)
    conn.close()

    # test basic query
    rows = run_query("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    for row in rows:
        print(row['table_name'])

    # check row counts
    for table in ["employees", "customers", "products", "orders", "order_items", "shipments"]:
        count = run_query(f"SELECT COUNT(*) as count FROM {table};")
        logger.info("{t}: {c} rows", t=table, c=count[0]['count'])

    # quick business query to see if joins work
    rows = run_query("""
        SELECT c.company_name, COUNT(o.order_id) as total_orders
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        GROUP BY c.company_name
        ORDER BY total_orders DESC
        LIMIT 5;
    """)
    for row in rows:
        print(row)