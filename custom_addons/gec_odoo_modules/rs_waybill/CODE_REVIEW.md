# rs_waybill code review (2026-10-28 → 2026-11-01)

Scope: every file of the module: `models/`, `wizards/`, `views/`, `static/`, `data/`, `security/`.
Every fix has a test; last full run of `/rs_waybill` (with `rs_base_methods` installed): 486 tests, 0 failed.

Confidence tags: [Certain] = read in source or reproduced in a test; [Likely] = strong inference; [Guessing] = gap-filling.

How each finding is explained to the user: a "Now (wrong)" and an "After the fix" step-by-step flow with a concrete
example, then ask before changing code.

---

## 1. Fixed — `rs_waybill.py` review

Commit `df9bb33`:
- [x] 1. Receipt step after an RS.GE sync is a post-commit step (`_rs_post_commit`): a failure no longer rolls back the
  sync; one chatter message per distinct error; a PO awaiting approval counts as pending.
- [x] 2. Scrapping lost goods runs one move at a time (`_action_scrap` handles a single move).
- [x] 3. Returns (type 5) never change the SO ordered quantity; return lines link to their return move; a done return
  changed on RS.GE refreshes its "deliver later or reduce?" question (`_rs_refresh_return_question`).
- [x] 4. Documents built after product mapping go through `_rs_post_commit` (savepoint, retried by drift).
- [x] 5. Type 3 (Without Transport) needs no driver/car; switching to type 3 clears `transport_type`.

Commit `2416df5`:
- [x] 6. [Certain] "Buyer cannot be your own company" compared with the switcher's company → the waybill's company.
  Type 1 is unaffected (its `buyer_id` stays empty).
- [x] 7. [Certain] PO picker showed with unmapped lines (`all(line_ids.mapped('product_id'))` drops empty lines) → shown
  only when every line has a product and no `uom_review`; `action_link_purchase` refuses otherwise
  (`_rs_check_lines_mapped`, `_rs_lines_need_mapping`).
- [x] 8. [Certain] A synced type 1 whose two addresses match one warehouse made a transfer from a location to itself →
  skipped when `(truck or src_loc) == dst_loc`; truck → same warehouse still moves.
- [x] 9. [Certain] Vendor raised again after a short: product-unit amount compared with PO-line-unit shorts → converted.
- [x] 10. [Certain] Picking Normal on a blank Medicine field wiped all lines → `is_medicine` defaults to `'0'`; lines are
  cleared (with a warning) only on a real Normal ↔ Medicine switch, compared with `_origin`.
- [x] 11. [Certain] Lot/serial goods on a PO made from the waybill: Received returned silently (`first_time` was False)
  → one to-do for the purchaser per receipt (`_rs_ask_lots`).
- [x] 12. [Certain] "Lock Confirmed Sales": every automatic SO line write failed, rolled back the delivery and retried
  forever → `_apply_line_diffs_to_picking_in_place` / `_apply_line_diffs_increase_on_done` unlock the order for that
  change only, lock it again and note it (`_rs_unlock_orders`, `_rs_note_followed_orders`). Returns untouched.
- [x] 13. [Certain] Driver/car lookups ignored the company; plates are unique across companies (fleet constraint) →
  car created in the waybill's company; another company's car or contact is not linked (RS.GE still gets
  `car_number` / `driver_tin`); `_rs_driver_from_tin(tin, name, company)`.
- [x] 14. [Certain] Transporter TIN lookup raised when RS.GE was down and used the switcher's login → try/except and
  `_rs_service()`; driver TIN lookups use the waybill company's login too.

Minor (`2416df5`):
- [x] Linked-transfer validation failure posted a message every 15 minutes (drift) → banner + one message per distinct
  reason (`_rs_note_validate_failure`); the repair counts it repaired only when the picking is done.
- [x] Unused `is_own_transport` (field, view, tests, README, ka_GE.po) and imports `timedelta`, `datetime`, `base64`,
  `html` removed; duplicate `picking = self.picking_id` removed.
- [x] Missing space in "Every line must have a product selected. %d line(s)…"; `ensure_one()` in
  `_validate_transporter_driver_fields`.
- [x] Comments and docstrings in the touched methods shortened to at most 2 lines.

Edge case (`2416df5`):
- [x] [Certain, reproduced] One product on two vendor waybill lines (two vendor codes mapped to it), PO made from the
  waybill: Received put the total on the first PO line (bill wrong, a receipt left open) → each waybill line follows its
  own PO line through new field `rs.waybill.line.purchase_line_id` (`_rs_own_po_lines`, `_rs_correct_own_po_lines`).
  **Deploy with `-u rs_waybill`.** Waybills received before it have no link and pair by creation order.

## 2. Fixed — other files (commit `df9bb33`)

- [x] Units: waybill lines carry `uom_id` / `rs_unit_code` / `uom_review`; RS code 14 (შეკვრა) for any package; whole
  packs of the SO line's unit declared as packs; buyer unit matching + "Unit Needs Review" (blocks PO/Receive); the unit
  picked in Resolve Now is remembered on the mapping; invoice wizard (rs_base_methods) quantity in the SO line unit.
- [x] Cron method renamed `_cron_sync_updated_waybills`; `uom_data.xml` noupdate; "Bundle (base unit)".
- [x] `migrations/` deleted (no deployed DBs) with the legacy upgrade code.
- [x] Per company: `is_rs_product` (company_dependent), `rs_enable_stock`, mappings require a company.
- [x] Settings: Auto-Sync boxes read the crons' real state; `rs_notification_email` → `rs_notification_user_ids`.
- [x] Lock on Send / Send to Transporter; one PDF per waybill; RS.GE invoice path removed — invoices only through the
  rs_base_methods wizard → rs_einvoice; `rs_invoice_id` removed.

## 2b. Fixed — the remaining files (2026-11-01, this commit)

- [x] 2. [Certain] Adjustment history: an old version's goods are now marked against RS.GE's current version
  (Changed / Removed later / Added later / Unchanged, `_snapshot_line_vals`); only the header was compared before.
- [x] 3. [Certain] Adjustment history: transport cost compared with `float_compare` (100.0 vs 100.00000000001 is not a
  change), as the Live RS View already did.
- [x] A. [Certain] Sync summary email: links were relative (`/odoo/rs.waybill/5`) and did nothing in a mail client →
  full URL from `web.base.url`.
- [x] B. [Certain] Waybill email showed the activation time in UTC → Georgian time (`TBILISI_TZ`).
- [x] Emails: colours and logo come from the company (`primary_color`, `email_secondary_color`, `logo`; the brand kit
  writes them on Apply, no dependency on it); white logo bar; text and accent switch for contrast; an invalid colour
  falls back; the two sync summary emails get the same frame (`_rs_mail_brand`, `_rs_mail_top_bar`, `_rs_mail_frame`).
- [x] C. [Certain] A Save refusal showed only "error code: -1004" → decoded through `_check_rs_result` like the other
  buttons. **Only a negative STATUS is decoded: Save answers 0 on success, unlike the actions (1).** Routing every Save
  STATUS through `_check_rs_result` refuses every successful Save; `test_save_success_codes_are_never_refused` guards it.
- [x] M. [Certain] A delivery cancelled from its order left a draft saved on RS.GE and told the user to click a Delete
  button that is hidden → the draft is deleted on RS.GE (`StockMove._action_cancel`), as Cancel on the delivery does;
  an RS.GE error stops the change.
- [x] N. [Certain] Configuration menus opened into access errors: Settings for `base.group_system` only, Car Plates for
  Fleet users only; waybill users get read access to `fleet.vehicle` so the Car Plate dropdown works for them.
- [x] O. [Certain] The main Complete button completed on RS.GE without a confirmation → "Complete this waybill?".
- [x] P1. [Certain] Save as Template kept only type, buyer, addresses and seller in Odoo → the template copies the
  header RS.GE keeps and the goods lines from the waybill (`TEMPLATE_HEADER_FIELDS`, `_template_line_commands`).
- [x] P2. [Certain] Create from Template never brought the goods (`copy()` does not copy One2many lines) → lines copied.
  A template never touches stock; a waybill made from one creates its order and delivery on Save like any other.
- [x] Q. [Certain] Missing space in "…before applying (%d still unmapped)".
- [x] R. [Likely] Resolve Now offered other companies' products → limited to the waybill's company and shared products,
  refused on Apply too.
- [x] J, K. Waybill button titles translated (`sale_order.py`, `stock_picking.py`); the "not saved on RS.GE" validate
  message reworded (Georgian typo "გაააქტიურეთ" fixed).
- [x] L. [Certain] The waybill list style matched any list with a `template_name` column → the Templates list carries
  its own class `o_rs_waybill_template_list`.

## 3. Open decisions (asked, not answered)

- [ ] Locked SO to-dos: popup "Reduce the order" / "Deliver later" and a cancelled delivery
  (`stock_picking._rs_reduce_sale_order`) still give a to-do for a locked order (#12 made only the automatic updates
  follow). Decide after testing the whole module. Unlocked orders are automatic; the credit-note to-do stays.
- [ ] Medicine flow (registry codes on lines): the user works it out later.
- [ ] Type 3 `TRANS_ID`: Odoo sends `1` (Auto) for Without Transport (`rs_waybill_soap_service.py`). Check on RS.GE.
- [ ] `fleet_vehicle.py`: the RS plate import matches vehicles across companies.
- [x] `account_tax.py` 0% taxes defaulting to RS VAT type Standard: resolved by `210af1d` (`rs_vat_type` dropped, the
  VAT type comes from the Tax Category Code).
- [ ] `purchase_order.py`: whole PO locked once a waybill is linked; `waybill_id` (One2many) should be `waybill_ids`;
  `waybill_count` unused.
- [ ] RS unit code 6 unknown: run `get_waybill_units` on a live account.
- [ ] Distribution cancel half-finished (`_rs_cancel_distribution`): accepted as is (drift repairs).
- [ ] 1. Adjustment history "Edit Date" may be 4 hours late: `get_adjusted_waybills` DT is stored without the
  Georgian → UTC conversion. Check what RS.GE sends before changing it.
- [ ] H. The customer's end address is `partner.street` only, without the city (`stock_picking.py`, `rs_waybill.py`).
- [ ] I. A delivery to a child contact sends the child's name as `buyer_name`; check whether RS.GE accepts it.
- [ ] D. `delete_waybill_template` does not check RS.GE's answer; find out what a successful delete returns first
  (the Save trap in C).
- [ ] G. `_rs_pickup_type` also returns an archived Customer Pickup type (kept: it stops a duplicate CP type).
- [ ] `rs_waybill_operation.py` is never used; delete it in its own commit after checking client DBs have no rows.
- [ ] Hourly sync and Fetch All: Fetch All reads only waybills created in the last 30 days; older ones edited today come
  only through the hourly cron (`get_waybills_v1`).

## 4. Not checked yet (edge cases, [Guessing])

- [ ] Multi-step delivery (pick + ship): only the final step is linked; truck sub-waybills may move stock twice.
- [ ] `_force_validate_moves` with several existing move lines (full quantity on the first line only).
- [ ] RS.GE lowering more than is still delivered after a partial return.

## 5. Files not reviewed yet

None. Read only in outline: `_sync_goods_lines` and the template part of `rs_waybill_sync.py`.

## 6. Do NOT "clean up" — deliberate

- RS.GE first, commit, then Odoo: every local step after an irreversible RS.GE call goes through `_rs_post_commit`
  (savepoint, `rs_post_commit_error` banner, retried by `_rs_repair_local_state`).
- `lock_for_update` on Save / Send / Send to Transporter (`_rs_lock`): a second click must not send twice.
- `skip_procurement` on every SO line write from the waybill: stops Odoo creating a duplicate delivery.
- A PO the purchaser made keeps its quantities; only a PO made from the waybill (`_rs_owns_purchase`) follows it.

## 7. Run the tests

Scratch DB, dropped afterwards (`DEBUG=0` must be an environment variable):
```
DB=claude_x
ODOO="cd /opt/odoo && python odoo-bin -c /etc/odoo.conf --db_host odoo20_db --db_user odoo --db_password odoo -d $DB --stop-after-init --no-http"
docker exec -e DEBUG=0 odoo20_odoo sh -c "$ODOO -i rs_waybill,rs_base_methods --without-demo=all"
docker exec -e DEBUG=0 odoo20_odoo sh -c "$ODOO -u rs_waybill,rs_base_methods --test-tags /rs_waybill,/rs_base_methods"
docker exec odoo20_db dropdb -U odoo $DB
```
Grep the output for `tests when loading|FAIL:|ERROR: Test`: many tests raise and log errors on purpose.

## Suggested order

1. Manual test on RS.GE's test account: items 1, I and D in section 3 need RS.GE's real answers.
2. Section 4 edge cases.
3. Section 3 decisions as they come up.
