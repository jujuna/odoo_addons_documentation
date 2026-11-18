# gec_income_tax_report — rs.ge Form 30 (withholding declaration)

> **Module:** `gec_income_tax_report` 20.0.1.14.0 | **Path:** [`custom_addons/gec_odoo_modules/gec_income_tax_report/`](../custom_addons/gec_odoo_modules/gec_income_tax_report/)
> Verified against the module source on 2026-11-03.

## Status on Odoo 20

- **Installed on `gec20_prod1`.** Rows come from four sources: payslips, manual journal entries, vendor bills and (legacy) payments with a withholding line. The Georgian withholding taxes are no longer payment-time taxes, so in practice entries and bills carry all non-salary withholding.
- **Persons and companies.** In 20.0 `is_company` is computed: a contact is a company when it is its own commercial entity and has a Tax ID ([res_partner.py:946](../odoo/addons/base/models/res_partner.py#L946)). `gec_localization` refines it: a Georgian 11-digit personal number in Tax ID makes the contact a person ([res_partner.py](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py), `_compute_is_company`). Entry, bill, payment and annex E rows split names on `is_company` (`_split_name`); salary rows always split as persons.

### Known issues (2026-11-03)

| # | Issue | Evidence |
|---|---|---|
| UI | RS rule lists show the YYYYMM validity with a thousands separator ("202,504" = April 2025) | the integer fields `valid_from` / `valid_to` in `rs_form30_classifier_views.xml` and `account_tax_views.xml` |
| T1 | The automated tests cover salary and payment rows only; entry rows, bill rows, the tax proposal, In File and part payments have no test | [`tests/`](../custom_addons/gec_odoo_modules/gec_income_tax_report/tests/) |
| E1 | Explanation Workbook on a draft declaration writes on it, so an Accounting Read-only user gets an access error | [`rs_form30_declaration_xlsx.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/rs_form30_declaration_xlsx.py), `action_export_explanation` |

## What It Does & Why It Exists

Every month a Georgian employer files the "გადახდის წყაროსთან დაკავებული გადასახადის დეკლარაცია" (rs.ge form 30) by the 15th. The portal needs one annex row per recipient and payment: who was paid, which category of recipient, which kind of income, how much, when, at which rate. The portal then computes the withheld tax, the pension 2% and the main-part totals itself.

This module collects those rows from what Odoo already booked and paid, checks them against the rs.ge classifier matrix and writes the import files the portal accepts. It builds four pages of the declaration:

| Portal page | What the module does |
|---|---|
| 2. Annex A (payments and withheld tax) | Generated from paid payslips, paid journal entries and vendor bills with a withholding tax, and withholding payments; read-only grid plus manual rows; 14-column file |
| 3. Annex D (private use of a company car) | Rows typed by the accountant, pre-filled from the vehicle; 5-column file |
| 4. Annex E (service fees not withheld at source) | Generated for recipients who pay their own tax, and from bill lines labelled for annex E; 7-column file |
| 5. Main part (cells 16–69) | Derived as a cross-check and as proposals for the typed cells; no file, the accountant copies it |

It also helps book the withholding: when a manual journal entry is posted, it recognises the withholding from the entry's accounts and puts the right withholding tax on it. Page 1 stays on the portal. The module books no amounts, sends nothing and runs no cron.

---

## The Big Picture — How It Works

```
Book: payslip / journal entry with WHT tax / vendor bill with WHT tax --> pay the recipient
Declare: New (month) --> Generate Lines --> review warnings and Not Declared, fix sources, regenerate
         --> annex D and manual rows --> main part --> Export rs.ge Files (rows become In File)
         --> upload on eservices.rs.ge
```

| Step | What happens | Source |
|---|---|---|
| Post a journal entry | Odoo matches the entry's accounts with the Account Rules and, when exactly one withholding tax fits, puts it on the expense line | `account.move._post`, [`account_move.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/account_move.py) |
| New | One declaration per company and month; the month defaults to last month and must start on day 1 | `RsForm30Declaration` |
| Generate Lines | Deletes the automatic rows that are not In File, rebuilds them from everything paid in the month, fills the Not Declared lists, refreshes the main part | `action_generate`, [`rs_form30_declaration.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/rs_form30_declaration.py) |
| Review | Each row has a level: blocker (never exported), warning (exported only when **Export rows with warnings** is ticked), note; each row links to its source | annex A grid |
| Export rs.ge Files | Blocks In File rows whose payment or source changed since the last export, validates the selected rows, stores one file per annex (`form30_a_YYYYMM.xml`, `_d_`, `_e_`), marks the rows In File, sets state `exported` | `action_export` |
| Reset to Draft / Clear In File Marks | Reopens the month; clearing the marks lets the filed rows be rebuilt | `action_draft`, `action_clear_in_file` |

Generation reads the database at the click. Late data appears only at the next Generate. A row the rs.ge matrix refuses is kept with a blocker instead of rolling back the month.

### Key Decision Points

- **Paid or not:** a row exists only for money paid in the month; the date is the bank statement date when the payment is matched, else the payment date, never before the document itself (an advance counts in the document's month). An offset entry counts as payment on its date. Part payments split the document by month.
- **Category of the recipient:** the contact's category history, resolved on the payment date. It decides which rates are allowed.
- **Income type and rate:** the withholding tax on the entry, bill or payment. One tax per income type; never reuse a tax because the rate matches.
- **Residency:** the contact's standard Country; each `res.country` carries its rs.ge code.
- **Annex A or annex E:** **Individual Entrepreneur** or **Small Business Status** on the contact.
- **Cells 57¹ / 57²:** the work location flag Adjara / Abkhazia on the employee's version.

---

## When to Use It (and When Not To)

### This module is for:
- A Georgian company paying salaries through `geo_payroll`, and other withheld income (dividends, interest, royalties, rent, services, goods from individuals, non-resident fees) booked as manual journal entries or vendor bills with a Georgian withholding tax.
- The monthly filing, and its amendments, on eservices.rs.ge.

### Use something else when:
- VAT declaration: `l10n_ge`'s VAT report, see [`l10n_ge.md`](l10n_ge.md).
- Booking the dividend itself: the `gec_localization` CIT wizard. Its entry carries the dividend withholding tax, so Form 30 declares it once the shareholder is paid.
- Pension payments to the agency: `geo_payroll` / `gec_payroll_bank`.

---

## Real-World Scenarios

### Scenario 1: September salaries paid on 5 October
**Situation:** payroll runs September payslips; the accountant pays them with Pay Salaries (`gec_payroll_bank`) on 5 October.
**What they do:** early November, create the October declaration and press Generate Lines.
**What happens:** each slip whose net salary line was settled in October gives one row (income type 1, rate 20), dated on the payment. A slip paid half in October and half in November gives half a row in each month.

### Scenario 2: Dividend by journal entry
**Situation:** Dr 530110 5,000 / Cr 340120 shareholder 5,000; Dr 340120 250 / Cr 331210 250. The shareholder's category is 1.4.
**What happens:** at posting, the income type 2 Account Rule (C 530110, D 340120, F 331210) matches and **WHT 5% - Resident Individual Dividends** is the one tax at an allowed rate for 1.4, so Odoo puts it on the 530110 line. Until the shareholder is paid, the entry sits under **Not Declared > Unpaid Entries**. Paid 4,750 on 15 December: one December row, amount 5,000 (net + tax), tax 250, rate 5.

### Scenario 3: Service from a person not registered at rs.ge
**Situation:** a vendor bill for 1,000 with **WHT 20% - Resident Individual Services (unregistered)**; the person is category 1.2.1.
**What happens:** the bill's tax line holds 200; the person is owed 800. When the bill is paid, one row: amount 1,000 (`tax_base_amount`), tax 200, rate 20, income type 7. With the **(company pays)** version of the tax the person gets 1,000 and the row is 1,250 / 250.

### Scenario 4: Service fee to a registered sole trader
**Situation:** the contact is ticked **Individual Entrepreneur (ი/მ)**.
**What happens:** a paid bill or entry for them goes to annex E with the service type of the tax (else of the contact). A bill line without a negative withholding tax reaches annex E when it carries a tax with **Declare in Annex E**, also when another line of the same bill is withheld.

### Scenario 5: Company car used privately
**What they do:** Annex D tab, Add a line, pick the vehicle. Plate, engine band and driver fill in; the employee fills the name and personal number.
**What happens:** the tax amount is the band amount when the band is picked (e.g. 100 GEL under 2,500 cm3) and is added to cell 57. A later edit of the band amount does not change existing rows: pick the band again. Generate Lines never touches these rows.

---

## How Things Work Under the Hood

### Cash: what "paid in the month" means

Every source is reduced to the credit line that owes the recipient: the payslip's net line, the entry's payable line per person, the bill's payment-term line. `_rs_form30_cash_parts` ([`account_move_line.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/account_move_line.py)) reads what settled that line:

| Settled by | Counts as | Dated |
|---|---|---|
| Bank statement line | cash | statement date |
| Paid payment | cash | latest matched statement date, else payment date with a warning |
| Offset entry: a plain journal entry whose other side is only the person's debt or advance (asset accounts, not cash) | cash, warning "Settled by an offset entry" | entry date (the offset act) |
| Write-off, reclass to another liability, credit note | not cash, warning | — |

An offset or advance closing counts as payment, in the month of the offset act; an advance already taxed when paid is not declared again, so these rows carry a warning and stay out of the file until reviewed (accountant, 2026-11-10). Money paid before its document is dated in the document's month (`invoice_date`, else date), with the warning "Paid in advance, before the document".

`_rs_form30_month_share` turns the cash dated in the month into a share of the document (paid through the month minus paid before it); gross, tax and pension are multiplied by that share, so the months of a part-paid document add up to the whole.

### Filed once: In File rows

Once a declaration is exported, its annex D car rows and its main-part rows refuse any change on the server until Reset to Draft (`_refuse_exported_rows`). Generate Lines, Reset to Draft and, on a journal entry, Set Withholding Tax and Detect Again ask for confirmation first.

Export marks the rows of the files **In File**. Generate Lines keeps them, and `_rs_form30_declared` / `_rs_form30_drop_filed` drop any new row whose payment or bank line is already in a file of the company, in this month or another (another month adds an "already declared in ..." warning). An In File row whose payment was cancelled or whose source was reversed gets the blocker "Filed, but its payment or source changed after the export". Rows of an exported declaration cannot be edited or deleted; Set Withholding Tax and Detect Again refuse a filed entry. **Clear In File Marks** (draft only) lets the next Generate rebuild them.

### Annex A — salary rows (`_rs_form30_salary_data`)

Payslips of the company in state validated or paid, not credit notes or refunds. Payroll is read with `sudo()`, because the filing accountant usually has no payroll access.

| Column | Value |
|---|---|
| Gross amount | `GROSS` line + Σ `ADVANCE_PAY` inputs, times the month share |
| Withheld tax (control) | `−PIT` + `ADV_PIT_PRE` |
| Pension (control) | `−PENSION_EE` + `ADV_PEE_PRE` |
| Other relief (col. 9) | employees in any `hr.payroll.tax.exemption` whose yearly allowance is not used up before the slip (`_gec_exemption_remaining`): `amount − pension − tax × 100 / rate`, with a warning; 0 once the allowance is used up |
| Date | latest cash date of the net line in the month; a slip marked paid without a payment uses `paid_date` with a warning |
| Rate | the slip's PIT rate: geo_payroll rule parameter `gec_ge_pit_rate` at the slip's end date (20) |
| ID | `version.identification_id`; else the work contact's Tax ID, with a warning; spaces and a leading `GE` are removed, a foreign prefix stays |
| Name / address | `legal_name` split into first / last name; the version's private street and city |
| Category / residency | work contact's category on the date; no category at all gives 1.1 with a warning, a gap leaves it empty. Residency = work contact country, else Nationality, else Georgia with a warning |

**Corrections.** A payslip, its refunds and corrections form one family (`origin_payslip_id`, `related_payslip_ids`). Only the final correction is declared, by the months its net was paid. Once rows of the family are In File, a month declares only the difference: the final figures times the share of net paid through the month, minus the gross, tax and pension already In File (earlier months and this declaration). A correction that lowers any of them, or raises pay that is never paid in cash, gives no row and the warning "correct that declaration, then generate this month again": a refund cannot be a row, the earlier month is amended. Cash of the family dated before the month but in no file blocks the difference row with "export the declaration of ... first, then generate this month again" (else that month would be declared twice). A family not yet In File whose older slip sits in an earlier declaration that is not exported warns "generate the declaration of ... again" (that month carries the figures from before the correction). Difference rows carry the note "Corrected by ... after earlier months were filed". A slip with an open net line at month end goes to **Unpaid Entries**. Rule codes come from `geo_payroll`; the net line is the line on the NET account (`_gec_net_account`), else the employee's reconcilable line.

### Annex A — journal entry rows (`_rs_form30_entry_vals`)

Posted manual entries (general journal; not payment, bank, reversal, opening or payslip entries) with a line tax that has a **Form 30 Income Type**. No date limit: an old entry paid this month is found.

| Lines of the entry | Role |
|---|---|
| Credit on an Account Rule's **Withholding Credit (F)** account, no partner or the State Treasury | the tax |
| Lines on the company's **Pension Liability** / **Employer Pension Expense** accounts | the pension |
| Lines with a partner on a reconcilable account, net credit | one recipient per commercial partner |
| Credits on a non-reconcilable liability | not payable: listed under **Entries Without a Payable Recipient** |

Tax and pension are split over recipients by net amount; gross = net + tax + pension. Two withholding taxes in one entry, or own-tax and withheld recipients mixed, block the rows. A booked tax that is not `(net + tax) × rate` warns, and the alert on the journal entry uses the same split (`account.move._rs_form30_entry_split`), so both agree; a tax line still open after the person was paid gives the note "Late: the tax was due with the payment". Entries that credit an F account without a withholding tax (last 12 months) are listed under **Entries Missing a Withholding Tax**.

### Withholding tax proposal on entries (`_rs_form30_propose_withholding_tax`)

Each **Account Rule** (Accounting > Configuration > rs.ge Form 30 (Advanced) > Account Rules) names, for one income type, the accrual debit (C), accrual credit (D) and withholding credit (F) accounts. At posting, a rule matches when the entry debits a C account, credits a D account and has a tax line on an F account. If the matched rules give one income type, the candidates are the company's negative withholding taxes of that type, valid on the entry date, of the recipient's residency group, at a rate the matrix allows for the recipient's category (tax-excluded variant preferred). Exactly one candidate goes on the expense lines; otherwise the entry shows "Form 30 will not declare ..." and the accountant uses **Set Withholding Tax**. A tax picked by hand is never replaced. Default rules are seeded for the Georgian chart only when a company has none.

### Annex A — vendor bill rows (`_rs_form30_bill_vals`)

Posted bills and receipts with a withholding tax line that has an income type, or a line tax with **Declare in Annex E**; bills from employee expenses are skipped. One row per withholding tax line, when the bill's payment-term line is paid: amount `tax_base_amount`, tax `−balance`, both times the month share. A credit note counts only when dated after the first payment. The posted bill shows alerts: a default withholding tax missing on a line, a label and a withholding tax on one line, withholding for an own-tax vendor, a category not meant for bills, a rate the matrix refuses, a tax version not valid on the bill date.

### Annex A — payment rows (`_payment_line_vals`)

One row per `account.payment.withholding.line` of an outbound payment in state `paid` or `reconciled`, dated in the month: `base_amount` / `amount` converted at the payment date, income type and rate from the tax. This is Odoo's withholding at payment; no Georgian tax uses it any more, so these rows come only from a tax a user ticks for it.

**Treaty allowance (col. 12).** A contact can carry **Tax Exempt Under International Agreement**. At export each selected row draws its withheld tax from that allowance into column 12 and logs the draw in `rs.form30.exempt.usage`; rows left out or reset to draft give it back. The allowance is per person, shared across companies, and does not reduce cell 57.

**Manual rows** (`source = manual`): **Add Manual Row** on a draft declaration; checked against the matrix when saved; never touched by Generate Lines. An automatic row with the same recipient and income type warns about a double declaration.

### Annex E — service rows

Entry, bill and payment rows whose recipient pays their own tax ([`_rs_form30_pays_own_tax`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/res_partner.py)), plus bill lines with a **Declare in Annex E** label and no negative withholding tax on the same line. Values: ID, names, address, country, service type (tax, else contact; missing = blocker), amount in GEL. With a company-pays tax the amount is what the person received.

### Annex D — car rows ([`rs_form30_car.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/rs_form30_car.py))

Typed in the grid. Picking a vehicle fills the plate, the vehicle's **rs.ge Engine Band** and the `hr_fleet` driver employee; the employee fills "Surname,Name" and the personal number. The tax amount is the band amount: over 3,500 cm3 300, 2,500–3,500 200, under 2,500 100, hybrid 60 (`data/rs.form30.car.engine.csv`, editable). Export needs plate, name and a 9- or 11-digit personal number. The file carries the band **number** (1–4), not the volume.

### Validation: matrix at creation, levels at generation, completeness at export

- **Matrix** (`_check_matrix`, a constraint on manual rows): category and income type valid in the declaration period, the pair present in the rate matrix, the rate among the pair's allowed rates. A failing generated row is kept with a blocker and never exported. Changing the declaration month re-checks manual rows.
- **Levels** (`ISSUE_LEVELS`): blockers (missing category, matrix refusal, two taxes in one entry, missing service type, filed row changed) never reach a file; warnings reach it only with **Export rows with warnings**; notes never hold a row back. The main part counts the same rows as the file.
- **Completeness** (`_validation_errors`, export only): ID, residency, category, income type and date present; residency has an rs.ge code; a Georgian ID has 9 or 11 digits; the date inside the month; amount positive.

### Classifiers = data

| Data | Content |
|---|---|
| `rs.form30.category` | 18 recipient categories; classifier ID ≠ portal number (ID `4` = "1.1", ID `42` = "4"); `is_organization` marks 2, 3.1, 3.3, 3.7, 3.8; Salary / Journal Entry / Vendor Bill flags and a "When to Use" note guide which document a category belongs on (warning only) |
| `rs.form30.income.type` | 15 income types; type 18 valid to 202411 |
| `rs.form30.rate.rule` | 152 rules = one per (category, type, rate) with YYYYMM validity, from the v7 workbook `30_data_7_202505.xlsx` |
| `rs.form30.account.rule` | Per root company: C, D, F accounts per income type, seeded for the Georgian chart, edited by the accountant |
| `res.country.rs_form30_code` | rs.ge code for 235 countries (Georgia = 268) |
| `rs.form30.car.engine`, `rs.form30.service.type` | 4 engine bands, 8 service types |
| `rs.form30.summary.cell` | 60 main-part rows |

Accounting Administrators edit them under Accounting > Configuration > rs.ge Form 30 (Advanced). A manual edit (archive included) of a category, income type, rate rule, engine band or service type sets its xmlid to `noupdate`, so later CSV reloads keep it (`rs.form30.shipped.data`). Managers cannot delete these rows: they close one with Valid To, or archive it (rate rules have no Active). Country codes load through a data function, because base ships country xmlids as `noupdate`. `tools/generate_classifier_csv.py` rebuilds the CSVs from a new rs.ge workbook and keeps the category usage flags.

### Export files (`_build_xml`)

Excel 2003 SpreadsheetML, worksheet `data`, one header row, every cell `ss:Type="String"`, dates `DD.MM.YYYY`, decimals with a dot, empty cells written as one space (as the portal's own export does). Annex A has the 14 portal import columns; the portal screen shows 16, because it adds pension and tax. Annex E follows the portal import order. An annex without rows gets no file.

### Main part (cells 16–69)

`_summary_values` derives every cell from the annex A rows that go into the file and from the ledger; `_sync_summary_lines` stores them at create, Generate and Export.

| Kind | Cells | Refresh |
|---|---|---|
| Computed (padlock) | 44 cells, 16–57 incl. 20¹, 56² | always overwritten; the portal computes them too, so they are a cross-check |
| Proposed (wand) | 57¹, 57², 58, 59, 61, 63, 65–69 | Odoo refreshes the value while it still equals the last proposal (`proposed_value`); a typed value stays. Cell 59 is a checkbox and is always overwritten |
| Typed | 56¹, 60, 62, 64 | never touched |

Definitions: base of a row = amount − pension − other relief (portal col. 7 − 8 − 9); tax = round(base × rate / 100) (portal col. 12). Routing (`_main_part_cells`):

| Cells | Rule |
|---|---|
| 16 / 17 | Σ amount / Σ base of income type 1 rows |
| 18 | Σ amount of royalty rows to resident individuals; memo, not summed into 39 |
| 19 / 20 / 20¹ | individuals, types 6, 7, 17, 19, 20 by rate 20 / 5 / 3, base; non-resident rows at 20 also land in 19 |
| 21 | individuals, types 5, 16, 21, 22, 23, base |
| 22–25 | dividends / interest to individuals: amount, then base |
| 26 | categories 1.3 and 3.10, base |
| 27–32 / 33–38 | non-resident individuals: 3.2 → 32, 3.6 → 29, 3.5 → 30, royalty at 5 → 28, other → 31; amount / base; 27 and 33 are sums |
| 39 | Σ tax of individual rows |
| 40–47 / 48–55 | organizations: 3.1 → 45, 3.8 → 42, 3.7 → 43, dividends → 46, interest → 47, royalty at 5 → 41, other → 44; amount / base; 40 and 48 are sums |
| 56 / 56² | Σ tax of organization rows / 12% of typed 56¹ |
| 57 | 39 + 56 + 56² + Σ annex D tax − Σ annex A foreign tax credit (Order 996 art. 38) |
| 57¹ / 57² | Σ tax of salary rows whose `autonomous_republic` is Adjara / Abkhazia |
| 58 | −Σ posted balance on `income` accounts in the month |
| 59 | ticked when a posted expense line exists in the month |
| 61 / 65 / 66 | salary persons: count, highest total, lowest total above zero |
| 63 | Σ inbound payments on cash journals in the month |
| 67 | balance of the cash journals' default accounts at month end |
| 68 / 69 | positive per-partner balances on 140311 "Settlements with Accountable Persons" (`gec_account_140311`) at month end: sum, count |

Assumptions not yet confirmed by a portal upload: 58 takes every income account, 63 every cash-journal receipt, 68/69 only 140311, non-resident rate-20 rows in 19.

**Question-mark button** per main-part row: opens `rs.form30.explain` with the formula, the stored value, its kind, every contributing row or journal item with its arithmetic and link, and flags a computed cell whose stored value differs from a fresh calculation.

**Explanation Workbook** (header button): writes `form30_explained_<period>.xlsx` with eight sheets (Read me, Annex A, Payslips, Payments, Annex D, Annex E, Main part, Cell details) from one traced calculation. Export stores one; on a draft every click rebuilds it.

### Tax / RS change wizard

Accounting Administrators only, from the tax form's **RS Declaration Rules** tab ([`rs_form30_tax_change.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/wizard/rs_form30_tax_change.py)). For a dated law change it can copy the tax with a new rate and close the old one the day before (`rs_form30_date_from` / `_to`, `rs_form30_previous_tax_id`), and end or start rate rules from the effective month. Every row takes the tax version valid on its date (`_rs_form30_version_on`), and so do the contact's default purchase tax and the CIT wizard's dividend tax. Rules are shared by every company and tax with that income type. It never changes the payroll salary rate.

### Screens, translation, tests

- Grids are OWL 3 field widgets extending `X2ManyField`: column filters and totals apply to the **current page** (100 rows), column widths auto-fit and drag, rows tinted by level, light and dark theme.
- `i18n/ka_GE.po` translates the form, grids, warnings and wizards. Not translated: the explanation formulas, the workbook, and the work-location field. Warnings are stored in English and translated at display (`warning_display`).
- Tests: [`test_form30.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/tests/test_form30.py) (salary, payments, grid) and [`test_tax_configuration.py`](../custom_addons/gec_odoo_modules/gec_income_tax_report/tests/test_tax_configuration.py) (change wizard, category history). See known issue T1.

---

## Configuration & Settings

| Where | Field | What it changes |
|---|---|---|
| Contact > Sales & Purchase > rs.ge Form 30 | **Form 30 Category History** (category, inclusive Valid From / Valid To, no overlap) | The category of every row paid on a date inside the period. Empty Valid From = always applied. Once history exists it replaces the legacy **Category Without History**, and a gap leaves the row without category (export blocked) |
| same | **Individual Entrepreneur** / **Small Business Status** | Moves the contact's rows from annex A to annex E |
| same | **Form 30 Service Type** | Annex E service kind when the tax has none |
| same | **Tax Exempt Under International Agreement** | Treaty allowance drawn into column 12; **Usage** lists every draw |
| Contact > Country | standard `country_id` | Residency; a country without rs.ge code blocks the export |
| Accounting > Configuration > Taxes > a withholding tax | **Form 30 Income Type**, **Form 30 Service Type**, **Declare in Annex E** | Income type and rate of the rows; annex E service kind; a 0% label that sends a bill to annex E. Filled at install for the `gec_localization` taxes listed in [`data/template/account.tax-ge.csv`](../custom_addons/gec_odoo_modules/gec_income_tax_report/data/template/account.tax-ge.csv) where still empty. A withholding tax without income type is invisible to Form 30 |
| Accounting > Configuration > rs.ge Form 30 (Advanced) > Account Rules | **Accrual Debit (C)**, **Accrual Credit (D)**, **Withholding Credit (F)** per income type | Which entries get a withholding tax proposed, which lines count as the tax, and which entries are listed as missing a tax |
| Accounting > Configuration > Settings | **Pension Liability Accounts**, **Employer Pension Expense Accounts** | Pension lines of an entry: they go into the row's pension and gross, not the recipient's net |
| Employees > Configuration > Work Locations | **Form 30 Autonomous Republic** | Feeds 57¹ / 57² with the tax of salary rows at that location |
| Fleet > Vehicle | **rs.ge Engine Band** | Pre-fills the band of annex D rows |
| Employee (version) | Identification No, Nationality | Salary row ID; Nationality is the residency fallback |
| Declaration header | **Export rows with warnings** | Includes rows with a warning in the files and the main part |

Income types by source: 1 from payslips (and the salary taxes when salary is booked outside payroll); every other type from the withholding tax mapped to it in the template CSV. Type 18 is valid only to 202411.

Access ([ir.access.csv](../custom_addons/gec_odoo_modules/gec_income_tax_report/security/ir.access.csv)): read-only accounting users see declarations; users with full accounting features (`account.group_account_user`) create, generate, export and use Set Withholding Tax; Accounting Administrators edit classifiers and Account Rules and run the change wizard. Declarations and all line models carry a company restriction row; Account Rules live on the root company.

---

## Dependencies

| Requires | Why |
|---|---|
| `geo_payroll` | Payslips, rule codes `GROSS`, `PIT`, `PENSION_EE`, `ADV_PIT_PRE`, `ADV_PEE_PRE`, input `ADVANCE_PAY`, the tax exemption model, the NET account |
| `gec_localization` | The Georgian withholding taxes (`gec_is_withholding`, tax groups), the State Treasury contact, the Treasury Pay hook that also pays the tax lines of entries, the CIT wizard, account 140311 |
| `l10n_account_withholding_tax` | `account.payment.withholding.line` for the payment rows |
| `hr_fleet` | Vehicles with a driver employee for annex D |

| Works With (not a dependency) | What It Adds |
|---|---|
| `gec_payroll_bank` | Pay Salaries pays the net salary lines the salary rows are dated by |
| `hr_expense` | Bills created from expenses are skipped |
| `nbg_rates` | Fetches only EUR and USD; other currencies need a manual rate for the payment date |

---

## Design Decisions and Why

| Decision | Reason |
|---|---|
| Rows come from the documents that owe a person (payslip, entry, bill, payment), never from tax grids, GL balances or `account.return` | Form 30 is per person, per payment, cash basis. Grids and balances have no person or date; 331210 collects the withholding of all recipients, so a balance cannot be split per person |
| Withholding is booked by hand; Odoo only reads and proposes the tax | The accountant's entries are the books. Odoo calculates nothing on entries, so the tax rate and amount the accountant booked are what is declared, with a warning when they disagree |
| Category on the contact, income type on the tax | A category describes the recipient; the income type describes the payment. One person can receive salary, dividends and royalties |
| Category and residency are set by a person | No Odoo field proves tax residency. Salary rows default to 1.1 / Georgia with a warning; other rows block the export |
| Date = the day the money left, dated by the bank when matched | Cash basis matches the portal's payment date (Tax Code art. 154: tax due at payment) |
| Part payments split by month, filed cash never declared twice | A document paid across months must add up to its whole once, and a re-generated month must not repeat a filed payment |
| Rows with warnings stay out of the file until ticked | An unchecked guess should not reach rs.ge silently; the count of left-out rows keeps it visible |
| Salary math never adds `REPAY_*` lines | Advance repayments are balance-sheet closings; the advance was declared when paid (`ADVANCE_PAY`), and the repayment month's `GROSS` is already reduced. Signs: withheld = (−PIT) + ADV_PIT_PRE |
| Rate = `abs(tax.amount)` | Base and withheld amount may be edited; tax / base is not a reliable rate |
| No 0% withholding tax for treaty cases | The matrix allows rate 0 only for salary and gambling payouts. Use the treaty allowance (col. 12) |
| New withholding taxes live in `gec_localization` | It creates missing template records per company and never rewrites existing ones; this module only maps the income type |
| Country codes on `res.country` | The Form 30 classifier sheet is the authority for the residency column |
| File import, no API | No rs.ge submission API for Form 30 was identified [Unverified]; the portal's "ატვირთვა ფაილიდან" takes the SpreadsheetML file |

---

## Gotchas & Non-Obvious Behavior

- **No payment, no row.** An entry booked in March and paid in May is a May row; an unpaid entry is only listed under Not Declared.
- **The person must be on a reconcilable payable account.** On a non-reconcilable liability Odoo cannot see the payment: the entry is listed as without a payable recipient and never declared.
- **One withholding tax per entry.** Two taxes, or a self-taxed and a withheld recipient in one entry, block every row of it.
- **A hand-picked tax sticks.** Once any withholding tax on the entry differs from Odoo's proposal, posting and Detect Again leave the entry alone.
- **Edited payslips warn forever.** Any inline line edit sets `hr.payslip.edited` and nothing clears it ([hr_payslip.py:173](../enterprise/hr_payroll/models/hr_payslip.py#L173)).
- **Relief is derived, not stored.** Relief = amount − pension − tax × 100 / rate, so base × rate always equals the withheld tax. Payroll takes the full employee pension off before the exemption (geo_payroll since 2026-11-11), so for new payslips the derived relief equals the allowance used; on payslips computed before, it comes out at 98% of it. Details: [`rs_form30_full_declaration_gap_plan.md`](../dev_notes/plans/rs_form30_full_declaration_gap_plan.md) §4.
- **Relief follows today's data.** `pension_fund_member` sits on the employee, not the version, so regenerating an old month uses today's flag.
- **Do not reconcile Form 30 with the month's ledger movement** on 331210 / 331310 / 331320: documents are dated by accrual, the declaration by payment.
- **A payment sent from internet banking** only appears as a bank statement line. Matched with the entry's or bill's payable line it dates the row; with nothing to match, add a manual row.
- **The income type is only as right as the tax.** Categories 4 and 30 accept both type 7 and type 17 at 20%, so a royalty booked with the services tax is filed as type 7 without a warning.
- **An entry to an ი/მ needs a withholding tax to be seen**; only bills reach annex E through a label.
- **Withheld tax on an annex E row is not declared.** Annex E has no tax column, and the IE / Small Business ticks have no date: a document with booked withholding whose recipient is ticked goes to annex E with the note "Tax was withheld from a recipient who pays their own tax" (a note, so the row is still exported); declare or refund that tax by hand. The same note marks annex E rows of tax withheld at payment.
- **The column layout is hard-coded** (`HEADERS`). Before the first live filing, compare the 14 columns with the portal sample ("ნიმუში").
- **Salary rate follows payroll.** The row takes geo_payroll's `gec_ge_pit_rate` at the slip's end date, the rate payroll withheld. A rate change is a new dated value; never edit or backdate a value once that period's slips are validated, or the row's rate stops matching the withheld tax. Per-employee rates (0, 5, 10, 12 in the matrix) still need manual rows.
- **Totals in the grid footer** cover the visible page only; the header totals cover the declaration. `Total Pension 2%` is the employee share only.
- **An amendment** needs Reset to Draft, Clear In File Marks, Generate and Export, then the full annex re-uploaded; on the portal delete the uploaded rows first, because a second import adds duplicates.
- **Classifier drift:** rs.ge re-versions the classifiers about once a year. Rules carry validity periods, so old months still validate with their own rules.
- **Portal probe still open:** the row math has never been compared with a portal-computed draft under a company registered in the pension e-system.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`rs_form30_full_declaration_gap_plan.md`](../dev_notes/plans/rs_form30_full_declaration_gap_plan.md) — the full declaration (pages 1–6) against Order 996 art. 38, open decisions for the accountant
- [`l10n_ge.md`](l10n_ge.md) — Georgian chart, taxes and VAT report (`l10n_ge` + `gec_localization`)
- [`geo_payroll.md`](geo_payroll.md) — the payslip side (PIT, pension, exemptions, advances)
- Module guides: [`README.md`](../custom_addons/gec_odoo_modules/gec_income_tax_report/README.md) (accountant), [`README_DEV.md`](../custom_addons/gec_odoo_modules/gec_income_tax_report/README_DEV.md) (developer)
- Accountant test guide: [`gec_income_tax_report_accountant_guide.html`](../dev_notes/tests/gec_income_tax_report_accountant_guide.html)
- Domain reference: [`sashemosavlo_deklaraciebi_sruli_cnobari.md`](../sashemosavlo_deklaraciebi_sruli_cnobari.md) — form rules, classifiers, penalties
