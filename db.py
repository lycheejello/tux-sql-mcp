"""
Azure SQL connection using Azure AD token auth.

Supports two auth modes (set SQL_AUTH env var):
  az_cli          — uses local `az login` credentials (dev default)
  managed_identity — uses Azure Managed Identity (prod/CI)

Token is refreshed on each call to get_connection() so there is no
stale-token risk across long-running server sessions.
"""

import os
import struct
import pyodbc
from azure.identity import AzureCliCredential, ManagedIdentityCredential

SQL_SERVER   = os.getenv("SQL_SERVER",   "tuxton-acu-sql.database.windows.net")
SQL_DATABASE = os.getenv("SQL_DATABASE", "acu-inventory")
SQL_AUTH     = os.getenv("SQL_AUTH",     "az_cli")

_SCOPE = "https://database.windows.net/.default"


def _get_token_struct() -> bytes:
    if SQL_AUTH == "managed_identity":
        cred = ManagedIdentityCredential()
    else:
        cred = AzureCliCredential()

    token = cred.get_token(_SCOPE).token
    token_bytes = token.encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def get_connection() -> pyodbc.Connection:
    token_struct = _get_token_struct()
    return pyodbc.connect(
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SQL_SERVER};"
        f"Database={SQL_DATABASE};"
        "Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={1256: token_struct}
    )


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a SELECT and return rows as a list of dicts."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
