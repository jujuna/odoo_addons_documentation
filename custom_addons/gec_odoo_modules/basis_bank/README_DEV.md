# Basis Bank Integration (`basis_bank`) — Developer guide

**Who this is for:** developers who change this module, or write another bank integration on
the same pattern. User steps and screens: [README.md](README.md). Business overview:
[documentations/basis_bank.md](../../../documentations/basis_bank.md). Bank API reference
(endpoints, payloads, error codes): [basisbank_api.md](../../../basisbank_api.md). Open issues: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

---

## 1. Purpose and facts

The module is a transport layer. It transmits existing `account.payment` records to Basis
Bank, records the bank's verdict in its own `basisbank_state`, imports statements through the
standard statement-import framework, and keeps an outbound Basis payment out of `reconciled`
until the bank report proves the transfer. It creates no journal entries of its own and never
reconciles a statement line.

It builds on `gec_bank` (the base shared with the TBC and BOG modules): the write guard, the
durable claim and write, the connection, approver and API-log mixins, the channel hooks and
the at-bank guard. It keeps its own transfer flow: it does not use `gec_bank`'s shared
transfer fields (`gec_bank_state` and the rest), which TBC and BOG use.

| Item | Value |
|---|---|
| Depends | `account_accountant` (bank reconciliation, the manual release path), `account_batch_payment` (batch model and views), `account_bank_statement_import` (`_create_bank_statements`, `unique_import_id` constraint), `mail` (chatter on the connection), `gec_localization` (`bank_name`/`bank_bic` from Georgian IBANs), `gec_bank` (guard, durable write, mixins, channel hooks, `_gec_bank_config_errors` reused as the send-time setup check, the default Outstanding Payments account `120410`) |
| External Python | `requests` |
| New models | `basisbank.connection` (on `gec.bank.connection.mixin`), `basisbank.approval` (on `gec.bank.approval.mixin`), `basisbank.api.log` (on `gec.bank.api.log.mixin`); abstract `basisbank.service` (REST client, on `gec.bank.service`) and `basisbank.sendable` (what payment and batch share, on `gec.bank.sendable`); transient `basisbank.otp.wizard`, `basisbank.statement.import.wizard`, `basisbank.resync.wizard`, `basisbank.change.password.wizard` |
| Extended models | `account.payment`, `account.batch.payment` (both carry `gec.bank.guard.mixin` from `gec_bank`), `account.journal`, `account.payment.method`, `account.payment.method.line`, `account.bank.statement.line` |
| Hooks, migrations, controllers, reports | None |
| Crons | `cron_basisbank_confirm_or_reset` (hourly, active), `cron_basisbank_daily_statement_sync` (daily, inactive) |

Data files, in manifest order: `security/basisbank_groups.xml` (category, privilege, User and
Manager groups), `data/basisbank_payment_method.xml` (the *Basis Bank Transfer* method),
`data/ir_cron_data.xml` (two crons), then the views (connection, approval, API log, journal,
payment, batch, wizards), `views/basisbank_menus.xml`, and last `security/ir.access.csv`.

---

## 2. Architecture

```text
┌────────────────────────────────────────────────────────────────┐
│ Configuration: connection (one per company), approver list,    │
│ journal detection (BIC CBASGE22 + connection)                  │
└────────────────────────────────┬───────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Entry points: payment form, batch form, OTP dialog,            │
│ Pay Salaries (gec_payroll_bank, through the payroll hooks)     │
└────────────────────────────────┬───────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Send pipeline (payment or batch): checks, approval, session,   │
│ durable claim, upload, durable result writes                   │
└────────────────────────────────┬───────────────────────────────┘
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ REST client: session ticket, calls, error codes,               │
│ redacted API log on its own cursor                             │
└────────────────────────────────┬───────────────────────────────┘
                                 ▼  HTTPS
                          Basis Bank API
                                 │  report items (GetReport)
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Proof: statement import + line auto-match, and the report      │
│ matcher (Resync, Reset to Pending, 48-hour cron)               │
│   → confirmed; an imported line is reconciled with the payment │
└────────────────────────────────────────────────────────────────┘
```

Names: connection = `basisbank.connection`, approver list = `basisbank.approval`, journal
detection = `account.journal.is_basisbank`, send pipeline = `basisbank_send_with_otp` on
`account.payment` and `account.batch.payment` (approval, session check and OTP dialog from
`basisbank.sendable`), REST client = `basisbank.service`, API log =
`basisbank.api.log`, line auto-match = `account.bank.statement.line._basisbank_auto_match`,
report matcher = `account.payment._basisbank_match_report_items`, confirm from statement =
`account.payment._basisbank_confirm_from_statement`.

The state, the approval and the bank's answers on payment and batch are protected fields: a
form, an import or an RPC call cannot write them, only the flows above, through
`_gec_bank_internal_write` or a durable write (section 5).

The send and the proof are separate transactions and separate code paths. The send moves
`basisbank_state` to `sent` and marks the payment sent; only the proof path moves it to
`confirmed`. Odoo's own `reconciled` comes from core, when a statement line is matched with the
payment's outstanding line: the statement import does that match itself
(`gec_bank` `_gec_bank_reconcile_payment`).

---

## 3. File map

| File | What it holds |
|---|---|
| [`__manifest__.py`](__manifest__.py) | Metadata, dependencies, data file order |
| [`__init__.py`](__init__.py) | Imports `models`, `services`, `wizard` |
| **models/** | |
| [`models/__init__.py`](models/__init__.py) | Model imports (the mixin first) |
| [`models/basisbank_sendable.py`](models/basisbank_sendable.py) | Mixin shared by payment and batch: the fields `basisbank_approved_by`, `basisbank_approved_date`, `basisbank_sent_date`, `basisbank_bank_response`; `_compute_basisbank_can_approve`, `action_basisbank_approve`, `_basisbank_check_approved`, `_basisbank_ensure_session`, `_basisbank_otp_dialog`, `_basisbank_connection`, `_basisbank_revoke_approval`, `_basisbank_notify` |
| [`models/basisbank_connection.py`](models/basisbank_connection.py) | Connection: credentials, mode, approver, ticket helpers, Test/Re-authenticate/Logout (write-access checked)/Change Password actions, journal refresh on create/write/unlink, daily sync cron |
| [`models/basisbank_approval.py`](models/basisbank_approval.py) | Approver and delegates; `approver_user_ids`, `user_can_approve` |
| [`models/basisbank_api_log.py`](models/basisbank_api_log.py) | One row per bank call; `connection_id` is `ondelete='restrict'`; the vacuum keeps the upload rows |
| [`models/account_journal.py`](models/account_journal.py) | `is_basisbank`, `basisbank_connection_id` (compute + search), the Basis method among a journal's default outbound methods, the `basisbank` bank-feed source, set on create and on a bank account/BIC/type write for a journal with Basis Bank's BIC (`_basisbank_apply_bank_feed_source`, only over `undefined`, with or without a connection), the dashboard mark (`_gec_bank_dashboard_logo`, by BIC, with or without a connection). `gec_bank` adds the line after the bank account is linked and fills the default outstanding account |
| [`models/account_payment_method.py`](models/account_payment_method.py) | `basisbank_transfer` method registration and domain; constants `BASISBANK_METHOD_CODE`, `BASIS_BANK_BIC` |
| [`models/account_payment_method_line.py`](models/account_payment_method_line.py) | Payroll hooks for `gec_payroll_bank` |
| [`models/account_payment.py`](models/account_payment.py) | Payment fields, constraints, protected fields, at-bank states for the `gec_bank` guard, approval revoke on write and create (payment and batch), pre-send checks, submit for approval, single send with durable claim and results, reject, report matching, Resync, 48-hour cron, Reset to Pending |
| [`models/account_batch_payment.py`](models/account_batch_payment.py) | Batch fields, endpoint compute, protected fields, submit for approval, batch send with durable claims, request build, reply recording, "done" rule, Reset to Pending, Resync action |
| [`models/account_bank_statement_line.py`](models/account_bank_statement_line.py) | Auto-confirm of sent payments when statement lines are created, and reconciliation of the matched line |
| **services/** | |
| [`services/__init__.py`](services/__init__.py) | Imports the client |
| [`services/basisbank_service.py`](services/basisbank_service.py) | REST client: endpoints, auth and ticket, `_call`, error table, redaction, logging; shared constants `RETRYABLE_SEND_CODES`, `UNKNOWN_SEND_CODES`, `TRANSFER_GROUPS`, `SENSITIVE_KEYS` and `report_window()` |
| **wizard/** | |
| [`wizard/__init__.py`](wizard/__init__.py) | Wizard imports |
| [`wizard/basisbank_otp_wizard.py`](wizard/basisbank_otp_wizard.py) | OTP dialog; deletes itself, then calls `basisbank_send_with_otp` |
| [`wizard/basisbank_statement_import_wizard.py`](wizard/basisbank_statement_import_wizard.py) | Statement import: computed currency, report fetch, line values, sign rule, advisory lock, counters |
| [`wizard/basisbank_resync_wizard.py`](wizard/basisbank_resync_wizard.py) | Batch Resync over an editable date window |
| [`wizard/basisbank_change_password_wizard.py`](wizard/basisbank_change_password_wizard.py) | Password change dialog (managers) |
| **data/** | |
| [`data/basisbank_payment_method.xml`](data/basisbank_payment_method.xml) | *Basis Bank Transfer* outbound method (`noupdate`) |
| [`data/ir_cron_data.xml`](data/ir_cron_data.xml) | The two crons (`noupdate`) |
| **security/** | |
| [`security/basisbank_groups.xml`](security/basisbank_groups.xml) | Category, privilege, `group_basisbank_user`, `group_basisbank_manager` |
| [`security/ir.access.csv`](security/ir.access.csv) | Permission rows, company restrictions, own-record rows for wizards |
| **views/** | |
| [`views/account_payment_views.xml`](views/account_payment_views.xml) | Payment form buttons, banner and Basis section; list columns; Payments action; list action *Basis Bank: Reset to Pending* |
| [`views/account_batch_payment_views.xml`](views/account_batch_payment_views.xml) | Batch form buttons, banner and Basis section; core Validate hidden; list columns; Batches and Batches Awaiting Approval actions |
| [`views/account_journal_views.xml`](views/account_journal_views.xml) | Basis section on bank journals |
| [`views/basisbank_connection_views.xml`](views/basisbank_connection_views.xml) | Connection form, list, action |
| [`views/basisbank_approval_views.xml`](views/basisbank_approval_views.xml) | Approver form, list, action |
| [`views/basisbank_api_log_views.xml`](views/basisbank_api_log_views.xml) | Read-only log list and form |
| [`views/basisbank_wizard_views.xml`](views/basisbank_wizard_views.xml) | OTP, import, resync, change-password dialogs; Import Statement action |
| [`views/basisbank_menus.xml`](views/basisbank_menus.xml) | Basis Bank app menu |
| **other** | |
| [`i18n/ka_GE.po`](i18n/ka_GE.po) | Georgian translation |
| [`static/description/icon.png`](static/description/icon.png) | App icon |
| [`static/src/img/basis_logo.svg`](static/src/img/basis_logo.svg) | Basis Bank's mark behind a Basis journal's dashboard card |
| [`tests/__init__.py`](tests/__init__.py) | Test imports |
| [`tests/common.py`](tests/common.py) | Shared fixture: connection, Basis journal and method line, partners and recipient accounts, payment and batch builders, service patch helper |
| [`tests/test_basis_protected_fields.py`](tests/test_basis_protected_fields.py) | Write guard, readonly fields, approval flow, batch approval voided by a joining or leaving payment, send needs write access |
| [`tests/test_basis_flows.py`](tests/test_basis_flows.py) | Send, statement, Resync, 48-hour, journal, approver and log flows with the bank answers mocked |
| `gec_payroll_bank/tests/test_basis_adapter.py` | Payroll adapter tests (live with the bridge, skipped when Basis is not installed) |
| [`README.md`](README.md), `README_DEV.md` | User and developer guides |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Open defects and decisions, with causes and proposed fixes |

---

## 4. Journal detection and the payment method

A journal is a Basis journal when `_is_basisbank_journal()` holds (bank journal, `gec_bank`'s
`bic_prefix(bank_bic)`, the first 8 characters, equals `CBASGE22`) **and** its company or a
parent company has a connection.

1. `_compute_basisbank_connection_id`: for Basis-BIC journals, the connection of the
   journal's company, else of the nearest parent in `parent_ids`. Searches connections with
   `sudo()`, because accountants outside the Basis groups open journals without access to
   connections. `_search_basisbank_connection_id` translates a search into
   `is_basisbank` + `company_id child_of`.
2. `_compute_is_basisbank` (stored): `bool(basisbank_connection_id)`. A connection in `error`
   or `blocked` state still counts, so a failed login never lifts the guards on payments
   already at the bank.
3. No field path leads from a journal to its connection, so `basisbank.connection` `create`,
   `write` (on `company_id`) and `unlink` call `account.journal._basisbank_refresh_journals`:
   it invalidates `basisbank_connection_id` on the bank journals of those companies and their
   branches and calls `modified()`. Odoo propagates that to `account.payment.is_basisbank`,
   `basisbank_state` and the batch fields.
4. `account.payment.method`: `basisbank_transfer` is registered with
   `{'mode': 'multi', 'type': ('bank',)}` and its domain is restricted to journals whose bank
   account BIC starts with `CBASGE22`. `_default_outbound_payment_methods` returns it for
   Basis-BIC journals. Core builds a journal's method lines before it links the bank account,
   so `gec_bank` `account.journal._gec_bank_ensure_api_lines` (on `create`, and on `write` of
   `bank_account_id`, `bank_account_number`, `bank_bic` or `type`) adds the missing line
   afterwards: it adds only API channels, which this module declares through
   `_gec_bank_channel_kind`.
5. `gec_bank` `account.payment.method.line.create` → `_gec_bank_fill_outstanding` fills
   `payment_account_id` on a fresh API line with the chart template's
   `account_journal_payment_credit_account_id` of the root company (`120410` on `l10n_ge`).
6. `_get_bank_statements_available_sources` adds a `basisbank` bank-feed choice, and
   `_basisbank_apply_bank_feed_source` (same `create`/`write` triggers as step 4) selects it
   for a Basis-BIC journal whose source is still `undefined`, so the dashboard stops showing
   the card as unconfigured. Nothing else reads it; imports run only through the wizard and
   the daily cron.

`account.payment._get_method_codes_using_bank_account` adds `basisbank_transfer`, so core shows
the recipient bank account on the payment. It is deliberately not added to
`_get_method_codes_needing_bank_account`: treasury transfers have no recipient account.

---

## 5. States and fields

### Payment

| Field | Notes |
|---|---|
| `basisbank_state` | Stored compute, `readonly=True`, tracked, protected. `_compute_basisbank_state`: `pending` for outbound payments on a Basis journal; a state set by the send flow is kept even if the journal stops being a Basis journal; a `pending` on any other payment is cleared |
| `basisbank_transfer_type` | `internal`, `national`, `foreign`, `treasury`; stored compute, editable: outbound payments on a Basis journal take `treasury` from their own `basisbank_treasury_code`, else the recipient BIC (`BASISBANK_BIC_PATTERN`): CBASGE22 `internal`, another `..GE..` BIC in GEL `national`, any other `foreign`; no valid BIC leaves it empty for the user. Depends on payment fields only (`journal_id`, not `is_basisbank`), so a connection change or a contact/account edit never retypes a payment; `-u` recomputes no existing row |
| `basisbank_bank_internal_id` | Bank reference; `models.Constraint` unique `(company_id, basisbank_bank_internal_id)` |
| `basisbank_error_code`, `basisbank_error_message` | Last verdict of the bank (protected). `basisbank_bank_response`, the reply's message, is in `basisbank.sendable` |
| `basisbank_treasury_code`, `basisbank_purpose_code`, `basisbank_receiver_country/city/address` (stored compute from the commercial contact: ISO country code, city, street + street2; editable), `basisbank_intermediate_bank_code/name`, `basisbank_detail_of_charges` (SHA/OUR/BEN, default SHA) | Type-specific payload |
| `is_basisbank` (related, stored), `basisbank_approval_id` (related to the connection's approver), `basisbank_can_approve` (compute) | View helpers |
| `basisbank_sent_date`, `basisbank_approved_by`, `basisbank_approved_date` | Audit, in `basisbank.sendable` (payment and batch), protected. `basisbank_sent_date` is the claim time (`_basisbank_reserve_send`), cleared when a send is handed back; the batch has its own |

Python constraints: `_check_basisbank_partner` (partner required on Basis journals),
`_check_basisbank_required_by_type` (treasury code only); a foreign payment's country, city, address and charges are
checked at send (`_basisbank_check_before_send`), because the type is computed when the payment is created.

Protected fields: `BASISBANK_PROTECTED_FIELDS` on the payment (`basisbank_state`,
`basisbank_approved_by`, `basisbank_approved_date`, `basisbank_bank_internal_id`,
`basisbank_error_code`, `basisbank_error_message`, `basisbank_sent_date`,
`basisbank_bank_response`) and `BASISBANK_BATCH_PROTECTED_FIELDS` on the batch (state,
approval, sent date, bank response), returned by `_gec_bank_protected_fields`. In
`gec.bank.guard.mixin`, `create` and `write` call `_gec_bank_check_protected`, which raises
`UserError` unless the context carries `GEC_BANK_WRITE_TOKEN`; the flows write them with
`_gec_bank_internal_write(vals)`, which holds the token for that one write. Every protected
field is `readonly=True`, or the web client would send it and every form would refuse to
save. The durable writes (`_basisbank_write_result`, `_basisbank_reserve_send`) update the
columns directly, so the guard does not see them.

Odoo 20 payment states: `draft`, `paid` (posted, not matched), `reconciled` (matched),
`canceled`, `rejected`. A sent Basis payment is `paid`, with `is_sent`; it becomes `reconciled`
when core matches its outstanding line with a statement line. A bank refusal makes it
`rejected` (`gec_bank` mapping, the one core's online payment uses).

Transitions of `basisbank_state` and the methods that make them:

| From | To | By |
|---|---|---|
| `pending` | `awaiting_approval` | `action_basisbank_submit_for_approval` |
| `awaiting_approval` | `awaiting_otp` | `action_basisbank_approve` (`basisbank.sendable`) |
| `awaiting_approval`, `awaiting_otp` | `pending` | `write` on a content field → `_basisbank_revoke_approval` |
| `pending`, `awaiting_otp` | `sending` | `_basisbank_reserve_send` (durable claim) from `basisbank_send_with_otp` |
| `sending` | `sent` | `_basisbank_apply_single_response`, or `_basisbank_apply_response` for batch members |
| `sending` | `pending` / `awaiting_otp` | code 2 or 3: nothing reached the bank, back to the state before the send |
| `sending` | `unknown` | code 999, an exception after the claim, a reply without the payment |
| `sending` | `failed` | any other non-zero code or item error → `_basisbank_reject` (core state `rejected`) |
| `sending`, `sent`, `unknown`, `not_in_report` | `confirmed` | `_basisbank_confirm_from_statement` from line auto-match |
| `sending`, `sent`, `unknown` | `confirmed` or `not_in_report` | `_cron_basisbank_confirm_or_reset` |
| `sending`, `unknown`, `not_in_report` | `confirmed` | `action_basisbank_resync` |
| `not_in_report`, `failed` | `pending` or `confirmed` | `action_basisbank_reset_to_pending` |

Every write the send makes after the claim goes through `_basisbank_write_result`
(`gec.bank.service._durable_write`, own cursor), including core's `is_sent` and `state` from
`_basisbank_payment_state_vals`: after an own-cursor commit on the row, an ORM write of it would
fail at commit and the request would run again.

`BASISBANK_APPROVAL_CONTENT_FIELDS` (`amount`, `currency_id`, `partner_id`, `partner_bank_id`,
`memo`, `payment_reference`, `journal_id`, `basisbank_transfer_type`, and the treasury,
purpose, receiver, intermediate-bank and charges fields): a `write` on any of them revokes the
payment's approval (back to `pending`) and its batch's (back to `draft`). A payment joining or
leaving a batch voids the approval of the batches involved: `create` with a
`batch_payment_id`, and `write` of `batch_payment_id`, which core's batch-error wizard also
does from the payment side. `BASISBANK_AT_BANK_STATES`
(`sending`, `sent`, `unknown`, `not_in_report`, `confirmed`) feed `_gec_bank_at_bank`, so
`gec_bank` refuses reset to draft, cancel and delete, on the payment and on its journal entry.

### Batch

`basisbank_state` (default `draft`, `readonly=True`, protected; every change goes through
`_gec_bank_internal_write`): `draft → awaiting_approval → awaiting_otp → sending →
sent_pending_confirm | awaiting_ib_confirmation (mode bank_confirm) → done`, plus `failed`
and `unknown`. `basisbank_endpoint` is a stored compute (section 6). `basisbank_salary` is set
by the payroll hook. `models.Constraint` unique `(journal_id, basisbank_endpoint, name)`,
because the name is sent as `PackageName`. A `write` on `payment_ids`, and a payment joining or
leaving from its own side (above), revokes the batch approval.

`_basisbank_set_done_when_confirmed()` closes the batches whose payments are all `confirmed`;
statement import, Resync and the 48-hour cron call it. Core `state` (`draft/sent/reconciled`)
is left to core: the members' `is_sent` and `is_matched` move it (`_gec_bank_after_durable`
recomputes it after a durable write).

### Connection

`state`: `draft → active` on a successful `authenticate`; `blocked` on codes 4/5 or
`Client.ActiveClient == false`; `error` only when the bank refuses the login (code 1,
`WRONG_LOGIN_CODE`). Any other failed login, and code 6 on any call, write `last_error_code` /
`last_error_message` and keep the state, so both crons (which take `active` connections only)
retry next run. The hourly cron skips a connection for the rest of its run once its report read
failed without a ticket or left it non-`active`: one failed login per connection per run. A
failed login inside a user request is rolled back with the request's error. Only
`blocked` is refused before a send (`_basisbank_connection`, through `gec.bank.connection.mixin`
`_gec_bank_unusable_errors`, which also words the "no connection" refusal); there is no unblock
action, Test Connection writes `active` on success. `processing_mode`: `odoo_approve`
(default), `direct`, `bank_confirm`. `approval_id` is a stored, editable compute that keeps
the approver only in `odoo_approve` mode (a leftover approver would show Submit for Approval
instead of Send); `_check_approval_when_required` requires it in that mode.
`allow_self_approval` (from `gec.bank.connection.mixin`, default off) lets the creator of a
transfer approve it; the form shows it in `odoo_approve` mode only. `_unlink_except_logged`
refuses to delete a connection that has API logs, and the log's `connection_id` is
`ondelete='restrict'`, so deleting a connection never deletes its log rows.

---

## 6. The send flow

Entry points: **Send to Basis Bank** → `action_basisbank_send` (payment) or
`action_send_basisbank` (batch), which check the approval (`_basisbank_check_approved`) and
the state and mode, **post the draft payments** (`action_post`), run the send checks and open
`basisbank.otp.wizard` (`_basisbank_otp_dialog`). Posting happens here, in its own request,
because a payment the send transaction already wrote cannot be claimed durably
(`_reserve_send` would wait on its own row lock). **Send** →
`basisbank.otp.wizard.action_confirm`.

1. `action_confirm`: strips the OTP, deletes the dialog row, calls
   `basisbank_send_with_otp(otp)` on the payment or batch.
2. `_gec_bank_check_user(BASISBANK_METHOD_CODE)` (gec_bank; group from this module's
   `_gec_bank_user_group_for`): only Basis Bank Users, also over RPC; superuser crons pass.
   Then `check_access('write')`: a user who cannot write the payment or batch is refused. Batch only: `lock_for_update()` on the batch; a `LockError`
   becomes "already being processed". Payments are not locked: their claim is the mutex.
3. State check (`pending`/`awaiting_otp` for a payment, `draft`/`awaiting_otp` for a batch).
   `_basisbank_connection()` then `_basisbank_check_approved(connection)` (`basisbank.sendable`):
   in `odoo_approve` mode the state must be `awaiting_otp` and `basisbank_approved_by` must
   still pass `approval.user_can_approve`.
4. Guards: `_basisbank_check_single_sendable` or `_basisbank_check_payments`, both requiring
   core state `paid` (`_gec_bank_check_sendable`) and ending in `_basisbank_check_before_send`
   (section 7).
5. Build the request: `basisbank_build_single_item`, or `_basisbank_build_request` for a batch.
6. Session: `_basisbank_ensure_session` (`ticket_is_valid()` or `authenticate()`); failure
   raises before anything is claimed.
7. Claim: `_basisbank_reserve_send` per payment (`gec.bank.service._reserve_send`: `sending` and
   `basisbank_sent_date` on an own cursor that commits at once, refused in
   `BASISBANK_CLAIM_BLOCKED_STATES`). A batch claims all its pending payments or, when one
   claim fails, gives the earlier ones back (`_basisbank_claim`). The batch row gets `sending`
   with `_gec_bank_internal_write`, an ORM write: the batch state is not claimed durably.
8. Upload (`upload_single_batch` or `upload_package`) and record the reply
   (`_basisbank_apply_single_response` / `_basisbank_apply_response`), every payment write
   through `_basisbank_write_result`. Any exception → the payments still `sending` become
   `unknown`, warning to Resync.
9. The notification action (`_basisbank_notify`) closes the dialog.

A crash or a re-run of the request after the upload finds the payments claimed (`sending`)
and refuses them; Resync or the 48-hour check settles them.

### Endpoint selection (`_compute_basisbank_endpoint`)

Evaluated in this order; `gel_only` = every member in GEL, one sender = one journal IBAN
(`_basisbank_uniform_sender`):

1. `basisbank_salary` and GEL-only and one sender → `package_salary` (op 5). The salary flag
   comes first, so a salary batch of mixed internal/national payments still goes as a Salary
   package.
2. All `internal`, GEL-only, one sender → `package_gel` (op 4).
3. All `treasury`, GEL-only, one sender → `package_treasury` (op 6).
4. Anything else → `single_batch` (op 7).

User-level table and example: [README.md, section 7](README.md#7-batches-which-bank-operation).

### Request shapes

- Package (`upload_package`): `SenderAcc`, `PackageName` = batch name, `Lang='GEO'`, `Otp`,
  `PackageItems` from `basisbank_build_package_item`: `Amount`, `ReceiverAcc`,
  `ReceiverAccName`, `Descrip`, `DocNum` = payment id; treasury items `Amount` and
  `TreasuryCode`; `TaxPayerTaxCode`/`TaxPayerName` when the partner has a VAT number.
- Single transfers (`upload_single_batch`): `Lang`, `Otp`, and the non-empty groups of
  `TRANSFER_GROUPS`, items from `basisbank_build_single_item` with
  `ClientInternalID = DocNum = payment id`.
- `ReceiverAccName` = `_basisbank_receiver_name()`: the account's `holder_name`, else the
  commercial partner's name, because Odoo 20 keeps recipient accounts on the commercial
  partner while the payment's partner can be a contact.

### Reply and finalize rules

| Reply | Single transfers | Package |
|---|---|---|
| `ErrorCode 0` | Per item by `ClientInternalID`: item error 0 → `sent` + `BankInternalID`; else that payment `failed` with its own message | Every member of the send `sent`, no per-payment bank id |
| Members missing from the reply | Missing ones `unknown`, batch `unknown`, chatter lists them | n/a |
| Code 2 or 3 (`RETRYABLE_SEND_CODES`) | Nothing reached the bank: payments back to their state before the send (`pending` in a batch, which goes to `awaiting_otp`) | Same |
| Code 999 (`UNKNOWN_SEND_CODES`) | `unknown` | Same |
| Any other non-zero code (including 6) | The payments of this send `_basisbank_reject` → `failed`; members confirmed by an earlier send keep `confirmed`; batch `failed` | Same |
| Every item rejected | Batch `failed` | n/a |
| Success | Batch `sent_pending_confirm`, or `awaiting_ib_confirmation` in `bank_confirm` mode | Same |

A single-payment send follows the same table. A reply without the payment's `ClientInternalID`
leaves it `unknown` (Resync); the bank echoes the id (basisbank_api.md, op 7 response).

`_basisbank_reject`: `failed` with the code and message, approval cleared, and core state
`rejected` through `_basisbank_payment_state_vals` (`gec_bank` `_gec_bank_mirror_vals`). The
entry stays posted and matched: the accountant resets and cancels it, or corrects and resends
it, as for any payment core marks Rejected.

---

## 7. Guards before sending

| Where | Checks |
|---|---|
| `account.payment._basisbank_check_single_sendable` | Outbound; Basis journal; not in a Basis batch; not `is_sent`; core state `paid` (`_gec_bank_check_sendable`); transfer type set; then the shared check |
| `account.batch.payment._basisbank_check_payments` | Has payments; outbound batch on a Basis journal; every member outbound and `pending` or `confirmed`; the pending ones not `is_sent` and core state `paid`; then the shared check |
| `account.payment._basisbank_check_before_send` (shared) | All problems at once: no recipient account, untrusted account (`allow_out_payment`), no BIC for national/foreign, no memo or reference (treasury is exempt from these four), non-GEL national/treasury; then each method line's `_gec_bank_config_errors()` (outstanding account present, reconcilable, not cash, not the journal's own account, plus this module's connection and IBAN checks) |
| `basisbank.sendable._basisbank_connection` | Connection exists and is not `blocked` (`gec.bank.connection.mixin` `_gec_bank_unusable_errors`: "No Basis Bank connection is configured for company ..." and "The Basis Bank connection is blocked. Contact the bank."); `draft` and `error` connections are tried |
| `basisbank.sendable._basisbank_check_approved` | In `odoo_approve` mode: state `awaiting_otp`, and the recorded approver still an approver or delegate |
| `basisbank_send_with_otp` (payment and batch) | `_gec_bank_check_user` (Basis Bank User), then `check_access('write')`, before anything else |
| Model constraints | Partner on Basis journals; treasury code; foreign country, city, address, charges |

`action_basisbank_submit_for_approval` on a payment runs `_basisbank_check_single_sendable`
first; on a batch it runs no payment checks, so they wait for the send.

---

## 8. Approval

1. `action_basisbank_submit_for_approval`: requires `odoo_approve` mode and `pending`
   (payment) or `draft` (batch); sets `awaiting_approval`; subscribes and notifies
   `approval.approver_user_ids()`.
2. `action_basisbank_approve` (`basisbank.sendable`, one implementation for payment and
   batch): requires `awaiting_approval`; calls the connection approver's
   `_gec_bank_check_approver(record, connection.allow_self_approval, connection._gec_bank_label())`
   (`gec.bank.approval.mixin`, shared with TBC and BOG); writes `awaiting_otp`,
   `basisbank_approved_by` and `basisbank_approved_date` with `_gec_bank_internal_write`, and
   posts "Approved for Basis Bank by ...".
3. The send re-checks `user_can_approve(basisbank_approved_by)` (`_basisbank_check_approved`,
   section 6, step 3).
4. `_basisbank_revoke_approval(reset_state)` (mixin): records in `awaiting_approval` or
   `awaiting_otp` go back to `reset_state`, lose the approver and date, and get a chatter note.

`_gec_bank_check_approver` is the authority check at approval: the user must be in approver +
delegates (`user_can_approve`), and the creator (`create_uid`) cannot approve unless the
connection's `allow_self_approval` is on (maker-checker). The send's re-check only tests
membership, not the creator rule. `basisbank_can_approve` applies the same rule (approver list,
then the creator or `gec_bank_prepared_by` refused unless `allow_self_approval`), so Approve
shows only where the click passes; it reads the approval and the connection with `sudo()` so the
form opens for an approver without access to them. `action_basisbank_approve` reads the
connection and approver as the user (KNOWN_ISSUES C5). The maker rule is written in both places
(gec_bank `_gec_bank_check_approver` and this compute): change them together.

---

## 9. Confirmation and matching

### Report matcher

`account.payment._basisbank_match_report_items(items)` is the single rule for every place that
reads the bank report: payment Resync, batch Resync wizard, Reset to Pending and the 48-hour
cron. Candidates by `BankInternalID` (when the payment has one) first, then by
`DocNum == payment.id`; a candidate must pass `_basisbank_item_amount_matches` (the debit
account equals the journal IBAN when both are present; `abs(Amount)` equals the payment amount
in the payment currency). The first passing candidate wins.

`report_window(sent)` gives the dates to read: `sent - 2 days` to `max(sent + 2 days,
tomorrow)`. The reference date is `_basisbank_confirmation_reference_date()`: the payment's
own `basisbank_sent_date`, else its batch's.

### Statement-line auto-match

`account.bank.statement.line.create` → `_basisbank_auto_match`, with `sudo()` on payments:

1. Keep lines whose `unique_import_id` contains `basisbank/` and whose `amount < 0` (an
   incoming line never confirms an outbound payment).
2. Look up payments on the lines' journals in `BASISBANK_MATCHABLE_STATES`
   (`sending`, `sent`, `unknown`, `not_in_report`), or `confirmed` and still unmatched
   (`is_matched` False: Resync or the 48-hour check confirmed them, and only their statement
   line can reconcile them): by `basisbank_bank_internal_id` (parsed from
   `unique_import_id`), else by `id == int(ref)` only while the payment has no bank id.
   Journal, not company, because a payment registered from a branch keeps the branch as
   company.
3. `gec_bank` `_gec_bank_matches_payment`: the line is a debit, and its amount converted into
   the payment currency at the line date equals the payment amount.
4. Each match runs in its own savepoint: the confirm (skipped for a payment already
   `confirmed`) with the reconciliation of the line
   (`gec_bank` `_gec_bank_reconcile_payment` → core `set_line_bank_statement_line` on the
   payment's open outstanding line, as superuser, the way core's end-to-end matching does);
   a failure leaves a chatter note on the payment.
5. `_basisbank_set_done_when_confirmed` on the affected batches.

### Confirm from statement

`_basisbank_confirm_from_statement(bank_id)`: writes `confirmed` and `is_sent` (and
back-fills the bank id if empty). It does not touch core's state: core calls `action_validate`
only for payments without an entry, and a payment with an entry is `reconciled` exactly when
its outstanding line is matched, which the statement-line auto-match does.

### Statement import

`basisbank.statement.import.wizard.action_import`:

1. Guards: dates ordered; connection present; journal IBAN present. `currency_code` is a
   computed field (`_compute_currency_code`: the journal's currency, else the company's), not
   an input, so a report is always read and booked in the journal's currency.
2. `basisbank.service.fetch_report_items`: every page, `UserError` on any bank error.
3. `_build_line_vals`: skips items without `BankInternalID`; `_amount_sign` takes the
   direction from which side holds our IBAN (`DebitAcc`/`SenderAcc` → −1,
   `CreditAcc`/`ReceiverAcc` → +1, neither → skipped), so signed and unsigned bank amounts both
   work; an item without a readable `DocDate` is skipped, never booked on today's date;
   `payment_ref = Descrip or '/'`, `ref = str(DocNum)`,
   `unique_import_id = basisbank/<journal_id>/<BankInternalID>`.
4. `pg_advisory_xact_lock(4342859, journal_id)`, then a snapshot of the journal's payments in
   the states auto-match can confirm (`BASISBANK_MATCHABLE_STATES`) for the counter.
5. One statement "Basis Bank <start> - <end>" through
   `journal.with_context(import_file=True)._create_bank_statements(vals, raise_no_imported_file=False)`,
   which returns `(statement_ids, ignored_duplicates, ignored_zero_amount)`. `import_file` keeps core's
   auto-reconcile of more than 80 new lines from committing inside the import, as core's CSV import does. The direct call skips core's
   `_complete_bank_statement_vals` (id prefixing, partner-bank lookup).
6. Counters: imported, skipped (duplicates + zero amounts + unplaceable items), confirmed
   (snapshot payments now `confirmed`).

`basisbank.connection._cron_daily_statement_sync` runs this wizard for yesterday–today on each
`active` connection's Basis journals with an IBAN, one savepoint per journal, with chatter on
the connection when a journal fails.

---

## 10. Reconciled in Odoo

- Odoo 20 keeps a posted payment in `paid` until its outstanding line is matched with a
  statement line (or all its bills are paid, which with `account_accountant` needs every
  payment `is_matched`). The module adds no gate of its own; the statement import matches the
  line of every payment it confirms (section 9).
- Why the outstanding account matters: without one the payment has no entry and core sets
  `is_matched = (state == 'reconciled')`; on the journal's own bank account `is_matched` is
  true at once. The send-time setup check refuses both, and names the method line.

---

## 11. The 48-hour cron

`account.payment._cron_basisbank_confirm_or_reset`, hourly:

1. Candidates: `is_basisbank`, outbound, state `paid/reconciled`, and `basisbank_state` in
   `sending/sent/unknown`, or `pending` inside a batch in `sending/unknown` (left by sends
   made before the durable claim); `limit=500`, ordered by id.
2. Expired: reference date older than `BASISBANK_CONFIRM_TIMEOUT_HOURS` (48).
3. Already matched (`is_matched`) → confirm, each in a savepoint.
4. The rest grouped by `(journal, currency)`; groups without an `active` connection or an IBAN
   are skipped; one `fetch_report_items` per group over `report_window(min(reference))`; a
   fetch error skips the group until the next run.
5. `_basisbank_match_report_items`: found → confirm.
6. Not found → `_basisbank_flag_not_in_report`: `not_in_report`, chatter, and an activity for
   the payment's creator. The entry and its matches stay as they are: a missing report line
   proves nothing, and core never changes accounting on missing evidence.
7. `_basisbank_update_batches_after_check`: batches whose members are all confirmed → `done`;
   a batch with a flagged member → `unknown` unless `failed`, with chatter.

The module never rewrites posted accounting.

---

## 12. Resync and Reset to Pending

- `account.payment.action_basisbank_resync` (button on `sending`/`unknown`/`not_in_report`):
  `_basisbank_find_report_item` (report window around the reference date, matcher) → confirm,
  or a "Not found on the statement yet" warning. Never resets, never resends.
- `account.batch.payment.action_basisbank_resync` (button on `unknown`) opens
  `basisbank.resync.wizard`; `default_get` fills the window from the batch send date;
  `action_resync` matches the members not `confirmed`/`failed` in the batch currency, confirms
  the matches, closes the batch when all are confirmed, and shows the unmatched names.
- `account.payment.action_basisbank_reset_to_pending` (form button on `not_in_report`/`failed`,
  list server action on any selection): refuses states other than `not_in_report`/`failed`
  and payments not in `draft`/`paid` (a `rejected` payment is reset to draft first); reads the
  report first and confirms any payment found; the rest get `unmark_as_sent`, `pending`, and a
  cleared bank id, error, send date and approval. It does not take the payment out of its
  batch.
- `account.batch.payment.action_basisbank_reset_to_pending` (button on `unknown`/`failed`):
  refuses while a member is `sending`/`sent`/`unknown`, and when no member is `not_in_report`
  or `failed`; resets those members through the payment method above; the batch then goes
  back to `draft` with its approval cleared when members are `pending` (the next send carries
  `_basisbank_payments_to_send`, the pending ones only), else `_basisbank_set_done_when_confirmed`.

---

## 13. REST client (`basisbank.service`)

| Aspect | Behavior |
|---|---|
| URL | `https://{api_host}/{api_version}/api/{path}`; scheme and trailing slashes stripped, HTTPS forced |
| Endpoints | `auth`, `auth/logout`, `main/changepassword`, `main/uploadpackagegel`, `main/uploadpackagesalary`, `main/uploadpackagetreasury`, `main/uploadsingletransfersbatch`, `main/getreport` |
| Transport | `requests.post(json=..., timeout=15, verify=True)`, `raise_for_status()`, JSON body |
| Authentication | `authenticate` posts `LoginName`/`Password`; success = `ErrorCode 0` + `Data.TicketId` → ticket stored for 540 s, connection `active`; `ActiveClient == false` → `blocked` |
| Ticket | Valid while it expires more than 30 s from now; `_ensure_ticket` re-authenticates and raises on failure; every ticketed call injects `TicketId` and, unless the reply is code 3, slides the expiry to now + 540 s (the bank's inactivity window is 10 minutes) |
| Retry | Only code 3 with `allow_reauth_retry`, which only `get_report` sets: clear ticket, authenticate, call once more. Sends, password change and logout never retry |
| Transport failures | Timeout, unreachable, HTTP error, bad body: logged with `error_code 999`, raised as `UserError` |
| Connection side effects | Codes 4/5 → `blocked`; 6 → `error`; any code other than 0/3 on `auth` → `error` |
| Logging | `_record_log` → `gec.bank.service._write_log`, on `registry.cursor()`, so a rolled-back send still leaves its row; `SENSITIVE_KEYS` (`Password`, `OldPassword`, `NewPassword`, `Otp`, `TicketId`, set as `_gec_bank_sensitive_keys`) masked by a dict walk (`_redact_data`), and by `_redact_text` for bodies that are not JSON; `error_message` cut to 255 characters |
| Pagination | `fetch_report_items` loops `PageNo` up to `PageCount` |

The code table is `ERROR_MESSAGES`; what each code does to payments is in section 6 and, for
users, in [README.md, section 13](README.md#13-when-the-bank-refuses-or-does-not-answer).

---

## 14. Payroll adapter

`gec_bank` declares the channel hooks on `account.payment.method.line`, and `gec_payroll_bank`
(**Pay Salaries**) creates the payments and batches through them; this module answers them,
each guarded on `self.code == 'basisbank_transfer'`. Basis does not opt in to `gec_bank`'s
shared transfer flow (`_gec_bank_transfer_flow` stays `False`), so `_gec_bank_handoff_state`
is its own:

| Hook | Returns or does |
|---|---|
| `_gec_bank_channel_kind` | `'api'` |
| `_gec_bank_extra_config_errors` | No connection; blocked connection (`_gec_bank_unusable_errors`, on the connection read with `sudo()`, so a Payroll Administrator without a Basis group can run Pay Salaries). The journal IBAN is checked by `gec_bank` for every `api` channel |
| `_gec_bank_check(kind, lines)` | Before anything is created: names every recipient (except treasury recipients) whose effective bank account has no BIC |
| `_gec_bank_payment_vals(kind, payment)` | Raises on non-GEL; a recipient whose commercial partner has `gec_treasury_code` → `treasury` with that code; otherwise raises on no BIC or no memo, and returns `internal` when the BIC starts with `CBASGE22`, else `national`. A missing or untrusted receiver account is refused by `gec_payroll_bank` before this hook runs |
| `_gec_bank_batch_vals(kind)` | `basisbank_salary = (kind == 'salary')` |
| `_gec_bank_handoff_state(batch)` | Member states first: `failed`/`not_in_report` mixed with others → `partial`; all `failed` → `failed`; any `unknown`/`not_in_report` → `uncertain`; else `BASISBANK_HANDOFF_STATES` maps the batch state (`draft`/`awaiting_*` → `prepared`, `sending` → `pending`, `sent_pending_confirm`/`awaiting_ib_confirmation` → `transmitted`, `done` → `confirmed`, `failed`, `unknown` → `uncertain`) |

The bridge's watchdog in `gec_payroll_bank` uses the handoff state to chase unsent or
uncertain payroll batches.

---

## 15. Data

| Record | File | `noupdate` | Notes |
|---|---|---|---|
| `account_payment_method_basisbank` | `data/basisbank_payment_method.xml` | yes | Core's `_auto_link_payment_methods` links it to existing Basis-BIC journals at install; `gec_bank` gives each new line the default Outstanding Payments account |
| `cron_basisbank_confirm_or_reset` | `data/ir_cron_data.xml` | yes | Hourly, active |
| `cron_basisbank_daily_statement_sync` | `data/ir_cron_data.xml` | yes | Daily, inactive |
| Category, privilege, groups | `security/basisbank_groups.xml` | no | Manager includes `base.user_admin` |

Because the method and crons are `noupdate`, an upgrade does not reset a cron's interval or
active flag, and XML changes to them need a manual update on existing databases.

---

## 16. Guards and invariants

| Guard | Where | Protects |
|---|---|---|
| Reset to draft, cancel, delete refused while at the bank (`BASISBANK_AT_BANK_STATES`) | `gec_bank`: `account.payment.action_draft` / `action_cancel` / `@api.ondelete`, and the journal entry's `button_draft` / `button_cancel`; core's statement-unmatching bypass key is honoured | A transfer at the bank losing its accounting. Gap: core Reject (KNOWN_ISSUES C3) |
| Durable claim per payment | `_basisbank_reserve_send` | Two sends of one payment, and a resend after a crash or a re-run |
| Row lock per batch send | `lock_for_update()` in the batch's `basisbank_send_with_otp` | Two users sending the same batch |
| Send-time checks | Section 7 | Resends of payments that may be at the bank; setups the confirmation flow could never release |
| Report re-read before Reset to Pending | `action_basisbank_reset_to_pending` | A resend duplicating an executed transfer |
| Posted accounting never rewritten | The 48-hour cron only flags | Bills paid twice after a missing report line |
| Rejected payments keep their entry | `_basisbank_reject` (core `rejected`) | Reopening a bill or payslip silently |
| One payment per bank reference and company | `_basisbank_internal_id_uniq` | Two payments claiming one transaction |
| One statement line per bank transaction | `unique_import_id` + core constraint | Duplicate imports |
| Core Validate hidden on Basis batches | `view_account_batch_payment_form_basisbank` | Marking payments sent without a bank call. View only: `validate_batch()` from code still does it |
| Protected fields (state, approval, bank answers, sent date) | `gec.bank.guard.mixin` `_gec_bank_check_protected`, on `create` and `write` of payment and batch | Forging an approval, or putting a sent transfer back to Pending, from a form, an import or RPC |
| Maker-checker | `_gec_bank_check_approver` from `action_basisbank_approve` | One person preparing and approving a transfer, unless the connection's `allow_self_approval` is on |
| Approval voided when batch membership changes | `account.payment.create` / `write`, `account.batch.payment.write` | A payment added to an approved batch being sent under an approval that never covered it |
| Basis Bank User for send, resync and reset | `_gec_bank_check_user(BASISBANK_METHOD_CODE)` first in payment `action_basisbank_send`, `basisbank_send_with_otp`, `action_basisbank_resync`, `action_basisbank_reset_to_pending` and batch `action_send_basisbank`, `basisbank_send_with_otp`, `action_basisbank_reset_to_pending`; the buttons carry `groups=` | An Invoicing user outside the Basis group sending or resetting by RPC |
| Write access before a send, a test or a logout | `check_access('write')` in `basisbank_send_with_otp`, `action_test_connection`, `action_reauthenticate`, `action_basisbank_logout` | Read-only users sending money or ending the company's bank session |
| A connection with API logs cannot be deleted | `gec.bank.connection.mixin` `_unlink_except_logged`, log `connection_id` `ondelete='restrict'` | Losing the audit trail with its connection |

Invariants other code relies on: the protected fields change only through
`_gec_bank_internal_write` or a durable write; `basisbank_state == 'confirmed'` only after a
report or statement match; `DocNum` and `ClientInternalID` are the payment id; `unique_import_id` has the
form `basisbank/<journal_id>/<BankInternalID>`.

---

## 17. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `basisbank.connection` | Basis Bank User | read | |
| `basisbank.connection` | Basis Bank Manager | all | |
| `basisbank.connection` | (restriction) | all | `company_id in company_ids` |
| `basisbank.approval` | Basis Bank User | read | |
| `basisbank.approval` | Basis Bank Manager | all | |
| `basisbank.approval` | (restriction) | all | `company_id in company_ids` |
| `basisbank.api.log` | Basis Bank Manager | read | |
| `basisbank.api.log` | `base.group_system` | all | |
| `basisbank.api.log` | (restriction) | all | `company_id in company_ids` |
| OTP, statement import, resync wizards | Basis Bank User | all | own records (`create_uid = user`) |
| Change-password wizard | Basis Bank Manager | all | own records |

- Groups: `group_basisbank_user` implies `account.group_account_invoice` (the minimum to work
  with payments); `group_basisbank_manager` implies User only, no accounting manager rights.
- Field groups: `login_name`, `password`, `api_host`, `api_version` Manager; `ticket_id`,
  `ticket_expiry` `base.group_system`. The service reads them with `sudo()`.
- Menus: root User; Configuration Manager. The *Change Password* button is Manager only
  (`groups=`). Test Connection, Re-authenticate and Logout carry no `groups=`, but each starts
  with `check_access('write')` on the connection, which the User group lacks (read only),
  because the service then writes the connection state and ticket with `sudo()`. `basisbank_send_with_otp` on
  payment and batch starts the same way.
- `@api.private` (not callable over RPC, because they write with `sudo()`): `store_ticket`,
  `clear_ticket`, `refresh_ticket`, `basisbank_change_password`.
- Protected fields: see section 5. The write guard is a Python token, so no RPC call, import
  or form can write them.

Each `sudo()` and why it is safe:

| Where | Why |
|---|---|
| `_compute_basisbank_connection_id`, `_basisbank_refresh_journals` | Which connection serves a journal is not sensitive; journal users lack connection access |
| `_compute_basisbank_can_approve` (`basisbank.sendable`) | Only computes a boolean for the current user |
| `_gec_bank_extra_config_errors` | Reads the connection state only, so the channel check of Pay Salaries needs no Basis group |
| `basisbank.service` reads and writes on the connection | Credentials and ticket are field-protected; the service is abstract and reached only through the send, import and connection actions |
| `_record_log` | Log rows are written by the system on their own cursor |
| `_basisbank_auto_match` on payments | Limited to payments on the lines' journals in `BASISBANK_MATCHABLE_STATES`, or confirmed and unmatched, with a matching reference and amount |
| `_gec_bank_reconcile_payment` (superuser, in `gec_bank`) | The same match core's end-to-end matching makes as superuser; limited to the matched payment's open outstanding line |
| Import counter snapshot | Count only |

---

## 18. Integration

| Module | Relies on | Breaks if changed |
|---|---|---|
| `gec_bank` | The hook overrides (section 14), the method code `basisbank_transfer`, the batch states in `BASISBANK_HANDOFF_STATES`, the guard mixin's `_gec_bank_protected_fields` and `_gec_bank_internal_write`, the connection, approval and API-log mixins; provides the durable claim and write, the at-bank guard, the status mapping, the statement reconciliation, the journal's missing-line fill and the default outstanding account | Salary routing, pre-send checks, watchdog status, send safety, protected fields |
| `gec_payroll_bank` | Calls the channel hooks above: they set `basisbank_transfer_type` (its own rule: any valid BIC other than Basis is `national`), `basisbank_treasury_code` and `basisbank_salary` on the payments and batches it creates, and `_gec_bank_handoff_state` maps the Basis states for its watchdog; `gec_payroll_bank/tests/test_basis_adapter.py` exercises the hooks | Pay Salaries routing and the payroll watchdog |
| `gec_localization` | Provides `GE_BANKS` (`BS` → `CBASGE22`), `gec_treasury_code`, and `120410` via `l10n_ge` | Journal detection, treasury routing, default outstanding account |
| `account_accountant` | `set_line_bank_statement_line`, used by the statement auto-match; `is_matched` from any reconciliation | Automatic Reconciled after import |

No other module depends on `basis_bank`.

---

## 19. Tests

```bash
./odoo-bin -c odoo.conf -d <test-db> -i basis_bank --test-tags /basis_bank --stop-after-init
```

| File | Covers |
|---|---|
| `tests/common.py` | Not a test: the shared fixture (connection, Basis journal and method line, partners, recipient accounts) and helpers that build payments and batches and patch `basisbank.service` methods. The HTTP layer is never called |
| `tests/test_basis_protected_fields.py` | Protected fields are `readonly=True`; state, approval and bank id cannot be written directly or on create; the approval flow and the payment form still save; a payment joining or leaving an approved batch voids the batch approval; sending needs write access |
| `tests/test_basis_flows.py` | Batch send (endpoint choice, drafts posted first, wrong OTP, one refused transfer, timeout then Resync); single send with approval, send checks listing every problem, changed amount voiding the approval; statement import confirming and reconciling; the 48-hour flag; Reset to Pending confirming a payment the report shows; connection, branch and journal detection; approver rules, including the creator rule and `allow_self_approval`; the Basis line on a journal created in one save; the channel check without a Basis group; the log vacuum keeping transfer logs |
| `gec_payroll_bank/tests/test_basis_adapter.py` | `_gec_bank_handoff_state` returns `partial` for mixed member states; `_gec_bank_payment_vals` refuses a recipient account without a BIC |

Not covered: the REST client itself (`_call`, ticket reuse, the code-3 retry, redaction), which
the flow tests replace by patching `basisbank.service` methods, and the durability of the
claim. That needs real cursors, while `registry_test_mode()` makes every cursor share the test
transaction, so it is checked with a scratch-database `odoo-bin shell` probe, not by these
tests.

---

## 20. Extending safely

- Never post, reconcile or create `account.move` records here. The module is transport only;
  core posting and reconciliation stay the single source of accounting.
- In any send path, claim each payment with `_basisbank_reserve_send` before the request and
  write every later change of that payment through `_basisbank_write_result`; never ORM-write a
  claimed payment in the same transaction, and never confirm (post) it there. Park every
  uncertain outcome in `unknown`: the bank may have executed a transfer Odoo could not record.
- Add a new bank-facing payment field to `BASISBANK_APPROVAL_CONTENT_FIELDS` when editing it
  must void an approval.
- Add a new field that only the flows write (a state, an approval, a bank answer) to
  `BASISBANK_PROTECTED_FIELDS` or `BASISBANK_BATCH_PROTECTED_FIELDS`, make it `readonly=True`,
  and write it with `_gec_bank_internal_write` or a durable write. A direct `write` raises, and
  a protected field that is not readonly makes every form refuse to save.
- Put what payment and batch share in `basisbank.sendable`, not in both models: approve, the
  approval check, the session check and the OTP dialog live there once.
- Read the bank report only through `_basisbank_match_report_items`, so Resync, Reset and the
  cron can never disagree. Statement lines keep their own rule: outgoing only, same journal,
  amount after conversion, bank reference before `DocNum`.
- Never change posted accounting from a job: flag and notify, as the 48-hour cron does.
- Add every new secret key to `SENSITIVE_KEYS`, or it lands in the API log.
- A new public method that writes with `sudo()` or through the write token must be
  `@api.private` or start with `check_access('write')`, as the connection actions and
  `basisbank_send_with_otp` do.
- Keep the payroll hooks free of network I/O: they run in the transaction that creates the
  payments, and the watchdog runs them in a cron.

---

## 21. Known limitations

Details, causes and proposed fixes: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

| Limitation | Consequence |
|---|---|
| Creating a connection gives `pending` to old outbound payments (A3) | Old payments show Send to Basis Bank |
| Package members match by `DocNum` only (B2) | Depends on the bank echoing it; an outside transfer with the same `DocNum` and amount would match |
| No statement balances; skipped items only counted (B3) | Gaps go unnoticed |
| Code 6 rejects instead of retrying (B4) | Payments `failed` although nothing was sent |
| A send cut off by a crash stays `sending` until the 48-hour cron flags it | It can be resent only after 48 hours; Resync meanwhile |
| Approver company is filtered in the form only (C1); concurrent sessions untested (C2) | Wrong-company approver possible from code; session clashes possible |
| Core Reject is not guarded (C3) | It marks a sent payment Rejected while `basisbank_state` stays `sent` |
| Approvers without Basis User get an access error on Approve (C5) | Give approvers the User group |
| A failed send leaves the OTP in the dialog row until autovacuum (C6) | OTP stored briefly in plain text |
| The send itself (checks, durable claim, reply recording) is written once on the payment and once on the batch (D1); ticket refreshed after error replies (D2) | Changes to the send must be made twice |
| Upload replies and `GetReport` may use different forms of `BankInternalID` (not verified with the bank) | Line auto-match by bank id may never hit for single transfers; the cron and Resync fall back to `DocNum` |
| The `basisbank` bank-feed source is never read | A label without behavior |
