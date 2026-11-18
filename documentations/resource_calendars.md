# Resource Calendars — The Time Math Engine

> **Module:** `resource` (community core) | **Path:** [`addons/resource/models/`](../addons/resource/models/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

`resource.calendar` is the working schedule: "8 hours a day, Monday to Friday", "these dates only",
or "no fixed slots at all". Its interval engine answers every "how many hours or days of work are
there between two dates" question in Odoo: time off durations, accruals, time rules, attendance
expectations, planning, helpdesk SLAs, manufacturing and payroll.

Payroll depends on it in three places:

1. **The monthly wage rate.** A fixed-wage worked-day line is priced at
   wage x line hours / the calendar's scheduled hours in the payslip period
   ([hr_payslip_worked_days.py:90](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L90)).
2. **Days on the payslip.** `number_of_days` = hours / the calendar's `hours_per_day`
   ([hr_payslip.py:1356](../enterprise/hr_payroll/models/hr_payslip.py#L1356)).
3. **Whether a schedule exists at all.** The calendar type decides if the payslip projection has
   scheduled hours to fill.

The module has no business menu of its own (`category: Hidden`,
[__manifest__.py:6](../addons/resource/__manifest__.py#L6)). HR exposes it as Employees →
Configuration → Working Schedules.

---

## The Model Family

| Model | What it is | Key point |
|---|---|---|
| `resource.calendar` | A working schedule plus the interval engine | Every company gets a "40 hours/week" calendar at creation ([res_company.py:42](../addons/resource/models/res_company.py#L42)) |
| `resource.calendar.attendance` | One work slot: a weekday (fixed) or a date with optional recurrence (variable) | Entered as a time range or as a duration only |
| `resource.calendar.leaves` | A calendar exception: a public holiday (no resource) or one resource's absence | Validated `hr.leave` records materialize here; `count_as` decides absence vs worked time |
| `resource.resource` | The schedulable thing (person or machine) | `calendar_id` and `tz` are **required** ([resource_resource.py:52](../addons/resource/models/resource_resource.py#L52)) |
| `resource.mixin` | Abstract glue that creates one resource per record | `hr.employee` inherits it; its company, calendar and timezone are related to the resource ([resource_mixin.py:21](../addons/resource/models/resource_mixin.py#L21)) |
| `res.company` | Default calendar and a timezone | `tz` is computed from the country when the country has one timezone, else from the user ([res_company.py:20](../addons/resource/models/res_company.py#L20)). A Georgian company gets `Asia/Tbilisi` |

`resource.calendar.tz` does not exist in 20.0; use `hr.version.tz` or `res.company.tz`.

---

## The Three Calendar Types

`calendar_type` ([resource_calendar.py:78](../addons/resource/models/resource_calendar.py#L78)) is
the first decision on the form. It changes which lines exist and how every number is computed.

| | Fixed | Variable | Undefined |
|---|---|---|---|
| Lines | Undated, one set per weekday | Dated lines, each optionally recurring every N days or weeks, forever / N times / until a date, with excluded occurrences | None |
| `hours_per_week`, `days_per_week` | Computed from the lines | Typed by the user | Typed by the user (may be 0) |
| What the engine returns | The weekday lines on every matching day | The lines whose date or recurrence matches the day ([_filter_by_date](../addons/resource/models/resource_calendar_attendance.py#L382)) | Synthetic hours (see below) |
| Typical use | Office Mon–Fri | Rotations, one-off schedules, alternating weeks | Freelance-like, "work whenever" |

- **Flexible** means an Undefined calendar with an hours target
  ([_is_flexible](../addons/resource/models/resource_calendar.py#L96)).
  **Fully flexible** means Undefined with no `hours_per_week` and no `hours_per_day`
  ([_is_fully_flexible](../addons/resource/models/resource_calendar.py#L100)).
- Every resource and every `hr.version` must have a calendar
  ([hr_version.py:159](../addons/hr/models/hr_version.py#L159)). An empty Working Hours field does
  not exist in 20.0; use an Undefined calendar.
- `two_weeks_calendar` does not exist in 20.0; use a Variable calendar with a 2-week recurrence.
- **Switching type deletes lines.** After every create and write, lines that do not fit the type
  are unlinked: Fixed drops dated lines, Variable drops undated lines, Undefined drops all lines
  ([_get_attendances_to_unlink](../addons/resource/models/resource_calendar.py#L105),
  [:278](../addons/resource/models/resource_calendar.py#L278)). The form's radio asks for
  confirmation first.

---

## The Fields That Drive the Math

| Field | How it is computed | Why payroll cares |
|---|---|---|
| `hours_per_week` | Fixed: sum of `duration_hours` of work-period lines ([:212](../addons/resource/models/resource_calendar.py#L212)). Other types: typed, 0–168 ([:230](../addons/resource/models/resource_calendar.py#L230)) | Denominator of `work_time_rate`; weekly target of flexible calendars |
| `days_per_week` | Fixed: number of distinct weekdays with a work-period line ([:197](../addons/resource/models/resource_calendar.py#L197)). Other types: typed | Divisor of `hours_per_day` |
| `hours_per_day` | `hours_per_week / days_per_week` ([:207](../addons/resource/models/resource_calendar.py#L207)) | Converts payslip hours into days; reference for half-day counting |
| `full_time_required_hours` ("Full Time Equivalent") | Reference calendar's `hours_per_week`, else the company calendar's, else its own ([:172](../addons/resource/models/resource_calendar.py#L172)) | Full-time benchmark. A typed value is overwritten when those hours change |
| `work_time_rate` / `is_fulltime` | `hours_per_week / full_time_required_hours`, a ratio (1.0 = 100%, 1.0 when no benchmark); full time = equal at 3 digits ([:241](../addons/resource/models/resource_calendar.py#L241)) | Part-time detection. Payroll's `hr.version.work_time_rate` is own hours ÷ reference calendar hours, rounded to 2 digits ([hr_version.py:402](../enterprise/hr_payroll/models/hr_version.py#L402)) |
| `reference_calendar_id` | Defaults to the company calendar | Which schedule counts as "full time" |

A weekday with only a morning slot still counts as one full weekday. Mon–Fri 8 h plus Saturday
4 h gives 44 / 6 = 7.33 `hours_per_day`, which lowers the day count on every payslip line of
employees on that calendar.

---

## Attendance Lines (`resource.calendar.attendance`)

- **Time range or duration.** A line with `hour_from = hour_to = 0` is *duration based*
  ([_compute_duration_based](../addons/resource/models/resource_calendar_attendance.py#L301)).
  The engine places it around noon: an 8 h duration becomes 08:00–16:00, and several duration
  lines on one day stack around 12:00. The default lines of a new fixed calendar are five 8 h
  duration lines, Monday to Friday ([_get_default_attendance_ids](../addons/resource/models/resource_calendar.py#L686)).
- **`day_period`** is computed: `full_day` when the line lasts more than 75% of `hours_per_day`
  or is duration based, otherwise `morning` or `afternoon` by its position around 12:00
  ([_compute_day_period](../addons/resource/models/resource_calendar_attendance.py#L306)).
  Half-day leaves use it.
- **Per-day rules** ([_check_attendance_for_date](../addons/resource/models/resource_calendar_attendance.py#L102)):
  at most 24 h per day, no overlap, and no mix of duration-based and time-based lines on one day.
  Each line lasts more than 0 and at most 24 h ([:76](../addons/resource/models/resource_calendar_attendance.py#L76)).
  The overlap check locks the calendar row so two concurrent saves cannot both pass
  ([_lock_calendars_for_overlap_check](../addons/resource/models/resource_calendar_attendance.py#L120));
  a variable calendar whose recurrences collide in more than 1000 ways is refused as "Too Complex Calendar".
- **Editing one occurrence of a recurrence** goes through `exclude_occurence`, `create_ad_hoc`
  (detach one date) or `create_new_recurrency` (change the series from a date on)
  ([resource_calendar_attendance.py:418](../addons/resource/models/resource_calendar_attendance.py#L418)).
- **Monthly clean-up.** The cron "Resource: Clean up calendar attendances"
  ([ir_cron.xml](../addons/resource/data/ir_cron.xml)) deletes lines that do not fit their
  calendar type, drops stale excluded dates and turns a recurrence with one occurrence left into a
  plain dated line ([_calendar_clean_up](../addons/resource/models/resource_calendar.py#L160)).
- **Time type per line.** `hr_work_entry` adds `work_entry_type_id`
  ([resource_calendar_attendance.py:13](../addons/hr_work_entry/models/resource_calendar_attendance.py#L13)),
  so a schedule can emit its own payroll type ("Saturday = Site Day"). A line whose type counts
  as absence is left out of `hours_per_week` and `days_per_week`
  ([_is_work_period](../addons/hr_work_entry/models/resource_calendar_attendance.py#L64)) and is
  subtracted from work intervals ([resource_calendar.py:38](../addons/hr_work_entry/models/resource_calendar.py#L38)),
  but the day keeps its whole span as the reference for half-day counting
  ([_get_reference_hours_per_day](../addons/hr_work_entry/models/resource_calendar.py#L23)).
  The choice is limited to the company country's types; see the gotcha below.
  Full story: [`work_entries.md`](work_entries.md).

---

## Calendar Exceptions (`resource.calendar.leaves`)

| Axis | Values | Effect |
|---|---|---|
| `resource_id` | Empty = public holiday / set = one resource's absence | A public holiday hits every resource of the same company on the calendar; a resource leave hits that resource only |
| `calendar_id` | Empty = every calendar of the company / set = that calendar | For resource leaves it follows the resource's calendar ([:52](../addons/resource/models/resource_calendar_leaves.py#L52)); `hr` stamps the calendar of the employee version active at `date_from` ([resource_calendar_leaves.py:12](../addons/hr/models/resource_calendar_leaves.py#L12)) |
| `count_as` | `absence` (default) / `working_time` ([:48](../addons/resource/models/resource_calendar_leaves.py#L48)) | The engine subtracts only `absence` rows by default. `working_time` rows (training) count as worked time in the payslip projection |

`company_id` is computed from the calendar ([:57](../addons/resource/models/resource_calendar_leaves.py#L57));
`hr_holidays` takes the employee's company of the linked leave first. `date_to` fills itself with
23:59:59 of the start day in the user's timezone, or the company's
([_compute_date_to](../addons/resource/models/resource_calendar_leaves.py#L62)).

Where rows come from: validated time off creates one row per leave (`holiday_id` set) and
refusal or cancellation removes it; public holidays are entered by hand, loaded by a wizard or
created by a monthly cron. Their effects on leaves, time rules and payroll are in
[`public_holidays_flow.md`](public_holidays_flow.md).

---

## Resource ↔ Employee Wiring

- **Timezone lives on the version.** `resource.resource.tz` is computed from the employee's current
  version and writes back to it ([resource.py:30](../addons/hr/models/resource.py#L30)); the
  version's `tz` is required ([hr_version.py:162](../addons/hr/models/hr_version.py#L162)).
  All interval math is localized per resource timezone.
- **Calendar by date.** The engine asks each resource for its calendar and hours at the query
  start ([_get_calendar_data_at](../addons/hr/models/resource.py#L132)). For employees this
  resolves to the version in contract on that date
  ([_get_calendars](../addons/hr/models/hr_employee.py#L2001)); without a version in contract the
  resource's current calendar is used. Details: [`hr_employee_versions.md`](hr_employee_versions.md).
- **Guards added by `hr`.** A calendar used by versions of companies the user is not logged into
  cannot be written ([resource_calendar.py:21](../addons/hr/models/resource_calendar.py#L21)),
  and its company cannot change to one incompatible with those versions
  ([:15](../addons/hr/models/resource_calendar.py#L15)). The employee form can duplicate a
  calendar and assign the copy to that employee
  ([action_duplicate_and_apply_to_employee](../addons/hr/models/resource_calendar.py#L67)).
- `transfer_leaves_to` ([resource_calendar.py:50](../addons/hr/models/resource_calendar.py#L50))
  has no caller outside tests: changing an employee's calendar does not move their leave rows.

### The day-math API (what HR code calls)

| Method | Returns | Fully flexible calendar |
|---|---|---|
| `_get_work_days_data_batch(from, to)` ([resource_mixin.py:91](../addons/resource/models/resource_mixin.py#L91)) | `{employee_id: {'days', 'hours'}}` of work time | Every calendar day in the range counts as one day of up to 24 h, minus leaves |
| `_get_leave_days_data_batch(from, to)` ([:130](../addons/resource/models/resource_mixin.py#L130)) | Same shape, work time ∩ leaves | The whole period is leave |
| `_list_work_time_per_day(from, to)` | `(day, hours)` per record; honours the `compute_leaves` context | Same synthetic hours as above |
| `_adjust_to_calendar(start, end)` ([resource_resource.py:118](../addons/resource/models/resource_resource.py#L118)) | Nearest schedule boundaries on those days | — |

All accept a `calendar` argument that replaces the record's own calendar; `hr.leave` uses it to
compute durations against a given schedule.

---

## The Interval Engine

All three batch methods need timezone-aware datetimes and return `{resource_id: Intervals}` of
`(start, stop, record)`. Called on a calendar, the result also holds a calendar-only entry under
key `False`.

**`_attendance_intervals_batch`** ([resource_calendar.py:287](../addons/resource/models/resource_calendar.py#L287)) —
the theoretical schedule. It fetches the lines per date ([_get_attendances_by_date](../addons/resource/models/resource_calendar.py#L860)),
builds one interval per line and day, clips to the query, then branches per resource on the
calendar in force at the query start:

- **Fixed / Variable:** the line intervals.
- **Fully flexible:** one interval covering the whole query
  ([:383](../addons/resource/models/resource_calendar.py#L383)).
- **Flexible:** synthetic days. It walks 7-day windows from the query start and gives each day
  `min(hours_per_day, hours left in the week)`, centred on 12:00
  ([:390](../addons/resource/models/resource_calendar.py#L390)). A query that starts inside a
  window assumes the earlier days of that window were worked in full.

**`_leave_intervals_batch`** ([:468](../addons/resource/models/resource_calendar.py#L468)) —
searches calendar leaves with `count_as = absence` by default
([:474](../addons/resource/models/resource_calendar.py#L474)), on this calendar or none, for these
resources or none. A public holiday applies to a resource only when their companies are equal
([:506](../addons/resource/models/resource_calendar.py#L506)). A flexible resource's own leave is
widened to whole local days.

**`_work_intervals_batch`** ([:525](../addons/resource/models/resource_calendar.py#L525)) —
attendance minus leaves; `hr_work_entry` also subtracts absence-type schedule lines.
`_unavailable_intervals_batch` ([:552](../addons/resource/models/resource_calendar.py#L552)) is the
complement; a flexible resource gets only its leave intervals
([:563](../addons/resource/models/resource_calendar.py#L563)).

**Day counting** — `_get_attendance_intervals_days_data` ([:583](../addons/resource/models/resource_calendar.py#L583))
splits intervals per calendar day. A day made of duration-based lines counts
hours ÷ that day's line total. Any other day counts **1 if its hours exceed 3/4 of the reference
day, else 0.5** ([:615](../addons/resource/models/resource_calendar.py#L615)). The sum is rounded
to 0.001 day.

**External API** — `get_work_hours_count` (date inputs are read in the company timezone,
[:699](../addons/resource/models/resource_calendar.py#L699)), `get_work_duration_data`
([:739](../addons/resource/models/resource_calendar.py#L739)), `plan_hours` / `plan_days` (walk
14-day chunks, at most 100, [:764](../addons/resource/models/resource_calendar.py#L764)),
`_get_unusual_days` (grey days in calendar views; for a flexible resource only leave days,
[:666](../addons/resource/models/resource_calendar.py#L666)) and `_works_on_date` (always true for
a flexible calendar, [:854](../addons/resource/models/resource_calendar.py#L854)).

---

## Consumer Map — Who Calls the Engine

| Business feature | Calls | Where |
|---|---|---|
| Fixed-wage rate on the payslip | `_work_intervals_batch(compute_leaves=False)` over the payslip period; Undefined calendars fall back to the slip's own non-extra hours | [hr_payslip_worked_days.py:66](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66) |
| Payslip days | `calendar.hours_per_day` | [hr_payslip.py:1356](../enterprise/hr_payroll/models/hr_payslip.py#L1356) |
| Out-of-contract line | `get_work_duration_data` on the version calendar (company calendar for flexible ones) | [hr_payslip.py:1365](../enterprise/hr_payroll/models/hr_payslip.py#L1365), [:1418](../enterprise/hr_payroll/models/hr_payslip.py#L1418) |
| Payslip time projection | `_attendance_intervals_batch`; absence durations from `_get_work_days_data_batch(compute_leaves=False)` | [hr_version.py:72](../addons/hr_work_entry/models/hr_version.py#L72), [:493](../addons/hr_work_entry/models/hr_version.py#L493) |
| Time rule thresholds | `_attendance_intervals_batch`, `_leave_intervals_batch` | [hr_time_rule.py:422](../addons/hr_work_entry/models/hr_time_rule.py#L422) |
| Time off durations | `_list_work_time_per_day`, `_get_work_days_data_batch`, `get_work_hours_count` | [hr_leave.py:904](../addons/hr_holidays/models/hr_leave.py#L904) |
| Half-day leave hours | `hr.employee._get_hours_for_date` | [hr_employee.py:848](../addons/hr_holidays/models/hr_employee.py#L848) |
| Accruals on worked time | `_get_work_days_data_batch`, `_get_leave_days_data_batch` | [hr_leave_allocation.py:526](../addons/hr_holidays/models/hr_leave_allocation.py#L526) |
| Expected attendance (tolerance validation, auto check-out) | `hr.employee._get_expected_attendances` | [hr_employee.py:2261](../addons/hr/models/hr_employee.py#L2261) |
| Grey days in calendar views | `hr.employee._get_unusual_days` | [hr_employee.py:2216](../addons/hr/models/hr_employee.py#L2216) |
| Planning allocation | `_get_valid_work_intervals` and the flexible helpers (locale weeks) | [resource_resource.py:196](../addons/resource/models/resource_resource.py#L196) |
| French and Indian time-off rules | `_works_on_date` | [l10n_fr hr_leave.py:145](../addons/l10n_fr_hr_holidays/models/hr_leave.py#L145) |

---

## Multi-Company Notes

- `resource.calendar` has no company restriction: every internal user reads all calendars and HR
  Officers hold an unrestricted create/write/delete row
  ([resource ir.access.csv:2](../addons/resource/security/ir.access.csv#L2),
  [hr ir.access.csv:40](../addons/hr/security/ir.access.csv#L40)). The only barrier is `hr`'s
  write guard above.
- `resource.calendar.leaves` and `resource.resource` carry company restrictions
  ([resource ir.access.csv:7](../addons/resource/security/ir.access.csv#L7),
  [:11](../addons/resource/security/ir.access.csv#L11)).
- A calendar without company is visible to all companies. Its public holidays still carry the
  company that created them, so they reach only that company's resources in the engine.

---

## Gotchas & Non-Obvious Behavior

- **Half-day weekdays lower `hours_per_day`** for everyone on the calendar, which changes payslip
  day counts (not amounts; amounts are priced on hours).
- **The 3/4 threshold decides full vs half days.** On an 8 h calendar a 6 h day counts 0.5 day and
  a 6.5 h day counts 1.
- **Fully flexible employees count 24 h per calendar day** in `_get_work_days_data_batch` and in
  payslip absence durations. A one-day public holiday or leave on such a calendar can become a
  24 h line.
- **Flexible rolling windows start at the query date**, while planning's flexible helpers count
  locale calendar weeks — two week conventions for the same employee.
- **`full_time_required_hours` does not keep a typed value**; it follows the reference calendar.
- **Changing the calendar type deletes lines** that do not fit the new type, immediately on save.
- **Time types on schedule lines follow the company country.** As soon as one
  `hr.work.entry.type` with the company's country exists, only that country's types can be
  chosen ([_compute_allowed_work_entry_type_ids](../addons/hr_work_entry/models/resource_calendar_attendance.py#L22)).
  Georgia has no core set, so a single Georgian type (such as the `GE_PUBLIC_HOLIDAY` that
  `geo_payroll` shipped until 2026-09-24) takes the generic types away here; see
  [`public_holidays_flow.md`](public_holidays_flow.md).
- **Payslip projection and time-off math search leaves differently.** Work-entry generation builds
  its own calendar-leave domain from the version's company and calendar
  ([_get_leave_domain](../addons/hr_work_entry/models/hr_version.py#L60)) instead of
  `_leave_intervals_batch`; differences between a leave's duration and its payslip hours usually
  trace to this fork.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_employee_versions.md`](hr_employee_versions.md) — which version (and calendar) applies on a date
- [`work_entries.md`](work_entries.md) — the payslip projection and time types on schedule lines
- [`public_holidays_flow.md`](public_holidays_flow.md) — public holiday rows and their effects
- [`payroll_wage_types.md`](payroll_wage_types.md) — how hours and days become money
- [`hr_payroll.md`](hr_payroll.md) — payslip lifecycle
- [`attendance_work_entry.md`](attendance_work_entry.md) — attendance-based versus schedule-based pay
- [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md) — day/half-day/hour time-off units
- [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md) — accruals over worked time
