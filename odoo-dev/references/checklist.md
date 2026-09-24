# Quality Checklist — Odoo 20

Run this before returning any code. Every item is a real bug or a real review blocker.

---

## Simplicity (check first — `simplicity.md`)

- [ ] This is the smallest change that solves the task
- [ ] No new model / wizard / menu / setting the task did not require
- [ ] Pattern copied from existing `addons/` / `enterprise/` code, not invented
- [ ] Every behavior claim backed by a source line, a `SELECT`, or a test run
- [ ] User finishes the action on one screen; nothing duplicated for them
- [ ] No field, method or data duplicated from something that already exists
- [ ] Validations block only real data corruption, once, at the real boundary
- [ ] No migration script; `version` in `__manifest__.py` untouched
- [ ] No unrequested README, tests or docs
- [ ] No dead code, commented-out code or unused imports left behind

## Dependencies (`dependencies.md`)

- [ ] Callers and overrides of every changed method grepped, and listed in the answer
- [ ] Views inheriting a changed view checked
- [ ] The core precedent found and followed
- [ ] If the change belongs in more than one place, all of them are covered
- [ ] `super()` kept on the normal path of every override

## Multi-company (`multicompany.md`)

- [ ] `company_id` exists, `index=True`, defaults to `self.env.company`
- [ ] A restriction row (empty `group_id`) scopes the model in `ir.access.csv`
- [ ] `check_company=True` on every company-scoped relational field
- [ ] `_check_company_auto = True` when any field uses `check_company`
- [ ] `_check_company_domain` overridden when branches must inherit the record
- [ ] No `self.env.user.company_id` in business logic
- [ ] Mixed-company loops use `grouped('company_id')` + `with_company()`
- [ ] Every `sudo()` on a scoped model re-applies the company filter

## Security (`security.md`)

- [ ] `security/<module>_security.xml` is **first** in manifest `data`
- [ ] `security/ir.access.csv` is **last** in manifest `data`
- [ ] Header is `id,name,model_id,group_id/id,operation,domain`
- [ ] `model_id` holds the model name, `group_id/id` the group xml id
- [ ] Every new model has at least one permission row, or nobody can use it
- [ ] Wizards restricted with `[('create_uid', '=', user.id)]`
- [ ] Child models use `('parent_id', 'access', 'read')` where visibility follows the parent
- [ ] Sensitive fields carry `groups=`
- [ ] Every `sudo()` has a permission check before it and a one-line reason
- [ ] Portal/public routes verify ownership and return 404 on mismatch
- [ ] No SQL built by string interpolation

## Python / ORM

- [ ] New model has `_description`
- [ ] Every new or changed non-trivial method has a docstring (what + why, 1–4 lines)
- [ ] No inline `#` / `//` comments unless the line is genuinely non-obvious
- [ ] Methods are batch-safe; no accidental singleton assumptions
- [ ] `ensure_one()` only where one record is truly required
- [ ] `create()` overrides use `@api.model_create_multi` and call `super()` once
- [ ] `write()` / `unlink()` overrides validate in batch, one `super()` call
- [ ] No removed APIs: `check_access_rights`, `_check_recursion`, `toggle_active`,
      `tools.ormcache`, `registry.clear_cache`, `tools.Query`, `name_get`, `type='json'`,
      `get_param`/`set_param` (typed `get_str`/`get_bool`/`set_*`, not exact renames:
      `v20-changes.md` §2), `SELF_WRITEABLE_FIELDS`
      (`user_writeable=True`) — these fail at run time, not at install
- [ ] `read_group()` / `_read_group()` use the v20 signature
- [ ] No N+1 queries in compute or business methods
- [ ] Computes assign every record and never write to other models
- [ ] Dynamic domains use `odoo.fields.Domain`
- [ ] x2many updates use `odoo.Command`
- [ ] User-facing text uses `self.env._()` with `%s`; no f-strings inside it
- [ ] Module-level helpers take `env` and call `env._()`; module-level constants use `_lt`
- [ ] `@api.constrains` methods raise `ValidationError`, not `UserError`
- [ ] A chatter/log entry written just before a `raise` uses its own cursor when it must
      survive the rollback (`transactions.md` section 9)
- [ ] Row locks use `lock_for_update()`; catch `LockError` when the user needs a specific message
- [ ] `_logger` uses lazy `%s` formatting
- [ ] Raw SQL parameterized; cache invalidated after SQL writes; `modified()` called
- [ ] Float comparisons use `float_compare` / `float_is_zero`
- [ ] Delete restrictions use `@api.ondelete`
- [ ] No mutable default arguments
- [ ] Constraints and indexes are `models.Constraint(...)` / `models.Index(...)`
- [ ] `cr.commit()` only in resumable cron/import code, with a test guard

## Cron (`cron.md`)

- [ ] Cron XML has no `numbercall` / `doall` (removed; install fails) and sets `user_id`
- [ ] The job does not depend on its Scheduler User being superuser; `sudo()` and company
      filtering are explicit
- [ ] Work done with a user's own credentials or language runs under `with_user(user)`
- [ ] A cron that notifies (activity, message, mail) stores a marker such as
      `..._escalated_at`, so the next run does not repeat it
- [ ] Cron method names stay stable (`code` sits in a `noupdate` record in the database)

## Fields

- [ ] `Monetary` paired with a `currency_id` + `currency_field=`
- [ ] `fields.Date.today` / `Datetime.now` defaults are callable (no parentheses)
- [ ] Every `Many2one` sets `ondelete`
- [ ] Non-stored computed field that must be searched/grouped uses `compute_sql`
      (with an explicit `compute_sudo=`), not a gratuitous `store=True`
- [ ] Self-referential computes declare `recursive=True`
- [ ] `@api.onchange` is UX-only; real logic is in a `@api.depends` compute
- [ ] `copy=False` on sequences, states, unique references
- [ ] Quantities rounded with `decimal.precision`, not a removed `uom.rounding`

## Views / frontend

- [ ] `<list>`, expression syntax, `name=` on `<page>` and `<filter>`
- [ ] `<chatter/>` when the model inherits `mail.thread`
- [ ] `t-out`, never `t-esc` — in OWL templates **and** server QWeb (views, reports, wizards)
- [ ] `t-call` parameters passed as attributes
- [ ] OWL: `proxy()` not `useState()`; no import `@odoo/owl` does not export; only
      `render`/`onWillRender`/`useLayoutEffect`/`useEnv`/`useSubEnv` from `@web/owl2/utils`
- [ ] OWL: `props = useProps(...)`, never `static props` / `static defaultProps` (they throw)
- [ ] OWL: refs via `signal.ref()`, read as `this.x()` — no `.el`
- [ ] OWL: `computed`/`signal` values called with `()`; `t-key` on every `t-foreach`
- [ ] xpaths into core OWL templates tested against the current core template
- [ ] Icons: Material Symbols names that exist in `addons/web/icons.py`; no `fa-*`;
      every `<i data-icon>` has a `title` or text
- [ ] No inline styles — Bootstrap classes
- [ ] SCSS: no hard-coded neutral colours — `$o-view-background-color`, `$o-gray-*`,
      `$o-main-text-color`; own colours that need a dark shade hold both values via
      `if($o-webclient-color-scheme == dark, dark, light)` (`owl.md` → Dark mode)

## Mail / tracking

- [ ] `tracking=True` on state/status fields
- [ ] Bulk operations run with `tracking_disable=True`
- [ ] User-visible events use `message_post()`, not `_logger`
- [ ] `message_post()` called per record (singleton contract)

## Module structure

- [ ] Manifest order: groups → data → reports/wizards → views/menus → `ir.access.csv`
- [ ] `noupdate="1"` on records the user is expected to edit
- [ ] Module icon at `static/description/icon.png`
- [ ] `depends` is the smallest set that works

## Refactor / quality review (`refactor.md`)

- [ ] Findings sorted into behavior change vs cleanup; only cleanup goes into the refactor
- [ ] `code_inventory.py compare`: no translatable text removed or added unless intended
- [ ] No public name renamed; nothing deleted before `dead_names.py` and its DB check
- [ ] External requests recorded old vs new and identical (`oldnew.Recorder`)
- [ ] Intended differences listed in the report; deploy note and `git add -A` hint given

## Tests

- [ ] Tests were **asked about**, not assumed
- [ ] If written: one success path, one failure/permission path
- [ ] If written: batch behavior covered when the method is multi-record
- [ ] If written: access-scope assertions for security-sensitive changes
