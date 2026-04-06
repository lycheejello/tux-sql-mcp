# Azure SQL Schema — acu-inventory

**Server:** `tuxton-acu-sql.database.windows.net`
**Database:** `acu-inventory` *(rename planned — name implies inventory-only but scope is broader)*
**Auth:** Azure AD (ODBC Driver 18, token-based)
**ETL source:** `../TuxtonTools/acu_etl` — Azure Function app that pulls from Acumatica and upserts here

---

## Tables

### `dbo.bi_sales_ledger` — 18,069 rows
Invoice line-level sales history from Acumatica's `InvoicedItems` GI.
**ETL:** upsert on `SalesLedgerKey` (`{TranType}-{ReferenceNbr}-{LineNbr}`)
**Model use:** Revenue actuals (IS), DSO calculation

| Column | Type | Notes |
|---|---|---|
| `SalesLedgerKey` | NVARCHAR(100) PK | `{TranType}-{ReferenceNbr}-{LineNbr}` |
| `TranType` | NVARCHAR(10) | e.g. `INV`, `CM` |
| `ReferenceNbr` | NVARCHAR(50) | Invoice number |
| `LineNbr` | INT | |
| `CustomerID` | NVARCHAR(50) | FK → `bi_customers` |
| `CustomerClassID` | NVARCHAR(50) | |
| `CustomerName` | NVARCHAR(255) | |
| `InventoryID` | NVARCHAR(50) | FK → `bi_inventory_items` |
| `Description` | NVARCHAR(255) | |
| `ItemClass` | NVARCHAR(100) | Maps to revenue category (Plates/Mugs/Bowls/Sets/Other) |
| `Salesperson` | NVARCHAR(50) | |
| `Commission` | DECIMAL(10,4) | |
| `InvoiceDate` | DATETIME2 | Use for monthly IS bucketing |
| `FinancialPeriod` | NVARCHAR(10) | e.g. `202401` |
| `DocumentDate` | DATETIME2 | |
| `Quantity` | DECIMAL(18,4) | |
| `UnitPrice` | DECIMAL(18,6) | |
| `UnitCost` | DECIMAL(18,6) | Landed cost / COGS per unit |
| `UnitProfit` | DECIMAL(18,6) | |
| `ExtAmount` | DECIMAL(18,4) | Revenue (price × qty) |
| `ExtCost` | DECIMAL(18,4) | COGS (cost × qty) |
| `ExtProfit` | DECIMAL(18,4) | |
| `AddressLine1` | NVARCHAR(255) | Ship-to |
| `City` | NVARCHAR(100) | |
| `State` | NVARCHAR(50) | |
| `PostalCode` | NVARCHAR(20) | |
| `Country` | NVARCHAR(10) | |

---

### `dbo.bi_open_po_lines` — 686 rows
Open (non-completed, non-cancelled) PO lines. Truncated and reloaded on every sync — closed POs disappear automatically.
**ETL:** truncate-and-reload
**Model use:** Open PO / COGS pipeline, DIO support

| Column | Type | Notes |
|---|---|---|
| `POLineKey` | NVARCHAR(100) PK | `{PONbr}_{LineNbr}` |
| `PONbr` | NVARCHAR(50) | |
| `LineNbr` | INT | |
| `InventoryID` | NVARCHAR(50) | FK → `bi_inventory_items` |
| `OrderQty` | DECIMAL(18,4) | |
| `PromisedOn` | DATE | Earliest per InventoryID used for PIMS sync |
| `WarehouseID` | NVARCHAR(50) | |

---

### `dbo.bi_inventory_items` — 2,612 rows
One row per InventoryID × WarehouseID combination.
**ETL:** upsert on `ItemWarehouseKey` (`{InventoryID}_{WarehouseID}`)
**Model use:** Product category mapping, DIO (QtyOnHand), open order quantities

| Column | Type | Notes |
|---|---|---|
| `ItemWarehouseKey` | NVARCHAR(100) PK | `{InventoryID}_{WarehouseID}` |
| `InventoryID` | NVARCHAR(50) | |
| `WarehouseID` | NVARCHAR(50) | |
| `WarehouseName` | NVARCHAR(255) | |
| `Description` | NVARCHAR(255) | |
| `ItemStatus` | NVARCHAR(50) | Active / Inactive |
| `ItemType` | NVARCHAR(50) | |
| `ItemClass` | NVARCHAR(50) | Revenue category bucket |
| `PostingClass` | NVARCHAR(50) | |
| `DefaultPrice` | DECIMAL | |
| `LastCost` | DECIMAL | Most recent landed cost |
| `QtyOnHand` | DECIMAL | Current inventory — DIO numerator |
| `QtyAvailable` | DECIMAL | |
| `QtyOnSalesOrder` | DECIMAL | |
| `QtyOnPurchaseOrder` | DECIMAL | |
| `PackSize` | DECIMAL | |
| `CaseWeightLbs` | DECIMAL | |
| `CaseVolumeCuFt` | DECIMAL | |
| *(+ dimensions, UOM fields, custom attrs)* | | See `explore_schema.py` output for full list |

---

### `dbo.bi_customers` — 465 rows
Customer master from Acumatica's `BI-Customers` GI.
**ETL:** upsert on `CustomerID`
**Model use:** Revenue concentration (top customers as % of revenue), DSO by customer

| Column | Type | Notes |
|---|---|---|
| `CustomerID` | NVARCHAR(50) PK | |
| `CustomerName` | NVARCHAR(255) | |
| `CustomerClass` | NVARCHAR(50) | |
| `Type` | NVARCHAR(50) | |
| `AddressLine1` | NVARCHAR(255) | |
| `AddressLine2` | NVARCHAR(255) | |
| `City` | NVARCHAR(100) | |
| `State` | NVARCHAR(50) | |
| `PostalCode` | NVARCHAR(20) | |
| `Country` | NVARCHAR(10) | |

---

### `dbo.bi_shipments` — 90 rows
Shipment header + line data.
**ETL:** `sql_shipments.py`
**Model use:** Freight cost analysis, shipment volume (secondary)

| Column | Type | Notes |
|---|---|---|
| `ShipmentLineKey` | NVARCHAR(100) PK | |
| `ShipmentNbr` | NVARCHAR(50) | |
| `Type` | NVARCHAR(50) | |
| `Status` | NVARCHAR(50) | |
| `ShipmentDate` | DATETIME2 | |
| `CustomerID` | NVARCHAR(50) | |
| `CustomerName` | NVARCHAR(255) | |
| `WarehouseID` | NVARCHAR(50) | |
| `ShippedQuantity` | DECIMAL | |
| `FreightCost` | DECIMAL | |
| `FreightPrice` | DECIMAL | |
| `IsUPSorFEDEX` | BIT | |
| *(+ weight, volume, packages, address fields)* | | |

---

### `dbo.bi_product_group_attributes` — 124 rows
Product group marketing/spec attributes (brand, material, bullets, harmonization codes, etc.).
**ETL:** `import_product_groups.py`
**Model use:** Not directly used in financial model — category enrichment only

---

### `dbo.edi_documents`
Every EDI transaction set (ST/SE pair) that passes through edi_sftp_sync.
**ETL:** `edi_sftp_sync/edi_tracker.py` (inline during file transport) + `migrations/backfill.py` (historic)
**Model use:** EDI order lifecycle tracking, 997 acknowledgment status

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Identity |
| `partner_id` | NVARCHAR(100) | partners.yaml id (e.g. ClarkFoodService, USFDirect) |
| `doc_type` | NVARCHAR(10) | 850, 855, 856, 810, 997 |
| `direction` | NVARCHAR(10) | inbound or outbound |
| `st_control_num` | NVARCHAR(50) | ST02 — used for 997 correlation |
| `gs_control_num` | NVARCHAR(50) | GS06 |
| `isa_control_num` | NVARCHAR(50) | ISA13 |
| `customer_po` | NVARCHAR(100) | PO number from BAK/BIG/PRF/BEG |
| `sales_order` | NVARCHAR(100) | Acumatica SO number if available |
| `filename` | NVARCHAR(500) | Original filename |
| `archive_path` | NVARCHAR(1000) | Blob archive path |
| `delivered_at` | DATETIME2 | When push_outbound sent to partner |
| `created_at` | DATETIME2 | When recorded |

---

### `dbo.edi_acknowledgments`
Links a 997 functional acknowledgment to the outbound document it acknowledges.
**ETL:** `edi_sftp_sync/edi_tracker.py` (correlated during pull_850s)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Identity |
| `ack_document_id` | BIGINT | FK → edi_documents (the 997 row) |
| `original_document_id` | BIGINT | FK → edi_documents (the 855/856/810), NULL if unmatched |
| `acked_doc_type` | NVARCHAR(10) | 855, 856, or 810 (from AK1) |
| `acked_st_control_num` | NVARCHAR(50) | ST control number being acknowledged (from AK2) |
| `ak5_status` | NVARCHAR(5) | A=Accepted, R=Rejected, E=Error |
| `ak5_error_code` | NVARCHAR(10) | AK5 element 2 error code |
| `created_at` | DATETIME2 | When recorded |

---

### `dbo.edi_order_lifecycle` (view)
Per-PO lifecycle summary joining 850→855→856→810 with 997 ack status.

| Column | Type | Notes |
|---|---|---|
| `customer_po` | NVARCHAR(100) | |
| `partner_id` | NVARCHAR(100) | |
| `doc_850_id` / `received_850_at` | | Inbound PO |
| `doc_855_id` / `delivered_855_at` / `ack_855_status` / `ack_855_at` | | PO acknowledgment |
| `doc_856_id` / `delivered_856_at` / `ack_856_status` / `ack_856_at` | | Ship notice |
| `doc_810_id` / `delivered_810_at` / `ack_810_status` / `ack_810_at` | | Invoice |

---

## Financial Model Mapping

| Model Need | Table | Key Columns |
|---|---|---|
| Revenue actuals (IS) | `bi_sales_ledger` | `ExtAmount`, `InvoiceDate`, `ItemClass` |
| COGS actuals (IS) | `bi_sales_ledger` | `ExtCost`, `InvoiceDate`, `ItemClass` |
| AR balance → DSO | `bi_sales_ledger` | Sum unpaid `ExtAmount` by `CustomerID` (no AR aging table yet) |
| Inventory balance → DIO | `bi_inventory_items` | `QtyOnHand × LastCost` by warehouse |
| Open PO pipeline | `bi_open_po_lines` | `OrderQty`, `PromisedOn` |
| Product category mapping | `bi_inventory_items` | `ItemClass` |
| Customer concentration | `bi_customers` + `bi_sales_ledger` | Join on `CustomerID` |

> **Note:** There is no dedicated AR aging or AP table yet. DSO/DPO actuals will require either an additional ETL feed or derivation from `bi_sales_ledger` + payment data.

---

## MCP Dependencies on ETL

If the ETL schema changes, update this file and the MCP query layer accordingly:

| ETL file | Table written | Break risk |
|---|---|---|
| `sql_sales_ledger.py` | `bi_sales_ledger` | High — primary IS data source |
| `sql_po_lines.py` | `bi_open_po_lines` | Medium — truncate/reload, schema stable |
| `sql_customers.py` | `bi_customers` | Low — rarely changes |
| `sql_shipments.py` | `bi_shipments` | Low — secondary use |
| `import_product_groups.py` | `bi_product_group_attributes` | None — not used in model |
| `edi_tracker.py` (edi_sftp_sync) | `edi_documents`, `edi_acknowledgments` | Medium — EDI lifecycle queries |
