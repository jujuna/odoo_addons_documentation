# rs_einvoice — Code Review Findings

Review date: 2026-07-02/03. Scope: every file in the module (16 Python files / 8,513 lines, 8 XML, security, JS widget, SCSS), verified against Odoo 19 core (`odoo/orm/models.py`, `addons/base/models/res_users.py`, `addons/account/models/account_tax.py`) and `rs_invoice_api_docs.md`. Diagnosis only — no code was changed. Use the checkboxes to track fixes. Paths re-pointed 2026-09-29 after the file split (`account_move_cancel.py`, `account_move_checks.py`); line anchors dropped, the method names are the reference.

Confidence tags: **[C]** certain (verified against core/API docs), **[L]** likely (strong inference from code), **[G]** guessing (plausible, unverified).

---

## 1. Bugs — fix first

### 1.3 [L] Buyer Accept never compares the operator's edited bill amounts to the rs.ge snapshot
- [ ] **Fix:** before `buyer_accept_invoice` (targets 2/8), compare local product-line sums (`price_total`, VAT) to pulled snapshot sums (`full_amount`, `drg_amount`) within a small tolerance; block with an explicit override context flag.
- Where: `action_rs_buyer_accept`, [models/account_move_buyer.py](models/account_move_buyer.py)
- Breaks: a supplier change after the import is refused (`rs_einv_pulled_lines_hash`), but the operator can still edit amounts on the draft and certify on rs.ge — booked input VAT diverges from what rs.ge holds. The form only *asks* the user to compare ("Reject if they don't match").
- Related cents-level gap: `_rs_pulled_line_vals` sets `price_unit=(full-vat)/qty` and lets Odoo recompute VAT — can differ from rs.ge `drg_amount` by a cent with no adjustment line.

### 2.4 Notes — intentional design, keep as is
- Commit-before-SOAP two-phase pattern (`_rs_mark_pending` [models/account_move.py](models/account_move.py), commits in create/correction/send/cancel/accept/reject flows) is the orphan-recovery design. Every commit is followed by relock+invalidate. Constraint for future code: anything calling these actions must be commit-aware (`_rs_auto_sync_pending_sent_edits` correctly routes through non-committing `action_rs_edit`).
- `action_rs_delete` uses bare truthiness on the SOAP result (the exact trap the C2 comment on `_rs_send_succeeded` documents) but is self-correcting — the follow-up `get_invoice` status≠-1 check catches a false success. Unify anyway (see 4.3).

---

## 3. Multi-company / branch

- 3.4 [G] Branches: all checks are strict `company_id ==` equality. With Odoo 19 branches, an invoice on a branch with the user on the parent would false-block. Only relevant if branches get used.
- Already correct: multi-company record rules on all auxiliary models, `company_id` stored+indexed, `rs_einv_id` unique per company.

---

## 4. Optimization / less code / clean code

- [ ] 4.3 One `_rs_flag_ok(result, attr)` helper to replace 3 hand-rolled SOAP success checks: `_rs_cancel_core` and the delete truthiness in `action_rs_delete` [models/account_move_seller.py](models/account_move_seller.py), buyer reject in `_rs_do_buyer_reject` [models/account_move_buyer.py](models/account_move_buyer.py). Canonical logic already exists in `_rs_send_succeeded` [models/account_move.py](models/account_move.py).
- [ ] 4.13 JS display nit: `vatAmount === 0` float equality labels a 1e-13 residue as "taxable" [static/src/js/rse_lines_field.js#L65](static/src/js/rse_lines_field.js#L65). Display only.
- [ ] 4.14 [G] Shared module-level zeep `Client` + one `requests.Session` (`_RS_CLIENT_CACHE` in [models/rs_soap_service.py](models/rs_soap_service.py)): fine under prefork; not documented thread-safe under the threaded server. Lock or per-thread cache if threaded mode is ever used.

---

## 5. Do NOT "clean up" — deliberate protection

- Orphan-recovery pending markers + mid-flow commits (duplicate-filing protection).
- SKIP LOCKED cron refreshers with `_commit_progress`, stranded-cancellation recovery cron.
- Partial line-sync detection with post-sync count verification.
- Advance-settlement guards: stray-advance, over-settle, MIN_DRG floor (`-1` = no floor per API docs), same-month refusal.
- Hardened raw-SOAP XML parsing (XXE-safe parser per call).

## Suggested fix order

1. Section 1 items 1.1–1.2 (small, isolated) and rs_base's password fix together.
2. 1.3 and 1.5 as one accounting-hardening pass (touches accept/import/payload paths — retest buyer flow end-to-end).
3. Section 4 as a separate mechanical PR so review stays easy.
