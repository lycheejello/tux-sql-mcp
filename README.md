# tux-sql-mcp

MCP server that exposes Tuxton's Acumatica-sourced Azure SQL data for financial modeling and EDI tracking. Designed for use with Claude Desktop and other MCP clients.

## Prerequisites

- **Python 3.12+**
- **ODBC Driver 18 for SQL Server** — [install guide](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- **Azure CLI** (for local dev auth) — `az login` must have access to the database

## Setup

```bash
# Clone and enter the repo
git clone https://github.com/lycheejello/tux-sql-mcp.git
cd tux-sql-mcp

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env if you need to change defaults
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `SQL_SERVER` | `tuxton-acu-sql.database.windows.net` | Azure SQL server hostname |
| `SQL_DATABASE` | `acu-inventory` | Database name |
| `SQL_AUTH` | `az_cli` | Auth mode: `az_cli` (dev) or `managed_identity` (prod/CI) |

Authentication uses Azure AD tokens — no passwords stored. In `az_cli` mode, run `az login` before starting the server.

## Running

```bash
# stdio transport (for Claude Desktop / MCP clients)
python server.py

# SSE transport (for network clients)
python server.py --transport sse
```

## Claude Desktop configuration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tux-sql-mcp": {
      "command": "python",
      "args": ["/absolute/path/to/tux-sql-mcp/server.py"],
      "env": {
        "SQL_AUTH": "az_cli"
      }
    }
  }
}
```

## Tools

### Income Statement

| Tool | Description |
|---|---|
| `get_revenue_by_period` | Monthly revenue by ItemClass and FinancialPeriod |
| `get_cogs_by_period` | Monthly COGS and gross margin by ItemClass |
| `get_sales_ledger` | Flexible filtered query on invoice lines (up to 2000 rows) |

### Balance Sheet

| Tool | Description |
|---|---|
| `get_inventory_snapshot` | Current inventory value by ItemClass (QtyOnHand x LastCost) |
| `get_inventory_items` | Item-level inventory with SKU detail |
| `get_open_pos` | Open PO lines with promised delivery dates |

### Customer & Concentration

| Tool | Description |
|---|---|
| `get_customer_revenue` | Revenue by customer with % of total |

### EDI Tracking

| Tool | Description |
|---|---|
| `get_edi_order_status` | Full lifecycle for a customer PO (850/855/856/810 + 997 acks) |
| `get_edi_order_status_batch` | Same as above but for multiple POs in one call |
| `get_edi_unacked` | Outbound docs missing 997 acknowledgment |
| `get_edi_unacked_aging` | Unacked docs with business-hour aging and overdue flags |
| `get_edi_rejected` | 997 rejections with error detail |
| `get_edi_partner_activity` | Recent EDI activity for a trading partner |
| `get_edi_summary` | Summary counts by partner, doc type, day/week |

## Database

Connects to Azure SQL via ODBC with Azure AD token auth. Key tables:

- `bi_sales_ledger` — Invoice lines with revenue and COGS by ItemClass
- `bi_inventory_items` — SKU x warehouse inventory with costs
- `bi_open_po_lines` — Open purchase orders with promised dates
- `bi_customers` — Customer master
- `edi_documents` — EDI transaction sets (850/855/856/810/997)
- `edi_acknowledgments` — 997 functional acknowledgment correlation

### EDI file archive

Raw EDI files are archived in Azure Blob Storage at:

```
https://tuxtonedisync.blob.core.windows.net/edi-sync/archive/
```

The `edi_documents.archive_path` column contains the blob path for each document. To pull a file locally:

```bash
az storage blob download \
  --account-name tuxtonedisync \
  --container-name edi-sync \
  --name "archive/<path>" \
  --file ./output.edi \
  --auth-mode login
```

See [`schema.md`](schema.md) for full schema documentation.
