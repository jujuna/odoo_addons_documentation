# Bank of Georgia Integration (`bog_bank`) — Developer guide

For a developer who knows Odoo 20 but not this module. The user-facing behaviour is in
[README.md](README.md); the transfer flow this module plugs into is described in
[../gec_bank/README_DEV.md](../gec_bank/README_DEV.md).

## Purpose and facts

Sends payment orders to Bank of Georgia Business Online (`api.businessonline.ge`, OAuth2 client
credentials from `account.bog.ge`) and imports statements through Odoo's own statement import. It is
a sibling of `tbc_bank` and `basis_bank`, built on the shared `gec_bank` base. The transfer state, the
bank's ids, the approval, the send guards, the durable writes, the statement matching and the payroll
handoff map live in `gec_bank`: one set of `gec_bank_*` fields on `account.payment`, switched on per
payment by its method code (`gec_bank_code`), in the pattern of core's `payment.transaction` and
provider code. This module answers `gec_bank`'s hooks for its own code, adds two states, and keeps
what is BOG's API: the document builder, single and bulk send, the status letters, recovery through
today's activities and the attachments.

| | |
|---|---|
| Depends | `account_accountant` (payments, batches, statements), `account_bank_statement_import` (statement creation + dedup), `account_batch_payment` (batches), `gec_bank` (the shared base: transfer flow on `account.payment`, `gec.bank.service`, the guard/connection/oauth/approval/log mixins, statement matching), `mail` (chatter) |
| New models | `bog.connection` (one per company, credentials + OAuth2 token cache), `bog.approval` (approver + delegates), `bog.api.log` (redacted call log), `bog.statement` (summary snapshots), `bog.statement.import.wizard` (transient), abstract `bog.sendable` (payment/batch mixin), abstract `bog.service` (REST client) |
| Extended models | `account.journal` (+`is_bog`, +`bog_connection_id`, +match-key fields), `account.payment` (+BOG fields, +BOG's answers to the `gec_bank` hooks, +document builder, +BOG buttons), `account.batch.payment` (+bulk send), `account.payment.method` (+`bog_transfer`), `account.payment.method.line` (+7 `_gec_bank_*` hooks) |
| Hooks | No post-init or uninstall hook; `gec_bank_state` carries `ondelete` fallbacks for its two added states (`awaiting_confirmation` → `pending`, `created` → `unknown`) |
| Crons | 4 with `noupdate`, run as `base.user_root`: daily statement sync (`bog.connection`, 7 days back), document status poll (`account.payment`, hourly) and batch status poll (`account.batch.payment`, hourly) active; live snapshots (`bog.statement`, 2h) off |
| Data loads | `security/bog_groups.xml` (2 groups + category), `data/bog_payment_method.xml` (noupdate: `bog_transfer`), `data/ir_cron_data.xml` (noupdate), views, `security/ir.access.csv` last |

## Architecture

```text
account.payment ──reserve / record──► gec.bank.service (durable cursor writes)
      │  build document                          ▲
      ▼                                          │
bog.service (REST client) ──_call──► api.businessonline.ge
      │  log (own cursor)                        │ answers
      ▼                                          ▼
bog.api.log          bog.connection (token cache, state)
```

Here `account.payment` runs `gec_bank`'s transfer flow (`gec_bank_state`), with BOG answering its
hooks; a BOG batch keeps its own `bog_state`. Every transition on a payment that reflects a bank
answer is written by `_gec_bank_write_result` through `gec.bank.service._durable_write` (independent
cursor), never through the ORM, so a crash after the bank answered cannot discard the document key.
`bog.service` wraps HTTP: OAuth2 token, 5 req/s throttle, soft failures (no response →
`http_status: 0`), one 429 retry, one 401 re-auth. Statements enter through
`bog.statement.import.wizard` into core's `_create_bank_statements`; `gec_bank`'s statement-line
`create` runs the auto-match with the key fields BOG names.

## File map

| File | Holds |
|---|---|
| `__manifest__.py` | module metadata; `gec_bank` is the key dependency |
| `__init__.py`, `models/__init__.py`, `services/__init__.py`, `wizard/__init__.py`, `tests/__init__.py` | package imports; `models/__init__.py` loads the BOG models, `bog_sendable` before the payment and batch files that inherit it |
| `models/account_payment.py` | BOG constants and fields, the `gec_bank_state` extension, BOG's answers to the payment hooks, the document builder, send/status/recover/cancel actions, status cron |
| `models/account_batch_payment.py` | bulk send and claim, batch states, package status table, per-line mapping, cancel, status cron, batch protected fields |
| `models/account_journal.py` | `is_bog` stored compute, connection compute/search, feed source, default methods, `_gec_bank_match_key_fields`, `_gec_bank_dashboard_logo` |
| `models/account_payment_method.py` | `BOG_METHOD_CODE`, `BOG_BANK_BIC`, method info/domain |
| `models/account_payment_method_line.py` | the 7 `_gec_bank_*` hooks (transfer flow opt-in, payroll checks, handoff map) |
| `models/bog_connection.py` | BOG credentials, approver link, name-match threshold, constraint, Test Connection, daily sync cron |
| `models/bog_approval.py` | only `delegate_ids` (everything else is the `gec.bank.approval.mixin`) |
| `models/bog_api_log.py` | `result_code`, `correlation_id`, `retry_after`, `is_money_movement`, vacuum domain |
| `models/bog_sendable.py` | `_bog_connection`, `_bog_notify`, `BOG_STATUS_POLL_LIMIT` |
| `models/bog_statement.py` | snapshot model + `_fetch_and_store`/`_statement_vals` + live cron |
| `services/bog_service.py` | endpoints, OAuth2, `_call`, throttle, paging, `bog_key` |
| `wizard/bog_statement_import_wizard.py` | import dialog: computed currency, paging call, line mapping, date parsing |
| `data/bog_payment_method.xml` | `account_payment_method_bog` (noupdate) |
| `data/ir_cron_data.xml` | the 4 crons as OdooBot, all active but the snapshot job (noupdate) |
| `security/bog_groups.xml` | module category, User / Manager groups (v20 privilege model) |
| `security/ir.access.csv` | access rows + one company restriction row per owned model |
| `views/*.xml` | menus, form/list views, buttons, statusbars, alerts |
| `tests/` | `common.py` fixture; payment, batch, service, statement and cross-bank test files |
| `bog.md` | raw notes about the bank's API (not code) |
| `i18n/ka_GE.po` | Georgian translations |
| `static/description/icon.png` | app icon |
| `static/src/img/bog_logo.svg` | BOG's mark behind a BOG journal's dashboard card (`_gec_bank_dashboard_logo`) |

## Flows

### Send one payment (`action_bog_send`)

1. `action_bog_send` → `_gec_bank_send_transfers(BOG_METHOD_CODE)` (gec_bank): one payment →
   `_gec_bank_check_own`, then `_gec_bank_send_one`; several → `_gec_bank_send_each` (each in its own
   savepoint; a `UserError` becomes a "payment: reason" line) and `_gec_bank_report_sends`, which counts
   the outcomes from the resulting states (`_gec_bank_count_outcomes`), not from return values, and names
   every payment refused before sending.
2. `_gec_bank_send_one` (BOG's answer, only for `gec_bank_code == 'bog_transfer'`) → `_bog_send_one` →
   `_bog_check_sendable`: `_gec_bank_check_transfer(BOG_METHOD_CODE)` (write access; own method code;
   refuses `unknown`, `failed` and `is_sent`; where the connection's mode is `odoo_approve`,
   `_gec_bank_check_approved`; `_gec_bank_check_sendable`: posted and Paid), then
   `_gec_bank_check_instructions` (BOG: the method line's `_gec_bank_config_errors`).
   `_gec_bank_check_approved` needs an approver who may still approve (`user_can_approve`); otherwise it
   withdraws the approval durably (`pending`) and refuses.
3. `_bog_prepare_send`: `_gec_bank_connection()` (the journal's connection through
   `_gec_bank_connection_record`; missing or `blocked` → UserError from `_gec_bank_unusable_errors`) and
   `_bog_ensure_attachments_uploaded` (uploads every file at each send, keeps the hashes durably when they
   changed; a refused extension, empty file or a reply without a hash fails here, before anything is claimed).
4. `_bog_reserve_send` → `_gec_bank_reserve_send`: `_gec_bank_new_request_vals` (BOG: reuse or mint
   `gec_bank_request_id` (UUID) and `bog_document_no` (`ODOO<id>`, max 16), and clear `bog_bulk_key`, since
   a new claim leaves the package the payment was last sent in), then `gec.bank.service._reserve_send`:
   one conditional UPDATE to `sending` on an independent cursor that commits at once, refused when the
   state is already in `at_bank | unknown` (for BOG: sending, created, sent, confirmed, unknown) —
   durable and a mutex; a double click finds the row claimed.
5. `_bog_build_document`: the JSON document; empty values dropped; `CheckUniqueId: True` always,
   `CheckInn` only when set, `AttachmentIds` from the cached hashes.
6. `bog.service.create_domestic` / `create_foreign` (soft mode, 60 s timeout).
7. `_bog_apply_send_result` (never raises): `http_status` 0/5xx → `unknown` + warning; 4xx →
   `failed`; 2xx: ResultCode 0 → `created` with the document key in `gec_bank_reference`, then the
   name-match warning and a best-effort `_bog_refresh_status` in a savepoint; 702 (request id exists) →
   `unknown`; 363 (duplicate) → `failed`, never offered Create Anyway; other Warn codes (333/444/701) →
   `awaiting_confirmation`; any other business code → `failed`.
8. Every state lands through `_gec_bank_write_result`: only columns of `_gec_bank_result_columns` (BOG
   adds `bog_bank_status`, `bog_result_code`, `bog_reject_code`, `bog_warn_code`, `bog_match_percent`,
   `bog_attachment_hashes`, `bog_bulk_key`), written durably through `_durable_write`, then
   `_gec_bank_after_durable`, then a chatter post; the approval is cleared when the new state is not in
   `_gec_bank_approval_kept_states`; Odoo's own fields follow `_gec_bank_payment_state_vals`
   (`created/sent/confirmed` → the payment is marked sent; `failed` → Rejected).

### Send a batch (`action_bog_send_batch`)

1. `_bog_sendable_payments`: refuses a non-BOG journal; refuses while any member is
   `sending/created/sent/unknown` (a new package would take the batch's one key, and the old package's
   members could no longer be followed); then the BOG members (`_gec_bank_own`) that are not
   `confirmed` or `failed`; cap 500 (`BOG_BULK_MAX_LINES`).
2. `_bog_connection()`; domestic and foreign cannot mix; every payment is `_bog_check_sendable`-checked
   and attachment-uploaded before anything is claimed, so one refusal stops the whole send.
3. `_bog_claim`: each payment `_bog_reserve_send()` and `_bog_build_document()`, so every member carries
   its own `UniqueId`/`DocumentNo` before the call (per-line recovery and status mapping depend on it).
   When a claim raises `UserError`, the claims already made are written back to their earlier
   `gec_bank_state` durably and the error is re-raised: nothing was sent.
4. `_bog_build_file_name` (batch name sanitised, ≤ 50 chars) and batch `bog_state='sending'` through
   `_gec_bank_internal_write`.
5. `create_bulk_domestic` / `create_bulk_foreign` (soft). `_bog_apply_bulk_result`: 0/5xx → batch and all
   members `unknown`; 4xx → `failed`; 2xx without a key (a bare integer, or an object's `UniqueKey`) →
   batch and every member `unknown`, recovered one by one; 2xx with the key → batch and members
   `created`, each member storing `bog_bulk_key`, then best-effort `_bog_refresh_bulk_status` in a
   savepoint.
6. `_bog_refresh_bulk_status`: `get_bulk_status` → package letter (`BOG_PACKAGE_STATUS_STATES`, where
   `P` means *To be Signed*, not Completed) + `DocumentStatuses` lines → `_bog_apply_bulk_lines`
   (match by `UniqueId`, else `DocumentNo`, among `_bog_package_payments()`: the members whose
   `bog_bulk_key` is the batch's current key; per line `_bog_status_vals`). A failed package →
   `_bog_fail_members` (members of that package still sending/created/sent fail; File Duplicate `D` →
   `unknown` with a warning instead). Otherwise the batch state is `_bog_state_from_members(package_state)`:
   all failed → failed, any failed → partial, all confirmed → confirmed, else the package state. A batch
   without a key (no package, or its adoption failed) takes `_bog_state_from_members()` alone: a sending or
   unknown member → unknown, nothing at the bank → draft, unsent members mixed in → partial, else
   created/sent; `action_bog_refresh_bulk_status` first refreshes the open members of such a batch.
7. `action_bog_send_batch_individually`: `_bog_sendable_payments`, then
   `_gec_bank_send_each(BOG_METHOD_CODE)`; the batch state is `_bog_state_from_members()` and its old
   package key is cleared; `_gec_bank_report_sends` names each refused payment.
   `action_bog_cancel_batch`: DELETE while `created`; on 2xx the batch is marked failed and the package's
   `created` members `_bog_cancel_locally`.

### Approval

`action_bog_submit_approval` (payment: `_gec_bank_submit_approval`; batch: forwards to its payments): the
own `pending` payments (none → UserError); per payment the connection must be usable and in `odoo_approve`
mode; the payment is checked as a send will (`_gec_bank_check_sendable`, `_gec_bank_check_instructions`),
set to `awaiting_approval` with `_gec_bank_internal_write`, and the approvers
(`approval_id.approver_user_ids()`) are subscribed and mentioned in the chatter. The form shows the button
only when `bog_processing_mode == 'odoo_approve'`.

`action_bog_approve` (`_gec_bank_approve`; the batch forwards): targets `awaiting_approval`; the connection
comes from `_gec_bank_connection()` first, so a journal without a connection, or with a blocked one,
refuses the approval as it refuses the send (an approval given before the approver rule exists would
release the money later). `bog.approval._gec_bank_check_approver` requires an approver or delegate and
refuses `create_uid == user` unless the connection's `allow_self_approval`. The result is `approved`
with `gec_bank_approved_by` and `gec_bank_approved_date`. The connection constraint
`_check_approval_when_required` requires an approver in `odoo_approve` mode.

Revocation: `account.payment.write` (gec_bank) compares the written fields with
`_gec_bank_payload_fields()` (BOG: `BOG_DOCUMENT_FIELDS`) and calls `_gec_bank_revoke_approval('pending')`:
payments in the `in_approval` group (awaiting_approval, approved, and BOG's awaiting_confirmation) go back
to `pending` and lose the approval, with a chatter note; any other payment not at the bank loses only the
approval. At send time `_gec_bank_check_approved` re-proves it (see Send one payment, step 2).

### Warn codes and recovery

- `action_bog_create_anyway`: only from `awaiting_confirmation` and never for 363; posts who chose to
  resubmit and re-runs `_bog_send_one` (same `UniqueId`, `CheckUniqueId` protects against double
  payment, answer 702 parked as `unknown`).
- `action_bog_reset_to_pending`: only failed/awaiting_confirmation/sending/unknown; a payment still
  `sending` whose `write_date` is fresher than 15 minutes (`BOG_SENDING_STALE_MINUTES`) is refused. Writes
  `pending` and clears the warning code, the document key, the package key and the error; the approval
  goes with the state and the same `UniqueId` is reused on the next send (a new one only for a document
  BOG had created and then rejected).
- `action_bog_recover`: only from `sending` or `unknown` (the button and the method). The status endpoint
  is keyed on BOG's `UniqueKey`, so the only way back is `get_today_activities` matched on our
  `DocumentNo` (uppercased); found with a `DocKey` → write `gec_bank_reference` + `created`, refresh status;
  found without one → nothing is written, a warning says to try again later; not found → an explicit
  "check Business Online" warning (today-activities covers only the current day).
- `action_bog_cancel_document`: DELETE while `created`; 2xx → `failed` with "Cancelled in Odoo".
- `action_bog_confirm_manual` → `_gec_bank_confirm_manual`: only from `sent` (the button and the method)
  → `confirmed`, source `manual`.

### Status refresh and the crons

`action_bog_refresh_status` → `_gec_bank_refresh_status(BOG_METHOD_CODE)` → `_gec_bank_refresh_one` →
`_bog_refresh_status`: only with a document key; `get_document_status` (soft) → stores the raw letter
(`bog_bank_status`), reject/result codes, match %, then `_bog_status_vals`: `A/Z → created`, `S/T →
sent` and `R/D/C → failed` only from sending/created/sent/unknown (`open` states plus sending), so a
failed transfer the user is recovering is never rejected again; `P → confirmed` (never undone). An unlisted letter changes nothing and posts a note, once while the raw letter stays
the same. The failed text is the reject-code sentence or the letter's label, translated by `self.env._`.

`_cron_bog_status_poll` → `_gec_bank_poll_status(BOG_METHOD_CODE, 'bog.connection', 'write_date, id')`:
BOG payments in the `open` states with a document key, on journals whose company has an `active`
connection, at most `GEC_BANK_STATUS_POLL_LIMIT` (100) per run, each refresh in a savepoint.
`_cron_bog_bulk_status_poll` does the same for batches with a `bog_bulk_key` in created/sent/partial/unknown,
and for batches without a key (not `sending`) that are `unknown` or have a transfer in created/sent/unknown,
limited by `BOG_STATUS_POLL_LIMIT`; it skips a batch it cannot lock (`try_lock_for_update`), so a batch a
user is sending is left alone. `_bog_sendable_payments` locks the batch first (`lock_for_update`) and
refuses with "already being processed" while the poll or another send holds it. Both order by `write_date`, so a normal run stays
well inside the worker's time limit at 5 calls a second. A refresh BOG answers with a JSON object writes
the row (the raw letter at least) and moves it to the back; one without a usable answer (timeout, 5xx, a
body that is not a JSON object) stays first, so 100 such documents would hold up the rest until the bank
answers them. The company filter keeps a blocked or missing connection, whose refresh raises before any
call, from taking those places.

### Statement import and auto-match

1. `action_import` (wizard): guards (connection, IBAN, dates), then `bog.service.fetch_all_records`. The
   currency is `_compute_currency_code`: the journal's, else the company's, never typed. Paging: the first
   page via `get_statement`, then `get_statement_page` sequentially from page 2 (BOG demands ordered
   pages) until the period is complete (`_statement_complete`: `totalCount` records, else a page shorter
   than `STATEMENT_PAGE_SIZE`, 1000). It raises, importing nothing, when an incomplete first page has no
   statement id, when an empty page arrives before `totalCount` is reached, and when `MAX_STATEMENT_PAGES`
   (200) pages after the first are not enough. `count` is not used: BOG's pages call it only "a number of
   records" and its Postman collection the total.
2. `_record_to_line_vals`: entry id (`bog_key` normalises decimal keys) and date required (else
   skipped); amount = credit − debit; counterparty = sender for money in, beneficiary for money out;
   `unique_import_id` = `bogbank-<journal>-<entryId>` (the constraint is global, so a bare entry id
   would collide across journals); `gec_bank_match_keys` = document key + document number.
3. `_create_statement_lines`: dedup by `unique_import_id`, then core
   `journal._create_bank_statements(...)` — one statement, duplicates and zero lines skipped, core
   matching runs at once.
4. `gec_bank`'s `account.bank.statement.line.create` → `_gec_bank_auto_match`: the key fields come from
   `journal._gec_bank_match_key_fields()` (here `gec_bank_reference`, `bog_document_no`); one search per
   journal for payments in the `open` states (sent, unknown, and BOG's created) or confirmed and not yet
   matched; `_gec_bank_matches_payment` (a debit for the payment's amount) → the payment is confirmed
   with `_gec_bank_internal_write` (source `statement`, plus `_gec_bank_payment_state_vals`) and
   `_gec_bank_reconcile_payment` (core's end-to-end statement matching as superuser). BOG has no
   statement-line override of its own.
5. `_cron_daily_statement_sync` (connection) and `_cron_fetch_live_statements` +
   `_fetch_and_store`/`_statement_vals` (bog.statement: `live` upserts one row per journal, `period`
   appends; the closing balance is the last daily summary's `balance` — BOG's summary has no
   opening/closing field).

### Service layer

`authenticate`: client-credentials POST to the Keycloak token URL, credentials in Basic **and** in
the body (what is known to work), token cached via `store_token` (`gec.bank.oauth.mixin`; expiry minus
60 s; undocumented `expires_in` defaults to 300 s), failures set `state=error`. `_ensure_token`
re-authenticates when `token_is_valid()` fails. `_call`: throttle (process-local 5 req/s), the HTTP
request, one 429 retry (Retry-After capped at 60 s), one 401 re-auth, soft mode returning `{http_status,
data, error_text, result_code, correlation_id}` with `http_status: 0` for no-response; non-soft raises
UserError on `>= 400`. Every outcome is logged via `_record_log` → gec_bank `_write_log` on its own
cursor (secrets redacted; file bytes never logged; `is_money_movement` set only by the create/delete
document calls, so the vacuum can tell money rows apart from `documents/*` polls).

### Journal recognition and payroll hooks

`is_bog` is a stored compute: bank journal + `bic_prefix(bank_bic) == BOG_BANK_BIC` (8-character
prefix; `bic_prefix` is gec_bank's). `bog_connection_id` is a non-stored compute (the journal company's connection, else the nearest parent's)
with a search method; creating or moving a connection needs no refresh because nothing stored depends on
it. Journal `create`/`write` sets `bank_statements_source` to `bogbank` when unset
(`_bog_apply_bank_feed_source`); `_default_outbound_payment_methods` adds `bog_transfer` on BOG journals,
and gec_bank's `_gec_bank_ensure_api_lines` gives the line to a journal created in one save with its
bank's BIC.

The payment's `gec_bank_code` is `bog_transfer` only when the method line opts in:
`_gec_bank_transfer_flow` returns `journal_id.is_bog`, and `_compute_gec_bank_code` re-declares its
dependency on `journal_id.is_bog`. The seven method-line hooks: `_gec_bank_transfer_flow`,
`_gec_bank_channel_kind` (api), `_gec_bank_extra_config_errors` (connection missing/blocked),
`_gec_bank_check` (payroll: no treasury recipients, Georgian IBANs only, BIC known),
`_gec_bank_payment_vals` (domestic, `IsSalary` only for salaries, BULK ≤ 10,000 GEL else MT103),
`_gec_bank_handoff_map` (adds `awaiting_confirmation → prepared`, `created → pending` to gec_bank's map)
and `_gec_bank_transfer_handoff_states` (a batch whose own `bog_state` is sending/unknown counts as
uncertain: `BOG_BATCH_HANDOFF_STATES`).

### The extension of the shared flow

| Where | BOG's part |
|---|---|
| `gec_bank_state` | `selection_add` of `awaiting_confirmation` and `created`; re-listing `sending` and `sent` only fixes the order |
| `_gec_bank_state_groups` | `created` joins `at_bank`, `held` and `open`; `awaiting_confirmation` joins `uncertain` and `in_approval` |
| `_gec_bank_result_columns`, `_gec_bank_protected_fields` | BOG's answer columns and package key; `BOG_PROTECTED_FIELDS` |
| `_gec_bank_label_for`, `_gec_bank_connection_record` | "Bank of Georgia"; `journal_id.bog_connection_id`, sudo |
| `_gec_bank_send_one`, `_gec_bank_refresh_one` | `_bog_send_one`, `_bog_refresh_status` |
| `_gec_bank_new_request_vals`, `_gec_bank_payload_fields`, `_gec_bank_check_instructions` | the claim's values, `BOG_DOCUMENT_FIELDS`, the channel's configuration errors |
| `account.journal._gec_bank_match_key_fields` | `gec_bank_reference`, `bog_document_no` |

The per-payment hooks (connection, send, refresh, claim values, payload fields, instruction check) start
with `if self.gec_bank_code != BOG_METHOD_CODE: return super()...`, and the method-line hooks guard on
`self.code`, so another bank's payment never reaches BOG's code. The state groups, the result columns and
the protected fields are model-wide: BOG's added states only occur on BOG payments.

## Data

`bog_payment_method.xml` and `ir_cron_data.xml` are `noupdate`: the method row and the cron schedules are
not rewritten: an existing database keeps its crons' on/off setting and user. A new install gets the daily
import and the two polls active, the snapshot job off. The two groups are plain data
(`user_ids` on Manager includes admin). No other data records.

## Guards and invariants

- `_bog_reserve_send` before any money call; `gec_bank_request_id` generated once and reused on every
  retry (a fresh GUID would be a new document to BOG); `bog_document_no` is stable per payment
  (today-activities is searched by it).
- `_gec_bank_write_result` refuses any column outside `_gec_bank_result_columns`; after a durable write
  the main transaction must never ORM-write that payment row (PostgreSQL re-run hazard). The batch row
  itself is written through the ORM (`_gec_bank_internal_write`); the durable record of a bulk send is the
  state and `bog_bulk_key` on its payments.
- Protected fields: `gec.bank.guard.mixin` sits on `account.payment` and `account.batch.payment`. A write
  or create of a field in `_gec_bank_protected_fields` (payment: the shared transfer fields plus
  `BOG_PROTECTED_FIELDS`; batch: `BOG_BATCH_PROTECTED_FIELDS`, i.e. `bog_state`, `bog_bulk_key`,
  `bog_file_name`, `bog_bank_status`, `bog_error_message`) is refused unless the code writes through
  `_gec_bank_internal_write`, which puts a Python token in the context; the token cannot arrive over RPC
  or in an import. The fields are also `readonly=True` for the web client.
- `_gec_bank_own(code)` / `_gec_bank_check_own(code)`: each BOG button acts only on payments whose
  `gec_bank_code` is `bog_transfer`, also over RPC.
- `gec_bank` refuses draft/cancel/delete of a payment and Reset to Draft / Cancel of its entry while
  `_gec_bank_at_bank()` — for BOG `sending/created/sent/confirmed` plus `unknown`.
- `BOG_DOCUMENT_FIELDS` ∩ vals → approval revoked. `unknown` blocks every send except Recover; `failed`
  blocks until Reset to Pending; `is_sent` blocks. Warn codes are never auto-retried; 363 can never be
  confirmed away.
- SQL: `bog.connection` unique per company; `account.payment` unique
  `(company_id, payment_method_id, gec_bank_reference)` and `(company_id, payment_method_id,
  gec_bank_request_id)` (gec_bank).
- A connection with API logs cannot be deleted (`_unlink_except_logged`; the log's `connection_id` is
  `ondelete='restrict'`).
- An unlisted bank status letter changes no state (both tables): the raw letter is always stored.

## Security

| Model | Group | Rights |
|---|---|---|
| `bog.connection` | User | read |
| `bog.connection` | Manager | crud |
| `bog.approval` | User | read |
| `bog.approval` | Manager | crud |
| `bog.api.log` | Manager | read |
| `bog.api.log` | System | crud |
| `bog.statement` | User | read |
| `bog.statement` | Manager | crud |
| `bog.statement.import.wizard` | User | crud |

Each owned model has one company restriction row `[('company_id', 'in', company_ids)]` in
`ir.access.csv`. Field groups: `client_id`/`client_secret` manager-only; `access_token`/`token_expiry`
system-only (`gec.bank.oauth.mixin`). `token_is_valid`, `store_token` and `clear_token` are `@api.private`,
so they cannot be called over RPC; Test Connection and every button that sends, recovers, cancels or
uploads starts with `check_access('write')`. `sudo()` uses: the connection compute and searches
(configuration read), the approver check at send time, the service layer and the durable writers (they
need the credentials, which are group-protected), and the statement reconcile (`with_user(SUPERUSER_ID)`,
mirroring core's own matching).

## Integration

`gec_payroll_bank` drives the `_gec_bank_*` hooks on the method line and reads the payment's
`gec_bank_state` through the handoff map. `gec_bank` owns the transfer flow on `account.payment`, the
durable writers, the at-bank guard, the protected-field guard, the sealed `_gec_bank_config_errors` (which
calls back into `_gec_bank_extra_config_errors`), the approval/connection/oauth/log mixins and the
statement matching. `tbc_bank` runs the same fields with its own method code and `basis_bank` keeps its own
flow; `BOG_METHOD_CODE = 'bog_transfer'` and `BOG_BANK_BIC = 'BAGAGE22'` are the codes the rest of the
system sees. `gec_localization` fills the BIC of a Georgian bank account, which is what makes a journal
`is_bog`.

## Tests

```bash
odoo -d <db> -u bog_bank --test-enable --test-tags /bog_bank --stop-after-init
```

- `tests/common.py`: fixture — one connection, a `BAGAGE22` bank account, journal and method line;
  `registry_test_mode()` so the durable writers share the test transaction.
- `tests/test_bog_service.py`: token flow, casings, paging and incomplete periods, throttle/retry,
  redaction, uploads.
- `tests/test_bog_payment.py`: payload building, the reserve mutex, the result state machine, warn
  codes, approval and revocation, recover, cancel, protected fields.
- `tests/test_bog_batch.py`: package keys on members, no re-send while a send is open, package rejection
  scope, released claims, a bulk answer without a key, Send One by One naming a refused payment.
- `tests/test_bog_statement.py`: line mapping (sign, counterparty, date), the journal's currency, dedup,
  auto-match, snapshots.
- `tests/test_bank_isolation.py`: each bank's buttons refuse the other bank's payments, a payment
  moving bank starts clean, a journal with a payment at the bank cannot change bank by a new
  account number, one Bank State list column (skips when `tbc_bank` is not installed).

The HTTP layer is always mocked; tests never reach the bank.

## Extending safely

- A new payment state: `selection_add` on `gec_bank_state` with an `ondelete` fallback; place it in
  `_gec_bank_state_groups` (`at_bank`, `held`, `open`, `uncertain`, `in_approval`) so the claim, the
  guards, the poll and the outcome count treat it right; give it a `_gec_bank_handoff_map` entry; update
  the view conditions. A new batch state goes in `bog_state` and the view conditions.
- A new payload field belongs in `_bog_build_document` and in `BOG_DOCUMENT_FIELDS` if editing it
  must void an approval.
- A new field BOG's answer fills belongs in `BOG_PROTECTED_FIELDS` (so only the flows write it) and in
  `_gec_bank_result_columns` (so `_gec_bank_write_result` may write it).
- A new business result code goes into `BOG_RESULT_MESSAGES` (sentence, wrapped in `_lt`, read through `self.env._`) and, if it means "not
  created", `BOG_WARN_CODES` — never 363.
- New bank status letters go into `BOG_DOCUMENT_STATUS_STATES` / `BOG_PACKAGE_STATUS_STATES`; the
  raw letter is always stored and an unknown letter must stay a no-op.
- Anything written on a payment after the bank answered goes through `_gec_bank_write_result`, never the
  ORM; protected fields are written with `_gec_bank_internal_write`.
- A new hook override starts with the `gec_bank_code` guard and falls back to `super()`.
- Endpoints and constants live in `services/bog_service.py`; `BOG_BANK_BIC` and
  `BOG_METHOD_CODE` in `models/account_payment_method.py`.

## Known limitations

- `expires_in` is undocumented for client credentials: the module reads the response and falls back
  to 300 s.
- The today-activities path: the docs show `api/v2/documents/...`, BOG's own collection uses the
  unversioned path; the collection's form is used.
- The bulk array size is undocumented; the module self-caps at 500 lines.
- `SourceAccountNumber` passes through exactly what the journal stores (BOG's docs and its own
  collection disagree about the currency suffix), so it must stay unmodified.
- The 5 req/s throttle is process-local; several Odoo workers can still breach the quota — the 429
  branch is the real backstop.
- Resending a document BOG rejected after creating it reuses the `UniqueId`, which `CheckUniqueId`
  may refuse for 7 days (code 702); the flow parks it in Unknown rather than guessing.
- A batch sent with Send One by One has no `bog_bulk_key`: its `bog_state` is `_bog_state_from_members()`,
  refreshed by Refresh Batch Status and by the batch poll while a transfer is open. Its payments' states
  are the truth.
