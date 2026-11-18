# Bank Channels (`gec_bank`) — Developer guide

For a developer who knows Odoo 20 but not this module and has to change it.
User guide: [README.md](README.md).

## Purpose and facts

The shared base of the Georgian bank integrations (`basis_bank`, `tbc_bank`,
`bog_bank`) and the contract those modules implement for the consumer
`gec_payroll_bank`. It holds what every bank client needs and none of them should
write twice: row writes that survive a rollback, the audit log on its own cursor,
secret redaction, the guard on bank-only fields, the approver, connection and OAuth
mixins, the channel hooks, and one transfer flow on `account.payment` that a bank opts
into by method code. The module's code is bank-agnostic: every bank-specific fact arrives through
a hook, a method code or a field a bank module adds (a few docstrings name the banks as
examples; no code does).

| | |
|---|---|
| Depends | `account` (payments, statements, journal entries), `account_batch_payment` (batches and the file-method registry), `gec_localization` (the Georgian chart with the Outstanding Payments account) |
| New models | 7, all abstract: `gec.bank.service`, `gec.bank.sendable`, `gec.bank.guard.mixin`, `gec.bank.approval.mixin`, `gec.bank.connection.mixin`, `gec.bank.oauth.mixin`, `gec.bank.api.log.mixin` |
| Extended models | `account.payment` (also inherits the guard mixin), `account.batch.payment` (guard mixin), `account.payment.method.line`, `account.journal`, `account.bank.statement.line`, `account.move`, `account.move.line`, `account.payment.register`, `res.partner.bank` |
| Fields added to core models | `account.payment`: `gec_bank_code` (computed, not stored), `gec_bank_state` (stored compute), `gec_bank_reference`, `gec_bank_request_id`, `gec_bank_error`, `gec_bank_approved_by`, `gec_bank_approved_date`, `gec_bank_confirmed_source`; `account.bank.statement.line`: `gec_bank_match_keys` |
| Constraints | Two SQL uniques on `account.payment`: `(company_id, payment_method_id, gec_bank_reference)` and `(company_id, payment_method_id, gec_bank_request_id)`; NULLs do not collide |
| Hooks | `@api.ondelete` on `account.payment._unlink_except_at_bank` and on `gec.bank.connection.mixin._unlink_except_logged`; `@api.autovacuum` on `_gc_gec_bank_api_logs`; `default_get`, `create` and `write` overrides on the guard; `create` overrides on `account.payment.method.line`, `account.journal` and `account.bank.statement.line`; `write` overrides on `account.payment`, `account.journal` and `res.partner.bank` |
| Crons | none of its own; the autovacuum is Odoo's base cron |
| Controllers | none |
| Data files | `views/account_payment_views.xml`: two inherited payment views (the form header carries `gec_bank_code` and `gec_bank_state` invisible, so a bank's buttons can use them; the list carries the optional **Bank State** column); `views/account_journal_dashboard_views.xml`: the bank's mark behind a bank journal's Accounting dashboard card |
| Assets | `static/src/scss/account_journal_dashboard.scss` in `web.assets_backend`, its `.dark.scss` in `web.assets_web_dark` |

## Architecture

```text
tbc_bank, bog_bank                        basis_bank
buttons, bank calls, bank answers         own flow, own fields, own buttons
   │ call _gec_bank_<verb>(code)             │ use the guard, the durable
   │ answer the hooks for their code         │ service and the mixins
   ▼                                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│ gec_bank                                                               │
│  account.payment              shared transfer flow, write() rules,     │
│                               undo fence                               │
│  account.payment.method.line  opt-in, channel hooks, handoff map       │
│  account.journal              API lines, match key fields              │
│  account.bank.statement.line  match keys, statement confirmation       │
│  account.batch.payment        guard on the bank's batch fields         │
│  mixins                       guard, approval, connection, oauth,      │
│                               api log, sendable                        │
│  gec.bank.service             durable claim and write, audit log       │
└────────────────────────────────────────────────────────────────────────┘
   ▲
   │ calls the channel hooks, reads the handoff state
gec_payroll_bank (Pay Salaries)
```

The shared transfer flow follows the pattern of core's `payment.transaction` and its
provider code: one set of fields and generic lifecycle methods in `gec_bank`, per-bank
code behind hooks that each bank answers for its own method code (`gec_bank_code`).
Basis Bank does not use the shared fields: it keeps `basisbank_state` and its own
buttons, and shares the guard, the durable service, the mixins and the undo fence only
(see "Basis Bank and the shared flow").

## File map

| File | What it holds |
|---|---|
| `__manifest__.py` | name, version 20.0.1.1.0, depends, the two view files, the dashboard assets |
| `__init__.py` | imports `models` |
| `models/__init__.py` | import order: sendable, guard, service, approval, connection, oauth, api log mixins, then the nine account models |
| `models/gec_bank_service.py` | `GecBankService`: durable claim and write on an independent cursor, `_log_vals`/`_write_log`, `_parse_json` / `_first_key`, redaction |
| `models/gec_bank_sendable.py` | `GecBankSendable`: `_gec_bank_notify` display_notification + close-dialog action |
| `models/gec_bank_guard_mixin.py` | `GecBankGuardMixin`: `GEC_BANK_WRITE_TOKEN`, protected fields, `_gec_bank_internal_write`, default_get filter, create/write refusal |
| `models/gec_bank_approval_mixin.py` | `GecBankApprovalMixin`: approver, delegates, name compute, constraint, `user_can_approve`, `_gec_bank_check_approver` |
| `models/gec_bank_connection_mixin.py` | `GecBankConnectionMixin`: processing mode, state, `allow_self_approval`, last error, log retention, label and unusable-connection errors, delete refusal, `action_view_logs` |
| `models/gec_bank_oauth_mixin.py` | `GecBankOauthMixin`: cached bearer token and expiry, `token_is_valid`, `store_token`, `clear_token` |
| `models/gec_bank_api_log_mixin.py` | `GecBankApiLogMixin`: log row fields, vacuum domain hook, `@api.autovacuum` garbage collection |
| `models/account_journal.py` | `_gec_bank_ensure_api_lines`, `_gec_bank_match_key_fields`, `_gec_bank_dashboard_logo`, `_fill_bank_cash_dashboard_data`, `_gec_bank_default_outstanding_account` |
| `models/account_move.py` | `button_draft` / `button_cancel` overrides running the at-bank fence on `origin_payment_id` |
| `models/account_payment.py` | `GEC_BANK_BYPASS_KEY`, `GEC_BANK_STATES`, `GEC_BANK_TRANSFER_FIELDS`, the `gec_bank_*` fields, state groups, the hooks, the lifecycle methods, the fence, `write`, `_gec_bank_release_bank` |
| `models/account_batch_payment.py` | Applies the guard mixin to `account.batch.payment` |
| `models/account_payment_method_line.py` | `bic_prefix`, `GEC_BANK_HANDOFF_STATES`, `GEC_BANK_TRANSFER_HANDOFF`, `GEC_BANK_CHANNEL_DOMAIN`, the channel hooks and checks, the handoff map, `create` fill |
| `models/account_move_line.py` | `_gec_bank_recipient_account`: recipient account at the paying bank by BIC prefix |
| `models/account_payment_register.py` | `_get_line_batch_key` override routing into that account via context BIC |
| `models/account_bank_statement_line.py` | `gec_bank_match_keys`, `_gec_bank_auto_match`, `_gec_bank_matches_payment`, `_gec_bank_reconcile_payment` |
| `models/res_partner_bank.py` | `write`: the journal bank-change guard for a BIC or account number edited on the bank account |
| `views/account_payment_views.xml` | Payment form header fields and the optional Bank State list column |
| `views/account_journal_dashboard_views.xml` | Inherits `account.account_journal_dashboard_kanban_view`: the `o_gec_bank_logo` element at the top of a card with `gec_bank_logo` |
| `static/src/scss/account_journal_dashboard.scss`, `.dark.scss` | The mark's place (lower right, below the amounts) and opacity (8% light, 12% dark); `isolation` on the card keeps it under the text and graph |
| `tests/__init__.py`, `tests/test_gec_bank.py` | Imports; the plumbing tests (see Tests) |
| `i18n/ka_GE.po` | Georgian translations |

## Flow 1: the durable claim and write

The primitives every bank uses. TBC and Bank of Georgia reach them through
`_gec_bank_reserve_send` and `_gec_bank_write_result` (Flow 2); Basis Bank wraps them in
its own methods.

1. `AccountPayment._gec_bank_check_sendable` — refuses draft payments (no posted
   entry) and payments no longer Paid (would pay twice).
2. `GecBankService._reserve_send(record, vals, state_field, blocked_states)` —
   claims the payment with one conditional UPDATE on its own cursor, writing the
   request id and sending state unless the state is blocked. Durable: a crash
   before the bank answers cannot roll the request id back; atomic: a double
   click finds no row. On a lock timeout it raises a UserError.
3. The bank module calls the bank (outside this module).
4. `AccountPayment._gec_bank_mirror_vals(outcome)` — maps the answer: `held`
   sets `is_sent`; `rejected` from `paid` sets `state='rejected'` and clears
   `is_sent`; executed changes nothing.
5. `GecBankService._durable_write(record, vals)` — writes the outcome on its own
   cursor. On a 2s lock timeout it falls back to an ORM write that carries the guard
   token and returns False (not durable, logged).
6. `AccountPayment._gec_bank_after_durable(vals)` — schedules the batch `state`
   and `amount_residual` recompute, because the durable write bypassed the ORM.

`_durable_columns` guards both writes: every key must be a plain stored column,
or it raises.

## Flow 2: the shared transfer flow (`account.payment`)

### Fields and the opt-in

| Field | Notes |
|---|---|
| `gec_bank_code` | Computed, not stored: the method code of an outbound payment whose channel opts in, else False. Depends on `payment_type` and `payment_method_line_id`; a bank that reads more in its opt-in adds the dependency by overriding `_compute_gec_bank_code` (TBC and BOG add `journal_id.is_tbc` / `is_bog`) |
| `gec_bank_state` | Stored compute, `readonly`, `tracking`, indexed. Starts `pending` when `gec_bank_code` is set; a state the flow already wrote is kept; a leftover `pending` clears when the payment leaves the flow |
| `gec_bank_reference` | The bank's own id for the transfer |
| `gec_bank_request_id` | Our id, sent with every attempt so the bank can refuse a second one |
| `gec_bank_error` | Last error text |
| `gec_bank_approved_by`, `gec_bank_approved_date` | The approval |
| `gec_bank_confirmed_source` | `statement`, `status` or `manual` |

All are `readonly=True, copy=False` and protected by the guard (see "The guard mixin").

**The opt-in** is `account.payment.method.line._gec_bank_transfer_flow()`: False in
`gec_bank`; a bank returns True for its own method code when the journal belongs to it
(TBC: `tbc_transfer` on a TBC journal; BOG: `bog_transfer` on a BOG journal). A channel
that does not opt in has `gec_bank_code` False and no Bank State.

### States and state groups

`GEC_BANK_STATES`: `pending`, `awaiting_approval`, `approved`, `sending`, `sent`,
`confirmed`, `failed`, `unknown`. A bank adds states with `selection_add` (with an
`ondelete` that maps each added state back to a shared one, so uninstalling the bank is
safe; BOG adds `awaiting_confirmation` and `created`) and places them in
`_gec_bank_state_groups()`, the single place a state gets its meaning. The method
returns a fresh dict of fresh sets per call, so an override adds to them with `super()`.

| Group | Base members | What reads it |
|---|---|---|
| `at_bank` | `sending`, `sent`, `confirmed` | `_gec_bank_at_bank` (with `unknown`), `_gec_bank_reserve_send` (blocked states, with `unknown`), `_gec_bank_release_bank`, `_gec_bank_approval_kept_states`, `_gec_bank_revoke_approval` |
| `held` | `sent`, `confirmed` | `_gec_bank_count_outcomes` (counted as sent), `_gec_bank_payment_state_vals` (`is_sent`) |
| `open` | `sent`, `unknown` | `_gec_bank_poll_status`, `_gec_bank_auto_match` |
| `uncertain` | `sending`, `unknown` | `_gec_bank_count_outcomes` |
| `in_approval` | `awaiting_approval`, `approved` | `_gec_bank_revoke_approval`, `_gec_bank_approval_kept_states` |

### Hooks each bank answers

A bank guards on its own code and delegates the rest to `super()`; two hooks
(`_gec_bank_label_for`, `_gec_bank_result_columns`) are `@api.model`.

| Hook | Default | What the bank returns |
|---|---|---|
| `_gec_bank_label_for(code)` | "Bank" | Its translated name for `code`, used in every message |
| `_gec_bank_connection_record()` | empty `gec.bank.connection.mixin` | The connection of the payment's journal, `sudo`, possibly empty |
| `_gec_bank_send_one()` | raises "This payment is not sent through a bank integration." | Sends one payment; returns True or a notification action |
| `_gec_bank_refresh_one()` | None | Asks the bank for the status and records it |
| `_gec_bank_new_request_vals()` | `{}` | What a claim writes: the request id (minted once, reused on every retry) and anything else to reserve |
| `_gec_bank_payload_fields()` | `frozenset()` | The fields the bank's instructions are built from; a change voids the approval |
| `_gec_bank_check_instructions()` | None | Raises for what the bank is documented to reject, and for a channel set up wrong |
| `_gec_bank_result_columns()` | `gec_bank_state`, `gec_bank_reference`, `gec_bank_error`, `gec_bank_confirmed_source`, `gec_bank_approved_by`, `gec_bank_approved_date`, `is_sent`, `state` (the request id is written by the claim, not by a result) | Union with the bank's own columns that a result may write |
| `_gec_bank_state_groups()` | the table above | Union with the bank's own states |
| `_gec_bank_protected_fields()` | `GEC_BANK_TRANSFER_FIELDS` | Union with the bank's own bank-only fields |
| `_gec_bank_at_bank()` | state in `at_bank` or `unknown` | `super() or` its own states, for a bank with its own flow |

### The lifecycle methods the banks' buttons call

A bank's public button is one line: it calls the generic method with its own method
code. The method filters or refuses payments of any other bank, so a button only acts
on its own bank's payments, also when called over RPC.

| Method | What it does |
|---|---|
| `_gec_bank_submit_approval(code)` | Own `pending` payments → `awaiting_approval`. Refuses an empty selection, a connection that is not in `odoo_approve` mode, a draft or no-longer-Paid payment (`_gec_bank_check_sendable`) and what `_gec_bank_check_instructions` refuses; follows and mentions the approvers |
| `_gec_bank_approve(code)` | Own `awaiting_approval` payments → `approved`, after the connection's `approval_id._gec_bank_check_approver`; stamps approver and date |
| `_gec_bank_send_transfers(code)` | One payment: `_gec_bank_check_own` then `_gec_bank_send_one`. Several: `_gec_bank_send_each` then `_gec_bank_report_sends` |
| `_gec_bank_send_each(code)` | Each payment in its own savepoint; returns the payments whose send ran, the refusals as `payment: reason` lines and the last notification |
| `_gec_bank_report_sends(code, done, errors, notice)` | The notification: counts from `_gec_bank_count_outcomes`, refusals named. A send that returns normally is not a success; the resulting states decide |
| `_gec_bank_check_transfer(code)` | Before any claim: write access, own bank, not `unknown`, not `failed`, not `is_sent`, approved where the mode is `odoo_approve` (`_gec_bank_check_approved`), `_gec_bank_check_sendable` |
| `_gec_bank_check_approved` | The approver must still be an approver or delegate; otherwise the approval is withdrawn durably (back to `pending`) and the send is refused |
| `_gec_bank_reserve_send` | The claim: `_gec_bank_new_request_vals` plus `gec_bank_state='sending'`, through `GecBankService._reserve_send`, blocked by the `at_bank` states and `unknown` |
| `_gec_bank_write_result(vals)` | Records a bank answer durably (below) |
| `_gec_bank_payment_state_vals(state)` | Core fields for a state: `held` → `is_sent`; `failed` → `state='rejected'` |
| `_gec_bank_confirm_manual(code)` | Own `sent` payments → `confirmed`, source `manual` (never `unknown` or BOG's unsigned `created`); bank User group only |
| `_gec_bank_check_user(code)` | Refuses a money action (send, reset, recover, cancel, confirm) outside the bank's User group (`_gec_bank_user_group_for`) |
| `_gec_bank_release_claim(state, error)` | A 401/429 answer to a send: back to the state before the claim, not Failed |
| `_gec_bank_refresh_status(code)` | Calls `_gec_bank_refresh_one` on each own payment |
| `_gec_bank_poll_status(code, connection_model, order)` | The cron body: own payments in the `open` group with a reference, only for companies with an `active` connection, at most `GEC_BANK_STATUS_POLL_LIMIT` per run in `order`, each in a savepoint, failures logged |
| `_gec_bank_revoke_approval(reset_state)` | Voids an approval (see `write`) |
| `_gec_bank_own(code)`, `_gec_bank_check_own(code)` | Filter to, or refuse anything but, payments whose `gec_bank_code` is `code` |
| `_gec_bank_connection()`, `_gec_bank_processing_mode()` | The usable connection (missing or blocked raises, through `_gec_bank_unusable_errors`); the connection's processing mode, `odoo_approve` without one |

### The send

1. The bank's button calls `_gec_bank_send_transfers(code)` (above).
2. The bank's `_<bank>_send_one` runs the shared checks first (`_gec_bank_check_transfer`,
   `_gec_bank_connection`, its own instruction check), so a configuration or data error
   fails before the claim.
3. `_gec_bank_reserve_send` claims the payment durably (Flow 1) and returns the claim.
4. The bank calls its API and builds `vals` from the answer.
5. `_gec_bank_write_result(vals)`: refuses any column outside `_gec_bank_result_columns`
   (`ValueError`); adds `_gec_bank_payment_state_vals`; clears the approval when the new
   state is not in `_gec_bank_approval_kept_states` (approved-and-unsent, or at the bank);
   writes durably; schedules the batch recompute; and posts the chatter lines
   ("%(bank)s state: old → new", and the Rejected notice) only when the write was durable,
   because the durable write skips tracking and the non-durable fallback is tracked by the ORM.

### Approval

1. `_gec_bank_submit_approval` and `_gec_bank_approve` write the state through
   `_gec_bank_internal_write`.
2. `GecBankApprovalMixin._gec_bank_check_approver(record, allow_self_approval, bank_label)`:
   the user must be the approver or a delegate of the connection, and must not be
   `record.create_uid` unless the connection's `allow_self_approval` is on. Basis Bank calls
   it too.
3. At send, `_gec_bank_check_approved` re-checks the approver.
4. In `write`, a change to a field in `_gec_bank_payload_fields()` calls
   `_gec_bank_revoke_approval('pending')` before the write: payments in the `in_approval`
   group go back to `pending` with the approver cleared and a chatter note; other payments
   outside `at_bank` that carry an approver lose it quietly; payments at the bank keep it as
   the record of who released the money.

### The bank-change rule

`write` records `gec_bank_code` before the super call when `payment_method_line_id`,
`journal_id` or `payment_type` is written. After it,
`_gec_bank_release_bank(old_codes)` runs for each payment whose code changed:

- A payment in an `at_bank` state or `unknown` raises "... is at the bank, or may be, so
  it cannot move to another bank or payment method." (the transaction rolls back).
- Otherwise, if the payment carries any transfer value, the old state, reference,
  request id and approver are posted to the chatter, then the transfer fields are cleared
  through `_gec_bank_internal_write` and the state becomes `pending` (or False when the
  payment is off the flow). The new bank never reuses the old one's id,
  reference or approval.
- The journal's side: `account.journal.write` (bank account, number, BIC or type) and
  `res.partner.bank.write` (`bank_bic`, `account_number`) collect the journal's payments at
  the bank before the write and call `_gec_bank_check_bank_kept` after it, which raises
  "These payments are at the bank, or may be, so their journal's bank cannot change: ...".
  An account number alone can change the bank: saving a Georgian IBAN fills its BIC
  (gec_localization `_sanitize_vals`).

## Flow 3: statement matching

1. A bank's statement import writes `gec_bank_match_keys` on each line it creates: the
   bank's references for the movement, space-separated.
2. `AccountBankStatementLine.create` calls `_gec_bank_auto_match` on the created lines
   that carry keys.
3. Per journal, `account.journal._gec_bank_match_key_fields()` names the payment fields
   the keys are matched on (TBC: `gec_bank_reference`, `gec_bank_request_id`; BOG:
   `gec_bank_reference`, `bog_document_no`). A journal that answers nothing is skipped.
4. One search per journal: payments of that journal in the `open` group, or `confirmed`
   and not `is_matched`, whose key fields hit any key. The first payment per key wins.
5. For each line, for each key: when a payment is found, is not already matched in this
   run and `_gec_bank_matches_payment` accepts the line, a payment not yet `confirmed` is
   written (`_gec_bank_internal_write`) to `confirmed`, source `statement`, error cleared,
   plus `_gec_bank_payment_state_vals('confirmed')`; then `_gec_bank_reconcile_payment`.
6. `_gec_bank_matches_payment` accepts a line only as a debit for the payment's amount in
   its currency (converting the journal currency at the line date; the foreign amount for
   a matching multi-currency line). A reference alone is never enough.
7. `_gec_bank_reconcile_payment` matches the payment's open Outstanding lines through
   `set_line_bank_statement_line` as superuser, the call core's own end-to-end matching
   makes, because the statement importer may lack reconciliation rights. Core then marks the
   payment matched, its batch Reconciled and the bill paid.

Basis Bank keeps `_basisbank_auto_match` on its own states.

## Flow 4: the channel hooks and the handoff map

`AccountPaymentMethodLine` is the contract with the consumer. Two accumulation orders exist:

- **super first, then guard on `self.code`:** `_gec_bank_check` (blocking
  messages per run), `_gec_bank_payment_vals` (values for one created payment),
  `_gec_bank_batch_vals` (extra batch vals), `_gec_bank_extra_config_errors`,
  `_gec_bank_handoff_map`, `_gec_bank_transfer_handoff_states`.
- **guard on `self.code` first, then super:** `_gec_bank_transfer_flow`,
  `_gec_bank_channel_kind`, `_gec_bank_handoff_state`.

`_gec_bank_config_errors` is sealed: core checks plus extras, a bank cannot skip
the base. `_gec_bank_core_config_errors` refuses non-outbound lines, non-bank
journals, a missing / cash / non-reconcilable / journal-own Outstanding account,
and an API channel whose journal has no IBAN. A bank adds its connection check with
`connection._gec_bank_unusable_errors(company)`, which the payment-side
`_gec_bank_connection` also uses.

**The handoff map.** The consumer asks `_gec_bank_handoff_state(batch)` where a batch
stands, one of `GEC_BANK_HANDOFF_STATES`.

1. For a channel that opts into the transfer flow, the default builds the set
   `_gec_bank_transfer_handoff_states(batch)`: each member payment's `gec_bank_state`
   looked up in `_gec_bank_handoff_map()` (an unmapped state counts as `uncertain`).
2. `_gec_bank_merge_handoff_states` folds the set: failed wins only when all failed
   (otherwise `partial`), then `uncertain`, `prepared`, `pending`, `transmitted`;
   `confirmed` requires every payment confirmed.
3. A channel outside the flow answers `prepared` while the batch is draft, else
   `transmitted`. A bank with its own flow overrides `_gec_bank_handoff_state` (Basis).

`GEC_BANK_TRANSFER_HANDOFF` maps `pending`, `awaiting_approval`, `approved` →
`prepared`; `sending`, `unknown` → `uncertain` (a send ends within about a minute, so a
payment still sending when the watchdog looks crashed mid-call); `sent` → `transmitted`;
`confirmed` → `confirmed`; `failed` → `failed`. A bank extends the map through
`_gec_bank_handoff_map` (BOG: `awaiting_confirmation` → `prepared`, `created` →
`pending`) and the set through `_gec_bank_transfer_handoff_states` (BOG adds a batch-level
`sending` or `unknown` as `uncertain`).

`_gec_bank_handoff_state` must not do network I/O: it runs in a cron over every open batch.

## Flow 5: the undo fences

All undo paths converge on one check:

- `AccountPayment.action_draft`, `action_cancel`, `action_reject` (core's Reject: a Rejected payment the
  bank still holds could never be sent or unmarked again),
  `AccountMove.button_draft`, `button_cancel`, `_reverse_moves`,
  `AccountPayment._unlink_except_at_bank` (`@api.ondelete`) each call
  `AccountPayment._gec_bank_check_not_at_bank`.
- The check skips when `GEC_BANK_BYPASS_KEY` is in the context (core's statement
  unmatching), filters payments through `_gec_bank_at_bank` (the `at_bank` states and
  `unknown` for a payment on the shared flow; a bank with its own flow extends it), and
  raises a UserError naming the payments.

`account.payment.write` is overridden for the approval and bank-change rules (Flow 2),
not for the fence: the fence runs on the buttons and the delete.

## Flow 6: channels, journals and the recipient account

1. `AccountPaymentMethodLine.create` calls `_gec_bank_fill_outstanding`.
2. For outbound API channels without an account, the fill reads
   `AccountJournal._gec_bank_default_outstanding_account` (chart template ref)
   and writes `payment_account_id`. Runs at create time only.
3. `AccountJournal.create` and `write` (when `bank_account_id`, `bank_account_number`,
   `bank_bic` or `type` is written) call `_gec_bank_ensure_api_lines`. Core builds the
   method lines before it links the bank account (and so the BIC) and recomputes them only
   when the type or currency change, so a journal created in one save with its bank's BIC
   would miss the bank's line. For each bank journal the step takes
   `_default_outbound_payment_methods()` minus the lines it already has, keeps the methods
   whose channel kind is `api`, and creates their lines. Only API channels are added.
   Because the same step runs on a later write of those fields, a removed API line returns
   when one of them is edited.
4. `AccountMoveLine._gec_bank_recipient_account(journal_bic)` picks the
   commercial partner's account at the paying bank by `bic_prefix` (8 chars;
   Odoo 20 has no bank records), excluding other-company accounts.
5. `AccountPaymentRegister._get_line_batch_key` overrides core's batch key with
   that account when the context carries `gec_bank_journal_bic` and the BIC
   matches.
6. `AccountJournal._fill_bank_cash_dashboard_data` (core's dashboard filler) adds
   `gec_bank_logo` = `_gec_bank_dashboard_logo()` to each bank journal's dashboard data.
   The dashboard view draws that image behind the card, except while the card shows
   Odoo's bank-connection grid (`bank_unconfigured` and `display_connect_bank_in_dashboard`).

## Flow 7: the audit log and its vacuum

1. `GecBankService._log_vals` builds the shared row values with `_dump_redacted`
   (request) and `_dump_redacted_text` (response); both go through
   `_redact_data` / `_redact_text` against the bank's `_gec_bank_sensitive_keys`.
2. `GecBankService._write_log` creates the row on its own cursor so a rollback
   of the calling transaction cannot erase the error it describes. A failed
   create is logged, never raised.
3. `GecBankApiLogMixin._gc_gec_bank_api_logs` (`@api.autovacuum`) deletes rows
   older than each connection's `log_retention_days`, minus the rows the bank's
   `_gec_bank_log_vacuum_domain` protects, in batches of 1000.

## The guard mixin

`gec.bank.guard.mixin` (inherits `gec.bank.sendable`, which is where `_gec_bank_notify`
comes from) is applied to `account.payment` and `account.batch.payment`.

- **Protected fields.** `_gec_bank_protected_fields()` returns the fields only a bank flow
  writes. `gec_bank` adds `GEC_BANK_TRANSFER_FIELDS` on the payment and nothing on the batch;
  each bank unions in its own (TBC `tbc_bank_status`; BOG answer fields on the payment and
  its batch-level state and package fields; Basis its state, approval and answer fields on
  payment and batch).
- **Defaults.** `default_get` drops a `default_<field>` context key and a saved default
  (`ir.default`, personal or company-wide) of a protected field and keeps the field's own
  default (a batch still starts in Draft). Core adds these defaults after `create` sees its values, so without this a URL
  or a saved default could preset the approver.
- **The refusal.** `create` and `write` call `_gec_bank_check_protected(vals)`: a protected
  field in the values raises "These fields are set by the bank integration and cannot be
  changed directly: ..." listing their labels.
- **The token.** `GEC_BANK_WRITE_TOKEN` is a Python `object()` compared with `is`, carried in
  the context as `gec_bank_write_token`. A Python object cannot arrive over RPC or in an
  import, so only code holding it can write the fields.
- **`_gec_bank_internal_write(vals)`** writes under the token for that one write. A bank
  flow writes protected fields only through it, or through `_gec_bank_write_result`. A
  context handed back to the web client must never carry the token.
- **`readonly=True`** on each protected field only guides the web client; the guard is the
  enforcement. A new protected field needs both.

## The connection, approval and OAuth mixins

- **`gec.bank.connection.mixin`** (company, `processing_mode`, `state`, `allow_self_approval`,
  `last_error_*`, `log_retention_days`; tracked). `_gec_bank_label()` returns `_description`;
  each bank returns its own translated name. `_gec_bank_unusable_errors(company)` returns
  the "No %(bank)s connection is configured for company %(company)s." text when the
  recordset is empty and "The %(bank)s connection is blocked. Contact the bank." when it
  is `blocked`. `_unlink_except_logged` (`@api.ondelete`) refuses to delete a connection
  that has `log_ids`; the concrete model must declare `log_ids`, and its log model's
  `connection_id` is `ondelete='restrict'`. `action_view_logs` reads the log model from
  `log_ids`.
- **`gec.bank.approval.mixin`** (primary approver, delegates, company, `active`): the
  constraint keeps the approver out of the delegates; `approver_user_ids` and
  `user_can_approve` answer who may approve; `_gec_bank_check_approver` is the maker-checker
  rule (not an approver: "You are not authorized to approve %s transfers."; the creator
  without `allow_self_approval`: "You created this transfer, so you cannot approve it...").
  The delegate relation table is per bank, so each bank model declares `delegate_ids` again.
- **`gec.bank.oauth.mixin`** (TBC and BOG connections): `access_token` and `token_expiry`
  readable by `base.group_system` only. `token_is_valid`, `store_token` and `clear_token` are
  `@api.private`: they write with `sudo()` and cannot be called over RPC. A token counts as
  valid until 60 seconds before its expiry, and `store_token` stores the expiry 60 seconds
  short of the lifetime the bank states.

## Basis Bank and the shared flow

Basis Bank does not use `gec_bank_state` or the other `gec_bank_*` fields, the generic
lifecycle methods, `gec_bank_code` or `_gec_bank_transfer_flow`. It keeps `basisbank_state`,
its own approval fields and buttons, and `_basisbank_auto_match` for statements. It shares
the guard (its own protected fields through `_gec_bank_protected_fields`, written with
`_gec_bank_internal_write`), `_gec_bank_check_sendable`, `_gec_bank_mirror_vals`,
`_gec_bank_after_durable`, the durable service, `_gec_bank_at_bank` (extended with its own
states), `_gec_bank_check_approver`, `_gec_bank_unusable_errors`, the three connection,
approval and log mixins, and the channel hooks including its own `_gec_bank_handoff_state`.

## Data

`views/account_payment_views.xml` loads two inheritance views on core's payment form and
list, with no `noupdate` block. The form view adds `gec_bank_code` and `gec_bank_state`
(invisible) to the header so a bank's own header buttons can use them in `invisible`
expressions. The list view adds one `gec_bank_state` badge column after `state`, optional and
hidden by default (`optional="hide"`): green for `confirmed`, blue for `approved`, red for
`failed` and `unknown`, and a warning colour for every state not named in those decorations
and not `pending`. A bank adds no list column of its own.

An upgrade reloads the views and the Python; it changes no business data.

## Guards and invariants

- **Never UPDATE after a durable write.** Under REPEATABLE READ PostgreSQL
  refuses, and Odoo re-runs the whole request — which re-sends a transfer. The
  docstring of `_durable_write` states the rule; the values go into the cache
  only.
- **A transaction that claimed durably must not write the row through the ORM**
  for the same reason. Results go through `_gec_bank_write_result`.
- **Only the bank flow writes a protected field**, through `_gec_bank_internal_write` or
  the durable write. Everything else is refused by the guard.
- **A new bank column written by a result goes in `_gec_bank_result_columns`** and must be
  a plain stored column, or `_gec_bank_write_result` raises.
- **A state means what `_gec_bank_state_groups` says.** A bank state missing from the
  groups is invisible to the fence, the polling, the counts and the approval rules.
- **The at-bank fence covers "may hold it".** A sent payment without an answer
  must count as at the bank (`_gec_bank_at_bank`).
- **A button acts only on its own bank's payments**: it passes its method code to the
  generic method, which filters or refuses by `gec_bank_code`.
- **A send's success is read from the resulting states**, never from the call returning.
- **`_gec_bank_payment_vals` must not touch `_get_trigger_fields_to_synchronize()` nor
  `payment_method_line_id`.** The consumer raises if a bank returns one.
- **`_gec_bank_handoff_state` must not do network I/O.** It runs in a cron over every
  open batch.
- **The vacuum never deletes rows the bank's domain protects.** Rows that moved
  money are the audit trail.

## Security

| Model | Access |
|---|---|
| The seven mixins | Abstract; the concrete banks declare their own tables and rows |
| The extended models | no ACL change |
| `access_token`, `token_expiry` (OAuth mixin) | field groups `base.group_system` |

`sudo()` and `SUPERUSER_ID` uses, and why each is safe:

- `_write_log`: creates the log row as sudo on its own cursor; writing a log row
  must not be blocked by the caller's rights and cannot fail the send.
- `_gc_gec_bank_api_logs`: reads connections and deletes log rows as sudo, so
  the nightly cleanup runs whoever triggered it.
- `_gec_bank_reconcile_payment`: `SUPERUSER_ID` for `set_line_bank_statement_line`,
  because a statement importer without reconciliation rights must still match.
- `_gec_bank_check_approved`: reads the connection's approver rule as sudo; a payroll
  administrator needs no bank group to be checked.
- `store_token`, `clear_token`, `token_is_valid`: sudo, and `@api.private` so no RPC
  caller can reach them.
- `_gec_bank_connection_record` is answered by each bank as a sudo read of a
  configuration record, for the same reason.

The send, refresh and manual-confirm entry points call `check_access('write')` on the
payments first.

## Integration

- `gec_payroll_bank` depends on this module and drives the channel hooks
  (`_gec_bank_channel_kind`, `_gec_bank_config_errors`, `_gec_bank_check`,
  `_gec_bank_payment_vals`, `_gec_bank_batch_vals`, `_gec_bank_handoff_state`). It also
  overrides `_gec_bank_recipient_account` (super first) and reads `bic_prefix`,
  `GEC_BANK_HANDOFF_STATES` and `GEC_BANK_CHANNEL_DOMAIN`. It calls no send hook: Pay
  Salaries opens the list of created batches, and each batch is sent from its own form.
- `tbc_bank` and `bog_bank` depend on this module, opt in through `_gec_bank_transfer_flow`,
  answer the payment hooks for their method code, call the generic lifecycle methods from
  their buttons and crons, extend `_gec_bank_state_groups`, `_gec_bank_protected_fields`
  and `_gec_bank_result_columns`, and answer `_gec_bank_match_key_fields` on their journals.
- `basis_bank` depends on this module, overrides the channel hooks, and extends
  `_gec_bank_at_bank`, `_gec_bank_extra_config_errors` and `_gec_bank_log_vacuum_domain`.
- All three set `_gec_bank_log_model` / `_gec_bank_sensitive_keys` on their services, inherit
  the connection, approval and api-log mixins, and answer `_gec_bank_label`.
- The method names **are** the contract: renaming a hook breaks the consumer and
  the three banks. The context key `gec_bank_journal_bic`, `GEC_BANK_BYPASS_KEY` and the
  `gec_bank_*` field names are the same kind of contract.
- `GEC_BANK_CHANNEL_DOMAIN` (string) must mirror `_gec_bank_channel_domain`
  (Python) for view attributes.

## Tests

```bash
./odoo-bin -d <test-db> -i gec_bank --test-tags /gec_bank --stop-after-init
```

| File | Covers |
|---|---|
| `tests/test_gec_bank.py` | On a plain bank journal with no bank module: a double click cannot claim twice (`_reserve_send`); `_durable_write` refuses what is not a plain column; every undo path (payment buttons, entry buttons, delete) refuses an at-bank payment and `GEC_BANK_BYPASS_KEY` lets core's unmatching through; only a Paid payment passes `_gec_bank_check_sendable`; `_gec_bank_mirror_vals`; a statement debit for the exact amount matches and reconciles, a credit or another amount does not; an API channel gets core's Outstanding Payments account; channel setup errors; the handoff merge; a context key or personal default cannot preset a bank field, while a field's own default stays; an account number of another bank cannot take held payments off their bank |

The tests use `registry_test_mode`, so the durable cursors share the test transaction.
`gec_bank` has no channel that opts into the transfer flow, so the flow, the guard and the
cross-bank rules are tested in the bank modules: `bog_bank/tests/test_bank_isolation.py`
(each button refuses another bank's payment, a payment that changes bank starts clean, an
at-bank payment cannot change bank, nor can its journal by a new account number, Basis
payments stay out of the shared flow, one Bank
State column; it skips without `tbc_bank`), `basis_bank/tests/test_basis_protected_fields.py`
(the guard) and the bank modules' own suites. `gec_payroll_bank` exercises the handoff map
and the merge through each bank's adapter tests.

## Extending safely

A new bank that wants the shared flow:

1. **Opt in by method code.** Override `_gec_bank_transfer_flow` on the method line, guard
   on your code, return whether the journal is yours; override `_compute_gec_bank_code` to
   add the dependency it reads. `gec_bank` must not name your bank: no code constant, label
   or field of yours belongs in this module.
2. **Answer the payment hooks guarded on `gec_bank_code`** (`_gec_bank_label_for` on its
   `code` argument), delegating every other code to `super()`. Set-valued hooks
   (`_gec_bank_state_groups`, `_gec_bank_protected_fields`, `_gec_bank_result_columns`,
   `_gec_bank_at_bank`) call `super()` first and add.
3. **Make your buttons one-liners** that pass your method code to the generic
   `_gec_bank_*` method; keep your own work in `_gec_bank_send_one` and
   `_gec_bank_refresh_one`.
4. **Write bank answers through `_gec_bank_write_result`** and bank-only fields through
   `_gec_bank_internal_write`; list each such field in `_gec_bank_protected_fields` and, when
   a result writes it, in `_gec_bank_result_columns`; keep `readonly=True` on it.
5. **Add states with `selection_add` and an `ondelete`**, place them in
   `_gec_bank_state_groups` and extend `_gec_bank_handoff_map`.
6. **For statements**, answer `account.journal._gec_bank_match_key_fields` and write
   `gec_bank_match_keys` in the import.
7. **For the connection**, inherit the connection mixin (and the OAuth mixin for a bearer
   token), declare `log_ids`, return your name from `_gec_bank_label`, make the log's
   `connection_id` `ondelete='restrict'`, inherit the approval mixin and call
   `_gec_bank_check_approver` on approval.

For every bank, shared or not:

8. **Override the channel hooks with the right accumulation order** — super first for
   `_gec_bank_check`, `_gec_bank_payment_vals`, `_gec_bank_batch_vals`,
   `_gec_bank_extra_config_errors`; guard on `self.code` first for
   `_gec_bank_channel_kind`, `_gec_bank_handoff_state`.
9. **Never return a trigger field or `payment_method_line_id` from
   `_gec_bank_payment_vals`**, or a caller-owned key from `_gec_bank_batch_vals` — the
   caller raises.
10. **Keep the durable discipline** — after `_durable_write`, always call
    `_gec_bank_after_durable` for `is_sent`/`state` values.
11. **List every secret key in the bank's `_gec_bank_sensitive_keys`** — keys not
    listed are logged in clear.
12. **Protect money-movement log rows in `_gec_bank_log_vacuum_domain`** — the
    default keeps everything, but a bank that overrides it must not let transfer
    rows age out.
13. **For the dashboard mark**, answer `account.journal._gec_bank_dashboard_logo` for the
    journals of your BIC with the URL of an SVG in your module's `static/src/img/`, and
    delegate every other journal to `super()`.

## Known limitations

- The at-bank fence runs on the buttons and the delete, not on every write: a write of an
  ordinary field of an at-bank payment is not fenced (a bank change and the payload fields
  are handled in `write`).
- The lock-timeout fallback in `_durable_write` is not durable by definition.
- `GEC_BANK_BYPASS_KEY` is a plain context key: any caller can set it.
- Redaction matches keys exactly; a bank that renames or nests a secret key
  leaks it into the log.
- `_gec_bank_fill_outstanding` runs at create time only; an existing channel without an
  account is not filled.
- `_gec_bank_ensure_api_lines` re-adds a removed API line the next time the journal's bank
  account, IBAN, BIC or type is written.
- The handoff defaults (prepared/transmitted) are deliberately coarse; banks
  with per-payment states must use the merge.
- `_gec_bank_poll_status` reads at most `GEC_BANK_STATUS_POLL_LIMIT` transfers per run, so
  a bank sets the `order` that serves the least recently read first.
- The bank-change rule runs on `write` of `payment_method_line_id`, `journal_id` or
  `payment_type` only; a payment created already on a bank starts `pending` by the compute.
