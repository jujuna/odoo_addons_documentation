# HR Access Rights — Who Sees What, and Why

> **Scope:** `hr`, `hr_holidays`, `hr_attendance`, `hr_recruitment`, `hr_expense`, `hr_payroll`, `hr_appraisal`, `knowledge`, `hr_contract_salary`, `geo_payroll`
> **Version:** Odoo 20.0. Sections marked **Changed in 20.0** differ from 19.0 — read them first if you are migrating.
> **Purpose:** answer "who can see whose data" without guessing. Every claim links to the rule that produces it.

## Why This Document Exists

The single most common HR support ticket is *"my manager can't see / approve X"*. It is almost never a bug.
Odoo does **not** have one concept of "manager". It has at least six, each stored in a different field,
each controlling a different app. A person who is a manager in the org chart may have zero approval
rights, and a person with no subordinates at all can be the approver for the whole company.

Understanding access in Odoo HR means understanding three layers, applied in this order:

| Layer | What it decides | Where it lives |
|---|---|---|
| **Menu groups** | Whether you even see the menu | `groups="..."` on `<menuitem>` |
| **Access** (`ir.access`) | Whether you can read/write the model **and which records** | `security/ir.access.csv` |
| **Field groups** | Which *fields* on a visible record you see | `groups=` on the field definition |

**Changed in 20.0:** `ir.model.access` and `ir.rule` have been merged into a single model, `ir.access`, declared in
`security/ir.access.csv` ([`ir_access.py`](../odoo/addons/base/models/ir_access.py)). One row now carries both the
model-level grant and the record filter:

`id,name,model_id,group_id/id,operation,domain`

- `operation` is a subset of the letters `crud` (create / read / update / delete) — it replaces the four `perm_*` columns
  *and* the four `perm_*` flags a record rule used to carry.
- A row **with** a `group_id` is a **permission** — it grants access to the rows matching `domain` (empty domain = all rows).
- A row **without** a `group_id` is a **restriction** — the old "global rule". It applies to everybody.
- Permissions are **OR-ed** across the user's groups; restrictions are **AND-ed** on top
  ([`ir_access.py:501`](../odoo/addons/base/models/ir_access.py#L501)).

The consequence is unchanged: adding a group can only ever widen what a user sees, and removing one can silently break an
approval flow. What *is* new is that a grant and its domain are no longer in two files — if a row is missing, both the
"you are not allowed to access" error and the empty list come from the same place.

Unchanged from 19.0: each group belongs to a `res.groups.privilege` (Employees, Time Off, Payroll, …), which is what
the Settings → Users dropdowns are keyed on. A group with **no** privilege — `group_hr_holidays_responsible`,
`group_hr_attendance_own_reader`, `group_payslip_display` — is invisible there and can only be granted by code.

---

## The Six Different "Managers"

All the approver fields live on `hr.employee` — none of them moved to `hr.version` in the versioning refactor. The
department one is on `hr.department`, the appraisal one on `hr.appraisal`.

| Field | Label in UI | Controls | Default source |
|---|---|---|---|
| `parent_id` | Manager (employee form) | Org chart, appraisal defaults & rule, expense rule, geo_payroll work logs | set manually |
| `leave_manager_id` | Time Off Approver | Time Off approvals + reading subordinate leaves | follows `parent_id.user_id` — see below |
| `attendance_manager_id` | Attendance Approver | Attendance records of that employee | follows `parent_id.user_id` — see below |
| `expense_manager_id` | Expense Approver | Expenses (with the Team Approver group) | follows `parent_id.user_id` — see below |
| `manager_ids` (on `hr.appraisal`) | Appraisal Manager | Reading/writing that appraisal | seeded at creation, see Appraisals |
| `hr.department.manager_id` | Department Manager | Time Off *reporting* for the department subtree, write on the department itself, expense approval | set on the department |

### How the three approver fields follow the org chart

**Changed in 20.0:** all three are now `compute=..., store=True, readonly=False` on `parent_id`, and all three use the
same rule — **reassign only, never fill**:

```python
if manager and employee.leave_manager_id and employee.leave_manager_id == previous_manager:
    employee.leave_manager_id = manager
```

([`hr_employee.py:264`](../addons/hr_holidays/models/hr_employee.py#L264),
[`hr_employee.py:140`](../addons/hr_attendance/models/hr_employee.py#L140),
[`hr_employee.py:63`](../addons/hr_expense/models/hr_employee.py#L63))

In 19.0 an **empty** approver field was filled in from `parent_id.user_id` on the fly. In 20.0 it no longer is: an empty
approver stays empty until someone sets it. Only a field that still points at the *previous* manager moves. This is the
single most likely cause of "approvals stopped working after the upgrade" — audit the field, do not assume the org chart
seeds it.

Time off is the exception: creating an employee *with* a `parent_id` still defaults `leave_manager_id` to that manager
([`hr_employee.py:316`](../addons/hr_holidays/models/hr_employee.py#L316)). Attendance and expense have no such create
hook, so a new employee starts with no attendance and no expense approver at all.

Two side effects worth knowing:

- Writing `leave_manager_id` **automatically grants** that user the `Time Off Responsible` group
  ([`hr_employee.py:341`](../addons/hr_holidays/models/hr_employee.py#L341)). Nobody has to touch Settings → Users.
  `attendance_manager_id` does the same for `group_hr_attendance_officer`
  ([`hr_employee.py:130`](../addons/hr_attendance/models/hr_employee.py#L130)).
- Clearing either removes the group again if the user is no longer anyone's approver
  (`_clean_leave_responsible_users` / `_clean_attendance_officers`).

---

## Layer 0 — What a Plain Employee Can Reach

An internal user with **no HR groups at all** (`base.group_user` only) still gets a surprising amount:

| Can do | Mechanism |
|---|---|
| Open the **Employees** app | menu root allows `base.group_user` ([`hr_views.xml:4`](../addons/hr/views/hr_views.xml#L4)) |
| Browse the **Directory** — every colleague's name, job, work phone/email, department, photo, org chart | `hr.employee.public` is readable by `base.group_user` ([`ir.access.csv:7`](../addons/hr/security/ir.access.csv#L7)) |
| See **Departments** kanban | [`hr_views.xml:39`](../addons/hr/views/hr_views.xml#L39) |
| **Edit** a department they manage (or that a subordinate manages) | `hr_dept_manager_access_rule`, **new in 20.0** ([`ir.access.csv:12`](../addons/hr/security/ir.access.csv#L12)) |
| Record their own home/office working location | `homeworking_own_rule` on `hr.employee.location` — **the `hr_homeworking` module was folded into `hr` in 20.0**, so this is now core ([`ir.access.csv:49`](../addons/hr/security/ir.access.csv#L49)) |
| Read own attendance | `group_hr_attendance_own_reader` is implied by `base.group_user` |
| Create/submit own work logs (geo_payroll) | [ACL](../custom_addons/gec_payroll_types/geo_payroll/security/ir.model.access.csv) + own-draft rule |

**Changed in 20.0 — Time Off is no longer automatic.** In 19.0 the Time Off models were granted to `base.group_user`
directly, so every internal user could request time off and see the shared calendar, always. In 20.0 those grants hang
off a new group, `hr_holidays.group_hr_holidays_employee`, which is implied by
[`base.default_user_group`](../addons/hr_holidays/security/hr_holidays_security.xml#L43) — the *template* of groups given
to newly created users, **not** an implication of `base.group_user`. Practical effect: new users still get Time Off by
default, but the group can now be revoked from an individual user without touching anything else. The same pattern
applies to `hr_attendance.group_hr_attendance_own`. Both are registered as "light" groups so they do not show up as a
separate privilege line in Settings → Users ([`res_groups.py`](../addons/hr_holidays/models/res_groups.py)).

What they **cannot** do: open the real `hr.employee` form. There is no `base.group_user` row for `hr.employee` — only
`hr.group_hr_user` (and a read-only row for `base.group_system`). Self-service works through a completely different
path: the **My Profile** dialog is a `res.users` form, and the HR fields on it are simulated related fields.

**Changed in 20.0:** the `SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` (and `hr`'s `HR_READABLE_FIELDS`) whitelists
are **gone**. Two mechanisms replace them:

- `related_employee_field()` builds a compute/inverse pair that reads and writes the employee record with `sudo()` **only
  when the record is the current user's own** ([`res_users.py:16`](../addons/hr/models/res_users.py#L16)). Reading
  someone else's user record goes through ordinary `hr.employee` access, so a plain user sees nothing.
- Writability is now a field attribute, `user_writeable=True`, enforced centrally in
  `ResUsers._has_field_access` ([`res_users.py:588`](../odoo/addons/base/models/res_users.py#L588)). If you add a field
  to the profile form and it silently refuses to save, this is why.

> **Consequence for development:** any "employee sees their own record" feature must be built on a model
> the employee has an `ir.access` row for — never as a page on the employee form. See
> [`hr_employee_versions.md`](hr_employee_versions.md).

### Directory vs Employees — the same app, two models

- **Directory** → `hr.employee.public`, an SQL view over `hr.employee` exposing only work-related fields
  ([`hr_employee_public.py`](../addons/hr/models/hr_employee_public.py)). No birthday, no private phone,
  no ID documents, no salary.
- **Management** → the real `hr.employee`, menu restricted to `group_hr_user`
  ([`hr_views.xml:17`](../addons/hr/views/hr_views.xml#L17)). *(Renamed from "Employees" in 20.0.)*

Private data is protected twice: the plain user has no `hr.employee` access row, **and** every sensitive field
carries `groups="hr.group_hr_user"` — private phone/email, birthday, place of birth, bank accounts,
work permit, ID card copy, driving licence, PIN, badge ID, emergency contact
([`hr_employee.py:169-319`](../addons/hr/models/hr_employee.py#L169)).

The model's own docstring states the invariant to respect when extending it: *any field that exists on `hr.employee`
but not on `hr.employee.public` must carry `groups="hr.group_hr_user"`*, otherwise the ORM prefetch will load it for
users who have no business reading it ([`hr_employee.py:37`](../addons/hr/models/hr_employee.py#L37)).

**Changed in 20.0 — the Officer/Administrator split on contract fields moved.** In 19.0 `contract_date_start/end`,
`trial_date_end`, `contract_wage` and `structure_type_id` were all `groups="hr.group_hr_manager"`. In 20.0:

- `contract_wage` no longer exists on `hr.employee` at all — wage lives on `hr.version`.
- `contract_date_start`, `contract_date_end`, `trial_date_end`, `fixed_term`, `date_start/date_end` are now
  `groups="hr.group_hr_user"` — an HR **Officer** sees contract dates
  ([`hr_employee.py:267`](../addons/hr/models/hr_employee.py#L267)).
- Only `structure_type_id` and `employee_type_id` remain `groups="hr.group_hr_manager"`
  ([`hr_employee.py:277`](../addons/hr/models/hr_employee.py#L277)).

If your policy was "Officers administer people, Administrators see the contract", that policy is weaker after the
upgrade: Officers have full CRUD on `hr.version` and now see contract dates. Salary itself is still out of reach —
`hr.version.wage` carries `groups="hr.group_hr_manager"`
([`hr_version.py:188`](../addons/hr/models/hr_version.py#L188)), narrowed again to
`hr_payroll.group_hr_payroll_user` when Payroll is installed
([`hr_version.py:31`](../enterprise/hr_payroll/models/hr_version.py#L31)). If you need a tighter boundary than that,
override the field's `groups` as
[`alta_hr_customization`](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L18) does.

---

## Employees (`hr`)

| Group | Name in Settings (privilege *Employees*) | What it opens |
|---|---|---|
| — | (plain user) | Directory, Departments, own profile dialog |
| `hr.group_hr_user` | Officer: Manage all employees | Real employee forms, all private fields, contract dates, Reporting, employee bank accounts, full `hr.version` CRUD |
| `hr.group_hr_manager` | Administrator | + Configuration, `structure_type_id` / `employee_type_id` / `wage`, onboarding plans |

Both are declared in [`hr_security.xml:9`](../addons/hr/security/hr_security.xml#L9); `group_hr_user` implies
`base.group_user`, `group_hr_manager` implies `group_hr_user`.

Scoping detail: there is **no** "officer sees only my department" rule. `group_hr_user` sees every employee
in the allowed companies.

**Changed in 20.0 — the cross-company employee escape hatches are gone.** In 19.0 the global rule on `hr.employee`
carried three extra OR-branches (`parent_id.user_id = user`, `id = user.employee_id.parent_id.id`, `user_id = user`) so
that your own record, your manager's record and your subordinates' records stayed visible even when they belonged to a
company you were not logged into. In 20.0 the restriction is plain multi-company:
`[('company_id', 'in', company_ids + [False])]` ([`ir.access.csv:6`](../addons/hr/security/ir.access.csv#L6)).
In a multi-company group this is a real behaviour change — an HR officer who has not enabled the other company in the
company switcher no longer sees those employees at all.

Bank accounts get a dedicated set of rules: a plain user (and a contact manager) can only see `res.partner.bank` records
that belong to **non-employees**; HR officers see all of them
([`ir.access.csv:52-54`](../addons/hr/security/ir.access.csv#L52)). `hr` deactivates base's own
`res_partner_bank_rule_user` rows to make room for these
([`hr_security.xml:28`](../addons/hr/security/hr_security.xml#L28)).

**New in 20.0 — department managers can edit their department.** `hr_dept_manager_access_rule` grants `update` on
`hr.department` to any `base.group_user` who is the department's `manager_id`, or whose subordinate is
([`ir.access.csv:12`](../addons/hr/security/ir.access.csv#L12)). No HR group required.

---

## Time Off (`hr_holidays`)

Two selectable groups plus two invisible ones:

| Group | Name in Settings | Sees |
|---|---|---|
| `group_hr_holidays_employee` | *(not selectable — default for new users)* | Own requests and allocations, the shared calendar, time off types. **New in 20.0** |
| `group_hr_holidays_responsible` | *(not selectable — auto-assigned)* | Requests of employees where they are `leave_manager_id`. Implies `group_hr_holidays_employee` |
| `group_hr_holidays_user` | Officer: Manage all requests | Every request in the company. Implies `group_hr_holidays_responsible` **and** `hr.group_hr_user` |
| `group_hr_holidays_manager` | Administrator | Everything + Configuration (types, accruals, public holidays, time rules) |

**Changed in 20.0:** everything that used to be granted to `base.group_user` — reading own leaves, creating requests,
the leave calendar report, reading time off types, the cancellation wizard — now hangs off
`group_hr_holidays_employee`. `hr.group_hr_user` and `base.default_user_group` both imply it
([`hr_holidays_security.xml:39`](../addons/hr_holidays/security/hr_holidays_security.xml#L39)), so nothing changes for a
standard install; what changes is that you can now take Time Off away from one user.

Note the implication chain, which is unchanged: **making someone a Time Off Officer also makes them an HR Officer**
([`hr_holidays_security.xml:24`](../addons/hr_holidays/security/hr_holidays_security.xml#L24)) — so they
gain access to every employee's private data, bank accounts included. This is the most common accidental
over-permission in an HR rollout.

### Who approves what

**Changed in 20.0:** the model `hr.leave.type` has been **renamed to `hr.work.entry.type`** and merged with payroll's
work entry types — one record now describes both "Paid Time Off" as a leave type and as a work entry. The field
`holiday_status_id` is `work_entry_type_id` everywhere. Configuration lives under Time Off → Configuration → Time Types.

The approval path is a property of that type, not of the person
(`leave_validation_type`, [`hr_work_entry_type.py:66`](../addons/hr_holidays/models/hr_work_entry_type.py#L66)). The
labels were reworded in 20.0; the behaviour is the same:

| Setting (20.0 label) | 19.0 label | Approver |
|---|---|---|
| None | None needed | auto-approved |
| By HR Responsible | By Time Off Officer | anyone in `group_hr_holidays_user` |
| By Time Off Approver | By Employee's Approver | the employee's `leave_manager_id` |
| By HR Responsible and Time Off Approver | By Employee's Approver and Time Off Officer | both, in sequence (`validate1` → `validate`) |

So "my manager can't approve my vacation" has exactly two possible causes: the type is set to
*By HR Responsible*, or `leave_manager_id` points at someone else (or, after a 20.0 upgrade, is empty — see
[How the three approver fields follow the org chart](#how-the-three-approver-fields-follow-the-org-chart)).

### Write windows

Employees can edit their own request only while it is not `validate`/`validate1`, and delete it only in
`confirm`/`validate1` ([`ir.access.csv:4-13`](../addons/hr_holidays/security/ir.access.csv#L4)).
After approval the employee must use *Cancel* (a wizard), not edit.

The approver's own write window is separate and wider: `hr_leave_rule_responsible_update` lets a `leave_manager_id`
create and write their reports' requests in any state
([`ir.access.csv:17`](../addons/hr_holidays/security/ir.access.csv#L17)).

### The department-manager exception

The **Time Off → Reporting** overview uses `hr.leave.report`, which has its own rule: a Time Off employee sees
rows where `has_department_manager_access = True` — meaning their own rows plus every employee in a
department (or sub-department) where they are `hr.department.manager_id`
([`hr_manager_department_report.py:15`](../addons/hr/report/hr_manager_department_report.py#L15),
rule at [`ir.access.csv:65`](../addons/hr_holidays/security/ir.access.csv#L65)).
It grants reporting visibility, not approval rights. In 20.0 it is no longer the *only* department-manager grant in
standard HR — see the `hr.department` write rule above, and the expense rule below.

### Privacy in the shared calendar

Everyone sees everyone's approved absences — but not why. `description` and `work_entry_type_id` on
`hr.leave.report.calendar` are `groups='hr_holidays.group_hr_holidays_user'`
([`hr_leave_report_calendar.py:42`](../addons/hr_holidays/report/hr_leave_report_calendar.py#L42)), and in 20.0 the link
back to the underlying request, `leave_id`, is restricted the same way
([`hr_leave_report_calendar.py:52`](../addons/hr_holidays/report/hr_leave_report_calendar.py#L52)).
Colleagues see *"Nino — 3 days"*, officers see *"Nino — Sick Leave"*.

---

## Attendance (`hr_attendance`)

| Group | Sees / can do |
|---|---|
| `group_hr_attendance_own_reader` (implied by every internal user) | own attendance, read-only |
| `group_hr_attendance_own` — *Self Attendance Edit* (default for new users) | create and edit **own** attendance while it is not `validated`. **New in 20.0** |
| `group_hr_attendance_officer` | attendance of employees where they are `attendance_manager_id` — read **and write** |
| `group_hr_attendance_user` — *Officer: Manage all attendances* | all attendance, all employees. Implies officer + own |
| `group_hr_attendance_manager` — *Administrator* | + configuration, kiosk settings |

Rules: [`ir.access.csv`](../addons/hr_attendance/security/ir.access.csv) — the officer scope is row 3
(`[('employee_id.attendance_manager_id', '=', user.id)]`), the self-edit window row 5. Groups:
[`hr_attendance_security.xml:17`](../addons/hr_attendance/security/hr_attendance_security.xml#L17).

**Changed in 20.0 — attendance records now have a state.** `hr.attendance.state` is `draft` / `validated` / `refused`,
and the self-edit rule only applies while the record is not `validated`, *unless* the company's
`attendance_validation` setting is `no_validation`
([`res_company.py:37`](../addons/hr_attendance/models/res_company.py#L37)). An employee who suddenly cannot fix
yesterday's clock-in is looking at a validated record, not a missing group.

**Changed in 20.0 — `attendance_manager_id` now follows `parent_id`.** It is computed from the org chart on the same
reassign-only rule as the other approver fields (see above). Setting it still auto-grants the Officer group, so the
field is no longer inert on its own — but it is still never filled in for an employee who has none.

---

## Payroll (`hr_payroll` + `geo_payroll`)

**Changed in 20.0 — there are now three payroll groups, not two**, and the first one implies more than it used to
([`hr_payroll_security.xml:10`](../enterprise/hr_payroll/security/hr_payroll_security.xml#L10)):

| Group | Name in Settings | Sees |
|---|---|---|
| — | (plain user) | **nothing**. `hr.payslip` has no `base.group_user` row |
| `group_hr_payroll_user` | Assistant *(was "Officer: Manage all contracts")* | all payslips, all batches, salary rules (read). Implies `hr.group_hr_user` **and `hr_holidays.group_hr_holidays_user`** |
| `group_hr_payroll_officer` | Officer — **new in 20.0** | + **validating payslips and pay runs**, + reviewing payroll changes on employee records, + the officer-level warnings queue |
| `group_hr_payroll_manager` | Administrator | + salary rules (write), rule parameters, benefit types, payroll settings. Implies `hr.group_hr_manager` |

The Officer group is the interesting one. It is not just another rule row — it is enforced in Python as a **maker /
checker split**:

- An Assistant can prepare and edit payslips but **cannot validate them**; `action_payslip_done` and
  `HrPayslipRun.action_validate` raise unless the user is an Officer
  ([`hr_payslip.py:981`](../enterprise/hr_payroll/models/hr_payslip.py#L981),
  [`hr_payslip_run.py:377`](../enterprise/hr_payroll/models/hr_payslip_run.py#L377)).
- Payroll-relevant changes an Assistant makes to an employee land in `review_state = '2_to_review'`, queued for an
  Officer ([`hr_employee.py:88`](../enterprise/hr_payroll/models/hr_employee.py#L88)).

If payslip validation stopped working for someone after the upgrade, they have the 19.0 group (now Assistant) and need
the new Officer one.

Watch the implication on the Assistant group too: in 19.0 it implied only `hr.group_hr_user`. In 20.0 it also implies
**Time Off Officer**, so anyone you make a payroll Assistant can read, approve and edit every time off request in the
company. Grant it knowing that.

There is still no partial payroll visibility and no "managers see their team's payslips" mode — the payslip permission
carries an empty domain ([`ir.access.csv:8`](../enterprise/hr_payroll/security/ir.access.csv#L8)); the only restriction
is multi-company. Employees receive payslips as emailed PDFs; `group_payslip_display` only controls whether the PDF
preview panel renders on the payslip form.

The one genuinely record-scoped model is the new `hr.payroll.warning`, split three ways by its `visible_to` field so
that an Assistant, an Officer and an Administrator each see a different queue
([`ir.access.csv:32-36`](../enterprise/hr_payroll/security/ir.access.csv#L32)).

### Work logs (custom — `geo_payroll`)

This is the one place where the plain **org-chart manager** (`parent_id`) is the authority
([`security.xml`](../custom_addons/gec_payroll_types/geo_payroll/security/security.xml)):

| Who | Can |
|---|---|
| Employee | read own + own manager's scope; create/edit/delete own logs in `draft`/`rejected` |
| `parent_id.user_id` (direct manager) | read direct reports; write/create their logs in `draft`/`submitted` — i.e. approve or send back |
| `hr_payroll.group_hr_payroll_user` (Payroll **Assistant** in 20.0) | everything, company-wide |

The **Work Log Approvals** menu under the Employees app has no group restriction — every internal user
sees the menu, and non-managers simply get an empty list (the action is domain-filtered on
`employee_id.parent_id.user_id = uid`).

> Deliberate inconsistency to explain in training: time off follows `leave_manager_id`, work logs follow
> `parent_id`. Changing someone's manager moves their work-log approvals immediately, but moves their
> time-off approvals only if `leave_manager_id` was already pointing at the previous manager.

> **Migration blocker:** `geo_payroll` is still written against the 19.0 security format —
> [`ir.model.access.csv`](../custom_addons/gec_payroll_types/geo_payroll/security/ir.model.access.csv) with `perm_*`
> columns, plus `ir.rule` records in
> [`security.xml`](../custom_addons/gec_payroll_types/geo_payroll/security/security.xml). **Both `ir.model.access` and
> `ir.rule` were removed as models in 20.0**, so these files reference models that no longer exist. The module needs
> converting to a single `security/ir.access.csv` before it will install. Odoo ships the conversion as a code-upgrade
> script — `odoo-bin upgrade_code`, script
> [`19.4-00-ir-access.py`](../odoo/upgrade_code/19.4-00-ir-access.py) — which merges each ACL row with the rules that
> narrowed it. The *intent* documented above (employee / direct manager / payroll officer) does not change; only the
> file format does. The same applies to the second copy of the module under `custom_addons/gec_odoo_modules/geo_payroll`,
> which is byte-identical in its security folder.

---

## Recruitment (`hr_recruitment` + Alta customization)

| Group | Sees |
|---|---|
| `group_hr_recruitment_interviewer` | only applicants where they are in `interviewer_ids`, or interviewer on the job position. Cannot create or delete ([`ir.access.csv:5`](../addons/hr_recruitment/security/ir.access.csv#L5)) |
| `group_hr_recruitment_user` — *Officer: Manage all applicants* | all applicants, all job positions, all talent pools; read + write on `res.partner` |
| `group_hr_recruitment_manager` — *Administrator* | + configuration, activity plans, job platforms |

Two things to flag:

- **Fixed in 20.0:** the Officer group used to carry a rule granting `(1,'=',1)` on `mail.message` — database-wide
  chatter read access for anyone who could recruit. That rule (`mail_message_user_rule`) has been **removed**. If you
  were relying on it, or if you worked around it, revisit that.
- Every internal user is implicitly in `group_applicant_cv_display`
  ([`hr_recruitment_security.xml:36`](../addons/hr_recruitment/security/hr_recruitment_security.xml#L36)), so CVs render
  on the application form for anyone who can open an applicant.

Side effect worth knowing (true in 19.0 and 20.0, but expressed differently now): installing Recruitment **downgrades**
HR Officers on job positions. `hr_recruitment` deactivates `hr.access_hr_job_user`
([`hr_recruitment_security.xml:41`](../addons/hr_recruitment/security/hr_recruitment_security.xml#L41)) and re-grants
`hr.job` as read-only to `hr.group_hr_user` ([`ir.access.csv:3`](../addons/hr_recruitment/security/ir.access.csv#L3)).
Writing job positions becomes a Recruitment Officer privilege.

### Salary offers

`hr.contract.salary.offer` is split by role rather than by record ownership
([`ir.access.csv:20-21`](../enterprise/hr_contract_salary/security/ir.access.csv#L20)):

- Recruitment Officer (`hr_recruitment.group_hr_recruitment_user`) → offers **with** an applicant (candidate offers)
- Payroll Assistant (`hr_payroll.group_hr_payroll_user`) → offers with **no** applicant (existing-employee offers)

**Changed in 20.0** on both sides. In 19.0 the employee-side half belonged to `hr.group_hr_manager` (HR Administrator);
it is now a **payroll** privilege. And the recruiter half used to be expressed as `employee_version_id = False`; it is
now the positive `applicant_id != False`, which is the same set in practice but no longer silently includes offers with
neither link. If HR Administrators lost sight of employee salary offers after the upgrade, this is why — give them the
payroll group.

Because permissions OR together, a user holding both groups sees both sets. A user holding neither sees none.

Alta's customization adds an `accepted` state that is terminal — an accepted offer cannot be refused or
deleted ([`hr_contract_salary_offer.py:86`](../custom_addons/alta_hr_customization/hr_customization/models/hr_contract_salary_offer.py#L86))
— and routes decision notifications by role on the applicant: `user_id` (recruiter) and `team_leader_id`
get a plain notice, `lawyer_id` additionally gets the offer details.

The candidate reads and signs the offer through a **tokenized public URL**, not a portal account
([`offer.py:13`](../custom_addons/alta_hr_customization/hr_customization/controllers/offer.py#L13)) —
access is `consteq` on `access_token`, and the link stops working once the offer leaves `open` or passes
`offer_end_date`.

### Contract & trial expiry alerts

A daily cron warns 7 days ahead and notifies the employee's `recruitment_recruiter_id`,
`recruitment_team_leader_id` and `recruitment_lawyer_id` — falling back to the version's `hr_responsible_id` if none are
set ([`hr_version.py:81`](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L81), recipients
resolved at [`hr_version.py:31`](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L31)).
The `contract_expiry_notified_for` / `trial_expiry_notified_for` stamps make it fire once per deadline, so
changing the end date re-arms the alert.

The same module also narrows the salary fields on `hr.version` — `wage`, `wage_type`, `hourly_wage`,
`contract_date_start/end`, `contract_type_id` are restricted to `hr_payroll.group_hr_payroll_user` plus a local
`hr_customization.group_hr_payroll_team_leader` group
([`hr_version.py:18`](../custom_addons/alta_hr_customization/hr_customization/models/hr_version.py#L18)). This is what
restores the "Officers administer people, payroll sees the money" boundary that core 20.0 loosened.

---

## Appraisals (`hr_appraisal`)

A plain user gets **create, read and update** (not read-only) on appraisals where they are the employee, are listed in
`manager_ids`, **or** the employee is anywhere below them in the org chart
([`ir.access.csv:3`](../enterprise/hr_appraisal/security/ir.access.csv#L3)). The feedback fields themselves are governed
by the appraisal's own "visible to employee / visible to manager" flags, not by the rule.
`group_hr_appraisal_user` sees all appraisals, `group_hr_appraisal_manager` adds campaigns and configuration.

**Changed in 20.0 — the org chart is now an access path.** The `child_of user.employee_ids.ids` branch is new. In 19.0
a manager only reached an appraisal by being in its `manager_ids`; in 20.0 every manager above the employee, at any
depth, can open and edit it. If you use appraisals for anything sensitive, that is a wider audience than before.

`manager_ids` is seeded on the `employee_id` onchange from the employee's `parent_id` — falling back to the creating
user's own employee, and additionally adding the creating user when they are an indirect manager without the Officer
group ([`hr_appraisal.py:334`](../enterprise/hr_appraisal/models/hr_appraisal.py#L334)). Because it is an onchange, it
is frozen afterwards: reassigning the employee later does not move existing appraisals.

---

## Expenses (`hr_expense`)

There is **no `hr.expense.sheet`** — expense reports are not a separate model. `hr.expense` carries the whole lifecycle
itself (`draft` → `submitted` → `approved` → `posted` → `in_payment` / `paid`, plus `refused`), and `manager_id` is a
field on the expense. *(This was already true in 19.0; an earlier version of this document described a "sheet" that
no longer existed.)*

| Group | Sees |
|---|---|
| — | own expenses in `draft` (write); own non-draft read-only; plus anything where they are `expense_manager_id` |
| `group_hr_expense_team_approver` — *Team Approver* | own + department-manager's employees + `child_of` own employee (org chart!) + `expense_manager_id` + `manager_id` on the expense |
| `group_hr_expense_user` — *All Approver* | all |
| `group_hr_expense_manager` — *Administrator* | all + configuration |

The approver rule includes the **org chart** (`employee_id child_of user.employee_ids.ids`) alongside department manager
and the explicit `expense_manager_id` ([`ir.access.csv:4`](../addons/hr_expense/security/ir.access.csv#L4)). Five
OR-branches, five different paths to the same approval right — which is why expense visibility often surprises people.
Appraisals joined it in 20.0; expenses and appraisals are now the two standard apps that read the org chart directly.

Team Approvers also pick up read access to `account.journal`, and to the `account.move` / `account.move.line` rows that
came from an expense ([`ir.access.csv:19-22`](../addons/hr_expense/security/ir.access.csv#L19)) — they see accounting
entries, scoped to expenses, without any Accounting group.

Apart from the format conversion, `hr_expense`'s security layer is unchanged between 19.0 and 20.0.

---

## Knowledge (`knowledge`)

Knowledge ignores HR groups entirely and computes access per article:

- `internal_permission` — `write` / `read` / `none` (Members only) — the default for **all internal users**
- inherited down the article tree from the nearest ancestor that defines it (`inherited_permission`)
- overridden per person by `article_member_ids`
- `is_desynchronized` breaks inheritance for a branch

The access rows simply read the computed flags: `user_has_access` for read, `user_has_write_access` for
write ([`ir.access.csv`](../enterprise/knowledge/security/ir.access.csv)). The **Section** shown in the sidebar
(Workspace / Shared / Private) is derived from those permissions, not chosen. Nothing about this model changed in
20.0 beyond the file format — the same domains now appear as `ir.access` rows, duplicated once per group
(`base.group_portal`, `base.group_user`) because a permission row carries exactly one group.

Alta flags one article with `welcome_message = True`; the most recently edited flagged article is linked in
the welcome email sent when HR creates an employee's user
([`res_users.py`](../custom_addons/alta_hr_customization/hr_customization/models/res_users.py)).

---

## Diagnosing "X can't see Y"

Work down the layers in order — the answer is almost always in the first three steps:

1. **Is the menu visible?** No → missing group. Menu groups are the cheapest thing to check.
2. **Empty list where records should be?** Menu is visible but no permission row's domain matches →
   wrong approver field, or the record belongs to a company not enabled in the switcher.
3. **"You are not allowed to access / modify … records"?** No permission row for any of the user's groups covers that
   operation on that model. In 20.0 the error message names the operation and the model
   ([`ir_access.py:48`](../odoo/addons/base/models/ir_access.py#L48)) — read it literally: "modify" means an `u` row is
   missing, not an `r` row.
4. **Record opens but a field is blank/missing?** Field-level `groups=`. Compare against the field
   definition — the value exists, it is just not sent to the browser.
5. **Right in one app, not another?** Different approver field. Check all six.

Debug tooling: **Settings → Technical → Security → Access Rights** — one list now, not two. Filter by model; the
**Type** column tells you whether a row is a *permission* (green — has a group, widens) or a *restriction* (red — no
group, narrows), and the Create/Read/Update/Delete checkboxes show the operation set. Group definitions live one menu
up, under **Privileges**.
Impersonating with **Log in as** is the fastest reliable test — never validate access from an admin session.

---

## Rollout Checklist

- [ ] Every employee has `parent_id` set — it drives appraisals, expense and work-log approvals
- [ ] **All three approver fields verified per employee.** In 20.0 an empty `leave_manager_id`,
      `attendance_manager_id` or `expense_manager_id` is never filled in from the org chart. Audit them after any
      upgrade or data import — this is the number one cause of silently broken approvals
- [ ] `hr.department.manager_id` set — required for the Time Off department overview, and it now also grants write on
      the department record itself
- [ ] Time types reviewed: `leave_validation_type` on `hr.work.entry.type` matches who you actually want approving
- [ ] Nobody has Time Off Officer unless they should also see all private employee data (implied group)
- [ ] Nobody has Payroll **Assistant** unless they should also be a Time Off Officer (new implied group in 20.0)
- [ ] Multi-company: employees outside your enabled companies are now genuinely invisible — check the company switcher
      before filing a bug
- [ ] Contract dates are visible to HR Officers in 20.0; if your policy needs them narrower, override `groups=` per field
- [ ] Payroll groups given only to payroll staff — there is still no partial payroll visibility
- [ ] Whoever validates payslips holds the **new** `group_hr_payroll_officer`; the 19.0 group alone is no longer enough
- [ ] Appraisals: org-chart managers can now edit their reports' appraisals without being in `manager_ids`
- [ ] Knowledge article permissions set at the top of each tree, before children are created
- [ ] Custom modules converted to `security/ir.access.csv` — `ir.model.access` and `ir.rule` no longer exist
- [ ] Access verified by **Log in as** for one plain employee, one manager, one officer
