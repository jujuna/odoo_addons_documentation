# rs_waybill Data Safety + Indexes Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps where Odoo and RS.GE (or Odoo and its own stock) can silently disagree, and add the missing database indexes.

**Architecture:** Small, independent fixes in the existing files; no new models. Each fix is test-first: a test that fails on today's code, the smallest change, then the whole `rs_waybill` suite.

**Tech Stack:** Odoo 20 (Python 3, ORM, `odoo.tests`), PostgreSQL, Docker containers `odoo20_odoo` / `odoo20_db`.

**Spec:** the module review of 2026-10-20 (five reviewers; findings A1–A7 and B8–B10, verified in code). Business rules from memory: a cancelled seller waybill means the order is abandoned; a completed waybill is corrected, never cancelled.

## Global Constraints

- Module path: `/home/saba/Desktop/odoo20/customAddons/gec_odoo_basic_modules/rs_waybill/`; paths below are relative to it.
- Odoo 20 only: `ir.access.csv`, `models.Index`, `index='btree_not_null'`, `self.env['ir.cron']._commit_progress()`, `lock_for_update()`.
- Run one test class: `docker exec odoo20_odoo sh -c 'python3 /opt/odoo/odoo-bin -c /etc/odoo.conf --addons-path=/opt/odoo/addons,/mnt/enterprise,/mnt/extra-addons/gec_odoo_basic_modules -d rsw_plan1 -i rs_waybill,rs_base_methods --test-enable --test-tags /rs_waybill:<Class> --stop-after-init --no-http --without-demo=all --log-level=test'`, then `docker exec odoo20_db dropdb -U odoo --force rsw_plan1`.
- Full suite: same command with `--test-tags /rs_waybill,/rs_base_methods`. Baseline: 291 tests, 0 failures.
- Tests never call RS.GE: patch `rs.waybill.soap.service` methods; patch `cr.commit` where the code commits.
- **Never commit or push.** Each task ends with the changes left in the working tree for the user to test and commit.
- User messages through `_()`; chatter HTML through `Markup`.

## Review Focus

1. A waybill that is mid-Adjustment when a sync arrives: the user's unsent lines must not be overwritten silently (Task 6 test 3).
2. Deleting a waybill from a list (several records, some on RS.GE): all refused, none deleted (Task 2 test 2).
3. Drift run cut by the cron time limit: waybills already checked stay checked (Task 3 test 2).
4. Cancel of a sales order whose second delivery's waybill refuses: the order is not cancelled, and a retry works (Task 5 test 2).
5. Bulk "Mark as Received" on 10 waybills, one refused: the other 9 still go through (Task 4 test 2).

---

### Task 1: Database indexes (B8, B9, B10)

**Files:**
- Modify: `models/rs_waybill_line.py:10` (`rs_waybill_id` → `index=True`)
- Modify: `models/stock_picking.py:33` (`waybill_id` → `index='btree_not_null'`)
- Modify: `models/rs_waybill.py:84` (`picking_id`), `:204` (`purchase_id`), `:217` (`sales_order_id`) → `index='btree_not_null'`; `:107` (`company_id`) → `index=True`; add `_create_date_id_idx = models.Index("(create_date desc, id desc)")` next to `_order` at `:32`
- Test: `tests/test_indexes.py` (new; register in `tests/__init__.py`)

**Interfaces:** Produces nothing other tasks use.

- [ ] **Step 1: Write the failing test** `TestIndexes.test_lookup_columns_are_indexed`: for each `(table, column)` in `[('rs_waybill_line','rs_waybill_id'), ('stock_picking','waybill_id'), ('rs_waybill','picking_id'), ('rs_waybill','purchase_id'), ('rs_waybill','sales_order_id'), ('rs_waybill','company_id')]`, query `pg_indexes` and `assertTrue(any(column in indexdef for indexdef))`; plus `test_list_sort_is_indexed`: an index on `rs_waybill` whose `indexdef` contains `create_date DESC`.
- [ ] **Step 2: Run** `--test-tags /rs_waybill:TestIndexes`. Expected: FAIL on every column.
- [ ] **Step 3: Add the index attributes** listed under Files.
- [ ] **Step 4: Run** the class again. Expected: PASS. Then the full suite: 0 failures.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 2: A waybill on RS.GE cannot be deleted (A1)

**Files:**
- Modify: `models/rs_waybill.py` (add the ondelete method near the CRUD overrides)
- Modify: `models/rs_waybill_actions.py:562` (`self.unlink()` → `self.with_context(rs_deleted_on_rs=True).unlink()`)
- Test: `tests/test_delete_guard.py` (new)

**Interfaces:**
- Produces: `RsWaybill._unlink_except_on_rs(self) -> None`, decorated `@api.ondelete(at_uninstall=False)`. Allows a waybill when `not rs_internal_id`, or `state == 'cancelled'`, or `is_template`, or context `rs_deleted_on_rs`; otherwise raises `UserError` naming the waybill and saying "Cancel or delete it on RS.GE first (Cancel / Delete buttons)."

- [ ] **Step 1: Write failing tests:**
  - `test_active_waybill_cannot_be_deleted`: `make_waybill(state='active', rs_internal_id=900001)`; `assertRaises(UserError)` on `unlink()`; `assertTrue(waybill.exists())`.
  - `test_list_delete_refuses_all`: two waybills (one draft without RS ID, one completed with RS ID) unlinked together → `UserError`; both still exist.
  - `test_local_draft_and_cancelled_can_be_deleted`: draft with `rs_internal_id=False`, and cancelled with an RS ID → `unlink()` works.
  - `test_delete_button_still_works`: draft with RS ID; patch `delete_waybill` to return `True`; `action_delete_waybill()` → the record is gone.
- [ ] **Step 2: Run** `/rs_waybill:TestDeleteGuard`. Expected: the first two FAIL (deleted); the last two PASS.
- [ ] **Step 3: Implement** `_unlink_except_on_rs` and the context in `action_delete_waybill`.
- [ ] **Step 4: Run** the class, then the full suite. Fix any existing test that deletes an RS waybill directly by giving it `rs_deleted_on_rs=True`, and say which.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 3: Drift saves each waybill as it goes (A2)

**Files:**
- Modify: `models/rs_waybill_sync.py:1416-1418` (end of the per-waybill loop in `_cron_rs_drift_repair_one`)
- Test: `tests/test_drift_progress.py` (new)

**Interfaces:**
- Consumes: core `self.env['ir.cron']._commit_progress(processed=1) -> float` (seconds left; `inf` outside a cron; commits).

- [ ] **Step 1: Write failing tests** (patch `get_full_waybill` to return `(None, [])`, and patch `ir.cron._commit_progress`):
  - `test_each_waybill_is_committed`: 3 candidate waybills → `_commit_progress` called 3 times with `processed=1`.
  - `test_stops_when_cron_time_is_up`: `_commit_progress` returns `0.0` → `get_full_waybill` called once; the other two keep `rs_drifted_checked = False`.
- [ ] **Step 2: Run** `/rs_waybill:TestDriftProgress`. Expected: FAIL (`_commit_progress` never called).
- [ ] **Step 3: Implement** after `waybill.rs_drifted_checked = fields.Datetime.now()`: `if not self.env['ir.cron']._commit_progress(1): break`.
- [ ] **Step 4: Run** the class, then the full suite.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 4: Received shows the RS.GE refusal (A5)

**Files:**
- Modify: `models/rs_waybill_actions.py:621-623` (the `except` in `action_confirm_waybill`)
- Test: `tests/test_receive_errors.py` (new)

**Interfaces:** none new.

- [ ] **Step 1: Write failing tests** (buyer waybill, active, `rs_internal_id` set, `waybill_type='5'` so no PO is needed; patch `cr.commit`, which the action calls):
  - `test_single_receive_shows_the_refusal`: patch `confirm_waybill` to raise `UserError('RS.GE refused')` → `assertRaises(UserError)`; `is_confirmed` unchanged.
  - `test_bulk_receive_skips_the_refused_one`: two waybills, `confirm_waybill` raises only for the first (by ID) → no exception; the second has `is_confirmed == '1'`; the returned notification message contains "1 confirmed, 1 skipped".
- [ ] **Step 2: Run** `/rs_waybill:TestReceiveErrors`. Expected: the first FAILS (no exception), the second PASSES.
- [ ] **Step 3: Implement** in the `except`: `if len(self) == 1: raise`, before the logging/skip.
- [ ] **Step 4: Run** the class, then the full suite.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 5: Cancel cannot lose its follow-up or half-cancel an order (A3, A4)

**Files:**
- Modify: `models/rs_waybill_actions.py:530-533` (the `write` before `cr.commit()` in `action_refuse_waybill`)
- Modify: `models/stock_picking.py:138` (`isolate`)
- Test: `tests/test_cancel_cascade.py` (add to the existing class)

**Interfaces:**
- Consumes: `rs_cancel_cascade` (`'pending'`/`'done'`), `_cascade_cancel_delivery()` (`rs_waybill.py:2540`), context key `rs_order_cancel` (set by `SaleOrder._action_cancel`, `sale_order.py:21-24`).

- [ ] **Step 1: Write failing tests:**
  - `test_pending_is_saved_with_the_cancel`: seller waybill, active, linked to an open delivery; patch `refuse_waybill` → `1`; patch `cr.commit` to record `waybill.rs_cancel_cascade` at the moment of the commit → the recorded value is `'pending'`.
  - `test_done_delivery_gets_no_pending`: same with a done delivery → the recorded value is `False` (the "goods already delivered" activity still appears once).
  - `test_order_cancel_stops_on_a_refusal`: an SO with 2 deliveries, each with an active waybill; `refuse_waybill` succeeds for the first and raises `UserError` for the second; `order.action_cancel()` → `assertRaises(UserError)`; then make the second succeed and call `action_cancel()` again → order `'cancel'`, both deliveries `'cancel'`.
- [ ] **Step 2: Run** `/rs_waybill:TestCancelCascade`. Expected: the 3 new tests FAIL.
- [ ] **Step 3: Implement:**
  - In the refuse `write`: add `'rs_cancel_cascade': 'pending'` when `waybill_direction == 'seller'` and `picking_id.state not in ('done', 'cancel')`.
  - In `stock_picking.action_cancel`: `isolate = len(targets) > 1 and not self.env.context.get('rs_order_cancel')`.
- [ ] **Step 4: Run** the class, then the full suite. `test_batch_cascade` must still pass, because a batch cancel without the order context still isolates.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 6: An Adjustment RS.GE refused is not lost or applied wrong (A6)

**Files:**
- Modify: `models/rs_waybill.py` `_compute_line_diff(self, snapshot_json=None)` (reads `snapshot_json or self.edit_snapshot_json`); `_apply_rs_goods_diff_auto`/`_rs_apply_goods_diffs` pass the snapshot as a parameter instead of writing `edit_snapshot_json`
- Modify: `models/rs_waybill_actions.py:207` (keep an existing `edit_snapshot_json`)
- Modify: `models/rs_waybill_sync.py` (sync, drift) and `rs_waybill_actions.py` Update: skip the goods step while `edit_snapshot_json` is set, and post one chatter line saying the RS.GE goods change waits for the Adjustment
- Modify: `views/rs_waybill_views.xml` (warning banner while `edit_snapshot_json` is set and not in `edit_mode`: "An Adjustment was not sent to RS.GE. Open Adjustment and submit it again.")
- Test: `tests/test_adjustment_pending.py` (new)

**Interfaces:**
- Produces: `RsWaybill._compute_line_diff(snapshot_json: str | None = None) -> list[dict]`. Other callers are unchanged.
- From now on, `edit_snapshot_json` means only "an Adjustment is open or was refused".

- [ ] **Step 1: Write failing tests** (completed waybill on a done delivery, as in `test_done_delivery_decrease.py`):
  - `test_reopening_keeps_the_first_snapshot`: `action_edit_waybill()`; set the line to 8 (the popup save); `action_edit_waybill()` again → `json.loads(edit_snapshot_json)[0]['quantity'] == 10`.
  - `test_resubmit_after_refusal_lowers_the_delivery`: as above, then patch `save_waybill` to return `{}` and `get_full_waybill` to return `(None, [])`; `action_submit_edit_to_rs()` → the delivery move quantity is 8.
  - `test_sync_does_not_overwrite_an_open_adjustment`: snapshot set and the line at 8; call `_sync_goods_lines` with RS goods saying 10, through the sync path → the line is still 8 and a chatter message mentions the Adjustment.
- [ ] **Step 2: Run** `/rs_waybill:TestAdjustmentPending`. Expected: all 3 FAIL.
- [ ] **Step 3: Implement** the four file changes above.
- [ ] **Step 4: Run** the class, then the full suite. `test_rs_goods_atomic`, `test_rs_line_matching` and `test_done_delivery_*` must still pass.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

### Task 7: Save cannot create two waybills on RS.GE (A7)

**Files:**
- Modify: `models/rs_waybill_actions.py` `action_save_to_rs` (first lines, before `service.save_waybill` at `:122`)
- Test: `tests/test_save_lock.py` (new)

**Interfaces:**
- Consumes: core `lock_for_update()` (`odoo/orm/models.py:5056`; raises `LockError` when another transaction holds the row).

- [ ] **Step 1: Write failing test** `test_save_refuses_while_another_save_runs`: patch `lock_for_update` on the waybill class to raise `odoo.exceptions.LockError`; patch `save_waybill` → `assertRaises(UserError)` with "already being saved", and `save_waybill` is not called.
- [ ] **Step 2: Run** `/rs_waybill:TestSaveLock`. Expected: FAIL (`save_waybill` is called).
- [ ] **Step 3: Implement:** `try: self.lock_for_update() except LockError: raise UserError(_("Waybill %s is already being saved. Wait a moment and reload."))`, before any RS call when `not self.rs_internal_id`.
- [ ] **Step 4: Run** the class, then the full suite.
- [ ] **Step 5: Stop.** Leave uncommitted; report.

---

## Plans 2–5 (written when Plan 1 is accepted)

| Plan | Items | Decisions needed first |
|---|---|---|
| 2 Speed | B11 skip unchanged waybills in sync, B12 drift scope, B13 one dashboard request, email batching | **B12:** stop re-checking completed waybills after N days? |
| 3 What users see | D18 Goods/Excise split (two filtered fields), D19 Markup in 14 messages, D20 button visibility + reconfirm banner, D21 readable RS.GE error texts, D22 dead Settings switches | **D22:** remove the switches, or make them work? |
| 4 Security | C14 sync callable only by cron/admin, C15 company on product mappings, C16 records in the document's company, C17 company required, a Waybill Manager group (delete, excise codes) | **Groups:** who is "Waybill Manager"? |
| 5 Cleanup | E23 one "apply RS.GE data" method, E24 dead code, E25 shared builders, E26 split `rs_waybill.py`, E27 missing tests, manifest depends | none; each item as its own change |
