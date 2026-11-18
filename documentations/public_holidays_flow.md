# Public Holidays — From Calendar Row to Payslip

> **Modules:** `resource`, `hr_holidays`, `hr_work_entry`, `hr_holidays_attendance`, `hr_payroll` | **Path:** [`addons/hr_holidays/models/resource_calendar_leaves.py`](../addons/hr_holidays/models/resource_calendar_leaves.py)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

A public holiday is one `resource.calendar.leaves` row with no resource. It is not an `hr.leave`:
nobody requests or approves it. That one row changes several things at once:

- employee leave durations and balances around the date,
- time-rule outputs on attendances (overtime),
- generated timesheet lines and Planning hours,
- the hours on every payslip computed afterwards.

Payroll stores nothing ahead of time. A draft payslip reads the holiday when it is computed or
refreshed; a validated or paid payslip never changes. So the practical rule is simple: **enter
the year's holidays before the first payslip of the year is computed**, and treat any later change
inside a paid period as a payroll correction.

Georgia has no bundled holiday data. Georgian companies enter their holidays by hand every year;
the loader wizard reports "Public holiday data is not available" and the monthly cron does nothing
for them.

---

## The Big Picture — How It Works

```
Create (by hand / Load Public Holidays wizard / monthly cron)
  resource.calendar.leaves   resource empty, calendar optional, time type, count_as
     |
     |-- hr_holidays ............ overlapping employee leaves re-evaluated
     |                            (duration, balance, message, maybe refused)
     |-- hr_holidays_attendance . time rules re-run for the affected employees
     |-- project_timesheet_holidays  one timesheet line per employee and working day
     |-- planning_holidays ...... shift allocated hours recomputed
     `-- payroll ................ nothing stored

Payslip compute / refresh (draft only)
  hr.version.generate_work_entries()
     scheduled hours inside the holiday  ->  hours of the holiday's time type
  worked-day line -> amount (type rate) -> BASIC -> GROSS
```

### Key Decision Points

- **Scope.** Leave *Working Hours* empty to hit every schedule of the current company, or pick
  one calendar. The company comes from the calendar, else from the company you are logged into.
- **Time type.** Defaults to the company country's `006.00` "Public holiday", else the generic one
  ([_compute_work_entry_type_id](../addons/hr_work_entry/models/resource_calendar_leaves.py#L19)).
  Its `amount_rate` decides the pay and its salary categories decide whether the pay reaches GROSS.
- **Counts as.** `absence` (default) removes the hours from work time; `working_time` treats them
  as worked time.
- **Eligible for accrual.** Off by default ([resource_calendar_leaves.py:18](../addons/hr_holidays/models/resource_calendar_leaves.py#L18)):
  accruals based on worked time lose the holiday hours.
- **Per time-off type: "Ignore Public Holidays".** Decides whether a leave spanning a holiday
  consumes balance for it (below).

---

## The Record

| Field | Meaning |
|---|---|
| `company_id` | Stored, read-only, computed from the calendar or the current company. Switch to the right company before creating an All Schedules holiday |
| `calendar_id` | Empty = every schedule of the company; set = that schedule only |
| `date_from` / `date_to` | Stored in UTC. The list edits them as a date range; an end left empty becomes 23:59:59 of the start day in the user's timezone ([_compute_date_to](../addons/resource/models/resource_calendar_leaves.py#L62)) |
| `work_entry_type_id` | The payroll time type (see Key Decision Points) |
| `count_as` | `absence` / `working_time` ([:48](../addons/resource/models/resource_calendar_leaves.py#L48)) |
| `elligible_for_accrual_rate` | Default off |
| `category_options_ids` | Payroll options carried into the payslip line key ([resource_calendar_leaves.py:10](../enterprise/hr_payroll/models/resource_calendar_leaves.py#L10)) |

Two holidays of the same company may not overlap on the same schedule; an All Schedules holiday
overlaps every schedule. The check runs in Python, so two simultaneous creates can both pass
([_check_compare_dates](../addons/hr_holidays/models/resource_calendar_leaves.py#L22)).

---

## Three Ways Holidays Are Created

| Path | Who / where | What it does |
|---|---|---|
| **By hand** | Time Off → Configuration → **Company Holidays** (Time Off Administrator, [hr_holidays_views.xml:113](../addons/hr_holidays/views/hr_holidays_views.xml#L113)); Payroll → Configuration → Time Management → Company Holidays ([hr_payroll_menu.xml:97](../enterprise/hr_payroll/views/hr_payroll_menu.xml#L97)); "Public Holidays" button on a calendar | Editable list of rows without resource ([resource_views.xml:102](../addons/hr_holidays/views/resource_views.xml#L102)). Dates are entered in the user's timezone |
| **Load Public Holidays** wizard | Button on the Company Holidays list | For a year after 2025 ([load_public_holiday_wizard.py:43](../addons/hr_holidays/wizard/load_public_holiday_wizard.py#L43)), reads the CSV of each active company's country ([_prepare_public_holidays_data](../addons/hr_holidays/models/resource_calendar_leaves.py#L152)), previews one line per holiday, skips dates already covered, requires a time type on every line, and creates each day from 00:00 to 23:59:59 in the **company** timezone ([_get_create_values_by_company](../addons/hr_holidays/wizard/load_public_holiday_wizard.py#L125)) |
| **Monthly cron** "Time Off: Generate Public Holidays" | Automatic, and once at every company creation ([res_company.py:30](../addons/hr_holidays/models/res_company.py#L30)) | Creates the next 12 months from the same CSVs ([_cron_generate_public_holidays](../addons/hr_holidays/models/resource_calendar_leaves.py#L231)); skipped during tests |

Bundled data covers 20 countries (AU, BE, CH, EG, HK, IN, JO, KE, LT, LU, MA, MX, MY, NL, PL, RO,
SA, SK, TR, US) in [`data/public_holidays/`](../addons/hr_holidays/data/public_holidays/).

---

## What Saving a Holiday Does Immediately

| Effect | Module | Detail |
|---|---|---|
| **Employee leaves re-evaluated** | `hr_holidays` | On create, write and unlink, every leave of an employee of that company overlapping the old or new dates (not refused or cancelled, not a time-rule output) gets its duration recomputed, is bounced through `confirm` and back, and has its calendar row recreated. The employee is told when days come back or are taken; a leave that no longer fits its allocation is **refused** ([_reevaluate_leaves](../addons/hr_holidays/models/resource_calendar_leaves.py#L61)). The search does not filter on the holiday's calendar |
| **Time rules re-run** | `hr_holidays_attendance` | Attendances of the affected employees are re-processed for the holiday span; a write re-processes both the old and the new span ([resource_calendar_leaves.py:56](../addons/hr_holidays_attendance/models/resource_calendar_leaves.py#L56)) |
| **Timesheet lines** | `project_timesheet_holidays` | When the company has an internal project and time-off task, one line per employee and working day, linked by `global_leave_id` ([_timesheet_create_lines](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L119)); an edit deletes and regenerates them ([:266](../addons/project_timesheet_holidays/models/resource_calendar_leaves.py#L266)) |
| **Planning hours** | `planning_holidays` | Shift `allocated_hours` recomputed on create and unlink ([resource_calendar_leave.py:66](../enterprise/planning_holidays/models/resource_calendar_leave.py#L66)) |
| **Payroll** | — | Nothing. The next compute of a draft payslip picks the holiday up |

---

## Time Off, Balances and Accruals

- **"Ignore Public Holidays"** on the time type (`include_public_holidays_in_duration`,
  [hr_work_entry_type.py:98](../addons/hr_holidays/models/hr_work_entry_type.py#L98)). Off
  (default): holiday hours are left out of the leave duration and cost no balance. On: they are
  counted and consumed. The flag cannot be toggled while leaves of the current year overlap a
  holiday ([_check_overlapping_public_holidays](../addons/hr_holidays/models/hr_work_entry_type.py#L175)).
- **A leave made only of holidays and days off** has zero duration and is refused at validation,
  unless its type's code is on the sickness/incapacity bypass list
  ([_get_leaves_on_public_holiday](../addons/hr_holidays/models/hr_leave.py#L1949)).
- **Accruals on worked time** subtract holiday hours unless the holiday is marked eligible
  ([hr_leave_allocation.py:526](../addons/hr_holidays/models/hr_leave_allocation.py#L526)). The
  wizard copies the flag from the chosen time type, which is off for absence types
  ([_compute_eligible_for_accrual_rate](../addons/hr_holidays/models/hr_work_entry_type.py#L407)).
- Changing a schedule or a timezone does not re-evaluate existing leave durations; only holiday
  edits do. Full time-off behaviour: [`hr_holidays.md`](hr_holidays.md).

---

## How a Holiday Reaches the Payslip

`generate_work_entries()` ([_get_version_work_entries_values](../addons/hr_work_entry/models/hr_version.py#L122))
subtracts calendar leaves from the theoretical schedule and turns the scheduled hours inside the
holiday into hours of the holiday's time type. Only scheduled hours count: a holiday on a day off
produces nothing. When a holiday and an employee leave cover the same hours, the holiday wins,
unless the country ships bypass codes (Belgium, Hong Kong)
([_get_interval_leave_work_entry_type](../addons/hr_holidays/models/hr_version.py#L264)).

| Employee setup | What the holiday produces |
|---|---|
| Schedule-based version, Fixed or Variable calendar, no attendance that day | Every scheduled hour of the day as holiday hours ([hr_version.py:197](../addons/hr_work_entry/models/hr_version.py#L197)) |
| Same, with a validated attendance that day (`hr_holidays_attendance`) | The whole scheduled day is knocked out ([hr_version.py:88](../addons/hr_holidays_attendance/models/hr_version.py#L88)); attended hours come in with the attendance's type; the holiday keeps only the scheduled hours not covered by the attendance — worked time beats absence ([_get_valid_leave_intervals](../addons/hr_holidays_attendance/models/hr_version.py#L165)) |
| Attendance-based version | The schedule supplies no work, but the holiday still produces the day's scheduled hours minus attended time ([hr_version.py:202](../addons/hr_work_entry/models/hr_version.py#L202)) |
| Flexible calendar | A one-day holiday keeps its own span minus attended time; a multi-day holiday is cut to the synthetic daily hours |
| Fully flexible calendar | The holiday's whole span: a full-day holiday becomes about 24 h ([hr_version.py:183](../addons/hr_work_entry/models/hr_version.py#L183)) |

**Pricing** ([hr_payslip_worked_days.py:66](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66)):

- Fixed wage: wage x holiday hours / the calendar's scheduled hours in the period x type rate. The
  denominator ignores leaves, so a month with a 100% holiday still totals exactly the wage.
- Hourly wage: `hourly_wage` x hours x type rate.
- Rate 0 = unpaid. The generic `006.00` type pays 100%
  ([hr_work_entry_type_data.xml:77](../addons/hr_work_entry/data/hr_work_entry_type_data.xml#L77)).

**The GROSS trap.** Core seeds salary categories from worked-day lines through the type's
`category_ids`, and only the generic Work type is mapped to BASIC
([hr_work_entry_type_data.xml:14](../enterprise/hr_payroll/data/hr_work_entry_type_data.xml#L14)).
The core BASIC rule shows all worked-day amounts but writes `categories['BASIC']` only when it is
still empty, and GROSS reads the category
([hr_salary_rule_data.xml:10](../enterprise/hr_payroll/data/hr_salary_rule_data.xml#L10),
[:27](../enterprise/hr_payroll/data/hr_salary_rule_data.xml#L27)). A holiday line whose type has no
category is therefore missing from GROSS whenever Work hours exist. Give the type the BASIC
category, or write the BASIC rule so it sets the category itself, as `geo_payroll` does
([payroll_structure_data.xml:78](../custom_addons/gec_odoo_modules/geo_payroll/data/payroll_structure_data.xml#L78)).

**Deferral does not apply.** The payroll filter that hides blocked leaves from closed periods acts
on employee leaves only ([hr_version.py:707](../enterprise/hr_payroll/models/hr_version.py#L707)).

**Draft payslips need a refresh** to see a new or moved holiday. Refresh skips payslips flagged
`edited` ([hr_payslip.py:1331](../enterprise/hr_payroll/models/hr_payslip.py#L1331)).

---

## Working on a Public Holiday (Overtime)

Odoo has no built-in holiday premium. What happens depends on the time rules:

- Rules apply on public holidays by default (`apply_on_public_holidays = True`,
  [hr_time_rule.py:182](../addons/hr_work_entry/models/hr_time_rule.py#L182)).
- Schedule-based thresholds subtract holidays from the expected hours
  ([hr_time_rule.py:953](../addons/hr_work_entry/models/hr_time_rule.py#L953)), so on a holiday
  the expected time is zero.
- Result with the shipped generic rule "Employee Schedule Rule" (Work → Overtime,
  [hr_time_rule_data.xml:4](../addons/hr_work_entry/data/hr_time_rule_data.xml#L4)): every
  validated hour worked on the holiday becomes **Overtime `040.00`**. That type is named "150%" but
  ships at rate 1.0 ([hr_work_entry_type_data.xml:12](../addons/hr_work_entry/data/hr_work_entry_type_data.xml#L12)).
- If law requires a premium, add a holiday-only rule with its own output type and rate — Jordan's
  "Public Holidays Overtime" is the stock pattern
  ([hr_time_rule_data.xml:69](../addons/hr_work_entry/data/hr_time_rule_data.xml#L69)). Setting
  `apply_on_public_holidays = False` on other rules keeps them off holiday days
  ([_build_rule_day_intervals](../addons/hr_work_entry/models/hr_time_rule.py#L507)).

Mechanics of rules: [`work_entries.md`](work_entries.md) and
[`attendance_work_entry.md`](attendance_work_entry.md).

---

## Security & UI

- Every internal user can read all public holidays of their companies
  ([hr_holidays ir.access.csv:69](../addons/hr_holidays/security/ir.access.csv#L69)).
- Time Off Officers have unrestricted create/write/delete
  ([:68](../addons/hr_holidays/security/ir.access.csv#L68)). The Company Holidays menu is for Time
  Off Administrators only, but a menu is not a security boundary.
- A company restriction applies to every row
  ([resource ir.access.csv:11](../addons/resource/security/ir.access.csv#L11)).
- "Generate Time Off / Multiple Requests" is a different tool: it creates real `hr.leave`
  requests per employee, with allocations and approvals.

---

## Georgian Setup Checklist

1. Log into the Georgian company. Create the year's holidays by hand, with Working Hours empty
   when all schedules follow Tbilisi time. Do it before the January payslips are computed.
2. Keep the generic `006.00` Public holiday type (rate 100%). `geo_payroll` structures put it in
   GROSS through their own BASIC rule. Do not give any time type the country Georgia (see Gotchas).
3. Decide the accrual policy and tick *Eligible for Accrual Rate* on the holidays if holidays
   must earn leave.
4. Check which time rules apply on holidays and what rate their output types pay.
5. After a late change: refresh the affected draft payslips; if a validated or paid period is
   touched, correct it through a payslip correction instead.

---

## Gotchas & Non-Obvious Behavior

- **One Georgian time type hides all the others.** Leave requests, allocations, accrual plans,
  schedule lines, public holidays, the loader wizard and payroll structure types offer only the
  country's types as soon as one active type with that country exists
  ([hr_leave.py:322](../addons/hr_holidays/models/hr_leave.py#L322),
  [res_company.py:23](../addons/hr_work_entry/models/res_company.py#L23),
  [hr_payroll_structure_type.py:79](../enterprise/hr_payroll/models/hr_payroll_structure_type.py#L79)).
  Core does this on purpose: a localized country gets a complete set of its own
  ([hr_work_entry_type_data.xml](../addons/hr_work_entry/data/hr_work_entry_type_data.xml),
  32 countries, not Georgia), so Georgia runs on the generic types. Leave the country empty on
  every time type you create. `geo_payroll` shipped one Georgian type, `GE_PUBLIC_HOLIDAY`, until
  2026-09-24; as the only one, it left the time-off form with "Public Holiday" and nothing else.
  It is gone from the module data, but a database that installed it keeps the row: `-u geo_payroll`
  deletes it only when its external id is no longer `noupdate`, which hr_payroll's weekly cron
  "Payroll: Update data" causes
  ([hr_work_entry_type.py:88](../enterprise/hr_payroll/models/hr_work_entry_type.py#L88)).
  Otherwise archive it.
- **Retroactive edits rewrite leaves, not payslips.** A late holiday can refuse a validated leave
  and change balances, while validated payslips keep the old hours.
- **Cron-created holidays have date-only bounds.** The cron passes plain dates
  ([_prepare_public_holidays_data](../addons/hr_holidays/models/resource_calendar_leaves.py#L152)),
  so start and end are both midnight UTC. Only the wizard converts a day to local 00:00–23:59:59.
  Irrelevant for Georgia (no data file) but worth checking for other countries.
- **Company scope.** A holiday belongs to the company you were logged into when the calendar is
  empty. Payslip generation searches calendar leaves of the version's company or none
  ([_get_leave_domain](../addons/hr_work_entry/models/hr_version.py#L60)).
- **Planning edits.** `planning_holidays` recomputes shift hours on write only when the keys
  `resource_ids`, `start_datetime` or `end_datetime` change — fields a holiday does not have
  ([resource_calendar_leave.py:73](../enterprise/planning_holidays/models/resource_calendar_leave.py#L73)).
  Moving a holiday leaves Planning hours stale until the shifts are touched.
- **Holiday timesheet lines are ordinary lines to validation.** They are read-only for users
  ([account_analytic.py:19](../addons/project_timesheet_holidays/models/account_analytic.py#L19)),
  but timesheet validation does not skip them, and a holiday edit deletes and recreates them in
  sudo whether validated or not. Any payroll rule that pays timesheets must exclude lines with
  `holiday_id` or `global_leave_id`.
- **Fully flexible employees get about 24 h per holiday day**, which a fixed-wage structure then
  prices against the slip's own hours.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_holidays.md`](hr_holidays.md) — time off, allocations, the loader wizard and cron
- [`work_entries.md`](work_entries.md) — the payslip projection and time rules
- [`resource_calendars.md`](resource_calendars.md) — calendar leaves in the interval engine
- [`attendance_work_entry.md`](attendance_work_entry.md) — attendance and overtime
- [`payroll_wage_types.md`](payroll_wage_types.md) — how worked-day hours are priced
- [`hr_payroll.md`](hr_payroll.md) — payslip lifecycle and corrections
- [`timesheets.md`](timesheets.md) — timesheet validation
- [`geo_payroll.md`](geo_payroll.md) — Georgian structures
