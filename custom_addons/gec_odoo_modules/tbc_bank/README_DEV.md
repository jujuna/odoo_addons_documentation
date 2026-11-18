# TBC Bank Integration (`tbc_bank`) — Developer guide

For developers who change this module. The business side is in [README.md](README.md), the
TBC API (endpoints, fields, errors, sandbox data) in [BIS_API.md](BIS_API.md), and the manual
test plan against TBC's test environment in [TESTING.md](TESTING.md).

## 1. Purpose and facts

The module sends Odoo payments as TBC transfers, imports TBC movements as bank statement
lines, and plugs TBC into Payroll Bank Channels as a salary bank. The transfer lifecycle is
shared: `gec_bank` owns the states, the approval, the durable claim and result writes, the
undo fence, the statement matching, the manual confirmation and the status poll, and calls
hooks that each bank answers for its own method code. This module answers them for
`tbc_transfer` and keeps the TBC API code: order building, send, duplicate resolution,
recovery, status refresh and statements. Accounting itself stays standard Odoo: payments,
batches and reconciliation are core.

| Item | Value |
|---|---|
| Depends | `account_accountant` (bank reconciliation), `account_bank_statement_import` (`unique_import_id` on statement lines), `account_batch_payment` (batches), `gec_bank` (the shared transfer flow and its hooks, the field guard, durable writes, the connection, OAuth, approver and log mixins, statement matching; brings `gec_localization`), `mail` (chatter on the connection) |
| New models | `tbc.connection` (`gec.bank.connection.mixin`, `gec.bank.oauth.mixin`), `tbc.approval` (`gec.bank.approval.mixin`), `tbc.api.log` (`gec.bank.api.log.mixin`), `tbc.statement`; abstract `tbc.service` (REST client, inherits `gec.bank.service`); wizards `tbc.statement.import.wizard`, `tbc.statement.fetch.wizard` |
| Extended models | `account.payment`, `account.batch.payment`, `account.journal`, `account.payment.method`, `account.payment.method.line` |
| Payment fields | This module adds `tbc_transfer_type`, the beneficiary and treasury order fields, `tbc_bank_status` and the related `is_tbc` and `tbc_processing_mode`. The transfer fields (`gec_bank_code`, `gec_bank_state`, `gec_bank_reference`, `gec_bank_request_id`, `gec_bank_error`, `gec_bank_approved_by`, `gec_bank_approved_date`, `gec_bank_confirmed_source`) and `gec_bank_match_keys` on the statement line belong to `gec_bank` |
| Scheduled jobs | `_cron_daily_statement_sync`, `_cron_fetch_live_statements`, `_cron_tbc_status_poll` (active at install except the snapshots, `noupdate`; the poll runs `gec_bank` `_gec_bank_poll_status`); autovacuum `_gc_gec_bank_api_logs` (inherited, protects transfer logs through `_gec_bank_log_vacuum_domain`) |
| Hooks, controllers | None |
| Migrations | `migrations/20.0.1.6.0/pre-migrate.py`: copies the old `tbc_*` transfer columns into the `gec_bank_*` ones |

Data files, in manifest order: `security/tbc_groups.xml`, `data/tbc_payment_method.xml`,
`data/ir_cron_data.xml`, the views, `views/tbc_menus.xml`, `security/ir.access.csv`.

## 2. Architecture

```text
 Payment form / Batch form
   │ action_tbc_*  (method code tbc_transfer)
   ▼
 gec_bank flow ──hooks──► tbc_bank code ──► tbc.service ──HTTPS──► TBC BIS API
 (states, approval,       (order, send,         │
  claim, results, poll)    refresh, recover)    └──► API log (own cursor)
   ▲
   │ _gec_bank_auto_match
 Statement line ◄── Import Statement ◄── movements

 Pay Salaries (gec_payroll_bank) ──hooks──► TBC payroll adapter
```

Payment = `account.payment`, Batch = `account.batch.payment`, Statement line =
`account.bank.statement.line`, TBC payroll adapter = `account.payment.method.line` hooks. The
public buttons (`action_tbc_*`) call the generic `_gec_bank_*` methods with the method code
`tbc_transfer`, so a button acts only on TBC payments, also over RPC; `gec_bank` calls back
the hooks `account.payment` answers here. Every HTTP call goes through `tbc.service._call`;
every outcome that concerns money is written outside the request transaction (`gec_bank`
`_gec_bank_write_result`) so a crash cannot lose it.

## 3. File map

| File | What it holds |
|---|---|
| `__manifest__.py` | Dependencies, data files, description |
| `__init__.py` | Imports `models`, `services`, `wizard` |
| `README.md`, `README_DEV.md` | User guide, this guide |
| `BIS_API.md` | TBC BIS API reference and module mapping |
| `TESTING.md` | Manual test plan against TBC's test environment |
| `data/tbc_payment_method.xml` | Payment method `tbc_transfer` (noupdate) |
| `data/ir_cron_data.xml` | The three scheduled jobs: import and status poll active, snapshots off (noupdate) |
| `i18n/ka_GE.po` | Georgian translation |
| `models/__init__.py` | Model imports |
| `models/account_batch_payment.py` | Batch send and batch approval buttons, `tbc_processing_mode` |
| `models/account_journal.py` | `is_tbc`, connection lookup, bank feed source, statement match keys, dashboard mark, statement import action |
| `models/account_payment.py` | TBC order fields, type from IBAN, the `gec_bank` hooks for `tbc_transfer`, order checks and building, send result, duplicate resolution, recovery, status refresh, reset to pending |
| `models/account_payment_method.py` | Method `tbc_transfer`, journal domain by BIC |
| `models/account_payment_method_line.py` | Transfer-flow opt-in and Payroll Bank Channels hooks for TBC |
| `models/tbc_api_log.py` | API log, link to the connection, rule for which rows the autovacuum keeps |
| `models/tbc_approval.py` | Delegates of the approver (the rest is the mixin) |
| `models/tbc_connection.py` | Credentials, environment, approver, Test Connection, daily statement sync; processing mode, state, self-approval, retention and the token cache come from the mixins |
| `models/tbc_statement.py` | Balance snapshots and the live snapshot job |
| `security/tbc_groups.xml` | Category, privilege, groups User and Manager |
| `security/ir.access.csv` | Access rows and company restrictions |
| `services/__init__.py` | Service import |
| `services/tbc_bank_service.py` | `tbc.service`: OAuth2, calls, blocked-user detection, all endpoints; durable writes, logging and redaction come from `gec.bank.service` |
| `static/description/icon.png` | App icon |
| `static/src/img/tbc_logo.svg` | TBC's mark behind a TBC journal's dashboard card (`_gec_bank_dashboard_logo`) |
| `tests/__init__.py` | Test imports |
| `tests/test_tbc.py` | Service, send, approval, recovery, statements, journals, logs, protected fields, multi-company |
| `gec_payroll_bank/tests/test_tbc_adapter.py` | TBC hooks and Pay Salaries through TBC (lives with the bridge, skipped when TBC is not installed) |
| `views/account_batch_payment_views.xml` | Batch buttons |
| `views/account_journal_views.xml` | Journal button and fields |
| `views/account_payment_views.xml` | Payment buttons, status boxes, the TBC Transfer group, the Transfers and Pending Approval actions |
| `views/tbc_api_log_views.xml` | API log views and action |
| `views/tbc_approval_views.xml` | Approver views and action |
| `views/tbc_connection_views.xml` | Connection views and action |
| `views/tbc_menus.xml` | The TBC Bank menu |
| `views/tbc_statement_import_wizard_views.xml` | Import wizard |
| `views/tbc_statement_views.xml` | Snapshot views and the fetch wizard |
| `wizard/__init__.py` | Wizard imports |
| `wizard/tbc_statement_fetch_wizard.py` | Fetch a balance snapshot for a period |
| `wizard/tbc_statement_import_wizard.py` | Import movements as statement lines |

## 4. Calling TBC

1. `tbc.service._ensure_token`: `token_is_valid` (60 seconds of margin, from
   `gec.bank.oauth.mixin`); if not, `authenticate` posts the client credentials (HTTP Basic,
   scopes `bab_accounts bab_transfers`) and `store_token` caches the token on the connection.
   The token methods are `@api.private`: they are not callable over RPC.
2. `_call`: builds `https://<host>/bab/v1/<path>`; the host is `api_host` or the environment's
   default (`_host`). Every call is logged by `_record_log` (`gec.bank.service._log_vals` and
   `_write_log`) on its own cursor, with secrets redacted (`_redact_data`, `SENSITIVE_KEYS`).
3. A 401 clears the token and retries once with a new one.
4. A `title` of `USER_IS_BLOCKED`, `USER_IS_NOT_ACTIVE` or `USER_IS_DELETED` sets the
   connection to `blocked` (`_mark_blocked_if_needed`, written with `_durable_write`).
5. Read calls raise `UserError` on failure. Money calls use `soft=True` and return
   `{'http_status', 'data', 'error_text'}`, with `http_status` 0 for no answer, so the caller
   can tell an ambiguous failure from a definite one. TBC's error body is turned into text once,
   in `_error_text` (title, detail and the per-field messages, else the raw body).

## 5. Sending one payment

Entry: **Send to TBC** → `account.payment.action_tbc_send` → `gec_bank`
`_gec_bank_send_transfers('tbc_transfer')`. One payment goes straight to the hook
`_gec_bank_send_one` (TBC answer: `_tbc_send_one`). Several go through `_gec_bank_send_each`
(a savepoint each; a `UserError` is collected as "payment: reason") and
`_gec_bank_report_sends` (counts read from the resulting states by
`_gec_bank_count_outcomes`, refused payments named). `_tbc_send_one`:

1. `_gec_bank_check_transfer('tbc_transfer')`: write access; the payment is a TBC transfer
   (`_gec_bank_check_own`); refuses `unknown` (recover first), `failed` (Reset to Pending
   first) and an `is_sent` payment; in *Approve in Odoo first* `_gec_bank_check_approved`
   (the approval exists and its approver may still approve, else it is withdrawn durably, see
   section 6); and `_gec_bank_check_sendable` (a draft has no entry yet, a payment that is not
   `paid` already left the bank or was refused).
2. `_gec_bank_connection`: the hook `_gec_bank_connection_record` (the journal's connection,
   sudo) then `_gec_bank_unusable_errors`: it exists and is not blocked.
3. `_tbc_check_order`: the channel setup (`_gec_bank_config_errors`: reconcilable Outstanding
   Payments account, journal IBAN, connection), amount above 0, journal IBAN, treasury in GEL
   with a 9-digit code, recipient account present, transfer type consistent with the IBAN's
   bank code, foreign fields filled. Nothing is reserved when this fails. The same check
   answers the hook `_gec_bank_check_instructions`, which Submit for Approval runs.
4. `_gec_bank_reserve_send`: `_gec_bank_new_request_vals` (TBC: a numeric id below 10^9,
   kept across retries) plus `gec_bank_state = 'sending'`, written by one conditional `UPDATE`
   on an independent cursor (`gec.bank.service._reserve_send`) unless the state is at the bank
   or `unknown`. It is the mutex (a second click updates no row) and makes the request ID
   survive a crash. The values go into the cache only; a re-read would return this
   transaction's older snapshot.
5. `_tbc_build_order` → `tbc.service.import_single_transfer`: one order per request,
   60-second timeout.
6. `_tbc_apply_send_result`: no answer or 5xx → `unknown`; `DUPLICATED_SINGLE_TRANSFER_REQUEST`
   → `_tbc_resolve_duplicate` (lookup by request ID, never `failed`); other 4xx → `failed`;
   207 with `failed[]` → `failed`; 207 with a `transferId` → `sent`, and in *Direct* mode
   `_tbc_refresh_status` right away.
7. Every outcome is written by `_gec_bank_write_result`: only the columns of
   `_gec_bank_result_columns` (TBC adds `tbc_bank_status`), through
   `gec.bank.service._durable_write`; `is_sent` or `state = 'rejected'` follow the bank state
   (`_gec_bank_payment_state_vals` → `_gec_bank_mirror_vals`); a state that keeps no approval
   clears it (`_gec_bank_approval_kept_states`); the batch is recomputed
   (`_gec_bank_after_durable`); the state change is posted in the chatter ("TBC Bank state:
   Sending → Sent"), plus a note when the payment is marked Rejected.

While a payment is `sending`, `sent`, `confirmed` or `unknown`, `_gec_bank_at_bank` makes
`gec_bank` refuse reset to draft, cancel and delete, on the payment and on its journal entry.

A `failed` transfer has its payment marked Rejected. The way back: reset the payment to draft,
confirm it, `action_tbc_reset_to_pending` (only from `failed`: state `pending`, reference and
error cleared; the request ID is kept, or cleared when TBC had created the transfer, so the next
claim mints a new one), send. Nothing else reopens it: an unknown or unfinished
send is resolved only by `action_tbc_recover`.

## 6. Approval

- `action_tbc_submit_approval` → `_gec_bank_submit_approval('tbc_transfer')`: only `pending`
  payments are taken (none: "No pending TBC Bank transfer in this selection."). Each needs a
  usable connection (`_gec_bank_connection`) whose processing mode is `odoo_approve` (else
  "The TBC Bank connection does not require approval in Odoo."), passes
  `_gec_bank_check_sendable` and `_gec_bank_check_instructions` (`_tbc_check_order`), goes to
  `awaiting_approval` with `_gec_bank_internal_write`, and the approvers
  (`approval_id.approver_user_ids()`) are subscribed and mentioned. The payment button shows
  only when `tbc_processing_mode == 'odoo_approve'`; so do the batch buttons.
- `action_tbc_approve` → `_gec_bank_approve`: the connection comes from
  `_gec_bank_connection`, so a journal without a connection, or with a blocked one, refuses
  the approval as it refuses the send (an approval given before the approver rule exists would
  release the money later). `tbc.approval._gec_bank_check_approver` (`gec.bank.approval.mixin`)
  requires the user to be the primary approver or a delegate (`user_can_approve`) and not the
  payment's creator unless `allow_self_approval`; then `approved`, `gec_bank_approved_by`,
  `gec_bank_approved_date`.
- At send, `_gec_bank_check_approved` re-checks `user_can_approve(gec_bank_approved_by)`. A
  removed approver's approval is withdrawn with `_gec_bank_write_result({'gec_bank_state':
  'pending'})` (durable, so it survives the refusal) and the send raises.
- `account.payment.write` (`gec_bank`) calls `_gec_bank_revoke_approval('pending')` when a field
  of `_gec_bank_payload_fields()` changes (TBC: `TBC_ORDER_FIELDS`: amount, currency, partner,
  bank account, memo, journal, transfer type and the other `tbc_*` order fields). An awaiting
  or approved transfer goes back to `pending`; a transfer at the bank keeps its approval as
  the record of who released the money, but a stray approval on another state is cleared.
- The batch buttons `account.batch.payment.action_tbc_submit_approval` and
  `action_tbc_approve` call the same methods on `payment_ids`.

## 7. Status, recovery and confirmation

- `action_tbc_refresh_status` → `_gec_bank_refresh_status` → hook `_gec_bank_refresh_one` →
  `_tbc_refresh_status`: reads the single-transfer status and always stores it as
  `tbc_bank_status`; `TBC_STATUS_OK` → `confirmed`; `TBC_STATUS_FAILED` → `failed` with TBC's
  error text, except on a `confirmed` transfer, which is never downgraded: the answer is
  posted in the chatter and the state is left alone.
- `_cron_tbc_status_poll` → `_gec_bank_poll_status('tbc_transfer', 'tbc.connection',
  'write_date, id')`: refreshes at most `GEC_BANK_STATUS_POLL_LIMIT` (100) `sent` or
  `unknown` payments that have a bank reference per run, each in its own savepoint; failures
  are logged. The order is least recently written first: every refresh writes
  `tbc_bank_status`, so a transfer that was read goes to the back and the ones left over come
  up in later runs. Only journals whose connection is `active` or `error` are polled, so a
  blocked or missing connection, whose refresh raises before any call, takes no places.
- `action_tbc_recover`: only from `sending` or `unknown`, with a request ID. It looks the
  payment up by `gec_bank_request_id`. Found → `sent` and a refresh; TBC's "not found" (404, or
  the 400 title in `TBC_EXTERNAL_ID_NOT_FOUND`) → `pending`. A payment still `sending` is
  refused for `TBC_SENDING_STALE_MINUTES` after its reservation: a send may still be running,
  and TBC's test environment does not refuse a resent request ID.
- `action_tbc_confirm_manual` → `_gec_bank_confirm_manual`: `sent` →
  `confirmed`, source manual; an `unknown` one goes through `action_tbc_recover`.
- `account.bank.statement.line.create` (`gec_bank`) → `_gec_bank_auto_match`: the key fields
  come from `account.journal._gec_bank_match_key_fields` (TBC: `gec_bank_reference`,
  `gec_bank_request_id`, both indexed, so each arm of the search uses an index). A line whose
  `gec_bank_match_keys` (the movement's `paymentId`, set by the import) equals one of them on
  a `sent` or `unknown` payment, and that is its debit for its amount
  (`_gec_bank_matches_payment`), confirms it (source statement) and is reconciled with its
  outstanding line (`_gec_bank_reconcile_payment`, the call core's end-to-end matching makes),
  so the payment reaches `reconciled`. A payment already `confirmed` by the status refresh or
  by hand, but not yet matched, is matched the same way: its state is kept and only the line
  is reconciled. One search per journal for the whole batch of lines.

## 8. Batch send

`account.batch.payment.action_tbc_send_batch` needs write access and a TBC journal, takes the
TBC payments in `pending`, `awaiting_approval` or `approved`, and sends them with
`_gec_bank_send_each` (each in its own savepoint) and `_gec_bank_report_sends`. `sent`,
`confirmed`, `sending`, `unknown` and `failed` members are not taken: the first four go
through Recover from TBC or the statement, a failed one is reset to pending first. A payment
refused before it was sent (for example not approved) counts as failed and is named in the
notification. One payment never rolls back another that already went out. The service wraps
no batch endpoint: transfers go out one by one. Core's **Validate** is hidden on TBC batches
(it would mark the payments sent without a bank call).

## 9. Statements

- `tbc.statement.import.wizard.action_import`: the currency is `currency_code`, computed from
  the journal (`_compute_currency_code`, not editable: the lines are booked in the journal's
  currency) → `tbc.service.fetch_all_movements` (page size 700, at most `MAX_MOVEMENT_PAGES`,
  period converted to Tbilisi time by `_to_tbc_local` with the standard library's `zoneinfo`,
  as core does). With a `total` in the answer, paging goes on until it is reached, and an
  empty page before it raises, so a period TBC stops sending part-way imports nothing; without
  a `total` a short page is the last →
  `_create_statement_lines`: skips movements whose `statusCode` is not authorized, and those
  `_movement_to_line_vals` cannot map (no id or no readable date; the movement's `paymentId`
  becomes `gec_bank_match_keys`), then hands the rest to core
  `journal._create_bank_statements`: one statement *TBC Bank <from> - <to>*, movements already
  imported skipped (`unique_import_id` = `tbcbank-<journal id>-<movementId>`), and core's
  automatic matching run on the new lines. No balances are passed: the snapshot API's window
  does not line up with the import's yet.
- `tbc.connection._cron_daily_statement_sync`: runs the wizard for every TBC journal that resolves
  to an active or error connection (its company's or a parent's) over the last `STATEMENT_SYNC_LOOKBACK_DAYS`.
- `tbc.statement._fetch_and_store`: a `live` snapshot is updated in place, a `period`
  snapshot is added; `_cron_fetch_live_statements` keeps the month to date;
  `tbc.statement.fetch.wizard.action_fetch` stores a period snapshot.

## 10. Payroll adapter

TBC answers Payroll Bank Channels' hooks in `models/account_payment_method_line.py`, for the
method code `tbc_transfer` only; every other code goes to `super()`.

| Hook | TBC answer |
|---|---|
| `_gec_bank_transfer_flow` | `journal_id.is_tbc`: a TBC channel on a TBC journal runs the shared transfer flow |
| `_gec_bank_channel_kind` | `'api'` |
| `_gec_bank_extra_config_errors` | no connection for the company, or a blocked one (`_gec_bank_unusable_errors`, connection read with sudo) |
| `_gec_bank_check` | a Treasury Code that is not 9 digits; a recipient account that is not a Georgian IBAN |
| `_gec_bank_payment_vals` | a Treasury Code recipient → `tbc_transfer_type = 'treasury'` and `tbc_treasury_code` |

There is no TBC override of `_gec_bank_handoff_state`: for a transfer-flow channel `gec_bank`
maps each payment's `gec_bank_state` through `GEC_BANK_TRANSFER_HANDOFF` and merges them with
`_gec_bank_merge_handoff_states`. The bridge already checks the sender IBAN, the receiver
account it really chose, the company currency and the settlement. Pay Salaries opens the
batch list: the user sends from the batch form. Other payments keep the type
`_compute_tbc_transfer_type` derives from the IBAN.

## 11. Journals and the payment method

- `account.journal._compute_is_tbc` → `_is_tbc_journal`: a bank journal whose BIC starts with
  `TBCBGE22` (`bic_prefix` from `gec_bank`: the first 8 characters, so the 11-character branch
  form matches too).
- `account.journal._default_outbound_payment_methods` adds `tbc_transfer` for a TBC journal.
  The line itself is created by `gec_bank` `account.journal._gec_bank_ensure_api_lines`, which
  `create` and `write` (bank fields) run, so a journal created in one save with its BIC gets
  the **TBC Bank Transfer** line; `account.payment.method.line._gec_bank_fill_outstanding`
  gives the new line core's default Outstanding Payments account. TBC's own `create` and
  `write` call `_tbc_apply_bank_feed_source` (feed `tbcbank` when undefined).
- `account.journal._gec_bank_match_key_fields`: `gec_bank_reference` and `gec_bank_request_id`
  for a TBC journal (a movement's `paymentId` is TBC's transfer ID or our request ID; the
  documentation does not say which).
- `account.payment.method`: `_get_payment_method_information` registers `tbc_transfer`;
  `_get_payment_method_domain` limits it to journals with a TBC BIC.
- `account.payment._get_method_codes_using_bank_account` makes the method require a
  recipient bank account; `_compute_tbc_transfer_type` picks the type from it.
  `_compute_gec_bank_code` depends on `journal_id.is_tbc`, because the transfer flow is
  opted in per journal (`_gec_bank_transfer_flow`).

## 12. Data

| File | Creates | Upgrade |
|---|---|---|
| `data/tbc_payment_method.xml` | method `tbc_transfer` | `noupdate`: kept as edited |
| `data/ir_cron_data.xml` | three jobs, snapshots off | `noupdate`: an existing database keeps its own activation and intervals |
| `security/tbc_groups.xml` | category, privilege, groups | updated |

## 13. Guards and invariants

- Money leaves only from a posted payment, so the journal entry exists first
  (`_gec_bank_check_sendable`, run by `_gec_bank_check_transfer`).
- One request ID per payment, reused on every retry; the reservation is the mutex
  (`_gec_bank_reserve_send`). The one exception: Reset to Pending of a transfer TBC had created
  clears it, so the resend gets a new one (`action_tbc_reset_to_pending`).
- Reservation and results are durable (independent cursor). `_durable_write` falls back to a
  normal write, logged, only when this transaction already holds the row lock.
- An ambiguous answer is `unknown`, never `failed`; nothing is resent automatically. An
  `unknown` transfer is not claimable and not sendable.
- A `failed` transfer is not sent until `action_tbc_reset_to_pending`; a payment already
  `is_sent` is not sent.
- A duplicate answer is resolved by lookup, never marked `failed`.
- A `confirmed` transfer is never failed by a status answer (`_tbc_refresh_status` posts it).
- Recover runs only from `sending` or `unknown`, and a `sending` payment cannot be recovered
  within `TBC_SENDING_STALE_MINUTES`.
- An approval needs an approver who may still approve at send (`_gec_bank_check_approved`).
- The fields only the integration writes (`gec_bank_state`, `gec_bank_reference`,
  `gec_bank_request_id`, `gec_bank_error`, the approval fields, `gec_bank_confirmed_source`,
  `tbc_bank_status`) are refused in `create` and `write` unless the write carries the
  `gec.bank.guard.mixin` token (`_gec_bank_internal_write`; the durable writes bypass the ORM).
  All are `readonly=True`.
- A payment that moves to another journal or method starts clean, and one at the bank cannot
  move (`_gec_bank_release_bank`).
- Secrets never reach the log (`SENSITIVE_KEYS`); transfer logs are never removed by the
  autovacuum, and a connection with logs cannot be deleted (`_unlink_except_logged`;
  `tbc.api.log.connection_id` is `ondelete='restrict'`).
- One connection per company (`_company_uniq`).

## 14. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `tbc.connection` | TBC Bank: User | read | |
| `tbc.connection` | TBC Bank: Manager | all | |
| `tbc.connection` | everyone (restriction) | all | `company_id in company_ids` |
| `tbc.approval` | User · Manager | read · all | restriction by company |
| `tbc.api.log` | Manager · System | read · all | restriction by company |
| `tbc.statement` | User · Manager | read · all | restriction by company |
| `tbc.statement.import.wizard`, `tbc.statement.fetch.wizard` | User | all | |

Groups: User implies Invoicing (`account.group_account_invoice`); Manager implies User and
Accounting Administrator, and the admin user gets it. `client_id`, `client_secret` and
`api_host` are Manager-only fields; `access_token` and `token_expiry` are System-only.

Entry points check access before they act: **Test Connection** (`action_test_connection`),
`action_tbc_send_batch`, `action_tbc_reset_to_pending`, `action_tbc_recover`, and
`gec_bank` `_gec_bank_check_transfer`, `_gec_bank_confirm_manual` and
`_gec_bank_refresh_status` start with `check_access('write')`. The token methods
(`token_is_valid`, `store_token`, `clear_token`) are `@api.private`, so RPC cannot call them.
The transfer fields cannot be written by a form, an import or RPC (section 13). **Submit for TBC Approval** is shown
to TBC users only, but `_gec_bank_submit_approval` checks no group; **Approve** is shown to everyone, because an
approver or delegate needs no TBC group (the approver check reads the connection with `sudo`).

`sudo()` uses: the connection lookup on journals (`_compute_tbc_connection_id`,
`_search_tbc_connection_id`) and the configuration reads in `_gec_bank_connection_record`
(which `_gec_bank_connection` and `_gec_bank_processing_mode` use),
`_gec_bank_extra_config_errors` (payroll adapter) and `gec_bank` `_gec_bank_check_approved`
(the approver record), so a user without a TBC group can read a journal or a payment, and a
Payroll Administrator can run Pay Salaries; the service reads credentials and writes the token
and logs; the log autovacuum; the snapshot upsert.

## 15. Integration

| Module | What it relies on |
|---|---|
| `gec_bank` | The method code `tbc_transfer`, the payment hooks of section 5 (`_gec_bank_send_one`, `_gec_bank_refresh_one`, `_gec_bank_connection_record`, `_gec_bank_new_request_vals`, `_gec_bank_payload_fields`, `_gec_bank_check_instructions`, `_gec_bank_label_for`, the protected and result columns), the method-line hooks of section 10 and `_gec_bank_match_key_fields`; payroll batches are sent with this module's batch button |
| `gec_payroll_bank` | The method-line hooks and the TBC state names through `GEC_BANK_TRANSFER_HANDOFF`; a change to either shows in its watchdog |
| `bog_bank` | Shares the transfer fields and the flow; `bog_bank/tests/test_bank_isolation.py` checks that neither bank's button acts on the other's payments (skipped without `tbc_bank`) |
| `gec_localization` | Fills `bank_bic` from a Georgian IBAN (a TBC journal is recognised at creation) and provides `gec_treasury_code` on contacts |
| `account_bank_statement_import` | `unique_import_id` keeps imports duplicate-free |

## 16. Tests

```bash
data_venv/bin/python odoo-bin -c odoo.conf -d <test-db> -u tbc_bank --test-tags /tbc_bank --stop-after-init --http-port 8099
```

| File | Covers |
|---|---|
| `tests/test_tbc.py` | Redaction, URLs, token cache and its RPC guard, order building per type, send outcomes, reservation, approval (submit checks, self-approval, removed approver), reset to pending, batch send and its report, crons and the status rotation, multi-company rules, log autovacuum, connection delete guard, statement mapping, paging and dedup, journal currency, journals, auto-match, duplicates, recovery, confirmed-never-failed, protected fields |
| `gec_bank/tests/test_gec_bank.py` | The shared flow: claim, durable write, undo fence, sendable states, mirror values, statement reconciliation, channel checks, handoff merge |
| `gec_payroll_bank/tests/test_tbc_adapter.py` | The hooks one by one; Pay Salaries through TBC: salary, pension into the agency's TBC account, treasury transfer, two payslips of one employee, refusals before creation, batch approval |

TBC is always mocked; the tests never call it.

## 17. Extending safely

- Write a send outcome only through `_gec_bank_write_result`: it is durable and whitelisted
  (`_gec_bank_result_columns`), and an ORM write of the same row would make Odoo retry the
  request and send the transfer again. A column a TBC answer writes goes into
  `_gec_bank_result_columns` and `_gec_bank_protected_fields`, as `tbc_bank_status` does.
- Write the protected fields from the flow with `_gec_bank_internal_write` (or the durable
  writes), never with a plain `write`: the guard refuses it.
- Never mint a new request ID for a payment that has one: TBC's test environment does not
  refuse a resent ID, so only reuse (`_gec_bank_new_request_vals`) keeps a retry traceable. The
  one exception is `action_tbc_reset_to_pending` of a transfer TBC had created, which TBC refuses
  to take again under the same ID.
- Keep money calls in soft mode, so a timeout can stay `unknown`.
- A field the order is built from belongs in `TBC_ORDER_FIELDS`, so a change voids the approval.
- Public buttons call the generic `_gec_bank_*` methods with `TBC_METHOD_CODE`, so a button
  never acts on another bank's payment.
- A state only TBC has is added with `selection_add` on `gec_bank_state` and placed in
  `_gec_bank_state_groups` and `_gec_bank_handoff_map`, as `bog_bank` does for its own;
  otherwise the payroll watchdog sees it as uncertain.
- Payroll hooks must not call TBC: the payments are not committed yet when they run.
- Keep `_tbc_check_order` in line with TBC's rules (BIS_API.md, section 7) so a payment is
  refused before it is reserved.

## 18. Known limitations

| Limit | Consequence |
|---|---|
| One TBC request per payment | A large batch takes as long as its payments together |
| TBC's batch endpoint and balance endpoint are not used | No single-call batches, no live balance |
| TBC dates are read as Tbilisi time | Not stated by TBC (BIS_API.md, open question Q1) |
| A movement's `paymentId` is matched to the transfer ID and the request ID | TBC does not say which one it is (Q2) |
| Imported statements carry no TBC balances | Odoo cannot flag a missing movement; compare with the snapshot by hand |
| Snapshot amounts are plain numbers | They are not converted or summed across currencies |
