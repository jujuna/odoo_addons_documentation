# rs_base_methods — Code Review Findings

Review date: 2026-07-02/03. Scope: every file in the module (Python, 6 XML, security CSV + rules, drift script), verified against Odoo 20 base ACLs (`odoo/addons/base/security/ir.access.csv`) and gec_rs_waybill call sites. Diagnosis only — no code was changed. Use the checkboxes to track fixes.

Overall: cleaner than rs_einvoice — `float_compare`/`float_is_zero` discipline, batched SO-line matching, invoices built through core `_prepare_invoice()` / `_prepare_invoice_line()` / down-payment builders. The findings below are concentrated in security and the waybill-link SOAP layer.

Confidence tags: **[C]** certain (verified against core), **[L]** likely, **[G]** guessing.

---

## 1. Security — fix immediately

### 1.1 [C] `rs_password` is cleartext and RPC-readable by any internal user
- [ ] **Fix:** change `groups='base.group_user'` to `groups='base.group_system'` on `rs_password` (and `rs_username`); keep `user_writeable=True` on both (so users still manage their own creds); change `_get_rs_credentials` to read via `self.sudo()` so service calls keep working for the owner.
- Where: [models/res_users.py#L50](models/res_users.py#L50) (`rs_username`), [models/res_users.py#L54](models/res_users.py#L54) (`rs_password`), [models/res_users.py#L113](models/res_users.py#L113) (getter)
- Breaks: base grants read on res.users to `base.group_user` (every employee; `odoo/addons/base/security/ir.access.csv:70`). Both fields carry `groups='base.group_user'`, so they are readable by every internal user and `read(['rs_username','rs_password'])` on any user id returns another employee's rs.ge credentials — credentials that can file, cancel, and accept fiscal documents. The view's `password="True"` masks the widget only, not RPC. Inconsistent with `rs_access_token`/`rs_device_code`, which carry `groups='base.group_system'`.

### 1.2 [L] Over-broad wizard ACLs
- [ ] **Fix:** scope `rs.invoice.from.waybill.wizard` (+line) to `account.group_account_invoice` instead of `base.group_user`. Not a live hole — account.move's own ACL blocks the final create — but least-privilege hygiene.
- Where: [security/ir.access.csv#L6](security/ir.access.csv#L6)

---

## 2. Bugs / accounting risks

### 2.4 [G] Cross-currency price comparison in the wizard
- [ ] **Review:** `_prepare_line_vals` compares wizard `unit_price` (GEL, from waybill/SO seed) against `sale_line_id.price_unit` (SO currency) with `float_is_zero` and overrides on mismatch. Dormant while all SOs are GEL; add a currency assert if foreign-currency SOs ever appear.
- Where: [wizards/rs_invoice_from_waybill_wizard.py#L205-L211](wizards/rs_invoice_from_waybill_wizard.py#L205-L211)

### 2.5 [L] `_rs_sync_waybill_links` — N+1 SOAP reads
- [ ] **Fix:** the full remote list is re-read after **every** link save (`rows = _read_remote_rows()` inside the loop, [models/account_move.py#L92-L115](models/account_move.py#L92-L115)). Do one final read matching all saved links (keep the claimed-id logic) — roughly halves the calls.
- Where: [models/account_move.py#L76](models/account_move.py#L76)

---

## 3. Multi-company / branch

- 3.3 [G] Branches: strict `company_id ==` equality everywhere; branch hierarchies would need branch-aware comparison. Only relevant if branches get used.
- Already correct: multi-company record rule on the link model, `company_id` stored+indexed, wizard company checks on the standalone path.

---

## 4. Optimization / less code / clean code

- [ ] 4.2 Raw `SELECT FOR UPDATE NOWAIT` in `_lock_waybills` → `lock_for_update()` (raises `LockError` when a row is busy; all-or-fail semantics fit here). Current code at least catches `psycopg2.errors.LockNotAvailable` properly. [models/rs_einvoice_waybill_link.py#L71-L79](models/rs_einvoice_waybill_link.py#L71-L79)
- [ ] 4.4 Extract the SO-mix validation (grouped-detail error text) written twice: [models/rs_waybill.py#L113-L121](models/rs_waybill.py#L113-L121) and [wizards/rs_invoice_from_waybill_wizard.py#L172-L180](wizards/rs_invoice_from_waybill_wizard.py#L172-L180).
- [ ] 4.5 Drop the dead defensive try/except ladder around `_get_user_fiscal_lock_date` (stable core API; the sibling module calls it bare). [wizards/rs_invoice_from_waybill_wizard.py#L188-L195](wizards/rs_invoice_from_waybill_wizard.py#L188-L195)
- [ ] 4.6 Magic tuple `(5,0,0)` → `Command.clear()` [wizards/rs_invoice_from_waybill_wizard_line.py#L136](wizards/rs_invoice_from_waybill_wizard_line.py#L136).
- [ ] 4.7 Link `write()` raises on `waybill_id`/`move_id` present in vals even when the value is unchanged — compare before raising. [models/rs_einvoice_waybill_link.py#L148-L158](models/rs_einvoice_waybill_link.py#L148-L158)
- [ ] 4.8 `default_get` parses raw `(6,0,ids)` tuples — use `Command` constants for readability. [wizards/rs_invoice_from_waybill_wizard.py#L76-L88](wizards/rs_invoice_from_waybill_wizard.py#L76-L88)

---

## 5. Do NOT "clean up" — deliberate protection / already right

- The waybill mutation lock (implemented, verified 2026-07-02): `_rs_assert_not_invoice_linked` on refuse/edit/submit/delete ([models/rs_waybill.py#L37](models/rs_waybill.py#L37)). Stuck-lock compute fixed via `wb.state != 'cancelled'` ([models/rs_waybill.py#L30](models/rs_waybill.py#L30)).
- Link-level defence in depth: write/unlink guards + remote detach + unique (move, waybill) constraint + active-holder constraints + `_lock_waybills` race lock.
- `_BigInteger` (int8) for rs.ge row IDs beyond int4 range — documented with observed values.
- `_rs_prefetch_sale_line_candidates` batch matching (explicit N+1 avoidance) and preferred-SO narrowing in `_match_sale_line`.
- Negative-net-quantity block in `_aggregate_invoice_lines` (steers excess returns to a credit note instead of a negative rs.ge line).
- `scripts/detect_invoice_id_drift.py` — read-only diagnostic, run via odoo shell.

## Suggested fix order

1. 1.1 (password field) — one field change + sudo in the getter; ship alone.
2. 2.4–2.5 + section 3 as one hardening pass.
3. Section 4 as a separate mechanical PR.
