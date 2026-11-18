# Accounting Reports Engine

> **Module:** `account_reports` (enterprise) | **Path:** [enterprise/account_reports/](../enterprise/account_reports/)
> **Depends on:** `account_accountant`
> **Base models:** `account` module ([addons/account/models/account_report.py](../addons/account/models/account_report.py))
> **Odoo version:** 20.0 — see [What Changed in Odoo 20](#what-changed-in-odoo-20) if you know the 19 engine.

---

## What It Does

The reporting engine is a **data-driven framework** for financial statements. Every report — Balance Sheet, P&L, Trial Balance, Tax Return, General Ledger, etc. — is a set of database records, not hardcoded Python. You define what lines to show and how to compute each value; the engine runs SQL and assembles the result.

**Core idea:**
- A report is `account.report` + its `account.report.line` rows
- Each row has `account.report.expression` records — one per column
- Each expression has an `engine` field that determines how its value is computed
- 8 engines exist (6 in Odoo 19 + `text` and `reference`), most running against `account.move.line`
- The result is an interactive screen view with drill-down, filters, PDF/XLSX export, comparison columns

---

## Dependencies

| Module | Why |
|---|---|
| `account_accountant` | Full accounting — posted entries, fiscal years |
| `account` | Base models: `account.report`, `account.report.line`, `account.report.expression` |

**Consumers:**

| Consumer | What it uses |
|---|---|
| `l10n_*` | Localized tax report variants via `root_report_id` + `country_id` |
| `account_reports_cash_basis` | `only_tax_exigible` filter |
| `account_budget` | `filter_budgets` on P&L |
| `account_asset` | asset/depreciation ledger reports and the `horizontal_group_ledger` grouping |

---

## Architecture: Three-Layer Model

```
account.report
    └── account.report.line          (one row, e.g. "Current Assets")
            └── account.report.expression   (one cell value per column)
                    engine     = domain | tax_tags | aggregation | account_codes
                               | external | custom | text | reference
                    formula    = what to compute (syntax depends on engine)   [Text]
                    subformula = modifier on the result                       [Text]
                    date_scope = time window for the SQL
```

`formula` and `subformula` were `Char` in Odoo 19 and are `Text` in Odoo 20, so multi-line aggregation formulas are now possible.
Source: [account_report.py:686](../addons/account/models/account_report.py#L686)

Every number on a financial report comes from an `account.report.expression` evaluated by its engine against `account.move.line`.

---

## Core Models

### `account.report` — The Report Definition

> [addons/account/models/account_report.py](../addons/account/models/account_report.py)
> Extended by [enterprise/account_reports/models/account_report.py](../enterprise/account_reports/models/account_report.py)

| Field | Type | Purpose |
|---|---|---|
| `name` | `Char` | Report name in UI and menus |
| `line_ids` | `One2many → account.report.line` | All rows of this report |
| `column_ids` | `One2many → account.report.column` | Column headers — each must match an expression `label` |
| `root_report_id` | `Many2one → account.report` | Points to the generic root; this record is a **variant** |
| `variant_report_ids` | `One2many` | All country/COA-specific variants of this report |
| `section_report_ids` | `Many2many` | Sub-reports for **composite** reports |
| `use_sections` | `Boolean` (computed) | True if this is a composite report |
| `country_id` | `Many2one → res.country` | Restricts report to one country |
| `chart_template` | `Selection` | Restricts report to one Chart of Accounts |
| `availability_condition` | `Selection` | When this report appears: `always`, `country`, `coa` |
| `custom_handler_model_id` | `Many2one → ir.model` | Model inheriting `account.report.custom.handler` |
| `default_opening_date_filter` | `Selection` | Default date range when report opens |
| `groupby` / `user_groupby` | `Char` | Report-wide default groupby for its lines (new in Odoo 20); `user_groupby` is the editable copy |
| `currency_translation` | `Selection` | `current` (latest rate at report date) or `cta` (per-account-type rates) — see [Currency Handling](#currency-handling) |
| `enable_snapshots` | `Boolean` | Allows engine results for closed periods to be cached as `account.report.snapshot` records |
| `use_fiscal_periods` | `Boolean` | Drive the date filter by fiscal periods rather than calendar ranges |

**Filter fields** — each adds a filter widget in the UI:
`filter_date_range`, `filter_journals`, `filter_partner`, `filter_hierarchy`, `filter_account_type`,
`filter_period_comparison`, `filter_growth_comparison`, `filter_line_comparison`, `filter_hide_0_lines`,
`filter_unreconciled`, `filter_show_draft`, `filter_aml_ir_filters`, `filter_budgets`, `filter_multi_company`.

Odoo 20 changes on this model:

| Field | Change |
|---|---|
| `filter_analytic` | removed — the analytic filter is now `filter_analytic_groupby`, declared in [account_analytic_report.py:14](../enterprise/account_reports/models/account_analytic_report.py#L14) |
| `prefix_groups_threshold` | removed, together with `_init_options_prefix_groups_threshold` |
| `filter_line_comparison`, `enable_snapshots`, `use_fiscal_periods`, `currency_translation`, `groupby`, `user_groupby` | added |
| `load_more_limit` | default is now 500 (was unset) |
| `active` | now computed from `active_fallback` / `active_selection` instead of a plain boolean |

---

### `account.report.line` — A Report Row

> [addons/account/models/account_report.py:405](../addons/account/models/account_report.py#L405)

| Field | Type | Purpose |
|---|---|---|
| `name` | `Char` | Row label |
| `code` | `Char` | Unique ID used in aggregation formulas (e.g., `CA`, `REV`) |
| `parent_id` | `Many2one` | Parent line for hierarchy |
| `children_ids` | `One2many` | Child lines |
| `expression_ids` | `One2many` | One expression per column |
| `groupby` / `user_groupby` | `Char` | Comma-separated `account.move.line` fields — expands row into sublines. `user_groupby` is the editable override; `groupby` is the definition default |
| `hierarchy_level` | `Integer` (computed) | Indentation depth; root = 1 |
| `foldability` | `Selection` (computed, editable) | `always_unfolded` / `never_unfolded` / `foldable`. **Replaces the `foldable` boolean of Odoo 19** |
| `hide_if_zero` | `Boolean` | Hidden when all columns are 0 |
| `horizontal_split_side` | `Selection` | `left`/`right` — side-by-side Balance Sheet layout |
| `print_on_new_page` | `Boolean` | Start a new PDF page at this line |
| `action_id` | `Many2one → ir.actions.actions` | Turns the line into a link executing that action |
| `sequence` | `Integer` | Display order |

**Shortcut write-only fields** (auto-create `expression_ids`):
- `domain_formula` → creates a `domain` engine expression
- `account_codes_formula` → creates an `account_codes` engine expression
- `aggregation_formula` → creates an `aggregation` engine expression
- `tax_tags_formula` → creates a `tax_tags` engine expression

---

### `account.report.expression` — One Cell Value

> [addons/account/models/account_report.py:664](../addons/account/models/account_report.py#L664)

| Field | Type | Purpose |
|---|---|---|
| `label` | `Char` | Matches `account.report.column.expression_label` (e.g., `balance`) |
| `engine` | `Selection` | Which computation engine (see below) |
| `formula` | `Char` | What to compute — syntax depends on engine |
| `subformula` | `Char` | Modifier on the result (e.g., `sum`, `-sum`) |
| `date_scope` | `Selection` | Time window for the SQL query |
| `figure_type` | `Selection` | `monetary`, `percentage`, `integer`, `float`, `date`, `string` |
| `green_on_positive` | `Boolean` | Color: green when positive |
| `blank_if_zero` | `Boolean` | Show blank instead of 0 |
| `auditable` | `Boolean` (computed) | Clicking opens journal line drill-down |
| `carryover_target` | `Char` | `line_code.expr_label` — where to carry this value in next period |
| `model_id` | `Many2one → ir.model` | New in Odoo 20 — the model the `reference` engine resolves against |

Two database constraints worth knowing:

- `_domain_engine_subformula_required` — a `domain` expression must have a subformula
- `_line_label_uniq` — one label per report line

Source: [account_report.py:719](../addons/account/models/account_report.py#L719)

---

### `account.report.external.value` — Stored Manual Values

> [addons/account/models/account_report.py:1059](../addons/account/models/account_report.py#L1059)

Used by the `external` engine. Each record is one manually entered (or carried-over) value for one expression.

| Field | Type | Purpose |
|---|---|---|
| `value` | `Float` | Numeric value |
| `text_value` | `Char` | Text value (for `string` figure types) |
| `date` | `Date` | Date of this value |
| `target_report_expression_id` | `Many2one → account.report.expression` | Which expression receives this |
| `company_id` | `Many2one → res.company` | Company context |
| `carryover_origin_expression_label` | `Char` | Source expression label (carryover only) |
| `carryover_origin_report_line_id` | `Many2one → account.report.line` | Source line (carryover only) |

---

## The 8 Computation Engines

**Renamed in Odoo 20.** Engine methods went from `_compute_formula_batch_with_engine_<engine>` to `_report_engine_<engine>`, and dispatch now goes through `_get_custom_report_function`, which also resolves custom engines declared on a handler:

```python
# enterprise/account_reports/models/account_report.py:4376
engine_function = self._get_custom_report_function(self._get_engine_function_name(engine), 'engine')
return engine_function(column_group_options, date_scope, formulas_dict, current_groupby, warnings=warnings)

def _get_engine_function_name(self, engine):
    # standard engine -> '_report_engine_<engine>'; custom engine -> the formula itself
    ...
```

Source: [`_compute_formula_batch() — account_report.py:4345`](../enterprise/account_reports/models/account_report.py#L4345), [`_get_engine_function_name() — account_report.py:4379`](../enterprise/account_reports/models/account_report.py#L4379)

The engine signature also lost `next_groupby`, `offset` and `limit`; batching by `next_groupby` is gone.

| Engine | Method | Added in |
|---|---|---|
| `domain` | `_report_engine_domain` | — |
| `tax_tags` | `_report_engine_tax_tags` | — |
| `aggregation` | resolved in `_compute_expression_totals_for_single_column_group` | — |
| `account_codes` | `_report_engine_account_codes` | — |
| `external` | `_report_engine_external` | — |
| `custom` | the formula names the method | — |
| `text` | `_report_engine_text` | **Odoo 20** |
| `reference` | `_report_engine_reference` | **Odoo 20** |

Source: [`engine` selection — account_report.py:672](../addons/account/models/account_report.py#L672)

---

### Engine 1: `domain` — Odoo Domain Filter

> [`_report_engine_domain() — account_report.py:4464`](../enterprise/account_reports/models/account_report.py#L4464)

Filters `account.move.line` by an Odoo domain, then aggregates the `balance` column.

**Formula:** A Python list — a valid Odoo domain on `account.move.line`.

**Subformulas (Odoo 20 — only two remain):**

| Subformula | Result |
|---|---|
| `sum` | Sum of all matching line balances |
| `-sum` | Negated sum — income accounts have credit-normal (negative) balances; negate to show positive revenue |

`sum_if_pos`, `sum_if_neg` and `count_rows` were **removed in Odoo 20**. If a localized report still declares one, it will not resolve. Replace `sum_if_pos` / `sum_if_neg` with an `aggregation` expression carrying an `if_above(...)` / `if_below(...)` bound; `count_rows` has no replacement.

**SQL generated (simplified):**
```sql
SELECT COALESCE(SUM(consolidation_balance), 0.0) AS sum,
       COUNT(1) > 0                              AS has_sublines
FROM   account_move_line
WHERE  <date_scope_filter>
  AND  <company_filter>
  AND  <journal_filter>
  AND  <domain_filter>
GROUP BY <current_groupby_field>   -- only when line has groupby
```

`consolidation_balance` is `balance * consolidation_rate`, a computed-SQL field on `account.move.line`. It replaced the Odoo 19 `currency_table` JOIN — see [Currency Handling](#currency-handling).

**Batching:** when every leaf of a domain walks the same many2one field (e.g. all terms start with `account_id.`), Odoo resolves that comodel once and groups all such formulas into a single query. Domains touching several root fields fall back to one query each.

**Real examples:**
```xml
<!-- P&L Revenue: income accounts have negative balance, negate to show positive -->
<field name="formula" eval="[('account_id.account_type', '=', 'income')]"/>
<field name="subformula">-sum</field>

<!-- Balance Sheet Receivables: filter by type AND exclude non-trade -->
<field name="formula" eval="[('account_id.account_type', '=', 'asset_receivable'), ('account_id.non_trade', '=', False)]"/>
<field name="subformula">sum</field>
```

---

### Engine 2: `tax_tags` — Tax Tag Matching

> [`_report_engine_tax_tags() — account_report.py:4392`](../enterprise/account_reports/models/account_report.py#L4392)

Matches `account.move.line` records carrying a specific `account.account.tag`. The tag is **auto-created** when the expression is saved — its name equals the formula string.

**Formula:** A tag name string, optionally prefixed with `-` to negate.

**No subformulas** for this engine.

**When to use:** Tax returns. Each box on a VAT declaration maps to a tag. Configure a tax's repartition lines with that tag → every journal entry from that tax carries the tag → the report sums those balances.

```xml
<field name="engine">tax_tags</field>
<field name="formula">base_20</field>
```

**Tag creation:** When `engine = 'tax_tags'` is saved, `_create_tax_tags()` creates an `account.account.tag` with `applicability = 'taxes'` scoped to the report's country.
Source: [`_create_tax_tags() — account_report.py:805`](../addons/account/models/account_report.py#L805)

---

### Engine 3: `aggregation` — Formula Over Other Lines

> Handled in [`_compute_expression_totals_for_single_column_group() — account_report.py:3773`](../enterprise/account_reports/models/account_report.py#L3773)

Combines values of other report lines using arithmetic. References lines by their `code` field. **Runs last** — after all other engines.

**Formula syntax:**
```
CA.balance + FA.balance + PNCA.balance    ← sum line codes
REV.balance - COS.balance                 ← subtraction
sum_children                              ← sum all direct child lines
```

**Subformulas for aggregation:**

| Subformula | Effect |
|---|---|
| `if_above(CUR(x))` | Result is blank unless it is strictly above `x` |
| `if_below(CUR(x))` | Result is blank unless it is strictly below `x` |
| `if_between(CUR(x), CUR(y))` | Result is blank unless it lies between `x` and `y` |
| `round(n[, method])` | Round to `n` decimals; `method` is `HALF-UP`/`HALF-DOWN`/`HALF-EVEN`/`UP`/`DOWN` (default `HALF-DOWN`). `n` may be negative |
| `cross_report(report[, force_date_scope])` | Reference a line from a **different** report; `force_date_scope` makes the referenced expression use this expression's `date_scope` |
| `ignore_zero_division` | Return 0 instead of raising when a denominator is 0 |

`CUR` is a 3-letter currency code; the bound is converted to company currency at `date_to` before comparison.
Source: [`_aggregation_apply_bounds() — account_report.py:4244`](../enterprise/account_reports/models/account_report.py#L4244)

There is no `force_between` — the correct name is `if_between`, and it blanks the value rather than clamping it. Bounds are **not applied when a groupby is being expanded**; `round` still is.

`cross_report` is used extensively in the Executive Summary to pull values from P&L without duplicating logic. Its `force_date_scope` argument is new in Odoo 20.
Source: [`CROSS_REPORT_REGEX — account_report.py:25`](../addons/account/models/account_report.py#L25)

**Real example — Balance Sheet total assets:**
```xml
<field name="code">TA</field>
<field name="aggregation_formula">CA.balance + FA.balance + PNCA.balance</field>
```

**Key rule:** Aggregation lines do NOT run SQL. They wait for all referenced lines to complete. Circular references raise a computation error.

---

### Engine 4: `account_codes` — Account Code Prefix Matching

> [`_report_engine_account_codes() — account_report.py:4575`](../enterprise/account_reports/models/account_report.py#L4575), parsing in [`_parse_account_code_engine_formulas() — account_report.py:4722`](../enterprise/account_reports/models/account_report.py#L4722)

Sums balances of all accounts whose **code starts with** a given prefix. Useful for COA-based reports organized by code ranges (common in European localizations).

**Formula syntax:**

| Syntax | Meaning |
|---|---|
| `400` | Sum all accounts starting with `400` |
| `400 - 500` | 400-range minus 500-range |
| `104\(1041)` | All 104* accounts except those starting with 1041 |
| `123D` | Balance of 123* accounts, **only if positive** (Debit side) |
| `416C` | Balance of 416* accounts, **only if negative** (Credit side) |
| `tag(xmlid)` | Accounts carrying that `account.account.tag` |
| `+` / `-` | Add or subtract prefix ranges |

**How it works internally:**
1. Loads all accounts for the company sorted by code (falling back to another company's code for accounts with no code in the active company)
2. Uses `bisect_left` for fast binary prefix matching
3. Runs one aggregated SQL query to sum balances

The formula grammar itself is unchanged from Odoo 19.
Source: [`ACCOUNT_CODES_ENGINE_TERM_REGEX — account_report.py:28`](../addons/account/models/account_report.py#L28)

---

### Engine 5: `external` — Manually Entered Value

> [`_report_engine_external() — account_report.py:4791`](../enterprise/account_reports/models/account_report.py#L4791)

The value is NOT computed from journal lines. It is either entered by the user directly in the report cell, or it is a value carried forward from a previous period.

**Formula values:**

| Formula | Meaning |
|---|---|
| `most_recent` | The most recently saved `account.report.external.value` for this expression |
| `sum` | Sum of all saved values within the date range |

**Subformula `editable`:** Marks the cell as user-editable in the UI (pencil icon appears).

**When to use:**
- Opening balance overrides
- Statistical data inputs
- Tax return carryover amounts (amounts from previous period)

---

### Engine 6: `custom` — Python Method

Calls a Python method on the report's `custom_handler_model`. The formula IS the method name. The report must have `custom_handler_model_id` pointing to a model that inherits `account.report.custom.handler`.

`_get_engine_function_name()` returns the formula unchanged for `custom`, and `_get_custom_report_function` resolves it on the handler (or on the root report's handler).
Source: [`_get_engine_function_name() — account_report.py:4379`](../enterprise/account_reports/models/account_report.py#L4379)

**Formula:** Method name on the handler model.

**Real examples:**

| Report | Formula | What it does |
|---|---|---|
| General Ledger | `_report_custom_engine_general_ledger` | Running balance — each line = previous balance + debit − credit |
| Trial Balance | `_report_custom_engine_trial_balance` | Debit/credit totals per account + opening balance |
| Executive Summary | `_report_custom_engine_executive_summary_ndays` | Number of days in selected period |

**Use when:** Standard engines can't express the computation — running totals, special period logic, opening balance accumulation.

> If `engine = 'custom'` but `custom_handler_model_id` is not set, resolution falls through to `account.report` itself, which does not define the method, and the render fails.

---

### Engine 7: `text` — Literal String (new in Odoo 20)

> [`_report_engine_text() — account_report.py:4384`](../enterprise/account_reports/models/account_report.py#L4384)

Returns the formula itself as the cell value. No SQL, no groupby support (it returns `[]` when a groupby is being expanded). Use it for static labels in a column — e.g. a fixed reference code next to a computed amount in a statutory report — instead of inventing a custom handler.

---

### Engine 8: `reference` — Record Reference (new in Odoo 20)

> [`_report_engine_reference() — account_report.py:4864`](../enterprise/account_reports/models/account_report.py#L4864)

Delegates to `_report_engine_external`, but the expression carries a `model_id`, so the stored value is interpreted as a reference to a record of that model rather than a number or free text. Used for report cells where the user picks a record (a partner, an account, a tax) and the choice is persisted as an `account.report.external.value`.

---

## Date Scope

Every expression has a `date_scope` controlling which `account.move.line` records are included.

| `date_scope` | Meaning | Used for |
|---|---|---|
| `strict_range` | Only lines within `date_from`..`date_to` | P&L, Tax Report — period-specific |
| `from_beginning` | All lines from beginning of time up to `date_to` | Balance Sheet — balances carry forever |
| `from_fiscalyear` | Lines from fiscal year start to `date_to` | YTD reports |
| `to_beginning_of_fiscalyear` | Lines before fiscal year start | Opening balance at year start |
| `to_beginning_of_period` | Lines before `date_from` | Running/opening balance of the current period |
| `previous_return_period` | Lines from the previous tax return period | Carryover in tax reports |

`_get_options_date_domain()` translates `date_scope` + current options into a domain leaf on `date`.
Source: [`_get_options_date_domain() — account_report.py:1216`](../enterprise/account_reports/models/account_report.py#L1216)

---

## Rendering Pipeline: `_get_lines()` to Screen

Full call chain for one report render:

> Entry: [`_get_lines() — account_report.py:2924`](../enterprise/account_reports/models/account_report.py#L2924)

| Step | Method | What it does |
|---|---|---|
| 1 | `_get_lines()` | Entry point — flush DB, generate common warnings, call compute |
| 2 | `_compute_expression_totals_for_each_column_group()` | For each column group (comparison period), compute all expression values |
| 3 | `_compute_expression_totals_for_single_column_group()` | Groups expressions by engine + date_scope, batch-computes, resolves aggregations last |
| 4 | `_compute_formula_batch()` | Dispatches to `_report_engine_<engine>` via `_get_custom_report_function` |
| 5 | `_get_dynamic_lines()` | Calls `_dynamic_lines_generator()` on the custom handler (for dynamic-only reports like Cash Flow) |
| 6 | `_get_static_line_dict()` | Builds an `AccountReportLineData` object for each static line |
| 7 | `_build_static_line_columns()` | For each column, looks up computed expression value from step 3 |
| 8 | `_build_column_data()` | Formats one column value — handles carryover, info popup, edit popup. **Renamed from `_build_column_dict()` in Odoo 20** |
| 9 | `_create_hierarchy()` | Re-aggregates account lines using `account.account.parent_id` (if hierarchy enabled) |
| 10 | `_cleanup_empty_sections()` | Drops sections left with no visible children |
| 11 | `_add_totals_below_sections()` | Inserts section total rows |
| 12 | `_fully_unfold_lines_if_needed()` | Expands groupby lines recursively (for "unfold all") |
| 13 | `_add_account_status_on_lines()` | Attaches audit-cycle status per account (new in Odoo 20) |
| 14 | `_inject_account_names_for_consolidation()` | Adds account names when several companies are consolidated |
| 15 | `_custom_line_postprocessor()` | Custom handler hook — last chance to modify the line list |
| 16 | `_customize_warnings()` | Custom handler hook — add report-specific warnings |
| 17 | `_format_column_values()` | Format all numeric values for display (monetary, percentage, etc.) |
| 18 | `_update_line_comparison_data()` | Fill the line-comparison column (`filter_line_comparison`) |
| 19 | `_postprocess_chatter_for_annotations()` | Attach annotation/chatter data (skipped for file exports) |

**Lines are objects, not dicts (new in Odoo 20).** The render pipeline passes `AccountReportLineData` / `AccountReportColumnData` dataclasses instead of plain dicts. They are `slots`-based for speed; `__getitem__` and `__setitem__` still work but log a warning telling you to access the attribute directly. Use `.as_dict()` / `.from_dict()` at the boundaries.
Source: [account_reports/utils/report_data_objects.py](../enterprise/account_reports/utils/report_data_objects.py)

**Expression batching:**

All expressions with the same `(engine, date_scope, current_groupby)` are computed in a single SQL call. This is the primary performance optimization — one call per engine/scope combination per column group, not one call per expression. Odoo 19's extra `next_groupby` dimension is gone.

**Snapshots (new in Odoo 20).** When a report has `enable_snapshots = True`, engines decorated with `@snapshotable_engine` first look for `account.report.snapshot` records covering the requested period and company. Full coverage means the engine is never called; partial coverage means the engine is called only for the gap after the snapshot date, and the two results are merged by the decorator's `result_aggregators`. Snapshots are intended for locked periods, and warnings produced inside a snapshotted range are lost.
Source: [`snapshotable_engine() — account_report_snapshot.py:14`](../enterprise/account_reports/models/account_report_snapshot.py#L14)

---

## Options System

`get_options(previous_options)` builds the complete options dict used for every render, export, and drill-down.

Source: [`get_options() — account_report.py:2287`](../enterprise/account_reports/models/account_report.py#L2287)

### Rerouting to Variants

The initialization sequence is split at `_init_options_report_id` (sequence 17). After that initializer runs, if the resolved `report_id` differs from `self.id` (because a localized variant or section was found), `get_options` is called again on the resolved report, carrying `selected_variant_id`, `selected_section_id`, `variants_source_id` and `sections_source_id` forward. This is how French companies automatically see the French TVA report instead of the generic tax report.

### `_init_options_*` Execution Order

Source: [`_get_options_initializers_forced_sequence_map() — account_report.py:2390`](../enterprise/account_reports/models/account_report.py#L2390)

| Sequence | Method | Purpose |
|---|---|---|
| 10 | `_init_options_companies` | Select companies to report on |
| 15 | `_init_options_variants` | Select report variant |
| 16 | `_init_options_sections` | Select report sections (composite reports) |
| 17 | `_init_options_report_id` | Set the actual report — variant reroute happens here |
| 29 | `_init_options_return_periodicity` | Tax return period (monthly / quarterly) |
| 30 | `_init_options_filter_date` | Build the available date-filter choices (**new in Odoo 20**) |
| 31 | `_init_options_date` | Resolve the selected date range |
| 40 | `_init_options_horizontal_groups` | Horizontal groupby columns |
| 50 | `_init_options_comparison` | Build comparison columns |
| 60 | `_init_options_export_mode` | Export mode flag |
| 70 | `_init_options_integer_rounding` | Rounding method |
| 75 | `_init_options_consolidation` | Multi-company consolidation toggle |
| 80 | `_init_options_journals` | Journal filter |
| 90 | `_init_options_journals_names` | Journal filter labels |
| 100 | `_init_options_audit` | Audit-cycle options |
| 200 | (all others) | Analytic, partner, budgets, buttons, hide_0, user groups, etc. |
| 990 | `_init_options_column_headers` | Column header labels |
| 1000 | `_init_options_columns` | Column structure — depends on dates and comparison |
| 1010 | `_init_options_column_percent_comparison` | Growth/budget comparison columns |
| 1020 | `_init_options_order_column` | Sort column |
| 1030 | `_init_options_hierarchy` | Hierarchy expand/collapse state |
| 1050 | `_init_options_custom` | Custom handler options |
| 1060 | `_init_options_section_buttons` | Buttons contributed by composite sections (**new in Odoo 20**) |
| 1070 | `_init_options_readonly_query` | Marks the query as readonly-safe (**new in Odoo 20**) |
| 1500 | `_init_options_filters` | Final filter aggregation |

Removed in Odoo 20: `_init_options_currency_table` (1055) and `_init_options_prefix_groups_threshold` (1040).

### Key `options` keys

```python
options = {
    'report_id': 42,
    'date': {'date_from': '2025-01-01', 'date_to': '2025-12-31', 'filter': 'this_year'},
    'comparison': {'periods': [...], 'number_period': 1, 'filter': 'previous_year'},
    'column_groups': {
        'column_group_0': {'forced_options': {'date': {...}}, 'forced_domain': [], ...},
        'column_group_1': {'forced_options': {'date': {...}}, ...},
    },
    'journals': [{'id': 1, 'name': 'Sales', 'selected': True}, ...],
    'companies': [{'id': 1, 'name': 'My Company'}],
    'hierarchy': True,
    'unfold_all': False,
    'unfolded_lines': [...],
    'buttons': [...],
}
```

Each entry in `column_groups` represents one column in the report (main period + each comparison period). The engine computes each expression once per column group.

---

## Custom Handler Interface

A custom handler is an `AbstractModel` inheriting `account.report.custom.handler` linked to a report via `custom_handler_model_id`.

Source: [`account.report.custom.handler` — account_report.py:8494](../enterprise/account_reports/models/account_report.py#L8494)

### All Overridable Methods

| Method | Signature | When to use |
|---|---|---|
| `_dynamic_lines_generator()` | `(report, options, all_column_groups_expression_totals, warnings=None)` | Generate dynamic lines not defined in the report's `line_ids` (e.g., one line per journal entry) |
| `_caret_options_initializer()` | `()` | Define right-click context menu items per model type |
| `_custom_options_initializer()` | `(report, options, previous_options)` | Add report-specific filters or option sections |
| `_custom_line_postprocessor()` | `(report, options, lines)` | Modify the rendered line list before display — inject rows, rename, reorder |
| `_custom_groupby_line_completer()` | `(report, options, line_data, current_groupby)` | Customize a groupby-expanded line's data (parameter renamed from `line_dict` in Odoo 20 — it is an `AccountReportLineData` now) |
| `_custom_unfold_all_batch_data_generator()` | `(report, options, lines_to_expand_by_function)` | Precompute data for "unfold all" to avoid N+1 queries |
| `_get_custom_groupby_map()` | `()` | Define custom groupby fields beyond `account.move.line` fields |
| `_customize_warnings()` | `(report, options, all_column_groups_expression_totals, warnings)` | Add report-specific warning messages |

A handler may also declare **custom engines** as `_report_engine_<name>` methods; `_get_custom_report_function(name, 'engine')` resolves them, and they can be wrapped with `@snapshotable_engine` if their results are composable by company and date.

**`_dynamic_lines_generator()` return format:**
```python
return [(sequence, line_data), ...]
# sequence:  integer for ordering relative to static lines
# line_data: an AccountReportLineData object (a plain dict still works via from_dict at the boundary)
```

**`_caret_options_initializer()` return format:**
```python
return {
    'account.account': [
        {'name': _("General Ledger"), 'action': 'caret_option_open_general_ledger'},
    ],
    'account.move.line': [
        {'name': _("View Journal Entry"), 'action': 'caret_option_open_record_form', 'action_param': 'move_id'},
    ],
}
# key: model name on the line's 'caret_options' key
# action: method name to call on the report/handler when clicked
```

---

## Caret Options (Right-Click Menu)

Caret options are context menu items that appear when clicking the arrow next to a line value.

**Default options** (all reports unless overridden):
Source: [`_caret_options_initializer_default() — account_report.py:2755`](../enterprise/account_reports/models/account_report.py#L2755)

```python
{
    'account.account':        [{'name': "General Ledger", 'action': 'caret_option_open_general_ledger'}],
    'account.move':           [{'name': "View Journal Entry", 'action': 'caret_option_open_record_form'}],
    'account.move.line':      [{'name': "View Journal Entry", 'action': 'caret_option_open_record_form', 'action_param': 'move_id'}],
    'account.payment':        [{'name': "View Payment", 'action': 'caret_option_open_record_form', 'action_param': 'payment_id'}],
    'account.bank.statement': [{'name': "View Bank Statement", 'action': 'caret_option_open_statement_line_reco_widget'}],
    'res.partner':            [{'name': "View Partner", 'action': 'caret_option_open_record_form'}],
}
```

**Trial Balance** adds "Journal Items" alongside "General Ledger", plus a second entry set for its `undistributed_profits_losses` pseudo-model:
Source: [`_caret_options_initializer() — account_trial_balance_report.py:194`](../enterprise/account_reports/models/account_trial_balance_report.py#L194)

**General Ledger** overrides for its custom `id_with_accumulated_balance` groupby key:
Source: [`account_general_ledger.py:51`](../enterprise/account_reports/models/account_general_ledger.py#L51)

**How dispatch works:**
1. Each rendered line carries a `caret_options` key identifying which model it represents
2. `_caret_options_initializer()` maps model → actions
3. When user clicks, `dispatch_report_action()` calls the action method on the handler

---

## Carryover Logic (Tax Reports)

Carryover allows an expression value from one period to be automatically applied to a target expression in the next period (e.g., tax credit from Q3 carried to Q4).

**Naming convention:**
- Source expression label must start with `_carryover_` (e.g., `_carryover_credit`)
- Target expression label must start with `_applied_carryover_` (e.g., `_applied_carryover_credit`)

**`carryover_target` field:**
```python
# addons/account/models/account_report.py:713
carryover_target = fields.Char(
    string="Carry Over To",
    help="Formula in the form line_code.expression_label. This allows setting the target of the carryover for this "
         "expression (on a _carryover_*-labeled expression), in case it is different from the parent line."
)
```

Two constraints enforce the naming convention at write time, so a mismatch raises immediately rather than silently at period close:

- `carryover_target` on an expression whose label does not start with `_carryover_` → error
- a `carryover_target` pointing at a label that does not start with `_applied_carryover_` → error

Source: [`_check_carryover_target() — account_report.py:729`](../addons/account/models/account_report.py#L729)

If `carryover_target` is not set, the framework auto-resolves the target by stripping the `_carryover_` prefix and finding a matching `_applied_carryover_*` expression on the same line.

**Storage:** Carryover values are written as `account.report.external.value` records with `carryover_origin_expression_label` and `carryover_origin_report_line_id` set.

**Generation:** `_generate_carryover_external_values()` is called when a tax period is closed. It computes `_carryover_*` expressions and creates the corresponding `account.report.external.value` records targeting `_applied_carryover_*` expressions on the next period.

---

## Groupby: Expanding Lines to Sublines

When `account.report.line.groupby` is set, the engine splits results by that field.

**How it works:**
1. Engine receives `current_groupby = 'account_id'`
2. SQL adds `GROUP BY account_move_line.account_id`
3. Returns `[(grouping_key, {result_dict}), ...]` instead of a single dict
4. Each grouping key becomes a new child row in the UI

**Multi-level groupby:** `groupby = 'partner_id, account_id'`
- First render: grouped by `partner_id` (collapsed rows)
- Expand a partner: triggers new API call with `current_groupby = 'account_id'`

**`foldability`:**

| Value | Behaviour |
|---|---|
| `foldable` | line shows a toggle and starts collapsed; clicking it triggers a new API call with `current_groupby` set |
| `always_unfolded` | children are rendered expanded, no toggle |
| `never_unfolded` | line cannot be expanded at all |

The default is computed: a line with children → `always_unfolded`; a line with a groupby and no `aggregation`/`external` expression → `foldable`; a line whose expressions are `aggregation` or `external` → `never_unfolded`.
Source: [`_compute_foldability() — account_report.py:490`](../addons/account/models/account_report.py#L490)

---

## Hierarchy Filter (Account Parents)

**Rewritten in Odoo 20.** The `account.group` model no longer exists. The chart of accounts is a tree on `account.account` itself (`parent_id` / `parent_path`, `_parent_store`), and the report hierarchy walks that tree.

When `filter_hierarchy = 'by_default'` or `'optional'` and enabled:
- Account-level lines are re-aggregated under their `parent_id` chain
- Each parent row shows the sum of its descendant accounts
- The filter is only offered when at least one account in the selected companies actually has a parent

```python
# _init_options_hierarchy
if self.filter_hierarchy != 'never' and self.env['account.account'].search_count(
        Domain.AND([
            self.env['account.account']._check_company_domain(company_ids),
            Domain('parent_id', '!=', False),
        ]), limit=1):
    options['display_hierarchy_filter'] = True
```

Source: [`_init_options_hierarchy() — account_report.py:1415`](../enterprise/account_reports/models/account_report.py#L1415), [`_create_hierarchy() — account_report.py:1434`](../enterprise/account_reports/models/account_report.py#L1434)

| | Odoo 19 | Odoo 20 |
|---|---|---|
| Grouping source | `account.group` records with `code_prefix_start`/`code_prefix_end` | `account.account.parent_id` |
| Filter availability | groups exist for the company | at least one account has a parent |
| Migration impact | — | `account.group` data is gone; a chart with no `parent_id` set shows no hierarchy filter at all |

Still distinct from the `account.root` virtual model used in the COA list view search panel — that is derived from the first two characters of the code, not from the parent tree.

---

## Report Variants and Localization

`root_report_id` connects generic reports to localized versions.

```
account.report (root)
    name                = "Generic Tax Report"
    root_report_id      = None
    country_id          = None

account.report (variant — France)
    name                = "Déclaration TVA CA3"
    root_report_id      → "Generic Tax Report"
    country_id          = France
    availability_condition = 'country'
```

When a French company opens the Tax Report, `get_options()` auto-redirects to the French variant.
Source: [account_report.py:2078](../enterprise/account_reports/models/account_report.py#L2078)

---

## Composite Reports (Sections)

A composite report contains multiple sub-reports accessible from one menu entry.

```
Annual Statements (composite)
    section_report_ids:
        → Balance Sheet
        → Profit and Loss
        → Trial Balance
```

Composite reports are auto-generated for localized report sets that set `use_sections = True`.
Source: [account_report.py:157](../addons/account/models/account_report.py#L157)

---

## Standard Reports — Deep Dive

### Balance Sheet

> [enterprise/account_reports/data/balance_sheet.xml](../enterprise/account_reports/data/balance_sheet.xml)
> Handler: `account.balance.sheet.report.handler`

- **Engine:** `domain` for leaf lines, `aggregation` for totals, one `custom` engine for the CTA line
- **`date_scope`:** `from_beginning` — assets/liabilities accumulate their full history
- **Default date filter:** `today` — point-in-time snapshot, not a range
- `filter_date_range = False` — single date only, no from/to
- `enable_snapshots = True` (new in Odoo 20)
- Report-level `groupby = account_id`
- Layout: horizontal split — Assets left, Liabilities + Equity right

**Structure (Odoo 20):**
```
ASSETS  (TA = CA + FA + PNCA)
  ├── Current Assets  (CA = BA + REC + CAS + PRE)
  │     ├── Bank and Cash Accounts  → domain: account_type = asset_cash
  │     ├── Receivables             → domain: asset_receivable AND non_trade = False
  │     ├── Current Assets          → domain: asset_current OR (asset_receivable AND non_trade)
  │     └── Prepayments             → domain: account_type = asset_prepayments
  ├── Plus Fixed Assets             → domain: account_type = asset_fixed
  └── Plus Non-current Assets       → domain: account_type = asset_non_current

LIABILITIES  (L = CL + NL)
  ├── Current Liabilities  (CL = CL1 + CL2 + CL3)
  │     ├── Current Liabilities → liability_current OR (liability_payable AND non_trade)
  │     ├── Payables            → liability_payable AND non_trade = False
  │     └── Credit Card         → liability_credit_card
  └── Non-current Liabilities   → liability_non_current

EQUITY (& EARNINGS)  (EQ = EQU + EAR + OCI)
  ├── Equity                       (EQU) → domain: account_type = equity,  from_beginning
  ├── Earnings                     (EAR = PYE + CYE)
  │     ├── Current Year Unallocated Earnings (CYE) → income*/expense*/equity_unaffected, from_fiscalyear
  │     └── Previous Years Earnings           (PYE) → same domain, to_beginning_of_fiscalyear
  └── Other Comprehensive Income   (OCI = CTA)
        └── Cumulative Translation Adjustments (CTA) → custom engine

LIABILITIES + EQUITY  (LE = L + EQ)
OFF BALANCE SHEET ACCOUNTS  (OS) → -sum on off_balance, hidden when zero
```

Source: [balance_sheet.xml](../enterprise/account_reports/data/balance_sheet.xml)

**`equity_unaffected` — correcting a common misconception.** The Balance Sheet *does* have explicit domain lines covering `equity_unaffected`; nothing is derived as a plug. `CYE` and `PYE` sum all income, expense **and** `equity_unaffected` accounts, split by `date_scope` (`from_fiscalyear` vs `to_beginning_of_fiscalyear`). So current-year profit appears in equity because the P&L accounts themselves are summed there, not because a handler back-solved `Assets − Liabilities`.

What the handler actually does is warn: if `currency_translation = 'cta'`, several company currencies are selected, and the report has no CTA expression, it raises `common_possibly_unbalanced_because_cta`.
Source: [`AccountBalanceSheetReportHandler — balance_sheet.py:5`](../enterprise/account_reports/models/balance_sheet.py#L5), [`_report_engine_cumulative_translation_adjustment() — balance_sheet.py:49`](../enterprise/account_reports/models/balance_sheet.py#L49)

**Odoo 20 addition — Other Comprehensive Income / CTA.** `_report_engine_cumulative_translation_adjustment` computes the translation difference that arises when subsidiaries in other currencies are consolidated, and posts it (sign-flipped) under equity. Without it, a multi-currency consolidated balance sheet does not balance.

---

### Profit and Loss (P&L)

> [enterprise/account_reports/data/profit_and_loss.xml](../enterprise/account_reports/data/profit_and_loss.xml)

- **Engine:** `domain` for leaf lines, `aggregation` for subtotals
- **`date_scope`:** `strict_range` — only the selected period
- **Default date filter:** `this_year`
- `filter_date_range = True`
- `filter_budgets = True` — budget comparison available

**`-sum` on income:** Income accounts have **credit-normal balances** (negative by convention). `subformula = '-sum'` negates them so revenue displays as a positive number. Using `sum` on income would show negative revenue.

**Structure (Odoo 20 — line codes and exact formulas):**
```
Revenue              (REV)   → domain: account_type = income,                            -sum
Costs of Revenue     (COS)   → domain: account_type = expense_direct_cost,                sum
Gross Profit         (GRP)   → aggregation: REV.balance - COS.balance
  Operating Expenses (EXP)   → domain: account_type = expense,                            sum
Operating Income     (INC)   → aggregation: REV.balance - COS.balance - EXP.balance
  Other Income       (OIN)   → domain: account_type = income_other,                      -sum
  Other Expenses     (OEXP)  → domain: expense_depreciation OR expense_other,             sum
Net Profit           (NEP)   → aggregation: REV.balance + OIN.balance
                                          - COS.balance - EXP.balance - OEXP.balance
  Allocations and Withdrawals (ALLOC) → domain: account_type = equity_unaffected,         sum
```

Source: [profit_and_loss.xml](../enterprise/account_reports/data/profit_and_loss.xml)

Two details that trip people up:

- `OEXP` covers **both** `expense_other` and `expense_depreciation`. Depreciation charges do not get their own P&L line by default.
- `INC` and `NEP` are computed from the leaves, not from the intermediate subtotals. Overriding `GRP` in a variant does not change `INC`.
- Odoo 20 dropped the "Less …" / "Plus …" prefixes from the line labels ("Less Costs of Revenue" → "Costs of Revenue"). The codes are unchanged, so variants keyed on codes still work.

---

### Trial Balance

> [enterprise/account_reports/data/trial_balance.xml](../enterprise/account_reports/data/trial_balance.xml)
> Handler: [account_trial_balance_report.py](../enterprise/account_reports/models/account_trial_balance_report.py)

**Purpose:** Verify mathematical integrity of the ledger. One row per account. No individual transactions.

**Columns** — built in `_get_column_values()`, not declared statically. Each column carries a `trial_balance_column_type` in its column group's `forced_options`:

| Column | `trial_balance_column_type` | Content | `date_scope` |
|---|---|---|---|
| Initial Balance | `initial_balance` | Net balance of all lines **before** `date_from` | `from_beginning`, capped at `trial_balance_block_end_date` |
| Debit | `period` | All debits **within** the period | `strict_range` |
| Credit | `period` | All credits **within** the period | `strict_range` |
| End Balance | `end_balance` | Initial Balance + period debit − period credit | `from_beginning` up to `date_to` |

Source: [`_get_column_values() — account_trial_balance_report.py:47`](../enterprise/account_reports/models/account_trial_balance_report.py#L47)

Odoo 20 organises comparison periods into **blocks**. Each block carries its own `trial_balance_block_fiscalyear_start` and `trial_balance_block_end_date`, so an Initial/End pair is computed against the fiscal year of *its own* comparison period rather than the main one. Comparisons are also forced ascending and the period-order filter is hidden.

**Balance sheet vs P&L accounts (income/expense reset):**

Balance sheet accounts (`include_initial_balance = True`) show all history in Initial Balance.
P&L accounts (`include_initial_balance = False`) only include lines from the **block's fiscal year start** — they reset each year.

```python
# account_trial_balance_report.py:237
if fiscalyear_start := options.get('trial_balance_block_fiscalyear_start'):
    extra_domain = [
        '|',
        ('account_id.include_initial_balance', '=', True),
        ('date', '>=', fiscalyear_start),
    ]
```

The code comment is explicit that this is both an optimisation and a functional rule — and that it is why the Unaffected Earnings line cannot be expanded.

**Undistributed Profits/Losses row:**
A special row for `equity_unaffected` representing the net of all un-closed P&L lines. Computed in `_custom_line_postprocessor()` and injected as a total. Odoo 20 injects a **Cumulative Translation Adjustment** row next to it when several company currencies are consolidated.
Source: [`_custom_line_postprocessor() — account_trial_balance_report.py:307`](../enterprise/account_reports/models/account_trial_balance_report.py#L307)

**Caret drill-down:** Each account row has "General Ledger" and "Journal Items"; the Undistributed Profits/Losses row gets its own pair pointing at `open_unallocated_items_journal_items`.
Source: [`_caret_options_initializer() — account_trial_balance_report.py:194`](../enterprise/account_reports/models/account_trial_balance_report.py#L194)

`filter_hierarchy = by_default` — accounts roll up under their `parent_id` by default (no longer `account.group`).

---

### General Ledger

> [enterprise/account_reports/data/general_ledger.xml](../enterprise/account_reports/data/general_ledger.xml)
> Handler: [account_general_ledger.py](../enterprise/account_reports/models/account_general_ledger.py)

**Purpose:** Full transaction history for every account. Every posted journal line shown individually with a running balance.

**Columns:**

| Column | Content |
|---|---|
| Date | Journal entry date |
| Partner | Partner on the line |
| Currency | Foreign currency amount (if multi-currency) |
| Debit | Debit amount |
| Credit | Credit amount |
| Balance | **Running balance** = previous balance + debit − credit |

**Groups by:** `account_id` → `id_with_accumulated_balance`

- Top level: one collapsed row per account
- Expand: every `account.move.line` for that account in date order
- Each individual line carries the cumulative balance to that point

**Running balance mechanism:**
```python
# account_general_ledger.py:379
accumulated_balance_by_colgroup[col_group_index] += line_balance
```
The accumulator is threaded between line batches to carry the running total across pagination.
Source: [`account_general_ledger.py:370`](../enterprise/account_reports/models/account_general_ledger.py#L370)

**Opening balance line:**
First row under each account is "Initial Balance" — `to_beginning_of_period` scope. All subsequent lines count from there.

**Pagination:** `load_more_limit = 80` — accounts with >80 lines show a "Load More" button.

**Trial Balance vs General Ledger:**

| | Trial Balance | General Ledger |
|---|---|---|
| Granularity | One row per account | One row per journal line |
| Shows transactions | No — totals only | Yes — every line |
| Balance column | Initial/End balance | Running (cumulative) balance |
| Use case | Verify totals, period-end close | Investigate what happened |
| Performance | Fast — aggregate SQL | Slow on large datasets — paginated |

---

### Aged Receivable / Aged Payable

> [enterprise/account_reports/data/aged_partner_balance.xml](../enterprise/account_reports/data/aged_partner_balance.xml)
> Handler: [account_aged_partner_balance.py](../enterprise/account_reports/models/account_aged_partner_balance.py)

**Purpose:** Show which invoices (AR) or bills (AP) are still outstanding and how long they have been overdue.

**Key difference from other reports:** Only **open items** appear. Fully reconciled invoices are excluded.

**How "open" is determined (rewritten in Odoo 20):**

The hand-written partial-reconciliation join is gone. The report now forces a reconciliation cut-off date into the options and reads two computed-SQL fields on `account.move.line`:

```python
if not report._get_option_recon_date(options):
    options['recon_date'] = {'date_to': options['date']['date_to']}
...
balance_select = SQL("%s * %s", query.table.residual_at_date, query.table.consolidation_rate)
```

- `residual_at_date` = `balance + partial_summary.amount_to_date` — the residual as of the report date
- `residual_currency_at_date` = the same in the line's own currency
- Partial reconciliations are counted only if their `max_date` falls on or before the cut-off, so the report stays historically accurate for any past date

Source: [`_aged_partner_report_custom_engine_common() — account_aged_partner_balance.py:85`](../enterprise/account_reports/models/account_aged_partner_balance.py#L85), [`residual_at_date — account_move_line.py:328`](../addons/account/models/account_move_line.py#L328)

Practical benefit: the same field is available in SQL, in the ORM and in list views, so an aged-report figure can be reproduced outside the report engine.

**Aging buckets** (default: 6 buckets, 30-day interval, based on `date_maturity`):

| Column | What it contains |
|---|---|
| `period0` | Not yet due — `date_maturity >= date_to` |
| `period1` | 1–30 days overdue |
| `period2` | 31–60 days overdue |
| `period3` | 61–90 days overdue |
| `period4` | 91–120 days overdue |
| `period5` | 121+ days overdue ("Older") |

Interval is user-configurable (`aging_interval`, default 30).
Source: [`_custom_options_initializer() — account_aged_partner_balance.py:41`](../enterprise/account_reports/models/account_aged_partner_balance.py#L41)

**Aging date basis:**

| `aging_based_on` | Date used for bucket assignment |
|---|---|
| `base_on_maturity_date` (default) | `date_maturity` — payment due date |
| `base_on_invoice_date` | `invoice_date` — original invoice date |

**UI structure:**
```
Partner A             0–30   31–60   61–90   91–120   Older   Total
  INV/2025/0001               1,500                           1,500
  INV/2025/0002                               800               800
```

**Trust indicator:** Each partner row gets `trust` (`good`/`normal`/`bad`) shown as a coloured dot, read with the partner's own company in context.
Source: [`_custom_line_postprocessor() — account_aged_partner_balance.py:61`](../enterprise/account_reports/models/account_aged_partner_balance.py#L61)

**AR vs AP — the only differences:**

| | Aged Receivable | Aged Payable |
|---|---|---|
| Account type | `asset_receivable` | `liability_payable` |
| Sign | `+1` (debit-normal) | `−1` (credit-normal, negated for positive display) |
| Audit journal filter | Excludes `purchase` journals | Excludes `sale` journals |

Both inherit `AccountAgedPartnerBalanceReportHandler` and share `_aged_partner_report_custom_engine_common()`. The engine methods are `_report_engine_aged_receivable` / `_report_engine_aged_payable` (renamed in Odoo 20).
Source: [account_aged_partner_balance.py:79](../enterprise/account_reports/models/account_aged_partner_balance.py#L79)

---

### Cash Flow Statement

> [enterprise/account_reports/data/cash_flow_report.xml](../enterprise/account_reports/data/cash_flow_report.xml)
> Handler: [account_cash_flow_report.py](../enterprise/account_reports/models/account_cash_flow_report.py)

**Purpose:** Show how cash moved through the business — operating, investing, and financing activities.

**Method:** Direct method (tracks actual cash movements through bank/cash accounts).

**Sections:**

| Section | Account tags used |
|---|---|
| Operating activities | `account.account_tag_operating` |
| Investing activities | `account.account_tag_investing` |
| Financing activities | `account.account_tag_financing` |

Account tags are pulled via `_get_tags_ids()`:
```python
# account_cash_flow_report.py:138
'operating': self.env.ref('account.account_tag_operating').id,
'investing': self.env.ref('account.account_tag_investing').id,
'financing': self.env.ref('account.account_tag_financing').id,
```
Source: [`_get_tags_ids() — account_cash_flow_report.py:135`](../enterprise/account_reports/models/account_cash_flow_report.py#L135)

**Computation flow** (in `_dynamic_lines_generator()`):
1. **Opening Balance** — `_compute_liquidity_balance(report, options, payment_account_ids, 'to_beginning_of_period')`
2. **Closing Balance** — same method with `'strict_range'` scope
3. **Liquidity Moves** — `_get_liquidity_moves()` — moves where at least one line touches a bank/cash account
4. **Reconciled Moves** — `_get_reconciled_moves()` — moves reconciled against bank/cash lines
5. **Dispatch** — `_dispatch_aml_data()` categorizes each move by account type and tag into the three sections
6. **Parent totals** — maintained recursively by `_report_update_parent()`

Because all lines are generated dynamically, this report uses `_dynamic_lines_generator()` exclusively — there are no static `account.report.line` rows with expressions.

---

### Tax Report (Generic)

> [enterprise/account_reports/data/generic_tax_report.xml](../enterprise/account_reports/data/generic_tax_report.xml)

- **Engine:** `tax_tags` for localized lines
- Root report: `account.generic_tax_report`
- Each `l10n_*` module creates a **variant** pointing to this root with country-specific tag names
- Before a localization is installed: shows all taxes by type
- After `l10n_xx` install: localized variant appears with actual tax return boxes

---

### Partner Ledger

> [enterprise/account_reports/data/partner_ledger.xml](../enterprise/account_reports/data/partner_ledger.xml)

- Similar to General Ledger but grouped by partner
- Shows receivable/payable lines per partner
- `filter_account_type` switches between customer (AR) / vendor (AP) view

---

### Interco Comparison (new in Odoo 20)

> [enterprise/account_reports/data/interco_comparison_report.xml](../enterprise/account_reports/data/interco_comparison_report.xml)
> Handler: [interco_comparison_report.py](../enterprise/account_reports/models/interco_comparison_report.py)

**Purpose:** Reconcile intercompany balances. For every counterpart company, it shows what the active company booked, what the counterpart booked, and the difference — the month-end check that previously had to be done by hand in a spreadsheet.

**Columns:** `main_company` / `counterpart` / `difference`, all produced by one custom engine `_report_engine_interco_comparison` with the column label as subformula.

**Groupby chain:** `currency_id → interco_company → interco_account_type → interco_account`

**How it scopes the data** — `_custom_options_initializer` forces a domain selecting only lines that sit on one side of an intercompany relationship:

```python
options['forced_domain'] = [
    ('move_id.exchange_diff_partial_ids', '=', False),
    '|',
        '&', ('partner_id', 'in', counterpart_companies.partner_id.ids), ('company_id', '=', self.env.company.id),
        '&', ('partner_id', '=', self.env.company.partner_id.id),        ('company_id', 'in', counterpart_companies.ids),
]
```

Account types are bucketed into pairs that should mirror each other — receivable ↔ payable, income ↔ expense, current assets ↔ current liabilities, and so on (`GROUPED_ACCOUNT_TYPES`). A non-zero **Difference** on a bucket means the two companies disagree and one side is missing or mis-posted.

Extras: tax lines are hidden by default (`hide_tax_lines`), exchange-difference moves are excluded, and a warning appears when only one company is selected — the report is meaningless without a counterpart.

---

## Report Snapshots (new in Odoo 20)

`account.report.snapshot` caches an engine's result for a closed period so later renders do not re-run the SQL.

| Field | Purpose |
|---|---|
| `report_id`, `company_id`, `date` | what the snapshot covers |
| `engine_func`, `engine_version` | which engine produced it, and at which version |
| `serialized_options`, `serialized_formulas_dict`, `date_scope`, `groupby` | the exact call signature it answers |
| `result` | the cached engine result (JSON) |

Source: [account_report_snapshot.py:85](../enterprise/account_reports/models/account_report_snapshot.py#L85)

**How it plugs in.** An engine opts in with `@snapshotable_engine(result_aggregators={...}, sub_engine_of=..., version=N)`. On each call the decorator looks for snapshots covering the requested period per company:

| Coverage | Behaviour |
|---|---|
| Full, for every selected company, at the report's end date | the engine is not called at all |
| Partial | the engine is called with a forced domain limited to dates after the snapshot, and the results are merged using `result_aggregators` |
| None | normal engine call |

Currently snapshotable: `_report_engine_tax_tags` and `_report_engine_account_codes` (through its subengine).

**Two constraints to respect when writing a snapshotable engine:**

1. The engine must be *composable* — computing it in parts by company and by date range, then aggregating, must give the same answer as computing it in one pass.
2. Warnings raised inside a snapshotted range are lost. This is deemed acceptable because snapshots target locked periods.

Bumping `version` invalidates existing snapshots: `_register_hook` deletes snapshots whose `engine_version` is lower than the current one, so a fix in stable forces recomputation.

---

### Executive Summary

> [enterprise/account_reports/data/executive_summary.xml](../enterprise/account_reports/data/executive_summary.xml)
> Handler: [executive_summary_report.py](../enterprise/account_reports/models/executive_summary_report.py)

**Purpose:** KPI overview for management — key ratios and financial health at a glance.

**Five sections:**

| Section | KPIs | Engine used |
|---|---|---|
| Cash | Cash received, Cash spent, Cash surplus, Closing bank balance | `domain`, `aggregation` |
| Profitability | Revenue, Cost of Revenue, Gross Profit, Expenses, Net Profit | `aggregation` with `cross_report` from P&L |
| Balance Sheet | Receivables, Payables, Net assets | `domain`, `aggregation` |
| Performance | Gross profit margin %, Net profit margin %, Return on investment % | `aggregation` (arithmetic on other expressions) |
| Position | Average debtors days, Average creditors days, Short-term cash forecast, Current assets/liabilities ratio | `aggregation`, `custom` |

**Notable pattern — `cross_report`:**
Profitability section pulls values directly from P&L without redefining the domain queries:
```
REV.balance → aggregation with cross_report(account.profit_and_loss_xml_id)
```

**Custom engine for NDays:**
```python
# executive_summary_report.py:11
# _report_custom_engine_executive_summary_ndays()
# Returns the number of days in the selected period — used for "average days" ratio denominators
```

---

## Currency Handling

**Reworked in Odoo 20.** The `currency_table` option and its JOIN are gone. Conversion now happens through computed-SQL fields on `account.move.line`:

| Field | Definition |
|---|---|
| `consolidation_rate` | the rate to apply to this line, resolved per company and account type |
| `consolidation_debit` | `consolidation_rate * debit` |
| `consolidation_credit` | `consolidation_rate * credit` |
| `consolidation_balance` | `consolidation_rate * balance` |

Engines select `SUM(consolidation_balance)` instead of `SUM(balance * currency_table.rate)`. When every selected company shares one currency, `_compute_sql_consolidation_rate` short-circuits to `SQL("1")` and no join is added at all.

Source: [`_compute_sql_consolidation_rate() — account_move_line.py:896`](../addons/account/models/account_move_line.py#L896)

**Which rate is used** depends on `account.report.currency_translation`:

| `currency_translation` | Rule |
|---|---|
| `current` | the current rate for the line's company, for every line |
| `cta` | per account type: `equity` → historical rate at the line's own date; `income*` / `expense*` / `equity_unaffected` → average rate over the period; everything else → current rate |

```sql
CASE WHEN account_type = 'equity'
        THEN historical->>company_id->>date
     WHEN account_type LIKE ANY (ARRAY['income%','expense%','equity_unaffected'])
        THEN average->>company_id
     ELSE current->>company_id
END::numeric AS rate
```

`cta` is the default on the field. It is what makes a consolidated multi-currency Balance Sheet balance — the residual lands on the Cumulative Translation Adjustment line under Other Comprehensive Income (see Balance Sheet above). If a report uses `cta`, has several currencies, and has no CTA expression, the Balance Sheet handler raises the `common_possibly_unbalanced_because_cta` warning.

Source: [`currency_translation — account_report.py:132`](../addons/account/models/account_report.py#L132)

---

## Audit Drill-Down

`auditable = True` on an expression means clicking the cell value opens a filtered list of `account.move.line` records.

- `account_codes` engine: collects `account_ids` for the matched accounts
- `domain` engine: uses the domain directly
- `aggregation` engine: traces back to source lines
- `external` engine: shows the `account.report.external.value` records

All standard engines are auditable.

---

## Export

| Format | How |
|---|---|
| PDF | QWeb template → Chromium headless render |
| XLSX | `xlsxwriter` library |
| EDI (XML, XBRL, SAFT) | Tax returns exported via `account.return.type` — localization-specific |

Export buttons are added to `options['buttons']` in `_init_options_buttons`.

---

## UI Entry Points

| Report | Menu path | Purpose |
|---|---|---|
| Balance Sheet | Accounting → Reporting → Balance Sheet | Point-in-time assets/liabilities |
| Profit and Loss | Accounting → Reporting → Profit and Loss | Revenue/expense for a period |
| Trial Balance | Accounting → Reporting → Trial Balance | Debit/credit totals per account |
| General Ledger | Accounting → Reporting → General Ledger | Every journal line with running balance |
| Partner Ledger | Accounting → Reporting → Partner Ledger | AR/AP lines by partner |
| Aged Receivable | Accounting → Reporting → Aged Receivable | Overdue customer invoices in buckets |
| Aged Payable | Accounting → Reporting → Aged Payable | Overdue vendor bills in buckets |
| Tax Report | Accounting → Reporting → Tax Report | VAT/tax return boxes |
| Cash Flow | Accounting → Reporting → Cash Flow Statement | Operating/investing/financing cash |
| Executive Summary | Accounting → Reporting → Executive Summary | KPI overview with key ratios |
| Interco Comparison | Accounting → Reporting → Interco Comparison | **New in Odoo 20** — matches each company's intercompany balances against the counterpart company's |
| Custom | Accounting → Reporting → (any custom) | Reports created via Accounting → Configuration → Financial Reports |

---

## Edge Cases and Gotchas

**`-sum` on income accounts**
Income accounts have credit-normal balances (negative by convention). `subformula = '-sum'` negates them for positive display. Using `sum` on income shows a negative number.
Source: [profit_and_loss.xml:32](../enterprise/account_reports/data/profit_and_loss.xml#L32)

**Balance Sheet uses `from_beginning`**
`date_scope` on Balance Sheet leaf expressions is `from_beginning`, not `strict_range`. It reads the full account history. Changing to `strict_range` would show only the period's movement, not the cumulative balance — Balance Sheet would be wrong.

**Aggregation runs last**
An `aggregation` expression cannot reference a line whose expression is still pending. The framework computes all non-aggregation lines first. Circular references raise a computation error.

**`count_rows` non-batchable**
`count_rows` subformula on `domain` engine is never batched — one SQL call per formula per line. Avoid on reports with many lines.

**Variant reroute is silent**
If a variant matches the current company's country, `get_options()` redirects without any visible indication. The UI shows the variant, not the root. Debugging: check `options['report_id']` vs `self.id`.
Source: [`get_options() — account_report.py:2309`](../enterprise/account_reports/models/account_report.py#L2309)

**`equity_unaffected` on Balance Sheet**
Contrary to a widespread belief, the Balance Sheet **does** have explicit domain lines covering `equity_unaffected` (`CYE` and `PYE` under Earnings). Nothing is back-solved. A wrong account type still breaks balance-sheet equality, but the failure mode is "the account is summed in the wrong bucket", not "the plug is wrong".

**`custom` engine without handler**
If `engine = 'custom'` but `custom_handler_model_id` is not set, `_get_custom_report_function` falls through to `account.report`, which has no such method, and the render fails.

**Carryover label convention**
`carryover_target` only works if the source expression label starts with `_carryover_` and the target label starts with `_applied_carryover_`. Both rules are enforced by `@api.constrains` at write time, so the error surfaces when you save the expression, not at period close.

**Report engine methods were renamed**
Any custom module overriding `_compute_formula_batch_with_engine_*` silently stops being called in Odoo 20. Rename to `_report_engine_*`.

**`sum_if_pos` / `sum_if_neg` / `count_rows` no longer exist**
Domain expressions using them must be converted to `aggregation` with `if_above` / `if_below` bounds. There is no replacement for `count_rows`.

**Lines are dataclasses, not dicts**
`line['name']` still works but logs "Use of slow `__getitem__` on report data object". In custom handlers, use `line.name`. Serialise with `.as_dict()` when passing data to the client or to code that expects dicts.

**Cash Flow is fully dynamic**
The Cash Flow Statement has no static `account.report.line` rows with expressions. All lines come from `_dynamic_lines_generator()`. You cannot add a line by adding an `account.report.line` record — you must modify the handler.

---

## What Changed in Odoo 20

Everything below is a behaviour or API change from Odoo 19 that affects custom reports or day-to-day reading of the standard ones.

| Area | Odoo 19 | Odoo 20 |
|---|---|---|
| Engine method names | `_compute_formula_batch_with_engine_<engine>` | `_report_engine_<engine>`, resolved through `_get_custom_report_function` |
| Engine signature | `(options, date_scope, formulas_dict, current_groupby, next_groupby, offset, limit, warnings)` | `(options, date_scope, formulas_dict, current_groupby, warnings)` |
| Engine count | 6 | 8 — `text` and `reference` added |
| `domain` subformulas | `sum`, `-sum`, `sum_if_pos`, `sum_if_neg`, `count_rows` | `sum`, `-sum` only |
| `formula` / `subformula` type | `Char` | `Text` |
| Currency conversion | `currency_table` option + SQL JOIN | `consolidation_rate` / `consolidation_balance` computed-SQL fields on `account.move.line` |
| CTA | implicit in the currency table | explicit rate rules by account type, plus a CTA line on the Balance Sheet and Trial Balance |
| Hierarchy | `account.group` prefix ranges | `account.account.parent_id` tree |
| Analytic filter | `filter_analytic` on `account.report` | `filter_analytic_groupby`, declared in `account_analytic_report.py` |
| Line folding | `foldable` boolean | `foldability` selection (`always_unfolded` / `never_unfolded` / `foldable`) |
| Prefix groups | `prefix_groups_threshold` + its initializer | removed |
| Lines and columns | plain dicts | `AccountReportLineData` / `AccountReportColumnData` dataclasses |
| Aged residual | inline partial-reconciliation SQL | `account.move.line.residual_at_date` |
| Trial Balance | one initial/end pair | comparison **blocks**, each with its own fiscal-year start, plus a CTA row |
| Balance Sheet equity | `UNAFFECTED_EARNINGS` + `RETAINED_EARNINGS` | `EQU` + `EAR` (`PYE`/`CYE`) + `OCI` (`CTA`) |
| Caching | none | `account.report.snapshot` + `@snapshotable_engine` |
| New reports | — | Interco Comparison |
| Security files | `ir.model.access.csv` + `ir.rule` | unified `ir.access.csv` (affects any custom report module) |

**Migration checklist for a custom report module:**

1. Rename `_compute_formula_batch_with_engine_*` → `_report_engine_*` and drop `next_groupby`/`offset`/`limit`.
2. Replace `sum_if_pos` / `sum_if_neg` / `count_rows` subformulas.
3. Replace `foldable` with `foldability` in XML data.
4. Replace `filter_analytic` with `filter_analytic_groupby`.
5. Drop any `_init_options_currency_table` override or `options['currency_table']` read; use `consolidation_balance` in SQL.
6. In handlers, access line attributes (`line.name`) instead of `line['name']`.
7. Convert `ir.model.access.csv` and `ir.rule` records to `ir.access.csv`.

---

## Related Docs

- [INDEX.md](INDEX.md)
- [accounting_coa.md](accounting_coa.md) — account types determine which domain expressions match
- [accounting_multicompany_branches.md](accounting_multicompany_branches.md) — company filter, consolidation and the Interco Comparison report
- [accounting_migration.md](../dev_notes/reference/accounting_migration.md) — which reports to validate before go-live
