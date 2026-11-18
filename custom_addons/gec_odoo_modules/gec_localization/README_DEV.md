# Georgia - Accounting Extensions (`gec_localization`) — Developer guide

For developers changing the module. How it is used: [README.md](README.md). Core `l10n_ge`
behavior, the three shipped mapping defects and the design decisions:
[documentations/l10n_ge.md](../../../documentations/l10n_ge.md).

---

## 1. Purpose and facts

The module has no chart of its own. It extends `l10n_ge`'s template `ge` with template
functions and CSV rows, and adds a tax-proposal rule on order and invoice lines, a CIT wizard,
an IBAN → bank name / BIC fill and a contact category model.

| Item | Value |
|---|---|
| Depends | `l10n_ge` (template `ge`; the accounts, tax groups and report tags our rows reference) · `contacts` (menu parent) · `l10n_account_withholding_tax` (`is_withholding_tax`, `withholding_sequence_id`) · `sale`, `purchase` (the order-line tax hooks) |
| New models | `gec.contact.category` · `l10n.ge.cit.wizard` (transient) |
| Extended models | `account.chart.template`, `account.tax`, `account.move.line`, `sale.order.line`, `purchase.order`, `purchase.order.line`, `product.template`, `res.partner`, `res.partner.bank` |
| Hooks | `post_init_hook` `post_init` (install only) calls `_ge_fix_core_vat_taxes`; `data/ge_tax_maintenance.xml` calls `_ge_gec_apply_maintenance` and `data/res_partner_data.xml` calls `_gec_recompute_georgian_company_flag` on every install and upgrade |
| Crons, controllers | none |
| Category | `Accounting/Localizations`, not `Accounting/Localizations/Account Charts`: the module defines no chart, so `account` has no reason to read it when it builds the chart selection |

Data files, in manifest order:

1. `data/wht_sequence.xml`: shared certificate sequence `seq_ge_wht` (`noupdate`), the template for the per-company copies.
2. `views/res_partner_views.xml`: Contact Categories list, form, search, action and menu; partner form, search and accounting-tab extensions.
3. `views/product_views.xml`: Not Taxed on the product form.
4. `views/cit_wizard_views.xml`: wizard form, action and menu.
5. `data/ge_tax_maintenance.xml`: `<function>` calling `_ge_gec_apply_maintenance`.
6. `data/res_partner_data.xml`: `<function>` calling `_gec_recompute_georgian_company_flag`.
7. `security/ir.access.csv`: last, as Odoo 20 requires.

The three CSVs in `data/template/` are not in `data`: the chart loader reads them through the
`@template` functions.

---

## 2. Architecture

```text
l10n_ge template 'ge'            our @template('ge') functions
accounts, VAT taxes, tags        14 accounts, 4 overrides, 64 taxes
            │                                  │
            └────────────────┬─────────────────┘
                             ▼
                chart data, merged per xmlid
                             │
                             ▼
                company accounts and taxes ◄─── maintenance: missing rows,
                             │                  one WHT sequence per company
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
   line tax proposal     CIT wizard       WHT at payment
   partner default,      one posted       certificate number
   Not Taxed             entry            from the sequence
```

Names: chart data = `account.chart.template._get_chart_template_data('ge')`; company records =
`account.account`, `account.tax.group`, `account.tax` with xmlids `account.<company_id>_<xmlid>`;
maintenance = `_ge_gec_apply_maintenance`; line tax proposal =
`account.tax._ge_partner_product_taxes`; WHT at payment = core `l10n_account_withholding_tax`.

Chart data flows one way, into company records, and only the maintenance adds to it later.
The tax rule, the wizard and the IBAN fill are independent of each other and of the chart
code.

---

## 3. File map

| File | Holds |
|---|---|
| `__manifest__.py` | Dependencies, data order, plain-text description |
| `__init__.py` | Imports `models` and `wizards` |
| `README.md` | User guide |
| `README_DEV.md` | This guide |
| `data/wht_sequence.xml` | `seq_ge_wht`, the shared certificate sequence (`WHT/%(year)s/`, 5 digits) |
| `data/ge_tax_maintenance.xml` | `<function>` → `_ge_gec_apply_maintenance` |
| `data/res_partner_data.xml` | `<function>` → `_gec_recompute_georgian_company_flag` |
| `data/template/account.account-ge.csv` | 14 new accounts and 4 column overrides of `l10n_ge` accounts |
| `data/template/account.tax.group-ge.csv` | 6 tax groups: out of scope, WHT non-residents, WHT residents, turnover 1%, turnover 3%, CIT |
| `data/template/account.tax-ge.csv` | 64 taxes with their repartition lines |
| `models/__init__.py` | Imports the model files |
| `models/template_ge.py` | Template functions, `_get_account_tax` override and `_ge_fix_core_vat_taxes` (VAT corrections), `_post_load_data` override, maintenance, per-company WHT sequence |
| `tests/test_ge_vat_mapping.py` | VAT corrections, 6 post_install tests |
| `models/account_tax.py` | `_ge_partner_product_taxes`, the tax-proposal rule |
| `models/account_move_line.py` | Rule on invoice and bill lines |
| `models/sale_order_line.py` | Rule on sales order lines; partner dependency on `_compute_tax_ids` |
| `models/purchase_order_line.py` | Rule on purchase order lines |
| `models/purchase_order.py` | Partner onchange that recomputes purchase line taxes |
| `models/account_move.py` | Partner onchange that recomputes invoice, bill and receipt line taxes; the Pay Withholding Tax flow |
| `models/product_template.py` | `not_taxed` |
| `models/res_partner.py` | `gec_contact_category_ids`, `property_sale_tax_id`, `property_purchase_tax_id`, `gec_treasury_code`, commercial-field sync, the Georgian person rule on `_compute_is_company` and its upgrade fix |
| `models/res_partner_bank.py` | `GE_BANKS` and the `_sanitize_vals` fill |
| `models/contact_category.py` | `gec.contact.category` |
| `wizards/__init__.py` | Imports `cit_wizard` |
| `wizards/cit_wizard.py` | `l10n.ge.cit.wizard` and `action_post_cit` |
| `views/res_partner_views.xml` | Category views, action, menu; partner form, search panel, default taxes, Treasury Code |
| `views/product_views.xml` | Not Taxed, hiding Sales Taxes and Purchase Taxes when ticked |
| `views/cit_wizard_views.xml` | Wizard form, action, menu (managers) |
| `security/ir.access.csv` | Two access rows ([Security](#13-security)) |

---

## 4. How the chart extension works

Precedent in core: `addons/l10n_sa_edi/models/account_chart_template.py`, an extension module
adding data to another localization's template.

```python
@template('ge', 'account.tax')
def _get_ge_gec_account_tax(self):
    tax_data = self._parse_csv('ge', 'account.tax', module='gec_localization')
    self._deref_account_tags('ge', tax_data)
    return tax_data
```

- **Unique method names.** `_template_register` registers template functions by attribute name
  and keeps the top of the MRO. A function named like one of `l10n_ge`'s
  (`_get_ge_res_company`, `_get_ge_account_journal`, `_get_ge_coa_account_account`,
  `_get_ge_template_data`) silently replaces core's. Ours are `_get_ge_gec_*`.
- **Merge per xmlid.** `_get_chart_template_data` runs every registered function and updates one
  dict per xmlid; `l10n_ge`'s CSV comes first. A row keyed by an `l10n_ge` xmlid changes only the
  columns it fills. That is how the payroll settings reach 310310, 332010 and 331310, and how
  331211 WHT Settled (core: Expense) becomes a non-trade Payable:

  ```csv
  "ge_account_310310","","","","liability_payable","","","",""
  "ge_account_332010","","","","liability_payable","True","","",""
  "ge_account_331310","","","","","False","","",""
  "ge_account_331211","","","","liability_payable","True","True","",""
  ```

- **Own xmlid prefixes.** New records use `gec_account_*` and `gec_tax_group_*`; taxes keep
  `ge_tax_*` because `gec_income_tax_report` maps them. Chart xmlids live in module `account`
  per company (`account.<company_id>_<xmlid>`), so a prefix `l10n_ge` does not use prevents a
  merge with a future core record.
- **References to `l10n_ge`** use its xmlids (`ge_tax_group_vat_18`, `ge_tax_group_vat_exempt`,
  `ge_account_333060`, ...), resolved per company at load. `_deref_account_tags` turns `21(B)` and
  `21(T)` into `l10n_ge`'s report tags.

### When our records reach a company

| Situation | What runs | Result on existing accounts |
|---|---|---|
| A company loads the `ge` chart after the install | `try_loading` loads the merged data in `chart_template_load` context, then our `_post_load_data` calls `_ge_gec_apply_maintenance(company)` (nothing missing; sequence only; the one-time text pass `_ge_apply_tax_texts` runs here too, once per database, on all root `ge` companies, not only `company`) | All columns land, 331310 `reconcile=False` included |
| The module is installed while `ge` companies exist | 1. the data `<function>` runs `_ge_gec_apply_maintenance()` and creates every missing record; 2. `ir.module.module.write` (state → installed) reloads this module's functions with `_pre_reload_data(force_update=True)`, `_pre_load_data`, `_load_data` | Columns are rewritten, except `reconcile`, which `_pre_reload_data` drops on existing accounts: 331310 stays reconcilable. 332010 still becomes reconcilable, because `_compute_reconcile` sets it for Payable |
| The module is upgraded | Only the data `<function>` | Only missing xmlids are created (a hand-made account with the same code is linked, a hand-made tax with the same name is renamed `[old] ...`); overrides and edited records are left alone, except the one-time text pass `_ge_apply_tax_texts` (once per database, all root `ge` companies regardless of the companies passed): it renames the taxes and removes the retired ones |

### Corrections to `l10n_ge`'s VAT taxes

`_get_account_tax` overrides core's root template method (decorator repeated as in
`l10n_pt/models/template_pt.py:38`; core registers the most-derived body under the base's
metadata, so it runs on every chart load and is skipped in module-filtered loads). For `ge` it removes the nine wrong **Replaces** links in
`GE_WRONG_REPLACEMENTS`, adds the non-VAT and Domestic positions to the sale taxes in
`GE_DOMESTIC_SALE_TAXES` that list the VAT Registered position, and makes
`GE_IMPORT_VAT_TAXES` price-included. Rows are read with `.get()`: `_parse_csv` returns a
defaultdict, and indexing a missing id would create an empty tax. `_ge_fix_core_vat_taxes` applies
the same fixes to existing records: once from the post_init hook (charts loaded before the
install) and from `_post_load_data` after every `ge` chart load, because a reload links the new
positions but never removes a **Replaces** link. It unlinks only the wrong source, adds positions
only next to VAT Registered, fills Included in Price only when empty and includes archived
records. An upgrade runs none of this. Business view:
[documentations/l10n_ge.md](../../../documentations/l10n_ge.md#corrections-to-l10n_ges-vat-taxes).

Step 1 of the install runs outside `chart_template_load`, where Odoo 20's
`account.account.create` would call `_create_default_journals` and give each new `asset_cash`
account (110120, 120300, 120980) a bank journal. The maintenance therefore loads with
`skip_auto_account_journal_creation=True`, so these accounts get no journal, as on a chart load.

---

## 5. Maintenance: `_ge_gec_apply_maintenance`

Runs from the data `<function>` (every install and upgrade; `@api.model` is required for the
`<function>` tag) and from the `_post_load_data` override (root companies loading `ge`).

1. Companies: the ones passed in, else every root company with `chart_template == 'ge'`.
   Branches share their root's accounts and taxes, so they are skipped. `_ge_apply_tax_texts`
   (step 5) always takes every root `ge` company, whatever was passed in.
2. `_get_chart_template_data('ge', module='gec_localization')`: only this module's rows;
   `template_data` is dropped.
3. Keeps the xmlids `ref()` cannot find in the company and loads only those with
   `_pre_reload_data` + `_pre_load_data` + `_load_data`. Reloading an existing tax would rewrite it; skipping it keeps
   the accountant's edits. `_pre_reload_data` first links a hand-made account with the same code and renames a hand-made
   tax with the same name to `[old] ...`, as a chart reload does, so the load does not fail on a duplicate. Core builds that
   match from the unescaped name (`addons/account/models/chart_template.py:419`): a same-named hand-made tax whose name has
   parentheses is not renamed and the upgrade still stops on "Tax names must be unique"; rename it by hand first.
4. `_ge_wht_company_sequence`: finds or creates the company's `ir.sequence` with code
   `l10n.ge.wht.certificate`, copied from `seq_ge_wht` (name + company, prefix, padding, next
   number). It is written on the company's withholding taxes whose `withholding_sequence_id` is
   empty or still the shared one; a sequence chosen by hand is kept.
5. `_ge_apply_tax_texts`: once per database (config parameter
   `gec_localization.tax_texts_20261023`) removes the retired taxes in `GE_REMOVED_TAXES` (unlink,
   archive when used) and rewrites the name, description and invoice label (English + Georgian) of
   our taxes and of the l10n_ge taxes listed in `data/template/ge_core_tax_texts.csv`. The core
   texts reach the template through `_get_account_tax`. The reverse-charge rename of
   `ge_tax_p_rc_18_nonvatreg` runs once more under `gec_localization.tax_texts_rc_20261104`, rewriting
   the texts of that tax only (`_ge_apply_tax_texts(key, xmlids)`), so the bulk pass is not repeated.
6. `_load_translations(companies=...)`: fills Georgian names that are missing. Our accounts, tax
   groups and taxes carry `name@ka`. Core saves with `overwrite=False`, so a name already set stays.

A second run finds nothing missing and the same sequences, so it changes nothing.

---

## 6. Tax CSV conventions

- Same layout as `l10n_ge/data/template/account.tax-ge.csv`: the first row carries the tax, the
  next rows add `repartition_line_ids/*` (base and tax lines, invoice then refund).
- Withholding: negative `amount`, `is_withholding_tax` True, `amount_type` percent. Core
  `_check_amount_type` refuses group and division for withholding taxes.
- `use_in_tax_closing` is set **False** on the tax lines of withholding, turnover and CIT taxes.
  Core `_compute_use_in_tax_closing` would make it True for any tax line on a balance-sheet account.
- Tags: Reverse Charge III-19 carries `l10n_ge` report tags (`21(B)` on the base, `21(T)` on
  the −100% leg) and 18% Fixed Assets `24(B)` / `24(T)` (VAT on 334011). The tags exist because
  `l10n_ge`'s report creates them.
- `fiscal_position_ids` (last column) is filled only on 18% Fixed Assets (`ge_fiscal_position_vat`,
  like core's purchase 18%); `map_tax` passes our other taxes through unchanged.
- A tax line without `account_id` posts to the base line's account: that is how Non-Deductible
  and the +100% leg of III-19 land in the cost.
- Turnover: `division`, `price_include_override` `tax_included`, so tax = price × rate.
- CIT: `type_tax_use` none (selectable on journal entries only, like `l10n_ge`'s `18% Loss of Goods`),
  `division` 15%, legs +100% to 910010 and −100% to 331110: net zero on the entry.
- A tax cannot use a Payable account (core domain on the repartition line), which is why payroll
  income tax has its own account 331320 instead of 331310 being retyped.

---

## 7. Tax proposal: partner default taxes and Not Taxed

User rules and examples: [README.md, section 9](README.md#9-default-taxes-per-contact-and-not-taxed-products).

| Document line | Hook, after `super()` | Trigger added |
|---|---|---|
| Invoice and bill line | `account.move.line._get_computed_taxes`: product lines of sale and purchase documents only | `account.move._onchange_partner_id_default_taxes` recomputes the line taxes of draft invoices, bills and receipts in the form |
| Sales order line | `sale.order.line._compute_tax_ids`: lines with a product, not combo | also depends on `order_id.partner_id` |
| Purchase order line | `purchase.order.line._compute_tax_id`: lines with a product; fiscal position from the order or `_get_fiscal_position` | `purchase.order._onchange_partner_id_default_taxes` recomputes every line |

All three call `account.tax._ge_partner_product_taxes(taxes, partner, product, company,
type_tax_use, fiscal_position, date)`:

1. `product.not_taxed` → empty recordset.
2. Reads `property_sale_tax_id`, or for purchases the hook `_gec_partner_purchase_tax`
   (`property_purchase_tax_id`; gec_income_tax_report returns the version valid on `date`), on the
   commercial partner, in the document's company.
3. None set → returns core's taxes unchanged.
4. Set → that one tax replaces core's taxes: a Georgian withholding tax or 0% label as it is,
   any other tax through `fiscal_position.map_tax`.

Fields: both partner taxes are `company_dependent`, `check_company`, `ondelete='restrict'`; the
sales domain excludes withholding taxes; the purchase domain takes any purchase tax (VAT, a
Georgian withholding tax or a 0% label), one tax per contact. `_commercial_fields` adds
both, so core copies them to child contacts. `not_taxed` only hides the product's tax fields;
their values stay and are read by every code path that does not go through the hooks above
(expenses, the rs.ge waybill → invoice wizard, `_prepare_purchase_order_line`, Point of Sale,
eCommerce).

---

## 8. Bank name and BIC: `res.partner.bank._sanitize_vals`

1. `super()` moves `sanitized_account_number` to `account_number`, recomputes
   `sanitized_account_number` when `account_number` is in `vals`, and uppercases `bank_bic`.
2. If the sanitized number starts with `GE`, `GE_BANKS[number[4:6]]` gives name and BIC.
3. `bank_name` and `bank_bic` are filled only when `vals` has no truthy value for them, so a
   value typed in the same save wins and core's empty BIC on journal creation counts as not typed.

A write that does not touch the account number changes nothing. Consumers match the BIC by its
first 8 characters (`bank_bic[:8]`).

---

## 9. Contacts: categories, person or company, Treasury Code

`gec.contact.category`: `name` (translated), `color`, `active`; no `company_id`, so all companies
share the list. `res.partner.gec_contact_category_ids` is a stored, recursive compute with
`readonly=False`: a contact with a parent takes the parent's categories, a root contact keeps
what the user set. The form makes it read-only when `parent_id` is set; the partner search view
adds a search-panel section for list and kanban with `limit="false"` (no limit, as core's chart of
accounts panel): on Odoo 20 `limit="0"` becomes SQL `LIMIT 0` and empties the panel.

**Person or company.** `_compute_is_company` runs core first (a contact that is its own
commercial entity and has a Tax ID is a company), then sets `is_company` False where
`_gec_has_georgian_personal_number` holds: `split_vat(vat)` gives 11 digits and the Tax ID is
Georgian (prefix `GE`, else country Georgia, else no country, because `rs_waybill` creates drivers
and sellers without one). 9-digit codes and other countries keep core's result. Core precedents:
`l10n_my`, `l10n_uz`. The extra depends `vat`, `country_id` merge with core's.

`is_company` is stored, so contacts saved before the rule keep their old value until their Tax ID
or country changes. `_gec_recompute_georgian_company_flag` (data `<function>`, every install and
upgrade) searches companies with a Tax ID, archived included, keeps those with a personal number
and recomputes them with `env.add_to_compute` + `_recompute_recordset`, as
`account.payment` does. A second run finds none.

**Treasury Code.** `gec_treasury_code` shows on the partner property form for every contact
without `parent_id`. It cannot follow `is_company`: budget recipients such as the State Treasury
have no Tax ID, so core makes them persons.

---

## 10. Profit Distribution (CIT): `action_post_cit`

1. `net` = `net_amount` rounded in the company currency; refuses `net <= 0`, and refuses
   withholding without `dividend_wht_account_id`.
2. `gross = round(net_amount / 0.85)`, `cit = round(gross − net)`,
   `wht = round(net × rate / 100)` when ticked, `shareholder = net − wht`.
3. Lines: debit distribution account `gross` (with partner), credit CIT account `cit`, credit
   shareholder payable `shareholder` (with partner), credit WHT account `wht` (with partner) when
   not zero. Balanced by construction: `cit + (net − wht) + wht = gross`.
4. Creates an `account.move` of type `entry` in the chosen journal, posts it and returns its form.

`_compute_amounts` shows unrounded preview amounts. Domains limit the journal to the company's
general journals and the accounts to the company (distribution: equity types; shareholder:
Payable or Current Liabilities). The wizard does not use the CIT 15% tax.

---

## 11. Data

| File | Creates | `noupdate` | On upgrade |
|---|---|---|---|
| `data/wht_sequence.xml` | `seq_ge_wht`, no company | yes | left as is; the company copies come from the maintenance |
| `data/template/*.csv` | per-company accounts, tax groups and taxes, through the chart loader | not module data | missing rows are created; existing records are left alone ([section 4](#when-our-records-reach-a-company)) |
| `data/ge_tax_maintenance.xml` | nothing itself; calls the maintenance | no | runs every time |
| `data/res_partner_data.xml` | nothing itself; calls `_gec_recompute_georgian_company_flag` | no | runs every time |
| `views/*.xml` | views, two window actions, two menus | no | updated |
| `security/ir.access.csv` | two access rows | no | updated |

---

## 12. Guards and invariants

- `action_post_cit` refuses a net amount of zero or less, and withholding without an account (the
  form also makes the account required while withholding is ticked).
- Core `_check_amount_type` refuses group and division computations on withholding taxes.
- The maintenance never rewrites an existing record (except the one-time tax text pass and the
  removal of retired taxes), only handles root `ge` companies, and only replaces an empty or shared
  certificate sequence.
- `_ge_partner_product_taxes` returns the one contact default instead of core's taxes; for a
  `gec_vat_payer` contact a withholding or label default is added to core's (fiscal-position-mapped)
  taxes; a Not Taxed product gets no tax at all.
- `_sanitize_vals` never replaces a value typed in the same save and ignores non-Georgian numbers.
- `_compute_is_company` only ever turns a company into a person, never the reverse.
- The default-tax rules, the journal-entry Pay link and its Outstanding-account check apply only when the root company's fiscal country is
  Georgia (`res.company._gec_is_georgian`). The Pay link also needs a partner on the line.

What other modules rely on (xmlids, fields, account settings) is listed in
[Integration](#14-integration).

---

## 13. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `gec.contact.category` | `base.group_user` | crud | none |
| `l10n.ge.cit.wizard` | `account.group_account_user` | cru | none |

- Menus: Profit Distribution (CIT) `account.group_account_manager`; Contact Categories
  `base.group_user`.
- The partner fields carry no `groups`; they sit inside core's Fiscal Information group and
  Invoicing tab, visible to `account.group_account_invoice` and `account.group_account_readonly`.
- `sudo()` only where the user may not have access to what the code reads or writes: the root company's fiscal
  country and default partner taxes for a branch (`models/res_company.py`, `models/account_tax.py`),
  company depth in the payment register (`models/account_payment_register.py`), and the once-per-database
  markers and tax passes over every Georgian company (`models/template_ge.py`).
- Multi-company: partner default taxes are company-dependent and `check_company`; the wizard's
  journal and accounts are filtered by `company_id`. `gec.contact.category` has no company on
  purpose: it is a classification shared by every company.

---

## 14. Integration

| Module | Relies on |
|---|---|
| `geo_payroll` | `l10n_ge` account xmlids and `gec_account_331320` (its payroll income tax account); 332010 Payable + reconcilable; sets `gec_treasury_code` on its State Treasury contact |
| `gec_payroll_bank` | `gec_treasury_code` (no bank account needed); pays authority lines only when Payable-type and reconcilable, and refuses reconcilable lines it cannot route, which is why 331310 must not be reconcilable |
| `basis_bank` | `gec_treasury_code` → treasury transfer; finds its journal by the BIC filled here |
| `bog_bank`, `tbc_bank` | the BIC prefix; they do not depend on this module, so without it the BIC is typed by hand |
| `gec_income_tax_report` | tax xmlids `ge_tax_p_wht_*` (Form 30 income types) and `gec_account_140311` (cells 68 and 69); `is_company` decides its first/last name split |
| `geo_payroll` (contact form), `rs_waybill` | `is_company`: the Pension group shows on persons; waybill drivers and sellers are created without a country |

Renaming any of these xmlids or fields breaks the module next to it. Core fields used:
`account.tax.is_withholding_tax` and `withholding_sequence_id`.

---

## 15. Tests

`tests/test_ge_vat_mapping.py` (post_install, own Georgian company through `setup_country('ge')`)
covers the VAT corrections: a Tax-ID sale, a sale without Tax ID and to a pinned individual, a
foreign bill with and without `18% Reverse Charge Services`, an import VAT bill, the install repair and a chart
reload. Run:
`odoo-bin -c odoo.conf -d <scratch> -u gec_localization --test-enable --test-tags /gec_localization`.
For other changes, check a scratch database in both orders: module installed before the company
chooses the chart, and chart loaded before the module is installed.

---

## 16. Extending safely

- **New template function:** name it `_get_ge_gec_<model>`. Reusing an `l10n_ge` name replaces
  core's function.
- **New record:** `gec_account_*` / `gec_tax_group_*` xmlid. Never rename a `ge_tax_*` xmlid
  (`gec_income_tax_report` maps them).
- **Change an `l10n_ge` record:** add a row keyed by its xmlid with only the columns to change.
  It reaches new companies at chart load and existing ones only at install, never `reconcile`.
- **Change a column of an existing row:** existing companies do not get it; the maintenance only
  creates. Write it on those companies by hand or tell the accountant.
- **New Bank and Cash account:** an upgrade creates it through the maintenance without a journal,
  as a chart load does; create the journal by hand where a company needs one.
- **New withholding tax:** negative amount, percent, `is_withholding_tax` True,
  `use_in_tax_closing` False; the maintenance gives it the company's sequence.
- **Maintenance:** keep `@api.model` (the `<function>` tag needs it) and never reload an existing
  record, except the one-time tax text pass gated by its config parameter.
- **Tax proposal:** keep the call after `super()` and pass core's taxes in; the fiscal position
  and withholding handling depend on it.
- **New Georgian bank:** one line in `GE_BANKS`.

---

## 17. Known limitations

- Core drops `reconcile` on existing accounts during the install reload: the 331310 override
  misses companies that had the chart before the install.
- An upgrade never updates existing rows, only creates missing ones.
- The wizard's access row names only `account.group_account_user`. With enterprise `accountant`,
  `account.group_account_manager` implies it; without it, an Accounting Administrator sees the
  menu and gets an access error.
- Every run of the maintenance fills missing translations for the whole `ge` chart of each
  company, not only this module's records (`overwrite=False`, so no name already set changes).
- Paths that bypass the tax hooks keep the product's taxes ([section 7](#7-tax-proposal-partner-default-taxes-and-not-taxed)).
- The VAT corrections never reach a company that had the `ge` chart before an earlier install
  of this module, unless its chart is reloaded (only a fresh install runs the post_init hook).
- Included in Price on the Import taxes works on invoices and bills only; journal entries compute taxes
  as excluded.

---

## 18. Upgrading an existing database

| Condition | Fix |
|---|---|
| The company had the `ge` chart before the install, and 331310 still has `reconcile` True | Switch off **Payment Reconciliation** on 331310 ([README.md, section 4](README.md#4-set-it-up-once), step 3) |
| Bank journals whose default account is 110120, 120300 or 120980 and that hold no entries | Archive them unless the company uses them |
| The State Treasury contact (`geo_payroll.partner_state_treasury`) has no `gec_treasury_code` | Type 101001000; `geo_payroll`'s data is `noupdate`, so an upgrade does not fill it |
