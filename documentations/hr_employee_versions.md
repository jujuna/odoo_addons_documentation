# Employee & Version Engine — `hr.employee` / `hr.version`

> **Module:** `hr` (community core) + employee-side pieces of `hr_attendance` / `planning` | **Path:** [`addons/hr/`](../addons/hr/)
> **Odoo 20.0.** Verified from source 2026-09-22. Related docs: [`hr_payroll.md`](hr_payroll.md), [`work_entries.md`](work_entries.md), [`resource_calendars.md`](resource_calendars.md).

## What It Does & Why It Exists

There is no `hr.contract` model in Odoo 20 (unchanged from 19 — it did not come back). All contract data — wage, calendar, structure type, contract dates — lives on `hr.version`, and an employee is a **timeline of versions**: each version says "from this date, these are the employee's terms". The employee form is a window onto one version at a time. Understanding this engine is mandatory for payroll work: payslips, work entries, and calendars all resolve "which version was in force on date X".

**Changed in 20.0:** the model is still `hr.version`, but its `_description` is now *Employee Record* and `date_version` is labelled *Effective Date*. Everything the UI calls an "employee record" in 20.0 is a version in this doc.

---

## The Big Picture — How Versions Work

```
hr.employee ──_inherits──> hr.version (via version_id, COMPUTED, not stored)
    version_ids (o2m, ordered by date_version)
    current_version_id (STORED compute: latest version with date_version <= today)
```

- `hr.employee` delegates to `hr.version` with a twist: `version_id` is a **computed, non-stored** many2one ([hr_employee.py:55](../addons/hr/models/hr_employee.py#L55)). If the context carries `version_id` (smart buttons on the version timeline do this), the form transparently reads *and writes* that historical version; otherwise it's the current one. **New in 20.0:** the field carries `compute_sql='_compute_sql_version_id'`, which simply resolves to the stored `current_version_id` column so that `_inherits` still works in SQL ([hr_employee.py:787](../addons/hr/models/hr_employee.py#L787)).
- **A version is in force from its `date_version` until the day before the next version's `date_version`**, clipped by contract end: `date_start = max(date_version, contract_date_start)`, `date_end = min(next.date_version − 1, contract_date_end)` ([hr_version.py:577](../addons/hr/models/hr_version.py#L577)). In 20.0 the "next version" lookup is batched over the whole recordset and restricted to *active* versions.
- `_get_version(date)`: latest version with `date_version <= date`; before the first version it returns the earliest one ([hr_employee.py:792](../addons/hr/models/hr_employee.py#L792)). Ties are impossible (unique index employee+date_version for active versions); gaps don't exist by construction.
- `current_version_id` is a **stored compute keyed on "today"**, refreshed by a daily cron `_cron_update_current_version_id` ([hr_employee.py:757](../addons/hr/models/hr_employee.py#L757), cron record in [hr_data.xml:109](../addons/hr/data/hr_data.xml#L109)) — between midnight and the cron run, the stored value can be stale. The cron is `model.search([])._compute_current_version_id()`: it recomputes every employee, every day.

### How writes are routed (employee vs version)

The split key is `field.inherited`: on employee create/write, all inherited-from-version values are peeled off and written to the resolved `version_id` in one call, stamping `last_modified_date/_uid` and setting a chatter log message `As of <start> to <end>` ([hr_employee.py:1877](../addons/hr/models/hr_employee.py#L1877)). Fields needing group protection are re-declared on the employee with explicit `inherited=True`. Silent behavior: on create, version fields the user can't write are **dropped without error** — `_prepare_create_values` filters the version half of the vals against `has_field_access(..., 'write')` ([hr_employee.py:399](../addons/hr/models/hr_employee.py#L399)).

**Changed in 20.0:** the contract-dates block (`contract_date_start/end`, `trial_date_end`, `date_start/date_end`, `is_current/is_past/is_future/is_in_contract`) moved from `hr.group_hr_manager` down to **`hr.group_hr_user`** ([hr_employee.py:267](../addons/hr/models/hr_employee.py#L267)). Any custom code that assumed only HR managers could read contract dates is now wrong.

**New in 20.0 — fan-out to later versions.** Editing a version-related field on the employee form while *not* on the chronologically last version pops a confirmation dialog: *This version* / *Change all* / *Cancel*. "Change all" writes the same values to every version from the edited one forward and re-saves with `multi_update_version_ids` in the context, which widens the chatter "As of …" range to cover the whole run ([form_view.js:44](../addons/hr/static/src/views/form_view.js#L44)). Contract start/end are explicitly excluded from this fan-out (they have their own sync path, below).

### Payroll "Version update" dialog (new in 20.0, `hr_payroll`)

The mirror case of the fan-out dialog: you are on the **latest** version and it already has validated or paid payslips. Payroll asks whether the edit is a real change of terms (**Create new version** from a date) or a fix of a mistake (**Correct the current version**, which also affects those payslips). It exists so a raise entered in October does not silently rewrite the September payslips.

**When it opens** — on the first field change of an edit session, not on save ([version_record_patch.js:15](../enterprise/hr_payroll/static/src/js/version_record_patch.js#L15)). It stays closed when any of these holds:

| Skip condition | Where |
|---|---|
| The employee is new (not saved yet) | `!record.resId` |
| A choice was already made in this edit session (reset on save/discard) | `this.versionChoice` |
| Every pending change is `contract_date_end` or `resource_calendar_id` | `EXCLUDED_FIELDS`, [:7](../enterprise/hr_payroll/static/src/js/version_record_patch.js#L7) |
| The form shows no version | `!version_id` |
| A version with a later `date_version` exists (you are on an older one) | `action_check_version_status`, [hr_version.py:754](../enterprise/hr_payroll/models/hr_version.py#L754) |
| The version has no payslip in `validated`/`paid` (draft/computed do not count) | `_get_valid_payslips_count`, [hr_version.py:642](../enterprise/hr_payroll/models/hr_version.py#L642) |

The exclusion check looks at **all pending changes of the form**, not only the last field touched.

**What each button does**

| Choice | Result |
|---|---|
| Correct the current version | Normal save, nothing else. |
| Create new version | On save, `action_create_version_from_update` copies the version, applies the changes that are `hr.version` fields, creates it via `create_version`, then **discards the form** ([version_record_patch.js:55](../enterprise/hr_payroll/static/src/js/version_record_patch.js#L55), [hr_version.py:769](../enterprise/hr_payroll/models/hr_version.py#L769)). Date must be after the current version start and not in the future. |
| Discard / close | All pending changes on the form are discarded. |

**Pitfall — employee-only fields.** Unlike the core fan-out dialog, which keeps only fields whose `related` points to `version_id`, this one only excludes two fields. Editing a phone, tags, or a custom `hr.employee` one2many such as `geo_payroll` work logs ([hr_employee.py:35](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_employee.py#L35)) opens it. Choosing *Create new version* for such an edit creates a copy of the version with no change and **throws the edit away**; choose *Correct the current version*. The default date is also broken (`"2026-09-" + "-01"` = `2026-09--01`), so the date field opens empty.

### Creating versions

`create_version(values)` ([hr_employee.py:804](../addons/hr/models/hr_employee.py#L804)): finds the version in force at `date_version`, copies it, applies the diff. Traps:

- **A version already existing at that exact date is returned as-is and your `values` are silently discarded.**
- Contract dates are inherited from the contract in force at that date; changing `contract_date_end` in the same call first syncs it onto all sibling versions.
- **New in 20.0:** a `contract_template_id` passed in `values` is applied *after* the copy, through the template whitelist (below) — so template values win over the copied ones for whitelisted fields only.

`create_contract(date)` ([hr_employee.py:881](../addons/hr/models/hr_employee.py#L881)) wraps this: if a version already exists on that exact date it just stamps `contract_date_start/end` on it instead of creating one, deriving the end date from the next contract's start − 1 day.

**New in 20.0 — bulk version creation wizard.** `hr.employee.create.version.wizard` ([hr_employee_create_version_wizard.py](../addons/hr/wizard/hr_employee_create_version_wizard.py)) is a list-view server action ("New Employee Records", bound on `hr.employee`, list view only — [hr_employee_views.xml:877](../addons/hr/views/hr_employee_views.xml#L877)). It asks for one date and calls `create_version({'date_version': date})` per selected employee. Deliberately minimal: no field values, so every new version is a pure copy-forward of whatever was in force on that date. The silent-discard trap above applies per employee — employees that already have a version on that date are no-ops.

---

## Contract Semantics

- A version **is a contract** iff `contract_date_start` is set; there is no state field — draft/open/close is gone, everything derives from dates (`is_current/is_past/is_future/is_in_contract`, all computed against `context_today` since 20.0).
- All versions of one contract share `contract_date_start/end`; **writing contract dates on one version fans out to all siblings** of that contract ([hr_version.py:333](../addons/hr/models/hr_version.py#L333)); for a single-version employee, writing `contract_date_start` also moves `date_version`. The recursion guard is the `sync_contract_dates` context key — set it and `write` becomes a plain write.
- Overlapping contract periods among active versions are forbidden (the error suggests a second employee record for concurrent contracts); sequential contracts are fine ([hr_version.py:250](../addons/hr/models/hr_version.py#L250)). A new contract is blocked while the current one is open-ended (`check_contract_finished`).
- The period tests payroll uses: `_get_versions_with_contract_overlap_with_period` (per employee, [hr_employee.py:2330](../addons/hr/models/hr_employee.py#L2330)) and the all-employees variant ([hr_employee.py:2209](../addons/hr/models/hr_employee.py#L2209)). **Changed in 20.0:** that all-employees variant is now `self.search([])` — it **no longer includes archived employees**. Payroll code that relied on picking up departed staff must pass `active_test=False` itself.
- **New in 20.0 — `fixed_term`.** A boolean on the version, separate from `contract_date_end`. Clearing the end date clears it; setting an end date on a contract whose start did not change sets it. On the form, changing `contract_date_end` opens a `ContractEndDialog` that asks whether this is a *correction* (just set `fixed_term`) or an *end of collaboration* (opens the departure flow, below).
- Contract expiry notifications: daily cron `notify_expiring_contract_work_permit` ([hr_employee.py:1425](../addons/hr/models/hr_employee.py#L1425), cron in [hr_data.xml:100](../addons/hr/data/hr_data.xml#L100)). The activity goes to `hr_responsible_id`.
  **Changed in 20.0:** the match is now a **range** — `today <= contract_date_end <= today + company.contract_expiration_notice_period` — and activities are deduplicated on `(employee, deadline, responsible)` via `technical_usage='hr_expiring_contract'`. The 19.0 exact-equality trap (one missed cron day = permanently missed notification) is gone. The same cron handles work permits with `work_permit_expiration_notice_period`.

## Contract Templates

A template is simply an `hr.version` with `employee_id = False` (the Contract Templates action is literally `[('employee_id', '=', False)]`). Applying one — on `hr.version.create`, on the employee's `contract_template_id` onchange, from `create_version`, or from the template picker button on the form — passes through the whitelist `_get_whitelist_fields_from_template` ([hr_version.py:467](../addons/hr/models/hr_version.py#L467)).

**Changed in 20.0:** the base whitelist is **8 fields** — `job_id, department_id, employee_type_id, structure_type_id, wage, resource_calendar_id, reference_calendar_id, hr_responsible_id`. Two edits versus 19.0: `contract_type_id` became `employee_type_id` (the `hr.contract.type` model was replaced by `hr.employee.type`), and `reference_calendar_id` was added. The extenders also changed: `hr_payroll` no longer adds `work_entry_source`/`payroll_properties`; in 20.0 only `hr_attendance` (`attendance_based`) and a few localizations extend it.

**Everything not whitelisted is dropped** — the known trap for custom fields (and still for `hourly_wage` in stock payroll code): extending this whitelist is mandatory for any custom module adding version fields that hiring should carry over.

**Changed in 20.0:** the `hr.contract.template.wizard` transient model is gone. Loading a template is now a client-side popover on the form ([contract_template_button.js](../addons/hr/static/src/js/contract_template_button.js)) that writes the whitelisted values directly onto the record.

---

## Calendar, Resource, and Timezone Wiring

```
hr.version.resource_calendar_id   (STORED — the versioned truth)
    ↑ related/inherited, store=False
hr.employee.resource_calendar_id  (proxy through context/current version)
resource.resource.calendar_id     (materialized "current" calendar)
```

- Sync is **current-version-only**, three-way: version→resource only when the written version is current; employee.write→resource same guard; resource→employee writes back ([hr_version.py:699](../addons/hr/models/hr_version.py#L699), [hr_employee.py:1920](../addons/hr/models/hr_employee.py#L1920)). Editing a past/future version's calendar never touches the resource — anything reading `resource.calendar_id` directly sees only today's calendar; historical accuracy exists only through `_get_calendars(date)` / `_get_version_periods`.
- **Changed in 20.0 — `resource_calendar_id` is now `required=True` with a default of `env.company.resource_calendar_id`** ([hr_version.py:159](../addons/hr/models/hr_version.py#L159)). In 19.0 an empty calendar was a legal state meaning "fully flexible"; in 20.0 a version **always** has a calendar, and flexibility is a property of the calendar itself. The old "empty calendar + calendar work-entry source = silently zero payslip" trap no longer arises from an empty calendar; it now depends on the calendar's `calendar_type`.
- **Changed in 20.0 — flexibility moved to the calendar.** The version's stored `is_flexible` / `is_fully_flexible` compute fields are gone; they are now plain methods delegating to the calendar ([hr_version.py:440](../addons/hr/models/hr_version.py#L440)). On `resource.calendar`: `_is_flexible()` is `calendar_type == 'undefined'` (the `flexible_hours` boolean is gone), and `_is_fully_flexible()` is flexible **and** no `hours_per_week` **and** no `hours_per_day` ([resource_calendar.py:96](../addons/resource/models/resource_calendar.py#L96)). Full math consequences in [`resource_calendars.md`](resource_calendars.md).
- `_get_calendars(date)` returns the calendar of the version **in contract** on that date — if no contract covers the date it silently falls back to `super()`, i.e. today's resource calendar, not the version in force ([hr_employee.py:2001](../addons/hr/models/hr_employee.py#L2001)). Same shape for `_get_hours_per_week_batch` / `_get_hours_per_day_batch`.
- **Changed in 20.0 — tz IS versioned.** `hr.version.tz` is now a real stored `Selection` field (required, defaulting to context/user tz), not a related to the employee ([hr_version.py:162](../addons/hr/models/hr_version.py#L162)); the employee's `tz` is the inherited proxy onto it. Resolution: `version.tz` → employee's user-partner tz → company tz → UTC ([hr_version.py:715](../addons/hr/models/hr_version.py#L715)). `hr.employee._get_tz(date=...)` resolves the tz **of the version in force on that date** ([hr_employee.py:1988](../addons/hr/models/hr_employee.py#L1988)) — so a relocation is now history-correct, where 19.0 retro-applied the current tz to all past periods. Writing employee tz still propagates to the linked user.
- `employee.active` is a stored related to `resource_id.active` — archiving the employee archives the resource in one write. Versions have their own `active`; nothing archives them with the employee, and you can never archive/detach/delete the last one.

---

## Departure

**Rewritten in 20.0.** The transient `hr.departure.wizard` is gone. Departure is now a **persistent model**, `hr.employee.departure` ([hr_employee_departure.py](../addons/hr/models/hr_employee_departure.py)), which turns departure from a one-shot action into a scheduled process.

- The version no longer stores departure data. It carries a single `departure_id` many2one with `copy=False` ([hr_version.py:150](../addons/hr/models/hr_version.py#L150)); `departure_reason_id`, `departure_description`, `departure_date`, `dismissal_date` are **related** fields through it. Because `departure_id` is `copy=False`, departure still never leaks into a copied version — the mechanism just moved a level down.
- Three dates, not one: `dismissal_date` (process starts), `departure_date` (last day — computed from `dismissal_date`, overridable so notice-period localizations can extend it), and `action_date` (when the employee is actually archived, defaulting to `departure_date + 1`).
- `create()` back-links every version of the contract in force at `departure_date` to the departure and sets `contract_date_end = departure_date` on them (with `sync_contract_dates` so the fan-out does not recurse). It also stashes the previous `contract_date_end` on `last_contract_date_end` so the departure can be undone ([hr_employee_departure.py:109](../addons/hr/models/hr_employee_departure.py#L109)).
- **A daily cron `_cron_apply_departure`** ([ir_cron_data.xml](../addons/hr/data/ir_cron_data.xml), [hr_employee_departure.py:127](../addons/hr/models/hr_employee_departure.py#L127)) picks up departures whose `action_date` has arrived and calls `action_register()`, which archives the employee, archives the user **only if no other active employee is attached to it**, and **unlinks every version with `date_version > departure_date`** ([hr_employee_departure.py:142](../addons/hr/models/hr_employee_departure.py#L142)). Future-dated version planning is therefore destroyed by a departure, not just archived.
- Validation lives in a real `@api.constrains`: the departure date may not precede the current contract's start, and there must be a version starting before it.
- `hr.employee.action_new_departure` ([hr_employee.py:2461](../addons/hr/models/hr_employee.py#L2461)) refuses employees with no contract ("archive it instead"), and refuses a second departure while one is pending. `action_cancel_departure` unarchives, restores `last_contract_date_end` on the version in force, and deletes the departure record.

---

## Employee-Side Attendance & Planning (what payroll touches)

**Attendance** (`hr_attendance`) — **substantially reworked in 20.0.** The separate `hr.attendance.overtime` model is gone. Overtime and undertime are now produced by a **time-rule engine** (`hr.time.rule`, defined in [hr_work_entry/models/hr_time_rule.py:111](../addons/hr_work_entry/models/hr_time_rule.py#L111)) which generates *output attendances*: ordinary `hr.attendance` rows carrying a `time_rule_id` and a real FK `source_attendance_id` back to the attendance that produced them ([hr_attendance.py:102](../addons/hr_attendance/models/hr_attendance.py#L102)). The 19.0 "value match on `check_in == time_start`" link is gone — it is a genuine foreign key now, and editing or deleting a source flags surviving outputs `source_stale`.

- `total_overtime` is now the **sum of `worked_hours` over all rule-generated attendances**, regardless of approval ([hr_employee.py:179](../addons/hr_attendance/models/hr_employee.py#L179)) — not "approved overtime only" as in 19.0. Attendances gained a `state` (`draft`/`validated`/`refused`) instead.
- `hours_last_month` still computes **current month-to-date** (still misnamed), and in 20.0 it counts only attendances *without* a `time_rule_id`; rule output is split off into `hours_last_month_overtime` ([hr_employee.py:192](../addons/hr_attendance/models/hr_employee.py#L192)).
- Unchanged: single model entry point `_attendance_action_change` for kiosk and systray ([hr_employee.py:284](../addons/hr_attendance/models/hr_employee.py#L284)), no `attendance_manual`; overlap prevention is a **Python constraint only** (no SQL exclusion); `copy()` raises; setting `attendance_manager_id` silently grants that user the attendance-officer group.
- Two opt-in company crons remain: auto check-out ([hr_attendance.py:451](../addons/hr_attendance/models/hr_attendance.py#L451)) and absence detection ([hr_attendance.py:515](../addons/hr_attendance/models/hr_attendance.py#L515)). **Changed in 20.0:** absence detection runs over *yesterday*, creates the 1-second `technical` attendance at the employee's **local** day start (already `validated`), stamps the company's default work entry type so undertime rule conditions match, and then **deletes any technical attendance that produced no rule output**. It only targets employees with a contract that started before yesterday.

**Planning** (`planning`): `default_planning_role_id`/`planning_role_ids` are still related to the **resource**, where roles actually live ([planning/models/hr_employee.py:19](../enterprise/planning/models/hr_employee.py#L19)). Slot `allocated_hours` resolves through the calendar: assigned+planned slots count effective working hours over the window × `allocated_percentage`; flexible resources saturate at `hours_per_day`/day and `full_time_required_hours`/week; fully-flexible resources count raw slot time with no caps. **Changed in 20.0:** slots carry `resource_ids` (many2many) rather than a single resource, and future-slot unassignment is driven by the **departure** process, not by archiving — `hr.employee.departure.action_register` is overridden to release slots ending after the departure date ([planning/models/hr_employee_departure.py](../enterprise/planning/models/hr_employee_departure.py)). `resource.resource.action_archive` now only releases slots for `material` resources. Employees without users still get a token-based portal link to their schedule (`employee_token`).

**Payroll bridges, in 20.0:**
- **`hr_payroll_planning` no longer exists** — the module was removed in 20.0. Nothing replaces its payslip smart button.
- `hr_payroll_attendance` is no longer a pure UI shell: besides the payslip attendance counter and smart button it now extends the time-rule engine (`_get_output_attendance_vals`) to carry pay-period category options onto generated output attendances. The bulk of payslip-numeric behavior still lives in the `hr_work_entry_*` layer ([`work_entries.md`](work_entries.md)).

---

## Employee Self-Service Reality (re-verified against 20.0, 2026-09-22)

The conclusion is unchanged; the plumbing under it changed in two places.

A regular internal user (`base.group_user`, non-HR) **still cannot open `hr.employee` at all** — there is no access row granting it, only `hr.employee.public` read. **Changed in 20.0:** `ir.model.access.csv` and the separate `ir.rule` XML records were merged into a single unified **[`security/ir.access.csv`](../addons/hr/security/ir.access.csv)** (lines 4-7 cover `hr.employee`: HR officers `crud`, `base.group_system` read-only, a multi-company rule, and `base.group_user` read on `hr.employee.public`).

The framework enforces this actively: `get_views` raises a RedirectWarning pushing the user to the public-employee action ([hr_employee.py:1501](../addons/hr/models/hr_employee.py#L1501)), `get_view` silently falls back to the public model, and `_search`/`search_fetch`/`fetch` reroute onto `hr.employee.public` for readable fields and block the private ones ([hr_employee.py:1525](../addons/hr/models/hr_employee.py#L1525)).

"My Profile" still opens a **`res.users` preferences dialog**, not the employee form. **Changed in 20.0:** the `SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` lists are gone. Each exposed field is now declared individually with the `related_employee_field()` helper ([res_users.py:16](../addons/hr/models/res_users.py#L16)), which builds a compute/inverse/search trio that `sudo()`s **only when the record is the current user**, plus a `user_writeable=True` flag on the fields a user may edit about themselves. Adding a self-service field means declaring it this way, not appending to a list.

`hr.employee.public` is still a separate `_auto=False` SQL-view model with its own views — pages inherited into `hr.view_employee_form` never appear there.

Consequence for custom development: any "employee sees/edits own records" feature must live on the custom model itself (own menu/action, default `employee_id` from `user.employee_id`, ACL for `base.group_user` + record rule on `employee_id.user_id`), like hr_expense/hr_leave — never as a page on the employee form, which only HR officers reach.

## Gotchas & Non-Obvious Behavior

- **`create_version` silently ignores `values`** when a version already exists at that exact date. The new bulk wizard inherits this.
- **`current_version_id` staleness** until the daily cron; anything reading it at 00:05 may get yesterday's version.
- **Import-time `today()` defaults**: `_get_version()`, `_is_flexible()` and `_is_fully_flexible()` still evaluate `fields.Date.today()` once at class load — a worker alive across midnight resolves "today" as yesterday when the argument is omitted ([hr_employee.py:792](../addons/hr/models/hr_employee.py#L792)).
- **Contract-date fan-out is silent** across sibling versions; batch-writing contract dates across different contracts raises. The `sync_contract_dates` context key disables the fan-out entirely — internal code sets it, and so can yours, by accident.
- Overlap/uniqueness constraints apply to **active versions only** — archived versions may overlap or duplicate dates.
- With context `version_id`, the standard employee form edits a historical version — an automation writing "to the employee" may not be touching the current terms. In 20.0 a *user* doing this gets the "apply to next versions?" dialog; an automated write does not, so it silently changes one version only.
- **Departure deletes future versions.** `action_register` unlinks every version with `date_version` after the departure date. Planned future terms are not recoverable by cancelling the departure.
- Seniority: `_get_first_version_date` / `_get_first_contract_date` take the latest run of *consecutive* versions. **Changed in 20.0:** consecutiveness is no longer the 19.0 "gap ≥ 4 days" heuristic — two versions are consecutive when the calendar reports **no working hours in the gap between them** ([hr_employee.py:617](../addons/hr/models/hr_employee.py#L617)), with a fast path for back-to-back dates. Both are HR-officer-gated (`AccessError` otherwise).
- **Resolved in 20.0:** the 19.0 "search ≠ display on `date_start`/`date_end`" mismatch is fixed. `_search_start_date` now pairs `date_version` with `contract_date_start` per operator, and `_search_end_date` recomputes the clamped end date in Python for every version before matching ([hr_version.py:602](../addons/hr/models/hr_version.py#L602)). The cost is that a `date_end` domain loads every version of the active companies — it is correct but not cheap.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`resource_calendars.md`](resource_calendars.md) — the calendar/interval math this engine delegates to
- [`payroll_wage_types.md`](payroll_wage_types.md) — wage fields on the version and how pay computes
- [`work_entries.md`](work_entries.md) — how versions drive work entry generation
- [`hr_payroll.md`](hr_payroll.md) — payslip lifecycle; version-side payroll extension facts
