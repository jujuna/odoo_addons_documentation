# Georgian VAT fix: exactly what we will change

5 October 2026. Proposed changes only; no application code or database records
have been changed.

**Environment: development/testing.** The user confirmed `gec20_prod1` is a test
database and these modules have not been deployed to production. Its name does
not indicate production use. The documents below are test examples, not evidence
of affected production invoices or filed returns. The objective is a correct
module and validated configuration before the first production deployment.

**The main fix removes nine wrong “Replaces” links and adds domestic availability
to ten existing sales taxes.** The application changes fit in
`models/template_ge.py`, using the existing maintenance flow for existing
companies and chart-template inheritance for new charts. Odoo continues
calculating and posting the selected taxes through its normal accounting engine.

Claude's review prompted the broader ten-tax correction, simpler lifecycle,
order audit, and domestic-position preflight below. A separate import-tax
price-setting fix is enumerated as Change D; it requires its own clone validation.

The detailed findings and source references are in the
[investigation](L10N_GE_VAT_MAPPING_INVESTIGATION.md). The
[read-only audit](L10N_GE_VAT_MAPPING_READONLY_AUDIT.sql) was tested against
`gec20_prod1`.

## Mandatory requirement — preserve both partner default tax fields

The accountant requires **Default Sales Tax** (`property_sale_tax_id`) and
**Default Purchase Tax** (`property_purchase_tax_id`). Both remain enabled,
visible, and functional. The repair will not remove or rename either field,
clear saved partner defaults, remove their views, or bypass their tax-selection
helper. Their company-specific values and commercial-partner behavior stay.

The existing selection rule, verified in
[account_tax.py:8](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/account_tax.py:8),
is:

1. A **Not Taxed** product proposes no taxes, including withholding.
2. Otherwise, when the commercial partner has a default for this direction,
   select that default in the document's company and apply the fiscal position
   to it. Keep withholding taxes from the core proposal.
3. When no partner default is set, keep the core tax proposal.

**A partner default chooses the source tax; the fiscal position still applies
afterwards.** The repair preserves that rule. It corrects the replacement data
used by the fiscal position, which currently expands even a partner-selected
standard sales 18% into six taxes.

| Partner choice | Position | Proposed result after Changes A/B |
|---|---|---|
| Customer default = standard sales 18% | Georgia (VAT Registered) | One standard 18% tax |
| Customer default = 18% AD or 0% EXT F | Georgia (VAT Registered) | The specifically selected advance or financial-services tax |
| Vendor default = standard purchase 18% | Georgia (VAT Registered) | Standard purchase VAT, plus proposed withholding if present |
| Vendor default = 18% R C S | Non-Georgia | One services reverse-charge tax, plus proposed withholding if present |
| Vendor default = GEC VAT Exempt (Purchase) | Domestic or Non-Georgia | That existing exempt tax, plus proposed withholding if present |
| Vendor default = standard purchase 18% | Non-Georgia | Empty VAT proposal; review and choose the actual purchase category before posting |
| Partner default empty | Any | Core proposal with the repaired mapping |
| Product marked Not Taxed | Any | No proposed taxes, retaining the existing product rule |

The foreign standard-18% case is an intentional consequence of Change B, not a
disabled partner field. Before rollout, inventory those partner defaults and
the documents using them. If the vendor consistently supplies qualifying
services, the accountant can set **Default Purchase Tax = 18% R C S**. Do not
silently overwrite saved defaults or infer a category from country alone.

The dependency sweep found **three callers and one implementation** of the
shared helper across `addons`, `enterprise`, and `custom_addons`, with no
additional helper override. These existing files require no edits for Changes A/B:

| Existing feature location | Verified responsibility |
|---|---|
| [models/res_partner.py:17](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/res_partner.py:17) | Both fields are company-dependent, check company compatibility, and are commercial fields |
| [views/res_partner_views.xml:87](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/views/res_partner_views.xml:87) | Both fields are displayed after Fiscal Position |
| [models/account_tax.py:8](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/account_tax.py:8) | Shared partner/product selection rule |
| [models/sale_order_line.py:8](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/sale_order_line.py:8) | Sales proposal, after `super()`, on product lines except combos |
| [models/purchase_order_line.py:7](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/purchase_order_line.py:7) | Purchase proposal, after `super()`, on product lines |
| [models/account_move_line.py:11](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/account_move_line.py:11) | Customer invoice and vendor bill proposal on eligible product lines |
| [models/purchase_order.py:8](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/purchase_order.py:8) | Existing purchase partner-change refresh |

This is a source review, not completed Odoo integration validation. Orders copy
their selected line taxes to invoices/bills. Existing copied/imported taxes and
changes to a partner default alone must not be assumed to repair previously
saved documents. Validation must cover order creation, direct invoices/bills,
order-to-invoice/bill conversion, partner changes, child contacts, two companies,
withholding, Not Taxed products, and both empty and explicitly selected defaults.

## 1. What changes in the tax configuration

### Change A — ordinary sales use ordinary VAT

In **Accounting → Configuration → Taxes**, these six sales taxes currently say
they replace the standard sales **18%** tax under **Georgia (VAT Registered)**:

| Existing tax | Existing “Replaces” | Proposed “Replaces” |
|---|---|---|
| 18% S — special margin scheme | Standard sales 18% | Empty |
| 18% AD — customer advances | Standard sales 18% | Empty |
| 18% O — other taxable transactions | Standard sales 18% | Empty |
| 0% EXT F — financial services | Standard sales 18% | Empty |
| 0% EXT L — land | Standard sales 18% | Empty |
| 0% EXT O — other exemptions | Standard sales 18% | Empty |

**Why:** these are different transaction categories. The current mapping selects
all six whenever a normal product proposes standard VAT. Removing those
replacement links lets standard VAT remain on an ordinary sale. A special tax
can still be selected when that special transaction actually occurs.

| Ordinary tax-excluded sale of 100 GEL | Before | After |
|---|---|---|
| Line taxes | Three 18% taxes and three exempt taxes | One standard sales 18% tax |
| VAT | 54 GEL | 18 GEL |
| Customer total | 154 GEL | 118 GEL |
| VAT report classification | Several unrelated categories | Standard sales: `1(B)` / `1(T)` |

### Change B — foreign purchases use the transaction's actual category

These three purchase taxes currently all replace standard purchase **18%** under
**Non-Georgia**:

| Existing tax | Existing “Replaces” | Proposed “Replaces” |
|---|---|---|
| 18% R C S — reverse-charge services | Standard purchase 18% | Empty |
| 18% R C G C — customs warehouse goods | Standard purchase 18% | Empty |
| 18% R C G F — FIZ goods | Standard purchase 18% | Empty |

**Why:** a foreign vendor's address does not establish which of these treatments
applies. Odoo currently selects all three. Each creates a VAT debit and credit,
so the bill total can look correct while VAT entries and reporting are wrong.

**The after-behavior needs an explicit choice.** With these links removed,
standard purchase VAT maps to **no tax** in generic Non-Georgia. The accountant
must choose the appropriate treatment before posting. An empty proposal is not
a conclusion that the purchase is exempt. This patch does not add a mandatory
posting check.

Example, assuming a 100 GEL purchase is classified as reverse-charge services:

| Vendor bill | Before | After selecting 18% R C S |
|---|---|---|
| Selected categories | Services, warehouse goods, and FIZ goods | Services only |
| VAT journal items | Three debits of 18 and three credits of 18 | One debit of 18 and one credit of 18 |
| Input VAT | 54 GEL | 18 GEL |
| Vendor payable | 100 GEL | 100 GEL |
| Report classification | Categories 21, 22, 23 and input tax 27 | Category 21 and input tax 27 |

For a vendor whose purchases consistently use one category, the existing GEC
**Default Purchase Tax** on the partner can select that specific tax. For mixed
purchases, choose per line. Establish this procedure before applying Change B.
Making services the default for every foreign vendor would merely replace the
duplication with potentially incorrect classification.

### Change C — make all ten affected sales taxes available to domestic buyers

Ten sales taxes are currently restricted to Georgia (VAT Registered). Under
the two other domestic positions Odoo drops a selected tax from this list and
limits the tax picker. Changes A and B do not fix that omission.

For a confirmed VAT-registered selling company, the proposed additional edit is:

| Existing tax | XML ID suffix |
|---|---|
| 18% | `ge_vat_sale_18` |
| 18% S | `ge_vat_sale_18_sp_sale` |
| 18% AD | `ge_vat_sale_18_adv` |
| 18% B | `ge_vat_sale_18_building` |
| 18% R | `ge_vat_sale_18_repairs` |
| 18% BA | `ge_vat_sale_18_barter` |
| 18% O | `ge_vat_sale_18_other` |
| 0% EXT F | `ge_vat_sale_exempt_financial` |
| 0% EXT L | `ge_vat_sale_exempt_land` |
| 0% EXT O | `ge_vat_sale_exempt_other` |

On each tax, keep existing memberships and add `ge_fiscal_position_nonvat` and
`ge_fiscal_position_domestic`: **20 added relationships in untouched stock data**.
This makes a specifically selected tax usable; it does not select all ten taxes
on a line. It also covers customer advances and explicitly selected exemptions,
which the earlier one-tax proposal omitted.

**Why:** buyer Tax ID matching should not silently discard the selected domestic
sales treatment. Confirm the selling company's VAT status and the use of this
VAT chart with the accountant before rollout; a company Tax ID alone is not
enough. Purchase-tax memberships stay as configured. Foreign memberships are
not added or cleared, so the existing export mapping remains separate.

### Change D — separate correction for customs VAT-only amounts

For `ge_import_duty_18`, `ge_import_duty_12`, and `ge_import_duty_5`, propose
`price_include_override = 'tax_included'` in the template and on existing stock
records. These three EX ONLY taxes use **100% division**, despite their names.
They represent an entered tax amount, rather than an ordinary net goods price.

With tax-excluded pricing, entering 180 currently leaves a base of 180 and adds
tax of 180, giving 360. For the intended VAT-only entry, price inclusion should
give base 0, tax 180, payable 180. The core formulas and current configuration
support this result; a full posted clone scenario has not been run in this review.

This is an explicitly separate setting change, not part of the nine-link repair.
Validate the three taxes, customs base/report treatment, refunds, and currencies
before enabling it. Preserve an already included setting; review other explicit
accountant settings before changing them. Do not alter the accompanying zero-rate
base taxes, the rates, accounts, or report tags.

## 2. Where the application changes go

All application changes are inside `gec_localization`:

| File | Exact planned addition | Why it is needed |
|---|---|---|
| [models/template_ge.py](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/gec_odoo_modules/gec_localization/models/template_ge.py) | Override `_get_account_tax(self, template_code)` using `super()` | New Georgian charts receive Changes A/B/C, and D once validated |
| Same file | Add one short `_ge_repair_stock_vat_configuration()` method in company context | Apply the named relationship/settings edits to already existing stock taxes |
| Same file, `_ge_gec_apply_maintenance()` | Call that method once for each Georgian root company; update its docstring | The existing XML already invokes maintenance on install/upgrade, and `_post_load_data()` already calls it on chart load |
| Existing documentation | Record the narrow repair exception and required purchase review | Replace the maintenance guarantee with an accurate description |

The existing `data/ge_tax_maintenance.xml`, `_post_load_data()` route, and
manifest need no changes. Keep version `20.0.1.2.0`. The read-only audit replaces
a second dry-run implementation. No new field, wizard, cron, tax record, or core
override for computation/posting is required.

Following the supplied
[Odoo development skill](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/.claude/skills/odoo-dev/SKILL.md),
the plan includes no version bump or standalone migration script. Validation
scenarios are listed here; test files would be added only if the user requests
or approves them during implementation.

## 3. How the code applies the configuration edits

**For a new company:** Odoo reads `l10n_ge`'s tax template. Our inherited
`_get_account_tax()` receives that data from `super()`, checks that the template
is `ge`, and corrects the known faulty data before Odoo creates the taxes. Add
the domestic memberships to the ten named sales taxes without replacing their
other memberships. Include the three import price settings only after Change D
passes its validation. The stock records are still created by Odoo.

**For an existing company:** the repair finds the existing source and destination
taxes using their company-specific XML IDs. It checks the known faulty mapping
and removes only the named source relationship through Odoo's ORM.

These are the exact tax identities used by the code:

| Destination XML ID suffix | Source relationship to remove | Expected position |
|---|---|---|
| `ge_vat_sale_18_sp_sale` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_vat_sale_18_adv` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_vat_sale_18_other` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_vat_sale_exempt_financial` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_vat_sale_exempt_land` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_vat_sale_exempt_other` | `ge_vat_sale_18` | `ge_fiscal_position_vat` |
| `ge_rcvat_18_ser` | `ge_vat_purchase_18` | `ge_fiscal_position_foreign` |
| `ge_rcvat_18_goods_customs` | `ge_vat_purchase_18` | `ge_fiscal_position_foreign` |
| `ge_rcvat_18_goods_fiz` | `ge_vat_purchase_18` | `ge_fiscal_position_foreign` |

For company 1, for example, the stock identity is
`account.1_ge_vat_sale_18_adv`. Company IDs are resolved at runtime; translated
tax names and screenshot database IDs are not used to locate records.

The core of each existing-record edit, **after identity and configuration checks**,
is:

```python
destination.write({
    'original_tax_ids': [Command.unlink(source.id)],
})
```

That removes a relationship. It does not delete the tax. The template version
sets `original_tax_ids` explicitly to `False` for each recognized single-source
mapping. Simply omitting the field or leaving a CSV cell blank would leave the
inherited bad mapping in place.

Use the audit as the before/after list. The repair recognizes the exact six-tax
domestic and three-tax foreign faulty configurations, not a general rule that
multiple replacements are wrong. Odoo legitimately combines replacements, for
example Spanish VAT with withholding. Preserve unrelated links and memberships.
Already repaired relationships/settings produce no further repair writes.

A changed upstream or customized replacement graph requires review before
applying this fixed policy. Resolve and validate the company proposal before
writing: apply A/B, then C, then validated D. If a bad named link remains in an
unexpected configuration, stop with a clear configuration conflict rather than
silently skipping it and labeling the company repaired. An upstream configuration
without those bad links needs no A/B writes. Keep this check concise and the
writes atomic in Odoo's transaction. Invalidate affected fiscal positions'
`tax_map` cache after replacement edits and verify the mapping in that environment.

Existing membership additions use `Command.link()` for missing positions.
Changing import price inclusion, if validated, uses a normal tax `write()`.
The maintenance docstring must state these named corrections as the narrow
exception to its ordinary policy of preserving existing accountant settings.

**Why both paths:** changing template data protects new companies but does not
remove bad relationships already stored by existing companies. The targeted ORM
repair fixes those existing records without reloading their complete chart.

## 4. Test-database checks and existing test documents

### Restore the missing domestic-position computation on the clone

Read-only inspection confirms `gec20_prod1` company 1 has
`domestic_fiscal_position_id = NULL`, despite its Georgian positions. Standard
sales/purchase taxes and the advance tax consequently have `is_domestic = false`.
This affects tax-picker availability independently of the nine wrong links.

On the clone, invoke the existing core
`company._compute_domestic_fiscal_position_id()` for the reviewed company, flush,
and verify the stored position and dependent tax flags/pickers. With the current
stock sequences, core should select Georgia (VAT Registered). This is a proposed
standard ORM recomputation, not a tested database correction. Keep sequence values
unchanged; changing and restoring a sequence only to trigger it is unnecessary.
The cause of the stale value is unproven. Check other companies individually;
this review verified `gec20_prod1`, not the reviewer's separate `gec20_prod` claim.

### Use existing documents as test examples

The nine-link repair preserves tax rates, accounts, invoice/refund repartition
lines, tags, and the tax records' fiscal-position membership. Automatic
fiscal-position detection continues. The current single export replacement is
outside these nine edits. Core tax calculation and posting remain responsible
for the resulting amounts and entries.

**Existing documents do not correct themselves.** A saved line already holds
its selected taxes; a posted move already holds its journal entries and tags.

| Existing test document | Validation step |
|---|---|
| Draft quotation/order | Select the intended taxes and compare totals after the configuration fix |
| Draft invoice/bill | Correct the selection and verify normal Odoo recalculation |
| Posted invoice/bill | Retain as a before-fix example and create a corrected test document; use native reset or reversal only when needed for a particular test |

The read-only audit found two posted customer invoices
(`INV/2026/00001`, `INV/2026/00002`), one posted vendor bill
(`BILL/2026/10/0002`), and draft/cancelled accounting candidates. It also found:

| Sales orders carrying the six taxes | Current state | Priority |
|---|---|---|
| S00001, S00005 | Draft | Examples for verifying corrected proposals |
| S00004 | Confirmed, still to invoice | Example proving saved taxes must be corrected before the next test invoice |
| S00002, S00006 | Already invoiced | Before-fix examples for comparing posting and reporting |

Order-to-invoice conversion copies the saved taxes, so an upgrade alone will not
change S00004's next test invoice. The expanded audit includes sales and purchase
orders. No production credit-note exercise or historical migration is required
by these findings. The configuration repair should still avoid silently rewriting
saved test documents, so its accounting effects can be compared reliably.

### Foreign-purchase procedure required with Change B

Inventory foreign vendor defaults before rollout. For confirmed services vendors,
the accountant sets the existing Default Purchase Tax to `18% R C S`; mixed
purchases still need per-line choices. These are reviewed configuration edits,
not automatic country-based partner updates.

For future production operations, before each monthly VAT filing, review posted Non-Georgia product lines with
no VAT classification. Audit query 8 lists untaxed lines and lines carrying only
withholding. Filter its accounting dates to the reporting period. Legitimately
untaxed transactions may appear; the list prompts classification review and does
not establish VAT liability. This plan adds neither a posting block nor a cron.

### Later scope: verify Georgian supplier VAT registration

Core's `vat_required` currently checks whether a Tax ID is present. It does not
verify Georgian VAT registration. For a supplier confirmed to be non-VAT,
the existing Default Purchase Tax can select the module's exempt purchase tax.
Review eligibility before claiming input VAT. Registry-backed selection through
`_get_vat_required_valid()` is a separate phase requiring a verified data source;
it must not silently replace the mandatory partner-default feature.

## 5. Implementation, testing, and first production deployment

1. On a disposable copy of the test database, run the expanded read-only audit and export the current
   relationships/settings. Resolve customized conflicts, validate the domestic
   position recomputation, confirm seller VAT scope for all ten Change C taxes,
   and establish vendor defaults and the monthly foreign-purchase review.
2. Implement the file changes above. Prioritize a fresh database with GEC installed
   and a new Georgian chart: this is the first-production setup path. Also test
   upgrading the existing test chart. Run the repair twice: the second run must make
   no further repair writes. Validate Change D separately before including it.
3. Validate an ordinary sale: 100 + 18 = 118, with standard sales tags. Validate
   each reverse-charge category separately: ±18 VAT and 100 payable. Validate
   every partner-default case in the table above through both orders and direct
   invoices/bills, preserving company-specific defaults, child-contact behavior,
   and withholding. Include ordinary, advance, special, and exempt selections
   under both other domestic positions, refunds, and the customs VAT-only scenario.
4. Compare the test copy before/after: only declared configuration changes should come
   from this repair. Existing test balances and stored report tags, rates,
   repartitions, defaults, and unrelated mappings must remain intact. Account
   separately for the module's pre-existing maintenance behavior.
5. Once validation passes, deploy the module for the first time, install it and
   configure the Georgian chart through the validated setup path. Verify mappings,
   tax availability, partner defaults, and sample transactions before real posting.
   Carry over reviewed configuration, not the erroneous test accounting documents.

Source inspection and the read-only database audit support this design. The
installation, upgrade, and accounting integration tests still need to pass
before deployment. When Odoo's patch arrives, compare its actual changes on a
clone and retire our conditional template repair once it is redundant; verify
existing database mappings independently.

As of 5 October 2026, the public [19.0 tax data](https://raw.githubusercontent.com/odoo/odoo/19.0/addons/l10n_ge/data/template/account.tax-ge.csv)
and [20.0 tax data](https://raw.githubusercontent.com/odoo/odoo/20.0/addons/l10n_ge/data/template/account.tax-ge.csv)
still contain the six/three replacements. This establishes their current source
state, not what a future hotfix or migration will do. The separate
[withholding PR #292088](https://github.com/odoo/odoo/pull/292088) is currently open
and draft. Compare its eventual implementation with GEC withholding separately;
it is not the VAT mapping fix.
