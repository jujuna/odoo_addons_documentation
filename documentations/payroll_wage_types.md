# Payroll Wage Types — Fixed, Hourly, Daily and Combinations

> **Module:** `hr_payroll` (enterprise) | **Path:** [`enterprise/hr_payroll/models/`](../enterprise/hr_payroll/models/) | Custom: [`geo_payroll`](../custom_addons/gec_odoo_modules/geo_payroll/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

This doc explains how Odoo 20 turns the wage on an employee version into payslip money, which
pay schemes work with configuration only, and where code is needed for daily rates and mixed
schemes (fixed + hourly, fixed + daily, hourly + daily, per unit). It ends with how `geo_payroll`
implements them for Georgian companies. Read it before promising a client a pay scheme.

Short answer: core has **two** wage types, Fixed and Hourly. Everything else is a localization
or a custom module.

---

## 1. The Two Standard Wage Types

Contract data lives on `hr.version`. `hr.contract` does not exist in 20.0; use `hr.version`.

| Field | Meaning | Source |
|---|---|---|
| `wage_type` | `monthly` ("Fixed Wage") or `hourly` ("Hourly Wage"). Stored compute from the structure type, editable, and **reset whenever the structure type changes** (no guard) | [hr_version.py:42](../enterprise/hr_payroll/models/hr_version.py#L42), [:397](../enterprise/hr_payroll/models/hr_version.py#L397) |
| `wage` | Gross wage per pay period | [hr_version.py:188](../addons/hr/models/hr_version.py#L188) |
| `hourly_wage` | Float with 4 decimals, must be ≥ 0 | [hr_version.py:46](../enterprise/hr_payroll/models/hr_version.py#L46), [:95](../enterprise/hr_payroll/models/hr_version.py#L95) |
| `schedule_pay` | Pay frequency, from the structure type (guarded compute) | [hr_version.py:391](../enterprise/hr_payroll/models/hr_version.py#L391) |
| `resource_calendar_id` | Required working schedule; its type (Fixed/Variable/Undefined) shapes the hours | [`resource_calendars.md`](resource_calendars.md) |
| `attendance_based` | Pay from badge records instead of the schedule on days without attendance | [`attendance_work_entry.md`](attendance_work_entry.md) |

**One dispatcher decides which wage is "the" wage.** `_get_contract_wage()` reads the field named
by `_get_contract_wage_field()`: `hourly_wage` for hourly versions, else `wage`
([hr_version.py:540](../enterprise/hr_payroll/models/hr_version.py#L540),
[base:484](../addons/hr/models/hr_version.py#L484)). On an hourly version `wage` stays on the form
but does not price worked days. A stale `wage` becomes live the moment the structure type flips
the version back to Fixed.

**No daily wage type in core `hr_payroll`.** Two localizations extend the selection:
Philippines adds `daily` ([l10n_ph hr_version.py:85](../enterprise/l10n_ph_hr_payroll/models/hr_version.py#L85)),
Switzerland adds `NoTimeConstraint` ([l10n_ch hr_version.py:216](../enterprise/l10n_ch_hr_payroll/models/hr_version.py#L216)).
`geo_payroll` adds `daily` and `unit` (section 7).

**`schedule_pay = 'daily'` is a frequency, not a rate.** It makes every payslip one day long
(`date_to = date_from`, [hr_payslip.py:318](../enterprise/hr_payroll/models/hr_payslip.py#L318)),
i.e. a payslip per day. It is not "a daily rate paid monthly".

---

## 2. The Computation Chain

```
hr.version (wage_type, wage / hourly_wage, calendar, attendance_based)
  -> generate_work_entries() at compute time: [{date, duration, time type}, ...]
  -> worked-day lines: one per time type (and payroll options)
       days = hours / calendar.hours_per_day, rounded per the type's request unit
  -> amount
       hourly: hourly_wage x hours x type rate
       fixed:  wage / calendar hours in the period x hours x type rate
               (Undefined calendars: wage / the slip's non-extra hours)
       rate 0, or code 000.00 -> 0
  -> categories seeded from worked days through type.category_ids  (Work 002.00 -> BASIC)
  -> BASIC rule = sum of worked-day amounts;  GROSS = categories BASIC + ALW
```

Anchors:

- **Amount:** [_compute_amount](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66).
  It skips payslips that are not draft or are flagged `edited`. The fixed-wage denominator is the
  calendar's scheduled hours inside the payslip dates, leaves ignored
  ([:90](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L90)).
- **Days:** [_get_worked_day_lines_values](../enterprise/hr_payroll/models/hr_payslip.py#L1374).
  Days are rounded to whole or half days for `day` / `half_day` request units using the type's
  `round_days_type` (default **Down**); the remainder moves to the biggest line
  ([_round_days](../enterprise/hr_payroll/models/hr_payslip.py#L1344)). Hours split off by a time
  rule keep their exact fraction.
- **Several versions on one slip.** All versions of the same contract that start inside the period
  are computed together, each worked-day line with its own version and rates
  ([_compute_worked_days_line_ids](../enterprise/hr_payroll/models/hr_payslip.py#L2162)).
- **BASIC and GROSS:** the core BASIC rule is `result = payslip._get_basic_salary()`
  ([hr_salary_rule_data.xml:10](../enterprise/hr_payroll/data/hr_salary_rule_data.xml#L10),
  [_get_basic_salary](../enterprise/hr_payroll/models/hr_payslip.py#L2625)) and GROSS reads the
  categories ([:27](../enterprise/hr_payroll/data/hr_salary_rule_data.xml#L27)).
- **Rule context** ([_get_localdict](../enterprise/hr_payroll/models/hr_payslip.py#L1626)):
  `worked_days` is a dict by code (`worked_days['002.00'].number_of_hours`), `inputs` a dict by
  code, plus `payslip`, `version`, `employee`, `categories`, `result_rules` and the raw
  `work_entries` values. `payslip.env[...]` searches are allowed in rule code.

### What the fixed-wage formula means in practice

Wage 2,200; the month has 22 scheduled days of 8 h = 176 h, so the rate is 12.50.

| Worked-day line | Hours | Amount |
|---|---|---|
| Work | 152 | 1,900.00 |
| Sick (rate 100%) | 8 | 100.00 |
| Leave without pay (rate 0%) | 16 | 0.00 |
| **Total** | 176 | **2,000.00** |

- A full month with a 100% public holiday still totals exactly 2,200: the holiday hours are
  scheduled hours and pay at the same rate.
- **Extra paid hours are paid on top.** 10 h of overtime at rate 1.0 add 125.00; nothing is
  diluted, because the denominator is the schedule, not the slip.
- **Mid-month hire.** A contract that covers 12 of the 22 scheduled days (96 h) pays
  96 x 12.50 = 1,200.00. The Out of Contract line (`000.00`) shows the rest at 0.
- A Variable calendar with more slots in one month gives a lower hourly rate that month; a full
  month still pays the wage.

**One rate per slip.** On a fixed slip every line, overtime included, is priced from the derived
rate; `hourly_wage` is never read. Wage 1,800 over 176 h = 10.23/h, so 42 h of overtime pays
429.55 at rate 1.0 and 644.32 at 1.5. Paying an independent 15/h (630.00) needs code or a salary
rule (sections 5–6).

---

## 3. Where Worked Time Comes From

| Source | What it supplies | Notes |
|---|---|---|
| Schedule | The calendar's slots, each with its own time type; synthetic days for Undefined calendars with a target; the whole span for fully flexible ones | Default for versions that are not attendance based |
| Attendances | Closed, validated clock records with their time type | Baseline for attendance-based versions; on schedule-based versions a badge replaces the whole scheduled day |
| Time rules | Overtime and deficit outputs as attendance or leave records with their own types | Output type rate = the pay |
| Time off and public holidays | Calendar leaves, typed by the leave's or holiday's time type | Absence types reduce worked time; working-time types count as worked |
| Timesheets | Nothing | No standard bridge; `geo_payroll` pays validated timesheets through salary rules |
| Planning | Nothing | Not a payroll source in 20.0 |

Full mechanics: [`work_entries.md`](work_entries.md).

---

## 4. Salary Scheme Matrix (Standard Odoo)

| Scheme | Standard? | How |
|---|---|---|
| 1. Fixed | Yes, configuration | `wage_type = monthly`; unpaid leave through rate-0 time types |
| 2. Hourly | Yes, configuration | `wage_type = hourly` + `hourly_wage`; `attendance_based` to pay the clock |
| 3. Daily | No | Localization or custom code (section 5). Approximation: `hourly_wage = day rate / hours per day`, exact only when every day has the same hours |
| 4. Fixed + overtime | Yes, configuration | A time rule sends excess hours to an overtime type with the rate you pay; its category must reach GROSS. Priced from the derived fixed rate x type rate |
| 5. Fixed + independent hourly | No | Code (section 6) |
| 6. Fixed + daily, hourly + daily, per unit | No | Code (section 6) |

---

## 5. Implementing a Daily Rate

Stock precedent: `l10n_ph_hr_payroll`.

1. **Extend the selection on both models** with a cleanup policy:
   `selection_add=[('daily', 'Daily Wage')], ondelete={'daily': 'set monthly'}` on
   `hr.version.wage_type` and `hr.payroll.structure.type.wage_type`
   ([l10n_ph hr_payroll_structure_type.py:9](../enterprise/l10n_ph_hr_payroll/models/hr_payroll_structure_type.py#L9)).
   `'set default'` fails at registry load because `hr.version.wage_type` has no default
   ([fields_selection.py:151](../odoo/orm/fields_selection.py#L151)).
2. **Add the rate field and route the dispatcher to it**: override `_get_contract_wage_field` and
   add the field to `_get_fields_that_recompute_payslip`
   ([l10n_ph hr_version.py:385](../enterprise/l10n_ph_hr_payroll/models/hr_version.py#L385)).
   Philippines keeps `wage` and the daily wage in sync through a days-per-year factor.
3. **Override `_compute_amount`** on `hr.payslip.worked_days` for your structures only, keeping the
   `edited` / non-draft guard and extending `@api.depends`
   ([l10n_ph hr_payslip_worked_days.py:29](../enterprise/l10n_ph_hr_payroll/models/hr_payslip_worked_days.py#L29)).
   BE, HK, MX, AU and LU override the same method.
4. **Derive payable days yourself.** `number_of_days` is display-grade (hours / `hours_per_day`,
   rounded down by default, remainder moved between lines).
5. **Every consumer of `wage_type` tests `== 'hourly'`**, so a new value falls into the fixed path
   everywhere: worked-day pricing, `_get_contract_wage_field`, `_get_normalized_wage`
   ([hr_version.py:534](../enterprise/hr_payroll/models/hr_version.py#L534)). The payslip PDF
   prints the raw key for non-monthly types ([report_payslip_templates.xml:70](../enterprise/hr_payroll/views/report_payslip_templates.xml#L70)).

---

## 6. Implementing Combinations

Core prices one slip with one rate path. Three designs work:

- **A. Salary-rule layer.** Keep `monthly` for the fixed part and add rules that pay the extra
  component from their own data (`result = hours x version.x_rate`). No core override; the money
  appears only in rule lines. This is how `geo_payroll` pays work logs, timesheets and units.
- **B. Rate routing per time type.** Override `_compute_amount` so that some time types are priced
  per day or per hour at their own rate and the rest at the fixed rate. Worked-day lines stay
  truthful. This is the pattern of the localization overrides above.
- **C. Wage components (Swiss pattern).** The version holds several rates and a payslip one2many
  of components computed from time data feeds the rules
  ([l10n.ch.swiss.wage.component](../enterprise/l10n_ch_hr_payroll/models/l10n_ch_worked_days.py#L7),
  [_compute_l10n_ch_swiss_wage_ids](../enterprise/l10n_ch_hr_payroll/models/hr_payslip.py#L240)).
  Most powerful, most maintenance.

Where each kind of money shows on the payslip:

| Surface | Fed by | Needs a time type? |
|---|---|---|
| **Worked Days** tab | The time projection, one line per type; days, hours and amount editable in draft, no add or delete ([hr_payslip_views.xml:150](../enterprise/hr_payroll/views/hr_payslip_views.xml#L150)) | Yes |
| **Salary Inputs** tab | `hr.payslip.input` lines, each linked to the salary rule that reads it | No |
| **Salary Computation** tab | Salary rules, including BASIC | No |

Stock pricing versus per-type routing, same month:

| Case | Line | Stock amount | With routing |
|---|---|---|---|
| Hourly 12/h + site days paid 100/day, 5 site days of 8 h | Site Day | 480.00 (40 h x 12) | 500.00 (5 x 100) |
| Fixed 1,800 + 42 h extra at an intended 15/h | Extra Hours | 429.55 (derived 10.23/h) | 630.00 |

---

## 7. How `geo_payroll` Implements the Schemes

Details and every guard: [`geo_payroll.md`](geo_payroll.md). The shape:

| Piece | What it does | Source |
|---|---|---|
| **Pay Scheme** on the version | Fixed, Hourly, Daily, Per Unit, Fixed + Daily, Fixed + Hourly, Daily + Hourly, Daily + Per Unit; sets `wage_type` and the component flags | [hr_version.py:41](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_version.py#L41) |
| `daily` and `unit` wage types | Added on version and structure type with `ondelete='set monthly'` | [hr_payroll_structure_type.py:8](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payroll_structure_type.py#L8) |
| Daily base | Priced only from approved daily work logs: `daily_wage x day units x type rate`; no schedule, leave or holiday pay | [hr_payslip_worked_days.py:13](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_worked_days.py#L13) |
| Unit and timesheet-hourly bases | Worked-day amounts forced to 0; the pay comes from rule lines | same |
| Add-ons | Overtime, daily and unit work logs and validated timesheets paid by salary rules (design A) | [`geo_payroll.md`](geo_payroll.md) |
| BASIC | Sets `categories['BASIC']` to every paid worked-day line itself, so paid leave and holidays reach GROSS | [payroll_structure_data.xml:78](../custom_addons/gec_odoo_modules/geo_payroll/data/payroll_structure_data.xml#L78) |

Background and the original design plan: [`../PAYROLL_WAGE_TYPES_PLAN.md`](../PAYROLL_WAGE_TYPES_PLAN.md).

---

## 8. Gotchas for a Custom Wage-Type Module

| # | Gotcha | Anchor |
|---|---|---|
| 1 | **A second manual payslip for a later version pays that slice twice.** One slip already covers all versions of the contract in its period | [hr_payslip.py:2162](../enterprise/hr_payroll/models/hr_payslip.py#L2162) |
| 2 | `wage_type` is recomputed from the structure type; put your value on both models | [hr_version.py:397](../enterprise/hr_payroll/models/hr_version.py#L397) |
| 3 | `edited` is set by any inline salary-line edit and never cleared; edited slips keep their worked-day amounts and are skipped by refresh | [hr_payslip.py:1326](../enterprise/hr_payroll/models/hr_payslip.py#L1326) |
| 4 | **Types without a salary category are missing from GROSS** when the core BASIC rule is used; the shipped Overtime `040.00` is in EXTRA_HOURS, which core GROSS does not add | [hr_work_entry_type_data.xml:14](../enterprise/hr_payroll/data/hr_work_entry_type_data.xml#L14) |
| 5 | `code in '000.00'` is a substring test: a custom code such as `0` or `00.00` is priced 0 | [hr_payslip_worked_days.py:114](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L114) |
| 6 | Structures without worked days (`use_worked_day_lines` off) make BASIC the raw contract wage — for an hourly version that is the hourly rate | [_get_basic_salary](../enterprise/hr_payroll/models/hr_payslip.py#L2625) |
| 7 | Wage edits refresh only draft, regular payslips of that version in the current company; add your own rate fields to the list | [hr_version.py:612](../enterprise/hr_payroll/models/hr_version.py#L612), [:683](../enterprise/hr_payroll/models/hr_version.py#L683) |
| 8 | **Fully flexible schedule-based versions get the whole period as worked time**, about 24 h per day. Fixed wages survive (they divide by the slip's hours); hourly wages multiply it | [hr_version.py:79](../addons/hr_work_entry/models/hr_version.py#L79) |
| 9 | Time rules rewrite attendances, and the shipped schedule rule turns every excess hour into `040.00` at 100% for every company | [`attendance_work_entry.md`](attendance_work_entry.md) |
| 10 | Days are display-grade; the default rounding is Down | [_round_days](../enterprise/hr_payroll/models/hr_payslip.py#L1344) |
| 11 | Employees cannot open `hr.employee` (HR Officers only); self-service screens for a custom model need their own menu and access | [hr ir.access.csv:4](../addons/hr/security/ir.access.csv#L4) |
| 12 | Custom blocking checks are `hr.payroll.warning` records with a domain and **Block Payslips** | [hr_payroll_warning.py:59](../enterprise/hr_payroll/models/hr_payroll_warning.py#L59) |
| 13 | No Georgian payroll localization exists in core; Georgian structures, rules and accounts come from `geo_payroll` | [`geo_payroll.md`](geo_payroll.md) |

---

## 9. Module Shopping List

| Need | Modules |
|---|---|
| Any payroll | `hr_payroll` (enterprise); it brings `hr_holidays` and `hr_work_entry` |
| Pay actual presence or overtime | `hr_attendance` (+ `hr_holidays_attendance`, `hr_payroll_attendance`, auto-installed) |
| Accounting entries and payments | `hr_payroll_account` — see [`payroll_payment_flow.md`](payroll_payment_flow.md) |
| Daily, per-unit, timesheet-paid and mixed schemes | `geo_payroll` |

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_payroll.md`](hr_payroll.md) — payslip lifecycle, pay runs, corrections
- [`work_entries.md`](work_entries.md) — the time projection and time types
- [`attendance_work_entry.md`](attendance_work_entry.md) — attendance and time rules
- [`resource_calendars.md`](resource_calendars.md) — schedule hours and days
- [`public_holidays_flow.md`](public_holidays_flow.md) — holiday hours on the payslip
- [`geo_payroll.md`](geo_payroll.md) — the Georgian implementation
