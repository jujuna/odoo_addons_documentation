# Georgia - Income Tax Declaration (rs.ge Form 30) (`gec_income_tax_report`) — Developer guide

For a developer who has to change this module. User steps and business rules:
[README.md](README.md). Background and design decisions:
[documentations/gec_income_tax_report.md](../../../documentations/gec_income_tax_report.md); open
items against the full declaration:
[dev_notes/plans/rs_form30_full_declaration_gap_plan.md](../../../dev_notes/plans/rs_form30_full_declaration_gap_plan.md).

---

## 1. Purpose and facts

One `rs.form30.declaration` per company and month. `action_generate` reads, at click time, every
payslip, manual journal entry, vendor bill and withholding payment whose recipient was paid in
the month, and writes annex A and annex E rows; annex D and manual rows are typed; the main part
is derived from the rows and the ledger. `action_export` validates and writes one SpreadsheetML
file per annex into Binary fields and marks the exported rows **In File**. The module also
proposes the withholding tax on manual journal entries when they are posted. Nothing is booked,
sent or scheduled.

| | |
|---|---|
| Depends | `geo_payroll` (salary rule codes, tax exemptions, `_gec_net_account`) · `gec_localization` (the Georgian withholding taxes and `gec_is_withholding`, the Treasury hooks `_gec_withholding_tax_lines` and `_gec_partner_purchase_tax`, the CIT wizard, account `gec_account_140311`) · `l10n_account_withholding_tax` (`account.payment.withholding.line`, the tax form) · `hr_fleet` (`fleet.vehicle.driver_employee_id`) |
| New models | `rs.form30.declaration`, `rs.form30.line` (annex A), `rs.form30.service.line` (annex E), `rs.form30.car.line` (annex D), `rs.form30.summary.cell` + `rs.form30.summary.line` (main part), `rs.form30.partner.category` (category history), `rs.form30.exempt.usage` (treaty allowance ledger), `rs.form30.account.rule` (accounts that identify a withholding on an entry) |
| Classifiers | `rs.form30.category`, `rs.form30.income.type`, `rs.form30.car.engine`, `rs.form30.service.type` on the abstract `rs.form30.classifier.mixin`; `rs.form30.rate.rule` (the matrix) |
| Wizards | `rs.form30.tax.change` (Apply Tax / RS Change), `rs.form30.explain` (one main-part cell), `rs.form30.set.withholding.tax` (Set Withholding Tax on an entry) |
| Extended | `account.move`, `account.move.line`, `account.tax`, `account.chart.template`, `hr.payslip`, `l10n.ge.cit.wizard`, `res.partner`, `res.company`, `res.config.settings`, `res.country`, `fleet.vehicle`, `hr.work.location`; `rs.form30.declaration` again in `rs_form30_declaration_salary.py`, `rs_form30_declaration_payment.py`, `rs_form30_declaration_summary.py`, `rs_form30_declaration_entry.py` and `rs_form30_declaration_xlsx.py` |
| Hooks, crons, controllers | None. Data `<function>` calls: country codes, account rules and filed-row marks on every install and update; tax mapping and pension seed at install only (section 4.14) |

Data files, in manifest order: the six classifier and cell CSVs (categories, income types, rate
rules, car engine bands, service types, main-part cells), `rs_form30_data.xml` (the five
functions), the views, the three wizard views, `menus.xml`, and `security/ir.access.csv` last.

## 2. Architecture

```text
 Sources                         Rows built                  Output
 ──────────────────────────────  ──────────────────────────  ───────────────────
 Payslips, net pay settled ─────► Annex A rows ────────────► form30_a_YYYYMM.xml
 Manual entries with a WHT tax ─┬► Annex A rows (withheld)
 Vendor bills with a WHT tax ───┤
 Withholding payment lines ─────┴► Annex E rows (own tax) ──► form30_e_YYYYMM.xml
 Rows typed by the user ────────► Annex D, manual A rows ──► form30_d_YYYYMM.xml
 Booked, not paid ──────────────► Not Declared lists
 Annex A and D rows,
 posted journal items ──────────► Main part cells ─────────► copied by hand
 rs.ge classifiers ─────────────► check every annex A row, on create and at export
```

Two ideas carry the whole module:

| Idea | How |
|---|---|
| **Cash basis** | A row exists only for money that left in the month. Every source is reduced to the credit line that owes the recipient (payslip net line, entry payable line, bill `payment_term` line); `_rs_form30_cash_parts` splits what settled it into dated cash parts; `_rs_form30_month_share` turns the parts dated in the month into a share of the document |
| **Filed once** | Rows of an exported file are `in_file`. `_rs_form30_declared` collects the payments and bank lines every In File row of the company already holds; generation drops what is already filed, here or in another month, and keeps In File rows as they are |

Rows are snapshots of the moment of Generate Lines. The rs.ge matrix is a constraint on manual
annex A rows; a generated row the portal would refuse is kept with a blocker and never exported.
The portal recomputes tax and pension; the control amounts on the row exist only for comparison.

## 3. File map

| File | Holds |
|---|---|
| `__manifest__.py` | Dependencies, data order, the backend assets of the four grids |
| `__init__.py`, `models/__init__.py`, `wizard/__init__.py`, `tests/__init__.py` | Imports |
| `models/rs_form30_declaration.py` | Declaration: fields, state and buttons, generation, In File bookkeeping, recipient classification, month shares, the shared row helpers (`_rs_form30_file_rows`, `_rs_form30_recipient_vals`, `_rs_form30_row_tax`, `_rs_form30_settlement_warnings`), validation, SpreadsheetML builder; helpers `_number`, `_refuse_in_file_rows` |
| `models/rs_form30_line.py` | Annex A line: fields, main-part cells of a row, matrix check, export values; constants `HEADERS`, `LEGAL_FORMS`, the routing sets |
| `models/rs_form30_warning.py` | The `WARNINGS` table (one row per warning: text and level), `ISSUE_RANK`, `_localize_warning`; no model |
| `models/rs_form30_declaration_salary.py` | Class on the declaration: salary rows from payslips (figures, settlement, plans, row values) |
| `models/rs_form30_declaration_payment.py` | Class on the declaration: annex A and E rows from withholding payment lines |
| `models/rs_form30_declaration_summary.py` | Class on the declaration: main-part routing and values (`_summary_values`, `_ledger_values`, `_sync_summary_lines`) |
| `models/rs_form30_declaration_entry.py` | Class on the declaration: entry rows, bill rows, the Not Declared lists |
| `models/rs_form30_declaration_xlsx.py` | Class on the declaration: `action_export_explanation` and one `_xlsx_*` writer per workbook sheet |
| `models/rs_form30_service.py` | Annex E line, its 7 headers in portal import order |
| `models/rs_form30_car.py` | Annex D line, its 5 headers, onchanges from Fleet and HR |
| `models/rs_form30_summary.py` | Main-part cell layout (`computed`, `proposed`, `is_boolean`, `is_section`) and per-declaration values |
| `models/rs_form30_classifier.py` | Classifier mixin, categories (with the `use_salary` / `use_entry` / `use_bill` guide), income types, rate rules (`_allowed_rates`), car engine bands, service types; the abstract `rs.form30.shipped.data` (its `write` keeps a manager's edit through `-u`) |
| `models/rs_form30_account_rule.py` | Account rules (C, D, F accounts per income type), `DEFAULT_ACCOUNT_RULES`, `_rs_form30_seed_account_rules` |
| `models/rs_form30_partner_category.py` | One category period of a contact; date order and overlap checks |
| `models/rs_form30_exempt_usage.py` | One draw on a recipient's treaty allowance |
| `models/account_move.py` | Plain-entry filter, rule match, tax proposal at `_post`, Detect Again, Set Withholding Tax entry point, the balancing-line refusal, entry and bill alerts; `_is_treasury` |
| `models/account_move_line.py` | `rs_form30_proposed_tax_id`, `_rs_form30_cash_parts`, the `_gec_withholding_tax_lines` extension |
| `models/hr_payslip.py` | Correction families (`_rs_form30_family_root`, `_rs_form30_family`), `_rs_form30_net_lines`, the note on Mark Unpaid |
| `models/res_partner.py` | Category fields, own-tax flags, service type, treaty allowance; `_rs_form30_category_on`, `_rs_form30_pays_own_tax` |
| `models/account_tax.py` | Income type, service type, Declare in Annex E, validity dates and previous tax on `account.tax`; `_rs_form30_version_on`, `_rs_form30_map_ge_taxes` (reads `data/template/account.tax-ge.csv`), the dated `_gec_partner_purchase_tax` |
| `models/account_chart_template.py` | `_post_load_data`: tax mapping, account rules and pension seed when a root company gets the Georgian chart |
| `models/cit_wizard.py` | The CIT wizard proposes the dividend tax version valid on its date |
| `models/res_company.py`, `models/res_config_settings.py` | Pension liability and employer pension expense accounts, their seed and settings fields |
| `models/res_country.py` | `rs_form30_code`; `_rs_form30_load_codes` |
| `models/fleet_vehicle.py` | `rs_form30_engine_id` |
| `models/hr_work_location.py` | `rs_form30_autonomous_republic` |
| `wizard/rs_form30_set_withholding_tax.py` | Set Withholding Tax: `default_get` proposes lines and tax, `action_apply` writes a hand pick and reposts |
| `wizard/rs_form30_set_withholding_tax_views.xml` | Its form |
| `wizard/rs_form30_tax_change.py` | Apply Tax / RS Change: preview, `_rule_plan`, `action_apply` |
| `wizard/rs_form30_tax_change_views.xml` | Its form |
| `wizard/rs_form30_explain.py` | Explanation of one main-part cell: `FORMULAS`, `_formulas`, `_cell_state`, `_explain_summary` |
| `wizard/rs_form30_explain_views.xml` | Its form and the QWeb template `main_part_explanation` |
| `views/rs_form30_declaration_views.xml` | Declaration list, form (header counters, Not Declared tab) and search, the manual row form, the exempt usage list, car engine band and service type lists and actions |
| `views/rs_form30_classifier_views.xml` | Category, income type and rate rule lists and actions |
| `views/rs_form30_account_rule_views.xml` | Account rule list, search and action |
| `views/account_move_views.xml` | **Set Withholding Tax** and **Detect Again** on the journal entry form |
| `views/res_partner_views.xml` | The **rs.ge Form 30** group on the contact form, current category in the contact list |
| `views/account_tax_views.xml` | Form 30 fields and the **RS Declaration Rules** tab on the withholding tax form; the Withholding Taxes action |
| `views/res_config_settings_views.xml` | Pension accounts in the Accounting settings |
| `views/fleet_vehicle_views.xml` | Engine band on the vehicle form |
| `views/hr_work_location_views.xml` | Autonomous republic on the work location form |
| `views/menus.xml` | Reporting menu and the **rs.ge Form 30 (Advanced)** configuration menus |
| `data/rs.form30.category.csv` | 18 recipient categories, with `display_code`, `is_organization` and the usage flags |
| `data/rs.form30.income.type.csv` | 15 income types with validity |
| `data/rs.form30.rate.rule.csv` | 152 allowed (category, income type, rate) cells with validity |
| `data/rs.form30.car.engine.csv` | 4 engine bands and their monthly tax |
| `data/rs.form30.service.type.csv` | 8 annex E service kinds |
| `data/rs.form30.summary.cell.csv` | 60 main-part rows: 44 computed, 11 proposed, 4 typed, 1 heading |
| `data/res.country.csv` | rs.ge code of 235 countries; not in the manifest, read by `_rs_form30_load_codes` |
| `data/template/account.tax-ge.csv` | Income type and Annex E flag per Georgian tax xmlid; not in the manifest, read by `_rs_form30_map_ge_taxes` |
| `data/rs_form30_data.xml` | The five `<function>` calls |
| `security/ir.access.csv` | Access and company restriction rows (section 7) |
| `static/src/components/rs_form30_grid/rs_form30_grid.js` | Annex A widget `rs_form30_grid` (`X2ManyField` subclass): columns, filters, totals, column widths, source links |
| `static/src/components/rs_form30_grid/rs_form30_grid.xml` | Its template |
| `static/src/components/rs_form30_grid/rs_form30_grid.scss` | Stylesheet of all four grids, scoped to `.o_rs_form30_grid` |
| `static/src/components/rs_form30_car_grid/rs_form30_car_grid.js` | Annex D widget, editable, extends the annex A widget |
| `static/src/components/rs_form30_car_grid/rs_form30_car_grid.xml` | Its template |
| `static/src/components/rs_form30_service_grid/rs_form30_service_grid.js` | Annex E widget, read-only, extends the annex A widget |
| `static/src/components/rs_form30_service_grid/rs_form30_service_grid.xml` | Its template |
| `static/src/components/rs_form30_summary_grid/rs_form30_summary_grid.js` | Main-part widget: row per cell, edit rules, the question-mark button |
| `static/src/components/rs_form30_summary_grid/rs_form30_summary_grid.xml` | Its template |
| `i18n/ka_GE.po` | Georgian translation |
| `tests/test_form30.py` | Salary rows, payment rows, validation, export file, grid rendering |
| `tests/test_tax_configuration.py` | Apply Tax / RS Change and category history |
| `tools/generate_classifier_csv.py` | Regenerates the category, income type, rate rule and country CSVs from the rs.ge classifier workbook |
| `README.md`, `README_DEV.md` | User guide, this guide |

## 4. Flows

### 4.1 Generate Lines: `action_generate`

1. Refuses unless `state == 'draft'`.
2. Unlinks the annex A rows that are neither `manual` nor `in_file`, and the annex E rows that are
   not `in_file`. The treaty draws of the deleted rows go with them
   (`rs.form30.exempt.usage.line_id` cascades).
3. `_rs_form30_mark_stale` blocks In File rows whose source changed since the export (4.7).
4. `_rs_form30_declared` collects what In File rows of the company already declare (4.7).
5. Builds the vals: `_rs_form30_salary_data` (4.2), `_payment_line_vals` + `_service_line_vals`
   (4.3), `_rs_form30_entry_vals` (4.4), `_rs_form30_bill_vals` (4.5). `_rs_form30_drop_filed`
   removes vals whose cash is already in a file and turns a clash with another month into a
   generation warning.
6. Vals matching a manual row's (partner, income type) get the "manual row exists" warning; vals
   that `_matrix_problems` refuses get the blocker "The rs.ge classifier does not allow ...".
   `_check_matrix` checks manual rows only, so one bad row never rolls back the generation.
7. One `write`: the rows, the three Not Declared lists (`unpaid_move_ids`,
   `not_payable_move_ids`, `missing_tax_move_ids`) and `generation_warnings`.
8. `_sync_summary_lines` refreshes the main part (4.10).

`warning` holds canonical English sentences; `_rs_form30_issue_level` maps them through the
`WARNINGS` table in `rs_form30_warning.py` to `blocker`, `warning` or `note`, stored in
`issue_level`. `_localize_warning` translates them at display from the same table.

### 4.2 Cash: `_rs_form30_cash_parts`, `_rs_form30_month_share`, `_rs_form30_month_amounts`

`account.move.line._rs_form30_cash_parts` takes credit lines and walks `matched_debit_ids` with
`sudo()`. Each counterpart becomes:

| Counterpart | Part | Date |
|---|---|---|
| Posted bank statement line | cash, `kind = 'bank'` | statement line date |
| Payment `paid` / `reconciled` | cash, `kind = 'payment'` | latest matched statement date when `is_matched`, else payment date (`matched = False`, row warns) |
| Plain journal entry whose other side is only on asset accounts, no cash or bank account (offset or advance closing, accountant 2026-11-10) | cash, `kind = 'offset'`, kept in `settlement_move_ids` | entry date (row warns "Settled by an offset entry") |
| Anything else (write-off, reclass, credit note, payroll netting) | other | entry date (row warns "Partly settled without a payment") |

`_rs_form30_cash_parts` dates no cash part before the settled document (`invoice_date`, else its date): money paid before the document is an advance, `kind = 'advance'`, declared in the document's month with the warning "Paid in advance, before the document".

The line's own entry, its reversals and exchange-difference entries are skipped.

`_rs_form30_month_share(cash, net, declared, label, source)` returns the parts dated in the month
and two ratios of `net`: paid before the month, paid through it. Parts already in a file of this
declaration, and parts in another declaration's file (with a warning), count as before.
`_rs_form30_month_amounts` multiplies each amount (gross, tax, pension) by both ratios and
subtracts the rounded values, so the months of a part-paid document always add up to the whole.

### 4.3 Salary rows: `_rs_form30_salary_data`

Searches `hr.payslip` with `sudo()` (the filing accountant usually has no payroll access):
company, `state in ('validated', 'paid')`, not a credit note or refund payslip.

1. **Families.** `_rs_form30_family_root` follows `origin_payslip_id`; `_rs_form30_family` adds all
   `related_payslip_ids`. The final correction of a family is declared, by the months its net was
   paid (`_rs_form30_salary_plans`). When the family is already In File (`declared['payslip_filed']`: gross, tax and pension of
   its In File rows up to this month), only the difference is declared, as a row noted "Corrected by ... after earlier months
   were filed", and only in a month with cash of the correction, or the month of its entry. No row, and the declaration
   warning "changes figures already declared" instead, when any figure is below what was filed, when gross is 0 but tax or
   pension is above 0, or when the family is fully paid with no cash this month and a figure rose. No row either, with
   "export the declaration of YYYY/MM first, then generate this month again", when cash dated before the month is in no
   file yet. When the family is not In File: the final slip is declared by the months its cash paid it, and a correction whose
   older slip is still in an earlier draft declaration warns "generate the declaration of YYYY/MM again before exporting it".
2. **Settlement.** `_rs_form30_net_lines` = the posted credit lines on the NET account
   (`_gec_net_account`), else the employee's reconcilable line equal to `net_wage`. Their cash
   parts date the row. Partials inside the family are payroll netting, not cash. A slip `paid`
   with no partials uses `paid_date` and warns "No payment matched"; a zero-net slip uses its entry
   date and warns.
3. **Unpaid.** A slip with an open net line and no cash up to month end, or with only
   rejected / canceled / draft payments, goes to `unpaid_move_ids`.

| Field | Value |
|---|---|
| `amount` | Σ `GROSS` line totals + Σ `ADVANCE_PAY` inputs, times the month share |
| `tax_amount` | −Σ `PIT` + Σ `ADV_PIT_PRE` (PIT lines are negative, prepaid legs positive) |
| `pension_amount` | −Σ `PENSION_EE` + Σ `ADV_PEE_PRE` |
| `other_relief` | Employees in an active `hr.payroll.tax.exemption`: `max(0, round(amount − pension − tax × 100 / rate))`, so the portal's `(amount − pension − relief) × rate` equals the withheld tax (README Example C); else 0 |
| `identification` | `slip.version_id.identification_id`, else `work_contact.vat` with a warning; both cleaned by `_clean_identification` |
| `first_name`, `last_name` | `_split_name(employee.legal_name or employee.name, is_company=False)` |
| `address` | `private_street`, `private_street2`, `private_city` of the slip's version |
| `category_id`, `country_id` | `_recipient_classification(work_contact, date, salary=True, nationality=version.country_id, usage='salary')` (4.6) |
| `income_type_id`, `rate`, `date` | `income_type_1`, the slip's `gec_ge_pit_rate` rule parameter (geo_payroll, 20), the latest cash date in the month |
| `autonomous_republic` | `version.work_location_id.rs_form30_autonomous_republic`, a snapshot for cells 57¹ / 57² |
| `settlement_payment_ids`, `settlement_statement_line_ids` | The payments and bank lines of the month's parts; the keys of "filed once" |

Other warnings: `slip.edited`, an advance in the amount (note), a correction family (note).
`hr.payslip.action_payslip_unpaid` posts a chatter note when the slip is already In File.

### 4.4 Entry rows: `_rs_form30_entry_vals`

Candidates: posted `entry` moves of the company with a line tax that has an income type, passed
through `_rs_form30_plain_entries` (general journal, no payment, statement line, reversal origin,
opening move or payslip entry). No date bound: an old entry paid this month is found.

Per entry, `account.move._rs_form30_entry_split`:

| Part | Lines |
|---|---|
| Tax lines | `_rs_form30_match`: credits on a rule's F account with no partner or the Treasury (`_is_treasury`) |
| Pension | Lines on the company's pension liability and employer pension accounts |
| Recipients | Other lines with a non-Treasury partner on a reconcilable account, grouped by commercial partner; kept when the net is a credit |
| Not payable | Credits on non-reconcilable liability accounts: counted in `net_total` so shares are not inflated, and listed in `not_payable_move_ids` |

`_rs_form30_entry_shares` splits tax and pension over recipients by net, the last one taking the
rounding rest; gross = net + tax + pension. `_rs_form30_entry_settlement` gives each recipient
its cash parts; for an entry reversed after payment the matched payments' residuals stand in.
`_rs_form30_entry_rows` then makes one row per recipient and month (annex E when
`_rs_form30_pays_own_tax`).

| Situation | Result |
|---|---|
| Two withholding taxes, or own-tax and withheld recipients mixed | Blocker on every row of the entry |
| Booked tax ≠ `(net + tax) × rate` beyond 0.01 per recipient | Warning |
| F line still open after the person was paid | Note "Late: the tax was due ..." |
| Reversed, no payment found | Generation warning if the reversal is in the month; no row |
| Unpaid by month end | `unpaid_move_ids` |

`_rs_form30_missing_tax_moves` fills `missing_tax_move_ids`: plain entries of the last 12 months
that credit an F account, carry no income-type tax, and raise the `rs_form30_tax_missing` alert.

Row fields as for payment rows (4.3 identity helpers), with `source = 'entry'`, `move_id`,
`income_type_id` and `rate` from `_rs_form30_version_on(row date)` of the booked tax, and
`usage='entry'` in the classification.

### 4.5 Bill rows: `_rs_form30_bill_vals`

Candidates: posted `in_invoice` / `in_receipt` with a tax line whose tax is `gec_is_withholding`
with an income type, or a line tax with `rs_form30_annex_e`; bills from employee expenses
(`expense_ids`) are skipped. The bill's `payment_term` lines are the settlement lines; `net` is
their credit.

| Row | Built from |
|---|---|
| Annex A, one per withholding tax line | `amount = tax_base_amount`, `tax_amount = −balance`, times the month share; `usage='bill'` |
| Annex E, own-tax vendor with a withholding tax | Same base; with a tax-included (company pays) tax, base + balance |
| Annex E, label only | Lines whose taxes include an `rs_form30_annex_e` tax and no negative withholding tax on the same line: Σ line balance |

A credit note counts only when dated after the first payment
(`_rs_form30_reversed_after_payment`). `_rs_form30_get_bill_alerts` shows on the posted bill:
default withholding tax missing on a line, label and withholding tax on one line, withholding
for an own-tax vendor, a category not meant for bills, a rate the matrix refuses, a tax version
not valid on the bill date.

### 4.6 Payment rows, annex E and classification

`_withholding_lines` (company, outbound, `paid` / `reconciled`, payment date in the month) feeds
`_payment_line_vals` and `_service_line_vals`; `_rs_form30_pays_own_tax` sends a line to exactly
one of them. Amounts are the line's `base_amount` and `amount` converted at the payment date. This
is Odoo's withholding at payment; the Georgian taxes no longer use it, so these rows come only
from taxes a user ticks for it.

Identity helpers on the line (`@api.model`): `_split_name` (people: first token / rest;
companies: first token only when it is in `LEGAL_FORMS` and more tokens follow);
`_clean_identification` (drops spaces and a leading GE when only digits follow); `_label`.
`is_company` follows `gec_localization`: a Georgian 11-digit personal number is a person.

`_recipient_classification(partner, date, *, salary, nationality, usage)`:

| Situation | Salary row | Other rows |
|---|---|---|
| History covers the date, or no history and a legacy category | that category | that category |
| No history, no legacy category | `category_4` (1.1) + "defaulted" warning | empty + "Set the category and residency" blocker |
| History exists, gap on the date | empty + "No category covers" blocker | the same |
| Residency | `partner.country_id`, else nationality, else `base.ge` + warning | `partner.country_id` |
| Category not flagged for `usage` | "not meant for" warning | the same |

`res.partner._rs_form30_category_on(date)` is the single resolver; a gap never falls back to the
legacy field. Empty cells are blocked at export, not at creation, so unfinished rows can be saved.

### 4.7 In File: `_rs_form30_declared`, `_rs_form30_drop_filed`, `_rs_form30_mark_stale`

`action_export` writes `in_file = True` and `exported_on` on the rows it put in a file and clears
both on the rest. In File rows cannot be written or deleted while their declaration is exported
(`_refuse_in_file_rows`; the export itself passes `rs_form30_export`), and
`account.move._rs_form30_check_not_in_file` refuses Set Withholding Tax and Detect Again on their
entries.

`_rs_form30_declared` returns, across the company, `documents`: `((payment|statement, id),
source) → declaration`, where `source` is the payslip family, or (entry|bill, move, partner), so
one payment settling two entries marks only its own. Rows of this declaration are read last and
win. `_rs_form30_drop_filed` drops vals whose documents are already declared; in another
declaration it also adds "already declared in ..." to `generation_warnings`.

`_rs_form30_mark_stale` adds the blocker "Filed, but its payment or source changed after the
export" when a settlement payment is no longer paid, the source was reversed, the payslip left
validated / paid, or the entry is no longer posted. `action_clear_in_file` (draft only) clears the
marks so the next generation rebuilds the rows. `_rs_form30_mark_filed_rows` (data function) marks
the rows of declarations exported before the field existed.

### 4.8 Withholding tax proposal on entries: `_post`, `_rs_form30_propose_withholding_tax`

`_post` runs on the plain draft entries: `_rs_form30_propose_withholding_tax`, then
`_rs_form30_check_no_balancing_line` (refuses an entry with a withholding tax and core's
Automatic Balancing Line, found by name in every installed language).

1. `_rs_form30_match`: a rule matches when the entry debits one of its C accounts, credits one of
   its D accounts and has a tax line on one of its F accounts.
2. `_rs_form30_candidates`: only when the matched rules give one income type. Candidate taxes:
   root company, `gec_is_withholding`, negative, that income type, valid on the entry date; per
   recipient, not in the other residency's tax group (`gec_tax_group_wht_res` / `_nr`) and at a
   rate the matrix allows for the recipient's category. Per rate, the tax-excluded variant wins.
3. Exactly one candidate goes on the expense lines; `rs_form30_proposed_tax_id` records it. An
   entry whose withholding taxes differ from the recorded proposal on any line is a hand pick and
   is never touched again.

`action_rs_form30_detect_withholding_tax` resets and reposts to rerun the proposal.
`rs.form30.set.withholding.tax` proposes the expense lines and the single candidate,
`action_apply` writes the tax as a hand pick (clears the proposal marker) and reposts; both check
the fiscal lock dates. Core refuses tax changes on posted lines, hence the draft-and-repost.

`_rs_form30_get_alerts` shows on the entry: no tax while a rule matches ("Form 30 will not
declare ..."; several income types fit), or a booked tax that is not the rate of net + tax, which uses the declaration's split (`account.move._rs_form30_entry_split`).
`account.move.line._gec_withholding_tax_lines` adds the F-account credits of matched entries to
`gec_localization`'s Treasury Pay.

### 4.9 Category history and treaty allowance

`rs.form30.partner.category`: `partner_id`, `category_id`, `date_from`, `date_to`; both bounds
inclusive and optional. A SQL constraint rejects reversed dates; `_check_periods` rejects overlaps.
`date_from` has no default on purpose: an empty start means "always applied". Deleting the contact
cascades its history; the category FK restricts. `rs_form30_current_category_id` is a non-stored
summary for today and is never read by generation.

`_rs_form30_draw_exempt` runs at export over the selected rows (`_rs_form30_export_exempt`, which
locks the partners first). For each row whose partner has a non-zero `rs_form30_exempt_limit`, it
writes `international_agreement_exempt_tax = min(tax_amount, remaining)` and creates one
`rs.form30.exempt.usage` with the balance before and after. Rows left out of the file and rows
reset to draft give their draw back (`_rs_form30_release_exempt`). The allowance is per partner,
not per company, and does not enter cell 57.

### 4.10 Main part: `_sync_summary_lines`, `_summary_values`, `_main_part_cells`, `_ledger_values`

`_sync_summary_lines` runs from `create`, `action_generate` and `action_export`. From `create`, so a
new declaration shows all 60 rows; from export, because annex D rows and 56¹ are typed after
generating and feed cell 57.

| Cell flag | Sync rule |
|---|---|
| `computed` | `value` always rewritten |
| `proposed`, amount | `value` rewritten only while it still equals `proposed_value`; `proposed_value` always updated. Typing the proposal back hands the cell to Odoo |
| `proposed`, `is_boolean` (59) | `value_bool` always rewritten |
| neither | never written |

`_summary_values(trace=None)` walks the annex A rows that would go into the file
(`_rs_form30_file_lines`, so rows with warnings count only when `export_warned_rows` is ticked).
Per row: `_main_part_cells` gives `(amount cell, base cell)`; `_taxable_base` = `amount −
pension_amount − other_relief`; `_portal_tax` = `round(base × rate / 100)` goes to 39 (natural
person) or 56 (`is_organization`). Then the `SUMMARY_SUMS` totals (27, 33, 40, 48), 56² = 12% of
the stored 56¹, 57 = 39 + 56 + 56² + Σ annex D `amount` − Σ `foreign_tax_credit`, and the
per-person salary totals for 61 / 65 / 66 (keyed by `identification`, else partner, else row). 18
is a memo (type 17 to resident individuals) and is not added into 39.

`_main_part_cells`, first match wins:

| Test | Amount cell | Base cell |
|---|---|---|
| income type 1 | 16 | 17 |
| organization 3.1, not type 2 | 45 | 53 |
| organization 3.8 / 3.7 | 42 / 43 | 50 / 51 |
| organization, type 2 / type 3 | 46 / 47 | 54 / 55 |
| organization, type 17 at 5 | 41 | 49 |
| other organization | 44 | 52 |
| individual, type 2 / type 3 | 22 / 24 | 23 / 25 |
| `HOTEL_CATEGORIES` (1.3, 3.10) | — | 26 |
| `NON_SERVICE_TYPES` (5, 16, 21, 22, 23) | — | 21 |
| 3.x at a `NON_RESIDENT_RATES` rate (4, 5, 10, 15): 3.2 / 3.6 / 3.5 / type 17 at 5 / other | 32 / 29 / 30 / 28 / 31 | 38 / 35 / 36 / 34 / 37 |
| rate 3 / rate 5 / anything else | — | 20¹ / 20 / 19 |

`_ledger_values` reads posted `account.move.line` of the company with the user's rights:

| Cell | Source |
|---|---|
| 58 | −Σ `balance`, dated in the month, `account_id.account_type = 'income'` |
| 59 | any line dated in the month with `account_id.internal_group = 'expense'` |
| 63 | Σ `amount_company_currency_signed` of inbound `account.payment` in cash journals, `paid` or `reconciled`, dated in the month |
| 67 | Σ `balance` up to month end on the `default_account_id` of the cash journals |
| 68 / 69 | `_read_group` by partner of the balance up to month end on `gec_account_140311`; positive balances summed / counted. No such account: 0 |

With a `trace` (`defaultdict(list)`), every contribution is recorded under its cell code by the
same code path that computes the value, so the explanation cannot disagree with the stored
numbers.

### 4.11 Explanation page and workbook

The question mark in `RsForm30SummaryGrid.explain` opens `rs.form30.explain` with
`default_declaration_id` and `default_cell_code`. `_explain_summary` recomputes
`_summary_values(trace)`, pairs the stored line with its trace items, adds the formula from
`_formulas()` (`FORMULAS` with `{t<code>}`, `{c<portal number>}` and `{orgs}` replaced by the
classifier names) and `_cell_state` (kind, sentence, stale flag). Rendered by the QWeb template
`main_part_explanation`.

`action_export_explanation` returns the stored workbook of an exported declaration, else builds it
with `_store_explanation` → `_explanation_workbook` (xlsxwriter, in memory): one
`_summary_values(trace)`, then `_xlsx_readme`, `_xlsx_annex_a`, `_xlsx_payslips`, `_xlsx_payments`,
`_xlsx_annex_d`, `_xlsx_annex_e`, `_xlsx_main_part`, `_xlsx_cell_details`. `action_export` stores
one at every export. Payroll figures are read with `sudo()`, as the rows themselves are.

### 4.12 Export: `action_export`

1. `lock_for_update` on the declaration (a second export is refused), `state == 'draft'`.
2. Refuses when all three annexes are empty. `_rs_form30_file_lines` /
   `_rs_form30_file_service_lines` select the rows: no blocker, and no warning unless
   `export_warned_rows`. Nothing selected and no car rows: refused.
3. `_sync_summary_lines`, then the validators of the annexes with rows: `_check_lines`,
   `_check_car_lines`, `_check_service_lines`. A failing validator raises a `UserError` with the
   problems and nothing is written.
4. `_rs_form30_export_exempt` (4.9), then `state = 'exported'` and each annex's file into its
   Binary field as `BinaryBytes` (`form30_a_<period>.xml`, `_d_`, `_e_`); an annex without rows
   gets `False`, so no stale file survives.
5. Selected rows become In File, the others lose the mark; `_store_explanation`.

`_check_lines` calls `_validation_errors` per row: missing ID, residency, category, income type or
date; a country without `rs_form30_code`; residency 268 with an ID that is not 9 or 11 digits;
date outside the month; amount not positive; then `_matrix_problems` again, because classifier
rules can be edited after generation.

`_build_xml` asks the recordset for `_rs_form30_headers()` and each row for `_export_values()`, so
the three line models share one builder:

| Rule | Reason |
|---|---|
| Excel 2003 SpreadsheetML, sheet `data`, one header row | The portal's import template |
| Every cell `ss:Type="String"` with style `@` | Leading zeros in IDs and country codes survive |
| Numbers by `_number`: dot decimal, no trailing zeros (`250`, `250.5`, `0`) | Portal format |
| Dates `DD.MM.YYYY`; treasury `1` or empty | Portal format |
| Empty cells written as one space | The portal's own export does it |
| Columns are positional | Change `HEADERS` and `_export_values` together |

Annex A column 6 carries the category `code` (the rs.ge ID, `4` for 1.1), not `display_code`.
Annex D column 2 carries the engine band `code` (1–4).

`action_draft` returns to draft and keeps the In File marks; `action_add_manual_row` opens the
manual row form (draft only).

### 4.13 Apply Tax / RS Change: `rs.form30.tax.change.action_apply`

`account.tax.action_rs_form30_change` opens the wizard (Accounting Administrators only);
`default_get` fills both rates from the tax, the onchanges propose the categories whose rule at
the old rate covers the effective month and a replacement name.

1. Guards: manager group, write access, row locks on the wizard and the tax, not applied yet; the
   tax is an active withholding tax (Tax Type Purchases or None) with a negative percentage and an
   income type; effective date on the 1st; rates 0–100.
2. Tax change (`both`, `tax`): `both` must replace the tax's current rate; the new rate must
   differ; the tax must not be replaced already (`rs_form30_date_to` empty) and the effective date
   must follow its `rs_form30_date_from`; a name is required.
3. Rule change (`both`, `rules`): categories required; `_rule_plan(period)` validates the whole
   change before anything is written: each category and the income type valid in the month; for
   replace / stop, a current rule at the old rate that started before the month; an existing rule
   at the new rate that already covers the interval is reused, an overlapping future one refuses.
   Finite end dates of the replaced rule are kept on the new one.
4. Writes: `tax.copy` with the new name, `amount = −new_rate`, `rs_form30_date_from = effective
   date`, `rs_form30_previous_tax_id`; the old tax gets `rs_form30_date_to` = the day before.
   Closed rules get `valid_to` = the previous month; new rules are created. Opens the new tax.

Every row source picks the version valid on its date with `_rs_form30_version_on`; the contact
default (`_gec_partner_purchase_tax`) and the CIT wizard's dividend tax do the same. The rules are
shared across companies (`rs.form30.rate.rule` has no company). Salary rows take the slip's `gec_ge_pit_rate`.

### 4.14 Data functions

| Function | When | Does |
|---|---|---|
| `res.country._rs_form30_load_codes` | Every install and `-u` | Reads `data/res.country.csv` with `file_open`, resolves `base.<alpha2>` in one `ir.model.data` query, writes only empty codes. Not a manifest CSV because `base` ships countries `noupdate`, so the loader would skip them on upgrade |
| `account.tax._rs_form30_map_ge_taxes` | Install (`noupdate`), and `_post_load_data` of a Georgian root company | Reads `data/template/account.tax-ge.csv` with `_parse_csv`, resolves each xmlid per root company, fills income type and Annex E only where empty. `-u` never re-ticks what the accountant cleared; a tax added later needs the method run once |
| `rs.form30.account.rule._rs_form30_seed_account_rules` | Every install and `-u`, and `_post_load_data` | Creates `DEFAULT_ACCOUNT_RULES` only for root companies with no rule at all (archived included), so edits and archives survive |
| `res.company._rs_form30_seed_pension_accounts` | Install (`noupdate`), and `_post_load_data` | 332010 as pension liability, 740900 and 721000 as employer pension expense, when both fields are empty |
| `rs.form30.declaration._rs_form30_mark_filed_rows` | Every install and `-u` | Marks rows of exported declarations without any In File row |

### 4.15 Grid widgets

| Widget | Field | Base | Editing |
|---|---|---|---|
| `rs_form30_grid` | `line_ids` (annex A) | `X2ManyField` | none; list `limit="100"` |
| `rs_form30_service_grid` | `service_line_ids` (annex E) | `RsForm30Grid` | none |
| `rs_form30_car_grid` | `car_line_ids` (annex D) | `RsForm30Grid` | row click → `enterEditMode`; `addNewRecord`; delete |
| `rs_form30_summary_grid` | `summary_line_ids` (main part) | `X2ManyField` | rows that are neither `computed` nor `is_section`; list `limit="200"` |

The subclasses override `get columns()` and their template; everything else comes from the base.
Filters and footer totals work on the loaded page only. The main part needs its explicit limit:
an x2many list loads 40 records by default and there are 60 cells.

## 5. Data

| File | xmlids | On `-u` |
|---|---|---|
| Categories, income types | `category_<rs id>`, `income_type_<code>` | Updated in place, except records a user has edited (`rs.form30.shipped.data.write`) |
| Rate rules | `rate_rule_<category id>_<type>_<rate>` | Updated in place, except rules a user has edited: `rs.form30.shipped.data.write` marks their `ir.model.data` `noupdate` outside `install_mode` |
| Car engine bands, service types, main-part cells | `car_engine_<n>`, `service_type_<n>`, `summary_cell_<code>` | Updated in place, except bands and service types a user has edited; cells are maintained by hand |
| Countries, tax mapping, account rules, pension accounts | Through the data functions (4.14) | Empty values filled, others kept |

Code relies on `category_4`, `income_type_1`, `base.ge` and the tax groups `gec_tax_group_wht_res`
/ `gec_tax_group_wht_nr`; never rename xmlids. Classifier FKs from the rows are
`ondelete='restrict'`: archive, never delete. A record removed from a CSV is deleted by the next
`-u` (it is not `noupdate`): keep retired classifiers and rules with a closed validity so old
months stay reproducible.

New rs.ge classifier workbook:

1. `python3 tools/generate_classifier_csv.py 30_data_<version>_<period>.xlsx data/` (needs
   `openpyxl`). It writes the category, income type, rate rule and country CSVs and keeps the
   category usage columns. Dated notes set validity (`გაუქმდა YYYYMM` → `valid_to` = previous
   month, `ძალაშია YYYYMM` → `valid_from`); cells whose note mixes several rates need an entry in
   `OVERRIDES`. Income types and rate rules whose `valid_to` is before the current month are not
   written, and `-u` deletes them from the database; a declaration of such a past period then
   refuses those rows.
2. Review the diff and every removed row, then `-u gec_income_tax_report`.

## 6. Guards and invariants

| Guard | Where |
|---|---|
| One declaration per company and month | `_company_month_uniq` |
| Month starts on the 1st; changing it re-checks the manual rows against the new month's matrix | `_check_date_from` |
| Company fixed once rows exist | `write` (and `readonly` in the form) |
| Generate, manual rows and Clear In File only in draft; one export at a time | `action_generate`, `action_add_manual_row`, `action_clear_in_file`, `action_export` (`lock_for_update`) |
| Cash in a file is never declared twice | `_rs_form30_declared`, `_rs_form30_drop_filed`, `_rs_form30_month_share` |
| In File rows of an exported declaration are read-only; a declaration holding them cannot be deleted. Car rows and summary rows of an exported declaration are read-only too | `_refuse_in_file_rows`, `_refuse_exported_rows`, `_unlink_except_in_file_rows` |
| A filed entry's tax cannot be changed | `_rs_form30_check_not_in_file` |
| An entry with a withholding tax cannot post with an automatic balancing line | `_rs_form30_check_no_balancing_line` |
| A hand-picked withholding tax is never replaced by the proposal | `rs_form30_proposed_tax_id` comparison in `_rs_form30_propose_withholding_tax` |
| No manual annex A row outside the matrix of its declaration's month; a generated one gets a blocker | `_check_matrix` for manual rows; `action_generate` for generated rows; both via `_matrix_problems` |
| Rows take the tax version valid on their date | `_rs_form30_version_on` |
| Rows with a blocker never reach a file; rows with a warning only when ticked | `_rs_form30_file_lines`, `_rs_form30_file_service_lines` |
| Export completeness, ID format, date in month, positive amount | `_check_lines`, `_check_car_lines`, `_check_service_lines` |
| Category periods do not overlap; dates in order | `_check_periods`, `_date_order` |
| Classifier and rule validity is a real `YYYYMM`; rate 0–100 | `check_period_bounds`, `RsForm30RateRule._check_validity` |
| A recipient lands in one annex only | the single `_rs_form30_pays_own_tax` predicate |
| Typed main-part cells are never overwritten; proposed ones only while untouched | `_sync_summary_lines` |

Invariants other code relies on: a row's `category_id` and `country_id` are stored snapshots, not
related fields, so a filed row never changes when the contact does; `warning` is canonical English;
the unique month means an amendment is the same record regenerated.

## 7. Security

| Models | Read | Create, write, delete |
|---|---|---|
| Categories, income types, rate rules, car engine bands, service types | `base.group_user` | `account.group_account_manager`: create and write only (close a rule with Valid To, archive the rest) |
| Main-part cells, account rules | `base.group_user` | `account.group_account_manager` |
| Declaration, annex A / D / E rows, main-part values | `account.group_account_readonly` | `account.group_account_user` |
| Category history | `base.group_user` | `account.group_account_user`, `base.group_partner_manager` |
| Exempt usage | `base.group_user` | `account.group_account_user` |
| `rs.form30.tax.change` | — | `account.group_account_manager` |
| `rs.form30.set.withholding.tax` | — | `account.group_account_user`, own records only |
| `rs.form30.explain` | `account.group_account_readonly` (all rights) | |

Company restriction rows: declaration and the four row models on `company_id in company_ids`;
account rules on `company_id parent_of company_ids` (rules live on the root company); category
history follows the core contact rule. Exempt usage has no company row on purpose: the allowance
is per person across companies.

`sudo()` and why it is safe:

| Where | Why |
|---|---|
| `_rs_form30_salary_data`, `_rs_form30_salary_settlement`, `hr.payslip` family and net-line helpers, `_label`, `_trace_item`, the `_xlsx_*` writers | The accountant has no payroll or HR access; reads are scoped to the declaration's company and expose what the rows already show |
| `_rs_form30_cash_parts`, `_rs_form30_entry_settlement`, `_rs_form30_mark_stale`, the expense check in `_rs_form30_bill_vals` | The accountant may lack access to the payments, bank journals or expenses that settled a line; only amounts, dates and states are read |
| `_rs_form30_get_rules`, `_rs_form30_get_taxes`, `_rs_form30_candidates`, `_rs_form30_missing_tax_moves`, `_rs_form30_plain_entries` | Rules, taxes, tax groups, rate rules and categories are configuration read by every user who posts; filtered by the root company |
| `hr.payslip.action_payslip_unpaid` | Payroll users may not read Form 30 rows; only the note data is read |
| `_rs_form30_export_exempt` | Writes the technical stamp on the contacts it locked |
| `RsForm30CarLine._onchange_employee_id` | Reads the chosen employee's legal name and ID for the row |
| `RsForm30RateRule.write`, `_rs_form30_load_codes` | `ir.model.data` of this module's rule xmlids and of `base` countries |

## 8. Integration

No module depends on this one. What it reads from others:

| Module | Relies on | If it changes |
|---|---|---|
| `geo_payroll` | Rule codes `GROSS`, `PIT`, `PENSION_EE`, `ADV_PIT_PRE`, `ADV_PEE_PRE`; input `ADVANCE_PAY`; `hr.payroll.tax.exemption.employee_ids`; PIT at 20%; `_gec_net_account` | A renamed code makes amounts silently 0; a changed PIT rate breaks the relief formula; a different net account loses the salary settlement |
| `hr_payroll`, `hr_payroll_account` | `hr.payslip.state`, `paid_date`, `credit_note`, `is_refund_payslip`, `origin_payslip_id`, `related_payslip_ids`, `edited`, `version_id`, `move_id`, `net_wage`, line `code` / `total`, input `code` / `amount` | Row selection, families, dating |
| `hr` | `hr.version.identification_id`, `private_street`, `private_street2`, `private_city`, `country_id`, `work_location_id`; `hr.employee.legal_name`, `work_contact_id` | Identity columns, residency fallback, cells 57¹ / 57² |
| `gec_localization` | `account.tax.gec_is_withholding`; the tax template xmlids in `data/template/account.tax-ge.csv`; tax groups `gec_tax_group_wht_res` / `_nr`; `res.partner.gec_treasury_code`; hooks `_gec_withholding_tax_lines`, `_gec_partner_purchase_tax`, `l10n.ge.cit.wizard._gec_default_dividend_wht_tax`; view `view_tax_form_ge_withholding`; `gec_account_140311` | A renamed xmlid leaves a tax unmapped; a renamed hook silently stops the Treasury Pay of entries or the dated defaults |
| `l10n_account_withholding_tax` | `account.payment.withholding.line` (`payment_id`, `tax_id`, `base_amount`, `amount`, `company_id`); `account.payment.withhold` | Payment rows only |
| `account` | `_post`, `_get_alerts`, `button_draft`, `_check_fiscal_lock_dates`, `_get_automatic_balancing_account`; partials (`matched_debit_ids`), `reversal_move_ids`, `exchange_diff_partial_ids`, `statement_line_id`, `payment_id`, `is_matched`, `reconciled_statement_line_ids`; `tax_line_id`, `tax_base_amount`, `display_type`; cash journals' `default_account_id` | Cash dating, proposal, cells 58–69 |
| `fleet`, `hr_fleet` | `license_plate`, `driver_employee_id`; view `fleet.fleet_vehicle_view_form` | Annex D prefill |
| `base` | `res.partner.vat`, `is_company`, `_display_address`; views `base.view_partner_form` (page `sales_purchases`) and `base.view_partner_tree`; `res.company.chart_template` | Identity columns, view inherits, tax mapping scope |
| `hr_expense` (optional) | `account.move.expense_ids` | Expense bills would become rows |

## 9. Tests

```bash
data_venv/bin/python odoo-bin -c odoo.conf -d <scratch db> -i gec_income_tax_report --test-enable --test-tags /gec_income_tax_report --stop-after-init --http-port=8079
```

All classes are `post_install`. The grid test needs Chrome and `websocket-client`; a free
`--http-port` keeps the run clear of a dev server on 8069.

| File | Covers |
|---|---|
| `tests/test_form30.py` | `TestForm30Salary` (on `GeoPayrollCase`): payslips computed, validated and paid; salary row values, ID fallback, exempt relief, residency from nationality, month filter, manual rows kept, export file, matrix refusals, bad Georgian ID, name and ID helpers, warning translation. `TestForm30Grid` (`HttpCase`): the form renders the grid without OWL errors. `TestForm30Payments` (on `AccountTestInvoicingCommon`): withholding payment → row → export; residency from the contact; matrix refusal |
| `tests/test_tax_configuration.py` | Combined, tax-only and rules-only changes; allow / stop; finite and conflicting future rules; manual rule edit surviving a CSV reload; month and range checks; wizard defaults and preview; non-manager refusal; category history boundaries and gaps |

Not covered: entry rows, bill rows, the tax proposal and Set Withholding Tax, In File and the
filed-once logic, part payments and payslip correction families, annex D, annex E, the main part,
the treaty draw, the explanation page and workbook.

## 10. Extending safely

- **Another automatic row source**: return vals with the same keys, a `source` value, `move_id`
  or another link, and `settlement_payment_ids` / `settlement_statement_line_ids`; date and share
  them through `_rs_form30_cash_parts` and `_rs_form30_month_share`, pass them through
  `_rs_form30_drop_filed`, extend `_rs_form30_source` and `_rs_form30_mark_stale`, and classify
  through `_recipient_classification`. Without the settlement keys a filed row is declared again.
- **Keep the portal's column order.** Files are read by position: change `HEADERS` and
  `_export_values` together, per model.
- **New main-part logic goes into `_summary_values` or `_ledger_values` through `add()`**, never
  beside them, so the explanation page and the workbook keep matching the stored values; add the
  sentence to `FORMULAS`.
- **Keep the matrix as a constraint for manual rows.** Generated rows carry it as a blocker, so one
  bad row never stops the month; completeness stays at export so unfinished rows can be saved.
- **Never rename classifier xmlids or delete classifier records**: rows restrict them and filed
  months must stay reproducible.
- **A new Georgian withholding tax**: add it to the `gec_localization` template, then one line in
  `data/template/account.tax-ge.csv`, check its (category, income type, rate) pairs in the matrix,
  and run `_rs_form30_map_ge_taxes` once on existing databases.
- **A new warning**: store it in English and add one row to `WARNINGS` in `rs_form30_warning.py`:
  the text inside `_lt()`, with `%s` or `%(name)s` where a value goes, and its level. A text
  without a row is shown in English with level `warning`.
- **Different salary rate**: add a dated value to geo_payroll's `gec_ge_pit_rate` rule parameter; the
  row takes the value at the slip's end date. Check the rate matrix allows it (0, 5, 10, 12 and 20 for 1.1 / type 1).

## 11. Known limitations

- **`action_export_explanation` writes on a draft declaration**, so an Accounting Read-only user,
  who can open the declaration and sees the button, gets an access error before the first export.
- **Treaty draw uses the withheld tax**, not the shortfall against base × rate; whether that matches
  the portal's reading of column 12 is open (gap plan A4).
- **An entry to an own-tax recipient needs a withholding tax** to be seen; a label tax reaches annex
  E only on bills.
- **Entry, bill and payment rows get no relief.** A withholding reduced by hand below base × rate
  makes the portal compute more tax than was withheld.
- **Main-part routing and ledger cells are unverified against a portal upload**, and so are the
  pension and tax the portal computes; README section 9 lists the assumptions.
- **Newer strings are missing from `ka_GE.po`**: the work-location field, the explanation page and
  the workbook show English on the Georgian screen.
- **Tests do not cover the entry and bill sources** (section 9); the grid test's selector also
  matches the empty-state row.
