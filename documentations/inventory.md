# Inventory (Stock) and Sales Deliveries

> **Module:** `stock` + `sale_stock` | **Path:** [`addons/stock/`](../addons/stock/) + [`addons/sale_stock/`](../addons/sale_stock/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Inventory records where physical goods are (locations inside warehouses), how many are there (quants) and how they move (transfers made of stock moves). Demand never creates a transfer directly. A confirmed sale, a reordering rule or a manufacturing need becomes a **procurement** ("10 units of X are needed at location Y"), and configurable **routes and rules** decide which document answers it: a transfer, a purchase order or a manufacturing order. Warehouse workers then reserve, pick, pack and validate; validation is the only step that changes on-hand quantities. `sale_stock` connects Sales: confirming a sale order launches the procurements that create the delivery, and delivered quantities flow back to the order lines for invoicing and delivery status. Warehouse managers configure steps, routes and operation types; salespeople see availability and delivery progress. Accounting for stock (valuation, COGS) is covered in [`stock_valuation.md`](stock_valuation.md).

---

## The Big Picture — How It Works

```
Demand                        Procurement engine                     Transfer life                         Result
SO confirmed ─────┐
Reordering rule ──┼─► stock.rule.run(procurement) ─► rule found ─► stock.move ─► transfer ─► Reserve ─► Validate ─► quants move
MTO chain, MO, ───┘   routes + location lookup        │              (Waiting / Ready)                  │
Replenish button                                      ├─ Buy ──────► purchase order line                ├─► push rule: next step
                                                      └─ Manufacture ► manufacturing order              └─► backorder for the rest
```

1. **A need appears.** Confirming a sale order builds one procurement per goods line ([`sale_order_line.py:375`](../addons/sale_stock/models/sale_order_line.py#L375)). Reordering rules, the Replenish wizard, MTO chains and manufacturing create procurements the same way.
2. **Odoo finds a rule.** [`run()`](../addons/stock/models/stock_rule.py#L426) looks for a rule that delivers to the procurement's location, checking route sources in priority order and walking up the location tree. No rule means an error: "No rule has been found to replenish ...".
3. **The rule's action creates the document.** A pull rule creates a stock move (always as superuser, because the salesperson who confirms may have no stock rights, [`stock_rule.py:262`](../addons/stock/models/stock_rule.py#L262)). A Buy rule adds a purchase order line; a Manufacture rule creates a manufacturing order.
4. **Moves are grouped into transfers** (`stock.picking`) by reference (the sale order), locations, operation type and priority ([`stock_move.py:1592`](../addons/stock/models/stock_move.py#L1592)).
5. **Reservation** ties on-hand quants to the move and writes move lines that say which lot, package and shelf to take ([`stock_move.py:2135`](../addons/stock/models/stock_move.py#L2135)).
6. **Validation** moves the quantities between quants ([`stock_move.py:2350`](../addons/stock/models/stock_move.py#L2350)), applies push rules for the next step, reserves waiting downstream moves and creates a backorder for what was not processed.
7. **Sales feedback.** `sale_stock` recomputes delivered quantities and the delivery status from done moves.

### Key Decision Points

- **Steps per warehouse:** receive in 1, 2 or 3 steps; deliver in 1, 2 or 3 steps. More steps means more transfers per order and staging locations.
- **Supply method per rule:** take from stock, trigger another rule (make to order), or take from stock and trigger another rule only for the shortfall.
- **Reservation method per operation type:** at confirmation, manually, or a number of days before the scheduled date.
- **Shipping policy:** ship as soon as possible with backorders, or only when everything is ready.
- **Backorder policy per operation type:** ask, always, or never (cancel the rest).
- **Tracking per product:** none, by quantity, by lots, by serial numbers.
- **Removal strategy** per product category or location: FIFO, LIFO, FEFO, closest location, least packages.

---

## When to Use It (and When Not To)

### This module is for:
- Companies that hold physical goods and need on-hand, reserved and forecasted quantities per location.
- Sales teams that must promise dates and see delivery progress on the order.
- Warehouses with staging areas (input, quality control, packing, output) or several warehouses resupplying each other.
- Traceability requirements: lots, serial numbers, expiration dates, product recalls.

### Use something else when:
- You sell only services: `sale` alone delivers and invoices services; nothing here applies.
- You need accounting entries for stock: that is `stock_account` / `account`, see [`stock_valuation.md`](stock_valuation.md).
- You need production planning: `mrp` builds on these moves, see [`mrp.md`](mrp.md).
- You only need a forecast explanation for one product: see [`inventory_forecast_report.md`](inventory_forecast_report.md).

---

## Real-World Scenarios

### Scenario 1: Small shop, partial stock
**Situation:** A one-step warehouse sells 10 chairs; 6 are on the shelf.
**What they do:** The salesperson confirms the order. The Delivery Orders operation reserves at confirmation, so WH/OUT is Ready with 6 reserved. The worker validates and answers "Create Backorder?" with Create Backorder.
**What happens:** 6 chairs leave WH/Stock; the order shows Partially Delivered; a backorder WH/OUT for 4 waits. When the next receipt is validated, Odoo reserves the backorder automatically.

### Scenario 2: Distributor with staging areas
**Situation:** A distributor receives in 3 steps (unload, quality check, store) and delivers in 2 (pick, ship).
**What they do:** Warehouse → Warehouse Configuration: Incoming Shipments = 3 steps, Outgoing Shipments = 2 steps (needs Multi-Step Routes).
**What happens:** A purchase creates only WH/IN. Validating WH/IN creates WH/QC; validating WH/QC creates WH/STOR. A sale creates only WH/PICK; validating WH/PICK creates WH/OUT. Each later step is created by a push rule when the previous one is done.

### Scenario 3: Buy exactly what was sold
**Situation:** Custom sofas are never stocked; each sale must trigger a purchase.
**What they do:** Enable Replenish on Order (MTO), tick Replenish on Order (MTO) on the product, set a vendor on its Purchase tab.
**What happens:** Confirming the sale creates a delivery in Waiting Another Operation and an RFQ for the vendor. With the vendor's default Group RFQ = On Order, each sale order gets its own RFQ; Daily, Weekly or Always group needs into shared RFQs. Receiving that purchase reserves the delivery at once.

### Scenario 4: Customer sends goods back
**Situation:** A customer returns 2 of 5 delivered items.
**What they do:** Open the done delivery → Return. The return transfer opens in draft with quantity 0 on every line; enter 2 (or click Return All for everything), then validate.
**What happens:** 2 units come back to stock; the sale order line's delivered quantity drops by 2, so a credit note can be issued. With Allow Spontaneous Returns, the customer can also request the return and print a return label from the portal; the warehouse then creates the return transfer when the parcel arrives.

---

## Core Concepts

### Locations and warehouses

Every quantity lives in a `stock.location` ([`stock_location.py:33`](../addons/stock/models/stock_location.py#L33)):

| Type (`usage`) | UI label | Used for |
|---|---|---|
| `internal` | Internal | Physical storage: WH/Stock, shelves, WH/Input, WH/Output |
| `view` | Virtual | Folder in the tree (the warehouse root); cannot hold stock |
| `supplier` | Vendor | Virtual source of receipts |
| `customer` | Customer | Virtual destination of deliveries |
| `inventory` | Inventory Loss | Counterpart of inventory adjustments and scraps |
| `production` | Production | Counterpart of manufacturing consumption and output |
| `transit` | Transit | Goods travelling between warehouses or companies |

Moves from Vendor, Customer, Inventory Loss or Production locations skip reservation, which is why receipts are Ready as soon as they are confirmed ([`stock_location.py:407`](../addons/stock/models/stock_location.py#L407)).

Creating a warehouse ([`stock_warehouse.py:114`](../addons/stock/models/stock_warehouse.py#L114)) builds:

- a view location named after the short code, with **Stock**, **Input**, **Quality Control**, **Output** and **Packing Zone**; the last four stay archived until the chosen steps need them ([`stock_warehouse.py:610`](../addons/stock/models/stock_warehouse.py#L610));
- eight operation types: Receipts (WH/IN), Delivery Orders (WH/OUT), Pick (WH/PICK), Pack (WH/PACK), Quality Control (WH/QC), Storage (WH/STOR), Internal Transfers (WH/INT), Cross Dock (WH/XD), activated or archived to match the steps ([`stock_warehouse.py:960`](../addons/stock/models/stock_warehouse.py#L960));
- the receipt and delivery routes and the warehouse's MTO rule.

Each company has its own Inventory adjustment, Production and inter-warehouse transit locations ([`res_company.py:178`](../addons/stock/models/res_company.py#L178)); see Scrap for the scrap location. A second active warehouse in a company switches on Storage Locations and multi-warehouse mode for all users ([`stock_warehouse.py:308`](../addons/stock/models/stock_warehouse.py#L308)); there is no separate multi-warehouse setting.

### Products: what gets tracked

- Only **goods** (`type = 'consu'`) create stock moves; services never do ([`stock_rule.py:422`](../addons/stock/models/stock_rule.py#L422)).
- **Track Inventory** (`is_storable`, defined on `product.template` in the `product` module, [`product_template.py:127`](../addons/product/models/product_template.py#L127)) decides whether quants exist. Goods without it still get delivery moves, but those moves skip reservation and the product has no on-hand quantity ([`stock_move.py:2047`](../addons/stock/models/stock_move.py#L2047)).
- The **Tracking** selector on the product form (`store_by`: None / By Quantity / By Lots / By Unique Serial Number, [`product.py:842`](../addons/stock/models/product.py#L842)) writes both `is_storable` and `tracking` ([`product.py:1054`](../addons/stock/models/product.py#L1054)). `tracking` itself holds only `lot`, `serial` or empty ([`product.py:835`](../addons/stock/models/product.py#L835)).

### Quants

A `stock.quant` is one row per (product, location, lot, package, owner). `quantity` is on hand, `reserved_quantity` is promised to transfers, `available_quantity` is the difference ([`stock_quant.py:80`](../addons/stock/models/stock_quant.py#L80)). Only done moves change `quantity`. The Physical Inventory screen stores a counted quantity on the quant, and Apply creates the adjustment move ([`stock_quant.py:1028`](../addons/stock/models/stock_quant.py#L1028)). Negative quants are allowed: validating more than is on hand drives the source quant below zero, and no setting blocks it.

Product-level quantities ([`product.py:156`](../addons/stock/models/product.py#L156)):

| Field | UI | Meaning |
|---|---|---|
| `qty_available` | On Hand | Sum of quants in the context locations |
| `free_qty` | Free | On hand minus reserved |
| `incoming_qty` / `outgoing_qty` | Incoming / Outgoing | Open moves into / out of the context locations |
| `virtual_available` | Forecasted | On hand + incoming − outgoing |

With Expiration Dates, Free and Forecasted exclude unreserved quantities whose removal date has passed; On Hand still counts them ([`product_product.py:11`](../addons/product_expiry/models/product_product.py#L11)).

### Operation types

An operation type (`stock.picking.type`) is the template every transfer follows. The fields that change behaviour:

| Field (UI) | Values | Effect |
|---|---|---|
| Type of Operation (`code`) | Receipt / Delivery / Internal Transfer | Dashboard grouping; validating a Receipt or Internal Transfer re-reserves waiting moves |
| Reservation Method | At Confirmation / Manually / Before scheduled date | When stock is reserved ([`stock_picking_type.py:98`](../addons/stock/models/stock_picking_type.py#L98)) |
| Create Backorder | Ask / Always / Never | What happens to unprocessed quantities ([`stock_picking_type.py:193`](../addons/stock/models/stock_picking_type.py#L193)) |
| Shipping Policy (`move_type`) | As soon as possible, with back orders / When all products are ready | Ready when anything vs everything is reserved; default comes from the company ([`stock_picking_type.py:218`](../addons/stock/models/stock_picking_type.py#L218)) |
| Create New / Use Existing Lots/Serial Numbers | booleans | How lots are entered on this operation ([`stock_picking_type.py:87`](../addons/stock/models/stock_picking_type.py#L87)) |
| Operation Type for Returns | operation type | Type used by the Return button ([`stock_picking_type.py:77`](../addons/stock/models/stock_picking_type.py#L77)) |
| Location for allocation / Show Allocation | location / boolean | Where allocated receipts go; open the allocation report on validation ([`stock_picking_type.py:68`](../addons/stock/models/stock_picking_type.py#L68)) |
| Automatic Batches + grouping options | booleans | Auto-batching and waving (see Batch, Wave and Cluster Transfers) |
| Move Entire Packages | boolean | Barcode shows packages instead of their content |

### Transfers, moves and move lines

- **Transfer** (`stock.picking`): one document per operation. States Draft, Waiting Another Operation, Waiting, Ready, Done, Cancelled, computed from its moves ([`stock_picking.py:55`](../addons/stock/models/stock_picking.py#L55), [`:331`](../addons/stock/models/stock_picking.py#L331)). With "As soon as possible", one reserved move is enough for Ready.
- **Move** (`stock.move`): one product line. Demand (`product_uom_qty`) in `uom_id`, `quantity` (reserved or processed) and `picked`. States New, Waiting Another Move, Waiting, Partially Available, Available, Done, Cancelled ([`stock_move.py:107`](../addons/stock/models/stock_move.py#L107)). Chains use `move_orig_ids` / `move_dest_ids`.
- **Forecasted location** (`forecasted_location_id`, [`stock_move.py:86`](../addons/stock/models/stock_move.py#L86)): where the chain ends, e.g. Customers for a pick move whose own destination is WH/Output. A move's destination comes from its transfer, from the rule when "Destination location origin from rule" is set, or from the operation type; it is replaced by the forecasted location when that location lies under it ([`stock_move.py:233`](../addons/stock/models/stock_move.py#L233)).
- **Move line** (`stock.move.line`): the detailed operation (lot, package, sub-location, `quantity`, `picked`).
- **Reference** (`stock.reference`, [`stock_reference.py:4`](../addons/stock/models/stock_reference.py#L4)): a named tag (e.g. the sale order number) put on every move of a document chain; it links transfers, purchases and sales that serve the same need.

For developers: `stock.move.product_uom` and `stock.move.line.product_uom_id` do not exist in 20.0; both are `uom_id`. `location_final_id` does not exist; use `forecasted_location_id`.

---

## Routes and Rules — How Demand Becomes Documents

A **route** is a named policy ("WH: Deliver in 2 steps", "Buy", "Replenish on Order (MTO)"). A **rule** is one step: "when goods are needed at *Destination*, do *Action* from *Source* with *Operation Type*". Warehouses create and update their routes automatically when the steps change; custom routes are only needed for flows the warehouse settings do not cover. Routes and rules live under Inventory → Configuration → Warehouse Management and need Multi-Step Routes.

### Rule fields that change behaviour

| Field (UI) | Values | Effect |
|---|---|---|
| Action | Pull From / Push To / Pull & Push; + Buy (`purchase_stock`), Manufacture (`mrp`) | Pull answers procurements, push reacts to goods arriving, Pull & Push does both ([`stock_rule.py:64`](../addons/stock/models/stock_rule.py#L64)) |
| Supply Method (`procure_method`) | Take From Stock / Trigger Another Rule / Take From Stock, if unavailable, Trigger Another Rule | See Supply methods below ([`stock_rule.py:79`](../addons/stock/models/stock_rule.py#L79)) |
| Automatic Move (`auto`) | Manual Operation / Automatic No Step Added | Push only: create a new move, or rewrite the destination of the arriving move lines ([`stock_rule.py:105`](../addons/stock/models/stock_rule.py#L105)) |
| Destination location origin from rule | boolean | Move destination = rule destination instead of the operation type default ([`stock_rule.py:73`](../addons/stock/models/stock_rule.py#L73)) |
| Lead Time (`delay`) | days | Pull: scheduled date = needed date − delay; push: next move date = done date + delay |
| Cancel Next Move (`propagate_cancel`) | boolean | Cancelling the move cancels the next one once all its other origins are cancelled. Without it, the next move is detached and becomes Take From Stock once its other origins are done or cancelled ([`stock_move.py:2273`](../addons/stock/models/stock_move.py#L2273)) |
| Push Applicability (`push_domain`) | domain | A push rule only applies to moves matching it ([`stock_rule.py:650`](../addons/stock/models/stock_rule.py#L650)) |
| Partner Address | contact | Forces the partner of the created moves |

### Where Odoo looks for a rule

[`_get_rule()`](../addons/stock/models/stock_rule.py#L546) takes the procurement location and all its parents. Starting with the most specific location, it tries these route sources in order and stops at the first rule whose destination is that location (push rules are excluded, [`stock_rule.py:631`](../addons/stock/models/stock_rule.py#L631)):

1. Routes on the procurement: sale order line Routes, the reordering rule's Route, the Replenish wizard's route. Warehouse-selectable Buy/Manufacture routes that are linked to no warehouse of the current company are added here, so they apply to every warehouse ([`stock_location.py:585`](../addons/stock/models/stock_location.py#L585)).
2. Routes of the packaging's package type.
3. Product routes, then product category routes (including parent categories).
4. Warehouse routes: receipt and delivery routes, Buy/Manufacture when "Buy/Manufacture to Resupply" is on, resupply routes.

Only then does it move to the parent location. Within one source, product routes win, then the lowest route Sequence, then the lowest rule Sequence. Rules of another warehouse are ignored; rules without a warehouse apply everywhere ([`stock_rule.py:482`](../addons/stock/models/stock_rule.py#L482)). Warehouse routes holding a Buy rule are skipped for products without a vendor or a confirmed purchase ([`stock_rule.py:165`](../addons/purchase_stock/models/stock_rule.py#L165)), and routes holding a Manufacture rule are skipped for products without a regular BoM ([`stock_rule.py:75`](../addons/mrp/models/stock_rule.py#L75)). When nothing matches, the error blocks the sale order confirmation; scheduler runs log an activity on the product instead ([`stock_orderpoint.py:748`](../addons/stock/models/stock_orderpoint.py#L748)).

### Supply methods

| Supply Method | Move after confirmation | Upstream procurement |
|---|---|---|
| Take From Stock (`make_to_stock`) | Waiting, then reserved from the source location | None |
| Trigger Another Rule (`make_to_order`) | Waiting Another Move (its transfer: Waiting Another Operation) | Full quantity at the rule's source location; the upstream document is linked to this move, and finishing it reserves this move |
| Take From Stock, if unavailable, Trigger Another Rule (`mts_else_mto`) | Created as Take From Stock, confirmed and reserved from what is there | Only the shortfall: demand minus the Free quantity at the source location and its children; the upstream move is not linked |

Sources: the move is created as Take From Stock for the mixed method ([`stock_rule.py:262`](../addons/stock/models/stock_rule.py#L262)); confirmation raises the procurement ([`stock_move.py:1770`](../addons/stock/models/stock_move.py#L1770)); the shortfall uses `free_qty` and accounts for other lines confirmed in the same batch ([`stock_move.py:1869`](../addons/stock/models/stock_move.py#L1869)). In the rules a warehouse generates, the first rule of a chain takes from stock and the following ones trigger another rule ([`stock_warehouse.py:826`](../addons/stock/models/stock_warehouse.py#L826)).

### Pull, push and the other actions

- **Pull**: `run()` groups procurements by action and calls `_run_pull`, `_run_buy` or `_run_manufacture`; Pull & Push behaves as pull there ([`stock_rule.py:426`](../addons/stock/models/stock_rule.py#L426)).
- **Push**: never called by `run()`. It fires after validation (and for negative moves at confirmation) through [`_push_apply()`](../addons/stock/models/stock_move.py#L1270). Rules are matched per group of move lines, by each group's actual destination and result package: goods put away on WH/Input/Shelf 2 still find a rule whose source is WH/Input because the search walks up the parents ([`stock_rule.py:650`](../addons/stock/models/stock_rule.py#L650)), and the routes of the packages' types are added. The next move's quantity is the sum of those lines. Automatic No Step Added rewrites the lines' destination (with putaway) instead of creating a move. No push happens for inventory adjustments or when the move already feeds a downstream move from its destination ([`stock_move.py:2335`](../addons/stock/models/stock_move.py#L2335)).
- **Buy** ([`stock_rule.py:59`](../addons/purchase_stock/models/stock_rule.py#L59)): picks the vendor from the product's vendor list and adds a line to a draft RFQ with the same vendor, operation type, company, buyer and currency, or creates one ([`stock_rule.py:325`](../addons/purchase_stock/models/stock_rule.py#L325)). The vendor's **Group RFQ** decides how far RFQs are shared: On Order (default) keeps needs with a reference, such as an MTO sale, on an RFQ of their own; Daily and Weekly group by expected arrival; Always groups everything. RFQs are created as superuser, or as the current user for manual replenishment. Without a vendor: from a reordering rule it is an error (activity on the product); otherwise the waiting move is cancelled or turned into Take From Stock and the product's responsible is notified.
- **Manufacture**: creates or enlarges a manufacturing order; details in [`mrp.md`](mrp.md). Kits (phantom BoMs) are exploded into component procurements before any rule is searched ([`stock_rule.py:43`](../addons/mrp/models/stock_rule.py#L43)).

### Buy and Manufacture are warehouse routes

The Buy route (`purchase_stock`) and the Manufacture route (`mrp`) cannot be ticked on a product. They are warehouse routes, linked to every warehouse whose Buy to Resupply / Manufacture to Resupply is on (the default) ([`purchase_stock_data.xml:10`](../addons/purchase_stock/data/purchase_stock_data.xml#L10), [`mrp_data.xml:10`](../addons/mrp/data/mrp_data.xml#L10), [`stock.py:77`](../addons/purchase_stock/models/stock.py#L77)). Their rules deliver to WH/Stock, so they answer procurements **at WH/Stock**: reordering rules, MTO chains, the Replenish wizard. They never answer a sale order's procurement, which is for the customer location. Manufacture has Sequence 5 and Buy 10, so with default sequences a product with both a vendor and a regular BoM gets a manufacturing order.

### MTO chains

**Replenish on Order (MTO)** is a global route, archived until the setting of the same name is enabled ([`stock_data.xml:42`](../addons/stock/data/stock_data.xml#L42), [`res_config_settings.py:46`](../addons/stock/models/res_config_settings.py#L46)). Each warehouse contributes one rule: WH/Stock → Customers with the first delivery step's operation type (Delivery Orders, or Pick for multi-step) and Trigger Another Rule ([`stock_warehouse.py:420`](../addons/stock/models/stock_warehouse.py#L420)).

```
SO confirmed ─► procurement at Customers ─► product's MTO rule ─► Move A (WH/Stock → Customers), Waiting Another Move
                                                         └─► procurement at WH/Stock, linked to Move A
                                                               ├─ vendor ─► Buy rule ─► RFQ line; receipt Move B feeds Move A
                                                               ├─ BoM ────► Manufacture rule ─► MO; finished move feeds Move A
                                                               └─ neither ─► "No rule has been found..." ─► SO not confirmed
Receipt / MO done ─► Move A reserved directly (no scheduler needed)
```

When the upstream move is done, its destination moves are reserved at once ([`stock_move.py:2350`](../addons/stock/models/stock_move.py#L2350)). If the upstream move ended somewhere the downstream move does not start from, the link is broken and the downstream move becomes Take From Stock ([`stock_move.py:2904`](../addons/stock/models/stock_move.py#L2904)).

### Which document do I get?

| Product setup (with `purchase_stock` and `mrp`) | Sale order confirmation creates | Where the supply comes from |
|---|---|---|
| No routes on the product | Delivery (or Pick), Waiting until stock | Existing stock; purchases only via reordering rules or Replenish |
| Vendor only | Delivery only | Same as above: Buy never answers a customer procurement |
| Replenish on Order (MTO) + vendor | Delivery Waiting Another Operation + RFQ line | The linked receipt |
| Replenish on Order (MTO) + regular BoM | Delivery Waiting Another Operation + MO | The linked MO; auto-confirmation rules in [`mrp.md`](mrp.md) |
| Replenish on Order (MTO), no vendor, no BoM | Nothing: confirmation fails | Fix the product configuration |
| Resupply route "WH2: Supply Product from WH1" only | Delivery from WH2 only | The route answers procurements at WH2/Stock: reordering rules, Replenish |
| Resupply route + Replenish on Order (MTO), order in WH2 | WH2 delivery Waiting Another Operation + WH1 → transit transfer; WH2 receipt follows | See Inter-warehouse resupply |
| Custom product route | Whatever its rules say | See the secondary-location pattern below |

Manual transfers (created by hand) do not use pull rules; push rules still apply when they are validated.

### Inter-warehouse resupply

Ticking **Resupply From** on a warehouse creates a route "WH2: Supply Product from WH1", selectable on products, categories and warehouses ([`stock_warehouse.py:678`](../addons/stock/models/stock_warehouse.py#L678), [`:812`](../addons/stock/models/stock_warehouse.py#L812)):

| Rule | Action | Operation type | Supply method |
|---|---|---|---|
| WH1/Stock → transit | Pull | WH1 Delivery Orders (or Pick if WH1 is multi-step) | Take From Stock |
| Transit → WH2/Stock | Pull & Push, push domain = WH2's address and WH1 as source | WH2 Receipts | Trigger Another Rule |
| Transit → WH1 receipt destination | Push, for returns | WH1 Receipts | — |

The transit location is the company's internal transit location, or the inter-company transit location when WH1 belongs to another company, so resupply also works between companies and branches. Warehouse addresses are mapped to transit: the warehouse partner's customer and vendor locations become the internal transit location for its own company and the inter-company transit location for every other company ([`stock_warehouse.py:937`](../addons/stock/models/stock_warehouse.py#L937)). A plain delivery from WH1 addressed to WH2's partner therefore lands in transit, and the push side of the transit → WH2 rule, matched by its push domain, creates WH2's receipt.

---

## Multi-Step Receipts and Deliveries

Set on the warehouse, Warehouse Configuration tab, fields **Incoming Shipments** and **Outgoing Shipments** ([`stock_warehouse.py:56`](../addons/stock/models/stock_warehouse.py#L56), [`:62`](../addons/stock/models/stock_warehouse.py#L62)). The tab shows these fields only with Multi-Step Routes.

| Incoming Shipments | Created at purchase / confirmation | Created by push when the previous step is validated |
|---|---|---|
| Receive and Store (1 step) | WH/IN Vendors → WH/Stock | — |
| Receive then Store (2 steps) | WH/IN Vendors → WH/Input | WH/STOR Input → Stock |
| Receive, Quality Control, then Store (3 steps) | WH/IN Vendors → WH/Input | WH/QC Input → Quality Control, then WH/STOR Quality Control → Stock |

| Outgoing Shipments | Created at sale confirmation | Created by push when the previous step is validated |
|---|---|---|
| Deliver (1 step) | WH/OUT Stock → Customers | — |
| Pick then Deliver (2 steps) | WH/PICK Stock → Output | WH/OUT Output → Customers |
| Pick, Pack, then Deliver (3 steps) | WH/PICK Stock → Packing Zone | WH/PACK Packing Zone → Output, then WH/OUT Output → Customers |

How the rules are built ([`stock_warehouse.py:769`](../addons/stock/models/stock_warehouse.py#L769)): the first step is a pull rule whose destination is the final location (WH/Stock for receipts, Customers for deliveries). The move's own destination comes from the operation type (Input, Output or Packing Zone) while `forecasted_location_id` keeps the end of the chain. Every later step is a push rule. With `purchase_stock` installed, the receipt route has no pull rule: purchase orders create WH/IN themselves and the warehouse's Buy rule answers procurements ([`stock.py:135`](../addons/purchase_stock/models/stock.py#L135)).

- A two-step sale shows one transfer until PICK is validated ([`test_sale_stock.py:1072`](../addons/sale_stock/tests/test_sale_stock.py#L1072)); a partial PICK and its backorder push into the same open WH/OUT, because moves with the same reference join it ([`test_sale_stock.py:1528`](../addons/sale_stock/tests/test_sale_stock.py#L1528)).
- Receipt rules cancel the next step when a step is cancelled, except the last one; delivery rules propagate the carrier ([`stock_warehouse.py:502`](../addons/stock/models/stock_warehouse.py#L502), [`:826`](../addons/stock/models/stock_warehouse.py#L826)).
- **Cross Dock** (WH/XD, Input → Output) is active only when both receipts and deliveries use several steps. No route uses it out of the box; build a route to send goods from Input straight to Output.

---

## Sale Order → Delivery (`sale_stock`)

### What confirmation does

1. `_action_confirm()` calls `_action_launch_stock_rule()` on the lines ([`sale_order.py:198`](../addons/sale_stock/models/sale_order.py#L198)).
2. For each goods line of a confirmed, unlocked order, the quantity to procure is the ordered quantity minus what existing moves already cover ([`sale_order_line.py:304`](../addons/sale_stock/models/sale_order_line.py#L304)). A `stock.reference` named after the order is created once and put on every move ([`sale_order_line.py:375`](../addons/sale_stock/models/sale_order_line.py#L375)).
3. Procurement values ([`sale_order_line.py:271`](../addons/sale_stock/models/sale_order_line.py#L271)):

| Value | Taken from |
|---|---|
| Location | Customer Location of the delivery address ([`sale_order_line.py:299`](../addons/sale_stock/models/sale_order_line.py#L299)) |
| Warehouse | Order's Warehouse (default: `ir.default`, else the salesperson's Default Warehouse, else the company's first warehouse) |
| Routes | Line Routes; only routes marked "Selectable on Sales Order Line" are offered |
| Deadline | Commitment Date, else the expected date (order date + Delivery Time of the line) |
| Scheduled date | Deadline minus Security Lead Time (company setting, days) |
| Packaging | The line's unit |

4. After `run()`, open transfers of the order are confirmed again, which fires reordering rules for products that go short ([`stock_picking.py:768`](../addons/stock/models/stock_picking.py#L768)).

### How moves become transfers

Moves join an existing transfer when they share references, source, destination, operation type and priority, and the transfer is not printed, not done and has the same partner ([`stock_move.py:1592`](../addons/stock/models/stock_move.py#L1592), [`:1599`](../addons/stock/models/stock_move.py#L1599)). Two sale orders never share a transfer. A transfer that was printed stops receiving new moves; the next ones go to a new transfer.

### Shipping policy and dates

- The order's **Shipping Policy** defaults from the company setting ([`sale_order.py:19`](../addons/sale_stock/models/sale_order.py#L19)). Transfers of an order use "As soon as possible" if any linked order says so, otherwise "When all products are ready" ([`stock.py:275`](../addons/sale_stock/models/stock.py#L275)). With "all at once", the order's expected date is the latest line date.
- Changing the **Commitment Date** rewrites the deadline of open outgoing moves ([`sale_order.py:158`](../addons/sale_stock/models/sale_order.py#L158)). Changing a line's Delivery Time does the same when no commitment date is set ([`sale_order_line.py:265`](../addons/sale_stock/models/sale_order_line.py#L265)). The product's Delivery Time (`sale_delay`) lives in `sale` and is company-dependent ([`product_template.py:66`](../addons/sale/models/product_template.py#L66)).

### Changing a confirmed order

| Change | Effect |
|---|---|
| Increase a quantity | Extra procurement; the new demand merges into the open move |
| Decrease a quantity | A negative procurement reduces the open move (a 2-step PICK goes from 50 to 30, [`test_sale_stock.py:1072`](../addons/sale_stock/tests/test_sale_stock.py#L1072)); a note is logged on the transfers. Below the delivered quantity is refused: "create a return" ([`sale_order_line.py:416`](../addons/sale_stock/models/sale_order_line.py#L416)) |
| Add a line | Procurement right away ([`sale_order_line.py:240`](../addons/sale_stock/models/sale_order_line.py#L240)) |
| Change the delivery address | Open transfers get the new partner, unless the same save also edits order lines ([`sale_order.py:146`](../addons/sale_stock/models/sale_order.py#L146)) |
| Cancel the order | Every transfer that is not done is cancelled; activities are logged on affected documents ([`sale_order.py:238`](../addons/sale_stock/models/sale_order.py#L238)) |

### Delivered quantity and delivery status

- Goods lines compute Delivered from done outgoing moves minus done returns with `to_refund` (on by default and copied to the return, [`stock_move.py:27`](../addons/stock_account/models/stock_move.py#L27); no view shows it in 20, so every return counts) ([`sale_order_line.py:185`](../addons/sale_stock/models/sale_order_line.py#L185)).
- **Delivery Status** is a `sale` field ([`sale_order.py:440`](../addons/sale/models/sale_order.py#L440)); `sale_stock` computes it from transfers ([`sale_order.py:77`](../addons/sale_stock/models/sale_order.py#L77)):

| Status | Condition |
|---|---|
| (empty) | No transfers, or all cancelled |
| Not Delivered | Transfers exist, none done |
| Started | A transfer is done but no line has a delivered quantity yet (e.g. only PICK is done) |
| Partially Delivered | A transfer is done and some line has a delivered quantity |
| Fully Delivered | Every transfer is done or cancelled |

- **Effective Date** is the first done delivery to a customer; invoices use it as delivery date ([`sale_order.py:70`](../addons/sale_stock/models/sale_order.py#L70)).
- Delivering a product that is not on the order adds a line with ordered quantity 0 and the delivered quantity; the price comes from an existing line for invoice-on-delivery products and is 0 for invoice-on-order products ([`stock.py:302`](../addons/sale_stock/models/stock.py#L302)).

### Cross-company warehouses and late installation

- The order's warehouse may belong to another allowed company. The procurement then runs in the warehouse's company, the origin gets the order company's name in brackets, and the delivery address is made visible to all companies ([`sale_order_line.py:366`](../addons/sale_stock/models/sale_order_line.py#L366), [`sale_order.py:255`](../addons/sale_stock/models/sale_order.py#L255)).
- `sale` tracks delivered quantities without stock. Installing `sale_stock` later splits partially delivered lines into a delivered part and a remainder, then launches procurements for every open line, so each open order gets a delivery ([`__init__.py:12`](../addons/sale_stock/__init__.py#L12), [`:34`](../addons/sale_stock/__init__.py#L34)).

---

## Reservation

### When stock is reserved

| Reservation Method | Behaviour |
|---|---|
| At Confirmation | Reserved when the transfer is confirmed; backorders are reserved immediately |
| Manually | Only when someone clicks **Reserve**; the scheduler never reserves these moves |
| Before scheduled date | Reservation date = scheduled date − Days (Days when starred for priority moves); the scheduler and incoming validations reserve from that date on ([`stock_move.py:756`](../addons/stock/models/stock_move.py#L756)) |

Returns are always reserved at confirmation ([`stock_move.py:2052`](../addons/stock/models/stock_move.py#L2052)).

### How it works

[`_action_assign()`](../addons/stock/models/stock_move.py#L2135) processes moves that are Waiting, Partially Available or Waiting Another Move and not yet picked:

1. Moves that bypass reservation (vendor or other virtual source, goods without Track Inventory) get move lines without touching quants.
2. Trigger Another Rule moves without an upstream move are skipped.
3. Chained moves reserve only what their upstream moves brought.
4. Other moves ask the quants for the missing quantity: quants are gathered in removal-strategy order and reserved one by one ([`stock_quant.py:866`](../addons/stock/models/stock_quant.py#L866)).
5. Move lines are created per (location, lot, package, owner); the move becomes Available or Partially Available; putaway rules set the destination of the new lines.

**Reserve never procures.** It only reserves stock that already exists at the source. Pull rules fire at confirmation, from the scheduler or from the Replenish tools.

### Order, re-reservation and limits

- **Reserve** handles starred moves first, then earlier deadlines and dates ([`stock_picking.py:787`](../addons/stock/models/stock_picking.py#L787)); the scheduler sorts by reservation date, priority and date ([`stock_rule.py:681`](../addons/stock/models/stock_rule.py#L681)).
- Validating a receipt or internal transfer, or applying an inventory adjustment, reserves waiting Take From Stock moves of the same products whose source contains the destination; moves sharing a reference go first ([`stock_move.py:2750`](../addons/stock/models/stock_move.py#L2750), [`stock_picking.py:996`](../addons/stock/models/stock_picking.py#L996)).
- Processing stock that another transfer had reserved frees that reservation ([`stock_move_line.py:822`](../addons/stock/models/stock_move_line.py#L822)).
- Product category **Reserve Packagings** = Reserve Only Full Packagings reserves whole packagings only ([`product.py:1302`](../addons/stock/models/product.py#L1302)).
- With Expiration Dates, lots whose removal date falls before the move's scheduled date are not reserved ([`stock_move.py:87`](../addons/product_expiry/models/stock_move.py#L87)).
- **Unreserve** (action menu) releases the quants. The nightly scheduler merges duplicate quants and repairs reserved quantities that do not match the move lines ([`stock_quant.py:1257`](../addons/stock/models/stock_quant.py#L1257), [`:1174`](../addons/stock/models/stock_quant.py#L1174)).

### Removal strategies

The strategy decides which quants go first. Lookup: product category **Force Removal Strategy**, else the source location's strategy (walking up the parents), else FIFO ([`stock_quant.py:650`](../addons/stock/models/stock_quant.py#L650)).

| Strategy | Order |
|---|---|
| FIFO | Oldest incoming date first ([`stock_quant.py:773`](../addons/stock/models/stock_quant.py#L773)) |
| LIFO | Newest first |
| Closest Location | Alphabetical full location name, as a proxy for the picking path |
| Least Packages | A* search for the fewest packages covering the need; falls back to FIFO order if the search runs out of memory ([`stock_quant.py:662`](../addons/stock/models/stock_quant.py#L662)) |
| FEFO (Expiration Dates) | Earliest removal date, then incoming date ([`stock_quant.py:25`](../addons/product_expiry/models/stock_quant.py#L25)) |

Quants with a lot are taken before untracked quants of the same product ([`stock_quant.py:803`](../addons/stock/models/stock_quant.py#L803)).

**FEFO example.** Category "Dairy" uses FEFO. Stock: LOT-A (in Jan 1, removal Mar 15, 20 units), LOT-B (in Jan 10, removal Mar 5, 15 units), LOT-C (in Feb 1, removal Mar 25, 30 units). A delivery of 25 reserves all of LOT-B and 10 of LOT-A, in two move lines. Under FIFO it would take 20 of LOT-A and 5 of LOT-B, and LOT-B could expire on the shelf.

---

## Validation, Backorders and Splitting

- **Picked.** A move or line is processed when it is Picked. If nothing on the transfer is marked picked, every line with a quantity is treated as picked ([`stock_picking.py:1272`](../addons/stock/models/stock_picking.py#L1272)). Reserve fills Quantity, so validating a Ready transfer without touching anything processes the reserved quantities.
- **Validate** ([`stock_picking.py:1176`](../addons/stock/models/stock_picking.py#L1176)):
  1. A draft transfer is confirmed first, and its moves without a quantity get their full demand.
  2. Sanity checks: no empty transfer, not all quantities zero, a lot or serial on every tracked line when the operation type uses lots ([`stock_picking.py:1129`](../addons/stock/models/stock_picking.py#L1129)).
  3. Backorder decision: with Create Backorder = Ask and something unprocessed, the "Create Backorder?" wizard opens ([`stock_picking.py:1353`](../addons/stock/models/stock_picking.py#L1353)); Always creates it silently; Never cancels the rest and posts a note listing what was not delivered ([`stock_picking.py:996`](../addons/stock/models/stock_picking.py#L996)).
  4. Done moves update quants, record lot customers, apply push rules, reserve downstream moves and create the backorder ([`stock_move.py:2350`](../addons/stock/models/stock_move.py#L2350)).
  5. Afterwards: re-reservation for receipts and internal transfers, the confirmation email for deliveries when enabled ([`stock_picking.py:1058`](../addons/stock/models/stock_picking.py#L1058)), and the operation type's auto-print reports.
- **Backorder**: a copy of the transfer with "Back Order of" set; reserved at once when its operation type reserves at confirmation ([`stock_picking.py:1397`](../addons/stock/models/stock_picking.py#L1397)).
- **Split** (action menu): keeps the quantities already filled in this transfer and moves the rest to a new backorder, without validating anything ([`stock_picking.py:1247`](../addons/stock/models/stock_picking.py#L1247)).
- **Zero Demand Warning**: Mark as To Do or Validate on a transfer that has lines with zero demand opens a wizard with Remove lines / Keep lines ([`stock_picking.py:768`](../addons/stock/models/stock_picking.py#L768), [`stock_zero_demand_confirmation.py:4`](../addons/stock/wizard/stock_zero_demand_confirmation.py#L4)).
- **Cancel**: done moves cannot be cancelled; return them instead ([`stock_move.py:2273`](../addons/stock/models/stock_move.py#L2273)).
- **Lock / Unlock**: done transfers are locked; Inventory Administrators can unlock them to correct done quantities.

---

## Returns

`stock.return.picking` does not exist in 20.0; returns are ordinary transfers created by `stock.picking._create_return()`.

- **Return** on a done transfer creates a draft transfer of the operation type's "Operation Type for Returns" (or the same type), starting where the original ended and going back to its source (to the return type's default destination when that type is a receipt), "Return of" set, each move linked to its original move and chained so that returning part of a PICK/PACK/OUT chain stays consistent ([`stock_picking.py:976`](../addons/stock/models/stock_picking.py#L976), [`:911`](../addons/stock/models/stock_picking.py#L911)).
- **Every line starts at quantity 0** ([`stock_picking.py:939`](../addons/stock/models/stock_picking.py#L939)). Enter what comes back, or click **Return All** (original done quantity minus what earlier returns already took back) or **Clear** ([`stock_picking.py:823`](../addons/stock/models/stock_picking.py#L823)). Then confirm and validate like any transfer.
- **Exchange** on a return that is Ready or Done creates a new transfer that sends the returned quantities again; it is not flagged as a return ([`stock_picking.py:843`](../addons/stock/models/stock_picking.py#L843)).
- Returned moves keep the sale line link, so the order's delivered quantity decreases ([`stock.py:399`](../addons/sale_stock/models/stock.py#L399)). A return reason can be stored on the transfer ([`stock.py:264`](../addons/sale_stock/models/stock.py#L264)).

### Customer portal returns (`sale_stock`)

With **Allow Spontaneous Returns**, an order whose first delivery is less than **Return Validity Days** old (default 14) shows a return dialog on the customer portal ([`sale_order.py:265`](../addons/sale_stock/models/sale_order.py#L265)). The customer picks delivered goods lines (combo items excluded), quantities and a **return reason**, then downloads a PDF return label with the warehouse address; the request is logged on the order ([`return_order.py:17`](../addons/sale_stock/controllers/return_order.py#L17), [`:67`](../addons/sale_stock/controllers/return_order.py#L67)). No return transfer is created: the warehouse creates it when the parcel arrives. Five reasons are seeded (wrong item, damaged, not meeting expectations, incorrect specifications, ordered by mistake) and can be edited from the setting ([`return_reason.py:6`](../addons/sale_stock/models/return_reason.py#L6)).

---

## Scrap

`stock.scrap` does not exist in 20.0; a scrap is a `stock.move` with `is_scrap` ([`stock_move.py:139`](../addons/stock/models/stock_move.py#L139)).

- Inventory → Operations → Adjustments → **Scrap** lists scrap moves. The Scrap action on a transfer or on a lot opens the Scrap Products form ([`stock_picking.py:1717`](../addons/stock/models/stock_picking.py#L1717), [`stock_lot.py:387`](../addons/stock/models/stock_lot.py#L387)); from a done transfer it takes the goods from the transfer's destination.
- The destination must be an Inventory Loss location; the default is the company's scrap location, which is the company's Inventory Loss location with the lowest id ([`res_company.py:61`](../addons/stock/models/res_company.py#L61), [`stock_move.py:233`](../addons/stock/models/stock_move.py#L233)).
- Scrapping validates immediately with a number from the `stock.scrap` sequence; if the stock is not there, a warning wizard asks to confirm ([`stock_move.py:2961`](../addons/stock/models/stock_move.py#L2961), [`:2972`](../addons/stock/models/stock_move.py#L2972)).
- **Scrap Reason** tags describe the cause ([`stock_move.py:203`](../addons/stock/models/stock_move.py#L203)); **Should Replenish** launches a procurement for the scrapped quantity at the scrap's source location ([`stock_move.py:2941`](../addons/stock/models/stock_move.py#L2941)).
- A scrap can be undone from Moves History → Revert ([`stock_move_line.py:1223`](../addons/stock/models/stock_move_line.py#L1223)).

---

## Lots and Serial Numbers

- Enable **Lots & Serial Numbers**, then set the product's Tracking to By Lots or By Unique Serial Number. The setting cannot be switched off while any product is tracked ([`res_config_settings.py:103`](../addons/stock/models/res_config_settings.py#L103)).
- Per operation type, **Create New Lots/Serial Numbers** lets workers type new numbers and **Use Existing** lets them pick existing ones ([`stock_picking_type.py:87`](../addons/stock/models/stock_picking_type.py#L87)). Validation refuses tracked lines without a number.
- Numbering: each product can use its own sequence or prefix (**Custom Lot/Serial**, [`product.py:850`](../addons/stock/models/product.py#L850)).
- **Lot customers**: delivering a lot adds the customer to the lot's Customers field, which stays editable ([`stock_move_line.py:704`](../addons/stock/models/stock_move_line.py#L704), [`stock_lot.py:59`](../addons/stock/models/stock_lot.py#L59)); the contact form lists the lots delivered to it ([`res_partner.py:21`](../addons/stock/models/res_partner.py#L21)).
- **Product recall**: Moves History → select lines → Send email mass-mails the partner of each line's transfer with the "Product recall" template ([`stock_move_line.py:715`](../addons/stock/models/stock_move_line.py#L715)).
- **Expiration Dates** (`product_expiry`): each lot carries expiration, best-before, removal and alert dates computed from the product's day offsets ([`production_lot.py:12`](../addons/product_expiry/models/production_lot.py#L12)). It adds FEFO, keeps expired lots out of reservation and out of Free/Forecasted quantities.
- Optional: print GS1 barcodes, and show lots and serial numbers on delivery slips (settings).

---

## Packages, Putaway and Storage

### Packages
- Enable **Packages**. A package (`stock.package`) can sit inside another package (**Container**, [`stock_package.py:44`](../addons/stock/models/stock_package.py#L44)).
- **Put in Pack** on a transfer or from Detailed Operations sets the result package. Validation refuses a package that would move twice in one transfer or end up split across locations ([`stock_move.py:2350`](../addons/stock/models/stock_move.py#L2350)).
- **Package types** carry dimensions and weight limits; they can hold routes (routes marked Applicable on Package Type) and be targeted by putaway rules.

### Putaway rules and storage categories
A putaway rule says: goods arriving in *When product arrives in* go to *Store to sublocation*, for a product, a category or a package type ([`product_strategy.py:16`](../addons/stock/models/product_strategy.py#L16)). Rules are ranked package type first, then product, then exact category, then parent category ([`stock_location.py:293`](../addons/stock/models/stock_location.py#L293)). Sublocation = No, Last Used (where this product was last stored) or Closest Location (the first child that fits, with a storage category) ([`product_strategy.py:69`](../addons/stock/models/product_strategy.py#L69), [`:133`](../addons/stock/models/product_strategy.py#L133)). **Storage categories** limit weight, quantity per product or package type, and whether a location accepts new products when not empty ([`stock_location.py:414`](../addons/stock/models/stock_location.py#L414)). Without a matching rule, goods stay at the destination (for a view location, its first internal child). Putaway runs when reservation creates move lines and when push rules rewrite destinations.

---

## Inventory Adjustments

- **Physical Inventory** (Operations → Adjustments) lists quants. Enter the Counted quantity and Apply: Odoo creates moves between the product's Inventory Adjustment location and the quant's location, updates the location's last and next count dates, and reserves waiting moves that the new stock can serve ([`stock_quant.py:1028`](../addons/stock/models/stock_quant.py#L1028)).
- If stock moved since the count was entered, the "Conflict in Inventory Adjustment" wizard asks which quantity wins ([`stock_quant.py:465`](../addons/stock/models/stock_quant.py#L465)).
- Counting schedule: company **Annual Inventory Date**, per-location Inventory Frequency, and a Scheduled date per quant.
- **Revert** in Moves History creates the opposite moves for inventory adjustments and scraps ([`stock_move_line.py:1223`](../addons/stock/models/stock_move_line.py#L1223)).
- Editing On Hand on the product form (Inventory Administrator) creates an adjustment in the company's first warehouse stock location ([`product.py:276`](../addons/stock/models/product.py#L276)).
- **Inventory at Date**: Reporting → Stock has a date picker in the side panel that recomputes quantities at a past date ([`stock_report_search_panel.xml:9`](../addons/stock/static/src/views/search/stock_report_search_panel.xml#L9)). It sets the `to_date` context; Odoo takes today's quants and reverses done move lines dated after that moment ([`product.py:228`](../addons/stock/models/product.py#L228), [`product.py:256`](../addons/stock/models/product.py#L256)). A date-only `to_date` means the end of that day in the company timezone ([`res_company.py:239`](../addons/stock/models/res_company.py#L239)), so "stock at the start of the month" is `to_date` = last day of the previous month. Only one date at a time: core has no on-screen opening / in / out / closing report per product; the only period versions are country exports (Peru PLE kardex, Romania SAF-T D406 stocks).

---

## Replenishment

### Reordering rules (`stock.warehouse.orderpoint`)

| Field (UI) | Effect |
|---|---|
| Trigger: Auto / Manual | Auto rules run from the scheduler and from immediate triggers; Manual rules only from the Replenishment screen ([`stock_orderpoint.py:32`](../addons/stock/models/stock_orderpoint.py#L32)) |
| Min / Max | Forecast below Min at the lead-time horizon → order up to Max ([`stock_orderpoint.py:57`](../addons/stock/models/stock_orderpoint.py#L57)) |
| Multiple | Round the quantity up to a unit or packaging; with Buy, vendor units are allowed ([`stock_orderpoint.py:89`](../addons/stock/models/stock_orderpoint.py#L89)) |
| Route | Force a Buy, Manufacture or product route; empty = the rules found for the product and location ([`stock_orderpoint.py:101`](../addons/stock/models/stock_orderpoint.py#L101)) |
| Daily Demand, Based on, % | Demand estimate used by Suggest Min-Max and the information popup ([`stock_orderpoint.py:68`](../addons/stock/models/stock_orderpoint.py#L68)) |
| Snoozed | Hides a manual rule until a date |

One rule per product, location and company ([`stock_orderpoint.py:127`](../addons/stock/models/stock_orderpoint.py#L127)).

**How much is ordered.** If the forecast at the lead-time horizon is below Min, the quantity is Max − (forecast at that horizon + quantity in progress), rounded up to the Multiple ([`stock_orderpoint.py:498`](../addons/stock/models/stock_orderpoint.py#L498)). The horizon is today + lead days + the company **Replenishment Horizon** (default 365 days, [`res_company.py:48`](../addons/stock/models/res_company.py#L48)). Lead days add the rules' Lead Times ([`stock_rule.py:388`](../addons/stock/models/stock_rule.py#L388)) and, for Buy, the vendor lead time plus Days to Purchase, or 365 days when no vendor is found ([`stock_rule.py:180`](../addons/purchase_stock/models/stock_rule.py#L180)). Quantity in progress (with `purchase_stock`) is what already sits on unconfirmed RFQs for that location.

**Buttons.** **Order** orders the manually entered quantity, else enough to reach Max ([`stock_orderpoint.py:379`](../addons/stock/models/stock_orderpoint.py#L379), [`:469`](../addons/stock/models/stock_orderpoint.py#L469)); **Automate** switches the rule to Auto and orders; **Snooze** hides it. **Suggest Min-Max** recomputes Daily Demand from past deliveries to customers and production minus customer returns over the chosen period, multiplied by the % factor, and scales Min and Max keeping their current days of coverage ([`stock_orderpoint_suggest.py:29`](../addons/stock/wizard/stock_orderpoint_suggest.py#L29), [`stock_orderpoint.py:886`](../addons/stock/models/stock_orderpoint.py#L886)).

### The Replenishment screen

Inventory → Operations → Procurement → Replenishment ([`stock_orderpoint.py:528`](../addons/stock/models/stock_orderpoint.py#L528)) looks for products with a negative forecast in each warehouse, subtracts what existing rules and RFQs already cover, and creates temporary Manual rules for the rest. Those temporary rules are deleted once nothing is left to order ([`stock_orderpoint.py:715`](../addons/stock/models/stock_orderpoint.py#L715)). The product-form **Replenish** button runs one procurement at the warehouse's stock location with the chosen route ([`product_replenish.py:89`](../addons/stock/wizard/product_replenish.py#L89)).

### Scheduler and immediate triggers

The daily cron **Procurement: run scheduler** ([`stock_sequence_data.xml:56`](../addons/stock/data/stock_sequence_data.xml#L56)) runs [`_run_scheduler_tasks()`](../addons/stock/models/stock_rule.py#L681):

1. Auto reordering rules of active products: recompute and procure, in batches of 1000, each batch in a savepoint so a failing rule does not stop the others ([`stock_orderpoint.py:748`](../addons/stock/models/stock_orderpoint.py#L748)).
2. Reserve Waiting / Partially Available moves whose reservation date has come or whose operation type reserves at confirmation.
3. Quant housekeeping (merge duplicates, repair reservations, drop empty quants).

Auto rules also fire immediately: confirming a transfer triggers the Auto rules of the source locations it takes from ([`stock_move.py:2726`](../addons/stock/models/stock_move.py#L2726)).

### Allocation report

On a receipt or batch, the allocation report lists the incoming products with their free and assigned quantities and the waiting outgoing demands of the same warehouse ([`stock_allocation_report.py:82`](../addons/stock/report/stock_allocation_report.py#L82)). Assigning links the incoming move to the chosen delivery (a make-to-order link) and shares references between the documents. When the operation type has a Location for allocation, the incoming goods are routed there, and the delivery takes them from there once the receipt is done ([`stock_allocation_report.py:419`](../addons/stock/report/stock_allocation_report.py#L419), [`stock_move.py:2718`](../addons/stock/models/stock_move.py#L2718)).

---

## Batch, Wave and Cluster Transfers

Batching is part of `stock` (setting **Batch, Wave & Cluster Transfers**, [`res_config_settings.py:19`](../addons/stock/models/res_config_settings.py#L19)); the separate `stock_picking_batch` module does not exist in 20.0.

- A batch (`stock.picking.batch`, [`stock_picking_batch.py:12`](../addons/stock/models/stock_picking_batch.py#L12)) groups whole transfers for one worker (Operations → Jobs). A **wave** (`is_wave`) groups individual move lines taken out of several transfers, for example all lines of one aisle.
- Per operation type, **Automatic Batches** puts transfers into batches as they are confirmed, grouped by contact, destination country, source or destination location, with maximum lines or transfers ([`stock_picking_type.py:227`](../addons/stock/models/stock_picking_type.py#L227), [`stock_picking.py:2052`](../addons/stock/models/stock_picking.py#L2052)). The wave options group reserved lines by product, category, location or date ([`stock_move_line.py:1455`](../addons/stock/models/stock_move_line.py#L1455)).
- Validating one transfer of a batch removes it from the batch unless the whole batch is done; backorders are re-batched automatically.
- Transport Management (`stock_fleet`) requires this setting.

---

## Pattern: Secondary-Location Fallback

**Verdict:** a custom configuration pattern, not core behaviour, and it works on 20.0. It uses only core features (a hand-made route with two pull rules and the core supply method "Take From Stock, if unavailable, Trigger Another Rule"); no core route ships it and no code is needed.

**Goal:** deliver from WH/Stock; when WH/Stock is short, move the missing quantity from a second storage location (WH/Stock2) first.

| Rule (same route) | Source | Destination | Operation type | Supply Method |
|---|---|---|---|---|
| Delivery | WH/Stock | Customers | Delivery Orders | Take From Stock, if unavailable, Trigger Another Rule |
| Replenishment | WH/Stock2 | WH/Stock | Internal Transfers | Take From Stock |

**Prerequisites**
1. Multi-Step Routes, to create the route.
2. WH/Stock2 must not be under WH/Stock. Stock in a child location already counts as free stock of WH/Stock and is reserved from there, so the pattern would never fire.
3. The route is Applicable on Product (or Product Category) and set on the product.

**What happens at confirmation**
```
SO confirmed ─► procurement at Customers ─► product route wins over the warehouse delivery route ─► Delivery rule
  ─► delivery move created as Take From Stock, confirmed, reserves what WH/Stock has
  ─► shortfall = demand − Free quantity of WH/Stock ─► procurement at WH/Stock ─► Replenishment rule
  ─► internal transfer WH/Stock2 → WH/Stock (reserved from WH/Stock2 if its type reserves at confirmation)
Internal transfer validated ─► automatic re-reservation reserves the delivery (no link between the two)
```

Sources: [`stock_rule.py:262`](../addons/stock/models/stock_rule.py#L262), [`stock_move.py:1770`](../addons/stock/models/stock_move.py#L1770), [`stock_move.py:1869`](../addons/stock/models/stock_move.py#L1869), [`stock_move.py:2750`](../addons/stock/models/stock_move.py#L2750).

**Limits**
- The mixed supply method belongs on the delivery rule. The replenishment rule only needs Take From Stock; setting the mixed method there would chain further upstream when WH/Stock2 is short.
- The shortfall is computed once, from Free quantity (on hand minus reserved) at confirmation. Stock that reaches WH/Stock later does not cancel the internal transfer.
- The delivery is not linked to the internal transfer. It shows Waiting (or Ready with a partial reservation), not Waiting Another Operation, and a manual-reservation delivery waits for its own Reserve click.
- If the product also has other product routes with a rule to WH/Stock, the lowest route Sequence decides which one answers the WH/Stock procurement.
- A Buy or Manufacture route linked to no warehouse applies everywhere and is checked before product routes, so a product with a vendor or BoM would then be bought or made instead of moved from WH/Stock2. With the default data, Buy and Manufacture are linked to each warehouse and do not interfere.
- Reserve on an existing delivery never raises the procurement, and adding the route after confirmation does not affect existing moves.

---

## Security

Security is `ir.access` rows ([`ir.access.csv`](../addons/stock/security/ir.access.csv), [`sale_stock ir.access.csv`](../addons/sale_stock/security/ir.access.csv)).

| Group | Can do |
|---|---|
| Internal user (`base.group_user`) | Read warehouses, locations, operation types, routes, rules, quants, packages; full access to move lines ([`ir.access.csv:43`](../addons/stock/security/ir.access.csv#L43)) |
| Inventory / User (`stock.group_stock_user`, [`stock_security.xml:9`](../addons/stock/security/stock_security.xml#L9)) | Full access to transfers, batches, lots and packages; create and edit quants and moves (no delete, [`ir.access.csv:20`](../addons/stock/security/ir.access.csv#L20)); read reordering rules ([`ir.access.csv:28`](../addons/stock/security/ir.access.csv#L28)); read and edit sale orders and lines |
| Inventory / Administrator (`stock.group_stock_manager`, [`stock_security.xml:15`](../addons/stock/security/stock_security.xml#L15)) | Everything above plus configuration: warehouses, locations, operation types, routes, rules, putaway, storage categories, reordering rules, move deletion |
| Sales / User (`sale_stock`) | Create and edit transfers and moves; read warehouses, locations, reordering rules, rules, lots, package types ([`ir.access.csv:2`](../addons/sale_stock/security/ir.access.csv#L2)) |
| Sales / Administrator | Delete transfers and moves; manage rules |
| Portal | Read transfers where they are the partner or the order customer ([`ir.access.csv:4`](../addons/sale_stock/security/ir.access.csv#L4)) |

Company restrictions: warehouses, transfers, batches, operation types, moves, reordering rules and putaway rules require `company_id in company_ids` ([`ir.access.csv:4`](../addons/stock/security/ir.access.csv#L4)); locations, lots, quants, packages, rules, routes, move lines and storage categories also accept records without a company. The feature groups behind settings (Storage Locations, Multi-Step Routes, Packages, Lots, Consignment, ...) are implied for all internal users when enabled. Rules create moves as superuser, so a salesperson can confirm an order without stock rights.

---

## Configuration & Settings

### Inventory settings (Inventory → Configuration → Settings)

Source: [`res_config_settings.py`](../addons/stock/models/res_config_settings.py), view [`res_config_settings_views.xml`](../addons/stock/views/res_config_settings_views.xml).

| Setting | What it changes |
|---|---|
| Packages | Packages, Put in Pack, package types, Least Packages removal |
| Batch, Wave & Cluster Transfers | Jobs menu, batches and waves, automatic batching per operation type; turning it off also unticks Transport Management |
| Partner-Specific Instructions | Shows the contact's stock instruction (`picking_warn_msg`) on transfers; it does not block anything |
| Shipping Policy | Company default for new orders and operation types; saving rewrites the Shipping Policy of every operation type of the company ([`res_config_settings.py:103`](../addons/stock/models/res_config_settings.py#L103)) |
| Quality / Quality Worksheet | Installs the enterprise quality modules |
| Annual Inventory Date | Default next count date for quants in locations without a frequency |
| Barcode Scanner / Stock Barcode Database | Installs `stock_barcode` (enterprise) / the barcode lookup database |
| Delivery Methods | Installs `delivery`; buttons to configure methods and find providers |
| Transport Management | Installs `stock_fleet` (docks, vehicles, consignment notes); needs batches |
| Confirmation Email / Text Confirmation | Email (or SMS through `stock_sms`) to the customer when a delivery is done |
| Signature | Sign button on delivery orders |
| Variants / Units & Packagings | Product variants; several units and packagings |
| Lots & Serial Numbers (+ Print GS1 Barcodes, Separator) | Lot/serial tracking; cannot be disabled while products are tracked |
| Expiration Dates | Installs `product_expiry` (lot dates, FEFO, expired stock excluded) |
| Display Lots & Serial Numbers on Delivery Slips | Prints them on the slip |
| Consignment | Owner on quants and transfers (stock owned by a third party) |
| Storage Locations | Sub-locations, Internal Transfers type, putaway rules; cannot be disabled with several warehouses in a company |
| Multi-Step Routes | Warehouse steps, routes and rules menus; switches Storage Locations on |
| Replenishment Horizon (days) | How far ahead reordering rules look; 0 = just in time |
| Dropshipping | Installs `stock_dropshipping` (vendor ships to the customer) |
| Replenish on Order (MTO) | Unarchives the global MTO route ([`res_config_settings.py:46`](../addons/stock/models/res_config_settings.py#L46)) |

### Settings added by `sale_stock`

Source: [`res_config_settings.py`](../addons/sale_stock/models/res_config_settings.py), [`res_company.py`](../addons/sale_stock/models/res_company.py).

| Setting | What it changes |
|---|---|
| Security Lead Time for Sales (days) | Schedules deliveries that many days before the promised date ([`res_company.py:12`](../addons/sale_stock/models/res_company.py#L12)) |
| Allow Spontaneous Returns + Return Validity Days + Manage Return Reasons | Portal return requests within N days of the first delivery; return reasons list ([`res_config_settings_views.xml:21`](../addons/sale_stock/views/res_config_settings_views.xml#L21)) |

### Per-record configuration that matters
- Warehouse: Incoming / Outgoing Shipments, Resupply From, Buy / Manufacture to Resupply.
- Operation type: Reservation Method, Create Backorder, Shipping Policy, lot options, return type, allocation location, auto-batch, auto-print.
- Product: Tracking, Routes (MTO, resupply, custom), Responsible, descriptions for receipts and deliveries.
- Product category: Routes, Force Removal Strategy, Reserve Packagings.
- Location: Removal Strategy, Storage Category, Inventory Frequency, Replenishments flag.
- Sale order line: Routes (routes marked Selectable on Sales Order Line).

### System parameters

| Key | Effect when true |
|---|---|
| `stock.picking_no_auto_reserve` | No automatic re-reservation after receipts and internal transfers ([`stock_move.py:2750`](../addons/stock/models/stock_move.py#L2750)) |
| `stock.no_auto_scheduler` | No immediate reordering-rule trigger at transfer confirmation ([`stock_move.py:2726`](../addons/stock/models/stock_move.py#L2726)) |
| `stock.cancel_moves_origin` | Cancelling a move with Cancel Next Move also cancels its origin moves ([`stock_move.py:2273`](../addons/stock/models/stock_move.py#L2273)) |
| `stock.intercompany_auto_unpack` | Packages sent to another company are unpacked on validation ([`stock_picking.py:1045`](../addons/stock/models/stock_picking.py#L1045)) |

---

## Dependencies

| Requires | Why |
|---|---|
| `product` | Products, units, packagings; `is_storable` lives here ([`__manifest__.py`](../addons/stock/__manifest__.py)) |
| `barcodes_gs1_nomenclature` | Barcode and GS1 parsing for locations, lots, packages |
| `digest` | Inventory KPIs in the periodic digest email |
| `sale` + `stock_account` (for `sale_stock`) | Sale orders; valuation of the delivery moves ([`__manifest__.py:20`](../addons/sale_stock/__manifest__.py#L20)); `sale_stock` auto-installs |

| Works With (optional) | What It Adds |
|---|---|
| `purchase_stock` | Buy route, RFQs from procurements, vendor lead times in reordering rules |
| `mrp` | Manufacture route, kits, component and finished-product moves ([`mrp.md`](mrp.md)) |
| `stock_account` | Valuation and COGS ([`stock_valuation.md`](stock_valuation.md)) |
| `product_expiry` | Lot dates, FEFO, expired stock excluded from reservation |
| `stock_dropshipping` | Dropship route and operation type |
| `stock_delivery`, `stock_fleet`, `stock_sms` | Carriers and labels, transport management, SMS confirmation |
| `stock_barcode`, `quality_control` (enterprise) | Barcode app; quality checks on transfers |

---

## Key Methods

| Method | Role |
|---|---|
| [`SaleOrderLine._action_launch_stock_rule()`](../addons/sale_stock/models/sale_order_line.py#L375) | Builds procurements from confirmed goods lines |
| [`StockRule.run()`](../addons/stock/models/stock_rule.py#L426) | Finds a rule per procurement and dispatches by action |
| [`StockRule._get_rule()`](../addons/stock/models/stock_rule.py#L546) | Route priority and location walk |
| [`StockMove._action_confirm()`](../addons/stock/models/stock_move.py#L1770) | Sets Waiting / Waiting Another Move, raises upstream procurements, groups into transfers |
| [`StockMove._action_assign()`](../addons/stock/models/stock_move.py#L2135) | Reservation |
| [`StockPicking.button_validate()`](../addons/stock/models/stock_picking.py#L1176) | Checks, backorder wizard, validation |
| [`StockMove._action_done()`](../addons/stock/models/stock_move.py#L2350) | Quant updates, push rules, downstream reservation, backorders |
| [`StockMove._push_apply()`](../addons/stock/models/stock_move.py#L1270) | Next step of multi-step flows |
| [`StockPicking._create_return()`](../addons/stock/models/stock_picking.py#L976) | Draft return transfer |
| [`StockWarehouseOrderpoint._procure_orderpoint_confirm()`](../addons/stock/models/stock_orderpoint.py#L748) | Reordering rules to procurements |
| [`StockRule._run_scheduler_tasks()`](../addons/stock/models/stock_rule.py#L681) | Nightly scheduler |

---

## Gotchas & Non-Obvious Behavior

- **Buy and Manufacture are not product checkboxes.** They are warehouse routes that apply when the product has a vendor or a regular BoM. With only a vendor, a sale order never creates an RFQ; add Replenish on Order (MTO) or a reordering rule.
- **MTO without a vendor or BoM blocks confirmation** with "No rule has been found to replenish ...".
- **Reserve never procures**, and changing routes or supply methods does not affect moves that already exist.
- **Validating without marking anything picked processes every reserved quantity.** Mark lines picked to validate only part of a transfer.
- **Return lines start at 0.** Use Return All for a full return; the portal request only produces a label, not a transfer.
- **A printed transfer receives no new moves**: later quantity increases on the order create a second transfer.
- **Changing the delivery address updates open transfers**, except when the same save also edits order lines.
- **Negative stock is allowed**; nothing in `stock` prevents validating more than is on hand.
- **Scrap destination**: the company scrap location is its Inventory Loss location with the lowest id. Installation creates the "Inventory adjustment" location before any "Scrap" location and creates "Scrap" only for companies that have no Inventory Loss location yet, so scraps usually land in "Inventory adjustment" unless another location is chosen on the scrap form ([`res_company.py:165`](../addons/stock/models/res_company.py#L165)).
- **Suggest Min-Max needs a Daily Demand.** It scales Min and Max by their ratio to the stored Daily Demand; a rule whose Daily Demand is 0 gets Min = Max = 0 ([`stock_orderpoint_suggest.py:29`](../addons/stock/wizard/stock_orderpoint_suggest.py#L29)).
- **Replenishment Horizon defaults to 365 days**, so reordering rules count demand planned up to a year ahead. Lower it for just-in-time ordering.
- **Tracked quants come first**: at equal strategy, quants with a lot are reserved before untracked ones of the same product.
- **Goods without Track Inventory still create deliveries**; their moves are Ready at once and never reserved.
- **Several warehouses force Storage Locations on**, and Storage Locations cannot be switched off while a company has more than one warehouse.
- **Warehouse addresses are transit locations**: delivering to a warehouse's own partner sends goods to a transit location, not to a customer.
- **Route assignments are stored on templates**: the `stock_route_product` table holds `product.template` ids in its `product_id` column; query it through the template, not the variant.
- **Delivery Status "Started"** means a first step (e.g. PICK) is done but nothing reached the customer yet.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`stock_valuation.md`](stock_valuation.md) — valuation, COGS, periodic vs perpetual (configured in `account`)
- [`inventory_forecast_report.md`](inventory_forecast_report.md) — forecast report and availability widget
- [`mrp.md`](mrp.md) — manufacturing orders, kits, Manufacture rule
- [`accounting_multicompany_branches.md`](accounting_multicompany_branches.md) — inter-company flows and security
