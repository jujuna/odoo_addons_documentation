# Payroll Bank Channels (`gec_payroll_bank`) — Developer guide

**Who this is for:** developers maintaining the bridge, and authors of bank integrations
that plug into it.

Functional guide: [README.md](README.md). Adapter references (each in the bank module's own
`account_payment_method_line` model file): [`basis_bank`](../basis_bank/models/account_payment_method_line.py),
[`tbc_bank`](../tbc_bank/models/account_payment_method_line.py),
[`bog_bank`](../bog_bank/models/account_payment_method_line.py).

---

## Purpose and facts

The bridge sits between Odoo Payroll (payslip journal entries), Odoo's standard
`account.payment.register`, and bank-specific modules. It routes payslip liabilities to
payment channels chosen per employee and per authority, creates the payments through the
standard register, seals them into payroll batches, and calls the channel hooks declared in
`gec_bank`. It never names a bank and performs no network I/O.

| Item | Value |
|---|---|
| Technical name | `gec_payroll_bank` |
| Depends | `hr_payroll_account` (posting payslip entries, the Paid flip), `account_batch_payment` (batches; the file-method registry), `gec_bank` (the channel hooks, the recipient-account rule, the shared bank plumbing), `gec_localization` (`bank_bic` filled from Georgian IBANs, `gec_treasury_code` on partners) |
| Models added | `hr.payroll.pay.wizard`, `hr.payroll.pay.wizard.line`, `hr.payroll.pay.wizard.authority` (all transient) |
| Models extended | `account.payment.register`, `account.batch.payment`, `account.payment`, `account.move.line`, `hr.employee`, `hr.payslip`, `hr.payslip.run`, `res.company`, `res.config.settings` |
| Access | No own group: `hr_payroll.group_hr_payroll_manager` (Payroll / Administrator) for the wizard. Payments, batches and the register also need `account.group_account_invoice` or higher, which that group does not imply |
| Cron | `cron_gec_payroll_stale_batches`, every 4 h, `noupdate=1`, user `base.user_root` |
| Hooks, migrations, demo | None |
| Tests | `tests/test_payroll_bank.py` (34 tests) plus three adapter suites that skip when the bank module is not installed |
| Downstream | `basis_bank`, `tbc_bank`, `bog_bank` depend on this module and implement its hooks; `geo_payroll` does not depend on it, but ships the account layout it expects |
| License | LGPL-3 |

Dependency direction is one-way: `gec_payroll_bank ← bank module`. A bank module that must
stay installable without Payroll puts its adapter in a small connector module depending on
both.

---

## Architecture

```text
Pay Salaries button (run kanban, payslip form/list)
        │
        ▼
hr.payroll.pay.wizard ── rows per payslip and per (partner, account),
        │                  manual ack, remember routing
        ▼
hr.payslip._gec_payroll_pay ── preflight, register runs, settlement assert,
        │                        batch creation, handoff
        ├──► account.payment.register (override) ── lock, residual snapshot,
        │        partial/settled guards, same-bank recipient account
        ├──► account.batch.payment (override) ── payroll fields, write token,
        │        envelope constraint, unlink guard, watchdog cron
        └──► account.payment.method.line hooks (declared in gec_bank) ──
                 kind, config checks, payment/batch vals, handoff state
```

The wizard is a thin router: it resolves payslips, collects one channel per payslip and per
authority, and hands two routing dicts to the engine. The engine does everything else, one
transaction, all-or-nothing.

---

## File map

| File | Responsibility |
|---|---|
| [`__manifest__.py`](__manifest__.py) | Name, depends, data order, `description` |
| [`__init__.py`](__init__.py), [`models/__init__.py`](models/__init__.py), [`wizard/__init__.py`](wizard/__init__.py), [`tests/__init__.py`](tests/__init__.py) | Imports |
| [`models/hr_payslip.py`](models/hr_payslip.py) | Line selectors, preflight checks, register runs, settlement assertion, batch creation, handoff; `GEC_PAYROLL_BATCH_RESERVED_VALS` |
| [`models/account_move_line.py`](models/account_move_line.py) | `_gec_bank_recipient_account`: a payslip line's own employee bank account wins over gec_bank's same-bank rule |
| [`models/account_payment_register.py`](models/account_payment_register.py) | `_create_payments` (lock, snapshot, partial/settled guards); `_gec_payroll_is_payroll_run` |
| [`models/account_batch_payment.py`](models/account_batch_payment.py) | Payroll fields, immutability, envelope constraint, unlink guard, watchdog cron, constants and the write token |
| [`models/account_payment.py`](models/account_payment.py) | Payment guards: no joining/leaving a payroll batch, no editing its booking fields, without the token |
| [`models/hr_payslip_run.py`](models/hr_payslip_run.py) | `gec_payroll_batch_ids`, batch count, run-level actions |
| [`models/hr_employee.py`](models/hr_employee.py) | `gec_payroll_channel_id` + company constraint |
| [`models/res_company.py`](models/res_company.py), [`models/res_config_settings.py`](models/res_config_settings.py) | Default Salary Bank (company field; settings bridge) |
| [`wizard/hr_payroll_pay_wizard.py`](wizard/hr_payroll_pay_wizard.py) | The wizard, its two line models, default channel logic, remember routing |
| [`wizard/hr_payroll_pay_wizard_views.xml`](wizard/hr_payroll_pay_wizard_views.xml) | Wizard form |
| [`views/hr_employee_views.xml`](views/hr_employee_views.xml) | Employee form + list Salary Bank field |
| [`views/hr_payslip_views.xml`](views/hr_payslip_views.xml) | Payslip form Pay Salaries button + list server action |
| [`views/hr_payslip_run_views.xml`](views/hr_payslip_run_views.xml) | Run kanban card menu buttons |
| [`views/account_batch_payment_views.xml`](views/account_batch_payment_views.xml) | Batch form Payroll group + list columns |
| [`views/res_config_settings_views.xml`](views/res_config_settings_views.xml) | Default Salary Bank setting |
| [`security/ir.access.csv`](security/ir.access.csv) | Wizard access for Payroll Administrators; no record rules |
| [`data/ir_cron_data.xml`](data/ir_cron_data.xml) | Watchdog cron (`noupdate`) |
| [`tests/test_payroll_bank.py`](tests/test_payroll_bank.py) | Bridge engine, guards, wizard, watchdog |
| [`tests/test_basis_adapter.py`](tests/test_basis_adapter.py), [`tests/test_tbc_adapter.py`](tests/test_tbc_adapter.py), [`tests/test_bog_adapter.py`](tests/test_bog_adapter.py) | Payroll-side behaviour of each bank adapter; skip when the bank module is not installed |
| [`i18n/ka_GE.po`](i18n/ka_GE.po) | Georgian translations |

---

## Channel discovery and classification

A channel is an existing `account.payment.method.line`. The hooks, the domain and the
configuration checks are declared in `gec_bank` (`models/account_payment_method_line.py`
there); this module only calls them.

Domain `_gec_bank_channel_domain(company)`: `payment_type = outbound`, `journal_id.type =
bank`, `journal_id != False`, `company_id = company` — the payslips' own company. The string
form for the wizard, employee and settings fields is `GEC_BANK_CHANNEL_DOMAIN`; the company
field states the same domain literally.

`_gec_bank_channel_kind()`: `'file'` when `self.code` is in
`account.batch.payment._get_methods_generating_files()`, else `'manual'`. `'api'` is only
ever returned by a bank override (guard-first style). The kind drives the default-channel
preference (api/file first), the manual acknowledgement requirement, and
`gec_payroll_manual_ack` on the batch.

Sealed configuration check `_gec_bank_config_errors()` = `_gec_bank_core_config_errors()` +
`_gec_bank_extra_config_errors()`. Core errors: not outbound; journal not bank; no
`payment_account_id` ("would post no journal entry at all"); outstanding account is
`asset_cash` or `liability_credit_card`; outstanding account not reconcilable; outstanding
account equals the journal's default account; a channel of kind `api` whose journal has no
IBAN (`bank_account_number`). A bank cannot remove these (test
`test_base_config_checks_cannot_be_removed_by_a_bank`).

Default channel `_gec_default_channel(company)`: the company setting if set, else the first
channel in the domain, preferring kind `api` or `file`.

---

## Line classification

Every selector works on `slip.move_id.line_ids` restricted to open credit lines
(`balance < 0`, not reconciled).

```text
Open credit line on the payslip entry
├─ account == NET rule credit account
│   ├─ partner == employee work contact, reconcilable, type in salary set
│   │      → employee line → salary payment
│   └─ otherwise → NET line not routable → hard block
└─ other accounts
    ├─ partnered, partner != work contact, reconcilable, receivable/payable type
    │      → authority line → authority payment
    ├─ reconcilable but nothing above matches → stray → hard block
    └─ not reconcilable → wizard warning only, stays open
```

Valid account types: salary lines use `account.payment._get_valid_payment_account_types()`
under context `hr_payroll_payment_register=True`, which `hr_payroll_account` extends to
`asset_receivable`, `liability_payable`, `liability_current`; authority lines use the plain
set `asset_receivable`, `liability_payable`. Consequence: a partnered, reconcilable
`liability_current` line (income tax on `331310`, as Odoo ships it) is a **stray** and blocks
the run; the same line on a non-reconcilable account only appears in the wizard warning.
That is why payroll income tax posts to the Payable `331320`. The warning
(`_gec_payroll_blocked_accounts`) lists liability accounts only: a non-reconcilable credit on
an expense account (a deduction on `720900`) owes nobody.

Recipients whose commercial partner has a `gec_treasury_code` (`gec_localization`, the State
Treasury) skip the bank-account check in `_gec_payroll_check_recipients`: they are paid by
that code, and a bank module either sends them as a treasury transfer (`basis_bank`,
`tbc_bank`) or rejects them in `_gec_bank_check` (`bog_bank`).

Recipient bank `line._gec_bank_recipient_account(journal_bic)`:
`line.employee_bank_account_id` if set (this module's override on `account.move.line`); else
gec_bank's rule — the commercial partner's bank accounts (company-less or same company),
preferring one whose BIC has the same first 8 characters as the paying journal's, then lowest
`sequence`. gec_bank's register override applies the same helper at runtime through
`_get_line_batch_key` (next section); the stock fallback from `hr_payroll_account` has no
company filter, so results can differ for partners with company-specific bank accounts.

---

## The engine: `hr.payslip._gec_payroll_pay(routing, authority_routing, payment_date, manual_ack)`

`routing` maps payslip id → channel; `authority_routing` maps `(partner id, account id)` →
channel. Execution order:

1. State guard: every slip `validated` with `net_wage > 0`.
2. Move guard: every slip has a draft or posted `move_id`; draft moves are posted here.
3. Single-company guard.
4. `_gec_payroll_check_payable`: all blocking messages collected and raised once.
5. Authority lines resolved first, then employee lines; groups keyed
   `(channel, kind, account_type, currency)`. Authority lines are grouped **before** salary
   lines: core's payment register updates `matched_payment_ids` on every source move of an
   aggregated payment, and doing salary first could spread employee payment links across
   unrelated payslip entries.
6. `_gec_payroll_check_channels`: per group — channel present, `_gec_bank_config_errors()`
   per channel, `channel.company_id != company`, journal and line currency must be the
   company currency, recipient checks, provider `_gec_bank_check(kind, lines)`.
7. Per group: create an `account.payment.register` with `_gec_payroll_register_context`
   context and `_create_payments()`; then `_gec_payroll_apply_channel_vals` (receiver-account
   check per payment, hook `_gec_bank_payment_vals`, booking fields and the channel refused).
8. `_gec_payroll_assert_settled`: residuals invalidated, NET lines must be closed, authority
   lines must be closed, slips still not `paid` get `action_payslip_paid()` and
   `paid_date = payment_date`; anything left raises.
9. `_gec_payroll_create_batches`: one batch per `(channel, kind, currency)`.
10. `_gec_payroll_handoff`: returns an action opening the "Payroll Payment Batches" list
    (`list,form`, domain on the created batch ids). No bank hook is called: the creation
    transaction is not committed, so sending belongs to a later, explicit action on each
    batch, taken by the person who approves and transmits it.

Details that matter:

- **Two keys.** Register runs are keyed `(channel, kind, account_type, currency)` because
  core refuses to mix account types in one run; batches drop `account_type`:
  `(channel, kind, currency)`.
- **Context per run** (`_gec_payroll_register_context`): `active_model='account.move.line'`,
  `active_ids`, `payment_consider_partner=True`, `gec_payroll_run=True`,
  `gec_bank_journal_bic` (the first 8 characters of the journal's BIC),
  `gec_payroll_residual_snapshot={line_id: residual}`, and `hr_payroll_payment_register=True`
  **for salary runs only** (the enterprise paid-flip code works per payslip and must not see
  aggregated authority legs).
- **`group_payment`.** `False` for salary (one payment per payslip move), `True` for
  authority (one payment per core batch key `(partner, account, currency, partner_bank,
  partner_type)`, aggregated across payslips).
- **Receiver account check.** Before the bank hook runs, `_gec_payroll_check_payment_account`
  refuses a created payment whose `partner_bank_id` is missing (unless the commercial partner
  has a `gec_treasury_code`) or not `allow_out_payment`, for every channel. The pre-flight
  checks the account Odoo is expected to pick; this checks the one it picked.
- **Post-create hook.** `_gec_bank_payment_vals` results intersecting
  `account.payment._gec_payroll_protected_fields()` raise and roll everything back: core's
  `_get_trigger_fields_to_synchronize()` (`date`, `amount`, `payment_type`, `partner_type`,
  `payment_reference`, `currency_id`, `partner_id`, `destination_account_id`,
  `partner_bank_id`, `journal_id`) plus `payment_method_line_id`, the same set the payment
  write lock below protects.
- **Batch creation.** All payments in a batch must share one date. Vals include
  `gec_payroll_is_batch`, `gec_payroll_kind`, `gec_payroll_channel_id`, `payslip_run_id`
  (the common run, else False), `gec_payroll_manual_ack` (only when acked **and** the channel
  kind is manual). `GEC_PAYROLL_BATCH_RESERVED_VALS` (9 keys) cannot be returned by
  `_gec_bank_batch_vals`. Batches are created under `gec_payroll_batch_write_token`.

All of it is one transaction: any `UserError` rolls back postings, payments, paid state and
remembered routing.

### Preflight messages (`_gec_payroll_check_payable`, collected and raised once)

| Condition | Message (shortened) |
|---|---|
| `company.batch_payroll_move_lines` | Shared payroll journal entries are enabled … Disable Batch Payroll Move Lines |
| employee without `work_contact_id` | These employees have no work contact |
| work contact is a child contact and a NET line lacks `employee_bank_account_id` | … would be paid to the parent company's bank account |
| NET rule without `account_credit` | The NET salary rule has no credit account on the structure of |
| NET lines that are not employee lines | These NET salary lines do not match the employee's current work contact or are not on a reconcilable payment account |
| reconcilable unroutable lines (strays) | These open amounts are owed to somebody but cannot be routed by this flow |

---

## `account.payment.register` override

- gec_bank's `_get_line_batch_key(line)`: when context `gec_bank_journal_bic` is set, the
  line has a partner and no `employee_bank_account_id`, pick the commercial partner's bank
  account whose BIC has the same first 8 characters (company-less or same company), lowest
  sequence, as `partner_bank_id`. Banks are compared by BIC because Odoo 20 has no bank
  records. Otherwise core/enterprise behaviour: explicit `employee_bank_account_id`, then
  first partner bank by sequence.
- `_create_payments()` in this module, when `_gec_payroll_is_payroll_run()` (context
  `gec_payroll_run`, or any `hr.payslip` whose `move_id` is among the lines, searched with
  `sudo()`):
  1. `line_ids.lock_for_update()`; `LockError` → "being paid right now by someone else".
  2. Invalidate residual/reconciled caches.
  3. Snapshot check against `gec_payroll_residual_snapshot` (int or str keys) → "amounts
     changed while you were working; nothing was created".
  4. Partial: `amount_residual != balance` → "Partially paid payroll lines are not
     supported".
  5. Settled: zero residual → "were paid while you were working".
  6. `super()`.

The stock payslip **Pay** button goes through the same `_create_payments`, so it gets the
lock and guards 4–5, but no snapshot (step 3 is a no-op without context) and no routing,
batches, hooks or watchdog.

---

## The batch envelope

Fields: `gec_payroll_is_batch` (indexed), `gec_payroll_kind` (`salary`/`authority`),
`gec_payroll_channel_id` (`ondelete='restrict'`: a channel with batches cannot be deleted),
`payslip_run_id` (`set null`, `btree_not_null`), `gec_payroll_manual_ack`,
`gec_payroll_stale_notified`, `gec_payroll_last_notified_state` (selection built from the
sorted `GEC_BANK_HANDOFF_STATES`).

Constants (`models/account_batch_payment.py`): `GEC_PAYROLL_STALE_HOURS = 48`,
`GEC_PAYROLL_ALERT_STATES = ('pending', 'prepared')`,
`GEC_PAYROLL_URGENT_STATES = ('partial', 'failed', 'uncertain')`,
`GEC_PAYROLL_TERMINAL_STATES = ('transmitted', 'confirmed')`,
`GEC_PAYROLL_BATCH_WRITE_TOKEN = object()`, `GEC_PAYROLL_IMMUTABLE_FIELDS` = `payment_ids`,
`journal_id`, `date`, `gec_payroll_is_batch`, `gec_payroll_kind`, `gec_payroll_channel_id`,
`payslip_run_id`, `gec_payroll_manual_ack`.

- `write`: touching an immutable field on a payroll batch (or setting `gec_payroll_is_batch`
  on any batch) without `context['gec_payroll_batch_write_token'] is
  GEC_PAYROLL_BATCH_WRITE_TOKEN` raises. The token is a Python `object()` compared by
  identity, so it cannot cross RPC. `batch_type`, `payment_method_id`, `name`, `state` and
  the two notification fields stay writable.
- `account.payment.write`: changing `batch_payment_id` into or out of a payroll batch
  without the token raises; the fields core books from (`_gec_payroll_protected_fields()` =
  `_get_trigger_fields_to_synchronize()` plus `payment_method_line_id`) are locked on
  payments that sit in a payroll batch. Core does not push those changes into a posted
  journal entry, so an edit would send the bank an instruction the accounting never saw.
- `_check_gec_payroll_envelope` (`@api.constrains`): every payment must match the batch's
  `journal_id`, `payment_method_line_id == gec_payroll_channel_id`, `company_id` and `date`.
  Raises `ValidationError`.
- `_unlink_except_transmitted_payroll` (`@api.ondelete(at_uninstall=False)`): a payroll
  batch with payments cannot be deleted; it is the record of what was sent. The message
  gives the way back for a rejected salary: reset the payment to draft and cancel it, mark
  the payslip unpaid, pay again.
- Core batch constraints still apply (same journal, method, type; no zero amounts).

---

## Watchdog

`_cron_gec_payroll_stale_batches` (every 4 h, `base.user_root`):

1. Search payroll batches with `gec_payroll_manual_ack = False` and
   `gec_payroll_last_notified_state != 'confirmed'`, ordered by id.
2. Per batch, in its own savepoint: `state = _gec_payroll_handoff_state()`; skip when it
   equals the last notified state.
3. `transmitted`/`confirmed` → record the state, no activity.
4. `partial`/`failed`/`uncertain` → to-do activity for the batch creator, chatter note,
   record the state. The note warns to check with the bank before reversing or resending.
5. `pending`/`prepared` older than 48 h (measured from `create_date`, not the payment date)
   → activity "still has not been sent to the bank", chatter, record.
6. Otherwise skip without recording. Any exception is logged and the loop continues.

`_gec_payroll_handoff_state()` on the batch: no channel → `prepared` if core state is
`draft` else `transmitted`; otherwise the channel's hook; an unknown value is logged at ERROR
and mapped to `uncertain`. Activity type `mail.mail_activity_data_todo`, assigned to
`create_uid`. Dedup is by last notified state, so a batch oscillating between two states
notifies on every flip.

---

## The six provider hooks (`account.payment.method.line`, declared in `gec_bank`)

| # | Hook | Signature | Default | Style | Called |
|---|---|---|---|---|---|
| 1 | `_gec_bank_channel_kind` | `(self) → 'api' / 'file' / 'manual'` | file if in the file registry, else manual | guard-first | wizard, engine |
| 2 | `_gec_bank_check` | `(self, kind, lines) → list[str]` (`lines` = `account.move.line` recordset) | `[]` | accumulator | preflight, once per (channel, kind) |
| 3 | `_gec_bank_payment_vals` | `(self, kind, payment) → dict` | `{}` | accumulator | after the group's register run, once per posted + reconciled payment |
| 4 | `_gec_bank_batch_vals` | `(self, kind) → dict` | `{}` | accumulator | once per batch, before create |
| 5 | `_gec_bank_handoff_state` | `(self, batch)` → one of `GEC_BANK_HANDOFF_STATES`; **no network I/O** | a channel on gec_bank's transfer flow: the merge of its payments' Bank States through the handoff map (below); any other: `prepared` if `batch.state == 'draft'` else `transmitted` | guard-first | watchdog |
| 6 | `_gec_bank_extra_config_errors` | `(self) → list[str]` | `[]` | accumulator | via sealed `_gec_bank_config_errors`, once per channel |

`GEC_BANK_HANDOFF_STATES = {pending, prepared, partial, transmitted, confirmed, failed,
uncertain}`.

Contract:

- Accumulator hooks call `super()` first, return unchanged for foreign method codes, then
  append. Guard-first hooks check their own code first and delegate to `super()` for
  everything else — this is what lets several bank modules coexist without stealing
  channels.
- Hook 3 may not return the booking fields or the channel (`_gec_payroll_protected_fields()`).
  Hook 4 may not return reserved keys: `journal_id`,
  `batch_type`, `date`, `payment_ids`, `gec_payroll_is_batch`, `gec_payroll_kind`,
  `gec_payroll_channel_id`, `payslip_run_id`, `gec_payroll_manual_ack`. Hooks may raise
  `UserError`; the whole Create Payments rolls back.
- Hook 5 must inspect member payments before the batch header so a rejected member is never
  hidden by a successful header; return `uncertain` for timeouts.
- Checks every bank needs live in the engine, not in the hooks: the sender IBAN of an `api`
  channel (core config errors) and the receiver account the payment really uses
  (`_gec_payroll_check_payment_account`). A hook adds only what its own bank requires.

Helper for hook 5: `_gec_bank_merge_handoff_states(states)` turns the set of handoff states
of a batch's payments into one: `failed` (all failed) or `partial` (some), then `uncertain`,
`prepared`, `pending`, `transmitted`, and `confirmed` only when every payment is. A bank with
its own flow maps its own payment states and passes the set; a channel on gec_bank's
transfer flow gets it from the default (next section).

### Handoff states of transfer-flow channels

A bank that opts into gec_bank's shared transfer flow (`_gec_bank_transfer_flow`: `tbc_bank`,
`bog_bank`) does not write hook 5. gec_bank's default `_gec_bank_handoff_state` maps each
member payment's `gec_bank_state` through `_gec_bank_handoff_map()` (an unmapped state counts
as `uncertain`) and merges the set:

| `gec_bank_state` | Handoff state |
|---|---|
| `pending`, `awaiting_approval`, `approved` | `prepared` |
| `sending`, `unknown` | `uncertain` (a send ends within about a minute, so a payment still sending when the watchdog looks crashed mid-call) |
| `sent` | `transmitted` |
| `confirmed` | `confirmed` |
| `failed` | `failed` |

A bank extends the map by overriding `_gec_bank_handoff_map` (BOG: `awaiting_confirmation` →
`prepared`, `created` → `pending`) and the set by overriding
`_gec_bank_transfer_handoff_states` (BOG adds a batch whose bulk send is `sending` or
`unknown` as `uncertain`). Both follow the accumulator style: `super()` first, then own code.

### Minimal adapter

```python
from odoo import _, models

ACME_CODE = "acme_transfer"
ACME_HANDOFF = {"draft": "prepared", "sending": "pending", "sent": "transmitted",
                "done": "confirmed", "failed": "failed", "unknown": "uncertain"}


class AccountPaymentMethodLine(models.Model):
    _inherit = "account.payment.method.line"

    def _gec_bank_channel_kind(self):
        if self.code == ACME_CODE:
            return "api"
        return super()._gec_bank_channel_kind()

    def _gec_bank_extra_config_errors(self):
        errors = super()._gec_bank_extra_config_errors()
        if self.code == ACME_CODE and not self.journal_id.acme_connection_id:
            errors.append(_("No Acme connection is configured for %s.",
                            self.journal_id.display_name))
        return errors

    def _gec_bank_payment_vals(self, kind, payment):
        vals = super()._gec_bank_payment_vals(kind, payment)
        if self.code != ACME_CODE:
            return vals
        bic = payment.partner_bank_id.bank_bic
        vals["acme_transfer_type"] = "internal" if (bic or "")[:8] == "ACMEGE22" else "national"
        return vals

    def _gec_bank_batch_vals(self, kind):
        vals = super()._gec_bank_batch_vals(kind)
        if self.code == ACME_CODE:
            vals["acme_salary_package"] = kind == "salary"
        return vals

    def _gec_bank_handoff_state(self, batch):
        if self.code != ACME_CODE:
            return super()._gec_bank_handoff_state(batch)
        return self._gec_bank_merge_handoff_states({
            ACME_HANDOFF.get(state, "uncertain") for state in batch.payment_ids.mapped("acme_state")})
```

The example is a bank with its own flow, so it writes hook 5 itself. A bank that opts into
gec_bank's transfer flow writes none (see "Handoff states of transfer-flow channels").

| Adapter | Hooks | What its hooks add |
|---|---|---|
| `basis_bank` | 1, 2, 3, 4, 5, 6 | Recipient bank (BIC) required on every account; GEL, BIC and memo on each payment; treasury transfer by Treasury Code; salary-package flag on the batch; batch state from payments and the Basis batch header (own flow, own `_gec_bank_handoff_state`) |
| `tbc_bank` | 1, 2, 3, 6 and the opt-in | 9-digit Treasury Code and Georgian IBAN only; treasury transfer by Treasury Code; batch state from each payment's Bank State through gec_bank's handoff map |
| `bog_bank` | 1, 2, 3, 6 and the opt-in | Refuses Treasury Code recipients (no treasury transfers); Georgian IBAN with a bank code; domestic transfer, IsSalary for salaries only, BULK up to 10,000 GEL; batch state from each payment's Bank State through the handoff map, extended for BOG's own states and its bulk send |

The user sends each batch from its own form (**Send to Basis Bank**, **Send to TBC** /
**Approve TBC Transfers**, **Send to BOG** / **Send One by One**); Pay Salaries only opens the
list of created batches.

Journal requirements for a channel: bank journal, the provider's outbound method enabled, a
reconcilable Outstanding Payments account different from the journal's default account, the
sender IBAN for an `api` channel, the connection configured by the bank module, recipient
accounts trusted.

---

## Wizard internals (`hr.payroll.pay.wizard`)

- `default_get`: payslips from context `gec_payroll_payslip_ids`, else `payslip_ids`
  commands, else `active_ids` only when `active_model == 'hr.payslip'` (the run button
  passes run ids); filter `validated` and `net_wage > 0`; single company; `default_channel`;
  common run (else empty); one line per payslip with `amount = sum(-residual of employee
  lines)` and `channel = employee.sudo().gec_payroll_channel_id or default`; authority rows
  aggregated by `(partner_id, account_id)` with the default channel.
- Computed: `warning` from `_gec_payroll_blocked_accounts()` (accounts of unroutable lines);
  `manual_ack_required` when any row channel is `manual`.
- `_onchange_channel_id` fills only rows with an empty channel.
- `action_pay`: rows exist; every row has a channel; manual ack if required; build the
  routing dicts; `_gec_remember_routing()` writes `employee.sudo().gec_payroll_channel_id`
  for rows that differ; then `_gec_payroll_pay(...)`. Remembering happens inside the same
  transaction and rolls back with it.
- Views: employees list editable, multi-edit, grouped by channel, no create/delete;
  authorities page hidden when empty; the manual-ack checkbox visible only when required;
  confirmation dialog on Create Payments.

`_gec_remember_routing` checks no group itself: only Payroll Administrators can open the wizard
(its access rows), the group the employee field is restricted to.

---

## Security

| Object | Access |
|---|---|
| `hr.payroll.pay.wizard`, `.line`, `.authority` | Full CRUD for `hr_payroll.group_hr_payroll_manager` only |
| `hr.employee.gec_payroll_channel_id` | Field-level `groups=hr_payroll.group_hr_payroll_manager`; form and list views also gated |
| Payslip button, list action, run kanban buttons | `hr_payroll.group_hr_payroll_manager` |
| Batch `payslip_run_id` in views | `hr_payroll.group_hr_payroll_user` |
| Settings | Anyone who can open Payroll settings |
| Record rules | None added |
| `sudo()` use | Batch count on the run (batches are accounting objects), payslip lookup in the register override (the stock Pay button is used by accountants), employee channel read/write in the wizard |

Implied groups: Payroll Administrator implies Payroll Officer, Payroll Assistant (payslips,
runs) and HR Manager. Accounting rights (`account.group_account_invoice` for batches,
payments, the register) come from the user's own accounting group; without them the pay flow
stops with an access error.

---

## Integration notes

| Module | Touchpoint |
|---|---|
| `basis_bank` | Hooks 1, 2, 3, 4, 5, 6; hook 2 names every recipient whose bank account has no BIC; the user sends from the batch form with **Send to Basis Bank** and an OTP |
| `tbc_bank` | Hooks 1, 2, 3, 6 for `tbc_transfer`, on gec_bank's transfer flow (handoff from the payments' Bank State); the user sends with **Send to TBC** (one TBC request per payment) and approves the batch as a whole with **Approve TBC Transfers** |
| `bog_bank` | Hooks 1, 2, 3, 6 for `bog_transfer`, on gec_bank's transfer flow, with its own handoff map entries; refuses State Treasury rows, so income tax must be routed to another channel; the user sends with **Send to BOG** (one bulk call) or **Send One by One** |
| `geo_payroll` | No dependency either way. Its GE chart configurator books NET on `310310` (reconcilable payable, employee partner via `employee_move_line`), pension on `332010` with the Pension Agency partner, PIT on the Payable `331320` with the State Treasury partner, and benefit deductions with a Vendor on the vendor's payable account — all of them become authority rows. Its `account.payment.register._reconcile_payments` override flips a slip to `paid` when its NET lines settle; under the salary-run context this may happen before `_gec_payroll_assert_settled`, which only acts on slips still not paid. Its `hr.payslip.action_register_payment` override rebuilds the **stock** Pay button (all partnered payable-class lines, grouped) and still passes through this module's `_create_payments` lock |
| `hr_payroll_account` | Stock Pay button left in place; the bridge adds its own button next to it. `batch_payroll_move_lines` must be off. Its enterprise `_reconcile_payments` flips a slip to `paid` when all lines settle under `hr_payroll_payment_register` context |
| `account_batch_payment` | File methods registered in `_get_methods_generating_files()` are `file` channels automatically; their batches keep the standard Validate/file export |

---

## Tests

Run from the project root:

```bash
./odoo-bin -d <test-db> -i gec_payroll_bank --test-tags /gec_payroll_bank --stop-after-init
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_payroll_bank.py` | 34 | Channel classification and configuration; line selection; the guards (untrusted bank, missing work contact, changed contact, partner-less liability, currency); the engine (draft posting, one payment/one batch, payment date, two banks, authority batches, aggregation across payslips, same-bank recipient); register guards (snapshot, trigger fields, reserved keys); wizard resolution; batch immutability; the watchdog (48 h stale, failed, terminal-then-failed, manual-ack skip, state merge); payment booking-field lock |
| `tests/test_basis_adapter.py` | 2 | Mixed member result → partial; recipient without BIC refused. Skips when `basis_bank` is not installed |
| `tests/test_tbc_adapter.py` | 9 | api kind, connection checks, treasury transfers, watchdog state per payment, a full salary+pension+income-tax run, two payslips of one employee, foreign IBAN, 9-digit treasury code, batch send/approve buttons. Skips when `tbc_bank` is not installed |
| `tests/test_bog_adapter.py` | 9 | api kind, connection checks, IsSalary/BULK cap, watchdog state, salary+pension run, income tax refused, foreign IBAN, bank code required, batch send buttons. Skips when `bog_bank` is not installed |

Fixture (`TestPayrollBank`): NET rule with `employee_move_line=True` on a reconcilable
`liability_current` account, two bank journals with outstanding accounts, two employees, and
a helper that adds a partnered negative pension rule. On Odoo 20 salary rules take
`category_ids` (Many2many) and `struct_ids`, not `category_id` / `struct_id`; the payslip
keeps `struct_id`.

Not covered: `action_pay`, `_gec_remember_routing`, row amounts in `default_get`, a hook
returning an action, the "choose a bank" path, the child-contact check, the
`batch_payroll_move_lines` guard, the envelope constraint.

---

## Known limitations and open points

| Item | Note |
|---|---|
| Company currency only; single company; full settlement only | By design |
| Only bank-account or Treasury Code recipients; partner-less or non-reconcilable liabilities are excluded or block | Taxes other than payroll income tax are settled elsewhere |
| Authority routing not remembered | No field |
| Header Default Bank does not re-route filled rows | `_onchange_channel_id` fills empty rows only |
| Watchdog skips only batches last seen `confirmed` | A batch stuck in another state is read every run |
| Threshold from `create_date`, not payment date | |
| Stock Pay button still reachable without routing or batches | Operational decision |
| Future extension points | Pre-create register-values hook (journal-synchronised fields), payment-to-batch split hook (bank transfer-count limits), foreign-currency payroll, partial payslips, transaction-safe post-commit auto-submit |

---

## Invariants a bank module must not break

- The standard `account.payment.register._create_payments()` remains the accounting
  authority; never replace it with custom payment or move creation.
- Check bank-specific account data (BIC, IBAN format) on `payment.partner_bank_id`, the
  account Odoo actually chose, not the wizard's guess. The bridge already refuses a missing
  or untrusted one.
- Never perform network I/O inside a hook; send from a committed batch through a later
  explicit action.
- Never bypass the write token, alter `payment_ids` directly, or move a payment between
  batches.
- Always call `super()` in accumulator hooks and never answer for another provider's method
  code.
- Treat `paid` on the payslip as accounting state, never as bank confirmation; map timeouts
  to `uncertain`.
