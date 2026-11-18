# Georgian Accounting — `l10n_ge` and `gec_localization`

> **Module:** `l10n_ge` (core, LGPL) + `gec_localization` (ours, 20.0.1.2.0, LGPL) | **Path:** [`addons/l10n_ge/`](../addons/l10n_ge/), [`custom_addons/gec_odoo_modules/gec_localization/`](../custom_addons/gec_odoo_modules/gec_localization/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Odoo 20 ships the Georgian localization `l10n_ge`: a 6-digit IFRS chart of accounts, 36 VAT taxes, 4 fiscal positions and the Georgian **VAT Report** laid out like Annex A of the declaration. It is pure data, loaded once when a company picks the chart; it has no fields, views or business logic.

Everything Georgian that needs more than data lives in our extension `gec_localization`. It adds 10 accounts, 62 taxes (withholding, turnover, CIT, out of scope, non-VAT purchases), payroll account settings, a per-company withholding certificate sequence, default taxes per contact, a "Not Taxed" product flag, a profit distribution (CIT) wizard, bank name and BIC from Georgian IBANs, and contact categories.

Users: the accountant who sets up a Georgian company and files the monthly VAT and withholding declarations, and developers of the modules built on it (`geo_payroll`, `gec_payroll_bank`, `gec_income_tax_report`, `basis_bank`). Generic tax mechanics are in [`taxes.md`](taxes.md), return and lock mechanics in [`account_returns.md`](account_returns.md); this doc covers only what is Georgian.

---

## The Big Picture — How It Works

```
Company country = Georgia
  -> Settings > Fiscal Localization: "Georgian Chart of Accounts (IFRS)" (template 'ge')
       l10n_ge:          306 accounts, 5 tax groups, 36 taxes, 4 fiscal positions
       gec_localization: +10 accounts, 3 account overrides, +6 tax groups, +62 taxes, WHT sequence
  -> invoice / bill line: product tax -> contact default tax (ours) -> fiscal position remap
  -> posting copies each repartition line's tags (1(B), 1(T) ... 33(T)) onto the journal items
  -> VAT Report sums balances per tag -> accountant files on rs.ge, sets the tax lock date by hand
  -> bill with a WHT tax -> Pay: "Withhold and Pay" -> bank net, WHT account, certificate number
```

The VAT declaration never reads accounts. It reads **tags** stamped on journal items at posting. That is why the same account (for example 333002 VAT Output) can feed several declaration lines, and why a tax without tags is invisible to the declaration.

### Key Decision Points
- **Which fiscal position a contact gets:** a position pinned on the contact wins; otherwise Tax ID present, absent, foreign country or no country decides (table below). The position decides which VAT tax lands on the line.
- **Which tax the line proposes:** product tax, replaced by the contact's default tax when set (ours), then remapped by the fiscal position. "Not Taxed" products get nothing.
- **How a withholding tax is paid:** the bill carries the WHT tax; the payment withholds it.

---

## When to Use It (and When Not To)

### This is for:
- Any company with country Georgia on Odoo 20: install `gec_localization`, which pulls in `l10n_ge`.
- Companies that pay non-residents or individuals (withholding), distribute profit (CIT) or run payroll through `geo_payroll`.

### Use something else when:
- rs.ge e-invoices and waybills: `rs_einvoice`, `rs_waybill`.
- Form 30 withholding declaration: `gec_income_tax_report` ([`gec_income_tax_report.md`](gec_income_tax_report.md)).
- Salary rules, PIT and pension on payslips: `geo_payroll` ([`geo_payroll.md`](geo_payroll.md)).
- A monthly VAT return card with deadline and lock: not available for Georgia in Odoo 20 (see [The VAT period](#the-vat-period)).

---

## Real-World Scenarios

### Scenario 1: Setting up a new Georgian company
**Situation:** An accountant creates a Georgian LLC in a database where `gec_localization` is installed.
**What they do:** Set the company country to Georgia, then choose **Georgian Chart of Accounts (IFRS)** under Accounting > Configuration > Settings > Fiscal Localization. Work through the [configuration checklist](#configuration--settings).
**What happens:** `l10n_ge` and our module load in the same chart load. Our `_post_load_data` hook also creates the company's own withholding certificate sequence ([template_ge.py:30](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L30)).

### Scenario 2: Monthly VAT declaration
**Situation:** Month end; invoices, bills and credit notes are posted.
**What they do:** Accounting > Reporting > Taxes & Fiscal > **Tax Report** ([accountant_menuitem.xml:14](../enterprise/accountant/views/accountant_menuitem.xml#L14)), variant **VAT Report**, month as period. Type line 4.1 of Part III by hand if needed, copy the lines to the rs.ge declaration, then set the tax lock date.
**What happens:** Each line shows the summed balances of its tags. Credit notes reduce the same lines because they carry the same tags with opposite signs. The report opens on the current month, so pick the month being filed. Accountant's guide in Georgian (entries per case, line table, monthly checks): [`l10n_ge_vat_report.md`](l10n_ge_vat_report.md).

### Scenario 3: Paying a foreign consultant
**Situation:** A non-resident firm invoices 1,000 GEL of management fees.
**What they do:** Post the bill with **WHT 10% - Non-resident Mgmt/Technical Fees** on the line, then click **Pay**; the dialog opens on **Withhold and Pay**.
**What happens:** The bill total stays 1,000. The payment pays 900 from the bank and books 100 on 331212. The vendor's "Non-Georgia" position removes purchase `18%`; reverse charge comes only from the vendor's **Default Purchase Tax** `18% Reverse Charge Services` ([VAT corrections](#corrections-to-l10n_ges-vat-taxes)).

### Scenario 4: Paying a dividend
**Situation:** The owners approve 850 GEL net to an individual shareholder.
**What they do:** Accounting > Accounting > **Profit Distribution (CIT)**, net 850, tick dividend withholding (5%), post.
**What happens:** One posted entry: 1,000 gross, 150 CIT, 42.50 withheld, 807.50 due to the shareholder.

---

## Part 1 — Core `l10n_ge`

### What it ships

| Piece | Source | Content |
|---|---|---|
| Chart | [account.account-ge.csv](../addons/l10n_ge/data/template/account.account-ge.csv) | 306 rows, 6-digit codes, `name@ka` on every row: 256 postable accounts + 50 inactive header accounts (9 roots, 41 second level) that form the hierarchy through `parent_id` |
| Taxes | [account.tax-ge.csv](../addons/l10n_ge/data/template/account.tax-ge.csv) | 36 VAT taxes: 18 sale, 16 purchase, 2 journal-entry only (`18% Loss of Goods`, `18% Retention of Goods`); all on invoice (no cash basis) |
| Tax groups | [account.tax.group-ge.csv](../addons/l10n_ge/data/template/account.tax.group-ge.csv) | VAT 18%, 12%, 5%, 0%, Exempt; name and country only |
| Fiscal positions | [account.fiscal.position-ge.csv](../addons/l10n_ge/data/template/account.fiscal.position-ge.csv) | 4, three auto-applied |
| VAT Report | [account_tax_report_data.xml:3](../addons/l10n_ge/data/account_tax_report_data.xml#L3) | `account.report` "VAT Report", variant of the generic tax report, Base and Tax columns, 42 lines / 67 expressions |
| Company defaults | [template_ge.py:25](../addons/l10n_ge/models/template_ge.py#L25) | default taxes `18%` sale/purchase, receivable 140110, payable 310110, income 611101, expense 749000, bank prefix 120, bank suspense 120210, transfer 100001 |

`account.group` does not exist in 20.0; the hierarchy is header accounts ([`accounting_coa.md`](accounting_coa.md)). Georgian names come from the CSV `name@ka` columns; [ka.po](../addons/l10n_ge/i18n/ka.po) has only empty entries.

### Tax accounts that matter

| Account | Used by |
|---|---|
| 333002 VAT Output | all 18% sale taxes except advances |
| 333011 VAT Accrued on Customer Advances | `18% Advance` |
| 334010 Input VAT Local Purchases | the six domestic 18% purchase taxes (III.1, III.5–III.8) |
| 333040 VAT Payable on Imports | `18% / 12% / 5% Import` |
| 334040 Input Reverse Charge VAT / 333060 Reverse Charge VAT Payable | the +100% / −100% legs of reverse charge |
| 140610 VAT Receivable / 333010 VAT Payable | reconcilable, non-trade; nothing in `l10n_ge` refers to them |
| 331110 CIT, 331210 / 331211 / 331212 WHT, 331310 PIT, 332010 pension, 339090 other taxes | no `l10n_ge` tax; our taxes and payroll use them |

### Taxes and the declaration lines they feed

The report line codes are `ge_1` … `ge_35`; each leaf reads the tags `N(B)` (base) and `N(T)` (tax).

| Declaration line (form numbering) | Tag | `l10n_ge` tax |
|---|---|---|
| I.1 Taxable supplies | 1 | `18%` |
| I.1.1 Margin scheme | 2 | `18% Margin Scheme` |
| I.2 Advances received | 3 | `18% Advance` |
| I.3 / I.5 Free goods / free services | 4 / 6 | `18% Free Supply of Goods` / `18% Free Services` |
| I.4 Inventory shortage | 5 | `18% Loss of Goods` (journal entries) |
| I.6 / I.6.1 Own building use / repairs | 7 / 8 | `18% Use of Own Building` / `18% Building Repairs` |
| I.7 Barter; I.7.1 retention after cessation | 9 / 10 | `18% Barter Sale` / `18% Retention of Goods` (journal entries) |
| I.8 Other taxable | 11 | `18% Other Transactions` |
| I.9–I.13 Exempt supplies | 12–16 | `0% Diplomatic Missions`, `0% Natural Gas`, `0% International Transport`, `0% International Projects`, `0% Inventory` (base only) |
| I.14 Export / re-export ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L291)) | 17 | `0% Export` (base only) |
| I.14.1–14.3 Exempt without deduction | 18–20 | `0% Financial Services`, `0% Land Plot`, `0% Other Exempt` (base only) |
| II.1–II.3 Reverse charge output ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L368)) | 21–23 | `18% Reverse Charge Services`, `18% Customs Warehouse`, `18% Free Industrial Zone` (−100% leg) |
| III.1 Local purchases ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L447)) | 24 | `18%` purchase |
| III.2 Import VAT | 25 | `Import` (tax) and `Import Base` (base) |
| III.3 Import VAT assessed by the authority ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L483)) | 26 | none |
| III.4 Reverse charge input | 27 | the three reverse-charge taxes (+100% leg) |
| III.4.1 ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L519)) | — | typed by hand (`external` engine, editable) |
| III.5–III.8 Fixed assets, building, repairs, barter, auction | 29–33 | `18% Cessation of Activity`, `18% Own Building`, `18% Own Repairs`, `18% Barter Purchase`, `18% Auction` |
| Totals I.15, II.4, III.9, net VAT ([line](../addons/l10n_ge/data/account_tax_report_data.xml#L674)) | — | aggregation formulas |

### Fiscal positions: the mapping lives on the tax

The position CSV has no tax columns. Each tax lists the positions it belongs to (**Fiscal Position**, `fiscal_position_ids`) and the tax it replaces (**Replaces**, `original_tax_ids`). [`map_tax`](../addons/account/models/partner.py#L161) swaps a tax for every tax of the position that replaces it; a tax nobody replaces stays only if it lists this position or lists none, otherwise it is removed.

Detection ([_get_fiscal_position](../addons/account/models/partner.py#L259)): a position pinned on the contact wins; a contact without country gets none ([partner.py:286](../addons/account/models/partner.py#L286)); otherwise the first auto-applied match by sequence.

| Position | Picked for | Sale `18%` becomes | Purchase `18%` becomes |
|---|---|---|---|
| Georgia (VAT Registered), seq 10 | Georgian contact **with any Tax ID** | core: six taxes (`18% Margin Scheme`, `18% Advance`, `18% Other Transactions`, `0% Financial Services`, `0% Land Plot`, `0% Other Exempt`); **ours: `18%`** | kept |
| Georgia (non-VAT Registered), seq 20 | Georgian contact without Tax ID | core: removed; **ours: `18%`** | removed |
| Non-Georgia, seq 30 | any other country | `0% Export` | core: three reverse-charge taxes; **ours: removed** |
| Domestic non-registered individual | only when pinned | core: removed; **ours: `18%`** | removed |

"Core" is `l10n_ge` as shipped; "ours" is what a company gets with `gec_localization` ([corrections](#corrections-to-l10n_ges-vat-taxes)). "VAT Registered" means "has a Tax ID": the check is `has_vat` ([partner.py:932](../addons/account/models/partner.py#L932), [res_partner.py:938](../odoo/addons/base/models/res_partner.py#L938)). Every Georgian company keeps its TIN in `vat`, so non-VAT-payer companies get this position too. Our own taxes list no position, so they pass through every position unchanged.

### What core `l10n_ge` does not do
- No withholding, turnover or CIT taxes; it ships only the WHT accounts.
- No VAT return type, deadline, closing entry or lock ([The VAT period](#the-vat-period)), and no rs.ge submission.
- No VAT on sales to contacts without a Tax ID as shipped (table above); `gec_localization` corrects it.
- No bank list: `res.bank` does not exist in 20.0; bank name and BIC are fields of each bank account.

---

## Part 2 — Our extension `gec_localization`

### How it extends the chart

It defines no chart of its own. Three `@template('ge', model)` functions with unique names return our CSV rows ([template_ge.py:9](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L9), [:19](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L19), [:23](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L23)). Core merges every function's dict per xmlid after `l10n_ge`'s CSV ([_get_chart_template_data](../addons/account/models/chart_template.py#L826)), so a row keyed by an `l10n_ge` xmlid changes only the columns it fills. Tag names are resolved to `l10n_ge`'s tags by [`_deref_account_tags`](../addons/account/models/chart_template.py#L1308).

Template functions are registered by method name and the top of the MRO wins ([chart_template.py:78](../addons/account/models/chart_template.py#L78)): reusing a core name such as `_get_ge_res_company` silently replaces core's function. Our names are `_get_ge_gec_*`; new records use the prefixes `gec_account_*`, `gec_tax_group_*` and `ge_tax_*`.

| Situation | What loads our records |
|---|---|
| Company loads the `ge` chart after the module is installed | normal chart load, ours merged in |
| Module installed while companies already have the `ge` chart | core install hook ([ir_module.py:72](../addons/account/models/ir_module.py#L72)); our `post_init` hook also corrects `l10n_ge`'s VAT taxes once ([below](#corrections-to-l10n_ges-vat-taxes)) |
| Module upgraded | data `<function>` [`_ge_gec_apply_maintenance`](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L36): creates records missing in a company, never rewrites existing ones, fills missing Georgian names. Exception, once per database (flag `gec_localization.tax_texts_20261023`): `_ge_apply_tax_texts` writes the template name, description and invoice label in English and Georgian on every `l10n_ge` and gec tax, and deletes retired taxes (`GE_REMOVED_TAXES`; archived if used); a later rename runs the same pass for the renamed tax only under its own flag (`tax_texts_rc_20261104`: `ge_tax_p_rc_18_nonvatreg`), so labels users edited on other taxes are kept |

**Tax names and labels (2026-10-23).** The accountant's sheet renamed the taxes: `l10n_ge`'s short codes became descriptive names (`18% S` → `18% Margin Scheme` / `18% მარჟის სქემა`), and every tax got a Georgian name. Our taxes carry `name@ka` in [account.tax-ge.csv](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv); `l10n_ge`'s texts are overridden from [ge_core_tax_texts.csv](../custom_addons/gec_odoo_modules/gec_localization/data/template/ge_core_tax_texts.csv) in `_get_account_tax`. The "(company pays)" taxes keep that suffix in the name only; description and label read like the normal withholding tax. `WHT 5% - Resident Individual Residential Rent (company pays)` was removed.

A chart reload never changes **Allow Reconciliation** on an existing account ([chart_template.py:455](../addons/account/models/chart_template.py#L455)). The 331310 override therefore reaches only companies that load the chart after our install. The Payable retypes still land, because the account type forces reconciliation.

### Accounts

14 new accounts ([account.account-ge.csv](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.account-ge.csv#L2)): 110120 Cash in Foreign Currency, 120300 Amounts Receivable via Acquiring, 120980 Conversion, 140311 Settlements with Accountable Persons, 140810 Receivables from Loans Issued, 160310 Computer Assembly, 160910 Additional Expenses, 310250 Gift Card, 331320 PIT Transit, 334011 Input VAT Local Purchases - Fixed Assets, 710500 Purchased Goods Returns, 710700 Direct Services & Subcontractors, 731000 Freight-out & Logistics Services, 740430 Security & Guarding Services. Rental income uses core's 651010.

Settings on core accounts, payroll and withholding ([account.account-ge.csv:10](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.account-ge.csv#L10)):

| Account | Setting | Why |
|---|---|---|
| 310310 Salaries Payable | Payable, reconcilable | accountant's choice: salary debts per employee |
| 332010 Pension Contribution Accrued | Payable, reconcilable | the Pension Agency payment settles it |
| 331310 PIT Accrued | not reconcilable | used only by two WHT taxes; Pay Salaries would otherwise block on its lines |
| 331320 PIT Transit (new) | Payable, reconcilable, non-trade | payroll PIT (`PIT_PAYABLE`, [account_chart_template.py:17](../custom_addons/gec_odoo_modules/geo_payroll/models/account_chart_template.py#L17)), paid to the State Treasury from Pay Salaries |
| 331211 WHT Settled | Payable, reconcilable, non-trade (core: Expense) | withheld tax moved here from 331210 with the State Treasury as partner is paid with the entry line's Pay |

The payment register pays only receivable and payable lines ([account_payment.py:247](../addons/account/models/account_payment.py#L247)); in payroll context `hr_payroll_account` adds current liabilities ([account_payment.py:13](../enterprise/hr_payroll_account/models/account_payment.py#L13)). **Treasury Code** on company contacts ([res_partner.py:29](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py#L29)) lets Pay Salaries pay a budget recipient by code instead of a bank account; `geo_payroll` gives its State Treasury contact 101001000 on a fresh install. Payroll flow: [`geo_payroll.md`](geo_payroll.md).

### Taxes

| Family | Taxes | Posts to | VAT Report |
|---|---|---|---|
| Out of Scope (Sale / Purchase) | 2, 0% | — | none |
| VAT Exempt (Purchase) ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L28)) | 1, 0% | — | none; the tax for non-VAT vendors |
| VAT 18% Non-Deductible (Purchase) ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L14)) | 1 | into the cost (no account on the tax line) | none |
| 18% Fixed Assets ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L18)) | 1 | 334011 | line III.1 (tags 24(B), 24(T)), like Odoo's 18%; VAT Registered position only |
| Reverse Charge 18% Non-Deductible, III-19 ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L22)) | 1 | +18% into the cost, −18% on 333060 | line II.1 (tags 21(B), 21(T)); for buyers not registered for VAT: due, not deducted |
| Small Business 1% / 3% Turnover ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L6)) | 2, price-included | 339090 | none |
| CIT 15% - Distributed Profit ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L196)) | 1, journal entries, `division` 15% | +100% 910010, −100% 331110 | none |
| Withholding, non-resident ([first row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L32)) | 11: dividends / interest / royalties 5%, management fees 10%, property rent 20%, offshore royalties / interest / services 15%, other GE income 10%, telecom / transport 10%, oil and gas 4% | 331212 | none |
| Withholding, resident individuals ([first row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L84)) | 10: dividends / interest / residential rent 5%, services 5% regime, royalties / unregistered services / commercial rent 20%, stipend 20%, gift over GEL 1,000 20%, goods without waybill 3% | 331210 | none |
| Withholding, salary ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax-ge.csv#L132)) | 2: salary (PIT) 20%, non-resident employment 20% | 331310 | none |

The 6 tax groups are Out of Scope, WHT Non-residents, WHT Residents, Turnover 1%, Turnover 3% and CIT ([account.tax.group-ge.csv](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.tax.group-ge.csv#L2)). Withholding, turnover and CIT tax lines set `use_in_tax_closing` False; core computes it True for other tax lines on balance-sheet accounts ([account_tax.py:5178](../addons/account/models/account_tax.py#L5178)).

### Corrections to `l10n_ge`'s VAT taxes

Since 2026-10-22 (VAT declaration plan, Phase 0) the module corrects three defects of `l10n_ge`'s tax data, so the VAT Report, and the declaration built on it, start from right lines:

| Fix | Core as shipped | With `gec_localization` |
|---|---|---|
| A, B: nine **Replaces** links removed ([list](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L4)) | sale `18%` to a Tax-ID customer becomes six taxes (a 100 invoice totals 154); purchase `18%` from abroad becomes three reverse-charge taxes | `18%` stays `18%`; a foreign bill gets no VAT tax unless the vendor's Default Purchase Tax is `18% Reverse Charge Services` (decision 2026-10-22: no automatic reverse charge). `0% Export` still replaces `18%` for export |
| C: the ten sale taxes that list the VAT Registered position also list non-VAT Registered and Domestic individual ([list](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L17)) | a Georgian buyer without Tax ID gets no VAT | 18% kept. A tax that lists no position is left alone (empty = all positions) |
| D: `18% / 12% / 5% Import` price-included ([list](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L29)) | an import VAT bill of 180 totals 360 | base 0, tax 180, total 180, on vendor bills only (see the gotcha) |

**How it reaches a company:**
- A company that loads the `ge` chart while the module is installed gets corrected data: our override of core's root template method [`_get_account_tax`](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L58) edits `l10n_ge`'s rows before they are created. Core runs the most-derived body of that decorated method on every chart load ([chart_template.py:83](../addons/account/models/chart_template.py#L83), [:235](../addons/account/models/chart_template.py#L235)) and skips it in module-filtered loads ([:839](../addons/account/models/chart_template.py#L839)). A one-step install of `gec_localization` on a new Georgian database belongs here: core defers the chart load until every module is loaded ([ir_module.py:117](../addons/account/models/ir_module.py#L117)).
- A company whose chart was loaded before the module was installed is corrected once by the [`post_init`](../custom_addons/gec_odoo_modules/gec_localization/__init__.py#L5) hook ([_ge_fix_core_vat_taxes](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L87)). It unlinks only the wrong source tax, adds positions only where VAT Registered is listed, fills Included in Price only when empty, and includes archived records.
- The same method runs after every `ge` chart load, so a chart **reload** of an uncorrected company completes the repair. Core's reload alone would link the new positions but keep the **Replaces** links ([chart_template.py:402](../addons/account/models/chart_template.py#L402)), stacking six taxes on non-registered buyers too.
- An upgrade never repairs an existing company. gec20_prod1 was repaired by hand on 2026-10-22.

Proof: [test_ge_vat_mapping.py](../custom_addons/gec_odoo_modules/gec_localization/tests/test_ge_vat_mapping.py#L57) has 6 tests: Tax-ID sale, no-Tax-ID and pinned-individual sales, foreign bill with and without `18% Reverse Charge Services`, import bill, install repair, chart reload. All pass, and each fails on the code without its fix (scratch DB, 2026-10-22). The install path was checked on a database where `l10n_ge` was installed first: 10 links before, only `0% Export` after.

---

## How a Posted Invoice or Bill Feeds the VAT Report

1. The line's taxes are proposed (product, contact default, fiscal position) and can be edited until posting.
2. At posting, each journal item copies its repartition line's tags into `tax_tag_ids`: the base tag on the income or expense line, the tax tag on the VAT line. A tax line without an account posts into the base line's account ([account_tax.py:2457](../addons/account/models/account_tax.py#L2457)); that is how "non-deductible" works.
3. Tags are stored on the journal items. Changing a tax later changes future postings only ([`taxes.md`](taxes.md), Tax Distribution & Tax Grids).
4. The report sums the balances per tag ([_report_engine_tax_tags](../enterprise/account_reports/models/account_report.py#L4401)). A leading `-` in the formula flips the sign ([account_report.py:4460](../enterprise/account_reports/models/account_report.py#L4460)): output lines use `-1(B)` so credits show positive; input lines use `24(B)`.
5. Tags are single records named without sign, created by the report expressions ([_create_tax_tags](../addons/account/models/account_report.py#L805), [account_account_tag.py:87](../addons/account/models/account_account_tag.py#L87)).

Example: a 100 GEL sale with `18%`, and a 100 GEL services bill from a non-resident with `18% Reverse Charge Services`.

| Journal item | Balance | Tags | Declaration |
|---|---:|---|---|
| Receivable 140110 | +118 | — | |
| Income 611101 | −100 | 1(B) | I.1 base 100 |
| 333002 VAT Output | −18 | 1(T) | I.1 tax 18 |
| Expense | +100 | 21(B), 27(B) | II.1 base 100, III.4 base 100 |
| 334040 Input RC VAT | +18 | 27(T) | III.4 tax 18 |
| 333060 RC VAT Payable | −18 | 21(T) | II.1 tax 18 |
| Payable 310110 | −100 | — | |

A full credit note posts the opposite balances on the same tags, so the lines return to 0. Reverse charge nets to 0 in the ledger but fills both parts of the declaration.

### The VAT period

- **No Georgian return type in 20.0.** Return types come from enterprise `l10n_xx_reports` modules and there is no Georgian one. For every country `account_reports` generates only "Annual Closing: Corporate Tax" ([account_return_data.xml:5](../enterprise/account_reports/data/account_return_data.xml#L5)). So there is no monthly VAT card, no deadline, no automatic closing entry and no lock on validation.
- Tax groups carry no settlement accounts in 20.0; those moved to `account.return.type` ([`account_returns.md`](account_returns.md)). Moving the month's VAT to 333010 / 140610 is a manual entry, if the accountant wants one.
- Lock the period yourself with the tax lock date after filing ([`account_returns.md`](account_returns.md), Which lock date does what).
- [Likely] An account manager can create a Georgian VAT return type by hand: Accounting > Configuration > Accounting > Return Types, report **VAT Report**, monthly, with settlement accounts. Managers have full rights on return types and the views allow creation; nobody has tried it on a database yet.
- Deadlines: withholding is declared by the 15th of the following month ([`mof_order_996_2010.md`](../dev_notes/reference/mof_order_996_2010.md)); VAT and CIT on distributions are also monthly [Unverified in our docs].

---

## Withholding at Payment

Our WHT taxes run on core `l10n_account_withholding_tax`. The flag is `is_withholding_tax` ([account_tax.py:13](../addons/l10n_account_withholding_tax/models/account_tax.py#L13)); `amount` is negative and the type must be percent ([_check_amount_type](../addons/l10n_account_withholding_tax/models/account_tax.py#L46)).

1. **Bill.** Put the WHT tax on the bill line (or among the product's purchase taxes). It does not change the bill total: withholding taxes are skipped in normal tax computation ([_add_tax_details_in_base_line](../addons/l10n_account_withholding_tax/models/account_tax.py#L74)). The bill shows **Withhold Due** and **Net Due** under Amount Due ([account_move_views.xml:19](../addons/l10n_account_withholding_tax/views/account_move_views.xml#L19)).
2. **Pay.** The dialog defaults to **Withhold and Pay** when the bill still has withholding due ([_get_default_withhold](../addons/l10n_account_withholding_tax/wizards/account_payment_register.py#L72)). **Withhold Only** posts the withholding alone on a Miscellaneous journal; **Payment Only** pays without withholding ([account_payment.py:13](../addons/l10n_account_withholding_tax/models/account_payment.py#L13)).
3. **Withholdings tab.** Lines are built from the bills' base lines ([_compute_withholding_line_ids](../addons/l10n_account_withholding_tax/wizards/account_payment_register.py#L158)); tax, base and amount stay editable.
4. **Post.** The certificate number is drawn from the tax's sequence ([account_withholding_line.py:369](../addons/l10n_account_withholding_tax/models/account_withholding_line.py#L369)). Ours is one sequence per company, `WHT/<year>/00001`, created from the template [seq_ge_wht](../custom_addons/gec_odoo_modules/gec_localization/data/wht_sequence.xml#L11) by [_ge_wht_company_sequence](../custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py#L72).

The payment entry for the 1,000 GEL management-fee bill with 10%: Payable +1,000, Bank −900, 331212 −100, plus a "WH Base" / "WH Base Counterpart" pair of ±1,000 ([_prepare_withholding_amls_create_values](../addons/l10n_account_withholding_tax/models/account_withholding_line.py#L348)). The pair posts on the **Withholding Tax Base** account from Settings, or on the bill line's account when that setting is empty ([account_withholding_line.py:482](../addons/l10n_account_withholding_tax/models/account_withholding_line.py#L482)). Our WHT taxes carry no tags, so nothing reaches the VAT Report.

**Paying the State Treasury is a separate, manual step.** No withholding payment sends the tax: **Withhold Only** has no bank line, and **Withhold and Pay** sends only the net to the vendor. The tax stays as a credit on 331212 / 331210 until it is paid by treasury transfer to code 101001000, by the 15th of the next month ([`rs_form30_full_declaration_gap_plan.md`](../dev_notes/plans/rs_form30_full_declaration_gap_plan.md), deadline row). None of our modules clears these accounts, and neither account allows reconciliation. Two ways to settle a month:

| Way | Send | Book |
|---|---|---|
| Recommended | The transfer from Basis Internet Banking | When the bank line arrives, open it in bank reconciliation, **Set Account**, choose 331212 / 331210 ([set_account_bank_statement_line](../enterprise/account_accountant/models/account_bank_statement.py#L1308)) |
| From Odoo | A payment to **სახელმწიფო ხაზინა** on a Basis journal, **Basis Bank Transfer Type** = Treasury, **Treasury Code** 101001000, then **Send to Basis Bank** ([account_payment.py:277](../custom_addons/gec_odoo_modules/basis_bank/models/account_payment.py#L277), [account_payment_views.xml:55](../custom_addons/gec_odoo_modules/basis_bank/views/account_payment_views.xml#L55)) | A payment can only post to a Payable or Receivable account ([account_payment.py:169](../addons/account/models/account_payment.py#L169), [:247](../addons/account/models/account_payment.py#L247)), so it lands on the Treasury's Payable. Add a journal entry Dr 331212 / Cr Payable (State Treasury) and reconcile the two Payable lines |

After two or more bank lines get the same account, Odoo creates a reconciliation rule from their common label text ([_check_and_create_reconciliation_rule](../enterprise/account_accountant/models/account_bank_statement.py#L1431)). All Georgian taxes go to the same treasury code, so check the proposed account on every treasury line.

**Overpaid withholding after a credit note** (accountant, 2026-11-10). A vendor credit note posted after the tax was paid leaves an open debit on 331210 / 331212: the Treasury holds an overpayment. Correct that month's Form 30 (its exported row is blocked as "Filed, but its payment or source changed"); the next Treasury payment from a bill on the same account deducts the open debit, whatever the vendor or tax ([`_gec_net_withholding_lines`](../custom_addons/gec_odoo_modules/gec_localization/models/account_move_line.py#L71)).

The Form 30 declaration reads these payments ([`gec_income_tax_report.md`](gec_income_tax_report.md)). That module sets **Form 30 Income Type** on 18 of our 23 WHT taxes ([account_tax.py:29](../custom_addons/gec_odoo_modules/gec_income_tax_report/models/account_tax.py#L29)). Five have none: gift 20%, goods without waybill 3%, non-resident other income 10%, telecom / transport 10%, oil and gas 4%.

---

## Default Taxes per Contact and "Not Taxed" Products

Odoo's own per-contact lever is the fiscal position, which can only replace or remove a tax the product already proposes ([`taxes.md`](taxes.md), FAQ: is there a default tax per partner?). The contact default is simpler to set and can also add a tax where the product has none.

**What the user sees.** **Default Sales Tax** and **Default Purchase Tax** on the contact, Sales & Purchase tab after Fiscal Position ([res_partner_views.xml:87](../custom_addons/gec_odoo_modules/gec_localization/views/res_partner_views.xml#L87)). A **Not Taxed** checkbox on the product hides both tax fields ([product_views.xml:4](../custom_addons/gec_odoo_modules/gec_localization/views/product_views.xml#L4)).

**The rule** ([_ge_partner_product_taxes](../custom_addons/gec_odoo_modules/gec_localization/models/account_tax.py#L48)), per line:
1. Product Not Taxed → no tax proposed; one can still be added by hand.
2. The commercial contact has a default tax for this direction (in the document's company) → it replaces the proposed taxes, the fiscal position still remaps it, and the product's withholding taxes stay.
3. Otherwise core behavior (product, account fallback on invoices, fiscal position).

Exception (user, 2026-10-21): when the contact is a **VAT Payer** (`gec_vat_payer`, shown in section rs.ge Form 30 by `gec_income_tax_report` for companies (Tax ID, no parent), Individual Entrepreneurs and Small Business Status contacts), a withholding tax or "no withholding" label as Default Purchase Tax is added to the product's taxes instead of replacing them ([account_tax.py](../custom_addons/gec_odoo_modules/gec_localization/models/account_tax.py#L48)). The product's `18%` has already passed the fiscal position, so the contact needs a Tax ID: without one, "Georgia (non-VAT Registered)" removes the `18%` first.

| Product taxes | Contact default | Contact position | Line gets |
|---|---|---|---|
| `18%` sale | — | — | `18%` (core) |
| `18%` sale | `0% Export` | — | `0% Export` |
| `18%` sale | `18%` | Non-Georgia | `0% Export`: the position still remaps |
| none | `18%` sale | — | `18%` (core would give nothing on orders) |
| `18%` + WHT 20% purchase | VAT Exempt (Purchase) | — | VAT Exempt (Purchase) + WHT 20% |
| `18%` purchase | PIT 1% - Small Business IE (label) | VAT Registered (Tax ID), **VAT Payer** ticked | `18%` + label |
| `18%` purchase | PIT 1% - Small Business IE (label) | VAT Payer not ticked | label only |
| anything, product Not Taxed | anything | anything | nothing |

**Where it runs.** After `super()` in the three methods that propose line taxes: invoice and bill lines ([_get_computed_taxes](../custom_addons/gec_odoo_modules/gec_localization/models/account_move_line.py#L11), product lines of sale and purchase documents only), sales order lines ([_compute_tax_ids](../custom_addons/gec_odoo_modules/gec_localization/models/sale_order_line.py#L8), not combo lines) and purchase order lines ([_compute_tax_id](../custom_addons/gec_odoo_modules/gec_localization/models/purchase_order_line.py#L7)). Journal entries are never touched, so deferral moves ([account_move.py:878](../enterprise/account_accountant/models/account_move.py#L878)) and asset moves ([account_move.py:449](../enterprise/account_asset/models/account_move.py#L449)) keep their own taxes. Invoices from orders copy the order line taxes ([sale_order_line.py:2067](../addons/sale/models/sale_order_line.py#L2067), [purchase_order_line.py:787](../addons/purchase/models/purchase_order_line.py#L787)). Inter-company invoices also go through the rule ([account_move.py:57](../enterprise/account_inter_company_rules/models/account_move.py#L57)). The module depends on `sale` and `purchase` for these hooks. Nothing else changes: posted documents, the tax engine, payments, reports, and the company default taxes on new products.

**Changing the contact in the form of a draft document recomputes line taxes.** Core recomputes only when the fiscal position changes: automatically on sales orders ([sale_order.py:1351](../addons/sale/models/sale_order.py#L1351)), through the Update Taxes button on invoices ([account_move.py:2809](../addons/account/models/account_move.py#L2809)). Ours: a partner onchange on invoices, bills and receipts ([account_move.py:29](../custom_addons/gec_odoo_modules/gec_localization/models/account_move.py#L29)) and purchase orders ([purchase_order.py:8](../custom_addons/gec_odoo_modules/gec_localization/models/purchase_order.py#L8)), and `order_id.partner_id` in the sales order line dependencies (so an eCommerce cart picks up the customer's default after login). This overwrites manual tax edits on those lines, as a fiscal position change does. A contact written outside the form (posted entry, bank statement sync, import, RPC, list multi-edit) never re-proposes taxes on invoices and entries (decision 2026-11-10: before, a posted bill or a statement entry lost its taxes on a contact change).

**Decisions (user, 2026-09-09):**

| # | Decision | Consequence |
|---|---|---|
| D1 | The fiscal position still remaps the contact tax | export and reverse-charge positions keep working; with the [VAT corrections](#corrections-to-l10n_ges-vat-taxes) a default `18%` on a Tax-ID customer stays `18%` |
| D2 | Commercial fields ([res_partner.py:44](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py#L44)) | copied to a new child contact and pushed to children when the parent changes, in every company ([res_partner.py:806](../odoo/addons/base/models/res_partner.py#L806), [:901](../odoo/addons/base/models/res_partner.py#L901)); a child cannot keep its own value |
| D3 | Product withholding taxes stay | "VAT Exempt" as vendor default does not drop the withholding (open: Q6 below) |
| D4 | Not Taxed is literal | nothing is proposed, withholding included |
| D5 | Company-dependent, `check_company` | a shared contact carries a different tax per company |
| D8 | Non-VAT vendor = `VAT Exempt (Purchase)` | an empty field means "no rule"; a 0% tax without tags removes VAT without touching the report |

**Compliance notes.**
- **No tax is not "exempt".** A line without tax never reaches the VAT Report. Exempt and zero-rated sales need their 0% exempt / `0% Export` taxes so the base reaches lines I.9–I.14.3. Use Not Taxed only for things that are not a supply (deposits, penalties, pass-through costs).
- **Rule of thumb:** the fiscal position states the *regime* (export, reverse charge, non-resident); the contact tax states the counterparty's *VAT status*. Set both on one contact only when the layered result is intended.
- The purchase field accepts withholding taxes (the sales field excludes them, [res_partner.py:17](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py#L17)). A WHT tax picked as Default Purchase Tax replaces the product's VAT, unless the contact is a VAT Payer.

**Not covered:**

| Where | Why |
|---|---|
| Expenses (`hr_expense`) | taxes come from the product's purchase taxes only ([hr_expense.py:702](../addons/hr_expense/models/hr_expense.py#L702)) |
| rs.ge waybill → invoice wizard | lines without a sale order take the product's taxes without the contact default ([rs_invoice_from_waybill_wizard.py:89](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L89)); the fiscal position is applied after create ([:509](../custom_addons/gec_odoo_modules/rs_base_methods/wizards/rs_invoice_from_waybill_wizard.py#L509)) |
| Purchase orders created by replenishment or requisitions | [`_prepare_purchase_order_line`](../addons/purchase/models/purchase_order_line.py#L810) writes `tax_ids` directly |
| Point of Sale, eCommerce | taxes computed in the browser from product and position |
| Drafts existing at install | no trigger fires; use **Update Taxes and Accounts** on invoices ([action_update_fpos_values](../addons/account/models/account_move.py#L6611)) or edit the lines |
| Loyalty reward lines (`sale_loyalty`) | its override keeps reward lines out of `super()` ([sale_order_line.py:33](../addons/sale_loyalty/models/sale_order_line.py#L33)); whether our rule then rewrites them depends on module load order [Guessing]; check discount lines if both are installed |

---

## Profit Distribution (CIT) Wizard

Menu: Accounting > Accounting > **Profit Distribution (CIT)**, account managers only ([cit_wizard_views.xml:49](../custom_addons/gec_odoo_modules/gec_localization/views/cit_wizard_views.xml#L49)). It posts one entry immediately in a Miscellaneous journal ([action_post_cit](../custom_addons/gec_odoo_modules/gec_localization/wizards/cit_wizard.py#L59)):

```
Gross = Net / 0.85        CIT 15% = Gross - Net
Dividend WHT = Net x rate (only if ticked, default 5%)        Shareholder = Net - Dividend WHT
```

| Account (chosen in the wizard) | Debit | Credit |
|---|---:|---:|
| 530110 Retained Earnings (distribution) | 1,000.00 | |
| 331110 Corporate Income Taxes | | 150.00 |
| 331210 WHT Accrued (resident individual; 331212 for a non-resident) | | 42.50 |
| 340120 Accrued Dividends Payable (shareholder) | | 807.50 |

Leave withholding off for a resident company shareholder. The **CIT 15%** tax is a separate tool for journal entries: on an 85 line it books 15 to 910010 expense against 331110, and the entry total does not change. The wizard does not use it.

---

## Bank Name and BIC from Georgian IBANs

`res.bank` does not exist in 20.0; use `bank_name` / `bank_bic` on `res.partner.bank`. [`GE_BANKS`](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner_bank.py#L4) maps the IBAN bank code (characters 5–6) of 19 Georgian banks to name and BIC. On create and write, [`_sanitize_vals`](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner_bank.py#L30) fills them when the account number is written and the same save carries no value for them; a typed value wins. `basis_bank`, `bog_bank` and `tbc_bank` find their journal by the 8-character BIC prefix; `bog_bank` and `tbc_bank` do not depend on this module, so without it the BIC must be typed. A new Georgian bank is one line in `GE_BANKS`.

## Contact Categories

`gec.contact.category` ([contact_category.py:4](../custom_addons/gec_odoo_modules/gec_localization/models/contact_category.py#L4)) is a user-managed classification, separate from core Tags: menu Contacts > Contact Categories, editable by any internal user. Child contacts inherit the parent's categories and show them read-only ([res_partner.py:7](../custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py#L7)). Contact lists and kanban get a category search panel. Categories have no company: all companies share them.

---

## Configuration & Settings

What the accountant configures, in order:

1. **Chart.** Company country Georgia, then Fiscal Localization **Georgian Chart of Accounts (IFRS)**.
2. **331310.** If the company had the `ge` chart before `gec_localization` was installed, untick **Allow Reconciliation** on 331310.
3. **Bank suspense.** Core sets it to 120210 Cash in Bank Foreign Currency, a bank-type account, although the **Bank Suspense** setting itself offers only current assets and liabilities ([res_config_settings.py:66](../addons/account/models/res_config_settings.py#L66)). Set it to 120001 Bank Suspense (Settings > Accounting > Default Accounts) so unreconciled statement lines stay apart from a real bank balance.
4. **Foreign vendors.** Default Purchase Tax `18% Reverse Charge Services` on vendors of services from abroad. Other Non-Georgia bills get no VAT tax: before filing, review the month's foreign bills without one. Book customs VAT as a vendor bill with `18% Import`, not as a journal entry.
5. **Contacts.** Vendors with a Tax ID that are not VAT payers: Default Purchase Tax = VAT Exempt (Purchase). Customers with a fixed regime: Default Sales Tax, or a pinned fiscal position.
6. **Products.** Not Taxed only for non-supplies; WHT taxes on the purchase taxes of services bought from non-residents or individuals.
7. **Withholding Tax Base** (Settings > Accounting > Default Accounts, [res_company.py:12](../addons/l10n_account_withholding_tax/models/res_company.py#L12)): optional; set it so the WH Base pair does not land on expense accounts.
8. **Form 30 Income Type** on the five WHT taxes that have none.
9. **Tax Category Code** (core field of `account_edi_ubl_cii`, on the tax form) on every VAT tax: `gec_localization` sets it on its own and `l10n_ge`'s taxes (S 18%, Z/G zero-rated and export, E/O exempt and out of scope; none on withholding, import and reverse charge). rs_einvoice and rs_waybill read it for the rs.ge VAT class; a VAT tax you create yourself needs it set by hand.
10. **Treasury Code** 101001000 on the State Treasury contact in databases created before `geo_payroll` set it.
11. **Tax lock date** every month after filing.

---

## Dependencies

| Requires | Why |
|---|---|
| `l10n_ge` | the chart `ge`, VAT taxes, fiscal positions, VAT Report |
| `l10n_account_withholding_tax` | payment-time withholding (`is_withholding_tax`, `withholding_sequence_id`) |
| `sale`, `purchase` | the tax-proposal hooks for contact defaults |
| `contacts` | the Contact Categories menu |

| Works With (optional) | What It Adds |
|---|---|
| `accountant` / `account_reports` (Enterprise) | the Tax Report screen that renders the VAT Report; the report record itself is community data |
| `geo_payroll`, `gec_payroll_bank`, `basis_bank` | payroll postings on the accounts above, Pay Salaries, treasury transfers |
| `gec_income_tax_report` | Form 30 from withholding payments |
| `rs_einvoice`, `rs_waybill` | rs.ge documents; the rs.ge VAT class of a line comes from its taxes' Tax Category Code |

---

## Gotchas & Non-Obvious Behavior

- **[Certain] The VAT corrections reach an existing company only at install or at a chart reload.** A company that had the `ge` chart before `gec_localization` was installed is corrected by the install hook, or later by a reload of the `ge` chart; `-u` never repairs one.
- **[Certain] Foreign bills get no VAT tax by default.** Non-Georgia removes purchase `18%` ([map_tax](../addons/account/models/partner.py#L161)); the vendor's Default Purchase Tax `18% Reverse Charge Services` gives one reverse-charge tax. Goods bought abroad carry no VAT on the vendor's invoice; customs VAT comes on its own bill.
- **[Certain] Automatic NBG exchange rates are one day late.** Odoo 20 values a document at the latest rate dated strictly before it, and the NBG provider stores each rate under the day it becomes valid, so every foreign-currency document uses the previous day's official rate. Details: [`currency_exchange_transit.md`](currency_exchange_transit.md).
- **[Certain] "VAT Registered" means "has a Tax ID"**, and a contact without country gets no position at all (taxes stay as proposed).
- **[Certain] Import VAT is right only on vendor bills.** `18% / 12% / 5% Import` are `division` 100% taxes; `gec_localization` makes them price-included, so a 180 bill line is all VAT (base 0, total 180). Journal entries compute every tax as excluded ([account_move.py:1681](../addons/account/models/account_move.py#L1681), [account_tax.py:898](../addons/account/models/account_tax.py#L898)): on a manual entry a 180 line still gets 180 of tax on top.
- **[Certain] Declaration line III.3 is fed by no tax** (tag 26), and III.4.1 is typed by hand.
- **[Certain] "Not Subject to VAT" is not offered for Georgia.** The company switch exists only for EU countries and Switzerland ([company.py:491](../addons/account/models/company.py#L491)).
- **[Certain] Two "Current Year Earnings" accounts.** 530110 Retained Earnings and 530510 Profit / Loss for the Reporting Period have that type ([rows](../addons/l10n_ge/data/template/account.account-ge.csv#L173)). Such accounts carry no opening balance in ledgers ([account_account.py:681](../addons/account/models/account_account.py#L681)), and core uses the first by code, 530110, as its unaffected-earnings account ([get_unaffected_earnings_account](../addons/account/models/company.py#L976)). The CIT wizard debits 530110 by default.
- **[Certain] 331211 WHT Settled is typed Expense in core** ([row](../addons/l10n_ge/data/template/account.account-ge.csv#L124)), so it would show in the P&L. `gec_localization` makes it a non-trade Payable ([row](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.account-ge.csv#L15)). None of our taxes use it.
- **[Certain] Paying several bills without "Group Payments" hides withholding**: the section appears only when the dialog makes one payment ([account_payment_register.py:151](../addons/l10n_account_withholding_tax/wizards/account_payment_register.py#L151)).
- **[Likely] Bill prediction can replace line taxes.** With `account_accountant`, typing a label on a draft vendor bill line can load the taxes of the vendor's earlier bills ([_onchange_name_predictive](../enterprise/account_accountant/models/account_move.py#L1053)) over the contact default.
- **[Certain] Bank name and BIC appear after saving**, not while typing: the fill runs in create/write. Changing an IBAN to another Georgian bank replaces both unless typed in the same save.
- **[Certain] Our taxes are never remapped, except "18% Fixed Assets".** The others list no fiscal position, so every position passes them through; choose them by product, contact default or by hand. "18% Fixed Assets" (2026-11-04) lists "Georgia (VAT Registered)" like core's 18 %, so a foreign or non-VAT vendor's position removes it.
- **[Certain] "18% Fixed Assets" vs "18% Cessation of Activity".** The first (ours, `ge_tax_p_vat_18_fixed_assets`) is a normal fixed-asset purchase: tags 24(B)/24(T) (VAT Report row III.1), VAT on 334011. The second is core's `ge_vat_purchase_18_fixed_assets` (core name "18% FA", renamed 2026-10-23): fixed assets kept after the business stops, tag 29 (row III.5). Bills pulled from rs.ge always get the company default 18 % (334010): switch asset lines by hand.
- **[Likely] Choosing the chart installs only `l10n_ge`.** Neither module sets `auto_install`, so a Georgian company does not get them by country alone; install `gec_localization` before or after the chart (both orders load our records).
- **[Certain] Payroll does not feed the VAT Report.** Salary rules can stamp tags (`debit_tag_ids` / `credit_tag_ids`, [hr_salary_rule.py:20](../enterprise/hr_payroll_account/models/hr_salary_rule.py#L20)), but no Georgian salary tags exist and the VAT tags do not belong there.

### Open decisions

| Item | Status |
|---|---|
| Q6: may a contact default purchase tax drop the product's withholding? | decided 2026-10-17: one contact default (VAT, withholding tax or 0% label) replaces the product's taxes; products cannot hold withholding taxes |
| A hand-made VAT return type (cards, closing entry, lock) | open; not tried |
| [Likely] CIT in equity vs P&L: the wizard charges CIT to 530110, the CIT tax to 910010 expense; IAS 12.57A generally puts tax on distributed profit in profit or loss | accountant to confirm |
| Form 30 income type for five WHT taxes | accountant to set |

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`taxes.md`](taxes.md) — tax engine, repartition, tags, fiscal positions, tax precedence on lines
- [`account_returns.md`](account_returns.md) — return types, closing entry, lock dates
- [`accounting_coa.md`](accounting_coa.md) — account types and the header-account hierarchy
- [`mof_order_996_2010.md`](../dev_notes/reference/mof_order_996_2010.md) — Georgian tax administration rules and deadlines
- [`gec_income_tax_report.md`](gec_income_tax_report.md) — Form 30 from withholding payments
- [`l10n_ge_vat_report.md`](l10n_ge_vat_report.md) — accountant's guide to the VAT Report (Georgian): entries per case, line table, wrong default taxes, monthly checks
- [`vat_declaration_annex_a_plan.md`](../dev_notes/plans/vat_declaration_annex_a_plan.md) — plan for an Annex A export
- [`geo_payroll.md`](geo_payroll.md) — payroll postings, PIT and pension accounts
- [`basis_bank.md`](basis_bank.md) — bank journals found by BIC, treasury transfers
