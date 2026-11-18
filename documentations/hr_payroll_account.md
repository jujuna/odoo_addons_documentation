# Payroll Accounting — From Payslip to Journal Entry

> **Modules:** `hr_payroll_account` | **Path:** [`enterprise/hr_payroll_account/`](../enterprise/hr_payroll_account/)
> Siblings covered here: `hr_payroll_account_iso20022` (SEPA/ISO 20022 salary payments — in v20 it depends on `hr_payroll` + `account_iso20022`, **not** on this module), `hr_payroll_expense` (expense reimbursement through payslips), `project_hr_payroll_account` (project stat button only).
>
> **Verified against Odoo 20 source: 2026-09-22.** Custom wage/work-log implementation plan: [`../PAYROLL_WAGE_TYPES_PLAN.md`](../PAYROLL_WAGE_TYPES_PLAN.md).

## What It Does & Why It Exists

`hr_payroll_account` is the bridge between HR payroll and the general ledger — the "money-out" side of payroll. Without it, a validated payslip is just an HR document; with it, validating a payslip also produces a **draft** `account.move` in a dedicated salary journal, built line by line from the debit/credit accounts configured on each salary rule. It auto-installs whenever `hr_payroll` and `accountant` are both installed ([__manifest__.py:39](../enterprise/hr_payroll_account/__manifest__.py#L39)). This is the module a Georgian implementation must configure (accounts on rules, journal on structure) before payroll can hit the GL.

In v20 this module no longer owns the payment side. The **Pay** button on the payslip belongs to `hr_payroll` and opens the payment-report wizard; the register-payment plumbing that used to live here is now dormant code kept for localizations (see [Paying Payslips](#paying-payslips)).

---

## The Big Picture — How It Works

```
Draft payslip (computed lines)
        |  "Validate" button (= action_payslip_done)
        v
Payslip state: validated  +  DRAFT account.move in structure's salary journal
        |  accountant reviews & posts the move (manual)
        v
Posted move
        |  "Pay" button (hr_payroll) -> hr.payroll.payment.report.wizard
        v
Manual / CSV / SEPA payment file, then "Mark as Paid" in the wizard
        v
Payslip state: paid (paid_date = wizard's effective date)
```

The validate button keeps its base label **Validate** in v20 — this module only re-renders it to add the confirm dialog and the PDF context ([hr_payslip_views.xml:20](../enterprise/hr_payroll_account/views/hr_payslip_views.xml#L21)); the v19 "Create Draft Entry" relabel is gone. [action_payslip_done()](../enterprise/hr_payroll_account/models/hr_payslip.py#L34) runs the base HR validation, then calls `_action_create_account_move()` for every slip that has a journal. The move is **created in draft, never auto-posted** — the cancel/refund tests post it explicitly before exercising anything downstream ([test_hr_payroll_account.py:626](../enterprise/hr_payroll_account/tests/test_hr_payroll_account.py#L626)).

### Key Decision Points

- **Per-slip vs per-batch moves** — company setting `batch_payroll_move_lines`, labelled **Anonymize Journal Entries** in v20. Off (default): one move per payslip. On: all slips of a pay run are merged into one move per (journal, month), lines aggregated and anonymized.
- **Which accounts** — set per salary rule (`account_debit` / `account_credit`, both company-dependent). Rules without accounts are silently skipped in the move.
- **Accounting date** — payslip field `date` ("Accounting Date"), **computed and stored** in v20 ([hr_payslip.py:20](../enterprise/hr_payroll_account/models/hr_payslip.py#L20)): `create_date` for a refund slip, `done_date` for a correction slip, otherwise end of month of `date_to`. It stays editable; if cleared, move construction falls back to end of month of `date_to`.
- **How the NET is booked** — the NET line is booked at its full total minus every rule flagged `not_computed_in_net`.

---

## Rule → Journal Item Mapping (the core)

Everything is driven by fields added to `hr.salary.rule` ([hr_salary_rule.py](../enterprise/hr_payroll_account/models/hr_salary_rule.py)):

| Field | Effect on the journal entry |
|---|---|
| `account_debit` / `account_credit` | Company-dependent. Positive rule total → debit on `account_debit`, credit on `account_credit`. Negative total swaps sides. A rule may have one, both, or neither. |
| `not_computed_in_net` | Reduces the amount booked for the **NET** line (accounting only — payslip NET itself is untouched). The flagged rule must carry its own accounts to be booked independently ([hr_salary_rule.py:17](../enterprise/hr_payroll_account/models/hr_salary_rule.py#L17)). |
| `split_move_lines` | Journal item label = payslip **line** name instead of rule name, so lines don't merge (used by default on deduction/attachment/assignment/child-support/reimbursement rules, [hr_salary_rule_data.xml](../enterprise/hr_payroll_account/data/hr_salary_rule_data.xml)). |
| `employee_move_line` | Puts the employee's work contact as partner on the journal item and prevents cross-employee merging (set by default on the NET rule, [hr_salary_rule_data.xml:24](../enterprise/hr_payroll_account/data/hr_salary_rule_data.xml#L24)). Ignored in batch mode, and hidden from the rule form when batch mode is on ([hr_salary_rule_views.xml:17](../enterprise/hr_payroll_account/views/hr_salary_rule_views.xml#L17)). |
| `debit_tag_ids` / `credit_tag_ids` | Tax report grids stamped on the debit/credit journal item — this is how payroll amounts land in tax reports without real taxes ([hr_salary_rule.py:20](../enterprise/hr_payroll_account/models/hr_salary_rule.py#L20)). Exposed per payslip line as computed fields meant to be overridden by localizations ([hr_payslip_line.py:9](../enterprise/hr_payroll_account/models/hr_payslip_line.py#L9)). |
| `analytic_distribution` | Rule-level analytic distribution (rule inherits `analytic.mixin`, [hr_salary_rule.py:9](../enterprise/hr_payroll_account/models/hr_salary_rule.py#L9)). |
| `partner_id` (base field) | Third party of the rule (tax office, pension fund…) — becomes the journal item partner when `employee_move_line` is off ([hr_payslip_line.py:46](../enterprise/hr_payroll/models/hr_payslip_line.py#L46)). |

### Move construction, step by step

Values are built by [_get_account_move_vals()](../enterprise/hr_payroll_account/models/hr_payslip.py#L45) and written by [_action_create_account_move()](../enterprise/hr_payroll_account/models/hr_payslip.py#L114) — the split is new in v20 and is what lets the pay-run preview wizard render the entry without creating it.

1. **Scope widening:** if a slip belongs to a batch and the batch has any validated/cancelled slip ([_are_payslips_ready](../enterprise/hr_payroll/models/hr_payslip_run.py#L622)), *all* slips of the batch are pulled in. Then filter: `state == 'validated'` with no existing `move_id`, **or** `state == 'draft'` when batch mode is on; and the structure must have a journal ([hr_payslip.py:55](../enterprise/hr_payroll_account/models/hr_payslip.py#L55)).
2. **Grouping:** batch mode → one bucket per (journal, month); normal mode → one bucket per slip ([hr_payslip.py:64](../enterprise/hr_payroll_account/models/hr_payslip.py#L64)). Month key = `slip.date or end_of(date_to, 'month')`.
3. **Line generation** per slip ([_prepare_slip_lines](../enterprise/hr_payroll_account/models/hr_payslip.py#L164)): iterate **all** payslip lines (the v19 `category_id` filter is gone); skip zero totals; for the `NET` line subtract every `not_computed_in_net` rule total ([hr_payslip.py:176](../enterprise/hr_payroll_account/models/hr_payslip.py#L176)); book debit account side, then credit account side. Merging is done through a `line_index` keyed on **(label, account, analytic distribution)** and a side/tax-grid check ([hr_payslip.py:170](../enterprise/hr_payroll_account/models/hr_payslip.py#L170), [hr_payslip.py:198](../enterprise/hr_payroll_account/models/hr_payslip.py#L198)) — unless `employee_move_line` forces separation (non-batch mode). The index is threaded through the whole bucket, so a line that could not merge earlier can still be the merge target of a later rule.
4. **Multi-bank split:** if the rule has `employee_move_line` and the employee has several bank accounts, the NET amount is split into one journal item per bank account — including salary-attachment beneficiary bank accounts — using the employee's fixed/percentage salary allocations ([hr_payslip.py:130](../enterprise/hr_payroll_account/models/hr_payslip.py#L130), allocation math in [_compute_salary_allocations](../enterprise/hr_payroll/models/hr_payslip.py#L2514)). Each item stores `employee_bank_account_id`, a field this module adds to `account.move.line` ([account_move_line.py:7](../enterprise/hr_payroll_account/models/account_move_line.py#L7)).
5. **Balancing:** if debits ≠ credits, an **Adjustment Entry** line on the journal's `default_account_id` absorbs the difference; missing default account raises ([_prepare_adjust_line](../enterprise/hr_payroll_account/models/hr_payslip.py#L260)).
6. **Creation:** moves created with `sudo()` ([hr_payslip.py:305](../enterprise/hr_payroll_account/models/hr_payslip.py#L305)) — payroll officers don't need account-creation rights. Slips get `move_id` and `date` written back; in batch mode the run gets `move_id` too ([hr_payslip.py:117](../enterprise/hr_payroll_account/models/hr_payslip.py#L117)).

Move header: `ref` = "Month Year" of the period; `narration` is **always empty** in v20 — the per-slip "id - employee name" listing was removed, so payslip moves no longer leak employee names in any mode ([hr_payslip.py:86](../enterprise/hr_payroll_account/models/hr_payslip.py#L86), asserted by [test_anonymized_payruns.py:341](../enterprise/hr_payroll_account/tests/test_anonymized_payruns.py#L341)).

### Previewing the entry before validation

In batch mode a pay run in state `01_ready` shows a **Journal Entry (Preview)** stat button ([hr_payslip_run_views.xml:21](../enterprise/hr_payroll_account/views/hr_payslip_run_views.xml#L21)). It opens `mock.account.move.wizard`, a transient that calls `_get_account_move_vals()` on the run's slips and renders the first proposed move — account, partner, label, debit, credit, tax grids — without writing anything ([mock_account_move_wizard.py:13](../enterprise/hr_payroll_account/wizard/mock_account_move_wizard.py#L13)). It is the only place a user sees the entry before it exists, so it is the practical way to catch missing rule accounts and runaway Adjustment Entries. The module's whole `security/ir.access.csv` exists just to grant payroll users read/create/write on this wizard and its line model ([ir.access.csv:2](../enterprise/hr_payroll_account/security/ir.access.csv#L2)).

### Taxes and tax grids

There are no `tax_ids` on salary rules. Instead, each generated journal item copies the **default taxes of the GL account** (`account.tax_ids`) ([hr_payslip.py:161](../enterprise/hr_payroll_account/models/hr_payslip.py#L161)) and carries the rule's debit/credit **tax grids**. So payroll-to-tax-report wiring is done with grids on rules, not taxes.

---

## Journal Resolution & Required Configuration

| Where | What | Source |
|---|---|---|
| `hr.payroll.structure.journal_id` | The **only** journal source. Company-dependent, required in the form view, computed-with-override: falls back to the journal of `hr_payroll.default_structure`, else the chart template's `hr_payroll_account_journal`. | [hr_payroll_structure.py:11](../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L11) |
| `hr.payslip.journal_id` | Related (read-only) to `struct_id.journal_id`. | [hr_payslip.py:15](../enterprise/hr_payroll_account/models/hr_payslip.py#L15) |
| Journal currency | Constraint: must be the company currency — payroll entries are always company-currency ([hr_payroll_structure.py:34](../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L34)). |
| Journal deletion | Blocked while any pay structure references it ([account_journal.py:10](../enterprise/hr_payroll_account/models/account_journal.py#L10)). |

**Install hooks:** only a pre-init hook survives in v20 — it renames any pre-existing journal coded `SLR` (to `SLR0`, `SLR1`…) to free the code ([__init__.py:9](../enterprise/hr_payroll_account/__init__.py#L9)). The v19 `_hr_payroll_account_post_init` hook is **gone**: the miscellaneous "Salaries" journal (code `SLR`) and the structure→journal assignment are now declared as chart-template data ([account_chart_template.py:78](../enterprise/hr_payroll_account/models/account_chart_template.py#L78), [:89](../enterprise/hr_payroll_account/models/account_chart_template.py#L89)) and applied generically by `account` when the module is installed into a company that already has a chart template ([addons/account/models/ir_module.py:72](../addons/account/models/ir_module.py#L72)). The structure template now covers **every** structure, not the three hardcoded XML ids of v19, and newly created structures get the journal via `_compute_journal_id` on create ([hr_payroll_structure.py:27](../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L27)).

**Localization hook:** after loading a chart template, `_load_payroll_accounts` looks for `_configure_payroll_account_<template_code>` ([account_chart_template.py:20](../enterprise/hr_payroll_account/models/account_chart_template.py#L20)). In v20 this only fires when the `chart_template_load` context key is set ([account_chart_template.py:15](../enterprise/hr_payroll_account/models/account_chart_template.py#L15)) — i.e. on a real chart-template installation, not on the generic module-install data reload. The generic helper [_configure_payroll_account()](../enterprise/hr_payroll_account/models/account_chart_template.py#L26) maps accounts and tax grids onto rules per company; it now accepts `account_refs` (XML ids) as an alternative to `account_codes` (code prefixes). This is exactly what the ~30 `l10n_*_hr_payroll_account` modules do, and the pattern to copy for a Georgian `_configure_payroll_account_ge`. A CI test walks every installed `l10n_*_hr_payroll_account` and fails if its chart template has no matching method ([test_l10n_payroll_account_config_method.py:17](../enterprise/hr_payroll_account/tests/test_l10n_payroll_account_config_method.py#L17)).

### What breaks when configuration is missing

| Missing | Behavior |
|---|---|
| Journal on structure | Slip shows the warning "No Journal on Structure", now a data-driven `hr.payroll.warning` record instead of hardcoded Python ([hr_payroll_warning_data.xml:4](../enterprise/hr_payroll_account/data/hr_payroll_warning_data.xml#L4)); validation succeeds but **no move is created, silently** — the filter just drops the slip. |
| Debit or credit account on a rule | No error. The one-sided imbalance is silently absorbed by the Adjustment Entry on the journal default account. |
| Journal `default_account_id` when adjustment needed | `UserError` at move creation ([hr_payslip.py:263](../enterprise/hr_payroll_account/models/hr_payslip.py#L263)). |

The NET-reconcilability and untrusted-bank-account guards of v19 disappeared with the Pay button; nothing in this module checks them any more.

---

## Paying Payslips

This module no longer adds a Pay button and no longer hides the base **Mark as Paid**. Payment is entirely a `hr_payroll` affair in v20:

1. **Pay** button on a validated payslip ([hr_payslip_views.xml:53](../enterprise/hr_payroll/views/hr_payslip_views.xml#L53)) calls [action_payslip_payment_report()](../enterprise/hr_payroll/models/hr_payslip.py#L1078), which opens `hr.payroll.payment.report.wizard` with the slip, its run, and the other unpaid slips of the same version pre-loaded.
2. The wizard exports the chosen format (manual / CSV / SEPA), writes the file on the slips and the run, stamps `paid_date`, and **its `mark_as_paid()` is what flips the slips to `paid`** ([hr_payroll_payment_report_wizard.py:162](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162)). No accounting is touched; the salary move must be settled separately by the accountant.
3. Batch-level equivalent: the run's **Mark as Paid** ([action_paid](../enterprise/hr_payroll/models/hr_payslip_run.py#L346)).

The register-payment plumbing stays in this module but is **dead unless a localization triggers it**: `account.payment` accepts `liability_current` accounts as payable under the `hr_payroll_payment_register` context ([account_payment.py:10](../enterprise/hr_payroll_account/models/account_payment.py#L10)); the register wizard groups lines per `employee_bank_account_id` ([account_payment_register.py:11](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L11)); and [_reconcile_payments()](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L24) posts chatter cross-links and writes `state = 'paid'` once every line of the payslip move has zero residual. The only core caller left is `l10n_au_hr_payroll_account`, which reinstates its own **Register Payment** button and `action_register_payment()` ([l10n_au_hr_payroll_account/models/hr_payslip.py:491](../enterprise/l10n_au_hr_payroll_account/models/hr_payslip.py#L491)).

### Payment reports (CSV / SEPA)

The base `hr.payroll.payment.report.wizard` (in `hr_payroll`) exports a CSV of net amounts per employee bank account — including salary-attachment beneficiary accounts — using `_compute_salary_allocations()` ([hr_payroll_payment_report_wizard.py:55](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L55)).

`hr_payroll_account_iso20022` adds `sepa` and `iso20022_ch` export formats with a bank-journal and payment-method-line selector ([hr_payroll_payment_report_wizard.py:10](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L10)):

- Builds one payment per (slip, bank account) from the salary allocations and generates a pain.001 credit transfer XML through the bank journal ([_create_sepa_binary](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L38)).
- Payments are flagged with SEPA category purpose **SALA** ([account_journal.py:228](../enterprise/account_iso20022/models/account_journal.py#L228)); priority HIGH comes from the wizard's new `sepa_priority` field rather than from the country, and pain.001.001.09 journals get a persistent per-slip UETR ([hr_payslip.py:9](../enterprise/hr_payroll_account_iso20022/models/hr_payslip.py#L9)).
- Checks: payment date not in the past, employees have named work contacts, journal bank account is an IBAN, a matching outbound payment method line exists ([hr_payroll_payment_report_wizard.py:97](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L97)).
- SEPA becomes the default export format only for EUR companies (CH companies get `iso20022_ch`) ([hr_payslip.py:19](../enterprise/hr_payroll_account_iso20022/models/hr_payslip.py#L19)) — a GEL company keeps CSV. The v19 payroll-dashboard warning listing employees with invalid IBANs is **gone**; the module's only remaining warning flags employees with no country on their address ([hr_payroll_warning_data.xml:4](../enterprise/hr_payroll_account_iso20022/data/hr_payroll_warning_data.xml#L4)). So this module is essentially irrelevant for Georgia now.

---

## Cancel, Refund, Set to Draft

- **Cancel** ([action_payslip_cancel](../enterprise/hr_payroll_account/models/hr_payslip.py#L29)) calls `move_id.sudo()._unlink_or_reverse()` before the base cancel. The account module decides per move ([account_move.py:5934](../addons/account/models/account_move.py#L5934)): deletable (no hash, after lock date, no CABA/exchange links) → reset to draft and **unlink**; protected by restrictive audit trail → set move to **cancel**; otherwise → **reverse** with auto-reconciliation. Only payroll managers can cancel a validated slip ([hr_payslip.py:1055](../enterprise/hr_payroll/models/hr_payslip.py#L1055)).
- **Set to Draft** exists only on cancelled slips ([hr_payslip_views.xml:55](../enterprise/hr_payroll/views/hr_payslip_views.xml#L55)) and does not touch the move.
- **Refund / Correction** (`refund_sheet` / `action_adjust_payslip`, base module) copies the slip as a `credit_note` with negated lines ([hr_payslip.py:1237](../enterprise/hr_payroll/models/hr_payslip.py#L1237)). When the refund slip is validated, negative totals naturally book on the opposite sides — unless the company uses **storno** accounting, in which case credit-note slips book negative amounts on the *same* side ([hr_payslip.py:194](../enterprise/hr_payroll_account/models/hr_payslip.py#L194)).
- **Guard:** `action_payslip_done` refuses if any selected slip is already `paid` ([hr_payslip.py:39](../enterprise/hr_payroll_account/models/hr_payslip.py#L39)).

---

## Analytic Distribution

Three layers, first non-empty wins per line ([hr_payslip.py:159](../enterprise/hr_payroll_account/models/hr_payslip.py#L159)):

1. `analytic_distribution` on the **salary rule** (rule-specific costs).
2. `analytic_distribution` on the employee's **hr.version** (contract) — added by this module via `analytic.mixin` ([hr_version.py:6](../enterprise/hr_payroll_account/models/hr_version.py#L6)), editable on the employee payroll tab and contract templates.
3. Nothing.

In v20 the distribution is part of the merge key, so two employees with the same analytic account but different percentages produce two lines even in batch mode ([test_anonymized_payruns.py:176](../enterprise/hr_payroll_account/tests/test_anonymized_payruns.py#L176)); identical distributions merge ([test_anonymized_payruns.py:209](../enterprise/hr_payroll_account/tests/test_anonymized_payruns.py#L209)). The v19 "any shared analytic account counts as a match" heuristic is dead code kept only as `_check_partially_matching_accounts` ([hr_payslip.py:293](../enterprise/hr_payroll_account/models/hr_payslip.py#L293)).

`project_hr_payroll_account` is UI-only on top of this: it counts hr.versions whose analytic distribution includes the project's account and shows a "Contracts" stat button on the project ([project_project.py:14](../enterprise/project_hr_payroll_account/models/project_project.py#L14), button in [project_project_views.xml:9](../enterprise/project_hr_payroll_account/views/project_project_views.xml#L9)). No accounting logic.

---

## Expenses Reimbursed Through Payslips (`hr_payroll_expense`)

Rewritten in v20: the hardcoded `EXPENSES` rule code is gone, replaced by an **expense product → salary rule** link.

Flow: an employee expense with `payment_mode = 'payslip_account'` ("Employee (Through a Payslip)") and state approved/posted is flagged **Reimburse In Next Payslip** ([_report_in_next_payslip](../enterprise/hr_payroll_expense/models/hr_expense.py#L86)). Draft payslip creation (or set-to-draft) auto-links all such expenses of the employee ([_link_expenses_to_payslip](../enterprise/hr_payroll_expense/models/hr_payslip.py#L75)) — but only if one of the expense product's `salary_rule_ids` belongs to the payslip's structure. The expense total is injected as the input value of that rule ([_update_expense_input_line_ids](../enterprise/hr_payroll_expense/models/hr_payslip.py#L95)), which the rule turns into a payslip line.

The accounting closure happens at **posting time of the payslip move** ([account_move.py:10](../enterprise/hr_payroll_expense/models/account_move.py#L10)): the expense moves are posted if needed, then the payslip-move line on the rule's debit account is matched — via a generated `matching_number` — and auto-reconciled against the expenses' payable lines, marking the expenses paid. The employee gets one payment (the payslip) covering salary plus expenses. Hard requirement: the linked salary rule must have a **debit** account of type `liability_payable` that is reconcilable — enforced both as a constraint on the product ([product_template.py:16](../enterprise/hr_payroll_expense/models/product_template.py#L16)) and as a `UserError` at posting ([account_move.py:100](../enterprise/hr_payroll_expense/models/account_move.py#L100)). Cancelling the payslip releases the expenses for a future slip ([hr_payslip.py:32](../enterprise/hr_payroll_expense/models/hr_payslip.py#L32)); expenses cannot be pulled out of a validated/paid slip ([hr_expense.py:134](../enterprise/hr_payroll_expense/models/hr_expense.py#L134)). Deleting a payslip move also unlinks/reverses the in-between moves ([account_move.py:34](../enterprise/hr_payroll_expense/models/account_move.py#L34)). New in v20: an expense linked to an existing vendor bill generates a **debt transfer entry** moving the payable from the vendor to the employee ([hr_expense.py:204](../enterprise/hr_payroll_expense/models/hr_expense.py#L204)).

---

## Multi-Company

- `account_debit`, `account_credit` on rules and `journal_id` on structures are **company-dependent** — one shared structure can post to different CoAs per company. Configure them logged into each company (or `with_company`). Structure creation runs `_compute_journal_id` once per company ([hr_payroll_structure.py:27](../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L27)).
- Moves are created `sudo()` in the slip's company; `journal_id` is `check_company` ([hr_payslip.py:15](../enterprise/hr_payroll_account/models/hr_payslip.py#L15)).
- `batch_payroll_move_lines` is per company ([res_company.py:10](../enterprise/hr_payroll_account/models/res_company.py#L10)); the chart-template loader force-enables it for BE/CH ([account_chart_template.py:42](../enterprise/hr_payroll_account/models/account_chart_template.py#L42)).

---

## Configuration & Settings

- **Anonymize Journal Entries** (Payroll settings → Accounting section) — merges all slips of a pay run into one move per journal+month with aggregated, anonymized lines ([res_config_settings.py:10](../enterprise/hr_payroll_account/models/res_config_settings.py#L10), [res_config_settings_views.xml:9](../enterprise/hr_payroll_account/views/res_config_settings_views.xml#L9)). Side effects: `employee_move_line` is ignored (no partner, no per-employee lines, no multi-bank split), draft slips of the run are swept into the move, and the run gets the **Journal Entry (Preview)** button. The setting's help text still mentions disabling "the pay button on individual payslips" — stale, that button no longer exists here.
- **Salary journal** — per structure (Payroll → Configuration → Structures, `journal_id` next to Schedule Pay, required). Set its **Default Account** too: it is the adjustment-entry account.
- **Rule accounts / grids** — per rule, "Accounting" tab ([hr_salary_rule_views.xml](../enterprise/hr_payroll_account/views/hr_salary_rule_views.xml)); grids filtered to `applicability = taxes`. The same columns are available (optional) on the structure's rule list and on the payslip's computation lines ([hr_payslip_views.xml:28](../enterprise/hr_payroll_account/views/hr_payslip_views.xml#L28)).
- **Employee bank accounts** — the v19 `res.partner.bank` auto-link from the employee form is gone; only an "Employees" filter on the bank-account search view remains ([res_partner_bank_views.xml](../enterprise/hr_payroll_account/views/res_partner_bank_views.xml)).

### Wiring a Georgian structure safely (checklist)

1. Confirm the `SLR` "Salaries" journal exists per company and set its default account (adjustment target — any imbalance from mis-configured rules lands here; pick a clearing account you monitor).
2. On each structure used, set `journal_id` **per company**.
3. Gross/employer-cost rules: `account_debit` = expense account. Withholding rules (PIT, pension employee part): `account_credit` = the tax/pension payable liability. NET rule: `account_credit` = salaries-payable account with **reconcile = True**; keep `employee_move_line` on to get per-employee payable lines.
4. Rules that must not shrink the booked NET amount stay unflagged; a rule already inside NET that you book separately (e.g. a benefit-in-kind netting) needs `not_computed_in_net` **plus** its own accounts.
5. Employer-side contributions (pension employer 2%) belong in rules that never enter NET category totals; give them debit expense + credit payable.
6. If the payroll declaration should feed tax report grids, put grids on `debit_tag_ids`/`credit_tag_ids` instead of inventing taxes.
7. Make sure the expense/liability accounts used have **no default taxes** (`account.tax_ids`) unless you really want tax lines on salary moves.
8. Before the first real run, open the pay run's **Journal Entry (Preview)** and check for an Adjustment Entry line — it is the cheapest way to spot a rule with a missing account.

---

## Dependencies

| Requires | Why |
|---|---|
| `hr_payroll` | payslips, rules, structures, batches — the documents being posted |
| `accountant` | full accounting (moves, payments, reconciliation, register wizard) |

`base_iban` was dropped from the dependency list in v20; IBAN validation now goes through `res.partner.bank._is_iban_valid()`.

| Works With | What It Adds |
|---|---|
| `hr_payroll_account_iso20022` | SEPA/ISO 20022 salary payment files (pain.001) from payslip batches — independent of this module in v20 |
| `hr_payroll_expense` | expense reimbursement folded into the payslip, auto-reconciled on posting |
| `project_hr_payroll_account` | "Contracts" counter on projects via analytic distribution |
| `l10n_*_hr_payroll_account` | per-country account/grid presets via `_configure_payroll_account_<code>` |

---

## Gotchas & Non-Obvious Behavior

- **No journal = silent no-move.** A validated slip whose structure lacks a journal is skipped without error — only a warning flags it beforehand, and that warning does not set `block_payslips` ([hr_payroll_warning_data.xml:4](../enterprise/hr_payroll_account/data/hr_payroll_warning_data.xml#L4)). You can end up with paid-in-HR payslips that never hit the GL.
- **Missing rule accounts don't error — they get "adjusted".** A forgotten credit account shifts its amount into the Adjustment Entry on the journal default account, keeping the move balanced and the mistake invisible. Audit the adjustment line every run, or use the preview wizard.
- **Custom ALW rules need a hard setup blocker.** Because missing rule accounts do not stop validation, the wage/work-log module must verify company-specific debit/credit accounts and journal configuration before payroll compute/confirm; a warning is not enough. In v20 the clean place for that is a custom `hr.payroll.warning` record with `block_payslips` on.
- **Every payslip line is booked now, not just categorised ones.** `_prepare_slip_lines` dropped the `line.category_id` filter ([hr_payslip.py:221](../enterprise/hr_payroll_account/models/hr_payslip.py#L221)); a rule with accounts but no category used to be skipped and now posts.
- **Reversal blocks re-posting.** If cancel *reversed* the move (lock date / hash), `move_id` stays on the slip; after Set to Draft and re-validation, `_get_account_move_vals` skips the slip because `move_id` is set — no new entry is ever created ([hr_payslip.py:55](../enterprise/hr_payroll_account/models/hr_payslip.py#L55)). Only the unlink path clears `move_id` (m2o set-null).
- **Validating one batch slip can post the whole batch.** Scope widens to all slips of a run as soon as the run "is ready" (any slip validated or cancelled) ([hr_payslip.py:50](../enterprise/hr_payroll_account/models/hr_payslip.py#L50)) — and in batch mode it also sweeps in slips still in `draft`.
- **`not_computed_in_net` is accounting-only** and assumes the flagged rule's total is already included in NET; it subtracts `abs(total)` from the NET booking regardless of the rule's sign logic ([hr_payslip.py:182](../enterprise/hr_payroll_account/models/hr_payslip.py#L182)).
- **Account default taxes leak into payroll moves.** Every generated line copies `account.tax_ids` ([hr_payslip.py:161](../enterprise/hr_payroll_account/models/hr_payslip.py#L161)); an expense account with a default purchase tax will create tax lines on posting the salary move.
- **The IBAN check in this module is still dead code.** [hr_payroll_payment_report_wizard.py:11](../enterprise/hr_payroll_account/wizard/hr_payroll_payment_report_wizard.py#L11) still filters `state == "done"`, a state that does not exist (v20 states: draft/validated/paid/cancel — the base wizard correctly uses `validated`, [hr_payroll_payment_report_wizard.py:135](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L135)). The new salary-attachment IBAN check added beside it ([:20](../enterprise/hr_payroll_account/wizard/hr_payroll_payment_report_wizard.py#L20)) inherits the same dead filter, and would also `TypeError` on its `'\n'.join(...)` of a recordset if it ever ran. Invalid IBANs are caught by nothing in the CSV export path.
- **Payment date ≠ paid state, but the gap closed.** The wizard writes `paid_date` at export time and, through `mark_as_paid()`, now also calls `action_payslip_paid()` ([hr_payroll_payment_report_wizard.py:162](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162)). Downloading the report without clicking Mark as Paid still leaves the slip `validated` with a `paid_date` set.
- **`paid` no longer follows accounting.** With the Pay button gone, nothing reconciles the salary move back onto the payslip state in a generic install: the slip goes `paid` from the wizard while the move may still be draft and unreconciled. Reconciliation-driven `paid` only exists where a localization uses `hr_payroll_payment_register` ([account_payment_register.py:36](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L36)).
- **Batch mode kills per-employee traceability.** With `batch_payroll_move_lines`, no per-employee lines, no partner, no multi-bank split, and an empty narration — you pay from the accounting side or via payment files, then mark the run paid.
- **Workspace Basis Bank integration widens through shared moves.** The custom `gec_basis_bank_integration` module (still at `19.0.*`) filters selected sendable slips but works from `move_id.line_ids`. In batch mode a shared move can include employees/slips outside the intended selection. Test subset/mixed-state exports or require per-slip moves for that integration — and re-verify it against the v20 payment flow, which no longer provides `hr.payslip.action_register_payment`.
- **Multi-bank splits can hard-fail validation.** `_compute_salary_allocations` raises `ValidationError` when fixed allocations exceed or undershoot the net ([hr_payslip.py:2561](../enterprise/hr_payroll/models/hr_payslip.py#L2561)).
- **Refund + storno companies** book negatives on the same side instead of swapping ([hr_payslip.py:194](../enterprise/hr_payroll_account/models/hr_payslip.py#L194)) — relevant if the Georgian company ever enables storno.
- **Salary journal is undeletable and must be company-currency** ([account_journal.py:10](../enterprise/hr_payroll_account/models/account_journal.py#L10), [hr_payroll_structure.py:34](../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L34)).
- **Expense rule contract:** the expense product's salary rule must have a debit account of type `liability_payable` that is reconcilable, else the product constraint or the posting error blocks it ([product_template.py:30](../enterprise/hr_payroll_expense/models/product_template.py#L30)). Auto-reconciliation silently gives up when more than two accounts are involved ([account_move.py:138](../enterprise/hr_payroll_expense/models/account_move.py#L138)).

---

## What Changed in Odoo 20

- **The Pay button and `hr.payslip.action_register_payment()` were removed from this module.** Payment now runs through `hr_payroll`'s payment-report wizard; the register-payment code here only fires for localizations that set `hr_payroll_payment_register` — [hr_payslip_views.xml](../enterprise/hr_payroll_account/views/hr_payslip_views.xml), [account_payment_register.py:24](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L24).
- **`post_init_hook` deleted.** The `SLR` journal and structure→journal assignment are chart-template data, applied by `account` on module install; the structure template now covers all structures — [account_chart_template.py:89](../enterprise/hr_payroll_account/models/account_chart_template.py#L89), [addons/account/models/ir_module.py:72](../addons/account/models/ir_module.py#L72).
- **Line merging rewritten** around a persistent `(label, account, analytic distribution)` index; exact-distribution matching replaces the v19 "shares any analytic account" heuristic — [hr_payslip.py:170](../enterprise/hr_payroll_account/models/hr_payslip.py#L170).
- **Move `narration` is always empty** — the per-slip id/employee listing was dropped, so no mode leaks employee names — [hr_payslip.py:86](../enterprise/hr_payroll_account/models/hr_payslip.py#L86).
- **New preview wizard** `mock.account.move.wizard` renders a pay run's proposed entry without creating it; `_get_account_move_vals()` was split out of `_action_create_account_move()` to feed it — [mock_account_move_wizard.py:13](../enterprise/hr_payroll_account/wizard/mock_account_move_wizard.py#L13).
- **Warnings became data.** The hardcoded `_get_warnings_by_slip` override is replaced by an `hr.payroll.warning` record with Python evaluation code — [hr_payroll_warning_data.xml:4](../enterprise/hr_payroll_account/data/hr_payroll_warning_data.xml#L4).
- **`security/ir.access.csv` added** (the module had no security dir in v19), granting payroll users `cru` on the preview wizard models only — [ir.access.csv](../enterprise/hr_payroll_account/security/ir.access.csv).
- **`date` is now a stored computed "Accounting Date"** (refund → create date, correction → done date, else end of month) instead of a plain optional field — [hr_payslip.py:20](../enterprise/hr_payroll_account/models/hr_payslip.py#L20).
- **Batch mode now sweeps draft slips** into the move and multi-bank splits include salary-attachment beneficiary accounts — [hr_payslip.py:55](../enterprise/hr_payroll_account/models/hr_payslip.py#L55), [hr_payslip.py:133](../enterprise/hr_payroll_account/models/hr_payslip.py#L133).
- **Siblings:** `hr_payroll_account_iso20022` dropped its dependency on this module and its invalid-IBAN warning; `hr_payroll_expense` replaced the hardcoded `EXPENSES` rule code with a product→salary-rule link and added vendor-bill debt transfers; `base_iban` and `models/res_partner_bank.py` were dropped here — [iso20022 __manifest__.py:6](../enterprise/hr_payroll_account_iso20022/__manifest__.py#L6), [product_template.py:8](../enterprise/hr_payroll_expense/models/product_template.py#L8).

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_payroll.md`](hr_payroll.md) — the payslip lifecycle this module hooks into (states, compute_sheet, batches)
- [`payroll_wage_types.md`](payroll_wage_types.md) — wage types and the custom work-log plan that pays via salary rules
- [`work_entries.md`](work_entries.md) — how worked days are generated before a slip is computed
- [`hr_employee_versions.md`](hr_employee_versions.md) — hr.version (contract) records that carry the analytic distribution fallback
- [`attendance_work_entry.md`](attendance_work_entry.md), [`resource_calendars.md`](resource_calendars.md) — upstream time sources
- [`analytic_accounting.md`](analytic_accounting.md) — analytic distribution mechanics used by rules/contracts
- [`odoo_tax_account_constraints.md`](odoo_tax_account_constraints.md) — account/journal constraints that also bind payroll moves
