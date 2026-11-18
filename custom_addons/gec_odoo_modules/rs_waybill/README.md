# gec_rs_waybill

Odoo 19 module providing full RS.GE (Georgia Revenue Service) waybill integration, with native Sales Order and Inventory workflow tie-ins.

---

## Overview

This module turns Odoo into a complete RS.GE waybill operator. Operators never need to open the RS.ge portal:

- Sales orders auto-generate waybills as soon as their delivery picking reserves stock
- Drivers, vehicles, transporters and product/barcode mappings are managed inside Odoo
- The full RS waybill lifecycle (save / send / edit / close / cancel / refuse) is exposed as Odoo buttons that call RS.ge SOAP endpoints directly
- Templates and synced waybills are pulled from RS.ge by background crons
- Sub-flows for buyer-side waybills and transporter waybills are supported in addition to the standard seller flow

---

## Features

### Sales Order ↔ Picking ↔ Waybill (forward auto-create)

- Confirming a sale order creates a stock picking (standard Odoo)
- When the picking reserves stock (`stock.move._action_assign`), the module automatically creates an `rs.waybill` linked to:
  - The picking (`rs.waybill.picking_id`)
  - The sales order (`rs.waybill.sales_order_id`)
- Waybill lines are built from `stock.move.quantity` — only **actually reserved** items end up on the waybill (not the SO demand)
- Partial availability is handled natively: if only some products are in stock, only those go on the first waybill. When the backorder picking later becomes available, a **second waybill** is auto-created for the remaining items, also linked to the same SO
- Auto-create is **opt-in per picking type** via the `Create RS Waybill` flag on `stock.picking.type`. By default no picking type creates waybills — the admin enables it on Delivery Orders (and any other types that should generate waybills)
- Each picking type can declare its default RS waybill type (Internal, With Transport, Without Transport, Distribution, Return, Sub Waybill) via the `RS Waybill Type` field

### RS.ge SOAP integration (full lifecycle)

Available as buttons on the waybill form:

| Action | RS.ge operation |
|---|---|
| Save to RS | `save_waybill` — creates draft waybill on RS, returns RS internal ID + waybill number |
| Send / Activate | `send_waybill` — moves waybill to active status (status=1) |
| Edit Waybill | Opens a modal popup of the same waybill in edit mode. Only **Activate Adjustment**, **Cancel Adjustment** and **Print PDF** are visible inside the popup. Activate calls `save_waybill` again on the same `rs_internal_id` — RS keeps the ID/number and archives the previous state as an adjustment |
| Update Status | Pulls latest state from RS |
| Delete Waybill | `del_waybill` — deletes a draft (status=0) |
| Refuse / Cancel | `ref_waybill` — cancels an active/completed waybill (status=-2) |
| Close Waybill | `close_waybill` — finalizes a delivered waybill (status=2). Also cascades to the linked delivery picking and auto-validates it (Ready → Done) so both systems stay in sync. |
| Reject Waybill | Buyer-side rejection |
| Confirm Waybill | Buyer-side confirmation |
| Print PDF | RS-generated waybill PDF |

### Transporter waybills (carrier flow)

Separate flow for carrier/transporter waybills:
- Save Transporter, Send Carrier Waybill, Active Transporter, Close Transporter actions
- Synced periodically by a dedicated cron

### Templates

- Save any waybill as a reusable template on RS (`rs_template_id`, `template_name`, `is_template`)
- Template picker wizard to start a new waybill from a saved template
- Templates are synced periodically by cron

### Driver & vehicle management

- `fleet.vehicle` extension with TIN, driver name and plate number — picker shows "TIN — Name — Plate"
- `res.partner` flag `rs_is_driver` for registered RS drivers
- Selecting a driver partner or vehicle auto-fills driver TIN, name, and car number on the waybill

### Product mapping (`rs.product.external.ref`)

When a buyer-side waybill is synced from RS and contains products whose barcodes don't match any local product, the lines are flagged as `unresolved`. The mapping wizard lets the operator map external barcodes to internal products. The mapping is remembered per seller (`seller_partner_id` + `external_barcode`) so future syncs auto-resolve.

### Adjustment history

Every time a waybill is edited on RS.ge (via the Edit popup), the previous state is archived under a new `archival_id` while the current `rs_internal_id` and `rs_waybill_number` stay the same. The form has an **Adjustments** smart button that:

- Calls `get_adjusted_waybills(rs_internal_id)` on demand (no local storage)
- Lists each archived version with date and user
- Opens a read-only mirror of the waybill form for any archival snapshot via `get_adjusted_waybill(archival_id)`

This means the full edit history of every active/completed waybill is one click away — header fields and goods lines included.

### Multi-direction waybills

`waybill_direction`:
- `seller` — outgoing (we are selling) → auto-creates Sales Order + delivery
- `buyer` — incoming (we are buying, synced from RS) → auto-creates Purchase Order + receipt; receipt validated when `is_confirmed='1'`
- `transporter` — carrier waybills

### Operation log / queue (table created, activation in Phase 2)

`rs.waybill.operation` model exists and is wired into security. Will be populated with every SOAP request/response in Phase 2 to enable:
- An "RS Logs" tab on each waybill showing the full audit trail
- A retry queue for failed SOAP calls
- Activity reports per user / per operation type

---

## Requirements

### Odoo

- Odoo 20.0
- Module category: `Operations/Services`

### Depends on (Odoo modules)

`base`, `mail`, `product`, `stock`, `account`, `fleet`, `sale`, `sale_stock`, `purchase`, `base_setup`.

**`rs_base_methods` must also be installed.** It holds the RS.ge logins (`_get_rs_credentials`,
`rs_un_id`, RS Responsible User). It is not in `depends` because `rs_base_methods` depends on this
module. Without it, RS actions show an error asking to install it and the crons log and skip.

### Python dependencies

- `zeep` — SOAP client for RS.ge WayBillService
- `lxml` — XML building

---

## Installation

1. Place this module under your Odoo addons path (already done in this repo: `customAddons/gec_rs_waybill/rs_waybill`)
2. Update apps list
3. Install **Waybill - Revenue Service(Georgia)**
4. Store each company's RS.ge login on the users who work with it (see Configuration below)
5. Enable `Create RS Waybill` on the picking types that should auto-generate waybills (typically Delivery Orders)

---

## Configuration

### RS.ge credentials

Logins are stored per user **and per company** by `rs_base_methods`. Switch to the company in the
company menu, open Preferences → Revenue Service (rs.ge), fill in the RS Username and Password and
click **Test SOAP (e-invoice)**. The test validates the login and stores the company's RS.GE taxpayer
id, which every waybill then names as its seller (`SELER_UN_ID`); a login that RS.GE does not let act
for that taxpayer is refused. Repeat in each company you work in.

Tick **RS Responsible User** on the user whose login should run the company's scheduled actions, one
per company. The crons run one pass per company as that user. **A company without an RS Responsible
User is not synced**, even when other users hold a login for it; the cron logs a warning naming the
company. The same rule applies to the e-invoice crons.

Every RS.GE call on a waybill runs with the login of the waybill's company, whatever company is
active in the switcher.

A waybill's transfer, warehouses, buyer, driver, vehicle, sales order and purchase order must belong
to the waybill's company (or to no company): Odoo refuses to save a mix, the same way it does on an
invoice or a sales order.

### Picking type opt-in

Inventory → Configuration → Operations Types → open each picking type → General tab → **RS.ge Waybill** group:
- `Create RS Waybill` — toggle on for types that should generate waybills
- `RS Waybill Type` — which RS type to use (defaults to `2` With Transport)

Typical configuration:
- **Delivery Orders** → enabled, type `2` (With Transport)
- **Internal Transfers** (warehouse-to-warehouse) → enabled, type `1` (Internal Transport)
- **Receipts** → disabled (vendor issues their own waybill)
- **Returns** → enabled, type `5` (Return)
- **Pick / Pack** (multi-step internal) → disabled

---

## Workflow — forward direction (Sales Order driven)

```
1. User confirms a Sales Order
   └─► Odoo creates a Delivery picking automatically (no waybill yet)

2. Stock reservation runs (stock.move._action_assign)
   └─► Module checks: is the picking type opted in?
       Is there a partner? Any reserved qty > 0?
       Is there no existing waybill on this picking already?
   └─► If yes → creates rs.waybill linked to picking + SO,
       with one line per reserved move (skipping unreserved ones)

3. (Partial availability case) Operator validates partial qty
   └─► Odoo creates a Backorder picking automatically
   └─► When the backorder eventually reserves stock,
       step 2 fires again → a second waybill is created

4. Operator fills driver / car / addresses on the waybill,
   clicks Save to RS → Send → Close

5. SO's Waybill smart button shows the count of all waybills
   created for this SO (original + backorder(s) + future returns)
```

---

## Workflow — buyer direction (RS → Purchase Order)

For waybills where **we are the buyer** (a vendor issued the waybill to us). These are
pulled from RS by the sync; we never push them.

```
1. Vendor issues a waybill to us on RS.ge (type 2/3/4)
   └─► Sync cron / "Fetch All Waybills" pulls it (buyer direction)

2. If the waybill is in integration scope (activation/create date ≥ cutoff):
   └─► _rs_create_purchase_from_waybill()
       • resolve vendor by seller_tin, or auto-create one (supplier_rank=1)
       • build a PO (one line per mapped product line), confirm it
       • Odoo spawns the incoming receipt → link waybill ↔ PO ↔ receipt
   └─► (lines with unmapped products → PO skipped until mapped)

3. We confirm receipt:
   • Confirm button on the waybill (calls RS confirm_waybill, sets is_confirmed='1'), OR
   • someone confirms on the RS portal → sync/Update brings back is_confirmed='1'
   └─► _cascade_validate_receipt() validates the receipt (Ready → Done) → goods in stock
       (the vendor's RS-side close does NOT validate our receipt — only our own receive)

4. PO's Waybill smart button opens the linked waybill; the receipt's Waybill button too
```

Prerequisite: **Enable Stock** + a **Stock Integration Start Date** (Settings), and the RS
sync user needs **Purchase + Inventory** rights so cron-side PO creation/validation succeeds.

---

## Models

### Core models

| Model | Description |
|---|---|
| `rs.waybill` | Main waybill record. Holds all RS fields, lifecycle state, links to picking and SO. Inherits `mail.thread` and `mail.activity.mixin` |
| `rs.waybill.line` | One line per product on a waybill. Linked to `stock.move` via `stock_move_id`. Tracks `rs_good_id` from RS, external barcode for mapping |
| `rs.waybill.operation` | Audit log / retry queue for SOAP operations (table only — populated in Phase 2) |
| `rs.product.external.ref` | Mapping table: external seller barcode → internal product |

### Extended models

| Model | Added fields / behavior |
|---|---|
| `sale.order` | `waybill_id` One2many to all waybills for this SO, smart button `action_view_waybills`, `rs_waybill_locked` lock guard |
| `sale.order.line` | `bar_code` (related from product, stored) |
| `purchase.order` | `waybill_id` One2many to all waybills for this PO, `waybill_count`, smart button `action_view_waybills` (buyer direction) |
| `stock.picking` | `waybill_id` Many2one to the linked waybill, `waybill_count` for smart button, `action_view_waybill` method |
| `stock.picking.type` | `rs_create_waybill` opt-in flag, `rs_waybill_type` default selection |
| `stock.move` | `_action_assign` override that triggers waybill creation after reservation |
| `res.partner` | RS driver flag and TIN-based lookup |
| `fleet.vehicle` | TIN, driver name, plate display in driver picker |
| `product.product` | RS-specific fields (barcode default, mapping helpers) |
| `uom.uom` | Mapped to RS unit codes |

---

## Cron jobs

| Cron | Frequency | What it does |
|---|---|---|
| `RS.GE: Sync Updated Waybills` | every 15 minutes | Pulls updated waybills (incoming/outgoing) from RS.ge; for in-scope waybills creates/back-fills the linked SO/PO/transfer and cascades completion + buyer-receipt validation |
| `RS.GE: Sync Template Waybills` | every 1 hour | Pulls saved templates from RS.ge |
| `RS.GE: Sync Transporter Waybills` | every 1 hour | Pulls transporter waybills |
| `RS.GE: Drift Repair` | every 15 minutes | Re-fetches and re-applies state for in-scope waybills (completion, buyer-receipt validation) so Odoo follows RS even if a button/sync was missed |

---

## Module structure

```
gec_rs_waybill/
├── README.md                          ← this file
└── rs_waybill/
    ├── __manifest__.py
    ├── __init__.py
    ├── data/
    │   ├── ir_cron.xml                ← scheduled syncs
    │   └── uom_data.xml               ← UoM ↔ RS code mapping
    ├── models/
    │   ├── rs_waybill.py              ← main model + all action_* methods
    │   ├── rs_waybill_line.py         ← waybill lines
    │   ├── rs_waybill_operation.py    ← audit log / queue
    │   ├── rs_waybill_soap_service.py ← SOAP client wrapper (zeep)
    │   ├── rs_waybill_sync.py         ← cron sync methods
    │   ├── rs_waybill_stock.py        ← (legacy, disabled in __init__.py)
    │   ├── rs_product_external_ref.py ← external product mapping
    │   ├── sale_order.py              ← SO extension
    │   ├── stock_picking.py           ← picking + picking type + move hooks
    │   ├── res_partner.py
    │   ├── res_config_settings.py     ← RS credentials config
    │   ├── product_product.py
    │   ├── fleet_vehicle.py
    │   └── __init__.py
    ├── wizards/
    │   ├── product_mapping_wizards.py ← resolve unresolved lines
    │   ├── template_wizards.py        ← save-as-template, pick-from-template
    │   └── __init__.py
    ├── views/
    │   ├── rs_waybill_views.xml       ← main form + tabs (incl. Sales Order page)
    │   ├── rs_waybill_list_views.xml  ← list views (given / received / saved / transporter / template)
    │   ├── rs_waybill_driver_views.xml
    │   ├── rs_waybill_menu.xml        ← menu items
    │   ├── sale_order_views.xml       ← SO smart button + barcode column
    │   ├── stock_picking.xml          ← picking + picking type inheritance + smart button
    │   ├── product_views.xml
    │   ├── uom_uom_views.xml
    │   ├── mapping_wizard_views.xml
    │   ├── template_wizards_views.xml
    │   └── res_config_settings_views.xml
    ├── security/
    │   └── ir.model.access.csv
    └── static/
        ├── description/icon.png
        └── src/scss/rs_waybill.scss
```

---

## Roadmap (planned phases)

Documented in `/home/saba/Downloads/waybill_integration_plan_v2.html`. Summary:

| Phase | Title | Status |
|---|---|---|
| 1 | Architecture & forward auto-create | ✅ done |
| 2 | Operation queue + no-commit refactor | planned |
| 3 | Goods ID persistence, line-removal **tombstone** | ✅ done (VAT derivation / FULL_AMOUNT rounding still open) |
| 4 | Cascade (picking validate → close waybill, **+ close → validate picking**), state-aware cancel | ✅ done (lock policy still open) |
| 5 | Edit → sync transfer **and** sales order (qty up/down, add, remove, returns) | ✅ done |
| 6 | Reverse direction (waybill-first → SO + picking), return-decision wizard, buyer↔customer sync, lock guard, RS goods auto-sync | ✅ done |
| 6b | **Buyer-direction → Purchase Order + receipt**, vendor auto-create, receipt auto-validate on `is_confirmed='1'`, doc-backfill for already-synced waybills | ✅ done |
| 7 | Invoice link / lock + `is_invoiced`, distribution (type 4), sub-waybills (type 6), multi-company, UoM/qty conversion polish | planned |

---

## Changelog

### Unreleased

#### Added

- **Automated test suite (`rs_waybill/tests/`).** First tests in the module. Nothing touches RS.GE — `rs.waybill.soap.service` is an `AbstractModel`, so every network entry point is stubbed with `unittest.mock`. Four files: `test_rs_result_codes.py` (RS reply-code decoding, `save_waybill` STATUS handling, the three action methods that used to skip the check), `test_timezone.py` (Tbilisi↔UTC in both directions, the round trip, the transporter leg, the UTC-midnight cutoff boundary), `test_line_diff.py` (the goods diff engine, including the empty-snapshot case), `test_validation.py` (`_validate_before_save` per waybill type, plus sub-waybill rules). Shared fixtures in `tests/common.py`. Run with:
  ```
  docker exec odoo19_odoo sh -c 'python /opt/odoo/odoo-bin -c /etc/odoo.conf \
    --db_host $DBHOST --db_user $DBUSER --db_password $PASSWORD \
    -d gec_ci -u rs_waybill --test-enable --test-tags /rs_waybill \
    --http-port=8099 --stop-after-init'
  ```
  (`--test-enable` starts the HTTP server, so it needs a port the running container isn't already using.)
- **Waybill lines carry the real VAT type instead of a hardcoded 18%.** `_rs_line_vals_from_move` stamped `vat_type = '0'` on every line, which reaches RS.GE as `GOODS/VAT_TYPE` — so every waybill Odoo built declared **standard 18%**, exports included, contradicting the zero-rated VAT invoice issued for the same goods. Both are filings to GRS, and the contradiction is visible without an audit.
  RS's three codes are the Tax Code of Georgia's own split, which is why the rate alone cannot answer it — zero-rated and exempt both charge nothing:
  | Code | Georgian treatment | Input credit |
  |---|---|---|
  | `0` | Standard 18% (Art 168) | ✅ |
  | `1` | Exempt **with** credit / zero-rated (Art 172): exports, international transport, ship & aircraft supply, FIZ-to-FIZ, agricultural cooperative own produce | ✅ |
  | `2` | Exempt **without** credit (Arts 170–171): land, investment gold, diabetic bread, Patriarchate items | ❌ |

  `_rs_vat_type_for_move` reads the type from the Tax Category Code of each tax on the `sale.order.line` / `purchase.order.line` behind the move (Accounting > Configuration > Taxes; the field comes from Odoo's e-invoicing module). gec_localization sets it on Georgian taxes: `S` standard, `Z` / `G` zero-rated, `E` / `O` exempt. Codes map to `S` 0, `Z` / `G` / `K` 1, `E` / `O` 2; a tax without a code (withholding, other non-VAT taxes) is ignored. No order line, no tax or no mapped tax gives `'0'`. When one line mixes types, the first of 0, 1, 2 wins and a warning is logged. **Setup step:** check the Tax Category Code on any VAT tax you create yourself.
- **A waybill declares what left the warehouse, not what was ordered.** Backorder pickings used the **demanded** quantity unconditionally (`use_demand = bool(self.backorder_id)`), so a backorder for 40 with 25 reserved filed **40** with the Revenue Service while 25 units existed. Nothing caught it: the `_validate_before_save` guard only requires the picking to be *Ready*, and under Odoo's default "As soon as possible" shipping policy a picking is Ready once **at least one** unit reserves (`stock/models/stock_picking.py:587`) — so a partially-reserved backorder sailed through. The drift job couldn't see it either, since it compares our waybill against RS's and both said 40. New `_rs_waybill_qty()` returns the reserved quantity; the demanded one survives only as a stand-in for a backorder that has reserved **nothing** yet, whose draft exists so the operator can prepare driver and vehicle and which cannot be sent anyway (with nothing reserved the picking is `confirmed`, and the save is refused). Used by both `_rs_build_waybill_lines` and `_rs_sync_waybill_lines`, so a draft now walks *down* to the truth as stock arrives instead of re-asserting demand forever. Normal pickings are unaffected.
- **Display labels refresh when the data behind them changes.** Three computed labels read fields they never declared, so Odoo had no reason to invalidate them: `res.partner`'s TIN label (`show_partner_tin`) depended only on the context while rendering `company_registry`/`vat`/`name`; `fleet.vehicle`'s "TIN — Name — Plate" read the driver's fields through a relation it didn't declare; and `rs.product.external.ref` depended on the bare m2o fields while rendering the seller's **name** and the product's **display name**, so a bare relation dependency only fired when the link was repointed. Correcting a driver's TIN, renaming a seller or changing a plate left the old text in every dropdown until an unrelated write dropped the cache. All three now declare what they read, dotted across relations where the value lives on the other side.
- **The buyer notification email is sent, not just queued.** `_send_notification_email` created a `mail.mail` and left it for the queue cron — if that cron is off or lagging, a transactional notice about a tax document the buyer must act on simply never left, with nothing anywhere saying so. It now calls `.send(raise_exception=False)`: a bad address can't break the lifecycle action that triggered it, and the failure lands on the mail record's state.
- **Live RS View no longer cries wolf, and no longer hides duplicate-row drift.** Two ways the drift indicator lied: floats were compared with `!=`, so `transport_cost` 100.0 against RS's 100.00000000001 tinted the field on every open (now `float_compare`, 4 digits, for both header values and line quantity/price); and goods were keyed by `(barcode, name)` alone, collapsing a waybill's legitimate duplicate lines — two rows of the same product at different prices, or split quantities — into one, so the second row was never compared and its drift never reported. Rows are now matched by key **plus occurrence**, with surplus copies on either side surfacing as `only_odoo` / `only_rs`.
- **`last_seen_date` means "this mapping resolved something".** `_resolve_product` stamped it before the multi-variant check that can still resolve to nothing, so a broken mapping (multi-variant template, no variant chosen) was marked as recently used — hiding exactly the stale mapping a cleanup pass looks for. Stamped only on a successful resolve now.
- **Products RS already knows about stop offering "Send to RS".** A pre-existing Odoo product matched by barcode during the catalog sync was never flagged `is_rs_product`, so it kept showing the send button for a barcode RS has already registered — and the operator got an already-registered error for their trouble.
- **`rs_menu_side` refreshes when the TINs it reads change.** The compute declared only `depends_context('company')`, so the Sent/Received label kept its old value after a seller or buyer TIN edit until something else forced a recompute. It now also depends on `seller_tin` / `buyer_tin`.
- **The drift-highlight animation frame is cancelled on unmount**, and repeated `onPatched` calls coalesce into one frame instead of queuing a DOM walk per patch (`waybill_live_form.js`).
- **The expected-zeep-parse-error handler says so.** `_call_datatable`'s `except Exception: pass` swallowed everything silently; a genuine bug vanished and resurfaced as a misleading "RS.GE returned no response". It now logs at debug what it caught and why it is expected.
- **Dead `datetime` import removed** from `fleet_vehicle.py`.
- **An external reference can no longer pair a variant with the wrong product.** `rs.product.external.ref`'s form domain keeps `variant_id` inside `product_id`, but a domain is UI only — an import or ORM write could pair them freely, and `_resolve_product` would then hand the wrong variant to a waybill line. The server constraint now checks `variant_id.product_tmpl_id == product_id`, in both directions (repointing either field is refused).
- **Uniqueness of `rs_internal_id` is enforced by the database alone.** The `@api.constrains` doing the same check in Python ran a `search()` per record on every write — N extra queries per sync batch — to re-answer what the partial unique index in `_auto_init` already answers, and it could not answer it any better: two concurrent workers can both pass a Python check and still collide. Removed; the index (and its test) stay.
- **One bad row, window or company no longer sinks a whole sync run.** The waybill engine (`_process_rs_rows`) always guarded each row and committed as it went; the layers around it did not.
  - `_fetch_waybills_chunked` had **no per-window guard** — one RS.GE fault aborted the entire 30-day fetch and discarded the windows that had already arrived. Each window is now guarded; the rows that did arrive are synced and the shortfall is logged.
  - `_sync_transporter_waybills_one`'s single un-chunked fetch was unguarded, so an RS.GE fault took the whole hourly cron down. It now logs and returns empty counts.
  - `_sync_templates_one` guarded only the per-template *fetch* — the mapping and write were bare, so one malformed template aborted the run **and discarded every template processed before it** (that loop had no commits at all). Each template is now committed on success and rolled back on failure, with failed ids reported, matching `_process_rs_rows`.
  - New `_rs_run_per_company()` isolates each company's pass, so one company's account being down, mis-credentialed or returning something unparseable can't stop the others. All six entry points go through it.
- **RS.GE calls on a never-saved waybill now say what's wrong.** Eight handlers — Cancel, Delete, Reject, and the four transporter/invoice/print actions — passed `rs_internal_id` straight into `int(...)`, so a waybill that had never reached RS sent **waybill_id 0** and came back with a generic RS failure code the operator has no way to interpret. New `_require_rs_id()` guard on `rs.waybill` refuses the call before it reaches the SOAP layer, with the same "Please save the waybill to RS.GE first." message the close path already used.
- **Each company syncs with its own RS.GE account.** Every cron entry point borrowed a single credentialed user — `search([('rs_username','!=',False)], order='id', limit=1)` — and fetched everything through it. An RS.GE service account belongs to **one taxpayer**, so in a database with two companies the second company's waybills were simply never returned by RS: nothing failed, nothing was logged, the data just wasn't there. `_rs_sync_contexts()` now yields one `(company, user)` pass per credentialed company, and `action_sync_seller_waybills`, `action_sync_buyer_waybills`, `action_sync_transporter_waybills`, `action_sync_templates`, `_cron_sync_updated_waybills` and `_cron_rs_drift_repair` each loop over it. A company with no credentialed user is **skipped and logged**, never synced through someone else's account; a company with no TIN isn't an RS taxpayer and is ignored. `_get_rs_sync_user(company)` takes the company's RS Responsible User only (see below): logins are stored per user and per company (2026-09-29), every call on a waybill runs under the waybill's company (`_rs_service()`), and the XML names the company's taxpayer id, not the login's.
  - **Interactive use is unchanged:** when the caller already has credentials — an operator clicking Fetch All — that user and their active company are the only pass, exactly as before. Covered by a test so it stays that way.
  - **The incremental cursor is per company** (`rs_waybill.last_v1_sync.<company_id>`). A shared cursor would let company A's successful pass advance the window for company B, which would then never fetch the rows it skipped. On first read it falls back to the legacy shared key, so an upgraded database resumes where it left off instead of re-fetching 30 days for every company.
  - **Drift repair is scoped too:** its candidate domain is now limited to the company whose account is running the pass (plus legacy `company_id = False` rows). Polling company B's waybill with company A's credentials gets `-101` or an empty response, counted as "skipped" — so its drift was never repaired.
- **The RS settings that belong to a company now live on the company.** `Stock Integration Start Date`, `Apply Product Mapping From` and `Waybill Notification Recipients` were single global `ir.config_parameter` values, but all three are read against a waybill and a waybill belongs to a company — so two companies in one database were forced to share one go-live date, one mapping cutoff and one recipient list. They are now fields on `res.company`, exposed through `res.config.settings` as `related=` fields (so the standard settings machinery saves them; the hand-written `get_values`/`set_values` for them is gone, along with its habit of drifting out of sync). Readers take the waybill's own company, falling back to the active one. `base_setup` added to `depends` — `res.config.settings.company_id` comes from there.
  - **Upgrade path:** `res.company.init()` backfills each company from the old global parameter on `-u rs_waybill`, filling only fields that are still empty (idempotent, never overwrites a company that already decided, treats the old `str(False)` as unset, and ignores stale user ids). Without it the upgrade would leave every company with **no** integration cutoff — and `_in_integration_scope()` answers False when the cutoff is unset, which would silently stop Odoo documents being created for new waybills. The legacy parameters are left in place rather than deleted, so a module rollback still finds them.
  - **Deliberately still global:** the two Auto-Sync switches toggle `ir.cron.active`, and a cron is one job for the whole database; `rs_waybill.last_v1_sync` is the incremental cursor for a single RS.GE account that covers every company. The three `Enable …` switches are stored but read by no code today, so they stay as they are.
- **Multi-company isolation on waybills (`security/rs_waybill_rules.xml`).** `rs.waybill` carries `company_id` and the sync engine deliberately classifies incoming RS rows per company, but nothing stopped a user of company A from reading, editing or **cancelling** company B's waybills — which are tax documents. Two **global** `ir.rule` records now scope `rs.waybill` by `company_id` and `rs.waybill.line` through its parent (lines have no `company_id` of their own, so without a rule of their own another company's products, quantities and prices were readable by querying the line model directly). Rows with `company_id = False` stay visible to everyone — the field isn't required and hiding legacy rows from all users would be worse than the leak. Being *global* rules, they are ANDed with everything else and don't depend on the still-open question of which functional groups this module will have.
- **The RS crons keep sweeping every company.** Direct consequence of the rule above: the sync and drift crons authenticate as a **single** credentialed user (`_get_rs_sync_user`) but must cover all companies. Left alone, the record rule would have narrowed `_process_rs_rows`'s existing-record lookup — the sync would stop recognising another company's waybill, treat the RS row as new, and the partial unique index on `rs_internal_id` would reject it — and would have silently narrowed the drift rotation to that user's own companies. Both lookups now run `sudo()`, with a test pinning down exactly why.
- **`close_date` field on the waybill.** RS's `CLOSE_DATE` now has its own field, shown next to Cancel Date as an optional column on all four waybill lists and on the Live RS View. See the matching fix below.

- **Distribution sub-waybills (type 4 parent → sub-waybills).** The "New Sub-Waybill" / "New Sub-Waybill/Internal Transport" buttons on a Distribution (type 4) waybill now create a real child waybill (`action_create_sub_waybill` → RS type 4; `_internal_trans` → type 1), linked to the parent via the new `parent_waybill_id` field (drives RS `PAR_ID`). The child copies the parent's type/category/seller/start-address and **goods lines with quantity 0 and `remainder` = the parent's still-available qty** (computed from completed sub-waybills, so it never double-counts). On a sub-waybill the form hides transport/driver (inherited from the parent), locks the goods grid to **quantity-only** (no add/remove), and the remainder updates live as you type (`parent_remaining − quantity`). Buttons: **Save** (`save_waybill` with `PAR_ID` → RS numbers it `…/1`), **Main Waybill** (open parent), **Sub-Waybill Complete** (`send_waybil_vd` + `close_waybill_vd`, then writes back the parent's remaining quantities). Validation requires `0 < qty ≤ available`; driver/car/warehouse requirements are skipped for sub-waybills. New SOAP wrapper `send_waybil_vd`. Per sub type: a **distribution sub** (type 4) shows + requires **buyer TIN / name / delivery address**; an **internal-transport sub** (type 1) shows seller + requires **only the delivery address**. Distribution waybills (and sub-waybills) now expose a **Transport Start Date** that maps to RS `BEGIN_DATE` (previously always blank). The parent distribution/internal-transport behaviour is unchanged — only their sub-waybills differ. The distribution form shows a **Sub-Waybills** table (number, recipient TIN/name, goods quantity, amount, registration date, state) via the `sub_waybill_ids` relation, mirroring the RS.GE layout. On a distribution waybill, setting a line quantity auto-fills its `remainder` (they match at creation); a sub-waybill **reserves** its quantity from the parent the moment it's **saved** (remainder drops on Save, not only on Complete). Cancelling a sub **restores** its quantity to the parent; cancelling the parent distribution **cancels its sub-waybills first, then the parent** (RS returns `-3` if you try to cancel a distribution that still has live subs). Parent cancel uses RS `ref_waybill_vd`, subs use `ref_waybill`. (RS `_vd` = "with date/comment" param, not "virtual distribution".) The Sub-Waybills table opens a sub full-page via an **Open** button (row-click no longer pops a dialog); a sub-waybill's form shows only Save/Main Waybill/Sub-Waybill Complete/Edit/Cancel/Print PDF/Live RS View. Internal-transport subs go to RS as `TYPE=1` with empty TRANS_ID/no driver (RS inherits buyer=self + driver/transport from the parent); distribution subs go as `TYPE=6` with a buyer. Subs auto-activate on Save (parent is already active). **Odoo document integration is sub-waybill-driven only** (never from the parent distribution, never SO→sub): a **distribution sub → Sales Order + delivery** (buyer = its partner), an **internal-transport sub → internal transfer** (its From/To warehouses, now shown + required on the internal sub). Created via the existing `_rs_create_documents_if_missing` on Save with `skip_rs_auto_create`. The full sub lifecycle cascades to its docs: **Save** creates them, **Sub-Waybill Complete** validates the delivery/transfer (`_cascade_validate_picking` → goods move), **Cancel** cancels the linked Sales Order (distribution sub) + delivery/transfer and restores the parent remainder.
- **Remainder Waybill.** A **Remainder Waybill** button on a Distribution creates a **separate** Distribution (TYPE=4, no buyer — TYPE 4 doesn't require one) for the **undistributed leftover** (goods = parent qty − distributed; copies the distribution's driver/transport/seller). It's **not** a sub-waybill — linked locally via `remainder_origin_id` (shown on Status & Technical; no RS `PAR_ID`). It does **not** consume the remainder and several can be created. On Save it builds a **return transfer** (the leftover comes back to stock) via `_rs_create_return_transfer_from_waybill`.
- **State icon column on the waybill lists.** A new narrow icon-only first column shows each waybill's `state` as a coloured FontAwesome icon matching the KPI cards: draft → file (grey), active → check-circle solid (blue), completed → check-circle outline (green), cancelled → times-circle (red). Implemented as a reusable OWL field widget `waybill_state_icon` (`registry.category("fields")`) in `waybill_state_icon.{js,xml,scss}`, applied via `<field name="state" widget="waybill_state_icon"/>` on the default, Sent, Received, Saved and Transporter lists.

#### Changed

- **Crons use the RS Responsible User only.** `_get_rs_sync_user(company)` no longer falls back to "the oldest user holding a login for the company": that user depended on who happened to enter a login, the sync ran with their access rights, and it disagreed with the e-invoice crons, which already skip such a company. A company without an RS Responsible User is now skipped with a warning. `company` is required; the unused "any user in the database" branch is gone.
- **Missing `rs_base_methods` is reported, not a crash.** In Odoo 20 `rs_base_methods` depends on this module, so it cannot be in `depends` (that would be a cycle). `_get_credentials` now raises a translated `UserError` asking to install it, and `_rs_sync_contexts` logs an error and returns no passes, instead of `AttributeError`. Supersedes the 19.0 note that declared it as a dependency.
- **Dead code removed:** `check_credentials`, `_get_seller_un_id` and `_RS_UN_ID_CACHE`. The seller taxpayer id comes from `rs_un_id` (stored per company by Test SOAP) since `_rs_company_un_id`; nothing called them.
- **Licence is `AGPL-3`**, matching `rs_base_methods`.
- **RS reply codes are checked on every action call.** `send_waybill`, `confirm_waybill` and `reject_waybill` returned RS's raw integer result, so a rejection (`-1` / `-100` / `-101`) came back looking like success and the caller flipped the Odoo state to active/confirmed anyway — Odoo said active, RS said rejected. All three now go through the shared `_check_rs_result` decoder like `close_waybill`/`delete_waybill`/`refuse_waybill` already did (`send_waybil_vd` too). No caller used the raw value.
- **New-record ids from RS are validated before use (`_check_rs_id`).** `save_invoice` and `save_waybill_template` answer with either a positive id or a negative error code; the callers did `int(...)` on whatever came back, so `-100` was stored as `rs_invoice_id` / `rs_template_id`. Both now return a validated positive int or raise a decoded `UserError`.
- **The excise/product sync is batched instead of row-by-row.** `action_update_rs_products` did a `search()` per row and a `create()` per record across ~1300 excise codes and ~1000 products — thousands of queries in one request. Existing codes, products (by barcode and by excise code) and UoMs are now prefetched into dicts once, creates are batched into single `create([...])` calls, and an unchanged code costs zero `UPDATE`s (only differing values are written).
- **KPI cards no longer sit inside the list's render path.** `waybill_list_kpis.js` reassigned `model.load` to `await refreshKpis()`, putting 8 `searchCount` RPCs inside every load/filter/sort/page — and one rejection took the whole list render down with it. The controller now listens on `model.bus`'s `update` event (the documented hook; `useBus` unsubscribes on unmount) and refreshes in the background, serialised so overlapping updates coalesce into one trailing refresh, with failures logged instead of thrown.
- **Waybill list KPI cards now show a per-card "today" count.** Each of the four cards above the list (Total / Active / Cancelled / Completed) keeps its big filter-aware number and adds a small coloured sub-line counting today's records *for that card's own metric*: Total → `N new today` (`create_date`), Active → `N active today` (`activation_date`), Cancelled → `N cancelled today` (`cancel_date`), Completed → `N completed today` (`delivery_date`). "Today" is the user-timezone start of day serialized to UTC; each count reuses the card's existing domain so it stays filter-aware. Implemented as four extra `searchCount` calls in `refreshKpis` (`waybill_list_kpis.js`), bold sub-line spans in `waybill_list_kpis.xml`, and accent-coloured `b` styling in `waybill_list_kpis.scss`.
- **KPI cards are now clickable filters.** Clicking Active / Completed / Cancelled toggles the matching search-view filter so the list shows only that state (exclusive — clicking another state switches, clicking the active card again or clicking Total clears back to all). Implemented by toggling the existing `filter_active` / `filter_completed` / `filter_cancelled` search items via `this.env.searchModel` (`onKpiClick` in `waybill_list_kpis.js`), so the search-bar facet and the KPI numbers stay in sync. The selected card gets an accent ring/border (tracked via `kpis.activeKey`, recomputed in `refreshKpis`; defaults to Total when nothing is filtered).
- **Fourth KPI card is now "Completed" (was "Unconfirmed").** Counts `state = completed` (green check-circle, matching the completed state icon); its "today" sub-line counts waybills delivered today (`delivery_date`). Active uses blue + solid check, Completed uses green + outline check (icons/colours swapped so the two read distinctly).
- **Form layout / field cleanup (main waybill form).** Removed the standalone read-only **Transport Start Date** display (RS exposes only the **Transport Start Date Postpone** field); reordered the lower section to **Transport Start Date Postpone → Handed Over By / Received By → Delivery Date → Note/Comment** (the old "Notes" label is now "Note/Comment"). **Transport Cost Payer** is now also shown for **Auto-Foreign country** transport (`transport_type == '6'`). For an internal-transport + Carrier waybill the **Delivery Address** now sits **above** the Carrier Information card.
- **Driver/car requirement scoped to road transport only.** `_validate_before_save` now requires Driver TIN (or foreigner) + Car Number only for transport types **Auto (1), Auto-Foreign (6), Moped/Motorcycle (8)** — matching the form's Driver Information card visibility. Railway (2), Air (3) and Other (4) no longer wrongly demand driver/car (previously it required them for every type except Carrier).
- **Delivery Date now defaults to exactly the Transport Start Date.** On activation `_set_default_delivery_date()` sets Delivery Date = transport start (was start + 1 minute). Since RS requires delivery strictly *after* start, this default is intentionally invalid for completion — so on **Complete** the operator gets "Delivery Date cannot be equal to or earlier than the Transport Start Date" and must set a real, later delivery date before the waybill/sub can be completed.
- **Adjustment button hidden on draft (saved-on-RS) waybills.** The Adjustment button now appears only on **active/completed** waybills; in draft the form is already editable and **Save** re-pushes to RS, so a formal (version-archived) adjustment is redundant there.

#### Fixed

- **A failure part-way through a batch validate or cancel no longer corrupts the rest of it.** RS.GE mutations aren't transactional with Odoo, and `action_close_waybill` / `action_refuse_waybill` commit as soon as RS accepts — which made multi-picking operations destructive:
  - **Validate** (`_action_done`): `super()` marks *every* picking in the recordset done, then each waybill is closed on RS. The first successful close committed the whole batch's done-state, so an exception on picking N left pickings N..last recorded as delivered in Odoo while RS still called their waybills **Active**, with no error path back. Each close is isolated now — the rest of the batch still closes, and the failure is written to the waybill's `rs_post_commit_error` (form banner) and the picking's chatter.
  - **Cancel** (`action_cancel`): the RS cancels run *before* `super()`, so a failure on picking N aborted the cancel for all of them — while pickings 1..N-1 already had their waybills cancelled on RS and committed, leaving cancelled waybills attached to live transfers. A picking whose RS cancel fails is now **excluded from `super()`**, so its waybill and its transfer stay consistent with each other and the rest of the batch proceeds.
  - **Single-record** validate and cancel keep their original all-or-nothing behaviour — the RS call raises before its commit, so nothing is left behind. Both are covered by tests so the distinction doesn't get lost.
- **A step that fails after RS.GE already accepted the operation is now recorded and retried.** The lifecycle buttons `cr.commit()` right after the RS call, deliberately — an RS-side close or cancel can't be undone, so rolling Odoo back would leave it forgetting what RS remembers. The problem was everything that runs *after* that commit. Three defects, now fixed together:
  - `_do_validate_linked_picking` and `_cascade_cancel_purchase` swallow every exception but had **no savepoint**. Catching a *database* error without one leaves the transaction aborted, so every subsequent query fails — including the `message_post` that was supposed to record the failure, taking the whole request down with it. Both now wrap their body in `cr.savepoint()`.
  - Several post-commit steps had no guard at all and escaped as tracebacks while RS was already final: `_rs_create_documents_if_missing` (5 call sites), `_refresh_distribution_remainder`, and the picking/sales-order cancels in `action_refuse_waybill`. All now go through a new `_rs_post_commit(label, func)` helper — savepoint, catch, chatter note, and the reason stored in a new **`rs_post_commit_error`** field shown as a warning banner on the Status & Technical page.
  - **Nothing retried.** A failed cascade became a chatter note nobody reads, and the drift cron couldn't see it: that cron repairs fields where Odoo and RS *disagree*, but here they agree (both say completed) — what's missing is the Odoo-internal follow-through, which no field comparison detects. New `_rs_repair_local_state()`, called by the drift cron for every candidate, retries the three outstanding cases (completed but transfer not validated / confirmed but receipt not validated / documents never built) and clears the flag once nothing is outstanding. This is what turns a permanent divergence into a temporary one.
- **Excise codes' "Currently Active" no longer freezes at write time.** `is_currently_active` was a **stored** compute whose value depends on *today*, but whose only triggers were `active_from` / `active_until` edits — and the calendar advancing is not a trigger. With no cron recomputing it, the stored boolean froze at whatever it was when the code was last written: **expired codes stayed pickable** in the Excise Code picker (`rs_excise_id`'s `domain="[('is_currently_active','=',True)]"`) and in the product-creation loop, and codes whose `active_from` was in the future **stayed hidden after they became valid**. The field is now computed on read, with a `_search_is_currently_active` method translating the domain into the same two indexed date columns so both call sites keep working. (Visible effect: expired codes now actually disappear from the picker, and future ones appear on the right day.)
- **The excise catalog sync no longer rewrites validity data RS didn't send.** `action_update_rs_products` built its update vals with `'active_from': start_date or fields.Date.today()`, so every run reset `active_from` to **today** for any code whose RS row carries a blank `START_DATE` — silently walking those codes' validity windows forward on each sync and corrupting their history. `active_from` is now written only when RS actually sent a `START_DATE`; the today-default survives on the **create** path only (the field is required, and a new code has to start somewhere).
- **The sync's "skip unchanged" check compares dates as dates.** The batching added above stored RS's raw `'YYYY-MM-DD'` strings in the comparison vals while `active_from` / `active_until` read back as `date` objects — and a date never equals its string form, so every code with a date looked changed and was written on every run. Parsed via a small `_as_date` helper before comparing.
- **"Reconcile Delivery" crashed every time it was used.** `rs_waybill_actions.py` called `json.loads(self.pending_return_json)` but never imported `json`; the `except (ValueError, TypeError)` below it doesn't catch `NameError`, so the button raised an unhandled 500 on every click since it was written. Added the import.
- **A `save_waybill` reply with no `<STATUS>` was treated as success.** The parser read `int(status.text) if status is not None else 0` — so a fault-shaped or truncated response scored 0, passed the `< 0` check, and Odoo stored an empty RS id and waybill number as though the waybill had been created on RS. A missing `STATUS` is now an error and the raw XML is logged.
- **The transporter leg sent UTC datetimes to RS.** `send_transporter_waybill` / `close_transporter_waybill` forwarded `begin_date` / `delivery_date` verbatim while their `_vd` siblings converted UTC→Tbilisi — the same −4h class of bug that makes RS answer `-1` to a close ("delivery before transport start"), just left unfixed on the carrier path. Both now convert. `CLAUDE.md`'s conversion-points list has been updated to include them.
- **Adjustment snapshots displayed all dates 4h off.** The snapshot's `_norm_dt` normalised the RS string but never converted Georgian local → UTC, unlike the ingest path. Both now share one converter, `rs.waybill.soap.service.rs_local_to_utc`.
- **RS `CLOSE_DATE` no longer shows up as a Cancel Date.** RS sets `CLOSE_DATE` on *any* close, normal delivery completion included, but the sync wrote it into `cancel_date` — so a completed waybill synced back from RS displayed a cancellation date, and the "cancelled today" KPI counted completed waybills. `CLOSE_DATE` now maps to the new `close_date` field; `cancel_date` is written only by `action_refuse_waybill`.
- **Integration cutoffs are compared as Georgian dates.** `_mapping_enabled` / `_in_integration_scope` called `.date()` on a UTC-stored datetime and compared it to a Georgian business-date cutoff, so anything created 20:00–24:00 UTC (00:00–04:00 next day in Tbilisi) was judged a day early — on the cutoff day itself, an in-scope waybill got no Odoo documents and skipped the product rules. Both now go through the new `rs.waybill._tbilisi_date()` helper.
- **A goods line added during an edit no longer breaks the reconcile.** `_compute_line_diff`'s "added" branch set `'snap': snap`, reusing the *previous* loop's variable: undefined when the snapshot was empty (`NameError`, swallowed by the broad handler upstream, which aborted the entire goods reconcile and posted "could not be auto-applied"), and the wrong line's snapshot data attached to every added line otherwise. Added lines now correctly carry `'snap': None`.
- **A cold SOAP history buffer no longer leaks a traceback.** `get_full_waybill` and `get_car_numbers` read `history.last_received` unguarded — on the first RS call in a fresh worker zeep's plugin buffer is empty and that raises `IndexError`. Both are guarded now, and `get_adjusted_waybill` / `get_full_waybill_with_client` had `IndexError` added to their existing `(TypeError, KeyError)` guard. This matters most for the drift cron, which calls `get_full_waybill` up to 200× per run.
- **The adjustment-count smart button no longer does network I/O per row.** `_compute_adjustment_count` had no `@api.depends` and fired one synchronous SOAP round-trip per record, so putting the field in a list view meant N round-trips per page. It now declares its dependency, computes over the wire only for a single record (a form), returns 0 for multi-record reads, and logs RS failures instead of silently reading 0.
- **The product sync could create two products for one excise code.** Step 2 creates a product per active excise code (deduped on `rs_excise_id`); step 3 deduped only on barcode, so a barcode whose RS name matched an excise title created a *second* product pointing at the same `rs.excise.code` — nothing in the schema prevents it. Step 3 now checks for an existing product on that code first and tags it with the barcode instead.
- **Close fallback no longer masks credential/ownership errors.** `_close_on_rs` previously caught *every* `UserError` from `close_waybill_vd` and silently retried with the plain `close_waybill` — so a `-100` (bad RS credentials), `-101` (wrong taxpayer), other error code, or network failure was swallowed and re-surfaced confusingly. It now calls `close_waybill_vd(..., check=False)` to read the raw RS code and falls back **only on `-1`** (the delivery-vs-begin/future window); any other code is raised via `_check_rs_result` with its real message, and transport failures propagate.
- **"Without Transport" (type 3) waybills now create their Sales Order + delivery on Complete.** Type 3 has no separate **Activate** button — `action_close_waybill` takes it draft → active → completed in one step. The `_rs_create_documents_if_missing()` call at the top of that method ran while the waybill was still **draft**, where the reverse-create deliberately skips (draft = no Odoo document), and the type-3 branch never re-ran it after activating — so the SO/delivery were never built and `_cascade_validate_picking` had nothing to validate. The type-3 branch now calls `_rs_create_documents_if_missing()` again right after it flips the waybill to active (idempotent — no-op if already linked). Type 2 was unaffected (its Activate button already creates the docs after going active).
- **Handed Over By / Received By / Note-Comment are now editable on the draft form.** Because RS has no clean way to set these on a sent waybill (any `save_waybill` flags it "adjusted"), they're now shown + editable on **draft** so they ride along in the initial Save and reach RS **without** an adjustment. On active/completed they're read-only (`readonly="is_locked"`) — changing them there is a genuine edit and goes through **Adjustment**. Delivery Date is unaffected: it stays an active-form field and is set cleanly at Complete via `close_waybill_vd`.
- **Sub-Waybill Complete no longer fails on the delivery-date window (-1).** An immediately-completed sub auto-activates on save, and RS stamps its `BEGIN` (transport start) at that activation moment — so a delivery date equal to "now" lands just before `BEGIN` (no valid `(begin, now]` window) and `close_waybill_vd` returns -1 ("delivery date is greater than current date" / before begin). New shared helper `_close_on_rs()` tries `close_waybill_vd` (to record the delivery date when there's a real time gap) and **falls back to the plain `close_waybill`** when RS rejects it, so Complete always goes through (RS records its own current time). Used by Complete (all types) and Sub-Waybill Complete.
- **A future Delivery Date no longer breaks Complete.** Setting a Delivery Date in the future on an active waybill and completing returned `close_waybill_vd → -1` (RS won't mark a delivery as done before it has happened). New `_clamp_future_delivery_date()` clamps a future delivery date to *now* at Complete (and on Sub-Waybill Complete), so the close goes through with the delivery recorded as now. `_check_delivery_after_start` still enforces delivery > transport start.
- **Complete is a clean close again — no spurious "adjusted" flag.** A brief attempt to push Handed Over By / Received By / Notes to RS on Complete called `save_waybill` right before closing; because **RS flags any `save_waybill` on a sent waybill as "adjusted"** (the regular `close_waybill` / `close_waybill_vd` have no reception/receiver params — only `close_waybill_transporter` does), every Complete showed the adjustment icon. Reverted: `action_close_waybill` now closes directly (`close_waybill_vd` with the delivery date, plain `close_waybill` otherwise) with no pre-close save, matching rs.ge's own Complete. Changing Handed Over By / Received By / Notes on an active waybill is an edit and must go through the **Adjustment** button (which legitimately archives a version on RS).
- **`save_waybill` no longer wipes the delivery date on RS.** `_build_waybill_xml` previously hard-coded `<DELIVERY_DATE></DELIVERY_DATE>` (empty), so any save on an active/completed waybill (e.g. an Adjustment) cleared RS's delivery date. It now sends the record's `delivery_date` converted UTC→Tbilisi local (empty only when none is set, e.g. drafts).
- **`WAYBILL_STATUS` NameError in notification emails.** `rs_waybill_notification.py` used `WAYBILL_STATUS` without importing it, so `_send_notification_email` raised `name 'WAYBILL_STATUS' is not defined` (surfaced as "Enrichment failed … drift cron will repair" after Activate/Complete). Added `from .rs_waybill import WAYBILL_STATUS`.

### 19.0.1.10.0 — 2026-06-10

#### Fixed

- **Intercompany waybills no longer flag goods as "unresolved" (no Resolve button).** When the **seller** of a buyer-direction waybill is **one of our own companies** (intercompany — e.g. company A issues a waybill to company B), the goods are our own products that already exist in inventory. The buyer side previously ran the seller-scoped external-barcode mapping, found no *external* alias for our own product, and flagged the line `unresolved` → showed the **Resolve Now** button. New guard `_rs_seller_is_own_company()` (seller_tin ∈ our companies' TINs) turns the mapping **off** for intercompany waybills in `_sync_goods_lines`, so lines resolve directly by barcode (find-or-create) and are never flagged. External-vendor waybills are unchanged (mapping still applies to genuinely foreign barcodes).
- **Sent / Received menus now route by the ACTIVE COMPANY's role, not by the stored `waybill_direction`.** In a multi-company DB a single waybill (one `rs_internal_id`) is the **seller's** document for one of our companies and the **buyer's** document for another — most visibly on **type-5 returns** between two of our own companies. The old menus filtered on the one `waybill_direction` value, so an intercompany return showed for only one side (e.g. the buyer company in Received) and never for the seller company in Sent. New computed, company-context-aware field **`rs_menu_side`** (`compute` + `search`, `@api.depends_context('company')`) matches the **active company's TIN** against `seller_tin` / `buyer_tin`: seller_tin = ours → **Sent**, buyer_tin = ours → **Received**, neither → hidden. The **Sent**, **Received** and **Saved** action domains now filter on `rs_menu_side` instead of `waybill_direction`. Switching the active company re-routes the same record to the correct menu for that company. **No data migration** — `waybill_direction` is untouched and still drives all document/business logic; only the menu *filtering* changed. This also **subsumes** the internal-transport (type 1) case: such a waybill has `seller_tin == buyer_tin == our TIN`, so it naturally matches **both** menus for its company (replacing the earlier `waybill_type == '1'` branch on the Received domain).

#### Removed

- **Draft-waybill → sales-quotation mirroring removed (reverse seller flow).** The state-fidelity "draft mirroring" added in `19.0.1.9.0` (a draft seller waybill spawned a draft **quotation**, later confirmed via two doors + an adoption guard) is gone. Reverse creation now does the simpler, correct thing: a **draft** seller waybill (status ≠ 8) creates **no Odoo document at all**; the confirmed **Sales Order + delivery** is built only once the waybill goes **active/sent/completed** (`_rs_create_so_and_delivery_from_waybill` early-returns while draft). Removed `_rs_confirm_quotation_if_needed` and its six call sites, and the **adoption guard** in `stock.picking._action_assign` (no quotation-stage waybill can exist to adopt). The forward flow (SO → reservation → waybill) and the internal/return transfer paths are unchanged. Net effect: **no SO is created for a draft waybill** — only when it's activated.

#### Changed

- **Seller barcodes are no longer trusted for global matching (buyer waybills).** `_resolve_product` now resolves a buyer line **only** via the seller-scoped `rs.product.external.ref` (seller + their barcode → our product). The previous global `product.barcode` match was removed: RS "barcodes" aren't globally unique (a seller's short code like `465` could collide with one of our product barcodes for a *different* product and silently mislink). Now: known seller+barcode → auto-resolves; otherwise the line stays **unresolved** for one-time operator mapping (which saves the alias, so it auto-resolves thereafter). Seller-direction is unaffected (uses our own barcodes). Buyer lines created on/after the **Mapping Cutoff Date** go through this path.
- **Mapping wizard now auto-creates the documents.** After **Resolve Now → Apply** resolves all lines, the wizard immediately runs the doc dispatcher (buyer → PO+receipt, seller → SO/delivery/transfer) when in scope — no separate Update click needed.
- **Receive is blocked until every line is resolved.** Buyer Receive buttons are hidden while `unresolved_count > 0`, and `action_confirm_waybill` raises a clear error if called with unresolved lines (also guards bulk "Mark as Received"). Prevents confirming on RS with no PO/receipt created.
- **Drift-repair cron is now a fair round-robin.** New `rs_drifted_checked` timestamp; each run takes the least-recently-checked batch (never-checked first), stamps them, and covers **all non-cancelled** waybills (draft/active/completed — completed can still be seller-edited) over time instead of re-scanning the same first 200 each run. Cancelled is excluded (terminal).
- **`origin_waybill_number` + clickable `origin_waybill_id`** on `rs.product.external.ref` — trace which waybill each seller↔product alias was first created from (shown on the product's External References page).

#### Refactor (no behaviour change)

- Split the 2,879-line `rs_waybill.py` for maintainability: `rs_waybill_actions.py` (all `action_*` buttons), `rs_waybill_notification.py` (email builder), and moved the drift cron into `rs_waybill_sync.py`. All same `rs.waybill` model via `_inherit`; fields stay in core. Each file's methods are grouped under `# ═══ SECTION ═══` headers (Computes / Onchanges / CRUD / Scope & Resolvers / Validation / Document Creation / Edit-Diff / Cascades, etc.). Core is now ~1,840 lines.
- **Removed `rs_waybill_stock.py`** — its planned PO/SO purpose is now built into the real integration; it was disabled (unimported) and unreferenced.

### 19.0.1.9.0 — 2026-06-05

#### Added

- **Lock guard on the Purchase Order (buyer direction).** Mirroring the existing SO/delivery lock: when a linked vendor waybill is on RS and not cancelled, the PO's **order lines become read-only** with a banner explaining that a buyer cannot edit a vendor-issued waybill — changes arrive from the vendor via RS sync (use **Receive**/**Reject** on the waybill). New computed `rs_waybill_locked` on `purchase.order`. The vendor field needs no extra lock (core Odoo already locks `partner_id` once the PO is confirmed). Closes the drift hole where a manual PO edit would trigger `purchase_stock`'s auto move creation and diverge from the vendor's waybill with no way to push the change to RS. View-level only — the module's own reconcile/cascade code keeps writing programmatically.

#### Changed

- **Direction-aware lock banner on the transfer.** The picking's lock banner now differs by waybill direction: seller deliveries keep the "open the waybill and use **Edit Waybill**" message; buyer receipts now correctly say the waybill is vendor-issued and changes arrive via RS sync (Receive/Reject) — a buyer cannot "Edit Waybill" on a vendor's document. New related `rs_waybill_direction` on `stock.picking`.

#### Fixed

- **Buyer reconcile no longer double-creates receipt moves.** `_reconcile_buyer_goods` wrote PO lines **and** built the receipt moves manually — but on a confirmed PO, `purchase_stock`'s create/write hooks (`_create_or_update_picking`) already build/merge those moves (and spawn a fresh receipt when the original is done). Result: a new product on a Ready receipt got **2× demand** on the same picking; an increase on a Done receipt left a **phantom Ready receipt** behind after the manual supplementary was validated. Rewritten hook-first: only the PO lines are written; the hook builds the moves; the code then validates **exactly the hook-built moves** (`_force_validate_moves`, replacing the picking-wide `_force_validate_picking`) and keeps a verify-and-correct safety net for the Ready case.
- **Line removal on a Ready receipt crashed.** The zero-qty path called `purchase.order.line.unlink()`, which Odoo forbids on a confirmed PO (`_unlink_except_purchase`) — the UserError aborted the rest of the delta loop, leaving a line with qty but no move. Now zeroes the line (same convention as SO lines) and cancels its moves.
- **Vendor return now decrements `qty_received`.** The outgoing return move had no `purchase_line_id`, so `_compute_qty_received` never counted it and the PO stayed permanently over-received (wrong billing status). The return move now carries `purchase_line_id`; supplier-destination done moves count negative, so received qty drops to match. Return picking type is now warehouse-aware (`receipt warehouse → out_type_id` before the company-wide fallback).
- **Corrupt `pending_goods_json` is surfaced.** On Receive, an unreadable delta now posts a chatter note instead of being silently discarded. *(Superseded same-day by the target-state reconcile below — the stored JSON no longer drives the math.)*
- **Vendor return must land in a `usage='supplier'` location.** purchase counts a done move as a return (decrementing `qty_received`) only via `_is_purchase_return()` — i.e. `location_dest_id.usage == 'supplier'`. The return used `partner.property_stock_supplier`, which for a partner that is itself a company in the same DB is an **inter-company transit** location — so the return was counted as **+received** (e.g. 5 received, return 2 → received 7). The destination is now validated: property location only if `usage == 'supplier'`, else the global Vendors location; the move also carries `to_refund=True`. (Live-test finding.)
- **Cron sync misclassified incoming waybills in multi-company DBs.** `_cron_sync_updated_waybills` split rows by comparing `SELLER_TIN` to the *sync user's default company* TIN — with two companies in the DB, incoming waybills of the other company matched the seller branch and were created as seller-direction records **with bogus Sales Orders** instead of buyer records with POs. Rows are now classified against the TINs of **all** companies (buyer side wins for intercompany rows — Odoo-issued waybills are protected by the direction-mismatch guard) and each bundle is processed under its own company (`with_company`), so POs/SOs land in the right one. (Live-test finding.)
- **All sync entry points unified on one ownership model.** New `_rs_company_tin_map()` is the single source of classification truth (self-to-self → seller path; buyer TIN ours → buyer path; seller TIN ours → seller path). The **Fetch-All seller and buyer syncs** now bundle rows **per company** and process each bundle `with_company(...)` — previously they stamped whichever company the clicking user had active onto every row (wrong TIN/name overrides for the other company's waybills). The **transporter sync** now skips rows where we are also the seller or buyer (those belong to the other paths) — eliminating the endless direction-mismatch warning flood (~25 warnings per run). Drift-repair and template crons audited: correct as-is (per-record, no classification).
- **Type-aware sync routing for special waybill types.** Self-to-self rows (buyer TIN = seller TIN, i.e. **internal transport, type 1**) are now always routed to the **seller** path — both in the cron classifier and in the Fetch-All seller sync — because that's where `_rs_create_documents_if_missing` creates the internal transfer (no SO/PO); the buyer path would create nothing. The Fetch-All seller sync also adopts the cron's **buyer-priority rule** (rows whose BUYER_TIN is one of our companies are left to the buyer path), so the two paths can no longer race each other into opposite directions for intercompany waybills.
- **Validate-cascade is seller-only.** `stock.picking._action_done` auto-closed ANY active linked waybill on RS — including the **vendor's** waybill when a buyer receipt was validated (RS refused: "belongs to another taxpayer"). Both the pre-checks and the auto-close now run only for `waybill_direction == 'seller'`; buyer documents are governed by Receive/Reject + the sync cascades.
- **DB-level unique constraint on `rs_internal_id`.** Uniqueness was only enforced by an in-code lookup, which concurrent sync runs (cron + Fetch All) can race past. A real SQL `unique` constraint now makes duplicates impossible (local drafts with no RS id are unaffected).

#### Added

- **Draft mirroring — quotations for draft seller waybills (state-fidelity).** A seller waybill that is still a DRAFT on RS (a deletable sketch, status ≠ 8) now creates a **sales quotation** instead of a confirmed SO+delivery. It is confirmed through either door: the user confirms the quotation on the SO form (a new **adoption guard** in the reservation hook links the spawned delivery to the existing waybill instead of creating a duplicate), or the waybill leaves draft — Activate / Send-to-Transporter / Complete buttons and all three pull paths (sync, Update, drift) call the new `_rs_confirm_quotation_if_needed` when the waybill is seen active/sent/completed (portal activation included). If the seller deletes the RS draft, the leftover is a non-binding draft quotation (one-click deletable) instead of a phantom confirmed order. Buyer direction intentionally unchanged — vendors activate before a waybill ever reaches a real buyer feed. Transfers (types 1/5) keep activation-time creation (pickings have no quotation stage). Repeated Saves no longer re-enter creation (`sales_order_id` guard).
- **Update button creates missing documents.** `action_update_rs_status` now runs the same idempotent creation dispatchers as the sync after refreshing — fix the cause (map a product, set warehouses), click Update, documents appear. Previously the only recovery was rewinding the cron's `last_v1_sync` timestamp by hand.
- **Product / UoM / external-ref fixes.** `is_rs_product` is read-only (system-managed). The product **Send to RS.GE** button visibility was inverted — it now shows when a barcode is set and the product isn't yet on RS, and "already registered" is a notification, not a hard error. Product-import UoM matching hardened (int-cast RS `UNIT_ID`, name fallback, logs unmapped units); `_sync_rs_units` made case-insensitive (`'Kg'`↔`'kg'`) + idempotent so **Update Products** reliably re-maps all RS units. `rs.product.external.ref` gains **`origin_waybill_number`** — the RS waybill a seller↔product mapping was first created from — shown on the product's External References page for traceability. The RS additions (Send button, `is_rs_product`, **External References page**) are now also on the **product.product variant form** (what opens from a waybill line) — previously only the template form had them; the Send button delegates via a `product.product` wrapper.
- **Buyer-direction return waybills (type 5) → outgoing delivery.** When a vendor issues a **return** waybill to us (we send their goods back), the sync now mirrors it as an **outgoing delivery only** (our stock → vendor's supplier-usage location) — no PO, no SO (`_rs_create_return_delivery_from_waybill`, dispatched via the new `_rs_create_buyer_documents_if_missing`). Linked before reserving (+`skip_rs_auto_create`) so no second waybill spawns; the delivery validates on the buyer's **Receive** via the existing cascade; a vendor **cancel** cancels the not-yet-shipped delivery (PO-less branch added to `_cascade_cancel_purchase`). Unmapped lines skip silently until mapped (same rule as the PO path).

- **`buyer_id` false-positive in the sync change-detector.** The diff loop compared `existing[k]` (a recordset for Many2one fields) with the mapped integer id — always unequal — so `buyer_id` was logged as "changed" and re-written on every sync for every waybill (~2600 log lines per run). Many2one values are now compared by id (same pattern as the drift cron); sync logs now show only real changes and the "updated" counter is meaningful again.
- **Vendor return / safety-net move creation crashed on Odoo 19.** Both used `'name'` on `stock.move` — removed in Odoo 19 (only `description_picking` exists). The `Invalid field 'name'` error aborted the reconcile loop, so decreases changed the PO line but never created the vendor return (and `qty_received` stayed high). Both now use `description_picking`. (Live-test S3-2/S3-4 finding.)
- **Receive button silently did nothing after a seller edit.** The Confirm gate only allowed `is_confirmed == '0'`; after a seller edit RS reports `-1` (refused/reset), so the click was skipped without feedback. The gate now blocks only an already-confirmed waybill (`== '1'` with no re-confirm pending). (Live-test S3-6 finding.)
- **Seller edits are now always surfaced to the buyer — goods or not.** All three pull paths (Update button, sync cron, drift cron) detect the `is_confirmed` transition away from `'1'` (RS resets the buyer decision on ANY seller edit, including driver/address-only) → set `is_buyer_reconfirm_needed` + post a chatter note "Seller edited this waybill…". Previously only goods changes raised a banner. (Live-test S3-6 finding.)

#### Changed (same-day redesign after live testing)

- **Receive reconcile is now target-state, not stored-delta.** `action_confirm_waybill` computes the delta **live** (`_compute_buyer_goods_delta`: waybill lines vs PO lines) instead of replaying `pending_goods_json`. Receive is therefore self-healing: a change the buyer previously **Rejected**, or a partially-failed earlier reconcile, is applied on the next Receive; re-clicking resumes from the remaining diff; unmapped lines are reported to chatter. `pending_goods_json` is now informational only (drives the banner) — and **Reject keeps it**, so the waybill-vs-PO mismatch stays visible until a later Receive heals it (previously the delta was discarded and the mismatch was permanent and invisible). (Live-test S3-5 finding.)
- **Purchase Order page on the waybill form.** Buyer-direction waybills now show a "Purchase Order" notebook page (mirror of the Sales Order page): PO, status, confirmation date, representative, payment terms, amounts, billing status + "Open Purchase Order" button. New related fields + `action_open_purchase_order`.

### 19.0.1.8.0 — 2026-06-04

#### Added

- **Scenario 3 — buyer-direction edit reconcile (deferred to Receive).** When the vendor edits their waybill on RS while we are the buyer, all goods changes now defer to the buyer's explicit Receive click instead of mutating Odoo immediately. A new `pending_goods_json` field on `rs.waybill` accumulates the signed per-product delta (+ = vendor added/increased, − = vendor reduced/removed); the "Vendor changed goods on this waybill" banner surfaces it on the form. On the buyer's next Receive, `_reconcile_buyer_goods` drains the delta:
  - **Ready receipt** → updates the PO line and the existing receipt's move in place; re-reserves. New product added becomes a new PO line + new receipt move.
  - **Done receipt, qty up / line added** → bumps the PO line (or adds one), creates a supplementary receipt picking on the same PO linked to the PO line (so `qty_received` tracks), validates it. No waybill on the supplementary picking.
  - **Done receipt, qty down / line removed** → reduces the PO line and creates an outgoing return picking to the vendor's `property_stock_supplier`, validates it. No waybill (buyer does not issue waybills).
  Reject discards the pending delta — non-terminal, PO/receipt stay open. The dispatcher branches at the top of `_apply_rs_goods_diff_auto`; all existing seller-direction behaviour is unchanged.
- Helper methods: `_signed_delta_from_diffs`, `_accumulate_pending_goods_delta`, `_reconcile_buyer_goods`, `_reconcile_buyer_increase_done`, `_reconcile_buyer_decrease_done`.

### 19.0.1.7.0 — 2026-06-02

#### Added

- **Buyer-direction → Purchase Order + receipt (reverse creation, buyer side).** A buyer-direction waybill (type **2/3/4**) synced from RS now auto-creates a **Purchase Order + incoming receipt** (`_rs_create_purchase_from_waybill`), mirroring the seller-side SO+delivery flow:
  - the vendor is resolved from `seller_tin` (`company_registry`/`vat` match) or **auto-created** with `supplier_rank=1` (`_get_or_create_vendor_partner`);
  - the PO is created and confirmed under `skip_rs_auto_create` so the receipt does not spawn a second waybill;
  - waybill ↔ PO ↔ receipt are linked both ways (`purchase_id`, `picking_id`).
  Skips silently when already linked, type not 2/3/4, any line has no mapped product (map first), or no `seller_tin`.
- **Buyer receipt auto-validation.** The incoming receipt is validated (Ready → Done, goods into stock) when RS reports `is_confirmed='1'` — i.e. our side confirmed receipt — via `_cascade_validate_receipt`. Triggered from four places: the **Confirm** button (`action_confirm_waybill`), the **Update** button (`action_update_rs_status`), the **sync cron**, and the **drift cron**. The seller's RS-side close does **not** validate our receipt — only our own receive does (`_cascade_validate_picking` returns early for buyer direction).
- **Doc-backfill for already-synced waybills.** `_process_rs_rows` now runs the document backfill **and** the completion/receipt cascades for **every in-scope existing waybill**, regardless of whether any field changed this sync. A waybill that synced before the integration cutoff was set (or before its products were mapped) therefore gets its SO/PO/transfer on the **next** sync or **Fetch All** click, even though it shows as "unchanged". Idempotent — re-running never duplicates.
- **Waybill smart button on the Purchase Order form.** `purchase.order` now shows a **Waybill** smart button (`action_view_waybills`), mirroring the Sales Order one. The model side (`waybill_id`, `waybill_count`, `action_view_waybills`) already existed; only the view was missing.

#### Fixed

- **Odoo 19 Purchase Order line UoM field.** `_rs_create_purchase_from_waybill` built the PO line with `'product_uom': line.product_id.uom_po_id.id`. In Odoo 19 the separate purchase UoM (`uom_po_id`) was **removed** (products have a single `uom_id`) and the order-line field was renamed to **`product_uom_id`**. The old code raised `AttributeError: 'product.product' object has no attribute 'uom_po_id'`, caught as a "Backfill Odoo docs failed" warning, so buyer waybills got no PO. Now uses `'product_uom_id': line.product_id.uom_id.id`. (Closes the prior `uom_po_id` qty-conversion note — Odoo 19 has no separate purchase UoM to convert.)

### 19.0.1.6.0 — 2026-05-31

#### Added

- **Reverse creation — waybill → transfer → SO.** A seller waybill with **no** linked transfer (created manually in Odoo or synced from RS) now builds the Odoo documents in **Ready** state when the operator clicks **Save / Activate / Send-to-Transporter / Complete** (`_rs_create_documents_if_missing`):
  - type **2/3/4** → Sales Order → delivery (buyer = customer);
  - type **1** (internal) → internal transfer (source WH → dest WH), no SO;
  - type **5** (return) → incoming transfer (customer → our WH), no SO.
  The transfer is linked before reserving (+ `skip_rs_auto_create`) so the forward hook never spawns a second waybill, and the **Complete** button validates it via the close cascade. No-op for forward-created waybills (a picking already exists).
- **Return Decision wizard.** Reducing/removing a line on a **completed** waybill, and **cancelling** a completed waybill, now open `rs.waybill.return.decision.wizard` asking *"did the goods physically come back?"* — **Goods returned** → return picking + type-5 return waybill; **Short-ship / adjust only** → return picking, no waybill. On cancel the waybill is refused on RS **regardless** of the choice. Replaces the always-auto-return behaviour, which mis-documented short-ships as physical returns.
- **Buyer ↔ customer sync (both stages).** While a waybill is a local draft (no `rs_internal_id`), changing the delivery's partner mirrors to the waybill **buyer** (`_rs_mirror_buyer_to_waybill`, alongside the line mirror). Editing the **buyer** in Edit Waybill propagates down to the **SO customer** and **delivery partner** (`_sync_buyer_to_so_and_picking`).
- **RS-driven goods auto-sync.** Goods changes coming back from RS (via the **Update** button, **sync cron**, and **drift cron**) are now pushed **down to the SO + transfer**, not just the waybill record (`_apply_rs_goods_diff_auto`): qty up / added → applied; not-yet-delivered down/removed → applied in place; **already-delivered** down/removed → **not** auto-applied (the return-vs-adjust decision a cron can't make) but stored in `pending_return_json` and surfaced by a **"Reconcile Delivery"** banner + button on the waybill (shown only when pending). The button opens the Return Decision wizard, which creates the return (± type-5 waybill) and clears the flag.

#### Changed

- **Lock guard on linked SO/transfer.** Once a waybill is on RS (`rs_internal_id` set), the linked **sales order** (customer + order lines) and **delivery** (partner + product/Demand/Done) become **read-only** with a banner directing the operator to **Edit Waybill** — preventing silent drift from direct edits. Computed `rs_waybill_locked` on `sale.order` and `stock.picking`; view-level only (Validate, lots, packaging stay usable). Before Save (no `rs_internal_id`) everything stays editable for the draft mirror.

### 19.0.1.5.0 — 2026-05-30

#### Added

- **Edit a waybill → sync the transfer AND the sales order.** Editing a draft/active/completed waybill now mirrors the change end-to-end so quantities match across waybill, delivery, and SO.
  - **Active waybill (delivery not validated):** qty up/down updates the move demand **and** the SO ordered line; adding a product creates a move on the same delivery **and** a matching SO line (`skip_procurement` so Odoo doesn't create a duplicate); removing a line cancels the move and **zeroes** the SO line (Odoo forbids deleting a confirmed line).
  - **Completed waybill (delivery validated):** qty up bumps the done move in place (demand + done qty) and the SO line (`_apply_line_diffs_increase_on_done`); adding a product creates a **supplementary delivery + SO line** with **no second waybill**; qty down / remove use the existing return-picking + type-5 flow. The old "block any increase, make a new SO" rule is replaced — one physical movement is corrected on its own document (per tax guidance).
- **Line-removal tombstones on RS.** Removing a line in an edit now sends the good back to RS with `STATUS=-1` (`save_waybill(removed_good_ids=...)` → `_build_waybill_xml`), so RS actually deletes it instead of keeping an orphan. The edit snapshot now captures `rs_good_id` for this.
- **Carrier completion-sync.** When a waybill flips to **completed** on RS out-of-band (e.g. a carrier activated + completed it, status 8 → 1 → 2), the linked delivery is now auto-validated via `_cascade_validate_picking`, triggered from the **Update** button (`action_update_rs_status`), the **update-sync cron** (`_process_rs_rows`), and the **drift-repair cron**. Cancellation stays seller-only (transporters can only activate/complete, never cancel).

### 19.0.1.4.0 — 2026-05-29

#### Added

- **Reverse cascade: close waybill → validate picking.** New `_cascade_validate_picking` helper on `rs.waybill`, called at the end of both branches of `action_close_waybill` (type-3 and the standard "Complete"). When the operator clicks **Complete** on the waybill form, the linked delivery picking is now automatically validated (Ready → Done) so the Odoo and RS sides stay in sync regardless of which side the operator acts on. Symmetric with the existing forward cascade (picking validate → close waybill).
  - Uses the Odoo 19 validate pattern: sets `move.picked = True` on moves with `quantity > 0`, then calls `picking.with_context(skip_backorder=True).button_validate()`. Backorders for partial reservations are still auto-created, and their own waybills auto-spawn via the existing `_create_backorder` override.
  - Safety net via try/except + chatter `message_post` on the waybill. When the picking can't be auto-validated (not Ready, missing lot/serial, etc.) the RS close stays committed and a chatter note explains why, so the operator can validate manually. Never raises; never blocks the RS close.
  - Wizard-action return from `button_validate` (Immediate Transfer / Backorder Confirmation) is detected and surfaced as a chatter note instead of swallowing silently.
  - No recursion: the cascade runs AFTER the local `state='completed'` write, so the picking's own `_action_done` post-check hits the `elif waybill.state == 'completed'` branch and just message_posts — no double-close on RS.

#### Changed

- **`purchase` added to manifest `depends`.** The return-waybill creation path (`_rs_create_return_waybill`) accesses `picking.purchase_id` to skip PO-driven receipts. That field is added to `stock.picking` by the `purchase_stock` module. Without the dependency, the cancel-completed reverse flow could fail with `AttributeError: 'stock.picking' object has no attribute 'purchase_id'` when validating the new return picking.

### 19.0.1.3.0 — 2026-05-29

#### Fixed

- **Forward-create TIN consistency.** Auto-created delivery waybills (and the picking-type external resync) now build `buyer_tin` as `company_registry or vat`, matching the buyer onchange, the seller default, and the return/internal paths. Previously the outgoing-delivery and external-resync paths used the reverse priority, so the same partner could get a different TIN depending on which path created the waybill.
- **Partial-reservation quantity freeze.** A waybill auto-created while the picking is only `partially_available` is no longer frozen at the partial quantity. New `_rs_sync_waybill_lines` re-mirrors the waybill's goods from the picking's moves (qty updates, new moves added, vanished moves dropped) **while the waybill is still a local draft not yet on RS**. Once it has an `rs_internal_id` or leaves `draft`, the waybill is authoritative and changes go through the Edit flow. Manually-added lines (no `stock_move_id`) are left untouched. The per-move line builder was extracted into `_rs_line_vals_from_move` so the builder and the sync share one definition.
- **Multi-warehouse start address.** Outgoing delivery waybills now set `start_address` (and `source_warehouse_id`) from the picking's source-location warehouse via `_rs_warehouse_address`, instead of always falling back to the company street. Fixes a wrong departure address when shipping from a non-HQ warehouse.
- **Cancelled-waybill validation guard.** `_action_done` checked `waybill.state == 'canceled'` (one `l`) — a value that never exists — so validating a delivery whose waybill was cancelled on RS was not blocked. Corrected to `'cancelled'`.
- **Split Transfer no longer crashes.** `stock.picking._create_backorder` was overridden as `def _create_backorder(self)`, but Odoo 19's core signature is `_create_backorder(self, backorder_moves=None)` and the Split Transfer button calls it as `_create_backorder(backorder_moves=...)`. Because the override applies to every picking, clicking **Split** raised `TypeError` globally. The override now accepts and forwards `backorder_moves`; the backorder waybill auto-create is unchanged.
- **Type-3 close notification.** `action_close_waybill`'s type-3 (Without Transport) branch called `self.send_notification_email()` — no such method (it's `_send_notification_email`). Inside a try/except so it never crashed, but the close email silently never sent. Corrected.

#### Changed

- **Activate can self-save.** `action_send_rs_waybill` now calls `action_save_to_rs()` first when the waybill has no `rs_internal_id`, so one click does Save → Activate. The **Activate** button's `invisible` condition dropped its `not rs_internal_id` clause, so it is now reachable on an unsaved draft (Save remains a separate button too). Validating, type-3, carrier (`transport_type == '7'`), buyer-direction, template, and already-active/completed/cancelled states are still correctly excluded.

### 19.0.1.2.0 — 2026-05-27

#### Added

- **Internal transfer waybills (type 1).** Internal transfer pickings (`picking_type.code == 'internal'`) now auto-create a type-1 (Internal Transport) waybill. Source/destination warehouses are derived from the picking's `location_id.warehouse_id` / `location_dest_id.warehouse_id`, addresses from each warehouse partner (`street + city`, with company fallback). Skips when both legs are in the same warehouse, when either side has no warehouse (transit), or when the picking is sale-driven.
- **Return waybills (type 5).** Customer-return receipts (`picking_type.code == 'incoming'`) auto-create a type-5 (Return) waybill. Addresses are flipped vs a delivery (start = customer, end = your warehouse). PO-driven receipts (vendor purchases, `purchase_id` set) are skipped — the vendor issues that waybill, not us.
- **Picking-type-change resync.** Changing `picking_type_id` on a picking that already has a draft waybill re-derives the waybill in place (same record, same `rs_internal_id`) via `_rs_resync_waybill_from_picking_type`. If the waybill is already on RS in draft, the change is pushed via `save_waybill`. Active/completed/cancelled/transporter-bound waybills are left untouched. Internal moves clear the SO link; switching back to delivery restores it.
- **`rs_progress` ribbon on the picking form.** A computed, read-only statusbar (Draft → Waiting → Reserved → Pending → Delivered, + Cancelled) shown below the source fields, parallel to Odoo's native status. Derived from `picking.state` + `waybill_id.state`; never writes to the native state.
- **Picking-derived waybill fields.** `picking_state`, `picking_scheduled_date`, `picking_date_done` (related from `picking_id`) — used on the new Delivery/Transfer page so it works for internal transfers too, not just SO-driven deliveries.

#### Changed

- **Waybill form pages split.** The single "Sales Order" page is now two: **Sales Order** (order + financial, visible only when an SO is linked) and **Delivery/Transfer** (picking info, visible whenever a picking is linked; SO-tied fields inside are guarded).
- **Save button visibility.** Now driven by `state` (visible while draft/unsaved, hidden once active/completed/cancelled or sent-to-transporter) instead of by `rs_internal_id`, matching RS's own "Save stays available in draft" behaviour.

#### Guarded

- Converting a sale-driven picking to an internal type that opts in to RS waybills raises a clear error: internal transport waybills must not be linked to a Sales Order — cancel the SO and create the transfer manually.

### 19.0.1.1.0 — 2026-05-25

#### Added

- **Edit popup flow.** Clicking *Edit Waybill* now opens the same waybill as a modal popup with a stripped-down header showing only **Activate Adjustment**, **Cancel Adjustment** and **Print PDF**. All other lifecycle buttons are hidden via `context.get('edit_mode')`. After Activate, the popup auto-closes and a success toast is shown.
- **`action_submit_edit_to_rs`.** New method that performs the actual SOAP `save_waybill` call for an existing `rs_internal_id`. The previous `action_edit_waybill` (which did the SOAP directly) was split into two: `action_edit_waybill` now only opens the popup, `action_submit_edit_to_rs` does the SOAP and returns a chained `display_notification` + `act_window_close`.
- **Adjustment history UI.** New `rs.waybill.adjustment.*` transient models and an *Adjustments* smart button on the waybill form. Lists archived versions on demand (`get_adjusted_waybills`) and opens a read-only mirror of any archival snapshot (`get_adjusted_waybill`).
- **`get_adjusted_waybills` / `get_adjusted_waybill`** SOAP wrappers in `rs.waybill.soap.service`, with ISO datetime normalisation (`T` → space, microseconds stripped) so RS-returned timestamps land cleanly in `fields.Datetime`.

#### Fixed

- **G18 — Edit no longer duplicates products.** `save_waybill` now also parses the `<GOODS_LIST>` from the RS response and returns the goods IDs. Callers (`action_save_to_rs`, `action_submit_edit_to_rs`, `action_send_carrier_waybill`) invoke the new `_sync_rs_good_ids` helper, which writes each returned RS ID back to `rs.waybill.line.rs_good_id`. Without this, every subsequent edit sent `<ID>0</ID>` for every line and RS would treat them all as new lines, duplicating the products. Verified against live RS test account.

---

### 19.0.1.0.0 — 2026-05-24

#### Added

- **Forward auto-create flow.** Waybills are now created automatically when a delivery picking reserves stock, via `stock.move._action_assign` override. Replaces the previous behavior where waybills were created on `sale.order.action_confirm` with demand quantities.
- **Picking-driven quantities.** Waybill lines are built from `stock.move.quantity` (actually reserved), not `sale.order.line.product_uom_qty` (demand). Partial availability creates a waybill with only the available items; backorder pickings auto-create their own waybills when they reserve.
- **`rs.waybill.operation` model.** New audit/queue table created (security in place). Population logic to be added in Phase 2.
- **Opt-in flag on picking type.** `stock.picking.type.rs_create_waybill` (default off) controls whether each picking type generates waybills. `stock.picking.type.rs_waybill_type` defines the RS waybill type to use.
- **Waybill smart button on delivery.** `stock.picking` form now shows a Waybill smart button with count badge (mirrors the existing SO smart button), opens linked waybill in form view.
- **Picking field on waybill form.** `picking_id` displayed inside Sales Order page → Delivery section, navigable.
- **`stock_move_id` on waybill line.** Each waybill line remembers its source `stock.move` for future sync / return / correction flows.
- **README.md.** This file.

#### Changed

- `sale_order.py`: removed `action_confirm` override and `_create_rs_waybill` method. Waybill is now created from the picking, not the SO. Kept `waybill_id` One2many and `action_view_waybills` for the SO smart button.

#### Removed

- `sale_order.SaleOrder.action_confirm` override
- `sale_order.SaleOrder._create_rs_waybill` method (logic moved to `stock.picking._rs_try_create_waybill` and `_rs_build_waybill_lines`)

---

## License

LGPL-3
