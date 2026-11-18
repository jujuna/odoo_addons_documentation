# Recruitment — Where an Applicant's Source Comes From

> **Modules:** `hr_recruitment`, `website_hr_recruitment`, `utm` | **Path:** [`addons/hr_recruitment/`](../addons/hr_recruitment/), [`addons/utm/`](../addons/utm/)
> Focused doc: only the Source / Medium / Campaign ("Sourcing") side of Recruitment.

## What This Answers

"Where did this applicant come from?" is answered by three UTM fields on the applicant —
**Source** (`source_id`), **Medium** (`medium_id`), **Campaign** (`campaign_id`) — shown in the
*Sourcing* group of the applicant form ([hr_applicant_views.xml:213](../addons/hr_recruitment/views/hr_applicant_views.xml#L213)).

There is **no inference logic**. Odoo never looks at the applicant's email domain, the job board
that forwarded the mail, or the referrer header to guess a source. The field is filled only if one
of two mechanisms hands a value to `create()`. Everything else leaves it empty.

---

## The Two Mechanisms

```
Visitor clicks tracker URL  -->  ?utm_source=LinkedIn in URL
                            -->  ir_http._post_dispatch sets cookie odoo_utm_source
                            -->  visitor applies (any page, up to 31 days later)
                            -->  create() -> default_get() reads cookie -> source_id

Candidate emails job+linkedin@company.com
                            -->  mail.alias with alias_defaults {'source_id': ...}
                            -->  message_new(custom_values=alias_defaults) -> source_id
```

### 1. Website apply — the UTM cookie

`hr.applicant` inherits `utm.mixin` ([utm_mixin.py:15](../addons/utm/models/utm_mixin.py#L15)), which
carries `source_id` / `medium_id` / `campaign_id` — and, new in 20, a generic `utm_reference`
([utm_mixin.py:36](../addons/utm/models/utm_mixin.py#L36)) — plus, crucially, a `default_get` override
([utm_mixin.py:41](../addons/utm/models/utm_mixin.py#L41)).

The chain:

| Step | Code |
|---|---|
| Any HTTP response, if the request URL had `utm_source=X`, writes cookie `odoo_utm_source=X`, `max_age` 31 days, host-scoped | [ir_http.py:15](../addons/utm/models/ir_http.py#L15) |
| The website form controller creates the applicant as SUPERUSER with only the submitted fields | [form.py:262](../addons/website/controllers/form.py#L262) |
| ORM `create()` fills every field absent from `vals` via `default_get` | [models.py:1625](../odoo/orm/models.py#L1625), called at [models.py:4285](../odoo/orm/models.py#L4285) |
| `utm.mixin.default_get` loops the tracking cookies (four in 20 — `utm_reference` was added); a string value is resolved to a `utm.source` record | [utm_mixin.py:48](../addons/utm/models/utm_mixin.py#L48), list at [utm_mixin.py:81](../addons/utm/models/utm_mixin.py#L81) |
| No matching `utm.source` (case-insensitive `name =ilike`) → **a new one is created** | `_find_or_create_record`, [utm_mixin.py:115](../addons/utm/models/utm_mixin.py#L115) |

So the source is dynamic, but it is dynamic *at create time from a cookie*, not from anything about
the application itself.

**Non-obvious consequences:**

- The cookie is set by **any** page hit carrying `utm_source`, is host-wide, and lives 31 days. A
  visitor who once landed via a marketing link and applies three weeks later through a Google search
  still gets the old source. Last-touch it is not; it's *last URL parameter seen*.
- Unknown source strings silently create `utm.source` rows. A typo in a hand-shared tracker URL
  produces a new source in the catalog.
- `default_get` **skips UTM entirely** for a non-superuser in `sales_team.group_sale_salesman`
  ([utm_mixin.py:45](../addons/utm/models/utm_mixin.py#L45)). Irrelevant to the website flow (it runs
  as SUPERUSER) but it means a salesperson creating an applicant in the backend never gets defaults.
- Tracker URLs are generated per recruitment source by `_compute_url`
  ([website_hr_recruitment/models/hr_recruitment_source.py:15](../addons/website_hr_recruitment/models/hr_recruitment_source.py#L15)) —
  it appends `utm_campaign=Job Campaign`, `utm_medium=<the row's medium>` (falling back to `Website`
  only when the field is empty), `utm_source=<source name>`. In 20 the row's `medium_id` defaults to
  **Social Media**, not Website, so a tracker link built without touching that field tags every
  applicant as Social Media
  ([hr_recruitment_source.py:16](../addons/hr_recruitment/models/hr_recruitment_source.py#L16)).

### 2. Email alias per recruitment source

On a job position, *Recruitment Sources* (`hr.recruitment.source`, one row per job × source) can each
get their own catch-all address via `create_alias`
([hr_recruitment_source.py:29](../addons/hr_recruitment/models/hr_recruitment_source.py#L29)).
The alias is named `<job alias or job name>+<utm.source name>` and its `alias_defaults` hardcode:

| Key | Value |
|---|---|
| `job_id` | the job |
| `source_id` | the recruitment source's `utm.source` |
| `medium_id` | `utm.utm_medium_email`, resolved through `utm.mixin._utm_ref` ([utm_mixin.py:209](../addons/utm/models/utm_mixin.py#L209)) |
| `campaign_id` | `hr_recruitment.utm_campaign_job` |

Mail arriving at that address goes through `hr.applicant.message_new`
([hr_applicant.py:952](../addons/hr_recruitment/models/hr_applicant.py#L952)), which merges
`custom_values` (= the alias defaults) into the vals — so the applicant is born with the source set.

This is the only path that is truly deterministic: address → source.

---

## Paths That Leave Source Empty

| Path | Why |
|---|---|
| Mail to the **job's own alias** (`job._alias_get_creation_values`, [hr_job.py:310](../addons/hr_recruitment/models/hr_job.py#L310)) | its `alias_defaults` set job / department / company / recruiter only — no UTM |
| Mail from a **Job Platform** (`hr.job.platform` — Indeed, LinkedIn forwarders, [hr_job_platform.py](../addons/hr_recruitment/models/hr_job_platform.py)) | the model only strips the sender and regex-extracts the candidate name; it has no source field |
| Enterprise **job-board integrations** (the five `hr_recruitment_integration_*` modules — `_base`, `_monster`, `_skills_monster`, `_website`, `_website_monster`) | none of them reference a UTM field at all; applications come back as ordinary alias mail |
| **Backend manual creation** | the field is a plain many2one with a placeholder; whoever creates the record picks a source or leaves it blank |
| Website apply where the visitor never hit a `utm_source` URL | no cookie, no default |

If accurate source attribution matters, the practical lever is: create one `hr.recruitment.source` per
channel per job, and use **either** its tracker URL (website) **or** its generated alias (email). No
other configuration produces attribution.

---

## Source Records — Two Different Models

Don't confuse them:

| Model | Role |
|---|---|
| `utm.source` | the global catalog entry ("LinkedIn"). What `applicant.source_id` points to. |
| `hr.recruitment.source` | a per-job channel row: `job_id` + `source_id` + optional `alias_id` + tracker URL. In 20 it declares `source_id` itself — required, `ondelete='restrict'`, defaulting to the LinkedIn `utm.source`, with `_rec_name = 'source_id'` ([hr_recruitment_source.py:18](../addons/hr_recruitment/models/hr_recruitment_source.py#L18)). The `utm.source.mixin` it used to inherit is gone, so a row no longer springs a `utm.source` into existence from a typed name; you pick an existing source on the many2one (the list view sets no option that would disable its quick-create, [hr_recruitment_source_views.xml:12](../addons/hr_recruitment/views/hr_recruitment_source_views.xml#L12)). |

Deleting a `utm.source` still referenced by a `hr.recruitment.source` is blocked with a readable error
([hr_recruitment/models/utm_source.py:13](../addons/hr_recruitment/models/utm_source.py#L13)) on top of
the `ondelete='restrict'` on the link. Separately, `utm` itself now refuses to delete any of the nine
core sources listed in `utm.mixin.SELF_REQUIRED_UTM_REF` — LinkedIn, Facebook, X, Instagram, YouTube,
Referral, Livechat, Survey, Mass Mailing ([utm_source.py:43](../addons/utm/models/utm_source.py#L43),
[utm_mixin.py:239](../addons/utm/models/utm_mixin.py#L239)); in 19 only Referral was protected. On the
applicant side the three UTM fields are re-declared with `ondelete='set null'`
([hr_applicant.py:140-142](../addons/hr_recruitment/models/hr_applicant.py#L140)),
so removing a source blanks historical applicants rather than deleting them.

---

## Dependencies

- `hr_recruitment` depends directly on `utm` for the mixin; `mail` (the alias gateway) comes in
  transitively through `hr` — [__manifest__.py:10](../addons/hr_recruitment/__manifest__.py#L10).
- `website_hr_recruitment` adds only the tracker `url` compute; the cookie plumbing lives in `utm`'s
  `ir.http` and applies site-wide.

---

## What Changed in Odoo 20

- `utm.source.mixin` was deleted. `hr.recruitment.source` now declares its own required `source_id`
  (default LinkedIn) and `_rec_name = 'source_id'`; creating a row from a bare name no longer
  auto-creates the `utm.source` — [hr_recruitment_source.py:10](../addons/hr_recruitment/models/hr_recruitment_source.py#L10)
- The generated alias name switched from the mixin's related `name` to `source_id.name` —
  [hr_recruitment_source.py:42](../addons/hr_recruitment/models/hr_recruitment_source.py#L42)
- `utm.medium._fetch_or_create_utm_medium()` is gone; core UTM records are now fetched (and created if
  missing) through `utm.mixin._utm_ref('<xml_id>')` against `SELF_REQUIRED_UTM_REF` —
  [utm_mixin.py:209](../addons/utm/models/utm_mixin.py#L209)
- The recruitment source's `medium_id` default moved from Website to **Social Media**, which changes
  the `utm_medium` on every freshly created tracker URL —
  [hr_recruitment_source.py:16](../addons/hr_recruitment/models/hr_recruitment_source.py#L16)
- `utm.mixin` gained a fourth tracked field, `utm_reference` (a `Reference` to the originating record),
  with its own `odoo_utm_reference` cookie; `hr.applicant` inherits it but no recruitment view shows it —
  [utm_mixin.py:36](../addons/utm/models/utm_mixin.py#L36), [utm_mixin.py:86](../addons/utm/models/utm_mixin.py#L86)
- `utm.source` delete protection widened from "Referral only" to the nine core sources —
  [utm_source.py:43](../addons/utm/models/utm_source.py#L43)
- The job alias defaults now carry `recruiter_id` instead of `user_id` (still no UTM key) —
  [hr_job.py:319](../addons/hr_recruitment/models/hr_job.py#L319)
- Unchanged: the cookie plumbing. [ir_http.py](../addons/utm/models/ir_http.py) is byte-identical to
  19 — same `_post_dispatch` hook, same 31-day `max_age`, same host scoping.
