# RS Petroleum Invoice (`rs_spec_invoice`) — Developer guide

For a developer who has to change the module. Business flow and screens: [README.md](README.md). rs.ge API of the
petroleum service: `spec_invoice_api_docs.md` at the repository root of odoo20 (not in this module).

## 1. Purpose and facts

The ნსაფ (rs.ge SpecInvoices service) is filed from the customer invoice. It reuses rs_einvoice's rs.ge fields on
`account.move` (`rs_einv_id`, `rs_einv_status`, `rs_einv_series`, `rs_einv_number`, `rs_einv_sent_at`,
`account.move.line.rs_line_id`), so rs_einvoice's locks, write guards, crons and status reactions apply to it. The
Boolean `rs_einv_is_spec` (defined in rs_einvoice) says which rs.ge service those fields belong to.

| Item | Value |
|---|---|
| depends | `rs_base_methods` (brings rs_einvoice, rs_waybill and the per-user rs.ge logins), `fleet` (vehicles), `purchase`, `sale`, `stock` (second unit), `gec_vat_declaration` (tabs 13 and 14) |
| External | `zeep` |
| New models | `rs.spec.site` (rs.ge site register), `rs.spec.soap.service` (abstract SOAP client) |
| Extended | `account.move`, `product.template`, `stock.picking`, `account.move.reversal`, `validate.account.move`, `rs.einvoice.inbox.wizard`, `rs.einvoice.inbox.line`, `rs.einvoice.correction.line`, `gec.vat.declaration`, `purchase.order.line`, `sale.order.line`, `stock.move`, `stock.move.line` |
| Crons, controllers, hooks | none |

Data files, in manifest order: `views/rs_spec_site_views.xml`, `views/account_move_views.xml`,
`views/account_move_reversal_views.xml`, `views/product_template_views.xml`, `views/second_unit_views.xml`,
`views/rs_buyer_inbox_wizard_views.xml`, `views/rs_spec_menus.xml`, `security/ir.access.csv`.

## 2. Architecture

```text
 product.template.rs_spec_rs_id  (rs.ge petroleum product id; set by the sync)
        │
 account.move (out_invoice, rs_einv_is_spec) ──rs_spec_*──► rs.spec.site (global)
        │  rs_einv_id / status / series / number   (rs_einvoice fields)
        ▼
 rs.spec.soap.service ──► rs.soap.service helpers ──► SpecInvoicesService
        (chek_in, writes)    (_get_client, _call_datatable,   (webserv.rs.ge)
                              _auth_kwargs, un_id lookup)
```

The petroleum client is a thin layer: credentials, the zeep client cache, the DataTable reader and the taxpayer-id
lookup are rs_einvoice's `rs.soap.service`, called with the petroleum WSDL (`SPEC_WSDL_URL`).

## 3. File map

| File | Holds |
|---|---|
| `__manifest__.py` | depends, data order |
| `__init__.py` | imports `models`, `wizard` |
| `models/__init__.py` | imports the model files |
| `models/account_move.py` | constants (`INVOICE_TYPES`, `TRANSPORT_TYPES`, `UNITS`, `PURCHASE_DOC_ALT_TYPES`, `SPEC_DRG_TYPES`, `SPEC_K_TYPES`, `SPEC_COPY_FIELDS`), the `rs_spec_*` fields, the correction hooks, marking at post, Save / Send / Delete / Load sites, the refresh and lock overrides, the buyer-side hooks (`_rs_get_service`, snapshot, product, pulled-line and header, section 5b) |
| `models/rs_spec_soap_service.py` | `rs.spec.soap.service`: `_login`, `_rs_table`, `_rs_write`, the buyer contract (section 5b) |
| `models/rs_spec_site.py` | `rs.spec.site` with `_rs_sync` |
| `models/rs_soap_service.py` | `get_buyer_invoices` sends the inbox search to `rs.spec.soap.service` when the context key `rs_spec_inbox` is set |
| `models/product_template.py` | `rs_spec_rs_id`, its partial unique index, `rs_spec_ssf_code` (4-digit rs.ge product code, read by tabs 13 / 14), `RS_SPEC_KG_SSN_CODES` (the three SSN codes sold by weight), `action_rs_spec_sync` |
| `models/second_unit.py` | `rs_spec_alt_qty`, `rs_spec_alt_uom_id` on `purchase.order.line`, `sale.order.line`, `stock.move`, `stock.move.line` (section 5c) |
| `models/rs_einvoice_correction_line.py` | `rs_good_id`, `rs_g_number_alt` on rs_einvoice's pulled-line snapshot |
| `models/gec_vat_declaration.py` | `action_generate` (super first, then the tab 13 / 14 rows from the ბ I / ბ II scans with `spec=True`), `_gec_spec_row`: the ნსაფ columns |
| `models/stock_picking.py` | no rs.ge waybill for a transfer of petroleum products only |
| `wizard/__init__.py` | imports the wizard files |
| `wizard/account_move_reversal.py` | sends a filed ნსაფ to the correction flow; refuses its other rs.ge credit-note flows |
| `wizard/validate_account_move.py` | marking on the Confirm Entries wizard |
| `wizard/rs_buyer_inbox_wizard.py` | `rs_spec` on the rs.ge Inbox, `action_search` sets the context `rs_spec_inbox`, `_do_import` with the petroleum default |
| `views/account_move_views.xml` | the Petroleum Invoice block on rs_einvoice's tab, waybill tab hidden for ნსაფ, "RS correction reason" hidden for ნსაფ, the Petroleum Invoices action |
| `views/account_move_reversal_views.xml` | the Petroleum Correction Type on rs_einvoice's credit-note wizard |
| `views/rs_spec_site_views.xml` | site list, search and action |
| `views/product_template_views.xml` | `rs_spec_rs_id` and `rs_spec_ssf_code` on the product form, search filter, the sync server action |
| `views/second_unit_views.xml` | the two second-unit columns (`optional="hide"`) on six lists |
| `views/rs_buyer_inbox_wizard_views.xml` | `rs_spec` on the inbox form, action `action_rs_spec_buyer_inbox` |
| `views/rs_spec_menus.xml` | four menus |
| `security/ir.access.csv` | access rows (section 9) |

## 4. Marking an invoice as ნსაფ

Entry points: `action_post` (Confirm), `action_validate_moves_with_confirmation` (list Confirm Entries) and
`validate.account.move.validate_move` (its wizard). Each calls `_rs_spec_mark_before_post`, then `super()`.

1. `_rs_spec_mark_before_post` takes draft `out_invoice` moves and skips those with `rs_einv_skip`, or that are not
   ნსაფ and have `rs_einv_replaces_id` or an `rs_einv_id` (an ordinary replacement, or an invoice filed as ordinary
   e-invoice, stays one). A ნსაფ correction copy (`rs_einv_is_spec` set by the copy) is checked like any fuel invoice.
2. Fuel lines = product lines (`_rs_product_lines`, without `is_downpayment`) whose product has
   `rs_spec_rs_id`. It refuses: fuel mixed with other lines; more than one fuel line; a filed ნსაფ or a correction
   copy with no fuel line left.
3. Writes `rs_einv_is_spec` True on new fuel invoices and False on unfiled invoices that no longer have fuel, one
   `write` per group.

`_post` is not overridden on purpose: POS, credit notes from `_reverse_moves(cancel=True)` and rs_einvoice's
cancellation reversal post through `_post` and must not be refused or marked.

Quantities: `_compute_rs_spec_quantities` (stored, editable) converts the single fuel line to litres
(`uom.product_uom_litre`) and kg (`uom.product_uom_kgm`) when the line's unit shares their reference, and sets
`rs_spec_unit` to kg only when litres do not convert.

## 4b. Petroleum products

`product.template.action_rs_spec_sync` (menu Sync Petroleum Products, server action `action_rs_spec_sync_products`):
reads `get_spec_products_n` for the company's taxpayer id, matches products by `rs_spec_rs_id` (archived included),
creates the missing ones in one `create` (name = GOODS_NAME, `barcode` = SSN customs code, `rs_spec_ssf_code` = the
4-digit code, no company), writes only the values rs.ge changed, unarchives returned ones, archives those rs.ge no
longer returns, then loads the seller's and the customs sites. The unit is kg when the SSN code is in
`RS_SPEC_KG_SSN_CODES`, else Litre (rs.ge gives no unit). An existing product whose unit would change keeps it, with a
chatter note, when documents already use it (`_trigger_uom_warning()` or a posted invoice line). Fuel everywhere in the module means
`product_id.rs_spec_rs_id` set; `_rs_spec_push` sends it as `p_good_id`. Excise Product (`is_excise`, rs_waybill) is not
set: it requires an Excise Code that rs.ge's petroleum list does not give. `_rs_spec_rs_id_unique` is a partial unique
index (`WHERE rs_spec_rs_id > 0`): an Integer stores 0 for an empty value, which a plain UNIQUE would reject twice.

## 5. Save, send, delete

`action_rs_spec_save` → `_rs_spec_push`:

1. Row lock (`_rs_acquire_row_lock`).
2. Local values first, so a local error never leaves a half document on rs.ge: the fuel line, `_rs_line_to_payload`
   (GEL total and VAT) and `_rs_line_vat_class` → `SPEC_DRG_TYPES` (1 taxable, 0 zero rated, -1 not taxed).
3. Line id: `line.rs_line_id`, or, when the invoice already has an `rs_einv_id` but the line id was lost, the first
   row of `get_invoice_desc_n` (one ნსაფ holds one line; id 0 would create a second line on rs.ge).
4. `_login` (`chek_in`, `sui` cached in `env.cr.cache` per user and company) gives `p_S_USER_ID`.
5. Seller un_id `_rs_company_un_id` and buyer un_id `_rs_partner_un_id` (rs_einvoice's service, cached on the
   partner) are read first, so a missing id or unknown TIN fails before any marker. First save only:
   `_rs_mark_pending('create')` commits a marker, so a lost answer leaves a trace. Then `save_invoice_b_n` with
   all 38 parameters by name. Empty end site is sent as `-`. A false
   result clears the marker and commits before the error: rs.ge answered, so there is nothing to recover.
6. First save only: write `rs_einv_id`, status '0', `_rs_clear_pending`, log row, `cr.commit()` (rs.ge now holds
   the document; a retry must edit it), `_rs_relock_after_commit`.
7. `save_invoice_desc_n`; store `line.rs_line_id`; `_rs_stamp_sync_hash` so the line sync badges read synced.

While the marker is set and the invoice has no `rs_einv_id`, `_rs_spec_push` refuses (Save and Send) and the view
hides both buttons; the tab shows rs_einvoice's **Resolve Orphan** (links the rs.ge id after checking seller and
buyer, read through `_rs_get_service`, so from the petroleum service) and **Dismiss Pending** (after 5 minutes).

For a correction (`rs_einv_replacement_mode == 'correction'`) `_rs_spec_push` differs:

1. No `rs_einv_id` yet: `_rs_spec_create_correction` runs `_rs_assert_correction_can_be_sent` (rs_einvoice guards,
   returns the original), `_rs_mark_pending('correction')`, calls `k_invoice_n(inv_id=original, k_type=rs_spec_k_type)`,
   writes the new `rs_einv_id` with status '4', clears the marker, logs, `cr.commit()` and relocks. A refusal by
   rs.ge clears the marker and commits before the error.
2. Type 11: only `_rs_stamp_sync_hash`; rs.ge zeroes quantity and amount itself, and the copy's quantity was set to 0
   by `_rs_do_correct_reissue`.
3. Otherwise the line id lookup (`get_invoice_desc_n`) finds the line `k_invoice_n` copied onto the correction, then
   `save_invoice_desc_n` and the stamp. `save_invoice_b_n` is never called: it has no partial update and would
   overwrite the operation date and graph 12.

`action_rs_spec_send`: lock, `_rs_spec_push`, `change_invoice_status_n` with 1 (or 5 from status 4), write the status
and `rs_einv_sent_at`, `cr.commit()` (rs.ge accepted the send), relock, `action_rs_refresh_status`. Same shape as
rs_einvoice `action_rs_send`.

`action_rs_spec_delete`: `change_invoice_status_n(-1)`, log, clear the line id and the rs.ge fields with context
`rs_allow_id_overwrite` (rs_einvoice's write guard otherwise refuses clearing `rs_einv_id`). The original it corrects
changes status on its own next Check Status; the next correction attempt refreshes it first
(`_rs_assert_correction_can_be_sent`).

`action_rs_spec_load_sites`: `rs.spec.site._rs_sync` for the seller and the buyer un_id.

## 5b. Supplier ნსაფ (buyer side)

Menu **Accounting > Vendors > Received Petroleum Invoices** ([rs_spec_menus.xml:5](views/rs_spec_menus.xml#L5)) opens the
ordinary rs.ge Inbox with `rs_spec` set (`action_rs_spec_buyer_inbox`, context `default_rs_spec`). Search reads
`get_buyer_invoices_n`. Import creates the draft bill with `rs_einv_is_spec` (`_do_import` adds it as a context
default) and runs the ordinary Pull.

`_rs_get_service` ([account_move.py:245](models/account_move.py#L245)) returns `rs.spec.soap.service` for every spec move,
seller or buyer; the inbox search sets the context `rs_spec_inbox` in `action_search`, read by this module's
`rs.soap.service.get_buyer_invoices` override. The client exposes the names the
buyer path calls:

| Method | rs.ge operation / source |
|---|---|
| `_check_auth` | `chek_in` (`_login`) |
| `_rs_company_un_id`, `_rs_partner_un_id`, `get_un_id_from_tin` | the ordinary service (one un_id space) |
| `get_invoice` | `get_invoice_n` as a namespace, int columns converted, empty columns None |
| `get_invoice_desc` | `get_invoice_desc_n`, with `full_amount` = `unit_price` and `drg_amount` = `dgg_price` |
| `get_buyer_invoices` | `get_buyer_invoices_n`, with the alias keys the inbox reads (`sa_ident_no`, `org_name`, `tanxa`, `reg_dt`) |
| `buyer_accept_invoice` | `acsept_invoice_status_n` |
| `buyer_reject_invoice` | `ref_invoice_status_n` |
| `get_invoice_waybills` | none: returns an empty list |

- Product: the pulled line's `good_id` = `rs_spec_rs_id` (`_rs_find_product_for_pulled`,
  [account_move.py:258](models/account_move.py#L258)); the snapshot keeps `good_id` and `goods_number_alt` in `rs_good_id`
  and `rs_g_number_alt` (`_rs_line_snapshot_vals` :253).
- A product whose unit is kg (and not litre) takes `goods_number_alt` as the quantity and the litre price scaled to it
  (`_rs_pulled_line_vals`, [:265](models/account_move.py#L265)).
- Sites: `_rs_pull_apply_header` ([:277](models/account_move.py#L277)) searches or creates `rs.spec.site` from `oil_st_n` and
  `oil_fn_n`; `-` or empty gives no site.
- rs_einvoice changes for this: `k_type` normalised to 0 or more in the inbox (petroleum
  originals carry -1, [rs_buyer_inbox_wizard.py:142](../rs_einvoice/wizard/rs_buyer_inbox_wizard.py#L142)), and the buyer
  cancel-and-reissue copy carrying `rs_einv_is_spec` ([account_move_buyer.py:552](../rs_einvoice/models/account_move_buyer.py#L552)).
- Verified live on the rs.ge test environment 2026-11-07: Accept 1 → 2 posts the bill; Reject gives rs.ge status 0 with
  `was_ref 1` and cancels the bill.

## 5c. Second quantity and unit

`rs_spec_alt_qty` (Float, digits `Product Unit`) and `rs_spec_alt_uom_id` (Many2one `uom.uom`) on `purchase.order.line`,
`sale.order.line`, `stock.move` and `stock.move.line` ([second_unit.py](models/second_unit.py)); `copy=False` on the two
stock models, so a backorder split does not copy them. Typed per document: no compute, default or conversion, and
nothing carries them from the order line to the move (core builds those values from explicit dicts). Six list columns,
all `optional="hide"` ([second_unit_views.xml](views/second_unit_views.xml)); the Moves Analysis list sums the quantity.

## 6. Status refresh and locks

`action_rs_refresh_status` is the single point rs_einvoice reaches for every status read: the Check Status button,
the refresh crons, `_rs_raise_if_locked` (Reset / Cancel), `_rs_refresh_parent`, the credit-note wizard. For a ნსაფ
the override reads the header through `self._rs_get_service().get_invoice()` (the petroleum client,
`rs_spec_soap_service.py`), writes series, number and transport start, and calls rs_einvoice's
`_rs_refresh_apply_status` (status write, log, 6 / 7 / 8 reactions; 7 cancels the invoice in Odoo). For a vendor bill it
also runs `_rs_refresh_rejection` after the status write and `_rs_refresh_pulled_lines` at the end. It does **not**
call `super()`: that would query the ordinary service with a ნსაფ id and run rs_base_methods' waybill sync.

After the status write the override also (a) resets a correction to draft when the status went from 5 back to 4
(buyer rejected; `no_text` is logged), through rs_einvoice's `_rs_reset_correction_to_draft_after_rejection`, and
(b) refreshes the correction that replaces this invoice (`rs_einv_replaced_by_id`), so Check Status on the
original also picks up the correction's status 8 while the refresh crons are off. A `UserError` from the child
(for example it was deleted on rs.ge) is caught in a savepoint and logged as a warning, so it never blocks the
original. The child never refreshes its parent, so there is no loop.

`_rs_raise_if_locked` forces `allow_pending=False` for a seller-side ნსაფ: rs.ge lets a sent ნსაფ change only at status
0 and 4, so Reset at status 1 is refused (ordinary e-invoices allow it). A vendor bill keeps the ordinary rule.

## 7. Credit notes and corrections

`account.move.reversal.refund_moves` refuses a filed ნსაფ unless the treatment is `skip` ("Only correct Odoo, not
rs.ge"). `modify_moves` sends a single filed ნსაფ with treatment `correct_reissue` to `_rs_do_correct_reissue`
(`rs_spec_is_filed` is the computed flag the view uses) and refuses every other flow: the `replace` flow and the
ordinary `k_invoice` cannot take a ნსაფ id. The status-7 auto-reversal calls `_reverse_moves` directly and is not
affected.

Hooks of rs_einvoice that `account.move` overrides here (all test the original, `self`, never the copy, so a
Correct / Cancel & Reissue copy of an ordinary fuel invoice never becomes a ნსაფ):

| Hook | ნსაფ behaviour |
|---|---|
| `_rs_correction_k_types` | `SPEC_K_TYPES` codes instead of '1'-'4' |
| `_rs_correction_copy_vals` | drops `rs_einv_k_type`, adds `rs_einv_is_spec`, `rs_spec_k_type` and the header fields in `SPEC_COPY_FIELDS` |
| `_rs_assert_correction_can_be_sent` | not overridden: called by `_rs_spec_create_correction` for the pre-send guards |
| `_rs_do_correct_reissue` | after `super()`, type 11 sets the copy's fuel quantity to 0; other types copy `rs_spec_unit`, `rs_spec_quantity_l` and `rs_spec_quantity_kg` from the original, so typed kg (or litres on a non-volume UoM) are not recomputed to 0 |

`rs_spec_k_type` is a separate field on purpose: the ordinary `rs_einv_k_type` list must not show petroleum codes.

Flow: wizard `modify_moves` → `_rs_do_correct_reissue(k_type)` → draft copy (`rs_einv_replaces_id`, mode `correction`) →
Confirm (`_rs_spec_mark_before_post` marks it) → Save / Send (`_rs_spec_push`, section 5) → status 5 → buyer
confirms 8 → `_rs_refresh_apply_status` (rs_einvoice) cancels the original; a rejection resets the copy to draft.

Status 4 (New Correction) is not in `RS_LOCKED_STATES`, so Reset to Draft is allowed there: a saved, unsent correction
is edited and confirmed again before Send. Status 8 is in `RS_CONFIRMED` (`('2', '8')`), so the correction can itself
be corrected again with the same treatment, except after type 11.

When the buyer confirms (8) the original goes through `_rs_auto_cancel_after_rs_cancellation`
(rs_einvoice/models/account_move_cancel.py:52-137): Odoo cancels it; if it belongs to an earlier VAT period (or a lock
date covers it) it is reversed with a credit note dated today instead; if payments or credit notes are applied, Odoo
leaves it and flags a To-Do to unreconcile first (Check Status retries).

## 7b. Transfers without a waybill

The ნსაფ replaces the rs.ge waybill for its load. Every waybill rs_waybill makes from a transfer is created in
`stock.picking._rs_try_create_waybill` (called from `action_assign`, `stock.move._action_assign`, backorders and an
operation-type change; it also builds internal and return waybills). The override returns without a waybill when every
product of the transfer has `rs_spec_rs_id`; otherwise `super()`. With no waybill, rs_waybill's `_action_done`
guard (it checks only transfers that have a waybill) lets the transfer validate. A mixed transfer keeps its waybill.

## 8. Guards and invariants

| Guard | Where |
|---|---|
| Fuel alone, one fuel line, filed ნსაფ keeps its fuel line | `_rs_spec_mark_before_post` |
| A move filed as ordinary e-invoice or an ordinary replacement is never marked | `_rs_spec_mark_before_post` |
| No Reset / Cancel / delete while live on rs.ge | rs_einvoice `_rs_raise_if_locked`, `unlink`, through the refresh override |
| Partner, date, currency, type locked once on rs.ge | rs_einvoice `_rs_write_check_immutable_fields` |
| `UNIQUE (rs_einv_id, company_id)` covers both services | rs_einvoice constraint; the id ranges do not overlap in practice |
| Ordinary seller buttons and View RS Data hidden for a ნსაფ | rs_einvoice views (`rs_einv_is_spec`) |
| ნსაფ excluded from annex ბ I and ბ II; filled into tabs 13 and 14 | gec_vat_declaration `_gec_b1_scan(spec)`, `_gec_b2_scan(spec)`; this module's `action_generate` override |

## 9. Security

| Model | Group | Rights |
|---|---|---|
| `rs.spec.site` | Internal user | read |
| `rs.spec.site` | Invoicing | create, read, write |
| `rs.spec.site` | Product manager | create, read, write (the product sync also loads sites) |

No `company_id` on `rs.spec.site`: sites are keyed by the taxpayer id, like `res.partner.rs_un_id`. Synced products
are shared (`company_id` empty): rs.ge's petroleum list is the same for every taxpayer (checked live with two
taxpayer ids). Creating products needs `product.group_product_manager` (core product access); the sync menu carries
that group; the sync's posted-line check runs `sudo()` so it sees every company's bills, as core's unit guards do. The `rs_spec_*` fields on `account.move`
follow the invoice's own access. `rs_spec_vehicle_id` is shown only to `fleet.fleet_group_user` (invoicing users have
no read access on `fleet.vehicle`). No `sudo()` in the module except the VAT rows `_gec_spec_row` (sudo like ბ I /
ბ II); the buyer un_id lookup writes the partner as superuser inside rs_einvoice `_rs_partner_un_id`.

## 10. Integration

| Module | Relies on |
|---|---|
| rs_einvoice | defines `rs_einv_is_spec`, hides its seller buttons and View RS Data for it; its crons and locks reach this module through `action_rs_refresh_status` |
| rs_base_methods | per-user, per-company rs.ge login; its waybill tab is hidden for a ნსაფ |
| rs_waybill | `rs_is_driver`, `rs_is_foreigner` on contacts; `rs_plate_only` display of vehicles; `_rs_try_create_waybill` is the single waybill-creation entry this module overrides |
| gec_vat_declaration | excludes `rs_einv_is_spec` from annex ბ I and ბ II; this module fills tabs 13 and 14 in its `action_generate` override (super first) |

Renaming `action_rs_refresh_status`, `_rs_raise_if_locked`, `_rs_line_to_payload`, `_rs_line_vat_class` or the
shared fields in rs_einvoice breaks this module silently (overrides would stop applying).

## 11. Tests

None yet.

## 12. Extending safely

- Never call `super()` for a ნსაფ in `action_rs_refresh_status`; any new rs_einvoice refresh step must check the
  service first.
- New posting paths that a user triggers must call `_rs_spec_mark_before_post`; automated posting must not.
- Keep the remote-line lookup before `save_invoice_desc_n`: rs.ge adds a line for id 0.
- Commit only right after an rs.ge write succeeded, and relock after it (rs_einvoice pattern).
- rs.ge petroleum ops end in `_n`; the ordinary service has different names and payloads: never route one service's
  id to the other.

## 13. Known limitations

- No rs.ge cancel (status 6), transport start, types 3-5, crons of its own.
- Buyer rejection handling assumes rs.ge returns the correction to status 4; not verified on live rs.ge.
- Check Status on the original also refreshes its correction; a correction missing on rs.ge is logged, not raised.
- Corrections: never change the header; corrections made on the rs.ge portal are not seen by Odoo; not tested against
  live rs.ge; in a foreign currency a price correction carries the exchange-rate change too.
- No advance attachment on the petroleum service (`get_attachable_advance_invs`, `attach_advance_invoice`): a final
  ნსაფ after an ordinary down-payment invoice carries the full VAT.
- `rs_einv_is_spec` is readonly in the view only; the server does not refuse writes to it.
- If rs.ge returns no row for a ნსაფ id, Reset and Cancel are refused with "rs.ge has no petroleum invoice".
- Supplier correction of a ნსაფ bill whose original is still live (Import Supplier Correction) is not supported: it
  needs `rs_einv_supplier_k_id`, which only the ordinary refresh sets; the cancel-and-reissue path from the inbox works.
- Merged stock moves keep only the first move's Alt. Quantity (`_merge_moves`); the second unit is typed per document
  and never converted.
- A product whose unit the sync would change but that already has documents keeps its unit and gets a chatter note.

## 14. Upgrading an existing database

Install together with `-u rs_einvoice` (new column `rs_einv_is_spec`) and `-u gec_vat_declaration`. A database whose
rs_waybill, rs_einvoice or rs_base_methods views are older than the code fails the install's view check: upgrade those
modules in the same run.
