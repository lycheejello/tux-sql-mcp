"""
Connects to acu-inventory via Azure AD token auth and prints the full schema.
Output is intended to be reviewed and used to populate schema.md.

Usage:
    az login  # if not already authenticated
    python scripts/explore_schema.py
"""

import os
import struct
import subprocess
import pyodbc

SERVER = "tuxton-acu-sql.database.windows.net"
DATABASE = "acu-inventory"


def get_token() -> bytes:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://database.windows.net/", "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, check=True
    )
    token = result.stdout.strip()
    token_bytes = token.encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def connect():
    token_struct = get_token()
    return pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SERVER};"
        f"Database={DATABASE};"
        "Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={1256: token_struct}
    )


def main():
    conn = connect()
    cur = conn.cursor()

    # Tables and views
    cur.execute("""
        SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        ORDER BY TABLE_TYPE, TABLE_NAME
    """)
    rows = cur.fetchall()
    print("=== TABLES / VIEWS ===")
    for r in rows:
        print(f"  {r[2]:6s}  {r[0]}.{r[1]}")

    # Columns
    print("\n=== COLUMNS ===")
    cur.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """)
    current = None
    for r in cur.fetchall():
        if r[0] != current:
            print(f"\n  [{r[0]}]")
            current = r[0]
        length = f"({r[3]})" if r[3] else ""
        nullable = "" if r[4] == "YES" else " NOT NULL"
        print(f"    {r[1]:45s} {r[2]}{length}{nullable}")

    # Row counts
    print("\n=== ROW COUNTS ===")
    cur.execute("""
        SELECT t.NAME, p.rows
        FROM sys.tables t
        JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0,1)
        ORDER BY p.rows DESC
    """)
    for r in cur.fetchall():
        print(f"  {r[0]:45s} {r[1]:>10,} rows")


if __name__ == "__main__":
    main()
