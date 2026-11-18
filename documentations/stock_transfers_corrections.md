# Transfers and Their Corrections — Stock, Sales, Purchase and Accounting

> **Modules:** `stock` + `sale_stock` + `purchase_stock` + `stock_account` (with the valuation half that lives in `account`), and our `rs_waybill` | **Paths:** [`addons/stock/`](../addons/stock/), [`addons/sale_stock/`](../addons/sale_stock/), [`addons/purchase_stock/`](../addons/purchase_stock/), [`addons/stock_account/`](../addons/stock_account/), [`custom_addons/gec_odoo_modules/rs_waybill/`](../custom_addons/gec_odoo_modules/rs_waybill/)
> Verified against the Odoo 20 source on 2026-09-25, and by 39 live scenarios on a throwaway database (generic chart, perpetual AVCO and FIFO, periodic AVCO). Results from those runs are marked **(Tn)** and listed in the [Scenario Log](#scenario-log).

## Read This First

These six facts decide almost every correction. They surprise people who know older Odoo versions.

1. **Correcting a done transfer posts no journal entry.** Receipts, deliveries and returns have no stock journal entry of their own in 20. Accounting for goods happens on the vendor bill (debit Stock Valuation), on the customer invoice or credit note (COGS lines), and in the Stock Closing. A correction only rewrites `stock.move.value` (T3, T5).
2. **A correction can rewrite a posted invoice.** When a correction changes the unit cost of goods already sold, Odoo rewrites the COGS lines of the posted customer invoice in place (T21, T22, T23). If that invoice is in a locked period, the whole correction is refused (T26).
3. **Quantities follow, invoices do not.** Delivered and received quantities recompute by themselves. Posted invoices and bills keep their quantities. **Create Invoice** or **Create Bill** then produces the credit note or refund for the difference (T3, T5). With "Invoice on ordered quantities", nothing produces it (T19).
4. **Several statuses lie after a correction.** Delivery Status shows "Fully Delivered" after a cancelled backorder, a cancelled second step or a full return (T12, T32). Receipt status shows "full" when short. A cancelled sale order can hold delivered goods that will never be invoiced (T14).
5. **Every return lowers delivered and received quantities.** The "update SO/PO quantities" switch (`to_refund`) has no field in any 20.0 view (T6, T7).
6. **A done transfer cannot be reset, cancelled or deleted.** The correction tools are: unlock and edit, return, exchange, and inventory adjustment (T35).

---

## What It Does & Why It Exists

A transfer (`stock.picking`) records goods moving from one location to another: a receipt from a vendor, a delivery to a customer, an internal step such as a pick. Each product line is a stock move (`stock.move`). The detail (lot, shelf, package, quantity) is a move line (`stock.move.line`). Validating a transfer updates on-hand quantities (quants) and gives each move a value.

The transfer sits in the middle of four apps:

- **Sales** reads done deliveries and returns to compute Delivered, which drives invoicing.
- **Purchase** reads done receipts and vendor returns to compute Received, which drives billing.
- **Valuation** (`stock_account`) gives every valued move a signed value and derives the product cost from them.
- **Accounting** posts the value later: on bills, on invoices (COGS), and at the Stock Closing.

This document explains that web. It then walks through every way a user can correct a transfer, and what each correction changes in Stock, Sales, Purchase, Valuation and Accounting. Warehouse managers, accountants and implementation consultants are the readers. Basic stock concepts (routes, reservation, backorders) are in [`inventory.md`](inventory.md); costing methods are in [`stock_valuation.md`](stock_valuation.md).

---

## The Big Picture — How the Documents Connect

```
 SALE                           STOCK                                          PURCHASE
 sale.order.line ◄─sale_line_id── stock.move (OUT, return IN)                  purchase.order.line
   qty_delivered  ◄──────────────   state, quantity, to_refund                   qty_received
   qty_invoiced                     origin_returned_move_id ──► original move    qty_invoiced
   qty_to_invoice                   move_orig_ids / move_dest_ids (chains)          │
      │                             value (signed), remaining_qty                   │
      ▼                                  │            ▲                             ▼
 customer invoice line ──cogs_move_ids──►│            │◄──────purchase_line_id── stock.move (IN, vendor return)
   COGS lines (display_type='cogs') ◄─cogs_aml_ids──┘            │
      │                                                         vendor bill line ──► sets receipt value
      ▼                                                          (account = Stock Valuation)
 ACCOUNTING: Stock Valuation account = bills − COGS ± closing;  product cost = replay of move values
```

The links that matter when something is corrected:

| Link | Where it is | What it is used for |
|---|---|---|
| `stock.move.sale_line_id` | `sale_stock` | Delivered quantity; copied to return moves ([`stock.py:399`](../addons/sale_stock/models/stock.py#L399)) |
| `stock.move.purchase_line_id` | `purchase_stock` | Received quantity; the vendor bill value flows back through it |
| `origin_returned_move_id` | [`stock_picking.py:911`](../addons/stock/models/stock_picking.py#L911) | Marks a return; the return is valued from this move |
| `move_orig_ids` / `move_dest_ids` | `stock` | Chains (PICK → OUT, receipt → MTO delivery). Correcting an upstream move re-reserves the downstream one |
| `return_id` / `return_ids` | `stock` | Return transfer ↔ original transfer |
| `backorder_id` | `stock` | Backorder ↔ original transfer |
| `to_refund` | [`stock_move.py:27`](../addons/stock_account/models/stock_move.py#L27) (default True) | Whether a return changes Delivered/Received. No view shows it |
| `cogs_move_ids` (invoice line) | [`account_move.py:127`](../addons/sale_stock/models/account_move.py#L127) | Moves behind an invoice line, found through its sale line; they give the COGS unit cost |
| `cogs_aml_ids` (move) | [`stock.py:20`](../addons/sale_stock/models/stock.py#L20) | COGS lines already posted for this move's sale line; re-priced when the move value changes |
| `stock.move.account_move_id` | [`stock_move.py:61`](../addons/stock_account/models/stock_move.py#L61) | Stock journal entry, only for moves that touch a location with a valuation account |

An invoice line has no direct link to a stock move. It reaches its moves only through the sale line (or the purchase line for bills).

---

## States and What Each Allows

### Transfer and move states

| Transfer state | Means | Stock effect | Accounting effect | Allowed corrections |
|---|---|---|---|---|
| Draft | Not confirmed | None | None | Edit anything; delete |
| Waiting Another Operation / Waiting | Confirmed, not reserved | Forecast only | None | Edit lines, Cancel |
| Ready | Stock reserved | Reserved quants | None | Edit, Unreserve, Cancel, Split |
| Done | Validated | Quants moved, move valued | Only for locations with a valuation account | Unlock and edit, Return, Scrap. No Cancel, no Delete |
| Cancelled | Cancelled | None | None | Nothing; the transfer is not re-created by itself |

The transfer state is computed from its moves ([`_compute_state()`](../addons/stock/models/stock_picking.py#L331)). A move is one of Draft, Waiting Another Move, Waiting, Partially Available, Available, Done, Cancelled. There is no "reset to draft" for a transfer in 20. `_action_reset_to_draft()` and `_action_reset_to_progress()` exist on `stock.move`, but only manufacturing orders call them ([`mrp_production.py:2039`](../addons/mrp/models/mrp_production.py#L2039)).

### Locked and unlocked

Every transfer is created locked (`is_locked`, default True, [`stock_picking.py:138`](../addons/stock/models/stock_picking.py#L138)). **Unlock** appears only on done or cancelled transfers, and only for Inventory Administrators ([`stock_picking_views.xml:196`](../addons/stock/views/stock_picking_views.xml#L196)). The Python method has no group check ([`action_toggle_is_locked()`](../addons/stock/models/stock_picking.py#L1348)), so code and RPC can toggle it.

| On a done transfer | Locked | Unlocked |
|---|---|---|
| Quantity per move | Read-only | Editable |
| Demand | Read-only | Editable, but it changes nothing in stock |
| Detailed operations: lot, locations, package, owner, quantity | Read-only | Editable |
| Add a product line | No | Yes, created directly as done |
| Date of transfer (`date_done`) | Read-only | Editable, unless it falls in a locked accounting period |
| Partner, source/destination of the transfer, operation type | Read-only | Still read-only |
| Product or unit of measure of an existing line | Read-only | Still refused: "Changing the product is only allowed in 'Draft' state." |

Locking also affects open transfers. Demand is editable only while the move is draft or the transfer is unlocked (`is_initial_demand_editable`, [`stock_move.py:372`](../addons/stock/models/stock_move.py#L372)).

---

## How Each Number Is Computed

Every number below is recomputed from moves. None of them is copied at validation time. That is why corrections propagate, and why some numbers end up wrong.

| Number | Computed from | Recomputes when | Misleads when |
|---|---|---|---|
| SO line **Delivered** | Done moves to a customer (or inter-company transit) minus done returns with `to_refund`; moves into inventory locations (scrap, loss) are ignored ([`_prepare_qty_delivered()`](../addons/sale_stock/models/sale_order_line.py#L185), [`_get_outgoing_incoming_moves()`](../addons/sale_stock/models/sale_order_line.py#L316)) | A move's state, quantity, UoM or destination changes ([`sale_order_line.py:181`](../addons/sale_stock/models/sale_order_line.py#L181)) | Never; it is the most reliable number |
| SO line **To Invoice** | Ordered − invoiced (policy "ordered"), or delivered − invoiced (policy "delivered"); draft invoices count as invoiced, credit notes subtract ([`sale_order_line.py:1347`](../addons/sale/models/sale_order_line.py#L1347)) | Delivered or invoiced changes | Policy "ordered" ignores every delivery correction (T19) |
| SO **Invoice Status** | "To invoice" if any line has a non-zero To Invoice, negative included | Same | Shows "To Invoice" when a credit note is due (T5) |
| SO **Delivery Status** | Transfer states only: all done or cancelled means "Fully Delivered" ([`_compute_delivery_status()`](../addons/sale_stock/models/sale_order.py#L77)) | A transfer's state changes | Cancelled backorder, cancelled second step, full return, cancelled order (T12, T14, T32) |
| SO **Effective Date** | Earliest done delivery to a customer ([`sale_order.py:70`](../addons/sale_stock/models/sale_order.py#L70)) | `date_done` changes | — |
| PO line **Received** | Done moves from a supplier (or transit) minus vendor returns with `to_refund`; the second step of a 2-step reception does not count ([`_prepare_qty_received()`](../addons/purchase_stock/models/purchase_order_line.py#L62)) | A move's state, quantity or UoM changes ([`purchase_order_line.py:58`](../addons/purchase_stock/models/purchase_order_line.py#L58)) | — |
| PO line **To Bill** | Ordered − billed (control "ordered"), or received − billed (control "received") ([`purchase_order_line.py:210`](../addons/purchase/models/purchase_order_line.py#L210)) | Received or billed changes | Control "ordered" ignores receipt corrections |
| PO **Receipt status** | Transfer states: every receipt done or cancelled means "full", even when short ([`_compute_receipt_status()`](../addons/purchase_stock/models/purchase_order.py#L62)) | A receipt's state changes | Cancelled backorder, cancelled order |
| Move **value** | Signed (in +, out −). In moves: manual value, then posted bill, then PO price, then return origin, then cost ([`stock_valuation.md`](stock_valuation.md#incoming-move-value-priority)). Out moves: FIFO stack or current average/standard cost | Validation, a line edit, a date edit, a bill posted or reset, a PO price change | — |
| Product **cost** (`standard_price`, AVCO/FIFO) | Recomputed from move values ([`_update_standard_price()`](../addons/stock_account/models/product.py#L714)) | An incoming move is valued | Stays stale after backdating a delivery until the next receipt (T25) |
| Invoice **COGS lines** | Invoice quantity × average unit value of the sale line's moves; product cost when there are no moves ([`_get_cogs_value()`](../addons/stock_account/models/account_move_line.py#L80)) | Posting; later re-priced in place when a move value changes ([`_set_cogs()`](../addons/stock_account/models/account_move_line.py#L50)) | The COGS quantity never follows a delivery correction (T5, T19) |
| **Stock Valuation account** balance | Bills − COGS ± closing entries ± entries of locations with a valuation account | Posting of those documents only | After any correction until the next Stock Closing (T37) |

---

## The Odoo 20 Accounting Model for Stock

This is why corrections behave as they do.

**Where stock journal entries come from.** `_create_account_move()` has one caller, `_action_done()` ([`stock_move.py:248`](../addons/stock_account/models/stock_move.py#L248)). It creates an entry only when a move touches a location with a valuation account ([`_should_create_account_move()`](../addons/stock_account/models/stock_move.py#L755)). Only inventory-loss and production locations show that field ("Loss Account", "Cost of Production", [`stock_location_views.xml:11`](../addons/stock_account/views/stock_location_views.xml#L11)). The generic chart sets none, so a fresh database posts no stock entry at all, not even for adjustments or scrap (T35). A correction never goes through `_action_done()`, so it never posts one either.

| Event | Periodic (`periodic`) | Perpetual (`real_time`, UI "Perpetual (at invoicing)") |
|---|---|---|
| Receipt validated | Move valued, no entry | Move valued, no entry |
| Vendor bill posted | Line on the expense account (T36) | Line redirected to Stock Valuation ([`account_move_line.py:790`](../addons/account/models/account_move_line.py#L790)); the receipt takes the bill's price |
| Delivery validated | Move valued, no entry | Move valued, no entry |
| Customer invoice posted | No COGS | COGS lines: debit expense, credit Stock Valuation ([`_create_cogs_lines()`](../addons/account/models/account_move.py#L5966)) |
| Credit note posted | No COGS | Reversed COGS lines at the moves' average cost |
| Return validated | Move valued, no entry | Move valued, no entry |
| Scrap / inventory adjustment | No entry | Entry only if the inventory location has a Loss Account (T35) |
| **Correction of a done transfer** | **Nothing** | **Nothing posted; move values rewritten; posted COGS re-priced in place** |
| Stock Closing | Cron (daily/monthly) or manual | Manual only; the cron skips perpetual companies ([`_cron_post_stock_valuation()`](../addons/account/models/company.py#L1447)) |

- **Anglo-Saxon is not the switch you may expect.** `anglo_saxon_accounting` is read in one place: price-difference lines on vendor bills ([`account_move.py:6001`](../addons/account/models/account_move.py#L6001)). COGS lines and the bill redirection depend only on perpetual valuation and a storable product ([`_use_inventory_valuation()`](../addons/account/models/account_move_line.py#L3818)). With the flag off, a perpetual product still gets COGS (T36).
- **"Continental perpetual" is decided by the valuation account.** The closing posts a period variation only when the stock valuation account has both a Stock Variation and a Stock Expense account ([`_get_continental_realtime_variation_vals()`](../addons/account/models/company.py#L1522)).
- **gec20_prod1 today** (checked 2026-09-25): company defaults periodic valuation, standard cost; no location has a valuation account; `anglo_saxon_accounting` is off. Every correction there changes stock and move values only. Bills go to expense. The Stock Closing carries the difference.

---

## Correction Toolbox — What Each Tool Changes

| Correction | Stock | Sales | Purchase | Valuation | Accounting | Log |
|---|---|---|---|---|---|---|
| Unlock + edit done delivery quantity | Quants re-posted at once; negative allowed | Delivered recomputes; To Invoice can go negative | — | Move value rewritten; replay if needed | None; posted COGS re-priced only if the unit cost changes | T5, T16, T17 |
| Unlock + edit done receipt quantity | Same | MTO delivery re-reserved | Received recomputes; To Bill can go negative | Value rewritten; later sales re-costed | None; posted COGS of later sales re-priced | T3, T21, T22 |
| Edit lot / location / package on a done line | Quants moved between lots/locations; negative allowed | — | — | Replayed | None | T18 |
| Add a product to a done transfer | Stock moves at once | **No SO line** is created | — | Valued by the replay | None | T15 |
| Set a done quantity to 0 | Stock restored | Delivered 0; line "Nothing to invoice"; Delivery Status stays "Fully Delivered" | — | Value 0 | None | T16 |
| Return (customer) | New done transfer back to stock | Delivered decreases | — | Return valued at the original move's unit value | Credit note needed (COGS reversed on it) | T6 |
| Return (to vendor) | New done transfer to the vendor | — | Received decreases | Valued at current cost (AVCO/FIFO), not at the PO price | Vendor refund needed | T28 |
| Return of a return / Exchange | Goods go out again | Delivered increases again | — | Out move at current cost | Invoice for the difference | T8, T9 |
| Cancel an open transfer or backorder | Reservation released | Nothing re-procured; status may show "Fully Delivered" | Receipt status may show "full" | None | None | T12, T32 |
| Change SO line quantity | New or reduced delivery | Ordered changes; below Delivered is refused | — | — | — | T11, T13 |
| Cancel SO | Open transfers cancelled; done stay | Invoice status "Nothing to invoice" for delivered goods | — | Done moves keep their value | COGS never posted for delivered, uninvoiced goods | T14 |
| Change PO line quantity | New receipt, reduced receipt, or an automatic return | — | Ordered changes | — | — | T27 |
| Change PO line price | — | — | — | Unbilled part of done receipts revalued at once | Posted COGS re-priced | T24 |
| Cancel PO | Open receipts cancelled; done stay; MTO deliveries become Take From Stock | — | Refused while a bill is posted | — | Received, unbilled goods are never billed | T29, T30, T34 |
| Edit the transfer date | Move and line dates follow | Effective Date follows | — | Full replay from the earliest date | Posted COGS re-priced; refused in a locked period | T25, T26 |
| Post, reset or cancel a vendor bill | — | — | Billed changes | Receipt value switches between bill price and PO price | Posted COGS re-priced | T23 |
| Scrap | Moves stock to the loss location | Scrap from a done delivery does not change Delivered | — | Valued | Entry only with a Loss Account | T35 |
| Inventory adjustment | New done move to/from the loss location | — | — | Valued | Entry only with a Loss Account | T35 |

---

## Correction Deep Dives

### 1. Editing a done delivery (unlock and change the quantity)

**What happens in code.** Changing `quantity`, lot, locations, package, owner or UoM on a done move line runs `stock.move.line.write()` ([`stock_move_line.py:432`](../addons/stock/models/stock_move_line.py#L432)):

1. The old line is undone on the quants (plus at the source, minus at the destination), then redone with the new values ([`:503`](../addons/stock/models/stock_move_line.py#L503), [`:520`](../addons/stock/models/stock_move_line.py#L520)). Nothing checks availability, so quants can go negative (T17).
2. If the source goes negative, other transfers' reservations on that stock are freed ([`_free_reservation()`, :523](../addons/stock/models/stock_move_line.py#L523)).
3. A note "The done move line has been corrected." is posted on the transfer, not on the sale order or invoice ([`:512`](../addons/stock/models/stock_move_line.py#L512)).
4. Waiting next moves in a chain are unreserved and reserved again ([`:540`](../addons/stock/models/stock_move_line.py#L540)).
5. `stock_account` re-values the move from its date ([`stock_move_line.py:15`](../addons/stock_account/models/stock_move_line.py#L15), [`_set_value()`](../addons/stock_account/models/stock_move.py#L345)).
6. The move's `quantity` follows its lines; its demand does not change.

No `_action_done()` runs. Push rules, backorders, lot checks and the SO-line creation for extra products do not run either.

**Down, after the customer was invoiced (policy "delivered", T5).** 5 delivered and invoiced, corrected to 4:

| Record | Before | After the correction | After Create Invoice + post |
|---|---|---|---|
| Stock on hand | 5 | 6 | 6 |
| Delivery move value | −50 | −40 | −40 |
| SO Delivered / Invoiced / To Invoice | 5 / 5 / 0 | 4 / 5 / −1 | 4 / 4 / 0 |
| SO Invoice Status | Fully Invoiced | To Invoice | Fully Invoiced |
| Original invoice COGS | 50 | 50 (unit cost unchanged) | 50 |
| Credit note | — | — | 1 unit, 20 + tax; COGS reversal: debit Stock Valuation 10, credit expense 10 |

Create Invoice turns a negative total into a credit note. The wizard passes `final=True` by default, which is what lets negative lines in ([`sale_order.py:1985`](../addons/sale/models/sale_order.py#L1985), [`:2169`](../addons/sale/models/sale_order.py#L2169)).

**Down, policy "ordered" (T19).** The invoice was for 5 and the delivery is corrected to 3. To Invoice stays 0, the line stays "Fully Invoiced" and Delivery Status stays "Fully Delivered". Nothing signals that the customer paid for 2 units they never got. The invoice's COGS still covers 5 units, so the books show 20 less stock than the warehouse holds, until the Stock Closing.

**Up, beyond stock (T17).** 5 → 8 with only 5 on hand: the quant goes to −3, Delivered becomes 8, above the 5 ordered, and To Invoice becomes 8 under policy "delivered". An increase can go through without any stock.

**To zero (T16).** The move stays Done with quantity 0 and the stock comes back. Delivered becomes 0 and the line becomes "Nothing to invoice", but Delivery Status stays "Fully Delivered". Setting 0 is the only way to "remove" a done line; deleting one is refused: "Deleting product moves after the transfer is done? … Try changing the “done” quantity to 0 instead." ([`stock_move_line.py:550`](../addons/stock/models/stock_move_line.py#L550)).

**Up, when the order had no backorder (T38).** 4 of 10 delivered and invoiced, the rest cancelled, then corrected to 6: To Invoice becomes 2 and Create Invoice makes a second invoice for 2 units, with COGS 20.

### 2. Editing a done receipt

**Before the bill.** The move value follows the quantity at the PO price. Received recomputes and the PO chatter logs the change ([`purchase_order_line.py:62`](../addons/purchase_stock/models/purchase_order_line.py#L62)).

**After the bill (T3).** 10 received and billed, corrected to 8:

| Record | After the correction | After Create Bill |
|---|---|---|
| Receipt value | 80 (the bill still prices the 8 units) | 80 |
| PO Received / Billed / To Bill | 8 / 10 / −2 | 8 / 8 / 0 |
| PO billing status | Waiting Bills | Fully Billed |
| Vendor bill | Unchanged | Draft vendor refund: 2 × 10, credit Stock Valuation 20 |

Create Bill builds an ordinary bill with To Bill as quantity and switches it to a refund when the total is negative ([`purchase_order.py:876`](../addons/purchase/models/purchase_order.py#L876)).

**After part of the goods was sold (T21, T22).** The valuation replays from the receipt's date and re-costs every later delivery:

| Case | Before | Correction | After |
|---|---|---|---|
| AVCO: 10 @ 10, then 10 @ 20; 12 sold and invoiced | Sale value −180, invoice COGS 180 | First receipt 10 → 4 | Sale value −205.71; **posted COGS rewritten to 205.71**; cost 17.14; 2 left |
| FIFO: 5 @ 10, then 5 @ 20; 6 sold and invoiced | Sale value −70, COGS 70 | First receipt 5 → 3 | Sale value −90; **posted COGS rewritten to 90** |

`_set_value()` sees an incoming move that is already partly consumed and calls `_correct_inventory_valuation()` from the earliest impacted date ([`stock_move.py:356`](../addons/stock_account/models/stock_move.py#L356), [`product.py:247`](../addons/stock_account/models/product.py#L247)). Each rewritten out value re-prices the linked COGS lines ([`stock_move.py:194`](../addons/stock_account/models/stock_move.py#L194)). If one of those invoices is in a locked period, the write fails with "You cannot add/modify entries prior to and inclusive of: Global Lock Date (…)" and the correction is refused (T26). A correction that does not change the unit cost (all receipts at the same price) goes through, because the COGS amount stays the same.

**MTO receipt (T34).** A receipt that feeds a make-to-order delivery re-reserves that delivery: 5 → 3 leaves the delivery Partially Available, with 3 of 5 reserved and demand unchanged.

### 3. Changing lot, location, package or owner on a done line

The same write path re-posts the quants (T18):

- Lot A → B on a delivered line: LOT-A goes back up by 3, LOT-B goes down by 3. The lot's customer history (`stock.lot.partner_ids`) is not rewritten: LOT-A still lists the customer and LOT-B does not (T39). A recall on LOT-B would miss this customer.
- A new source sub-location with less stock than the line quantity goes negative (−2 in T18). Nothing warns.
- Valuation replays from the move date. A line redirected to or from a non-valued location changes the move's valued quantity. [Likely] An unvalued internal move whose line is redirected to a loss location is not re-valued, because `is_in`/`is_out` are stored on state and lines only ([`stock_move.py:86`](../addons/stock_account/models/stock_move.py#L86)).
- A serial number already in stock elsewhere is checked before the write, not after; a duplicate serial set by the correction is not re-checked [Likely, from the order of `_check_quantity()` and `write`].

### 4. Adding a product to a done transfer

On an unlocked done transfer, a new line is created directly as done (`additional=True`, [`stock_move.py:801`](../addons/stock/models/stock_move.py#L801), [`:855`](../addons/stock/models/stock_move.py#L855)). Stock moves at once and the move is valued, but three things are skipped (T15):

- **No sale order line.** The hook that adds a line with ordered 0 for an unplanned product runs only during validation ([`_action_synch_order()`](../addons/sale_stock/models/stock.py#L93), [`stock.py:302`](../addons/sale_stock/models/stock.py#L302)). The product left the warehouse and will never be invoiced. The same product added *before* validation gets its SO line (ordered 0, delivered 1).
- No lot checks, no lot creation from a typed lot name.
- No push rules, so no next step in a multi-step flow.

Create a separate delivery from the sale order instead (add the SO line, let Odoo procure it).

### 5. Returns

**How a return is made.** `stock.return.picking` was removed in 20 (commit `36b4a0f5fb2b`). **Return** on a done transfer calls `_create_return()` ([`stock_picking.py:976`](../addons/stock/models/stock_picking.py#L976)), which:

- first unreserves the waiting next moves of the original transfer ([`:978`](../addons/stock/models/stock_picking.py#L978));
- copies every non-cancelled move with demand 0, `origin_returned_move_id` set, and chain links reversed ([`:911`](../addons/stock/models/stock_picking.py#L911));
- uses the operation type's "Operation Type for Returns", and the return type's default destination when that type is a receipt ([`:959`](../addons/stock/models/stock_picking.py#L959)). A return of a 2-step SHIP therefore goes straight into WH/Stock as a Receipt, skipping WH/Output (T33).

Return moves keep the sale line ([`stock.py:399`](../addons/sale_stock/models/stock.py#L399)) and the purchase line, and copy `to_refund` from the original ([`stock_picking.py:34`](../addons/stock_account/models/stock_picking.py#L34)).

**Buttons on the draft return.** **Return All** sets each line to the original done quantity minus earlier returns ([`:823`](../addons/stock/models/stock_picking.py#L823)); **Clear** sets 0. Nothing caps the quantity: returning 5 of 3 delivered is accepted and makes Delivered −2 (T10).

**Customer return after invoicing (T6).** 5 delivered and invoiced, 2 returned:

| Record | Value |
|---|---|
| Return move | +20 (2 × the delivery's unit value, [`_get_value_from_returns()`](../addons/stock_account/models/stock_move.py#L575)) |
| SO Delivered / To Invoice | 3 / −2, Invoice Status "To Invoice" |
| Create Invoice | Credit note 2 units, COGS reversal 20 (debit Stock Valuation, credit expense) |
| Stock journal entry | None |

**`to_refund` (T7).** With `to_refund` False (settable only in code), Delivered stays 5 and Create Invoice refuses: "Cannot create an invoice. No items are available to invoice." In Odoo 19 the flag was a debug-only column on the return wizard; 20 has no field for it in any view. Treat every return as "update quantities".

**Return of a return, and Exchange (T8, T9).** Returning 1 of the 2 returned units raises Delivered to 4 and To Invoice to +1. **Exchange** (on a Ready or Done return) creates a normal outgoing transfer for the returned quantities, clears `origin_returned_move_id` and keeps the sale line ([`stock_picking.py:843`](../addons/stock/models/stock_picking.py#L843)). Once validated, Delivered is back to 5 and nothing needs invoicing, since the credit note was never made.

**Vendor return (T28).** 6 received and billed, 2 returned: Received 4, To Bill −2, Create Bill makes a draft refund of 2 × PO price. The return move is valued at the current AVCO/FIFO cost (−20 here), not at the PO price ([`stock_move.py:401`](../addons/stock_account/models/stock_move.py#L401)). When the cost has moved since the receipt, the refund and the move value differ; the difference stays in the Stock Valuation account until the closing.

**Re-procurement trap (T33).** After a return with `to_refund`, the next edit of the SO line quantity procures the returned quantity again. 5 delivered, 2 returned, quantity changed from 5 to 6: Odoo creates a delivery for 3, not 1 ([`_get_qty_procurement()`](../addons/sale_stock/models/sale_order_line.py#L304)). Decide first whether the returned goods should ship again.

**Portal returns.** The customer's portal return request creates no transfer; see [`inventory.md`](inventory.md#customer-portal-returns-sale_stock).

### 6. Cancelling

**Done moves cannot be cancelled.** Cancel and Delete on a done transfer both raise "You cannot cancel a stock move that has been set to 'Done'. Create a return in order to reverse the moves which took place." ([`stock_move.py:2273`](../addons/stock/models/stock_move.py#L2273); delete calls cancel, [`stock_picking.py:724`](../addons/stock/models/stock_picking.py#L724)).

**Cancelling an open transfer or a backorder (T12).** The reservation is released and nothing is re-created:

| Record | 10 ordered, 6 delivered, backorder of 4 cancelled |
|---|---|
| Delivery Status | Fully Delivered |
| Delivered / To Invoice | 6 / 6 (policy "delivered") |
| Later quantity edit 12 → 13 | New delivery for 7: every uncovered unit, not just the added one |

Cancelled moves are ignored when Odoo decides how much to procure. If the rest will never ship, set the ordered quantity to what was delivered instead of only cancelling the backorder.

**Chains.** Cancelling an upstream move cancels the downstream move when `propagate_cancel` is set and all its sibling origins are cancelled; otherwise the downstream move is detached and becomes Take From Stock ([`_action_cancel()`](../addons/stock/models/stock_move.py#L2273)). When propagation applies, the system parameter `stock.cancel_moves_origin` also cancels the open origin moves ([`:2281`](../addons/stock/models/stock_move.py#L2281)). Cancelling the SHIP of a done PICK leaves the goods in WH/Output (T32): Delivered 0, Delivery Status "Fully Delivered", and a later quantity edit procures only the extra quantity.

**Cancelling a sale order (T14).** There is no cancel wizard in 20. `_action_cancel()` cancels every transfer that is not done and all draft invoices; done deliveries and posted invoices stay ([`sale_order.py:238`](../addons/sale_stock/models/sale_order.py#L238), [`sale_order.py:1797`](../addons/sale/models/sale_order.py#L1797)). 4 of 10 delivered, not invoiced:

- the 4 units left the warehouse and the order shows "Nothing to invoice";
- Delivery Status shows "Fully Delivered";
- in perpetual valuation no COGS is ever posted, so the Stock Valuation account keeps the value of goods that are gone.

A locked order cannot be cancelled: "You cannot cancel a locked order. Please unlock it first." ([`sale_order.py:1791`](../addons/sale/models/sale_order.py#L1791)).

**Cancelling a purchase order.** Refused while any bill is posted: "Unable to cancel purchase order(s): …. You must first cancel their related vendor bills." (T29, [`purchase_order.py:723`](../addons/purchase/models/purchase_order.py#L723)). Without a bill it goes through (T30): open receipts are cancelled, done receipts stay with the note "The purchase order … this receipt is linked to was cancelled." ([`purchase_order.py:221`](../addons/purchase_stock/models/purchase_order.py#L221)). The received goods stay in stock, To Bill is 0 and they will never be billed.

**Cancelling an MTO purchase (T34).** The sale delivery is not cancelled. It becomes Take From Stock and waits for stock. No new purchase is proposed for it; a later SO quantity increase buys only the increase.

### 7. Changing the sale order after confirmation

| Change | Result | Log |
|---|---|---|
| Increase | Extra quantity merged into the open delivery, or a new delivery | T11 |
| Decrease above Delivered | Open move reduced; a move emptied to 0 is cancelled unless picked | T11 |
| Decrease below Delivered | Refused: "The ordered quantity of a sale order line cannot be decreased below the amount already delivered. Instead, create a return in your inventory." ([`sale_order_line.py:416`](../addons/sale_stock/models/sale_order_line.py#L416)) | T11 |
| Decrease while the delivery is already picked | Demand drops (10 → 6) but the picked quantity (8) stays; validating delivers 8. Note "The initial demand has been updated." | T13 |
| Any change on a locked order | No procurement at all ([`sale_order_line.py:387`](../addons/sale_stock/models/sale_order_line.py#L387)); quantity, product and price edits are refused | — |
| Delivery address | Open transfers take the new partner, except when the same save edits lines; done transfers keep the old one ([`sale_order.py:146`](../addons/sale_stock/models/sale_order.py#L146)) | — |
| Commitment date | Deadline of open outgoing moves only ([`sale_order.py:158`](../addons/sale_stock/models/sale_order.py#L158)) | — |
| Warehouse | Read-only once confirmed | — |

Draft invoices are never adjusted by these changes. They already count as invoiced; edit the draft rather than creating another invoice.

### 8. Changing the purchase order after confirmation

| Change | Result | Log |
|---|---|---|
| Increase | New or merged receipt for the difference ([`_create_or_update_picking()`](../addons/purchase_stock/models/purchase_order_line.py#L188)) | T27 |
| Decrease with an open receipt | Open receipt reduced | T27 |
| Decrease below Received with an open receipt | Open receipt cancelled, and **an outgoing transfer to the vendor for the excess** is created (not flagged as a return). Validating it lowers Received | T27 |
| Decrease below Received, nothing open | No error and no transfer | — |
| Decrease below Billed | An activity on the bill: "The quantities on your purchase order indicate less than billed. You should ask for a refund." | — |
| Unit price | Open moves take the new price; done receipts are revalued at once for their unbilled part ([`purchase_order_line.py:123`](../addons/purchase_stock/models/purchase_order_line.py#L123)); posted COGS re-priced | T24 |

With "Lock Confirmed Orders" (`po_lock`), confirmed orders lock at confirmation ([`purchase_order.py:701`](../addons/purchase/models/purchase_order.py#L701)) and their lines become read-only; a Purchase Manager unlocks them. A locked order cannot be cancelled: "Unable to cancel purchase order(s): …. You must first unlock them."

### 9. Dates — backdating and the valuation replay

- Writing the transfer date on a done transfer copies it to every move ([`stock_picking.py:704`](../addons/stock/models/stock_picking.py#L704)); move line dates follow as a related stored field. Scrap moves attached to the transfer are not updated.
- `stock_account` refuses a done date inside the fiscal-year or hard lock date: "You cannot modify the scheduled date of operation … because it falls within a locked fiscal period." ([`stock_picking.py:13`](../addons/stock_account/models/stock_picking.py#L13)). The system parameter `stock_account.skip_lock_date_check` disables this. Writing a move's `date` directly is not checked.
- A date change replays valuation from the earliest of the old and new dates ([`stock_move.py:181`](../addons/stock_account/models/stock_move.py#L181)).

**Example (T25).** Receipts 10 @ 10 (three days ago) and 10 @ 20 (yesterday), then 10 sold today at AVCO 15 (COGS 150). The delivery is backdated to two days ago, between the receipts. Its value becomes −100 and the posted COGS is rewritten to 100. The product cost still shows 15, while the 10 units on hand are worth 200 (cost 20). The cost is corrected only by the next incoming move. The replay path skips `_update_standard_price()` ([`stock_move.py:370`](../addons/stock_account/models/stock_move.py#L370)).

### 10. Bills and invoices changed after the goods moved

| Change | Effect on stock values | Effect on accounting | Log |
|---|---|---|---|
| Vendor bill posted at another price after part of the goods was sold | Receipt value takes the bill price; later sales re-costed | Posted COGS re-priced; refused if a re-priced invoice is in a locked period | T23, T26 |
| Vendor bill reset to draft or cancelled | Receipt falls back to the PO price; sales re-costed | Posted COGS re-priced back ([`account_move.py:54`](../addons/stock_account/models/account_move.py#L54)) | T23 |
| Customer invoice reset to draft | None | COGS lines deleted; re-created at posting at invoice quantity × current move unit value | T20 |
| Credit note | None | COGS reversed at the moves' average unit value | T5, T6 |
| Price-difference lines (standard cost + Anglo-Saxon + category price-difference account) | — | Built on the bill only; not rebuilt by receipt corrections | — |

### 11. Multi-step deliveries and MTO chains

In 20, a 2- or 3-step delivery creates only the first step (PICK) at confirmation. The next steps are created by push rules when the previous one is validated ([`stock_warehouse.py:785`](../addons/stock/models/stock_warehouse.py#L785)). Consequences:

- **Correcting a done PICK after the SHIP exists (T31).** PICK 10 → 7: SHIP demand stays 10, its reservation drops to 7 (Partially Available). Validating SHIP at 10 anyway drives WH/Output to −3. Validate the 7 and cancel the rest, or correct the SHIP demand.
- **Cancelling the SHIP (T32).** The goods stay in WH/Output. Nothing re-creates the SHIP. Delivered is 0 but Delivery Status shows "Fully Delivered". Return the PICK to put the goods back, or create a new SHIP.
- **Returns (T33).** A return of the SHIP goes to WH/Stock as a Receipt. A return of the PICK goes Output → Stock.
- **Status during the steps.** After PICK only, Delivery Status is "Started" and Delivered is 0; only the last step to the customer counts.

### 12. Scrap and inventory adjustments

- **Scrap** is a `stock.move` with `is_scrap` in 20; `stock.scrap` no longer exists. **Scrap** on a done delivery opens a scrap form whose source is the delivery's destination (the customer) and whose destination is the company's scrap location, the inventory-loss location in a fresh database ([`action_scrap()`](../addons/stock/models/stock_picking.py#L1717)). Scrapping there moves goods Customers → Loss: value 0, Delivered unchanged (T35). Scrap from WH/Stock is valued (−10 in T35).
- **Inventory adjustment** creates a new done move to or from the loss location ([`_apply_inventory()`](../addons/stock/models/stock_quant.py#L1028)). It does not touch the transfer that was wrong, nor the sale or purchase.
- Both post a stock journal entry only when the Inventory adjustment location has a Loss Account: then debit loss, credit Stock Valuation (T35). Without one, the value difference waits for the Stock Closing.

---

## Invoicing Consequences Cheat Sheet

### Sales

| Event after invoicing | Policy "delivered" | Policy "ordered" |
|---|---|---|
| Delivery corrected down | To Invoice negative → Create Invoice makes a credit note | Nothing changes; the customer keeps an invoice for goods not shipped |
| Delivery corrected up | To Invoice positive → extra invoice | Nothing to invoice; the line shows "Upselling" (delivered > ordered) |
| Return | Credit note via Create Invoice | Nothing to invoice; credit manually from the invoice (Reverse keeps the sale line link, so Invoiced drops) |
| Return of return / Exchange | Positive To Invoice if a credit note was made | Nothing |
| Backorder cancelled | Only what was delivered is invoiced | Invoice still for the full order |
| Order cancelled | Delivered, uninvoiced goods become "Nothing to invoice" | Same |

sale_stock marks a "delivered" line as Fully Invoiced when nothing is left to invoice, all its moves are done or cancelled and it has a Delivered quantity, even if short ([`sale_order_line.py:212`](../addons/sale_stock/models/sale_order_line.py#L212)).

### Purchases

| Event after billing | Control "received" | Control "ordered" |
|---|---|---|
| Receipt corrected down | To Bill negative → Create Bill makes a refund | Nothing changes |
| Receipt corrected up | Extra bill | Nothing |
| Vendor return | Refund via Create Bill | Nothing; create the refund manually |
| Receipt backorder cancelled | Bill only what arrived | Bill for the full order |
| Order cancelled | Refused while a bill is posted | Same |

---

## Keeping Stock and Books Aligned — the Stock Closing

In 20, stock values and the Stock Valuation account are two separate stories that meet at the Stock Closing. The closing compares the inventory value (`total_value` of every product at the date) with the account balance and posts the difference to the Stock Variation account ([`_get_stock_valuation_account_vals()`](../addons/account/models/company.py#L1489)). It is not a sum of deltas, so a correction to a move dated before the last closing is still caught at the next one.

| Cause of a gap | Direction | Cleared by |
|---|---|---|
| Delivery corrected down, policy "ordered" (T19) | Books below stock | Closing, or a credit note that carries COGS |
| Order cancelled with delivered, uninvoiced goods (T14) | Books above stock | Closing only |
| Purchase cancelled with received, unbilled goods (T30) | Books below stock | Closing only |
| Goods received, bill not yet posted | Books below stock | The bill, or accruals at closing |
| Vendor return valued at a cost other than the refund price | Either | Closing |
| Adjustment or scrap without a Loss Account (T35) | Either | Closing |
| Product cost stale after backdating (T25) | Future deliveries mis-costed | Next receipt |

**Example (T37).** A delivery corrected 5 → 3 on an order invoiced on ordered quantities (gap 20) plus a cancelled purchase with 4 units received (gap 40): inventory value 210, Stock Valuation balance 150. The closing proposes a draft entry: debit Stock Valuation 60, credit Stock Variation 60, "Closing: Stock Variation Global for company […]".

The closing is launched from the Inventory Valuation report ([`controller.js:83`](../addons/account/static/src/components/stock_valuation/controller.js#L83), [`action_close_stock_valuation()`](../addons/account/models/company.py#L1278)). With accruals, it also posts auto-reversing entries for goods received not billed and delivered not invoiced. A closing cannot be dated before the last one.

---

## Which Correction to Use

| Situation | Use | Avoid |
|---|---|---|
| Goods physically came back | **Return** (credit note / refund via Create Invoice / Create Bill) | Editing the done quantity: no return document, no rs.ge return waybill |
| The quantity was keyed in wrong and the goods never moved | **Unlock and edit** the done quantity, same day, before invoicing | Editing after an invoice in a locked period (refused) or under policy "ordered" (silent mismatch) |
| Wrong lot or shelf keyed in | **Unlock and edit** the move line | An inventory adjustment: it fixes quants but leaves the wrong lot on the delivery and the customer's lot history |
| Count difference found later in the warehouse | **Inventory adjustment** | Editing an old transfer: replays valuation and may re-price old invoices |
| Customer will not receive the rest | Set the SO quantity to Delivered, then cancel the backorder | Only cancelling the backorder: the next SO edit re-procures the rest |
| Wrong product shipped | Return the wrong product, deliver the right one | Adding the right product to the done transfer: no SO line, never invoiced |
| Vendor sent less than billed | Edit the receipt (or return) and Create Bill for the refund | PO cancel (refused with a posted bill) |
| Ship replacement goods after a return | **Exchange** on the return | Editing the SO quantity: it may re-procure more than intended (T33) |

---

## Our Modules: `rs_waybill`

`rs_waybill` ties a delivery to a Georgian rs.ge waybill and changes how corrections work on those transfers.

- **Validation needs the waybill on rs.ge.** A seller-direction delivery cannot be validated while its waybill is not saved or still draft on rs.ge, or cancelled there. After validation the active waybill is closed on rs.ge ([`_action_done()`](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L563)).
- **Transfers with a waybill on rs.ge are frozen.** Once the waybill has an rs.ge id (`rs_waybill_locked`), the form makes partner, product, demand and quantity read-only, even after Unlock ([`stock_picking.xml:47`](../custom_addons/gec_odoo_modules/rs_waybill/views/stock_picking.xml#L47)). A banner points to Edit Waybill.
- **Corrections go through the waybill.** Editing a delivered waybill on rs.ge drives Odoo:
  - quantity up: the done move quantity, its demand and the SO line are raised in place ([`_apply_line_diffs_increase_on_done()`](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1334));
  - new product: a new SO line and a supplementary delivery, with no second waybill;
  - quantity down or line removed: the Return Decision wizard asks whether the goods came back (return transfer plus a type-5 return waybill) or never left (return transfer only) ([`return_decision_wizard.py:22`](../custom_addons/gec_odoo_modules/rs_waybill/wizards/return_decision_wizard.py#L22), [`_create_return_picking()`](../custom_addons/gec_odoo_modules/rs_waybill/models/rs_waybill.py#L1438)).
- **Cancel cascades to rs.ge.** Cancelling a transfer deletes a draft waybill on rs.ge, or refuses (cancels) an active one; an rs.ge failure blocks the cancel ([`action_cancel()`](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L109)).
- **Customer returns** get a type-5 return waybill when their receipt operation type has waybills enabled; it is created once the return is reserved. Receipts from a purchase never get one ([`_rs_try_create_waybill()`](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L160), [`_rs_create_return_waybill()`](../custom_addons/gec_odoo_modules/rs_waybill/models/stock_picking.py#L449)).
- **Gap:** a done delivery whose waybill never reached rs.ge is not frozen. Unlocking and editing it changes stock and sales but no waybill. Open findings for the module are in [`rs_waybill_einvoice_fix_plan.md`](../dev_notes/plans/rs_waybill_einvoice_fix_plan.md).

---

## Configuration & Settings That Change Correction Behaviour

- **Operation type → Create Backorder** (Ask / Always / Never): with Never, the rest is cancelled at validation and a note lists what was not delivered, so later corrections start from a short, "Fully Delivered" order.
- **Operation type → Operation Type for Returns**: decides where returns land (T33).
- **Warehouse → Outgoing/Incoming Shipments** (1/2/3 steps): with more steps, only the last step to the customer or the first from the vendor changes Delivered/Received.
- **Product → Invoicing Policy** (ordered / delivered): decides whether a delivery correction reaches invoicing at all.
- **Product → Control Policy** (ordered / received quantities): same for bills.
- **Product category → Inventory Valuation** (Periodic / Perpetual) and **Costing Method**: perpetual makes corrections re-price posted COGS; FIFO and AVCO replay later moves; standard cost never re-costs sales.
- **Inventory location → Loss Account** (`valuation_account_id`): with it, scrap and adjustments post entries at once; without it, they wait for the closing.
- **Company → Anglo-Saxon Accounting**: only enables price-difference lines on bills.
- **Accounting → Lock dates**: block backdating into a locked period and any correction that re-prices a COGS line dated there.
- **Sales → Lock Confirmed Sales** (`sale.group_auto_done_setting`): confirmed orders lock; they no longer procure on edits and cannot be cancelled until unlocked.
- **Purchase → Lock Confirmed Orders** (`po_lock`): same for purchases.
- **System parameters:** `stock.cancel_moves_origin` (with propagation, cancel open upstream moves too), `stock_account.skip_lock_date_check` (allow backdating into locked periods).

---

## Security

| Action | Who |
|---|---|
| Validate, Cancel, Return | Inventory User (`stock.group_stock_user`); Return and Cancel buttons show for any internal user, but writing a transfer needs the stock group |
| Unlock a done transfer | Inventory Administrator (`stock.group_stock_manager`), view level only |
| Delete a stock move | Inventory Administrator; Inventory Users have create/read/write only ([`ir.access.csv:19`](../addons/stock/security/ir.access.csv#L19)) |
| Unlock a confirmed purchase order | Purchase Manager ([`purchase_views.xml:129`](../addons/purchase/views/purchase_views.xml#L129)) |

`stock.move.line` gives full create/write rights to every internal user in `ir.access.csv`. Not verified: whether anything besides the view stops an internal user without stock rights from editing done lines over RPC.

---

## Gotchas & Non-Obvious Behavior

1. **No stock journal entry, ever, for a correction.** Look for the effect in move values, COGS on invoices and the closing, not in the Inventory Valuation journal.
2. **Posted invoices change.** Receipt corrections, late bills, bill resets, PO price edits and backdating rewrite COGS lines on posted invoices without any message on the invoice.
3. **Lock dates block corrections indirectly.** The error names the lock date, not the transfer; it comes from the COGS rewrite on an old invoice.
4. **Negative stock is always possible through a correction**, whatever the "allow negative" habits of the warehouse.
5. **Delivery Status is not a delivery measure.** It reads transfer states. Use Delivered vs Ordered on the lines.
6. **Returns always update Delivered/Received** because `to_refund` has no UI.
7. **Over-returns are accepted** and make Delivered negative.
8. **A return re-arms procurement.** The next SO quantity edit ships the returned quantity again.
9. **Cancelled backorders are forgotten, not closed.** The next SO edit procures every uncovered unit.
10. **Cancelling an order does not settle delivered goods.** They stay delivered and uninvoiced for good.
11. **Cancelling a purchase does not settle received goods.** They stay in stock and unbilled for good.
12. **Products added to a done transfer are never invoiced.**
13. **Decreasing a PO below Received can create an outgoing transfer to the vendor** when a receipt was still open.
14. **Backdating leaves the product cost stale** until the next receipt; deliveries in between use the stale cost.
15. **Vendor returns are valued at current cost**, not at the purchase price, so the refund and the stock value can differ.
16. **In multi-step flows, correcting one step does not correct the next.** Reservations follow; demands do not.
17. **The chatter note is on the transfer only.** The sale order, purchase order and invoice show nothing about a done-quantity correction.
18. **Inventory adjustments do not fix the source document.** Use them for count differences, not for a wrong delivery.
19. **Lot corrections leave the lot's customer history behind.** The old lot keeps the customer, the new one does not get it.

---

## Corrections to Other Docs

Found while writing this doc and fixed in those docs on 2026-09-25:

- [`stock_valuation.md`](stock_valuation.md): receipts posting to Stock Input and deliveries to Stock Output (walkthroughs, account table, money-flow diagrams, code traces, glossary); the Anglo-Saxon flag described as the COGS switch; a picking reset to draft; the `_use_inventory_valuation()` override placed in `stock_account`; `_get_price_unit_delivery()` called removed; `product.value.account_move_id` called the adjustment's journal entry (nothing writes it); drifted line links in the COGS section.
- [`accounting_coa.md`](accounting_coa.md): the Anglo-Saxon flag described as "COGS posted at delivery", COGS "posted on delivery", and "every stock move creates journal entries in real time".
- [`inventory.md`](inventory.md#delivered-quantity-and-delivery-status): `to_refund` described as the "Update quantities on SO/PO" option, which has no field in 20.

Not edited: [`rs_waybill_einvoice_fix_plan.md`](../dev_notes/plans/rs_waybill_einvoice_fix_plan.md) (item bodies are Odoo 19 on purpose; its 20.0 notes already say `stock.return.picking` is gone) and [`certification_exam.md`](../dev_notes/reference/certification_exam.md) (Odoo 19 practice questions).

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`inventory.md`](inventory.md) — routes, reservation, backorders, returns and the SO-to-delivery flow this doc builds on
- [`stock_valuation.md`](stock_valuation.md) — costing methods, move value priority, COGS mechanics, closing
- [`inventory_forecast_report.md`](inventory_forecast_report.md) — how open moves appear in the forecast
- [`mrp.md`](mrp.md) — manufacturing orders, the only documents with a reset to draft
- [`rs_waybill_einvoice_fix_plan.md`](../dev_notes/plans/rs_waybill_einvoice_fix_plan.md) — open findings in `rs_waybill`

---

## Scenario Log

Run on 2026-09-25 on the throwaway database `gec20_scenario_stock` (Odoo 20, generic chart, Anglo-Saxon on, dropped afterwards). Each scenario ran in its own rolled-back savepoint. Accounts: Stock Valuation 110100, Stock Variation 110200, expense/COGS 600000, income 400000, tax 15%. Products: P (perpetual AVCO, invoice and bill on delivered/received quantities), PF (perpetual FIFO), Q (perpetual AVCO, invoice and bill on ordered quantities), PP (periodic AVCO). Sale price 20, purchase price 10 unless stated.

| # | Scenario | Result |
|---|---|---|
| T1 | Receipt 10 @ 10 validated | Move value 100; no stock journal entry |
| T2 | Its bill posted | Debit 110100 100, debit tax 15, credit payable 115 |
| T3 | Receipt 10 → 8 after the bill | Value 80; Received 8, Billed 10, To Bill −2, "Waiting Bills"; no entry; Create Bill → draft refund 2 × 10 (credit 110100 20) |
| T4 | Delivery 5 validated, invoiced | Move −50, no entry; invoice COGS debit 600000 50 / credit 110100 50 |
| T5 | Delivery 5 → 4 after invoice (policy delivered) | Delivered 4, Invoiced 5, To Invoice −1; invoice untouched; Create Invoice → credit note 1 unit + COGS reversal 10; then Fully Invoiced |
| T6 | Return 2 of 5 after invoice | Return move +20, no entry; Delivered 3, To Invoice −2; credit note 2 units + COGS reversal 20 |
| T7 | Same with `to_refund` False (code) | Delivered stays 5; Create Invoice: "Cannot create an invoice. No items are available to invoice." |
| T8 | Return of the return, 1 unit | Delivered 3 → 4, To Invoice +1 |
| T9 | Exchange after returning 2 | Exchange transfer keeps the sale line, no return origin; after validation Delivered 5 |
| T10 | Return 5 of 3 delivered | Accepted; Delivered −2, To Invoice −2 |
| T11 | SO 10, delivered 6, backorder 4; quantity → 5 / 8 / 12 | 5 refused (message in §7); 8 → backorder demand 2; 12 → backorder 6 |
| T12 | Then backorder cancelled; quantity 12 → 13 | Delivery Status Fully Delivered with 6 of 12; edit → new delivery for 7 |
| T13 | SO 10 → 6 while 8 picked, not validated | Demand 6, quantity 8 kept; note "The initial demand has been updated." |
| T14 | SO cancelled with 4 of 10 delivered | No wizard; backorder cancelled; SO Cancelled, "Nothing to invoice", Delivery Status Fully Delivered |
| T15 | Product X added to a done delivery (unlocked) | Move done, value −10, stock out; no SO line. Added before validation → SO line ordered 0, delivered 1 |
| T16 | Done delivery quantity → 0 | Move done with 0; stock back; Delivered 0; "Nothing to invoice"; Fully Delivered |
| T17 | Done delivery 5 → 8 with 5 in stock | Quant −3; Delivered 8 on 5 ordered; To Invoice 8 |
| T18 | Lot A → B on a done delivery line; then source → a shelf holding 1 | A 2 → 5, B 5 → 2; note "The done move line has been corrected."; shelf −2 |
| T19 | Policy ordered: invoice 5 before delivery, deliver, correct 5 → 3 | COGS 50 (product cost) and unchanged; Invoiced 5, Delivered 3, To Invoice 0, Fully Invoiced, Fully Delivered |
| T20 | Invoice reset to draft after delivery 5 → 4, reposted | COGS lines deleted, re-created at 5 × 10; To Invoice −1 remains |
| T21 | AVCO 10 @ 10 + 10 @ 20, 12 sold and invoiced; first receipt 10 → 4 | Sale −180 → −205.71; posted COGS 180 → 205.71; cost 17.14; 2 on hand |
| T22 | FIFO 5 @ 10 + 5 @ 20, 6 sold and invoiced; first receipt 5 → 3 | Sale −70 → −90; posted COGS 70 → 90 |
| T23 | Bill at 12 after 4 of 10 sold; then bill reset to draft | Receipt 120, sale −48, COGS 40 → 48, cost 12; reset → 100, −40, COGS 40, cost 10 |
| T24 | PO price 10 → 12 after receipt (no bill); after a sale, → 15 | Receipt 120, cost 12; then receipt 150, sale −60, COGS 48 → 60 |
| T25 | 10 @ 10 (3 days ago), 10 @ 20 (yesterday), 10 sold today; delivery backdated 2 days | Sale −150 → −100, COGS 150 → 100; cost stays 15 (true 20); next receipt of 1 @ 20 → cost 20; move and line dates follow `date_done` |
| T26 | Fiscal-year lock 10 days ago; receipts 40 days ago, sale and invoice 35 days ago | Receipt correction that changes the unit cost → "You cannot add/modify entries prior to and inclusive of: Global Lock Date (…)"; same unit cost → accepted; bill at another price → same error, at the same price → posts; backdating the delivery → "You cannot modify the scheduled date of operation … because it falls within a locked fiscal period."; return today → credit note dated today, COGS 30 |
| T27 | PO 10, received 6, backorder 4; line → 5; then → 8 | Backorder cancelled and an outgoing transfer of 1 to Vendors created; after validating it Received 5; → 8 creates a receipt of 3 |
| T28 | Return 2 to vendor after billing 6 | Received 4, To Bill −2; Create Bill → draft refund 2 × 10; return move −20 |
| T29 | PO cancel with a posted bill | "Unable to cancel purchase order(s): P…. You must first cancel their related vendor bills." |
| T30 | PO cancel with 4 of 10 received, not billed | Accepted; open receipt cancelled, done one kept; To Bill 0 |
| T31 | 2-step delivery: PICK 10 → 7 after SHIP was created | SHIP demand 10, reserved 7; validating SHIP at 10 → WH/Output −3 |
| T32 | 2-step: SHIP cancelled after PICK done; SO 10 → 11 | 10 stay in WH/Output; Delivered 0; Fully Delivered; "Nothing to invoice"; edit → new PICK for 1 |
| T33 | 2-step: return 2 of SHIP; return of PICK; SO 5 → 6 | SHIP return: Receipts type into WH/Stock; PICK return: Output → Stock; edit → new PICK for 3 |
| T34 | MTO + Buy: receipt 5 → 3; separately PO cancelled; SO 5 → 6 | Delivery reserved 3 of 5; after PO cancel the delivery is Take From Stock, waiting; edit → new PO for 1 |
| T35 | Scrap from a done delivery; scrap from stock; adjustment −2; adjustment with a Loss Account | Customers → Inventory adjustment, value 0, Delivered unchanged; stock scrap −10, no entry; adjustment −20, no entry; with Loss Account 600000: entry debit 600000 20 / credit 110100 20 |
| T36 | Periodic product billed and invoiced; perpetual product with Anglo-Saxon off | Periodic: bill to 600000, no COGS, corrections post nothing. Anglo-Saxon off: bill still to 110100, COGS still posted |
| T37 | Gaps: order-policy correction (20) + cancelled PO with 4 received (40); closing | Inventory 210 vs 110100 balance 150; draft closing debit 110100 60 / credit 110200 60 |
| T38 | 4 of 10 delivered without backorder and invoiced; delivery 4 → 6 | To Invoice 2; second invoice 2 units, COGS 20 |
| T39 | Lot-tracked delivery of 3 from LOT-A, then lot changed to LOT-B | LOT-A customers: Customer C; LOT-B customers: none, before and after the correction |
