# Job Positions — `hr.job` and the `department_id` field

> **Module:** `hr` (+ consumers `hr_recruitment`, `website_hr_recruitment`, enterprise `hr_contract_salary`) | **Path:** [`addons/hr/models/hr_job.py`](../addons/hr/models/hr_job.py)
> Scope: the `hr.job` model and specifically how its `department_id` behaves — including when it is left empty. Not a full `hr` module doc.

## What It Does & Why It Exists

A Job Position (`hr.job`) is a named role inside a company — "Developer", "Accountant". It carries a recruitment target (`no_of_recruitment`), a recruiter (`recruiter_id`, an `hr.employee`), an employee type (`employee_type_id` → `hr.employee.type`), an optional department, and a job description. It is the anchor object for recruitment: the email alias, the website careers posting, and applicant routing all hang off it. On the employee side it is mostly a label (`job_title`).

The `department_id` on a position is **optional** and is **not** the same relationship as the department on an employee. This is the single most misunderstood part of the model.

---

## `department_id` — the field itself

Defined at [`hr_job.py:42`](../addons/hr/models/hr_job.py#L42):

```python
department_id = fields.Many2one('hr.department', string='Department',
    check_company=True, tracking=True, index='btree_not_null')
```

- **Not `required`** → empty is a fully valid state.
- **No `default`, no `compute`, no `onchange`** → it is a plain manual field. Nothing fills it for you.
- `check_company=True` → if set, the department must belong to the job's company.
- `index='btree_not_null'` → indexed only for non-null rows (empty rows aren't indexed).

### Uniqueness constraint — the empty-department trap

[`hr_job.py:47`](../addons/hr/models/hr_job.py#L47):

```python
_name_company_uniq = models.Constraint(
    'unique(name, company_id, department_id)',
    'The name of the job position must be unique per department in company!')
```

PostgreSQL treats `NULL` as **distinct** in a `UNIQUE` constraint. v20 does support `NULLS NOT DISTINCT` in `models.Constraint` (`res.currency` uses it), but `hr.job` does **not**. `company_id` is `required=True` in v20, so `department_id` is the only column in the triple that can be NULL — and when it is, the constraint does **not** fire. You can create **many** positions with the same name in the same company as long as they all have no department. With a department set, the duplicate is blocked.

---

## What the job's department DRIVES (works only when it is set)

Everything below reads `job.department_id`. Leave it empty and each one degrades as noted.

| Consumer | Source | When department is SET | When EMPTY |
|---|---|---|---|
| **Applicant department** | [`hr_applicant.py:585`](../addons/hr_recruitment/models/hr_applicant.py#L585) `_compute_department` | applicant `department_id = job.department_id` (stored, editable) | applicant created with no department |
| **Applicant company** | [`hr_applicant.py:575`](../addons/hr_recruitment/models/hr_applicant.py#L575) `_compute_company` | company taken from `department_id.company_id` **only if it equals `job.company_id`** | falls back to `job.company_id`, then `env.company` |
| **Email alias defaults** | [`hr_recruitment/hr_job.py:310`](../addons/hr_recruitment/models/hr_job.py#L310) `_alias_get_creation_values` | apply-by-email applicants get this department; company `= department_id.company_id or company_id` | no department on emailed-in applicants; company falls back to job |
| **Department Manager on job** | [`hr_recruitment/hr_job.py:64`](../addons/hr_recruitment/models/hr_job.py#L64) `manager_id = related('department_id.manager_id')` | manager resolved; if the manager is also the outgoing recruiter, changing the recruiter will not unsubscribe them ([`:360`](../addons/hr_recruitment/models/hr_job.py#L360)) | empty — no manager shown, no unsubscribe guard |
| **New employee from applicant** | [`hr_applicant.py:1011`](../addons/hr_recruitment/models/hr_applicant.py#L1011), [`:1040`](../addons/hr_recruitment/models/hr_applicant.py#L1040) | employee gets `department_id`; `work_phone` seeded from `department_id.company_id.phone` | employee created with no department; no work_phone company default |
| **Website careers — department line** | [`website_hr_recruitment_templates.xml:31`](../addons/website_hr_recruitment/views/website_hr_recruitment_templates.xml#L31) (job card), [`:354`](../addons/website_hr_recruitment/views/website_hr_recruitment_templates.xml#L354) (job page) `t-if="job.department_id"` | department shown on the card and the job page | both lines hidden |
| **Website careers — grouping/filter** | [`website_hr_recruitment/hr_job.py:115`](../addons/website_hr_recruitment/models/hr_job.py#L115) | listed under its department filter | listed under the **"Others"** bucket (`is_other_department` → `department_id = None`) |
| **Website careers — JSON-LD (v20)** | [`website_hr_recruitment/hr_job.py:213`](../addons/website_hr_recruitment/models/hr_job.py#L213) `_prepare_jsonld_vals` | `JobPosting.occupationalCategory` = department name; `identifier` built from `department_id.company_id` | both keys omitted from the structured data |
| **Department recruitment KPIs** | [`hr_recruitment/hr_department.py:28`](../addons/hr_recruitment/models/hr_department.py#L28) `_compute_recruitment_stats` | target/hired counts roll up into the department | not counted toward any department |
| **Group By / search** | [`hr_job_views.xml:92`](../addons/hr/views/hr_job_views.xml#L92) group_by; [`:86`](../addons/hr/views/hr_job_views.xml#L86) `child_of` filter | grouped under the department; matched by department search | lands in the "None" group; a `child_of` department search won't return it |
| **Salary offer (enterprise)** | [`hr_contract_salary_offer.py:487`](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L487) `_onchange_employee_job_id` | offer department auto-filled from the job | left as-is, not auto-filled |

---

## What the job's department does NOT do

- **It does NOT set the employee's department.** On `hr.version` (the employee's record/contract), `department_id` ([`hr_version.py:131`](../addons/hr/models/hr_version.py#L131)) and `job_id` ([`:134`](../addons/hr/models/hr_version.py#L134)) are **independent** fields. There is **no onchange/compute** copying `job.department_id` → the employee's department; the only thing `job_id` drives on the version is `job_title` ([`:223`](../addons/hr/models/hr_version.py#L223)). Assigning a position to an existing employee changes their job title, not their department. The only path where a job's department reaches an employee is recruitment **Create Employee**, and even there it flows through the applicant, not through `job_id`.
- **It does NOT affect headcount on the position.** `no_of_employee` / `expected_employees` count employees whose `job_id` is this job, regardless of department ([`hr_job.py:57`](../addons/hr/models/hr_job.py#L57)).
- **It does NOT enforce name uniqueness** while empty (Postgres NULL semantics, above).

---

## Gotchas & Non-Obvious Behavior

- **Position department ≠ employee department.** Still decoupled in v20. Setting one never moves the other on the employee record. Treat the position's department as a recruitment/reporting attribute, not an employee assignment.
- **Recruitment department is computed but editable.** `applicant.department_id` recomputes from `job_id` whenever the job changes ([`hr_applicant.py:585`](../addons/hr_recruitment/models/hr_applicant.py#L585)); a manual value on the applicant is overwritten if the job is reselected.
- **Empty department = duplicate positions allowed.** Same name + same company + no department can exist many times.
- **Website still lists department-less jobs** — under "Others", not hidden.
- **No department → weaker recruitment defaults**: no department manager on the job, no company-derived `work_phone` when creating the employee, company resolved by fallback chain.
- **`work_email` is no longer seeded in v20.** The employee-creation vals used to set `work_email` from `department_id.company_id.email or email_from`; that line is gone from both [`create_employee_from_applicant`](../addons/hr_recruitment/models/hr_applicant.py#L1011) and [`_get_employee_create_vals`](../addons/hr_recruitment/models/hr_applicant.py#L1040). New employees created from an applicant start with an empty work email regardless of department.

---

## What Changed in Odoo 20

`department_id` itself is byte-identical to v19 — same definition, same constraint. What moved is everything around it.

- **`user_id` → `recruiter_id`, and it is now an `hr.employee`, not a `res.users`** — on both `hr.job` ([`hr_job.py:31`](../addons/hr/models/hr_job.py#L31)) and `hr.applicant`. The alias defaults write `recruiter_id` instead of `user_id` ([`hr_recruitment/hr_job.py:319`](../addons/hr_recruitment/models/hr_job.py#L319)). Since `hr.job` no longer has a `user_id` field at all, mail's `user_id`-based auto-subscription no longer applies to job positions.
- **`contract_type_id` (`hr.contract.type`) → `employee_type_id` (`hr.employee.type`)** — [`hr_job.py:44`](../addons/hr/models/hr_job.py#L44). The website filter query arg changed to `employee_type_id` too ([`website_hr_recruitment/hr_job.py:106`](../addons/website_hr_recruitment/models/hr_job.py#L106)).
- **`company_id` on `hr.job` is now `required=True`** — [`hr_job.py:43`](../addons/hr/models/hr_job.py#L43). `department_id` is the only nullable column left in the uniqueness triple.
- **`work_email` seeding dropped** from employee creation — [`hr_applicant.py:1036`](../addons/hr_recruitment/models/hr_applicant.py#L1036) and [`:1060`](../addons/hr_recruitment/models/hr_applicant.py#L1060) now set `work_phone` only.
- **`_compute_company` on the applicant is stricter** — the department's company is only used when it equals the job's company ([`hr_applicant.py:575`](../addons/hr_recruitment/models/hr_applicant.py#L575)); v19 took it whenever a department was set.
- **New consumer: website JSON-LD.** `hr.job` gained `website.structured_data.mixin`; `_prepare_jsonld_vals` maps the department to `occupationalCategory` and to the `identifier` property value ([`website_hr_recruitment/hr_job.py:213`](../addons/website_hr_recruitment/models/hr_job.py#L213)).
- **New `hr.job` fields** unrelated to the department but visible on the same form: `tag_ids`, `salary_min`/`salary_max`, `payment_interval` (copied to the applicant's `schedule_pay` on create) — [`hr_recruitment/hr_job.py:96`](../addons/hr_recruitment/models/hr_job.py#L96) — and `company_country_code` — [`hr_job.py:45`](../addons/hr/models/hr_job.py#L45).
- **Security files moved to `ir.access`** — `hr`, `hr_recruitment` and `website_hr_recruitment` now ship `security/ir.access.csv`; `ir.model.access.csv` and `ir.rule` records are gone.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`hr_payroll.md`](hr_payroll.md) — employee `hr.version` (job_id/department_id live here), payroll consumers
- [`employee_registry_rs.md`](employee_registry_rs.md) — derives target status from `hr.version`
