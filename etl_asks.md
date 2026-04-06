# ETL Asks — acu_etl Team

Requests from the MCP / financial model team. Each ask includes the model need it unblocks.

---

## 1. AR Aging table (High priority)

**Ask:** Add an ETL feed that writes open AR balances to a new table, e.g. `dbo.bi_ar_aging`.

**Minimum columns needed:**
- `CustomerID`
- `ReferenceNbr` (invoice number)
- `InvoiceDate`
- `DueDate`
- `OriginalAmount`
- `BalanceDue`
- `AgingBucket` (Current / 1–30 / 31–60 / 61–90 / 90+)

**Why:** Without this, we cannot compute actual DSO or validate the model's 52-day DSO assumption. Currently the closest proxy is inferring unpaid AR from `bi_sales_ledger`, which is inaccurate.

**Acumatica GI target:** ARDocumentDetails or ARBalanceByCustomer

---

## 2. AP / Open payables table (High priority)

**Ask:** Add an ETL feed for open AP balances, e.g. `dbo.bi_ap_aging`.

**Minimum columns needed:**
- `VendorID`
- `VendorName`
- `ReferenceNbr`
- `DocDate`
- `DueDate`
- `OriginalAmount`
- `BalanceDue`

**Why:** No AP data exists in the database today. The model's 38-day DPO assumption cannot be validated or replaced with actuals.

**Acumatica GI target:** APDocumentDetails or APBalanceByVendor

---

## 3. Historical (closed) PO lines (Medium priority)

**Ask:** Either (a) retain closed PO lines in `bi_open_po_lines` with a `Status` column, or (b) create a separate `dbo.bi_po_history` table with completed PO lines.

**Minimum columns needed:** Same as `bi_open_po_lines` + `Status`, `ClosedDate`, `ReceivedQty`, `UnitCost`.

**Why:** `bi_open_po_lines` is truncate-and-reload of open-only POs. There is no historical landed cost data per PO line. The model needs actual COGS/landed cost by period — currently derived from `bi_sales_ledger.UnitCost` which may lag.

---

## 4. Confirm ItemClass values map to model categories (Low effort)

**Ask:** Confirm (or provide a mapping) that `bi_sales_ledger.ItemClass` and `bi_inventory_items.ItemClass` values correspond to the model's five revenue categories:
- Plates
- Mugs
- Bowls
- Sets
- Other

**Why:** The MCP server groups revenue and COGS by `ItemClass`. If the values in the DB don't match the model's category names, we need a translation layer.

---

## 5. Database rename (Low priority / housekeeping)

**Ask:** Rename `acu-inventory` to a more descriptive name (e.g. `acu-bi` or `tuxton-bi`) before the MCP server goes into regular use.

**Why:** The database holds invoices, customers, shipments, and POs — not just inventory. The current name causes confusion.

**Note:** Requires updating `SQL_DATABASE` in `.env` and any ETL connection strings.

---

## Summary table

| # | Ask | Priority | Unblocks |
|---|---|---|---|
| 1 | AR aging table | High | DSO actuals, AR balance on BS |
| 2 | AP / open payables table | High | DPO actuals, AP balance on BS |
| 3 | Historical closed PO lines | Medium | COGS history, landed cost by period |
| 4 | Confirm ItemClass → category mapping | Low effort | Revenue/COGS grouping accuracy |
| 5 | Database rename | Low | Clarity / housekeeping |
