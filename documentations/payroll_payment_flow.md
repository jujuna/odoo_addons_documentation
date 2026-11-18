# Payroll Payment Flow — Paying Payslips and Settling the Salary Entry

> **Modules:** `hr_payroll_account` + `account.payment.register`; custom `geo_payroll`, `gec_localization`, `gec_payroll_bank`, `basis_bank` | **Path:** [`enterprise/hr_payroll_account/`](../enterprise/hr_payroll_account/), [`custom_addons/gec_odoo_modules/gec_payroll_bank/`](../custom_addons/gec_odoo_modules/gec_payroll_bank/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

"Paying a payslip" means two different things:

1. **Payroll state:** the payslip moves from *Validated* to *Paid*.
2. **Accounting:** the salary entry's liabilities (net salary, pension, income tax) are settled by
   real `account.payment` records, reconciled against the entry, and sent to a bank.

Stock Odoo 20 does only the first. The GEC design does both with standard payments: every
liability on the payslip entry is a reconcilable Payable line with a partner, and the **Pay
Salaries** wizard pays them through the standard payment register, marks the payslips Paid and
hands sealed batches to the bank module. This doc explains the stock mechanics first, then the
design built on them.

---

## Stock Odoo 20: How Paying Works

| Step | What happens | Source |
|---|---|---|
| 1. Salary entry | At validation each rule line becomes a journal item. A rule with **Set employee on account line** (`employee_move_line`) gets the employee's work contact as partner; any other line gets the rule's third-party partner. An employee with several bank accounts gets one NET item per account | [_prepare_line_values](../enterprise/hr_payroll_account/models/hr_payslip.py#L123), [hr_salary_rule.py:37](../enterprise/hr_payroll_account/models/hr_salary_rule.py#L37) |
| 2. **Pay** button | On a validated payslip; opens the payment report wizard | [hr_payslip_views.xml:53](../enterprise/hr_payroll/views/hr_payslip_views.xml#L53) |
| 3. Report + Mark as Paid | Exports manually or as CSV, stamps `paid_date`, then `action_payslip_paid()` sets state *Paid*. **No accounting entry is made** | [mark_as_paid](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162), [action_payslip_paid](../enterprise/hr_payroll/models/hr_payslip.py#L1062) |
| 4. Settle the entry | Left to the accountant (payments, statement matching) | — |

Payment-register plumbing is still in `hr_payroll_account`, but nothing in a generic install
calls it. Only `l10n_au_hr_payroll_account` re-adds a Register Payment action
([hr_payslip.py:491](../enterprise/l10n_au_hr_payroll_account/models/hr_payslip.py#L491)).
Details of the entry itself: [`hr_payroll_account.md`](hr_payroll_account.md).

### Payment register rules that shape any payroll design

- **Only Receivable and Payable lines are payable**
  ([_get_valid_payment_account_types](../addons/account/models/account_payment.py#L247)). Context
  `hr_payroll_payment_register` adds Current Liabilities
  ([account_payment.py:11](../enterprise/hr_payroll_account/models/account_payment.py#L11)).
- **One account type per wizard.** Lines of two types raise "You can't register payments for both
  inbound and outbound moves at the same time" — misleading, but that is the check
  ([account_payment_register.py:1049](../addons/account/wizard/account_payment_register.py#L1049)).
- **Batches** are per partner, account, currency and bank account; `hr_payroll_account` takes the
  bank account from the journal item, else the partner's first account
  ([_get_line_batch_key](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L11)).
- **Every journal item keeps a residual until it is reconciled**, expense lines included
  ([account_move_line.py:1212](../addons/account/models/account_move_line.py#L1212)). A line on a
  non-reconcilable account is never closed, so "all lines at zero" never happens on a salary
  entry. The stock paid transition in `_reconcile_payments` waits for exactly that
  ([account_payment_register.py:36](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L36)),
  so it does not fire.

---

## The GEC Design

### 1. Booking layout (net-payable)

Configured by `geo_payroll` on companies using the `l10n_ge` chart
([account_chart_template.py:13](../custom_addons/gec_odoo_modules/geo_payroll/models/account_chart_template.py#L13)):

| Rule | Debit | Credit | Partner on the item |
|---|---|---|---|
| Earnings (BASIC, daily work logs, timesheets, units) | 720100 Salary expense | — | — |
| Overtime work logs (WORKLOG_OT) | 720200 | — | — |
| Bonus and benefits in kind | 720110 | — | — |
| Termination payment | 720700 | — | — |
| PENSION_EE (negative total) | 332010 Pension payable (posts as a credit) | — | Pension Agency |
| PIT (negative total) | 331320 PIT transit (posts as a credit) | — | State Treasury |
| PENSION_ER | 721000 Pension expense | 332010 Pension payable | Pension Agency |
| NET | — | 310310 Salaries payable | The employee (`employee_move_line`) |
| Benefit deductions | 720900, or the benefit vendor's payable when the program has a vendor | — | Vendor |

`gec_localization` sets the account types this needs
([template_ge.py:9](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L9)):
310310 and 332010 become **Payable + reconcilable**, 331320 is a new Payable, reconcilable,
non-trade PIT account ([account.account-ge.csv:10](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.account-ge.csv#L10)),
and 331310 stays for withholding taxes, not reconcilable. All payable legs share one account
type, so salary, pension and income tax can go through the payment register.

The authority partners are data: Pension Agency and State Treasury, the latter with treasury code
101001000 ([res_partner_data.xml:13](../custom_addons/gec_odoo_modules/geo_payroll/data/res_partner_data.xml#L13)).

The configurator skips any company whose base rules already carry an account
([:115](../custom_addons/gec_odoo_modules/geo_payroll/models/account_chart_template.py#L115)): an
accountant's mapping survives upgrades, and a mapping change in code does not reach configured
companies — remap their rules by hand.

### 2. Pay Salaries (`gec_payroll_bank`) — the production path

Buttons on the payslip form and list and on the pay-run card, for **Payroll Administrators**
([hr_payslip_views.xml:12](../custom_addons/gec_odoo_modules/gec_payroll_bank/views/hr_payslip_views.xml#L12));
the payments are created as the user, so the user also needs accounting rights (Invoicing or
higher), assigned separately.

1. **Select** validated payslips with a positive net ([action_gec_pay_salaries](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L18)).
   The wizard proposes a bank channel per employee and per authority.
2. **Pre-flight** ([_gec_payroll_check_payable](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L144))
   refuses the run, listing every reason at once: batch payroll entries enabled, employees without
   work contact, NET rule without credit account, NET items that are not the employee's or not on
   a reconcilable payment account, and open reconcilable amounts owed to somebody the flow cannot
   route.
3. **Pay.** Draft entries are posted, then one payment-register run per channel, purpose, account
   type and currency ([_gec_payroll_pay](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L303)):
   - **Authority legs** first, grouped per partner across payslips, without the payroll context
     ([_gec_payroll_register_context](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L279)).
   - **Salaries**: the employee's NET items (NET account and employee partner,
     [_gec_payroll_employee_lines](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L75)),
     one payment per payslip entry, with the payroll context.
4. **Check and mark Paid.** Every NET item and every selected authority item must be closed, or
   nothing is created; then `action_payslip_paid()` runs
   ([_gec_payroll_assert_settled](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip.py#L385)).
5. **Seal batches** per bank, purpose and currency and hand them to the bank module. A watchdog
   cron, every 4 hours, flags batches nobody sent or the bank rejected
   ([ir_cron_data.xml:4](../custom_addons/gec_odoo_modules/gec_payroll_bank/data/ir_cron_data.xml#L4)) — "Paid" in Odoo is not
   "money moved".

**Basis Bank channel.** A salary batch in GEL from one sender account goes out as a salary package
(op 5); other batches as GEL, treasury or single transfers
([_compute_basisbank_endpoint](../custom_addons/gec_odoo_modules/basis_bank/models/account_batch_payment.py#L73)).
A payment to a partner with a treasury code becomes a treasury transfer carrying that code, with
no receiver account ([_gec_payroll_payment_vals](../custom_addons/gec_odoo_modules/basis_bank/models/account_payment_method_line.py#L68)).
Transmission, statements and matching: [`basis_bank.md`](basis_bank.md).

### 3. Register Payment (`geo_payroll`) — one payslip, standard wizard

A **Register Payment** button on validated payslips with their own entry
([hr_payslip_views.xml:94](../custom_addons/gec_odoo_modules/geo_payroll/views/hr_payslip_views.xml#L94),
[action_register_payment](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_account.py#L145)):

- Refuses paid payslips, unposted entries, untrusted employee bank accounts, payslips without an
  open NET item, and a NET credit account that is not reconcilable.
- Opens the standard wizard on every open line of a valid account type on a reconcilable account;
  a payable line without partner stops it, naming the rule.
- Marks the payslip Paid as soon as its **NET items** are settled, even while authority legs stay
  open ([account_payment_register.py:7](../custom_addons/gec_odoo_modules/geo_payroll/models/account_payment_register.py#L7)).

It does not create bank batches; use it for a one-off payment or an off-cycle slip.

### 4. Corrections, refunds and releasing an entry (2026-10-10)

A correction family (origin, refund, correction) is booked and paid **once**:

- Validating a refund or a correction posts the family's draft entries and reconciles them:
  the refund against the origin first, then what is left of the refund against the correction
  ([_gec_settle_correction_family](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_account.py#L100)).
  NET lines match per account, the other legs per partner. Both payment paths then pay only what
  is still open.
- Origin paid at 1,000.00 (1,020.00 out), corrected to 1,100.00: the correction pays **102.00**
  (NET 78.40, PIT 19.60, pension 2.00 + 2.00); origin, refund and correction end Paid.
- Origin never paid: the refund cancels it. Register Payment on it says it was "corrected or
  refunded", Pay Salaries leaves it out of its run
  ([_compute_gec_payroll_can_pay](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/hr_payslip_run.py#L21)),
  and paying the correction marks the whole family Paid.
- Correction down after the origin was paid: nothing is paid; the correction and refund end Paid,
  the overpaid net stays open on the employee's net-payable account (overpaid PIT and pension on
  the authority accounts) and core flags the correction "negative net to report". Recover it by
  hand on the next payslip: the automatic deduction is not built yet.
- The "partially paid" guard of Pay Salaries ignores lines matched only with other payslip
  entries ([_create_payments](../custom_addons/gec_odoo_modules/gec_payroll_bank/models/account_payment_register.py#L8)).

Releasing a payslip's entry (Cancel, list Set to Draft, pay-run reset) is refused when
([_gec_release_journal_entries](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_account.py#L218)):

| Case | Message points to |
|---|---|
| The entry was posted and the user has no accounting (Invoicing) rights | an accounting user, as core's Cancel |
| The slip still has a validated refund or correction | cancel the correction and its refund first |
| An entry line is matched with a payment or a bank statement line | cancel or unreconcile that payment first |

Matches inside the correction family are dropped automatically. So Mark Unpaid followed by
Cancel can no longer pay a salary twice while its transfer is at the bank, and undoing a Correct
needs Invoicing rights once the family's entries are posted.

---

## Configuration Checklist

1. Company on the `ge` chart with `gec_localization` installed; 310310, 332010 and 331320 Payable
   and reconcilable.
2. NET rule of each structure credits the net-payable account with **Set employee on account
   line** on; pension and PIT rules carry the Pension Agency / State Treasury partners.
3. **Batch Payroll Move Lines** off (Pay Salaries refuses shared entries).
   Pay Salaries also refuses a draft payslip entry dated in a locked period, naming the payslip and the lock, instead of letting Odoo move it to a later date.
4. Employees: a work contact and a trusted bank account (`allow_out_payment`).
5. Pension Agency: a bank account. State Treasury: its treasury code.
6. Payroll → Configuration → Settings → **Default Salary Bank**; employee **Salary Bank** where it
   differs.
7. The payroll administrator also holds an accounting group.

---

## Gotchas & Non-Obvious Behavior

- **The stock Pay button never touches accounting.** Paid payslips from the report wizard leave
  the salary entry open.
- **The stock "paid when settled" transition is dead** (residuals on expense lines, above). Any
  flow built on `hr_payroll_payment_register` needs its own paid transition, as `geo_payroll` and
  `gec_payroll_bank` have.
- **Register Payment on several payslips crashes** when a grouped authority payment reconciles
  lines of two entries: core `_reconcile_payments` posts a message on both payslips at once and
  `message_post` requires one record ([account_payment_register.py:34](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L34),
  [mail_thread.py:2308](../addons/mail/models/mail_thread.py#L2308)). The form button is
  single-record; Pay Salaries avoids it by paying authorities without the payroll context.
- **The payroll IBAN check never runs.** `hr_payroll_account` filters payslips on state `done`,
  which does not exist in 20.0 ([hr_payroll_payment_report_wizard.py:11](../enterprise/hr_payroll_account/wizard/hr_payroll_payment_report_wizard.py#L11)).
- **Older payslips on 331310** cannot pay their income tax through Pay Salaries; the wizard warns
  about them instead of blocking the run.
- **A work contact that is a child contact** would send the salary to the parent's bank account;
  the pre-flight refuses it.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_payroll_account.md`](hr_payroll_account.md) — how the salary entry is built
- [`geo_payroll.md`](geo_payroll.md) — Georgian structures, tax rules and account mapping
- [`basis_bank.md`](basis_bank.md) — sending batches to Basis Bank
- [`gec_payroll_bank` README](../custom_addons/gec_odoo_modules/gec_payroll_bank/README.md) — Pay Salaries for users
- [`hr_payroll.md`](hr_payroll.md) — payslip states
- [`../BASIS_SALARY_NET_PAYMENT_HANDOFF.md`](../BASIS_SALARY_NET_PAYMENT_HANDOFF.md) — the handoff that chose the net-payable layout
