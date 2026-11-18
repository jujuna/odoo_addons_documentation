# Analytic Margin & Cost Allocation — Developer Notes

Module `gec_analytic_margin` · Odoo 20 Enterprise · version 20.0.1.21.0

User documentation: [README.md](README.md).

Depends on `account`, `account_budget`, `account_reports`, `project`,
`hr_timesheet`. No enterprise method is overridden; everything new lives in the
`gec.*` namespace or in added fields.

---

## Data flow

```
account.analytic.line  (invoices, bills, payroll, timesheets, allocation lines)
        │
        ├── classification ── gec.margin.classification.rule._component_sql
        │                      → component, function, revenue stream (labels only)
        │
        ├── allocation ─────── gec.allocation.run → contra + target analytic lines
        │                      gec.activity.rate per activity and run
        ▼
gec.margin.report  (SQL model: actual ∪ budget, exploded per analytic plan)
        │
        ├── Margin Statement   account.report + gec.margin.statement.report.handler
        ├── Margin Analysis    pivot / list / graph on gec.margin.report
        └── Dashboard          gec.margin.dashboard (+ _proof) → OWL client action
```

---

## Models

| Model | Kind | Purpose |
|---|---|---|
| `gec.margin.component` | stored | A P&L line; flags `allocatable`, `is_function`, `function_reclassify`, `cost_level` |
| `gec.margin.classification.rule` | stored | Account type / code prefix → component, per company |
| `gec.margin.level` | stored | A ladder rung; owns a report column |
| `gec.margin.level.mixin` | abstract | Models inheriting it get one column per level |
| `gec.revenue.stream` | stored | Kind of revenue; `recurring`, `standard_product` |
| `gec.activity` | stored | An activity and where its quantities are counted |
| `gec.activity.rate` | stored | Rate, units, pool, charged, idle, variance per activity and run |
| `gec.activity.plan` | stored | Planned driver units per activity and cost object |
| `gec.allocation.rule` | stored | Rule; `gec_allocation_rule_abc.py` adds the activity driver |
| `gec.allocation.rule.line` | stored | Manual percentages |
| `gec.allocation.run` | stored | Batch, generated lines, log; monthly cron in `data/gec_allocation_cron.xml` |
| `gec.margin.report` | SQL, `_auto = False` | Budget ∪ actual, exploded per plan |
| `gec.margin.statement.report` | SQL | Statement source, inherits `gec.margin.report` |
| `gec.margin.row` | database view | P&L ladder rows (components and levels in statement order) |
| `gec.margin.statement.report.handler` | abstract | `account.report.custom.handler` for the Margin Statement |
| `gec.margin.dashboard` | abstract | `get_dashboard_data`, drill-down actions |
| `gec.margin.dashboard` (proof) | abstract, `models/gec_margin_dashboard_proof.py` | `get_proof(key, …)` → `_gec_proof_<key>` |
| `gec.margin.dashboard` (delivery) | abstract, `models/gec_margin_dashboard_delivery.py` | Projects & Cash tab: milestones, go-live, end dates, templates, DSO, cash conversion, 13-week forecast, forecast accuracy, and their proofs |
| `gec.forecast.snapshot` | stored | Monthly revenue forecast frozen on the 1st (cron `ir_cron_gec_forecast_snapshot`); past months back-filled by `post_init_hook` as *reconstructed* |
| `gec.abc.health`, `gec.abc.health.check` | transient | Setup Health Check |
| `gec.allocation.preview(.line)` | transient | Dry run |
| `gec.activity.plan.wizard` | transient | Plan from Actuals |

**Extended:** `account.account` (component, revenue stream), `account.analytic.account`
(function, revenue stream, headcount), `account.analytic.plan` (statement reading),
`account.analytic.line` (allocation flags, activity), `account.analytic.distribution.model`,
`account.move.line`, `budget.line` (GL account), `project.project` (function, forecast,
backlog, cash; `models/project_delivery.py`: go-live dates, template link set in
`copy_data` under `copy_from_template`, forecast end date from an 8-week burn rate), `project.tags` (`gec_rework`), `hr.department` (function),
`res.company` (`gec_pl_mode`), `res.config.settings`.

---

## Key implementation points

**One source of truth for classification.** Resolution lives only in
`gec.margin.classification.rule._component_sql`. Python reads it through a
`Domain.custom(to_sql=…)` wrapper, so a filter and a report cannot disagree.
`account.account.code` is company-dependent, so prefix matching uses
`code_store` and matches every company's copy of an account.

**`gec.margin.report`** has no database view: `_table_sql` returns the query,
inlined as a subquery at read time (the `budget.report` mechanism).
`_component_join` resolves the component in two steps (GL, then function
reclassification when `res_company.gec_pl_mode = 'function'` and the
component has `function_reclassify`). Function order: project plan account →
activity (not on contra lines) → other plan accounts. Revenue stream: revenue
rows take analytic streams, then the GL stream; cost rows analytic streams only.
Synthetic ids are bigint.

**Generic columns.** `gec.margin.report` inherits `analytic.plan.fields.mixin`,
so a new plan adds a column. Levels create their own columns via
`gec.margin.level.mixin` with `ir.model.fields`. `post_init_hook` syncs both and
applies the classification rules.

**Margin Statement** uses the Odoo 20 report API: `AccountReportLineData` /
`AccountReportColumnData`, `_build_column_data`, expand functions with the
signature `(line_dict_id, groupby, options, unfold_all_batch_data=None,
limit_to_load=None)` returning a list, load-more lines. Filters *Before
Allocation* and *Ladder First* are added in `static/src/js/margin_statement_filters.js`.

**Currency conversion** (dashboard only). When `env.companies` have more than
one currency, `_gec_reporting_env()` sets context `gec_reporting_currency_id`;
`gec.margin.report._converted(amount, date)` multiplies by
rate(target) / rate(row currency) from `res_currency_rate`. Project computes use
`@api.depends_context('gec_reporting_currency_id')`.

**Project forecast** (`models/project_project.py`, non-stored computes):
backlog = max(contract − revenue, 0); overhead to come = backlog × allocated
non-hourly cost ÷ revenue; ETC = hours to go × rate + other cost + overhead;
percent complete = cost ÷ forecast cost (≤ 1); unbilled = contract × percent
complete − revenue; collected = reconciled part of invoices + registered
matched payments, capped at the invoice total.

**Cash figures** read accounting directly, company-wide. Odoo 20 can register a
payment without a journal entry (no outstanding account), leaving the invoice
*In Payment* with its full residual; `_gec_paid_by` therefore counts dated
reconciliations plus such payments, capped at the total. Operating cash = bank
(`asset_cash`) movements whose counterpart is not equity, long-term debt or fixed
assets, plus registered payments whose invoices are still *In Payment*.

**Allocation lines** are analytic lines only: one contra + *n* targets per
(tags × GL × month). Contra = sum of targets, not the pool, so capacity and
share remainders stay on the source. A pool ignores lines from its own step or
later (`gec_allocation_step`), which prevents double charging.

**Sign convention.** Revenue positive, cost negative, matching
`account.analytic.line.amount`. Budget amounts are signed from the component's
nature, falling back to `budget_type`.

---

## Dashboard front end

`static/src/dashboard/` — `dashboard.js`, `dashboard.xml`, `dashboard.scss`.
OWL 3 (Odoo 20): `useProps`, `t.*` validators, `proxy`, signals; charts with
`useChart` and `t-ref="this.chart.ref"`. Icons use the `oi` font with
`data-icon` (Font Awesome is not available in Odoo 20).

- `BENCHMARKS` in `dashboard.js` holds the benchmark ranges; Python's
  `HEADCOUNT_TARGETS` holds the headcount mix.
- Filters persist in `localStorage` key `gec_abc_dashboard` (wrapped in
  try/catch).
- *Whole company* is `plan_id = -1` (`COMPANY_WIDE`).
- Cards are `GecDashboardKpi` components; `proofed(card)` makes them open the
  proof panel, which calls `gec.margin.dashboard.get_proof`.
- Adding a card with a proof: add `_gec_proof_<key>(ctx)` returning title,
  formula, filled formula, parts (`_part`), benchmark, notes; the test
  `test_dashboard.py` checks every card key has a proof.

`--dev=reload` does **not** rebuild asset bundles: after editing JS/XML/SCSS,
touch a `.py` file or restart the container.

---

## Tests

244 tests under `tests/` (tagged `post_install`, `-at_install`). Run on a
throw-away database:

```bash
python odoo-bin -c /etc/odoo.conf -d gec_test --db_host <host> --db_user <user> \
  --db_password <pw> -i gec_analytic_margin --test-tags /gec_analytic_margin \
  --stop-after-init --http-port 8099
```

`static/tests/tours/dashboard_tour.js` needs Chrome in the container; without
it the tour test is skipped. Cron tests can fail if the server's own cron runs
at the same time — re-run.

---

## Translations

`i18n/ka_GE.po` holds the Georgian translation (1,029 terms, all translated).
After adding or changing user-facing strings, export a fresh template and merge:

```bash
python odoo-bin i18n export -c /etc/odoo.conf -d <db> -o /tmp/gam.pot gec_analytic_margin
msgmerge --update i18n/ka_GE.po /tmp/gam.pot     # then translate the new empty entries
```

Load into a database with `-u gec_analytic_margin` (or `i18n loadlang -l ka_GE`).
Glossary used: accounting terms follow the company's `gec_i18n_accounting` pack
(e.g. Analytic Item = ანალიტიკური ერთეული, Journal Item = ჟურნალის ერთეული).

## Upgrades

The module ships no migration scripts (removed in 20.0.1.21.0; see git
history). A database installed before 20.0.1.21.0 and then upgraded keeps
**Standard Product** unticked on the shipped streams: tick it by hand on
License, Maintenance & Support and Subscriptions, or product revenue % reads 0.
A database still on an early 19.0 version of this module needs the old scripts
back from git before it is upgraded.

**Upgrade notes.** `-u gec_analytic_margin` is needed after field changes.
Shipped margin levels are reset on update; revenue streams are `noupdate`.

**Removing ABC.** The ABC layer is `models/gec_activity.py`,
`models/gec_allocation_rule_abc.py` and `views/gec_activity_views.xml` (plus
rates and plans). The configurable P&L model does not depend on it.
