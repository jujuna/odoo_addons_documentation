# Time Off Duration Units — Days, Half-Days, Hours

> **Module:** `hr_holidays` | **Path:** [`addons/hr_holidays/`](../addons/hr_holidays/)
> Scope: how the Day / Half-Day / Hours unit works across time types, allocations, requests, and balances. Accrual plans have their own doc: [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md).

> **Changed in 20.0 — the model moved.** `hr.leave.type` no longer exists. Time off types are now records of **`hr.work.entry.type`**, extended by `hr_holidays` in [`hr_work_entry_type.py`](../addons/hr_holidays/models/hr_work_entry_type.py) (the old `hr_leave_type.py` was renamed). On `hr.leave` and `hr.leave.allocation` the type link is `work_entry_type_id`, not `holiday_status_id`. Everything below is 20.0.

## What Controls the Unit — Two Fields, Not One

**Changed in 20.0:** the single `request_unit` no longer decides everything. The type carries two independent unit fields, both radios on the type form after "Count as" ([`hr_work_entry_type_views.xml:39`](../addons/hr_holidays/views/hr_work_entry_type_views.xml#L39)) — the form is an inherit of `hr_work_entry.hr_work_entry_type_view_form`, so they sit mid-form, not at the top:

| Field | Label | Values | Drives |
|---|---|---|---|
| `unit_of_measure` ([`:94`](../addons/hr_holidays/models/hr_work_entry_type.py#L94)) | **Unit** | `hour` (default) / `day` | Allocation entry, balances, dashboard, accrual, negative cap |
| `request_unit` ([`:88`](../addons/hr_holidays/models/hr_work_entry_type.py#L88)) | **Duration Type** | `day` "Full Day" (default) / `half_day` "Half-Day" / `hour` "Custom Hours" | The *finest granularity a request may use* |

A type can therefore be allocated in hours but requested only in full days, or the reverse. Selection labels changed too: `day` is now "Full Day" and `hour` is "Custom Hours".

## Per-Request Choice — New in 20.0

**Removed in 20.0:** `request_unit_hours` and `request_unit_half` on `hr.leave` are gone. The request now reads the type through the related `work_entry_type_request_unit` ([`hr_leave.py:242`](../addons/hr_holidays/models/hr_leave.py#L242)) and exposes a real per-request field, `request_duration` (`full` / `am` / `pm` / `specific`, [`hr_leave.py:268`](../addons/hr_holidays/models/hr_leave.py#L268)), rendered as a `selection_badge_with_filter` ([`hr_leave_views.xml:467`](../addons/hr_holidays/views/hr_leave_views.xml#L467)).

What the type permits is computed into `allowed_request_durations` ([`_get_allowed_request_durations`, `hr_leave.py:382`](../addons/hr_holidays/models/hr_leave.py#L382)):

| `request_unit` | Allowed `request_duration` |
|---|---|
| `day` | `full` |
| `half_day` | `full`, `am`, `pm` |
| `hour` | `full`, `am`, `pm`, `specific` |

So the type still caps the granularity, but an hour-type request can be booked as a plain full day or a half day without switching type. A multi-day request (`last_several_days`, [`hr_leave.py:1074`](../addons/hr_holidays/models/hr_leave.py#L1074)) is forced back to `full`.

## How Each Screen Changes

| Screen | Day type | Hour type |
|---|---|---|
| Time off request | Date range (`request_date_from/to`) + duration in days | **Datetime range** `request_date_hour_from → request_date_hour_to`, `daterange` widget ([`hr_leave_views.xml:434`](../addons/hr_holidays/views/hr_leave_views.xml#L434)); `number_of_hours` is directly editable ([`:455`](../addons/hr_holidays/views/hr_leave_views.xml#L455)) |
| Duration label | `N days` | `H:MM hours` ([`hr_leave.py:1095`](../addons/hr_holidays/models/hr_leave.py#L1095)) |
| Allocation | "Allocation: N **Days**" (`number_of_days_display`) | swaps to `number_of_hours` — "N **Hours**" ([`hr_leave_allocation_views.xml:172`](../addons/hr_holidays/views/hr_leave_allocation_views.xml#L172)) |
| Balance / type name / dashboard | remaining days | remaining hours — keyed on **`unit_of_measure`**, not `request_unit` ([`hr_work_entry_type.py:391`](../addons/hr_holidays/models/hr_work_entry_type.py#L391), [`time_off_card.xml:39`](../addons/hr_holidays/static/src/dashboard/time_off_card.xml#L39)) |

`request_hour_from` / `request_hour_to` still exist but are **plain Float fields** in 20.0 (no compute, [`hr_leave.py:251`](../addons/hr_holidays/models/hr_leave.py#L251)); the form keeps them invisible and the datetime pair writes through to them. `date_from` / `date_to` are then built from `request_date_from` + those hours, stamped to UTC in `_compute_date_from_to` ([`hr_leave.py:712`](../addons/hr_holidays/models/hr_leave.py#L712)).

## Storage and Conversion — Days Are Still the Internal Unit

Hours remain a display layer; leaves and allocations store `number_of_days`. On allocations the hour field was **renamed `number_of_hours_display` → `number_of_hours`** ([`hr_leave_allocation.py:118`](../addons/hr_holidays/models/hr_leave_allocation.py#L118)):

- Days → hours: `number_of_days * _get_employee_hours_per_day()` ([`:273`](../addons/hr_holidays/models/hr_leave_allocation.py#L273))
- Hours → days (inverse): `number_of_hours / _get_employee_hours_per_day()` ([`:345`](../addons/hr_holidays/models/hr_leave_allocation.py#L345))
- `_get_employee_hours_per_day()` ([`:182`](../addons/hr_holidays/models/hr_leave_allocation.py#L182)) wraps `employee._get_hours_per_day(date)` ([`hr_employee.py:830`](../addons/hr_holidays/models/hr_employee.py#L830)), which reads the calendar's **"Average Hour per Day"** (`resource.calendar.hours_per_day`, [`resource_calendar.py:69`](../addons/resource/models/resource_calendar.py#L69)) and returns **24 for a fully-flexible calendar** ([`hr_employee.py:836`](../addons/hr_holidays/models/hr_employee.py#L836)).
- **New in 20.0:** a generic `_convert_duration(duration, src_unit, dst_unit)` plus `_convert_to_/_convert_from_type_request_unit` ([`:427`](../addons/hr_holidays/models/hr_leave_allocation.py#L427)) centralise every × / ÷ `hours_per_day`; accrual and carryover code goes through them.

**Changed in 20.0 — where `hours_per_day` comes from.** It is no longer summed off attendance lines directly: it is now `hours_per_week / days_per_week` ([`_compute_hours_per_day`, `resource_calendar.py:207`](../addons/resource/models/resource_calendar.py#L207)), and the compute **only runs for `calendar_type == 'fixed'`**. On `variable` and `undefined` calendars the user sets it by hand (constrained 0–24, [`:237`](../addons/resource/models/resource_calendar.py#L237)).

**Changed in 20.0 — "fully flexible" is no longer "no calendar".** `_is_fully_flexible()` ([`resource_calendar.py:103`](../addons/resource/models/resource_calendar.py#L103)) means `calendar_type == 'undefined'` **and** no `hours_per_week` **and** no `hours_per_day`. An undefined calendar that carries an hours target is not fully flexible and does not get the 24.

So a 24-day entitlement on an 8 h/day schedule is allocated as **192 hours**, stored as 24 days, and a 2-hour request consumes 0.25 day internally.

## Worked Example — "24 days, taken by the hour"

1. Time Off > Configuration > Time Types: on the type set **Unit = Hours** and **Duration Type = Custom Hours** (Requires Allocation stays on).
2. New Allocation for the employee: the duration field reads Hours — enter **192** (24 × 8).
3. Employee requests: picks the type, then `request_duration = Specific`, and drags the datetime range 09:00 → 11:00. Duration shows **2:00 hours**; balance drops 192 h → 190 h.
4. Prerequisite: the employee's working schedule averages 8 h/day; the conversion uses that number, not a hardcoded 8.

## Gotchas & Non-Obvious Behavior

- **Two units can disagree.** `unit_of_measure` defaults to `hour` while `request_unit` defaults to `day`, so a freshly created type allocates in hours but is requested in full days. This is the single most common surprise in 20.0.
- **Accrual allocations ignore the type's unit entirely.** `_get_request_unit()` ([`hr_leave_allocation.py:381`](../addons/hr_holidays/models/hr_leave_allocation.py#L381)) returns the **accrual plan's** `added_value_type` when a plan is set, and only falls back to the type's `unit_of_measure` otherwise. A plan granting "1 day per month" shows the allocation in days even on an hour type.
- **Flexible employees skew conversions.** Fully-flexible calendar → 24 h/day divisor; 192 h becomes 8 days instead of 24. Give the employee a fixed 8 h calendar, or set `hours_per_day` on the undefined one, before allocating.
- **Hours are recomputed from days.** `number_of_hours` is derived from stored days × current calendar average; changing the calendar's hours/day changes the displayed hours of existing allocations.
- **Editing hours on a request writes back.** `hr.leave.number_of_hours` gained an inverse in 20.0 ([`hr_leave.py:1209`](../addons/hr_holidays/models/hr_leave.py#L1209)) that replans the end date in worked hours — typing a duration is now a supported entry path, not just a readout.
- **Changing the type's unit retro-affects existing records' display.** The related `work_entry_type_request_unit` and the allocation's computed `type_request_unit` re-render in the new unit. Days stored internally stay consistent, so no data migration is needed.
- **Half-day mode**: `request_unit = 'half_day'`, AM/PM picked via `request_duration` on a single day, or via `request_date_from_period` / `request_date_to_period` when the request spans several days ([`hr_leave_views.xml:445`](../addons/hr_holidays/views/hr_leave_views.xml#L445)).
- **`duration_display` shows hours beyond hour types.** Day/half-day leaves split or trimmed by a time rule also render `H:MM hours` when they land under a full day ([`hr_leave.py:1095`](../addons/hr_holidays/models/hr_leave.py#L1095)).

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md) — accruals grant balances into these same allocations; the plan's `added_value_type` wins on accrual allocations
- [`hr_payroll.md`](hr_payroll.md) — validated leaves become work entries; the time type *is* the work entry type in 20.0
