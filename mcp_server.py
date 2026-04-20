import sqlite3
import json
import sqlglot
from sqlglot import errors
from mcp.server.fastmcp import FastMCP


DB_PATH = "electronics_store.db"

mcp = FastMCP("electronics-store")


def _query(sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@mcp.tool()
def run_sql(query: str) -> str:
    """
    Execute a read-only SQL SELECT query against the electronics store SQLite database.
    Use this to answer any question about products, categories, customers, orders, or order_items.

    Schema:
    - categories(id, name)
    - products(id, name, category_id, price, stock)
    - customers(id, name, email, city, signup_date)
    - orders(id, customer_id, order_date, total, status)
    - order_items(id, order_id, product_id, quantity, unit_price)
    """
    query = query.strip().rstrip(";")
    if not query.upper().startswith("SELECT"):
        return "Error: only SELECT queries are allowed."

    try:
        # Syntactic validation using the sqlite dialect
        sqlglot.transpile(query, read="sqlite")
    except errors.ParseError as e:
        return f"SQL Syntax Error: {str(e)}. Please correct the query and try again."

    try:
        rows = _query(query)
        if not rows:
            return "Query returned no results."
        return json.dumps(rows, indent=2)
    except Exception as e:
        return f"SQL Error: {e}"


@mcp.tool()
def get_schema() -> str:
    """Return the full database schema with table definitions and row counts."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    parts = []
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = ", ".join(f"{c[1]} {c[2]}" for c in cur.fetchall())
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        parts.append(f"{t}({cols})  -- {count} rows")
    conn.close()
    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run(transport="stdio")
