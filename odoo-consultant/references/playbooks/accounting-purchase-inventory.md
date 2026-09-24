# Playbook: Accounting, Purchase and Inventory

Use this as a research starting point, not a ready-made recommendation. Historical
verification notes below do not certify the current checkout or client database. Re-check
material rules, defaults, calculations and labels before using them. Follow SKILL.md and
the implementation protocol for discovery and decisions.


The structural decisions to settle with the client and the accountant **before** they
start working. Verified against Odoo 20 source (2026-09-22). Re-check a label in the source
before giving it as a click-path.

## Decide first: these are hard or impossible to change later

| Decision | Why it's locked | Source |
|---|---|---|
| **Company currency** | Blocked once any journal item exists: *"You cannot change the currency of the company since some journal items already exist"* | `addons/account/models/company.py` |
| **Hard Lock Date** | Can never be removed or moved back. Can't be set while draft entries exist in the period | `addons/account/models/company.py` |
| **Costing method** | Can be changed, but Odoo **silently recalculates the stock value** of every product in the category from the last closing date. Change it only right after a closing | `addons/stock_account/models/product.py` `_correct_inventory_valuation` |

## How Odoo thinks

| Idea | In plain words |
|---|---|
| **Journal entry** | Every financial event (invoice, bill, payment, stock valuation) ends up as a journal entry. Reports are built from these |
| **Perpetual valuation (Odoo 20)** | Label: **Perpetual (at invoicing)**. Stock value is booked when the **vendor bill** is posted; cost of goods sold when the **customer invoice** is posted. **Not** at receipt or delivery, as in older Odoo versions |
| **Periodic valuation** | Label: **Periodic (at closing)**. Nothing posted day to day. At closing, the accountant posts the difference from the valuation report |
| **Product category** | Carries costing method and valuation settings. Group products by how they're valued, not only by type |
| **Warehouse routes** | Receipts and deliveries can be 1, 2 or 3 steps. Each step is a separate transfer someone must validate |

Warning: `documentations/stock_valuation.md` still describes the old flow (a journal entry
at receipt). For valuation, trust the source.

## Accounting decisions

| Decision | Options (exact labels) | Choose A when / B when | Change later? |
|---|---|---|---|
| Stock valuation | **Inventory Valuation**: **Periodic (at closing)** / **Perpetual (at invoicing)**, in the Accounting settings, block **Inventory Valuation**. Can be overridden per product category | Periodic: accountant closes monthly and interim figures don't matter. Perpetual: management wants current margin and balance sheet | Allowed. Past periods are not restated |
| Costing method | **Costing Method** on the category: **Standard Price**, **Average Cost (AVCO)**, **First In First Out (FIFO)** | Standard: production with planned costs. AVCO/FIFO: trading with changing purchase prices | See the table above: recalculates silently |
| Multi-currency | Setting **Multi-Currencies** | Any supplier, customer or bank in another currency | Can be switched on anytime |
| Lock dates | **Accounting > Closing > Lock Dates...** (in the Accounting app; needs accounting administrator access): **Sales Lock Date**, **Purchase Lock date**, **Tax Return Lock Date**, **Global Lock Date**, **Hard Lock Date** | Soft locks for the monthly close (exceptions possible). Hard lock only when the audit or tax return is final | Soft: yes. Hard: never |
| Cost centers / projects | Setting **Analytic Accounting** | Management wants profit by department, project or branch | Can be turned on later, but earlier history has no analytic data. Decide at start |
| Foreign/exempt customers | Fiscal positions (**Detect Automatically**, **Country**, **Tax ID required**) | Many export or VAT-exempt customers | Only affects new documents |
| Group companies | Inter-company rules: **Generate Bills and Refunds** (Draft / Validated), **Generate Sales Orders** / **Generate Purchase Orders** | Regular trade between group companies | Per company |

## Purchase decisions

| Decision | Options | Choose A when / B when | Change later? |
|---|---|---|---|
| When to pay the vendor | Product, Purchase tab, **Control Policy**: **On ordered quantities** / **On received quantities**. Services are always "ordered". Setting **3-way matching** adds bill-to-receipt matching | Ordered: prepayments, services, trusted suppliers. Received: pay only for what arrived | Per product, anytime |
| Purchase approval | Setting **Purchase Order Approval** + **Minimum Amount** (default 5000, company currency) | On: spending control and segregation of duties. Off: small team | Anytime |
| Edit confirmed orders | Setting **Lock Confirmed Orders** | On: prevents changes after confirmation | Anytime |

## Inventory decisions

| Decision | Options | Choose A when / B when | Change later? |
|---|---|---|---|
| Receipt steps | Warehouse **Incoming Shipments**: **Receive and Store (1 step)** / **Receive then Store (2 steps)** / **Receive, Quality Control, then Store (3 steps)**. Visible only with Multi-Step Routes on | 1: small warehouse. 2-3: receiving dock, putaway, inspection. With 2-3 steps, goods can't be sold until the last step is done | Allowed. Check open transfers first (effect not verified) |
| Delivery steps | Warehouse **Outgoing Shipments**: **Deliver (1 step)** / **Pick then Deliver (2 steps)** / **Pick, Pack, then Deliver (3 steps)** | 1: counter sales, low volume. 2-3: picking waves, packing stations | Same as receipts |
| Lots / serials | Setting **Lots & Serial Numbers**; product **Tracking**: **None**, **By Quantity**, **By Lots**, **By Unique Serial Number** | Tracking for food, pharma, warranty, recalls. None for commodities | Tracking can change (fix stock with an inventory adjustment). **Valuation by Lot/Serial** is blocked while untracked stock exists |
| Replenishment | Reordering rule **Trigger**: **Auto** / **Manual**; routes **Buy**, **Replenish on Order (MTO)** | Auto: stable fast movers (RFQs created by the scheduler). Manual: buyer reviews each time. MTO: custom or expensive items | Anytime |

## Sales decision that affects accounting

| Decision | Options | Choose A when / B when | Change later? |
|---|---|---|---|
| What to invoice | Sales settings **Invoicing Policy**: **Ordered quantities** / **Delivered quantities** (default for new products; editable per product) | Ordered: prepaid, projects, subscriptions. Delivered: invoice only what was shipped | Anytime. It's read live from the product, not frozen on the order |

## Questions to ask the accountant

1. Statutory currency, and do any partners or banks use other currencies?
2. Periodic or perpetual: how often do they need stock value and margin?
3. Which costing method matches their tax and management reporting?
4. Monthly close routine: who locks what, and when?
5. Is profit by branch, department or project needed from day one?
