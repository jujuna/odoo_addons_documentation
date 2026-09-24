# Guardrails — Odoo 20

Non-negotiable rules applied to every code output. When a rule here conflicts with older
habits or with v19 code you are reading in this repo, this file wins.

Full 19 → 20 delta with source links: `v20-changes.md`.

---

## 1. API table — v20 forms only

| Wrong (removed or deprecated) | Right (v20) |
|---|---|
| `security/ir.model.access.csv` | `security/ir.access.csv` |
| `<record model="ir.rule">` | a `domain` on the `ir.access` row |
| `perm_read,perm_write,perm_create,perm_unlink` | one `operation` column (`crud` subset) |
| `check_access_rights(op, ...)` | `check_access(op)` / `has_access(op)` |
| `check_access_rule(op)` | `check_access(op)` |
| `_filter_access_rules(op)` | `_filtered_access(op)` |
| `check_field_access_rights(op, fnames)` | `check_field_access(f, op)` / `has_field_access(f, op)` |
| `_check_recursion()` / `_check_m2m_recursion(f)` | `_has_cycle(field_name=None)` — **boolean inverted** |
| `toggle_active()` | `action_archive()` / `action_unarchive()` |
| `copy_translations()` | removed, no replacement |
| `from odoo.tools import ormcache` | `from odoo import api` → `@api.ormcache(...)` |
| `ormcache_context(...)` | `@api.ormcache('self.env.context.get("lang")')` |
| `registry.clear_cache('x')` | `self.env.transaction.invalidate_ormcache('x')` |
| `from odoo.tools import Query` | `from odoo.models import Query` |
| `odoo.http.serialize_exception` | `odoo.http.dispatcher.serialize_exception` |
| `uom.rounding` | `env['decimal.precision'].precision_get('Product Unit')` |
| `_rec_names_search = ['name']` | `_rec_names_search = ('name',)` |
| `_read_group_select(spec, query)` | `_read_group_select(table, spec)` — `TableSQL` first |
| `_order_to_sql(order, query, alias, reverse)` | `_order_to_sql(table, order, reverse)` |
| `name_get()` | `_compute_display_name()` |
| `type='json'` | `type='jsonrpc'` |
| `<tree>` | `<list>` |
| `attrs={}` | `invisible="..."` / `readonly="..."` |
| `_sql_constraints` | `models.Constraint(...)` class attribute |
| `@api.one` / `@api.multi` | removed since v13 — delete |
| `@api.model` on `create` | `@api.model_create_multi` |
| `fields.Date.today()` as default | `fields.Date.today` (callable, no parens) |
| `group_operator='sum'` | `aggregator='sum'` |
| `auto_join=True` | `bypass_search_access=True` or `any` / `not any` domains |
| `self._cr` / `self._uid` / `self._context` | `self.env.cr` / `.uid` / `.context` |
| `ir.config_parameter` `get_param()` / `set_param()` | `get_str/get_bool/get_int/get_float(key, default)`, `set_str/set_bool/...(key, value)` |
| `res.users` `SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` | `user_writeable=True` on the field; secrets on `res.users` need `groups=` |
| `t-esc` (QWeb + OWL) | `t-out` |
| `useState()` / `reactive()` (OWL) | `proxy()` from `@odoo/owl` |
| `<t t-set>` before `<t t-call>` | parameters as `t-call` attributes (`x="expr"`, `x.f="text"`) |
| payment `state == 'in_process'` / `== 'paid'` | `'paid'` (posted) / `'reconciled'` (matched): rename paid → reconciled first |
| `res.bank`, `bank_id.bic`, `journal.bank_id` | `res.partner.bank.bank_bic` / `bank_name`, `journal.bank_bic` |
| `acc_number`, `sanitized_acc_number`, `journal.bank_acc_number` | `account_number`, `sanitized_account_number`, `journal.bank_account_number` |
| `def __get_bank_statements_available_sources` | `def _get_bank_statements_available_sources` |

**`read_group()` is NOT deprecated in v20.** It is the public, `@api.model`, RPC-safe
wrapper with the modern signature. Backend code still calls `_read_group()`; the web layer
calls `formatted_read_group()`.

**`_has_cycle()` inverts the old boolean.**

```python
# Old: True meant "safe"
if not self._check_recursion():
    raise ValidationError(...)
# v20: True means "there is a loop"
if self._has_cycle():
    raise ValidationError(self.env._("You cannot create recursive categories."))
```

---

## 2. Security — non-negotiable

- Groups in `security/<module>_security.xml`, **first** in manifest `data`
- Access in `security/ir.access.csv`, **last** in manifest `data`
- Header is always `id,name,model_id,group_id/id,operation,domain`
- Every new model gets at least one permission row, or nobody can use it
- Every multi-company model gets a **restriction** row (empty `group_id`) with a
  `company_id` domain — see `multicompany.md`
- Transient (wizard) models get a `[('create_uid', '=', user.id)]` restriction
- Never unvalidated `sudo()` on user-controlled data; every `sudo()` carries a one-line
  reason and is preceded by an explicit permission check
- ORM over SQL for business CRUD — SQL bypasses `ir.access` entirely
- SQL parameters are always `%s`, never string interpolation
- Sensitive fields carry `groups=...` on the field and in the view
- No secrets in XML/data files, never log passwords/tokens/keys
- Portal and public routes: verify ownership, return 404 (not 403) on mismatch

## 3. Multi-company — non-negotiable

Every model that stores business data is multi-company until proven otherwise.

- `company_id = fields.Many2one('res.company', index=True, default=lambda self: self.env.company)`
- `check_company=True` on every relational field pointing at company-scoped data
- A restriction row in `ir.access.csv` scoping the model to `company_ids`
- Read the active company with `self.env.company`, the accessible set with `self.env.companies`
- Never `self.env.user.company_id` in business logic
- Cross-company writes go through `.with_company(company)`

Details, domains and the branch-company (`parent_of`) rules: `multicompany.md`.

## 4. Dependency safety — non-negotiable

Before changing anything that already exists (a core method, a core field, a core view, a
public method of ours), run the sweep in `dependencies.md` and state the result in the
answer. No sweep → no change to existing behavior.

## 5. Performance

- No `search`/`read`/`write` inside a loop when a batch form exists
- `search_fetch()` when the field set is known at search time
- Filter in the domain, not with `.filtered()` on large sets
- Non-stored computed field that must be searched/grouped → `compute_sql`, not `store=True`
- Large batch jobs: chunk + `_commit_progress` + progress logging
- Mixing ORM and SQL: `flush_model()` before SQL reads, `invalidate_model()` after SQL
  writes, `modified(fnames)` when a compute dependency was written
- `_order` on indexed columns, with `id` as the final tiebreaker

## 6. Python / ORM

- Every method is multi-record unless it documents and enforces a singleton
- `ensure_one()` only at genuine singleton boundaries
- `create()` overrides: `@api.model_create_multi`, one `super().create(vals_list)`
- `write()` / `unlink()` overrides: validate in batch, one `super()` call
- Computes assign **every** record in `self`, and never write to other models
- `odoo.Command` for x2many values, never raw `(0, 0, vals)`
- `odoo.fields.Domain` for dynamic or composed domains
- `self.env._("...")` for user-facing text; never an f-string inside it
- `_logger` uses lazy `%s` formatting
- `float_compare` / `float_is_zero`, never `==` on floats
- `@api.ondelete` for delete restrictions when no cleanup is needed
- `@api.constrains` only fires on plain field names present in the `create`/`write` call —
  dotted paths are ignored; enforce always-required invariants in `create()`
- No mutable default arguments
- No `cr.commit()` in request / button / compute / constraint / onchange code
- Imports at module top; a function-level import only to break a cycle or defer a heavy
  optional dependency (mark `# noqa: PLC0415`)
- Docstrings, not comments — every new or changed non-trivial method gets a short
  docstring (what + why, 1–4 lines); inline `#` / `//` only for a genuinely non-obvious
  line; never touch comments, docstrings or type hints in code you did not change

## 7. Fields

- `Monetary` always paired with a `currency_id` M2O + `currency_field='currency_id'`
- `fields.Date.today` / `fields.Datetime.now` as defaults, no parentheses
- Every `Many2one` sets `ondelete` explicitly
- `company_id` has `index=True`; company-scoped relations have `check_company=True`
- Related fields that are searched or grouped: `store=True` or a `compute_sql`
- Self-referential computes (depending on `parent_id.x`) declare `recursive=True`
- `aggregator=`, and `index='trigram'` on columns searched with `ilike`
- `@api.onchange` for UX hints only; real logic lives in a `@api.depends` compute
- `copy=False` on sequences, states and unique references
- `compute_sql` requires an explicit `compute_sudo=` and a `compute=` method

## 8. Views / frontend

- `<list>`, expression syntax, `name=` on `<page>` and `<filter>` for stable inheritance
- `<chatter/>` when the model inherits `mail.thread`
- `t-out`, never `t-esc` — server QWeb too: v20 renders an unknown `t-esc` as nothing
- `t-call` parameters as attributes
- OWL 3: `proxy` from `@odoo/owl`; only `render`, `onWillRender`, `useLayoutEffect`,
  `useEnv`, `useSubEnv` from `@web/owl2/utils`; refs are `signal.ref()` read as `this.x()`;
  explicit `this.` in templates
- xpaths into core OWL templates copy the **current** core attribute text
  (`this.props.Renderer`, not `props.Renderer`) — `owl.md` §10
- Icons are Material Symbols: `icon="open_in_new"`, `<i class="oi" data-icon="..." title="..."/>`;
  never `fa-*`; the name must exist in `addons/web/icons.py` — `views.md` §12

## 9. Module / data

Minimal layout: `__manifest__.py`, `models/`, `views/`, `security/`.

Manifest `data` order:
1. `security/<module>_security.xml` — groups and privileges
2. core data (sequences, config, cron, mail templates)
3. reports and wizards
4. views, actions, menus
5. `security/ir.access.csv` — **last**

`noupdate="1"` for records the user is expected to edit (cron defaults, templates,
sequences).

- Do **not** bump `version` in `__manifest__.py`. A `19.0.x.y.z` version is different: it
  makes the module uninstallable on 20 (`odoo/modules/module.py:500`) — report it and
  change the series prefix only with the user's OK
- Do **not** write migration scripts — solve data changes with a compute, a default, or a
  fill-only-if-empty pass
- Do **not** add a README, tests or docs unless asked

## 10. Mail / tracking

- `tracking=True` on business-critical state fields
- Bulk operations run under `tracking_disable=True`
- User-visible events go to `message_post()`, not `_logger`
- `message_post()` is singleton-only — loop deliberately

## 11. Tests

Never write tests silently. When a change would normally warrant tests, **ask first**:
say which behaviors you would cover and let the user decide. If they say yes, follow
`testing.md`. Security-sensitive and money-touching changes are the cases worth pushing for.

## 12. Never output these

```
security/ir.model.access.csv         → security/ir.access.csv
<record model="ir.rule">             → domain column on the ir.access row
perm_read,perm_write,...             → operation column ('r', 'cru', 'crud', ...)
security files first in manifest     → groups first, ir.access.csv LAST
migrations/<version>/*.py            → solve it in code
version bump in __manifest__.py      → leave it alone
unrequested model/wizard/menu/test   → extend what exists, ask about tests
validation "just in case"            → only block real data corruption
model without company_id             → justify it explicitly
check_company missing on a company-scoped M2O → always set it
read_group() with fields=/lazy=      → v20 signature (domain, groupby, aggregates, ...)
_read_group_select(spec, query)      → _read_group_select(table, spec)
from odoo.tools import ormcache      → from odoo import api; @api.ormcache
registry.clear_cache()               → env.transaction.invalidate_ormcache()
name_get()                           → _compute_display_name()
type='json'                          → type='jsonrpc'
<tree> / attrs={} / t-esc            → <list> / invisible="..." / t-out
useState() / reactive()              → proxy()
static props / static defaultProps   → props = useProps(schema)  (static form throws)
useRef("x") / ref.el / t-ref="x"     → signal.ref() / this.x() / t-ref="this.x"
useExternalListener()                → useListener() from @odoo/owl
useEffect(fn, deps)  (OWL 2 style)   → useLayoutEffect(fn, () => deps) from @web/owl2/utils
icon="fa-x" / class="fa fa-x"        → icon="name" / class="oi" data-icon="name"
xpath "//t[@t-component='props.X']"  → copy the v20 attribute: 'this.props.X'
_sql_constraints                     → models.Constraint(...) (v20 ignores the old one)
'version': '19.0.x.y.z'              → flag it: uninstallable on 20, ask before changing
fields.Date.today()  (default)       → fields.Date.today
Monetary without currency_id         → always pair them
M2O without ondelete                 → always set ondelete
sudo() without a reason              → justify it in one line
SQL with f-strings                   → %s parameters
@api.one / @api.multi                → removed since v13
@api.model on create                 → @api.model_create_multi
missing _description                 → always set it
magic x2many tuples                  → odoo.Command
hand-built domain lists              → odoo.fields.Domain
cr.commit() in a button/request      → the transaction belongs to Odoo
check_access_rights()/_rule()        → check_access() / has_access()
_check_recursion()                   → _has_cycle()  (boolean inverted)
toggle_active()                      → action_archive() / action_unarchive()
self._cr / self._uid / self._context → self.env.cr / .uid / .context
ir.config_parameter.get_param()      → get_str() / get_bool() / get_int() / get_float()
ir.config_parameter.set_param()      → set_str() / set_bool() / set_int() / set_float()
SELF_WRITEABLE_FIELDS (res.users)    → user_writeable=True on the field
SELECT ... FOR UPDATE (raw)          → lock_for_update() / try_lock_for_update()
```
