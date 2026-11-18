# Georgian VAT mapping repair: detailed investigation and technical reference

For the concise list of what changes, where, how, and why, read the
[implementation plan](L10N_GE_VAT_MAPPING_REPAIR_PLAN.md) first. This document
preserves the investigation, source references, database findings, and detailed
validation requirements.

The revised plan also records the accountant's mandatory partner default tax
feature and the supplied Odoo skill's restrictions: preserve both fields and
their helper, keep the manifest version, and obtain a request/approval before
adding test files. The concise plan and this reference incorporate the verified Claude review.

Date: 5 October 2026. Status: investigation complete; implementation proposed.

**Environment correction from the user:** `gec20_prod1` is a test database;
these custom modules have not run in production. Database names must not be
used to infer deployment status. Existing documents are test fixtures. This
investigation supports development and first-deployment readiness, not a
production accounting remediation or historical migration.

**Recommendation:** correct the localization's tax replacement relationships in
`gec_localization`, using Odoo's chart-template inheritance and ORM. Keep Odoo's tax
calculation, accounting entries, chart of accounts, and VAT report engines intact.
The main repair removes nine incorrect replacement links and adds domestic
availability to ten sales taxes. The separately enumerated import-price correction
requires its own validation. Special taxes remain selected by transaction.

This document proposes application changes; none have been implemented. Database
inspection used PostgreSQL read-only transactions. The companion
[read-only audit SQL](L10N_GE_VAT_MAPPING_READONLY_AUDIT.sql) can reproduce the key
configuration and document checks without modifying data.

## 1. Evidence and limits

The investigation covered:

| Component | Examined version / evidence |
|---|---|
| Odoo core and `l10n_ge` | Local branch `20.0`, commit `25d63be66b6f`, 4 October 2026 |
| Custom addons | Repository commit `b4751f4`, 5 October 2026; clean before this investigation |
| `gec_localization` | Manifest and installed version `20.0.1.2.0` |
| Screenshot/test database | `gec20_prod1`, company 1, chart `ge`; inspected with writes disabled; no production deployment |
| Accounting reporting | Installed `account_reports`; its actual tax-tag SQL engine examined |
| Support acknowledgement | The user's supplied correspondence confirms Odoo considers the configuration defective |

Odoo's official documentation describes replacement taxes as cumulative: several
taxes configured to replace the same source are all applied. See
[Odoo tax mapping documentation](https://www.odoo.com/documentation/19.0/applications/finance/accounting/taxes.html).
The local Odoo 20 source establishes the exact behavior analyzed here. On
5 October 2026, direct retrieval of the public
[19.0 tax CSV](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/l10n_ge/data/template/account.tax-ge.csv)
and [20.0 tax CSV](https://raw.githubusercontent.com/odoo/odoo/20.0/addons/l10n_ge/data/template/account.tax-ge.csv)
confirmed the same six domestic sales and three foreign purchase replacements
remain in both branches. This verifies the current data, not the behavior of a
future hotfix/migration or every released Odoo build.

No complete Georgian tax-law audit, production migration, invoice correction, or
Odoo integration test was performed. A Tax ID on a company or partner does not
establish its legal VAT registration. Business classifications still need to be
provided by the company's accountant.

## 2. Root cause: configuration produces several destinations

In this Odoo version, tax replacement rules live on `account.tax`:

- `fiscal_position_ids`: positions in which this tax is available.
- `original_tax_ids`: source taxes that this destination replaces.
- `account.fiscal.position.tax_map`: groups **all** destinations by source tax.
- `map_tax()`: returns every configured destination. If there is no replacement,
  it keeps the source only when the source belongs to the current position or
  has no fiscal-position restriction; otherwise it removes the source.

Source:
[tax fields](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:81),
[map construction](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:105),
[mapping algorithm](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:161).

### Domestic sale

Under `ge_fiscal_position_vat`, standard `ge_vat_sale_18` is replaced by:

| Destination XML ID suffix | Tax | VAT-report category |
|---|---|---|
| `ge_vat_sale_18_sp_sale` | 18% S | `2(B)`, `2(T)` — special margin scheme |
| `ge_vat_sale_18_adv` | 18% AD | `3(B)`, `3(T)` — customer advances |
| `ge_vat_sale_18_other` | 18% O | `11(B)`, `11(T)` — other taxable transactions |
| `ge_vat_sale_exempt_financial` | 0% EXT F | `18(B)` — financial services exemption |
| `ge_vat_sale_exempt_land` | 0% EXT L | `19(B)` — land exemption |
| `ge_vat_sale_exempt_other` | 0% EXT O | `20(B)` — other exemption |

These are alternative transaction categories. The mapping applies them together
and removes ordinary VAT. For a tax-excluded line of 100 GEL, the three 18% taxes
produce 54 GEL and a total of 154 GEL. The zero-rate taxes also attach incorrect
report classifications, even though their monetary tax amounts are zero.

Database confirmation: `S00005` is a draft quotation with fiscal position 3,
untaxed 100.00, tax 54.00, total 154.00.

### Foreign vendor bill

Under `ge_fiscal_position_foreign`, standard `ge_vat_purchase_18` is replaced by:

| Destination XML ID suffix | Tax | Output VAT category |
|---|---|---|
| `ge_rcvat_18_ser` | 18% R C S | `21(B)`, `21(T)` — services |
| `ge_rcvat_18_goods_customs` | 18% R C G C | `22(B)`, `22(T)` — customs warehouse goods |
| `ge_rcvat_18_goods_fiz` | 18% R C G F | `23(B)`, `23(T)` — FIZ goods |

Each tax has a +100% input VAT leg on account `334040` and a -100% output VAT
leg on account `333060`. All three share input-report tags `27(B)` / `27(T)`.
They are three classifications, rather than three components of one VAT charge.

Database confirmation: posted `BILL/2026/10/0002` has a 100 GEL expense and 100 GEL
payable, plus **six** VAT journal items: three debits of 18 and three credits of
18. Its tax total is zero and its invoice total is 100. The payable looks correct
while VAT accounts and report classifications are wrong.

For this exact bill, tagged balances are:

| Tag | Actual tagged balance | Journal items |
|---|---:|---:|
| `21(B)` / `22(B)` / `23(B)` | 100 each | 1 each |
| `21(T)` / `22(T)` / `23(T)` | -18 each | 1 each |
| `27(B)` | 100 | 1 |
| `27(T)` | 54 | 3 |

**Precision matters:** the shared `27(B)` base is 100, not 300, on this single
invoice line. Core unions base tags on the same journal item; the three input VAT
items still sum to 54 under `27(T)`. The existing repository guide
`documentations/l10n_ge.md` says III.4 gets the base three times. That statement
needs correction during the documentation update; it is contradicted by both
the core code and this bill's stored tags.

## 3. Why automatic fiscal-position detection is expected

The standard positions are:

| Position | Sequence | Automatic condition |
|---|---:|---|
| Georgia (VAT Registered) | 10 | Georgian address and a Tax ID |
| Georgia (non-VAT Registered) | 20 | Georgian address; no Tax ID requirement |
| Non-Georgia | 30 | No country restriction; fallback after domestic matches |
| Domestic non-registered individual | 40 | Manual only |

A fiscal position explicitly assigned on the partner wins. When the partner
field is empty, Odoo selects the first matching automatic position; sales and
invoices can use delivery-address criteria. The screenshot's Georgian address
and Tax ID therefore explain the detected position.

`vat_required` uses `partner.has_vat` in the examined core. It does not call a
Georgian VAT-registration service. The position's name is therefore stronger
than what its matching condition proves.

Source:
[position templates](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_ge/data/template/account.fiscal.position-ge.csv:1),
[selection](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:259),
[Tax ID check](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:924).

Changing sequence, disabling detection globally, or assigning empty positions
to every partner would obscure the defective mappings and can alter other
transactions. The immediate repair should preserve position detection.

## 4. Core accounting path and the customization boundary

| Stage | Core behavior | Consequence for the repair |
|---|---|---|
| Chart creation | Reads localization CSV and merges chart-template methods | Adjust the input mappings before records are created |
| Company defaults | Georgian template selects `ge_vat_sale_18` and `ge_vat_purchase_18` | Keep those defaults and original tax identities |
| Tax proposal | Sales / purchases use product taxes; invoice lines also have account fallbacks | Repair mappings once instead of patching every document model |
| Fiscal position | Maps source taxes to destinations | Remove the bad replacement links |
| Tax computation | Calculates each selected tax; negative repartition factors produce reverse-charge counterparts | Retain the tax engine and repartition factors |
| Journal generation | Uses repartition accounts, amounts, and tags; synchronizes draft moves | Let Odoo recalculate reviewed drafts normally |
| VAT report | Aggregates stored tagged journal-item balances | Fix future inputs; correct historic entries separately |

Relevant source:
[chart merge](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:826),
[company defaults](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_ge/models/template_ge.py:24),
[invoice tax proposal](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_move_line.py:1302),
[sales mapping](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/sale/models/sale_order_line.py:707),
[purchase mapping](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/purchase/models/purchase_order_line.py:192),
[repartition and base tags](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:2417),
[tax-line grouping](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:2334),
[draft synchronization](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_move.py:3346),
[report engine](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/enterprise/account_reports/models/account_report.py:4401).

`gec_localization` already adds partner default taxes and a Not Taxed product
option after core tax proposal. Its helper maps the partner's chosen tax through
the same fiscal position and preserves withholding taxes. Consequently a partner
default of standard 18% reproduces the localization error; the helper is not the
source of the nine bad links. Keep these proposal hooks intact for this repair.

Some integrations supply `tax_ids` explicitly. They may bypass tax proposal;
existing wrong selections or imported predictions can survive a mapping fix.
The current waybill invoice wizard also applies `map_tax()` after creation.
These paths belong in acceptance tests, without adding a second tax-selection
engine or sending anything to RS.ge during testing.

## 5. The immediate configuration changes

### A. Domestic sales: unlink six replacement edges

For the six domestic destination taxes in section 2, remove only the source link
to `ge_vat_sale_18` from `original_tax_ids`.

Keep their current fiscal-position membership, rates, labels, accounts, and
invoice/refund repartition lines. With no destination replacing standard VAT,
core's fallback maps `ge_vat_sale_18` to itself under the VAT position.

Expected ordinary transaction on 100 GEL tax-excluded:

- One selected standard sales VAT tax; VAT 18, receivable 118.
- Credit revenue 100; credit VAT payable `333002` 18; debit receivable 118.
- VAT report uses `1(B)` = 100 and `1(T)` = 18 in displayed output signs.
- Special margin, advance, other, and exempt report categories receive nothing
  from this ordinary transaction.

The six special taxes remain usable when explicitly selected on the appropriate
line/product/partner default. The plan does not reinterpret their tax bases or
implement special margin or advance business workflows.

### B. Foreign purchases: unlink three replacement edges; classify explicitly

Remove the source link to `ge_vat_purchase_18` from each of the three
reverse-charge destination taxes. Preserve all three tax records, their foreign
position membership, and their existing repartition data.

**This intentionally stops automatic reverse-charge classification.** In the
generic Non-Georgia position, standard purchase VAT is then removed by core
because it belongs only to the domestic VAT position. The resulting empty tax
proposal is an unclassified foreign purchase, not evidence that the transaction
is exempt or outside VAT. Before posting, the accountant must select the
appropriate purchase treatment, including one existing reverse-charge tax when
applicable. Build this review into the rollout and purchasing procedure.

A foreign address alone cannot choose between services, warehouse goods, FIZ
goods, customs import VAT, or another treatment. Neither product Goods/Services
scope nor tax sequence disambiguates these destinations in `map_tax()`.
Automatically retaining the services replacement would fix the count while
potentially assigning goods to the wrong declaration category.

For a service classified to `ge_rcvat_18_ser`, a 100 GEL bill should produce:

- Expense debit 100 and vendor payable credit 100.
- Input reverse-charge VAT debit `334040` 18.
- Output reverse-charge VAT credit `333060` 18.
- Report base/tax 100/18 for category 21 and 100/18 for category 27;
  categories 22 and 23 remain zero for that transaction.

For a consistently classified vendor, the existing company-dependent
`property_purchase_tax_id` can select that specific tax. Avoid a vendor-wide
default when the vendor supplies mixed transaction types: select per line. Before
rollout, inventory existing partner defaults. Before each monthly VAT filing,
review the audit's posted Non-Georgia lines with no non-withholding tax. Correctly
untaxed purchases can appear; the list is a review tool, not a VAT-liability test.
No posting block, automatic country-based default assignment, or cron is proposed.

**Optional later convenience:** explicit, nonautomatic service/warehouse/FIZ
fiscal positions can encode distinct treatments using standard Odoo fields.
This is a separate configuration extension. A tax's Replaces links apply to all
positions on that tax: combining a new specific position with generic
Non-Georgia and restoring its source link would reintroduce the original bug.
Design and test the complete position membership before adding these positions.

### Preserve the existing export replacement

Do not remove `ge_vat_sale_18 -> ge_vat_sale_0_ex` under Non-Georgia as part of
the nine-link hotfix. This is a single distinct rule, rather than the observed
triplication. Test that it remains unchanged.

Its business suitability still needs separate review: a foreign customer is
not proof of a qualifying goods export, and the same generic position also
matches services and some missing-address situations. Preserving a rule does
not certify its tax-law correctness.

## 6. Implementation in `gec_localization`

**Only `models/template_ge.py` needs application changes.** Reuse the existing
`_ge_gec_apply_maintenance()` lifecycle instead of adding another XML function,
manifest entry, or dry-run path. The companion read-only SQL supplies preflight
and postflight evidence. The concise plan contains the exact nine-link and
ten-tax tables and the separately enumerated import setting.

### 6.1 Future chart creation

Override the generic `_get_account_tax(self, template_code)`, call `super()`,
and return other chart codes unchanged. On `ge`, recognize and remove the exact
faulty six/three source replacement graphs. Set `original_tax_ids` explicitly to
`False` for the current single-source values: omitting the field or leaving a
CSV cell blank does not clear inherited data. Add both other domestic positions
to the ten named sales taxes while retaining existing memberships. Add the three
VAT-only import price overrides only after their separate validation.

Use ordinary inheritance with the original signature, without adding a GEC
`@template` registration to this override. Core retains the original template
metadata when locating an override. Validate actual registration on the clone.

GEC maintenance loads only template data attributed to `gec_localization` and
creates missing records. Sparse stock-tax overrides in
`_get_ge_gec_account_tax()` would make a missing stock ID look like a new GEC tax
with no complete definition. Keeping the correction on the core provider avoids
that path and keeps GEC's tax CSV limited to its own taxes.

Source:
[template registration](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:76),
[stock provider](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:1136),
[empty CSV handling](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:1343).

### 6.2 Existing companies through the current maintenance method

Add one short `_ge_repair_stock_vat_configuration()` method in company context,
called once per root company from `_ge_gec_apply_maintenance()`. Existing
`data/ge_tax_maintenance.xml` already calls maintenance on install/upgrade;
`_post_load_data()` already calls it on Georgian chart loading. Those routes and
the manifest require no edits. Keep version `20.0.1.2.0`; add no migration script.

Resolve stock taxes and positions by company-prefixed XML IDs using
`account.chart.template.ref()`, for example `account.1_ge_vat_sale_18_adv`.
Require correct ownership. Branches sharing root records inherit the correction;
do not create duplicate branch taxes. Preserve inactive status.

For a recognized faulty graph, remove only the named source relationship with
`Command.unlink(source.id)`. Add only missing Change C memberships with
`Command.link(position.id)`. The separate validated Change D is a normal tax
`write()` for its three price overrides. No `Command.clear()`, tax deletion, SQL
update, or manual commit is appropriate. After replacement edits, invalidate the
affected positions' nonstored `tax_map` cache and verify the resulting mappings.
Its compute depends on `tax_ids`, while its body also reads `original_tax_ids`;
validate a map cached before the repair.

Do not define the defect merely as multiple destinations for a source. Spanish
localization legitimately maps VAT and withholding together:
[VAT source/destination](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_es/data/template/account.tax-es_common.csv:2),
[additional withholding destination](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_es/data/template/account.tax-es_common.csv:614).
Match the named Georgian faulty configurations. Already removed links require
no write. Validate the proposal before writes, then apply A/B, C, and validated D
in that order. A changed upstream/custom graph with a remaining bad named link
requires review and a clear configuration conflict, rather than a silent skip
described as a successful repair. Keep this check concise and all repair writes
transactional. Preflight should resolve conflicts before an upgrade is attempted.

Update maintenance's docstring: normal GEC records retain accountant edits,
with an explicit exception for these named stock corrections. This does not
authorize overwriting other existing configuration. Repeated repair calls should
make no additional repair writes; the pre-existing maintenance can still perform
its own sequence/translation work during an upgrade.

Template changes protect new charts, but chart reload generally preserves old
replacement links. Core only restores such links for newly created taxes; a
source change alone does not clean existing relationships. Odoo's eventual patch
must be assessed for its actual database repair, not assumed to include one.

Source:
[GEC maintenance and chart-load route](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py:30),
[existing data function](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/data/ge_tax_maintenance.xml:4),
[company XML IDs](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:1244),
[reload rules](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/chart_template.py:403),
[map cache dependency](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:105).

## 7. Companion configuration and release gates

### Change C: all ten domestic sales taxes

The stock CSV and database confirm ten sales taxes are restricted to
`ge_fiscal_position_vat`: standard VAT, special margin, advances, building,
repairs, barter, other taxable sales, and financial/land/other exemptions. Core
therefore drops these selections under the two other domestic positions.

The revised plan adds `ge_fiscal_position_nonvat` and
`ge_fiscal_position_domestic` to **all ten**, preserving existing memberships.
That is 20 added relationships in stock configuration, separate from the nine
replacement removals. It makes the selected domestic treatment available and
does not automatically choose all ten taxes. Verify ordinary, advance, special,
and exempt selections under both positions. Confirm the selling company's VAT
scope with the accountant; a company Tax ID alone does not prove it. Do not
apply this sales policy to purchase taxes or clear foreign restrictions.

### Missing stored domestic position in `gec20_prod1`

Read-only inspection confirms company 1 has no stored
`domestic_fiscal_position_id`. All ten taxes above currently have
`is_domestic = false`. Tax and fiscal-position domestic flags depend on this
company field, so picker availability is affected independently of tax mapping.

On the clone, run the existing core
`company._compute_domestic_fiscal_position_id()`, flush, and verify the stored
position and dependent flags/pickers. Its current sequence/country computation
should choose Georgia (VAT Registered). Preserve sequences; toggling one only
to trigger recomputation adds unnecessary edits. The recomputation has not been
executed in this review, and the cause of the stale value is unproven. Core's
compute dependencies omit company country, but that alone does not establish
what happened in this database. The reviewer's separate `gec20_prod` claim has
not been independently checked here.

Source:
[company computation](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/company.py:436),
[tax domestic flag](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:318),
[position domestic flag](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:81),
[picker filtering](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:253).

### Change D: customs VAT-only price setting, validated separately

Stock `ge_import_duty_18`, `ge_import_duty_12`, and `ge_import_duty_5` are
100% division taxes. In `gec20_prod1` their explicit price overrides are empty
and company pricing is tax-excluded. Core's formula then gives base 180 plus
VAT 180, payable 360 for an entered 180. With `price_include_override` set to
`tax_included`, the intended VAT-only example should give base 0, tax 180,
payable 180. Source formulas and configuration were checked; this review has not
run the full Odoo posting/report integration scenario claimed by Claude's older
probe. Keep that distinction explicit.

Propose the three override changes in the same template/maintenance file, but
validate them separately before rollout: import VAT account and tags, companion
customs base, refunds, currencies, and price display. Preserve rates, the
zero-rate base taxes, tags, and repartitions. Already included settings need no
write; other explicit accountant settings require review.

Source:
[import tax CSV](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_ge/data/template/account.tax-ge.csv:106),
[price-included formula](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:1078),
[price-excluded formula](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_tax.py:1098).

### Later: supplier VAT-registration verification

Core's Tax ID condition is not a Georgian VAT registry check. A confirmed
non-VAT supplier can use the existing GEC exempt Default Purchase Tax;
classification and input-VAT eligibility still need accountant review. A future
registry integration could extend `_get_vat_required_valid()`, as the EU VIES
module does, but requires a verified Georgian data source and its own design.
Keep both mandatory partner defaults operational.

Source:
[core Tax ID hook](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/partner.py:924),
[EU extension precedent](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/l10n_eu_account_vies/models/res_partner.py:178).

Export applicability, missing report categories, special-margin calculation,
and advance workflows remain separate investigations. Do not silently add
account/rate/report changes to the configuration repair.

## 8. Existing test documents: validation examples

The audit found the following accounting candidates in `gec20_prod1`:

| State | Type | Candidate documents / lines |
|---|---|---:|
| Posted | Customer invoice | 2 / 2 |
| Posted | Vendor bill | 1 / 1 |
| Draft | Vendor bill | 1 / 1 |
| Cancelled | Customer invoice | 1 / 1 |

The posted documents are `INV/2026/00001`, `INV/2026/00002`, and
`BILL/2026/10/0002`. The expanded audit additionally found five sales orders:

| Order | State | Current invoice status |
|---|---|---|
| S00001 | Draft | Nothing to invoice |
| S00002 | Confirmed | Invoiced |
| S00004 | Confirmed | Still to invoice |
| S00005 | Draft | Nothing to invoice |
| S00006 | Confirmed | Invoiced |

All five carry the same six sales taxes. **S00004 is a useful saved-order test**:
core copies its current taxes to the next test invoice even after the mapping
repair. Correct the intended selection before testing the corrected invoice flow;
this is not an urgent production billing issue.
No purchase orders matched the three-tax candidate query at inspection time.
Emma Granger is the foreign-address vendor in the default inventory and has no
saved purchase-tax default. That inventory shows stored overrides, not calculated
ORM fallback values. The monthly untaxed Non-Georgia query currently returned
no rows; it must be used after repair and before filings as well.

Source:
[sales tax copy](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/sale/models/sale_order_line.py:2067),
[purchase tax copy](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/purchase/models/purchase_order_line.py:787).

This is a candidate inventory, not proof of every document's intended tax
treatment or a complete inventory of imported data and tax omissions.

These records are test data. There is no demonstrated production ledger or
filed return to remediate. Keep representative before-fix records for comparison,
and create corrected test transactions after applying the configuration changes.
Saved taxes are not automatically corrected by an upgrade, so inspect the saved
orders separately when using them in tests.

The configuration repair should not write to orders, moves, journal items,
payments, or reconciliations. This makes it possible to prove that accounting
changes arise from normal tax selection/posting rather than hidden data rewrites.
A disposable test invoice may be reset through native Odoo actions if appropriate;
credit notes and reversals are validation scenarios, not mandatory remediation of
these test records. Refund tests should verify normal signs and report treatment.
Do not edit journal tax tags directly or divide report amounts by three.

Source:
[Update Taxes](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_move.py:6611),
[native reversal](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/account/models/account_move.py:5888).

## 9. Verification required before deployment

An isolated source probe executed the actual core `_compute_tax_map()` and
`map_tax()` methods with small in-memory recordset stand-ins. Eight assertion
groups passed: stock six/three destinations reproduced; proposed domestic
standard sale and purchase retained; generic foreign purchase became empty;
export remained unchanged; explicit special and reverse-charge choices remained
available; the separate domestic no-Tax-ID omission remained visible.

This establishes the mapping behavior. It is **not** a live Odoo registry test,
tax-engine test, module installation test, or posted VAT-report test. The
following integration validation remains required before deployment; adding
test files requires the user's request/approval under the supplied skill:

| Test | Required result |
|---|---|
| Fresh chart with GEC installed first | Correct template registration; nine bad edges absent; all stock/GEC taxes and accounts created normally |
| Install GEC after an existing `ge` chart | Guarded repair operates on existing IDs; no sparse stock-tax creation or duplicate accounts/taxes |
| Upgrade GEC on a clone | Audit before/after agrees with declared edits; repeat repair makes no additional repair writes |
| Cached map before repair | Same environment returns corrected mappings after ORM write/invalidation |
| Ordinary domestic SO → invoice | On 100 tax-excluded, one VAT 18; total 118; correct revenue/VAT/receivable lines and report category 1 |
| Domestic purchase order → bill | Standard local VAT remains 18; total 118; input VAT account `334010` and category 24 |
| Explicit RC services / customs / FIZ, separately | Exactly one category per tested line, two VAT legs ±18, payable 100, input VAT 18; shared input base once |
| Generic foreign purchase | No automatic RC category; reviewed vendor defaults/per-line choice select intended treatment; monthly candidate list works |
| VAT-only imports, separately | Entered VAT 180 gives base 0, tax 180, payable 180 with reviewed customs-base/report workflow |
| Missing domestic company position | Core recomputation on clone yields expected position and picker flags without sequence edits |
| Standard foreign sale | Existing single export replacement unchanged; accountant-approved business scenario used |
| Customer without Tax ID / manual domestic position | All ten selected sales treatments remain available and map to themselves; ordinary VAT 18 on 100 |
| Credit notes and reversal scenarios | Correct refund/report signs; an exact reversal offsets its original test entries |
| Price-included, multicurrency, discounts, rounding | Odoo totals remain consistent with approved corrected tax IDs; unit-price effects reviewed |
| Partner defaults, withholding, Not Taxed products | Existing helper behavior remains intact; explicitly selected categories do not expand into several taxes |
| GEC CIT/payroll/WHT maintenance | Existing settings and sequences unchanged by the repair; upgrade effects separately accounted for |
| Multi-company and branches | Independent roots repaired independently; shared branch records changed once; other charts untouched |
| Customized / missing / inactive configuration | No guessed identity or reactivation; conflicts reported; unrelated mappings preserved |
| Existing drafts, posted lines, payments, locks | Repair alone changes none of these records or balances; historic VAT report unchanged |
| Prediction, copying, down payments, waybill/RS paths | Old wrong tax sets identified; chosen taxes retained where valid; external RS calls stubbed |
| Simulated corrected upstream data | Matching correction becomes a no-op; changed replacement graph is reviewed, with legitimate new configuration preserved |

Capture before/after IDs and values for accounts, taxes, repartitions, tags,
company defaults, orders, journal items, and reconciliations. During a module
upgrade, distinguish this repair's writes from existing GEC maintenance, which
can create missing GEC template records, assign WHT sequences, and fill missing
translations. Existing maintenance is broader than the nine-edge repair.

## 10. Development validation, first deployment, and Odoo's eventual patch

1. Preserve the current test database as a reproducible baseline and work on a
   disposable copy. Stub outbound integrations and disable external clone jobs.
2. Run the expanded read-only audit; resolve customized mapping conflicts, seller
   VAT scope for all ten taxes, domestic-position recomputation, and the intended
   foreign-purchase defaults/review procedure. Validate Change D separately.
3. Implement the small configuration repair. Prioritize fresh installation and
   new-chart creation, the first-production path. Also validate upgrades against
   the existing test chart and repeat repair calls. Add test files only when
   requested/approved under the supplied skill.
4. Compare declared configuration edits and unchanged saved test accounting.
   Create corrected orders, invoices, bills, refunds, and import examples through
   normal Odoo flows and verify their entries and VAT report.
5. After validation passes, make the first production deployment using the
   validated installation/chart setup. Carry over reviewed configuration, not
   erroneous test documents. Verify company settings, partner defaults, mapping,
   picker availability, and representative transactions before real posting.

There is no current production upgrade, historic-invoice correction campaign, or
filed-return amendment established by this investigation. Existing-company repair
remains useful for development database upgrades and later supported upgrades.
A failed test can be rolled back by restoring the disposable test copy; uninstalling
GEC or restoring the wrong tax relationships is not the chosen fix.

When Odoo releases its patch, compare its actual source and migration against
this policy. Do not assume installing new source removes old database links or
corrects old invoices. Test the patched version on a clone, confirm both fresh
and existing company mappings, then retire the now-redundant conditional template
repair. Keep the explicit business classifications and document remediation
that are still required. A future upgrade must never blindly restore the old
stock mappings or overwrite an accountant's new valid configuration.

The design confines the immediate repair to configuration relationships and
uses the standard accounting engine. Deployment safety is established by the
clone comparison and acceptance tests above; it cannot be guaranteed from source
inspection alone.
