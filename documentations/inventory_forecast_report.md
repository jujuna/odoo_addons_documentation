# Inventory Forecast Report

> **Module:** `stock` (+ `sale_stock`, `purchase_stock`, `mrp`, `stock_account`, `product_expiry`) | **Path:** [`addons/stock/report/stock_forecasted.py`](../addons/stock/report/stock_forecasted.py)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

The Forecasted Report answers, per product and per warehouse, "how much will I have, and which demand will be served by which supply?". It combines three views of the same stock: header totals (on hand, incoming, outgoing, forecasted, lead time), a stepped graph of the forecasted stock level day by day, and a table that matches every open outgoing move to a supply source: stock already reserved, free stock, stock in transit inside the warehouse, or a specific receipt. Demand that nothing covers is shown in red as **Not Available**. Planners use it to decide whether to replenish, which delivery gets priority, and which receipt should be assigned to which order. The same matching engine feeds the colored availability badge on transfer and MO lines.

---

## How to Open It

| Entry point | Opens |
|---|---|
| Product form → **Forecasted** smart button | Report for the template ([`action_product_tmpl_forecast_report()`](../addons/stock/models/product.py#L1271)) or the variant ([`action_product_forecast_report()`](../addons/stock/models/product.py#L690)) |
| Availability badge on a transfer or MO component line | Report for that product, warehouse of the move, with the move's lines highlighted ([`stock.move.action_product_forecast_report()`](../addons/stock/models/stock_move.py#L1062), context `move_to_match_ids`) |
| Reordering rule / replenishment line | Report for the rule's warehouse, with its lead horizon date and quantity to order in the context ([`action_product_forecast_report()`](../addons/stock/models/stock_orderpoint.py#L345)) |
| MO, purchase line | Same client action, tag `stock_forecasted` ([`stock_forecasted_product_product_action`](../addons/stock/views/stock_forecasted.xml#L4)) |

The page is the OWL client action [`StockForecasted`](../addons/stock/static/src/stock_forecasted/stock_forecasted.js#L14). It loads the warehouses, picks the first one when the context has none, and calls `get_report_values` on `stock.forecasted_product_template` or `stock.forecasted_product_product` ([`_getReportValues()`](../addons/stock/static/src/stock_forecasted/stock_forecasted.js#L42)). Switching warehouse writes `warehouse_id` into the context and replaces the current action ([`updateWarehouse()`](../addons/stock/static/src/stock_forecasted/stock_forecasted.js#L87), [`reloadReport()`](../addons/stock/static/src/stock_forecasted/stock_forecasted.js#L95)). The component follows OWL 3: `props = useProps(standardActionServiceProps)` and the context and warehouse list held with `proxy()`.

---

## The Big Picture — Three Sources

```
                      warehouse_id in context
                               │
     ┌─────────────────────────┼──────────────────────────────┐
     ▼                         ▼                              ▼
 Header totals            Stepped graph                 Detail table
 product.product fields   report.stock.quantity          stock.forecasted_product_product
 (_compute_quantities)    (PostgreSQL view)              ._get_report_lines()
                                                              │
                                                              └─► also used by the availability
                                                                  badge on move lines
```

[`_get_report_data()`](../addons/stock/report/stock_forecasted.py#L156) builds the header and the lines for one warehouse: all locations under the warehouse view location count as "in the warehouse", and the warehouse **stock location** (`lot_stock_id`) and its children count as free stock. Without `warehouse_id` in the context, the first active warehouse is used ([`_get_warehouse()`](../addons/stock/report/stock_forecasted.py#L153)).

`location_final_id` does not exist in 20.0; use `forecasted_location_id` ("Forecasted Location", [`stock_move.py:86`](../addons/stock/models/stock_move.py#L86), `forecasted_location_id`).

---

## Part 1 — Header

### Quantities
[`_get_product_quantities()`](../addons/stock/report/stock_forecasted.py#L69) reads the product fields computed by [`_compute_quantities_dict()`](../addons/stock/models/product.py#L156) with the warehouse in the context:

| Header label | Field | Formula ([`product.py:266`](../addons/stock/models/product.py#L266), `qty_available`) |
|---|---|---|
| On Hand | `qty_available` | Sum of quant quantities in the warehouse locations |
| Incoming | `incoming_qty` | Sum of `product_qty` of moves in state waiting / confirmed / partially available / assigned that enter the warehouse |
| Outgoing | `outgoing_qty` | Same states, moves that leave the warehouse |
| Forecasted | `virtual_available` | On hand + incoming − outgoing − expired unreserved quantity; shown in red below zero |
| (used by buttons) | `free_qty` | On hand − reserved − expired unreserved quantity |

- For moves not done, "enters/leaves the warehouse" is judged on `forecasted_location_id` when set, else on the destination ([`_get_domain_locations_new()`](../addons/stock/models/product.py#L404)). A pick move from Stock to Output whose chain ends at the customer already counts as outgoing.
- Draft moves are never in these numbers. [`_get_report_header()`](../addons/stock/report/stock_forecasted.py#L112) sums them separately (`draft_picking_qty`) for the table footer.
- The expired unreserved quantity is only subtracted when the context has `with_expiration` ([`product.py:225`](../addons/stock/models/product.py#L225), `with_expiration`).
- A kit's quantities are derived from its components (`mrp` override of `_compute_quantities_dict`, [`product.py:239`](../addons/mrp/models/product.py#L239)).
- With `to_date` in the past, on hand is rebuilt backwards: current quants minus done move lines received after that date plus done move lines sent after it ([`product.py:231`](../addons/stock/models/product.py#L231), `dates_in_the_past`).

### Lead time
[`_get_product_leadtime()`](../addons/stock/report/stock_forecasted.py#L98) finds the rules that replenish the warehouse stock location and sums their delays with `_get_lead_days()` (purchase lead times, manufacturing lead time and days to prepare, transfer delays). The header shows the smallest total among the displayed variants and the earliest possible arrival = today + that delay; a popover lists each delay ([`leadTime`](../addons/stock/static/src/stock_forecasted/forecasted_header.js#L32)).

### Additions by other modules
| Module | Adds |
|---|---|
| `stock_account` | Stock value of the warehouse quants, for Inventory Administrators only ([`stock_forecasted.py:11`](../addons/stock_account/report/stock_forecasted.py#L11), `_get_report_header`) |
| `product_expiry` | "To remove" quantity (expired stock), expired quants excluded from free stock ([`stock_forecasted.py:11`](../addons/product_expiry/report/stock_forecasted.py#L11), `to_remove_qty`) |
| `mrp` | Draft MO quantities and draft component demand (`draft_production_qty`, [`stock_forecasted.py:25`](../addons/mrp/report/stock_forecasted.py#L25), `_get_report_header`) |
| `sale_stock`, `purchase_stock` | Draft quotation and draft purchase quantities with links (`draft_sale_qty`, `draft_purchase_qty`) |

---

## Part 2 — The Stepped Graph

The graph is a standard graph view embedded in the page, on model [`report.stock.quantity`](../addons/stock/report/report_stock_quantity.py#L7), a PostgreSQL **view** (`_auto = False`) recreated by [`init()`](../addons/stock/report/report_stock_quantity.py#L36) at module install or update. The page filters it on `state = 'forecast'`, the warehouse and the product ([`graphDomain`](../addons/stock/static/src/stock_forecasted/stock_forecasted.js#L107)).

### What the view contains
One row per product × warehouse × day × state:

| `state` | Label | Rows |
|---|---|---|
| `forecast` | Forecasted Stock | Stock level of the day |
| `in` | Forecasted Receipts | Open moves entering the warehouse that day |
| `out` | Forecasted Deliveries | Open moves leaving that day (negative) |

How it is built:
1. **Moves kept:** storable products, not draft or cancelled, whose source warehouse differs from the destination warehouse; done moves only if dated within the past period. The destination of an open move is `forecasted_location_id`, else `location_dest_id`. Moves between two warehouses are duplicated (`GENERATE_SERIES(0, 1)`) so each warehouse gets its own out or in row.
2. **Base level:** each quant in an internal location of a warehouse, or in a transit location, is repeated on every day from today − period to today + period.
3. **Corrections:** a done move adds back its quantity on the days before it happened (so the past shows the stock of that day); an open move adds its signed quantity from its date (or the start of the window) to the end.
4. Rows are summed per product, template, state, date, company and warehouse.

**Period:** system parameter `stock.report_stock_quantity_period` in months, default 3, read with `get_int` when the view is created ([`report_stock_quantity.py:49`](../addons/stock/report/report_stock_quantity.py#L49), `report_period`). Changing it takes effect only after the view is rebuilt (module update).

### Rendering
[`StockForecastedGraphRenderer`](../addons/stock/static/src/stock_forecasted/forecasted_graph.js#L5) makes every dataset `stepped` and blanks the points where no dataset changes, keeping the first and last point.

---

## Part 3 — The Detail Table (Reconciliation)

[`_get_report_lines()`](../addons/stock/report/stock_forecasted.py#L239) builds the table.

### Which moves, in which order
- **Outgoing** and **incoming** moves come from [`_move_domain()`](../addons/stock/report/stock_forecasted.py#L30) restricted to waiting, confirmed, partially available and assigned moves with a non-zero demand ([`_move_confirmed_domain()`](../addons/stock/report/stock_forecasted.py#L55)). An in comes from outside the warehouse into it; an out starts inside and its destination, or its forecasted location, is outside.
- Outs are processed in two groups ([`stock_forecasted.py:332`](../addons/stock/report/stock_forecasted.py#L332), `past_domain`): first those whose **reservation date** is today or earlier (by priority, date, id), then the others (by reservation date, priority, date, id; no reservation date last).
- Ins are ordered by priority, date, id.

`reservation_date` ([`_compute_reservation_date()`](../addons/stock/models/stock_move.py#L756)) depends on the operation type's **Reservation Method**: *Before scheduled date* gives move date − **Days** (or **Days when starred** for starred moves); *Manually* gives none; *At Confirmation* sets today when the move is confirmed. So moves that reserve now are served first, and starred moves that reserve earlier move up.

### Chains
For each out, the report collects its upstream moves with [`_rollup_move_origs()`](../addons/stock/models/stock_move.py#L2796), stopping at incoming moves ([`stock_forecasted.py:349`](../addons/stock/report/stock_forecasted.py#L349), `_rollup_move_origs`). In a 3-step delivery the OUT therefore sees the reservations of its PACK and PICK. Each in knows its downstream moves ([`_rollup_move_dests()`](../addons/stock/models/stock_move.py#L2793)), which links a receipt to the delivery it was procured for. Caches are prefetched first (`_rollup_move_origs_fetch`, `_rollup_move_dests_fetch`).

### Stock counters
Quants of the warehouse are summed per product and location; quantities in children of the stock location are also added to the stock location ([`stock_forecasted.py:393`](../addons/stock/report/stock_forecasted.py#L393), `currents`). Then, for all outs of a product:
1. **Reserved stock** ([`_get_out_move_reserved_data()`](../addons/stock/report/stock_forecasted.py#L240)): the reserved quantity of the out and its upstream moves. A pick or pack shared by several outs is counted once (`used_reserved_moves`).
2. **Taken from stock** ([`_get_out_move_taken_from_stock_data()`](../addons/stock/report/stock_forecasted.py#L269)): for unreserved upstream moves, what free stock at their source location can cover. For chained moves, only what the previous step delivered and siblings did not take.

**Free stock** = what remains at the stock location. **Transit stock** = what remains elsewhere in the warehouse (outside the stock location tree), e.g. in Input or Output ([`stock_forecasted.py:423`](../addons/stock/report/stock_forecasted.py#L423), `transit_stock`).

### Lines per out
For each out, in order, until its demand is covered:

| Step | Line | `document_in` | `in_transit` | `replenishment_filled` |
|---|---|---|---|---|
| Reserved | Reserved quantity, with the reserving document | — | yes if the reserving move has upstream moves | yes |
| Free stock | Quantity taken from stock | — | no | yes |
| In transit | Quantity covered by transit stock | — | yes | yes |
| Linked receipts | Quantity from receipts procured for this out ([`_reconcile_out_with_ins()`](../addons/stock/report/stock_forecasted.py#L305)) | receipt | no | yes |
| Any receipt | Second pass over every receipt of the product, after all outs had their linked receipts | receipt | no | yes |
| Not available | What is still uncovered | — | no | **no** |

A receipt can be split across several outs. After the outs, the product gets: a **Free Stock in Transit** line for unused transit stock, the **Free Stock** line ([`_free_stock_lines()`](../addons/stock/report/stock_forecasted.py#L485); shown even at zero when the product has no other line), and one line per receipt quantity nobody uses.

Each line ([`_prepare_report_line()`](../addons/stock/report/stock_forecasted.py#L174)) carries the source documents (`_get_source_document()`: the picking, the MO for component and finished moves in `mrp`, the order in sales and purchase modules), receipt and delivery dates, late flags (`is_late` when the receipt comes after the delivery date), the reservation document and `is_matched` for highlighted moves.

### What the user sees
Columns: **Available**, **Outgoing**, **Used by**, action, **Delivery Date**. The **Available** cell reads ([`forecasted_details.xml`](../addons/stock/static/src/stock_forecasted/forecasted_details.xml#L40), `document_in`):

| Line | Available cell |
|---|---|
| Reconciled | Receipt link: "quantity expected on date" |
| In transit, with an out | Stock In Transit |
| In transit, no out | Free Stock in Transit |
| Reserved or free stock for an out | Stock To Reserve: total |
| Free stock | Free Stock |
| Uncovered | Not Available (row in red) |

Consecutive lines from the same receipt, or of the same on-hand or not-available group, are merged ([`_mergeLines()`](../addons/stock/static/src/stock_forecasted/forecasted_details.js#L154)). Below the lines: **Forecasted Inventory**, draft rows (Incoming / Outgoing Draft Transfer, plus draft MOs, quotations and draft purchases from the other modules) and **Forecasted with Pending** = forecasted + draft in − draft out ([`futureVirtualAvailable()`](../addons/stock/static/src/stock_forecasted/forecasted_details.js#L231)).

### Actions in the table
| Action | Shown when | Effect |
|---|---|---|
| Star (priority) | The out belongs to a transfer | Toggles the transfer's priority, then reloads |
| **Reserve** / **Unreserve** | Inventory users (`user_can_edit_pickings`), transfer lines not in transit; Unreserve on reserved lines | Reserve or unreserve the out and its upstream moves ([`action_reserve_linked_picks()`](../addons/stock/report/stock_forecasted.py#L489), [`action_unreserve_linked_picks()`](../addons/stock/report/stock_forecasted.py#L497)) |
| **Assign** / **Unassign** | Line has both a receipt and a delivery | `stock.allocation.report.action_assign` / `action_unassign`: links the receipt to the delivery as its origin (make-to-order link, shared references, optional **Location for allocation** on the receipt's operation type), splitting moves when quantities differ ([`action_assign()`](../addons/stock/report/stock_allocation_report.py#L207)) |

Header buttons: **Replenish** opens the `product.replenish` wizard with the warehouse; **Update Quantity** opens the quants in inventory mode ([`_onClickReplenish()`](../addons/stock/static/src/stock_forecasted/forecasted_buttons.js#L31)).

---

## Part 4 — Availability Badge on Move Lines

`stock.move` fields [`forecast_availability` and `forecast_expected_date`](../addons/stock/models/stock_move.py#L194) (computed, not stored, `compute_sudo`) are filled by [`_compute_forecast_information()`](../addons/stock/models/stock_move.py#L528):

| Move | `forecast_availability` |
|---|---|
| Not storable | Its quantity |
| Assigned | Reserved quantity |
| Draft, free quantity covers the demand | Free quantity |
| Draft outgoing, free quantity short | Forecasted quantity if it covers the demand, else forecasted quantity − demand |
| Waiting / confirmed / partially available outgoing | From the reconciliation engine (below) |
| Internal, free quantity covers the demand | Free quantity |
| Receipt | Forecasted quantity at its date (+ its own quantity while draft) |

Free and forecasted quantities are read for the move's warehouse at the move date (or now if earlier). For unreserved outgoing moves, [`_get_forecast_availability_outgoing()`](../addons/stock/models/stock_move.py#L2815) runs `_get_report_lines(..., read=False)` for the move's warehouse and source location: covered lines add up to the available quantity, an uncovered line gives a negative value, and the expected date is the latest receipt date among the lines serving the move.

The badge ([`ForecastWidgetField`](../addons/stock/static/src/widgets/forecast_widget.js#L7)):

| Badge | Condition |
|---|---|
| **Available** (green) | Availability ≥ demand and no expected date |
| **Exp** *date* (yellow) | Covered by a future receipt on or before the deadline |
| **Exp** *date* (red) | Covered, but the expected date is after the move deadline |
| **Not Available** (red) | Availability < demand |

It shows on operation lines of internal and outgoing transfers that are not done or cancelled ([`stock_picking_views.xml:375`](../addons/stock/views/stock_picking_views.xml#L375), `forecast_widget`) and on MO component lines ([`mrp_production_views.xml:532`](../addons/mrp/views/mrp_production_views.xml#L532), `forecast_widget`). Clicking it opens the report for storable products.

---

## Configuration

| Setting | Where | Effect |
|---|---|---|
| `stock.report_stock_quantity_period` | System Parameters | Months shown before and after today in the graph (default 3); rebuild the view after a change |
| **Reservation Method**, **Days**, **Days when starred** | Operation type | Drive `reservation_date`, hence the order in which outs are served |
| **Location for allocation** (`allocated_location_id`) | Operation type of receipts | Where assigned receipts are sent ([`stock_picking_type.py:68`](../addons/stock/models/stock_picking_type.py#L68), `allocated_location_id`) |
| Inventory User group | Users | Reserve / Unreserve links ([`stock_forecasted.py:171`](../addons/stock/report/stock_forecasted.py#L171), `user_can_edit_pickings`) |
| Inventory Administrator group | Users | Stock value in the header (`stock_account`) |

---

## Extension Points

| Hook | Used by |
|---|---|
| [`_get_report_header()`](../addons/stock/report/stock_forecasted.py#L112) | `mrp`, `sale_stock`, `purchase_stock`, `stock_account`, `product_expiry` add header data |
| [`_prepare_report_line()`](../addons/stock/report/stock_forecasted.py#L174) | `mrp` adds the MO of component moves; `sale_stock` and `product_expiry` add line data |
| [`_move_draft_domain()`](../addons/stock/report/stock_forecasted.py#L49) | `mrp` removes MO moves from the draft transfer rows |
| `_get_quant_domain()`, `_free_stock_lines()` | `product_expiry` excludes expired quants and splits free stock by removal date |
| `stock.move._get_source_document()` | Modules return their document for the table links |
| `report.stock.quantity._get_product_qty_col()` | `product_expiry` counts only reserved quantity of quants past their removal date ([`report_stock_quantity.py:14`](../addons/product_expiry/report/report_stock_quantity.py#L14), `_get_product_qty_col`) |

JS side: `ForecastedDetails` groups lines through `_groupLines()` so modules can add groups, and `mrp`, `sale_stock`, `purchase_stock` extend its template with their draft rows.

---

## Gotchas & Non-Obvious Behavior

- **Header forecast ≠ graph.** The header is a formula over open moves at any date; the graph spreads moves over the window by date and only includes moves between warehouses (transfers inside one warehouse do not appear).
- **Draft moves are not reconciled.** They only appear in the draft rows and in "Forecasted with Pending".
- **Order is reservation date, not delivery date.** Outs that may reserve today are served before later ones, whatever their delivery date.
- **One warehouse at a time.** Stock in another warehouse never covers demand; inter-warehouse transfers show as a receipt in one and a delivery in the other.
- **Sub-locations count as stock.** Quants in children of WH/Stock are free stock; quants elsewhere in the warehouse are transit stock that covers demand but cannot be reserved yet.
- **Shared pick/pack.** A pick feeding two deliveries is counted once across them.
- **Availability badges are computed on read.** Every open outgoing move line runs the reconciliation for its product and warehouse, with sudo.
- **The graph view definition is static.** It always reads live moves and quants, but the period and SQL only change when the view is recreated.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`inventory.md`](inventory.md) — moves, reservations, routes and multi-step transfers
- [`mrp.md`](mrp.md) — MOs, component demand and manufacturing lead times shown in the report
