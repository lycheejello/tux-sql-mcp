"""
tux-sql-mcp — MCP server exposing acu-inventory Azure SQL data
for the Tuxton Finance 3-statement financial model and EDI tracking.

Tools
-----
get_revenue_by_period       Monthly revenue by item class (IS)
get_cogs_by_period          Monthly COGS by item class (IS)
get_inventory_snapshot      Current inventory value by item class (BS / DIO)
get_inventory_items         Item-level inventory with SKU, qty, and value
get_open_pos                Open PO lines with promised dates
get_customer_revenue        Revenue by customer for concentration analysis
get_sales_ledger            Flexible filtered query on bi_sales_ledger
get_edi_order_status        EDI order lifecycle for a customer PO
get_edi_unacked             Outbound EDI docs missing 997 acknowledgment
get_edi_partner_activity    Recent EDI activity for a partner
get_edi_summary             Summary counts by partner, doc type, ack status
get_edi_unacked_aging       Unacked docs with biz-hour aging and overdue flags

Run
---
    python server.py                  # stdio (for Claude Desktop / MCP clients)
    python server.py --transport sse  # SSE transport
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from dotenv import load_dotenv  # type: ignore[import-untyped]

load_dotenv()

from mcp.server.fastmcp import FastMCP
import db

mcp = FastMCP(
    "tux-sql-mcp",
    instructions=(
        "Provides financial data from Tuxton's Acumatica-sourced Azure SQL database. "
        "All monetary values are in USD. Revenue and COGS come from bi_sales_ledger; "
        "inventory balances from bi_inventory_items. "
        "Use FinancialPeriod (format YYYYMM) or InvoiceDate range for period filtering. "
        "Also provides EDI document tracking — use get_edi_order_status to check "
        "order lifecycle (850/855/856/810 + 997 acks), get_edi_unacked for missing "
        "acknowledgments, and get_edi_partner_activity for recent partner activity."
    ),
)


# ---------------------------------------------------------------------------
# Income Statement tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_revenue_by_period(
    year: int,
    month_start: Optional[int] = None,
    month_end: Optional[int] = None,
) -> list[dict]:
    """
    Monthly revenue (ExtAmount) grouped by ItemClass and FinancialPeriod.

    Args:
        year:        Fiscal year (e.g. 2024)
        month_start: First month to include, 1–12. Defaults to 1.
        month_end:   Last month to include, 1–12. Defaults to 12.

    Returns list of {FinancialPeriod, ItemClass, Revenue, Quantity, LineCount}.
    """
    m_start = month_start or 1
    m_end   = month_end   or 12
    period_start = f"{year}{m_start:02d}"
    period_end   = f"{year}{m_end:02d}"

    return db.query(
        """
        SELECT
            FinancialPeriod,
            ItemClass,
            SUM(ExtAmount)  AS Revenue,
            SUM(Quantity)   AS Quantity,
            COUNT(*)        AS LineCount
        FROM dbo.bi_sales_ledger
        WHERE TranType = 'INV'
          AND FinancialPeriod BETWEEN ? AND ?
        GROUP BY FinancialPeriod, ItemClass
        ORDER BY FinancialPeriod, ItemClass
        """,
        (period_start, period_end),
    )


@mcp.tool()
def get_cogs_by_period(
    year: int,
    month_start: Optional[int] = None,
    month_end: Optional[int] = None,
) -> list[dict]:
    """
    Monthly COGS (ExtCost) and gross profit grouped by ItemClass and FinancialPeriod.

    Args:
        year:        Fiscal year (e.g. 2024)
        month_start: First month to include, 1–12. Defaults to 1.
        month_end:   Last month to include, 1–12. Defaults to 12.

    Returns list of {FinancialPeriod, ItemClass, Revenue, COGS, GrossProfit, GrossMarginPct}.
    """
    m_start = month_start or 1
    m_end   = month_end   or 12
    period_start = f"{year}{m_start:02d}"
    period_end   = f"{year}{m_end:02d}"

    return db.query(
        """
        SELECT
            FinancialPeriod,
            ItemClass,
            SUM(ExtAmount)                                          AS Revenue,
            SUM(ExtCost)                                            AS COGS,
            SUM(ExtProfit)                                          AS GrossProfit,
            CASE WHEN SUM(ExtAmount) = 0 THEN NULL
                 ELSE ROUND(SUM(ExtProfit) / SUM(ExtAmount) * 100, 2)
            END                                                     AS GrossMarginPct
        FROM dbo.bi_sales_ledger
        WHERE TranType = 'INV'
          AND FinancialPeriod BETWEEN ? AND ?
        GROUP BY FinancialPeriod, ItemClass
        ORDER BY FinancialPeriod, ItemClass
        """,
        (period_start, period_end),
    )


# ---------------------------------------------------------------------------
# Balance Sheet tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_inventory_snapshot(warehouse_id: Optional[str] = None) -> list[dict]:
    """
    Current inventory value (QtyOnHand × LastCost) grouped by ItemClass.
    Used for DIO calculation in the balance sheet.

    Args:
        warehouse_id: Filter to a specific warehouse. Omit for all warehouses.

    Returns list of {ItemClass, QtyOnHand, InventoryValue, ItemCount}.
    """
    if warehouse_id:
        return db.query(
            """
            SELECT
                ItemClass,
                SUM(QtyOnHand)              AS QtyOnHand,
                SUM(QtyOnHand * LastCost)   AS InventoryValue,
                COUNT(DISTINCT InventoryID) AS ItemCount
            FROM dbo.bi_inventory_items
            WHERE WarehouseID = ?
              AND ItemStatus = 'Active'
              AND QtyOnHand > 0
            GROUP BY ItemClass
            ORDER BY InventoryValue DESC
            """,
            (warehouse_id,),
        )
    return db.query(
        """
        SELECT
            ItemClass,
            SUM(QtyOnHand)              AS QtyOnHand,
            SUM(QtyOnHand * LastCost)   AS InventoryValue,
            COUNT(DISTINCT InventoryID) AS ItemCount
        FROM dbo.bi_inventory_items
        WHERE ItemStatus = 'Active'
          AND QtyOnHand > 0
        GROUP BY ItemClass
        ORDER BY InventoryValue DESC
        """
    )


# ---------------------------------------------------------------------------
# Item-level inventory tool
# ---------------------------------------------------------------------------

@mcp.tool()
def get_inventory_items(
    item_class: Optional[str] = None,
    inventory_ids: Optional[list[str]] = None,
    top_n: Optional[int] = None,
) -> list[dict]:
    """
    Item-level inventory with SKU, quantity on hand, and value (QtyOnHand × LastCost).

    Args:
        item_class:    Filter to a specific ItemClass (e.g. 'CHINAWARE CUSTOM'). Omit for all.
        inventory_ids: Filter to one or more SKUs (e.g. ['IHP-020', 'VEA-102']). Omit for all.
        top_n:         Return only the top N items by InventoryValue. Omit for all.

    Returns list of {InventoryID, ItemClass, QtyOnHand, LastCost, InventoryValue}.
    """
    top = f"TOP {top_n}" if top_n else ""
    conditions = ["ItemStatus = 'Active'"]
    params: list = []

    if item_class:
        conditions.append("ItemClass = ?")
        params.append(item_class)

    if inventory_ids:
        placeholders = ",".join("?" * len(inventory_ids))
        conditions.append(f"InventoryID IN ({placeholders})")
        params.extend(inventory_ids)

    where = "WHERE " + " AND ".join(conditions)

    return db.query(
        f"""
        SELECT {top}
            InventoryID,
            ItemClass,
            QtyOnHand,
            LastCost,
            QtyOnHand * LastCost AS InventoryValue
        FROM dbo.bi_inventory_items
        {where}
        ORDER BY InventoryValue DESC
        """,
        tuple(params),
    )


# ---------------------------------------------------------------------------
# Open PO tool
# ---------------------------------------------------------------------------

@mcp.tool()
def get_open_pos(
    warehouse_id: Optional[str] = None,
    promised_before: Optional[str] = None,
) -> list[dict]:
    """
    Open purchase order lines with promised delivery dates.

    Args:
        warehouse_id:    Filter to a specific warehouse. Omit for all.
        promised_before: ISO date string (YYYY-MM-DD). Return only POs due before this date.

    Returns list of {PONbr, LineNbr, InventoryID, OrderQty, PromisedOn, WarehouseID}.
    """
    conditions = []
    params: list = []

    if warehouse_id:
        conditions.append("WarehouseID = ?")
        params.append(warehouse_id)
    if promised_before:
        conditions.append("PromisedOn < ?")
        params.append(promised_before)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return db.query(
        f"""
        SELECT PONbr, LineNbr, InventoryID, OrderQty, PromisedOn, WarehouseID
        FROM dbo.bi_open_po_lines
        {where}
        ORDER BY PromisedOn, PONbr, LineNbr
        """,
        tuple(params),
    )


# ---------------------------------------------------------------------------
# Customer / concentration tool
# ---------------------------------------------------------------------------

@mcp.tool()
def get_customer_revenue(
    year: int,
    top_n: Optional[int] = None,
) -> list[dict]:
    """
    Revenue by customer for a given year, with % of total.
    Used for customer concentration KPI (top 3 as % of revenue).

    Args:
        year:  Fiscal year (e.g. 2024)
        top_n: Return only the top N customers by revenue. Omit for all.

    Returns list of {CustomerID, CustomerName, Revenue, PctOfTotal}, sorted descending.
    """
    period_start = f"{year}01"
    period_end   = f"{year}12"

    rows = db.query(
        """
        SELECT
            s.CustomerID,
            c.CustomerName,
            SUM(s.ExtAmount)    AS Revenue
        FROM dbo.bi_sales_ledger s
        LEFT JOIN dbo.bi_customers c ON c.CustomerID = s.CustomerID
        WHERE s.TranType = 'INV'
          AND s.FinancialPeriod BETWEEN ? AND ?
        GROUP BY s.CustomerID, c.CustomerName
        ORDER BY Revenue DESC
        """,
        (period_start, period_end),
    )

    total = sum(r["Revenue"] or 0 for r in rows)
    for r in rows:
        r["PctOfTotal"] = round((r["Revenue"] or 0) / total * 100, 2) if total else None

    return rows[:top_n] if top_n else rows


# ---------------------------------------------------------------------------
# Flexible sales ledger query
# ---------------------------------------------------------------------------

@mcp.tool()
def get_sales_ledger(
    year: int,
    month_start: Optional[int] = None,
    month_end: Optional[int] = None,
    item_class: Optional[str] = None,
    customer_id: Optional[str] = None,
    tran_type: Optional[str] = "INV",
) -> list[dict]:
    """
    Filtered rows from bi_sales_ledger. Use for ad-hoc analysis.

    Args:
        year:        Fiscal year (e.g. 2024)
        month_start: First month, 1–12. Defaults to 1.
        month_end:   Last month, 1–12. Defaults to 12.
        item_class:  Filter to a specific ItemClass (e.g. 'Plates').
        customer_id: Filter to a specific CustomerID.
        tran_type:   Transaction type filter. Defaults to 'INV'. Pass None for all types.

    Returns raw ledger rows (up to 2000).
    """
    m_start = month_start or 1
    m_end   = month_end   or 12
    period_start = f"{year}{m_start:02d}"
    period_end   = f"{year}{m_end:02d}"

    conditions = ["FinancialPeriod BETWEEN ? AND ?"]
    params: list = [period_start, period_end]

    if tran_type:
        conditions.append("TranType = ?")
        params.append(tran_type)
    if item_class:
        conditions.append("ItemClass = ?")
        params.append(item_class)
    if customer_id:
        conditions.append("CustomerID = ?")
        params.append(customer_id)

    where = "WHERE " + " AND ".join(conditions)

    return db.query(
        f"""
        SELECT TOP 2000
            SalesLedgerKey, TranType, ReferenceNbr, LineNbr,
            CustomerID, CustomerName, InventoryID, ItemClass,
            InvoiceDate, FinancialPeriod,
            Quantity, UnitPrice, UnitCost,
            ExtAmount, ExtCost, ExtProfit
        FROM dbo.bi_sales_ledger
        {where}
        ORDER BY InvoiceDate DESC, ReferenceNbr, LineNbr
        """,
        tuple(params),
    )


# ---------------------------------------------------------------------------
# EDI Tracking tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_edi_order_status(customer_po: str) -> list[dict]:
    """
    Full EDI lifecycle for a customer PO: which documents exist (850/855/856/810),
    whether each was delivered, and whether a 997 acknowledgment was received.

    Args:
        customer_po: The customer's PO number (e.g. '8274768')

    Returns list of {doc_type, direction, st_control_num, filename, delivered_at,
                     created_at, ak5_status, ack_at} ordered by created_at.
    """
    return db.query(
        """
        SELECT d.doc_type, d.direction, d.partner_id,
               d.st_control_num, d.customer_po, d.sales_order,
               d.filename, d.delivered_at, d.created_at,
               a.ak5_status, a.ak5_error_code, a.created_at AS ack_at
        FROM dbo.edi_documents d
        LEFT JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        WHERE d.customer_po = ?
        ORDER BY d.created_at
        """,
        (customer_po,),
    )


@mcp.tool()
def get_edi_unacked(
    partner_id: Optional[str] = None,
    days: Optional[int] = 30,
) -> list[dict]:
    """
    Outbound EDI documents (855/856/810) that were delivered to the partner
    but have NOT received a 997 functional acknowledgment.

    Args:
        partner_id: Filter to a specific partner (e.g. 'USFDirect'). Omit for all.
        days:       Look back N days. Defaults to 30.

    Returns list of {partner_id, doc_type, customer_po, filename, delivered_at, created_at}.
    """
    conditions = [
        "d.direction = 'outbound'",
        "d.doc_type IN ('855', '856', '810')",
        "d.delivered_at IS NOT NULL",
        "a.id IS NULL",
        f"d.created_at >= DATEADD(day, -{int(days)}, SYSUTCDATETIME())",
    ]
    params: list = []

    if partner_id:
        conditions.append("d.partner_id = ?")
        params.append(partner_id)

    where = "WHERE " + " AND ".join(conditions)

    return db.query(
        f"""
        SELECT d.partner_id, d.doc_type, d.st_control_num,
               d.customer_po, d.filename, d.delivered_at, d.created_at
        FROM dbo.edi_documents d
        LEFT JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        {where}
        ORDER BY d.created_at DESC
        """,
        tuple(params),
    )


@mcp.tool()
def get_edi_rejected(
    partner_id: Optional[str] = None,
    days: Optional[int] = 30,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """
    Outbound EDI documents (855/856/810) whose 997 acknowledgment reported
    Rejected (R) or Error (E) instead of Accepted (A).

    These require investigation — the partner is saying they couldn't process
    the document. Common causes: syntax errors, missing segments, invalid data.

    Args:
        partner_id: Filter to a specific partner. Omit for all.
        days:       Look back N days. Defaults to 30. Ignored if date_from is set.
        date_from:  Start date (YYYY-MM-DD). Overrides days.
        date_to:    End date (YYYY-MM-DD). Defaults to now.

    Returns list of {partner_id, doc_type, customer_po, sales_order, filename,
                     delivered_at, ak5_status, ak5_error_code, ack_at}.
    """
    conditions = [
        "d.direction = 'outbound'",
        "d.doc_type IN ('855', '856', '810')",
        "a.ak5_status IN ('R', 'E')",
    ]
    params: list = []

    if date_from:
        conditions.append("d.created_at >= ?")
        params.append(date_from)
        if date_to:
            conditions.append("d.created_at < DATEADD(day, 1, CAST(? AS DATE))")
            params.append(date_to)
    else:
        conditions.append(f"d.created_at >= DATEADD(day, -{int(days)}, SYSUTCDATETIME())")

    if partner_id:
        conditions.append("d.partner_id = ?")
        params.append(partner_id)

    where = "WHERE " + " AND ".join(conditions)

    return db.query(
        f"""
        SELECT d.partner_id, d.doc_type, d.st_control_num,
               d.customer_po, d.sales_order, d.filename,
               d.delivered_at, d.created_at,
               a.ak5_status, a.ak5_error_code, a.created_at AS ack_at
        FROM dbo.edi_documents d
        JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        {where}
        ORDER BY a.created_at DESC
        """,
        tuple(params),
    )


@mcp.tool()
def get_edi_partner_activity(
    partner_id: str,
    days: Optional[int] = 7,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    doc_type: Optional[str] = None,
    direction: Optional[str] = None,
) -> list[dict]:
    """
    Recent EDI document activity for a partner — shows all documents
    (inbound and outbound) with delivery and acknowledgment status.

    Args:
        partner_id: Partner ID from partners.yaml (e.g. 'ClarkFoodService', 'USFDirect')
        days:       Look back N days. Defaults to 7. Ignored if date_from is set.
        date_from:  Start date (YYYY-MM-DD). Overrides days.
        date_to:    End date (YYYY-MM-DD). Defaults to now.
        doc_type:   Filter to a specific doc type (e.g. '855'). Omit for all.
        direction:  Filter to 'inbound' or 'outbound'. Omit for both.

    Returns list of {doc_type, direction, customer_po, filename, delivered_at,
                     created_at, ak5_status, ack_at}.
    """
    conditions = ["d.partner_id = ?"]
    params: list = [partner_id]

    if date_from:
        conditions.append("d.created_at >= ?")
        params.append(date_from)
        if date_to:
            conditions.append("d.created_at < DATEADD(day, 1, CAST(? AS DATE))")
            params.append(date_to)
    else:
        conditions.append(f"d.created_at >= DATEADD(day, -{int(days)}, SYSUTCDATETIME())")

    if doc_type:
        conditions.append("d.doc_type = ?")
        params.append(doc_type)

    if direction:
        conditions.append("d.direction = ?")
        params.append(direction)

    where = "WHERE " + " AND ".join(conditions)

    return db.query(
        f"""
        SELECT d.doc_type, d.direction, d.st_control_num,
               d.customer_po, d.sales_order, d.filename,
               d.delivered_at, d.created_at, d.resent_at,
               a.ak5_status, a.ak5_error_code, a.created_at AS ack_at
        FROM dbo.edi_documents d
        LEFT JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        {where}
        ORDER BY d.created_at DESC
        """,
        tuple(params),
    )


@mcp.tool()
def get_edi_summary(
    group_by: str = "partner",
    partner_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    days: Optional[int] = 30,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """
    Flexible summary counts of EDI documents and acknowledgment status.

    Args:
        group_by: How to group results. Options:
                  'partner' — per partner (default)
                  'doc_type' — per document type (855/856/810)
                  'day' — per day (for trend analysis)
                  'day_doc' — per day + doc type (drill-down)
                  'week' — per week
                  'partner_doc' — per partner + doc type (most detailed)
        partner_id: Filter to a specific partner. Omit for all.
        doc_type: Filter to a specific doc type (e.g. '855'). Omit for all.
        days: Look back N days. Defaults to 30. Ignored if date_from is set.
        date_from: Start date (YYYY-MM-DD). Overrides days.
        date_to: End date (YYYY-MM-DD). Defaults to now.

    Returns list of dicts with group columns plus:
      total, delivered, acked, acked_ok, acked_rejected, unacked
      (outbound 855/856/810 only for ack counts)
    """
    # Build WHERE
    conditions = []
    params: list = []

    if date_from:
        conditions.append("d.created_at >= ?")
        params.append(date_from)
        if date_to:
            conditions.append("d.created_at < DATEADD(day, 1, CAST(? AS DATE))")
            params.append(date_to)
    else:
        conditions.append(f"d.created_at >= DATEADD(day, -{int(days)}, SYSUTCDATETIME())")

    if partner_id:
        conditions.append("d.partner_id = ?")
        params.append(partner_id)

    if doc_type:
        conditions.append("d.doc_type = ?")
        params.append(doc_type)

    where = "WHERE " + " AND ".join(conditions)

    # Build GROUP BY
    group_map = {
        "partner":     {"select": "d.partner_id AS partner_id",
                        "group": "d.partner_id", "order": "d.partner_id"},
        "doc_type":    {"select": "d.doc_type AS doc_type",
                        "group": "d.doc_type", "order": "d.doc_type"},
        "day":         {"select": "CAST(d.created_at AS DATE) AS day",
                        "group": "CAST(d.created_at AS DATE)", "order": "CAST(d.created_at AS DATE)"},
        "week":        {"select": "DATEADD(week, DATEDIFF(week, 0, d.created_at), 0) AS week",
                        "group": "DATEADD(week, DATEDIFF(week, 0, d.created_at), 0)",
                        "order": "DATEADD(week, DATEDIFF(week, 0, d.created_at), 0)"},
        "day_doc":     {"select": "CAST(d.created_at AS DATE) AS day, d.doc_type AS doc_type",
                        "group": "CAST(d.created_at AS DATE), d.doc_type",
                        "order": "CAST(d.created_at AS DATE), d.doc_type"},
        "partner_doc": {"select": "d.partner_id AS partner_id, d.doc_type AS doc_type",
                        "group": "d.partner_id, d.doc_type", "order": "d.partner_id, d.doc_type"},
    }
    g = group_map.get(group_by, group_map["partner"])

    return db.query(
        f"""
        SELECT
            {g['select']},
            SUM(CASE WHEN d.direction = 'inbound' THEN 1 ELSE 0 END) AS inbound,
            SUM(CASE WHEN d.direction = 'outbound' THEN 1 ELSE 0 END) AS outbound,
            SUM(CASE WHEN d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
                     THEN 1 ELSE 0 END) AS outbound_business,
            SUM(CASE WHEN d.delivered_at IS NOT NULL
                      AND d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
                     THEN 1 ELSE 0 END) AS delivered,
            SUM(CASE WHEN a.id IS NOT NULL
                      AND d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
                     THEN 1 ELSE 0 END) AS acked,
            SUM(CASE WHEN a.id IS NOT NULL AND a.ak5_status = 'A'
                      AND d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
                     THEN 1 ELSE 0 END) AS acked_ok,
            SUM(CASE WHEN a.id IS NOT NULL AND a.ak5_status IN ('R', 'E')
                      AND d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
                     THEN 1 ELSE 0 END) AS acked_rejected,
            SUM(CASE WHEN d.direction = 'outbound'
                      AND d.doc_type IN ('855','856','810')
                      AND d.delivered_at IS NOT NULL
                      AND a.id IS NULL THEN 1 ELSE 0 END) AS unacked,
            MIN(d.created_at) AS earliest,
            MAX(d.created_at) AS latest
        FROM dbo.edi_documents d
        LEFT JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        {where}
        GROUP BY {g['group']}
        ORDER BY {g['order']}
        """,
        tuple(params),
    )


def _biz_hours(start: datetime, end: datetime) -> float:
    """Count hours between two datetimes, excluding Saturday and Sunday."""
    if not start or not end or end < start:
        return 0.0
    total = timedelta()
    cur = start
    while cur < end:
        if cur.weekday() < 5:  # Mon–Fri
            day_end = min(end, (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0))
            total += day_end - cur
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    return total.total_seconds() / 3600


@mcp.tool()
def get_edi_unacked_aging(
    partner_id: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> list[dict]:
    """
    Unacked outbound EDI docs with business-hours aging and partner percentiles.

    For each unacked delivered doc (855/856/810), computes how many business hours
    (Mon–Fri only) it has been waiting, and compares against that partner's
    historical ack percentiles. Flags docs as 'overdue' if beyond the partner's
    observed max ack time.

    Args:
        partner_id: Filter to a specific partner. Omit for all.
        doc_type:   Filter to a specific doc type (e.g. '856'). Omit for all.

    Returns list of {partner_id, doc_type, customer_po, filename, created_at,
                     biz_hours_waiting, partner_median_h, partner_p90_h,
                     partner_max_h, status} where status is 'ok', 'slow', or 'overdue'.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Get historical ack times per partner+doc_type
    hist_rows = db.query("""
        SELECT d.partner_id, d.doc_type, d.created_at AS sent, a.created_at AS acked
        FROM dbo.edi_documents d
        JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        WHERE d.direction = 'outbound' AND d.doc_type IN ('855','856','810')
    """)
    from collections import defaultdict
    hist: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in hist_rows:
        h = _biz_hours(r["sent"], r["acked"])
        if h > 0:
            hist[(r["partner_id"], r["doc_type"])].append(h)

    percentiles: dict[tuple[str, str], dict] = {}
    for key, vals in hist.items():
        vals.sort()
        n = len(vals)
        percentiles[key] = {
            "median": vals[n // 2] if n else 0,
            "p90": vals[int(n * 0.9)] if n else 0,
            "max": vals[-1] if n else 0,
            "n": n,
        }

    # 2. Get unacked delivered docs
    conditions = [
        "d.direction = 'outbound'",
        "d.doc_type IN ('855','856','810')",
        "d.delivered_at IS NOT NULL",
        "a.id IS NULL",
    ]
    params: list = []
    if partner_id:
        conditions.append("d.partner_id = ?")
        params.append(partner_id)
    if doc_type:
        conditions.append("d.doc_type = ?")
        params.append(doc_type)

    where = "WHERE " + " AND ".join(conditions)
    unacked_rows = db.query(
        f"""
        SELECT d.partner_id, d.doc_type, d.customer_po, d.filename, d.created_at
        FROM dbo.edi_documents d
        LEFT JOIN dbo.edi_acknowledgments a ON a.original_document_id = d.id
        {where}
        ORDER BY d.partner_id, d.doc_type, d.created_at
        """,
        tuple(params),
    )

    # 3. Compute aging and flag
    results = []
    for r in unacked_rows:
        key = (r["partner_id"], r["doc_type"])
        bh = round(_biz_hours(r["created_at"], now), 1)
        p = percentiles.get(key, {"median": 0, "p90": 0, "max": 0, "n": 0})

        if p["max"] > 0 and bh > p["max"]:
            status = "overdue"
        elif p["p90"] > 0 and bh > p["p90"]:
            status = "slow"
        else:
            status = "ok"

        results.append({
            "partner_id": r["partner_id"],
            "doc_type": r["doc_type"],
            "customer_po": r["customer_po"],
            "filename": r["filename"],
            "created_at": r["created_at"],
            "biz_hours_waiting": bh,
            "partner_median_h": round(p["median"], 1),
            "partner_p90_h": round(p["p90"], 1),
            "partner_max_h": round(p["max"], 1),
            "partner_sample_size": p["n"],
            "status": status,
        })

    return results


if __name__ == "__main__":
    import sys
    transport = "sse" if "--transport" in sys.argv and "sse" in sys.argv else "stdio"
    mcp.run(transport=transport)
