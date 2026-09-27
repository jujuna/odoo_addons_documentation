# Odoo 19 → 20 Delta

Everything below was verified against this checkout (`19.0` vs `20.0` branch). Paths are
clickable from the repo root. Load this file when migrating code, when reviewing code that
looks like it was written for v19, or when unsure whether an API still exists.

Framework version: `version_info = (20, 0, 0, FINAL, 0, '')` — [odoo/release.py:15](../../../../odoo/release.py#L15)
Python: **3.12 – 3.14** (`MIN_PY_VERSION = (3, 12)`, `MAX_PY_VERSION = (3, 14)`) — the ORM uses
PEP 695 generics (`def mapped[T](...)`), so 3.11 will not even import.

---

## 1. Security was rebuilt — the single biggest change

`ir.model.access` **and** `ir.rule` are gone. Both are replaced by one model, `ir.access`,
defined in [odoo/addons/base/models/ir_access.py](../../../../odoo/addons/base/models/ir_access.py).

| v19 | v20 |
|---|---|
| `security/ir.model.access.csv` | `security/ir.access.csv` |
| `security/*_security.xml` with `<record model="ir.rule">` | same CSV, `domain` column |
| `perm_read,perm_write,perm_create,perm_unlink` (4 bool columns) | one `operation` column, a subset of `crud` |
| `model_id:id` = `model_sale_order` (xmlid) | `model_id` = `sale.order` (the model name) |
| `group_id:id` | `group_id/id` |
| global rule = `ir.rule` with no `groups` | **restriction** = `ir.access` row with empty `group_id` |
| group rule = `ir.rule` with `groups` | **permission** = `ir.access` row with a `group_id` |

Counts in this checkout: 506 `ir.access.csv` files, 0 `ir.model.access.csv`.

The one canonical header, identical in all 506 core files:

```csv
id,name,model_id,group_id/id,operation,domain
```

Full rules, semantics and templates: `security.md`.

### New `access` domain operator

`('order_id', 'access', 'read')` means *"the user must have `read` on the related
`order_id` record"*. It replaces hand-written cross-model rule domains and it is what
core now uses for line models —
[addons/sale/security/ir.access.csv:36](../../../../addons/sale/security/ir.access.csv#L36).
Works on `many2one` fields and on `id` only —
[odoo/orm/domains.py:1921](../../../../odoo/orm/domains.py#L1921).

### Manifest order flipped

`security/ir.access.csv` is loaded **last**, after views and menus. Group definitions
(`security/<module>_security.xml`) stay **first**. Verified in `account`, `stock`,
`project`, `hr`, `purchase`, `mail`, `sale` — in every one, the groups file is entry `0`
and `ir.access.csv` is the last entry.

---

## 2. Removed APIs — using these is a hard error in v20

| Removed | Use instead |
|---|---|
| `check_access_rights(op, raise_exception=True)` | `check_access(op)` |
| `check_access_rights(op, raise_exception=False)` | `has_access(op)` |
| `check_access_rule(op)` | `check_access(op)` |
| `_filter_access_rules(op)` / `_filter_access_rules_python(op)` | `_filtered_access(op)` |
| `check_field_access_rights(op, fnames)` | `check_field_access(field, op)` / `has_field_access(field, op)` |
| `_check_recursion()` / `_check_m2m_recursion(f)` | `_has_cycle(field_name=None)` — **boolean inverted** |
| `toggle_active()` | `action_archive()` / `action_unarchive()` |
| `copy_translations()` | — (no replacement; translations follow `copy()`) |
| `odoo.tools.ormcache` | `odoo.api.ormcache` (`from odoo import api`) |
| `odoo.tools.ormcache_context` | `@api.ormcache('self.env.context.get("lang")')` |
| `registry.clear_cache(name)` | `self.env.transaction.invalidate_ormcache(name)` |
| `odoo.tools.Query` | `odoo.models.Query` |
| `api.deprecated` | `odoo.tools.func.deprecated` |
| `api.Self` | `typing.Self` |
| `odoo.http.serialize_exception` | `odoo.http.dispatcher.serialize_exception` |
| `odoo.tools.populate` | `odoo.tools.duplicate` |
| `uom.uom.rounding` | `env['decimal.precision'].precision_get('Product Unit')` |
| `_read_group_fill_results` / `_read_group_fill_temporal` / `_read_group_format_result` | web layer only — [addons/web/models/models.py](../../../../addons/web/models/models.py) |
| OWL 2 `useState` / `reactive` | OWL 3 `proxy` |
| QWeb `t-esc` / `t-raw` (server side too) | `t-out`. v19 had `_compile_directive_esc`; v20 does not. The engine only logs "Unknown directives or unused attributes" and renders **nothing** — reports and wizard HTML come out blank, no error ([ir_qweb.py:1929](../../../../odoo/addons/base/models/ir_qweb.py#L1929)) |
| `_sql_constraints` | `models.Constraint(...)`. v20 logs "no longer supported" and creates **no** constraint — uniqueness is silently unenforced |
| `ir.config_parameter.get_param(key, default)` / `set_param(key, value)` | typed `get_str` / `get_bool` / `get_int` / `get_float(key, default)` and `set_str` / `set_bool` / `set_int` / `set_float(key, value)` — commit `a4f2879697a`, [ir_config_parameter.py:65-129](../../../../odoo/addons/base/models/ir_config_parameter.py#L65). The module still installs; the cron or button that reads the key dies with `AttributeError` at run time. `set_bool(key, False)` stores `'False'` (v19 `set_param(key, False)` deleted the row); only `None` means undefined. A settings `Boolean` with `config_parameter=` and `default=True` shows ON while the key is missing ([res_config.py:264](../../../../odoo/addons/base/models/res_config.py#L264)) — code reading the key must use the same default, or drop the field default |
| `res.users.SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` | field parameter `user_writeable=True` — commit `a816d151ae1`, [res_users.py:189](../../../../odoo/addons/base/models/res_users.py#L189), [:638](../../../../odoo/addons/base/models/res_users.py#L638). Overriding the old properties is silently ignored: the user can no longer save that field on their own record (only `base.group_erp_manager` can). Reads follow record rules, and every internal user reads every user ([base ir.access.csv:70](../../../../odoo/addons/base/security/ir.access.csv#L70)), so a secret stored on `res.users` needs `groups=` |
| Font Awesome (`fa fa-x`, `icon="fa-x"`) | Material Symbols — see §10 and `views.md` |

**Porting `get_param` reads.** Pick the getter by how the value is used. The typed getters
are not exact renames:

| v19 read | v20 | Trap |
|---|---|---|
| `get_param(key, 'B')` | `get_str(key, 'B')` | v19 returned `raw or default`, so a stored `''` gave the default. `get_str` returns `''`; only a missing row or a NULL value gives the default ([ir_config_parameter.py:124](../../../../odoo/addons/base/models/ir_config_parameter.py#L124)) |
| `get_param(key) == 'True'` | `get_bool(key, False)` | parsed by `str2bool`, so `'1'`, `'true'`, `'yes'`, `'on'` now read True ([misc.py:456](../../../../odoo/tools/misc.py#L456)) |
| `float(get_param(key))` inside `try/except ValueError` | `get_float(key, default)` | a non-numeric value already returns the default and logs a WARNING ([ir_config_parameter.py:149](../../../../odoo/addons/base/models/ir_config_parameter.py#L149)). Drop the wrapper |

A `res.config.settings` `get_values()` override that re-reads a `config_parameter=` field is
dead code in v20: core `default_get` already reads every such field with the typed getter and
the field default ([res_config.py:263-286](../../../../odoo/addons/base/models/res_config.py#L263)).
Delete the override instead of porting it.

`odoo.tools` only re-exports `SQL` and `drop_view_if_exists` from `tools.sql` now;
`from odoo.tools import *` no longer pulls in the whole SQL helper set —
[odoo/tools/\_\_init\_\_.py:15](../../../../odoo/tools/__init__.py#L15).

---

## 3. `read_group()` is back — and it is no longer deprecated

This reverses the v19 guardrail. In v20 there are three layers:

| Method | Where | Returns | Use it for |
|---|---|---|---|
| `read_group(domain, groupby, aggregates, having, offset, limit, order)` | `@typing.final @api.model`, [odoo/orm/models.py:1932](../../../../odoo/orm/models.py#L1932) | list of tuples, relational values as **ids** | RPC / external callers |
| `_read_group(...)` — same signature | [odoo/orm/models.py:1996](../../../../odoo/orm/models.py#L1996) | list of tuples, relational values as **recordsets** | all backend Python |
| `formatted_read_group(...)` | [addons/web/models/models.py:1022](../../../../addons/web/models/models.py#L1022) | web-formatted dicts | the web client |

The old v16 signature (`fields=`, `groupby=`, `lazy=True`, returning dicts) is gone for good.
Keep using `_read_group()` in server code — `read_group()` is the public wrapper, not a
replacement for it.

Also available (already in 19, still the right tool for multi-level aggregation in one
round-trip): `_read_grouping_sets(domain, grouping_sets, aggregates, order)`.

---

## 4. Signature changes — `Query` → `TableSQL`

Group-by and order hooks now receive a `TableSQL` object instead of `(alias, query)`:

```python
# v19
def _read_group_select(self, aggregate_spec, query): ...
def _read_group_groupby(self, alias, groupby_spec, query): ...
def _read_group_having(self, having_domain, query): ...
def _read_group_orderby(self, order, groupby_terms, query): ...
def _order_to_sql(self, order, query, alias=None, reverse=False): ...

# v20
def _read_group_select(self, table: TableSQL, aggregate_spec): ...
def _read_group_groupby(self, table: TableSQL, groupby_spec): ...
def _read_group_having(self, table: TableSQL, having_domain): ...
def _read_group_orderby(self, table: TableSQL, order, groupby_terms): ...
def _order_to_sql(self, table: TableSQL, order, reverse=False): ...
```

`TableSQL` supports **dotted traversal that auto-joins**: `table.company_id.currency_id`
produces the joined SQL expression. This is what makes `compute_sql` (below) short.

Other renames on `BaseModel`:

| v19 | v20 |
|---|---|
| `_has_field_access(field, op)` | `has_field_access(field, op)` (public) |
| `_check_field_access(field, op)` | `check_field_access(field, op)` (public) |
| `concat(*args)` / `union(*args)` | also accept one iterable: `union(list_of_recordsets)` |
| `_rec_names_search = ['name']` | `_rec_names_search = ('name',)` — tuple |

New: `models.get_public_method(model, name)` (replaces `check_method_name`),
`Model._access_domain(operation)` (the cached access domain, replaces reading `ir.rule`).

---

## 5. New: `compute_sql` — searchable/groupable computed fields without `store=True`

The highest-value new field attribute in v20. A non-stored computed field with
`compute_sql` becomes searchable, groupable and orderable, because the ORM can express it
in SQL. 82 core fields already use it.

```python
currency_id = fields.Many2one(
    'res.currency', 'Currency',
    compute='_compute_currency_id',
    compute_sql='_compute_sql_currency_id',
    compute_sudo=True,          # mandatory when compute_sql is set
)

@api.depends('company_id')
def _compute_currency_id(self):
    for template in self:
        template.currency_id = template.company_id.sudo().currency_id or main_currency

def _compute_sql_currency_id(self, table):
    main_company = self.env['res.company']._get_main_company()
    return SQL("COALESCE(%s, %s)", table.company_id.currency_id, main_company.currency_id.id)
```

[addons/product/models/product_template.py:99](../../../../addons/product/models/product_template.py#L99)

Rules enforced by the framework ([odoo/orm/fields.py:471](../../../../odoo/orm/fields.py#L471)):
- `compute_sql` only makes sense on a field that also has `compute`
- `compute_sudo` must be passed **explicitly** (warning otherwise)
- the method must return an `SQL` object

Prefer, in this order: plain compute → `compute_sql` → `search=` method → `store=True`.
`store=True` only when the value is genuinely stable and read far more often than written.

Also new: `init_storage=` (how a new column is populated at install time).

---

## 6. New: `models.CachedModel`

A Python-only mixin for small, rarely-changing reference tables (currencies, countries,
UoM-style data). It caches a fixed field set in the `'stable'` ormcache and serves reads
from it — [odoo/orm/models_cached.py](../../../../odoo/orm/models_cached.py).

```python
class MyRef(models.CachedModel):
    _name = 'my.ref'
    _cached_data_domain = []
    _cached_data_fields = ('code', 'name')   # no translated, context- or model-dependent fields
```

Do not reach for it by default. It is for data read on nearly every request.

---

## 7. ormcache moved and is now transaction-aware

```python
from odoo import api

@api.ormcache('self.env.company.id', 'code')       # default bucket
def _get_config(self, code): ...

@api.ormcache(cache='stable')                      # named bucket, invalidated separately
def _get_all_access(self): ...
```

Invalidation: `self.env.transaction.invalidate_ormcache('stable')`.
`registry.clear_cache()` is gone. The transaction also exposes
`invalidate_access_cache(model_name='')`, `clear()` and `reset()` —
[odoo/orm/environments.py:833](../../../../odoo/orm/environments.py#L833).

---

## 8. QWeb: `t-call` takes parameters as attributes

The nested `<t t-set>`-before-`t-call` idiom is replaced by attributes on the `t-call`
itself:

```xml
<!-- v19 -->
<t t-call="web.brand_promotion_message">
    <t t-set="_utm_medium">portal</t>
</t>

<!-- v20 -->
<t t-call="web.brand_promotion_message" _message.translate="" _utm_medium.f="portal"/>
```

| Suffix | Meaning |
|---|---|
| `name="expr"` | Python expression |
| `name.f="text"` | format string / literal |
| `name.translate="text"` | translatable literal |

[addons/web/views/webclient_templates.xml:103](../../../../addons/web/views/webclient_templates.xml#L103)

---

## 9. OWL 2 → OWL 3

`addons/web/static/lib/owl/owl.js` reports `3.0.0-alpha.49`. This is a different
reactivity model, not a version bump. See `owl.md` for the working rules.

| OWL 2 | OWL 3 |
|---|---|
| `useState(obj)` / `reactive(obj)` | `proxy(obj)` from `@odoo/owl` |
| `static props` / `static defaultProps` | `props = useProps(schema)` — the static form **throws** in the component constructor ([owl3_compatibility_layer.js:45](../../../../addons/web/static/src/owl2/owl3_compatibility_layer.js#L45)); field widgets use `useProps(standardFieldProps)`, client actions `useProps(standardActionServiceProps)` |
| `useEffect(fn, deps)` | `useLayoutEffect(fn, () => deps)` from `@web/owl2/utils`. `@odoo/owl` still exports a `useEffect(fn)`, but it is a new one-argument reactive effect — a deps argument is silently ignored |
| `useEnv`, `useSubEnv`, `onWillRender` | from `@web/owl2/utils` — its **only** exports are these three plus `render` and `useLayoutEffect` ([owl2/utils.js](../../../../addons/web/static/src/owl2/utils.js)) |
| `useRef("x")` + `t-ref="x"` + `ref.el` | `x = signal.ref()` + `t-ref="this.x"` + `this.x()` — `.el` is `undefined`, no error |
| `useExternalListener(target, ev, fn)` | `useListener(target, ev, fn)` from `@odoo/owl` (351 core uses) |
| `useComponent`, `useChildSubEnv`, `onRendered` | gone — no export anywhere, 0 imports in core |
| `t-esc` | `t-out` |
| `t-slot` | `t-call-slot` |
| `t-portal` | `t-custom-portal` |
| `t-ref`, `t-model` | directive names unchanged (core: `t-ref` 887, `t-custom-ref` 0; `t-model` 29) — only the `t-ref` value changed |
| implicit `this` in templates | explicit `this.props.x`, `this.state.x` |

Importing a name `@odoo/owl` no longer exports does not fail the bundle — the binding is
`undefined` and the component throws when `setup()` calls it. Full export list and the
migration procedure are in `owl.md`.

New core primitives: `computed`, `signal`, `t`, `useProps`, `useOnChange`, plugins
(`usePlugin`), scopes, resources. Counts in `addons/web/static/src`: `useState` 0,
`proxy(` 146, `t-esc` 2, `@web/owl2/utils` imports 58.

**v19 xpaths into core OWL templates stop matching.** Core templates now say
`t-component="this.props.Renderer"`, `t-if="this.model.isReady()"`, so a v19 xpath such as
`//t[@t-component='props.Renderer']` matches nothing and the view crashes with
"cannot be located in element tree". Rewrite every xpath against the v20 attribute text.

---

## 10. Smaller changes worth knowing

- **New view type `card`** — `ir.ui.view.type` selection now includes `('card', "Card")`,
  [odoo/addons/base/models/ir_ui_view.py:164](../../../../odoo/addons/base/models/ir_ui_view.py#L164).
- **`odoo.http` is a package** — `odoo/http/{dispatcher,router,session,stream,...}.py`.
  Route types unchanged: `type='http'`, `type='jsonrpc'` (422 core usages), plus the
  `/json/2/<model>/<method>` external API.
- **Cron**: `MIN_TIME_PER_JOB` 10 s → 120 s; failing crons now notify the admin before
  being deactivated; each job runs in its own `contextvars` context —
  [odoo/addons/base/models/ir_cron.py](../../../../odoo/addons/base/models/ir_cron.py).
- **`res.groups`**: `model_access` / `rule_groups` → `access_ids`; `privilege_id` is
  labelled "Scope" in the UI; disjoint-group validation is stricter.
- **UoM has no `rounding` field** — round quantities with
  `precision_digits=env['decimal.precision'].precision_get('Product Unit')`.
- **Binary fields hold `BinaryValue` objects, not base64** (`odoo.tools.binary`). Writing `bytes` raises
  `TypeError: <field>: use BinaryValue instead of bytes` ([fields_binary.py:112](../../../../odoo/orm/fields_binary.py#L112));
  a `str` is still accepted and decoded as base64 (RPC input). Write `BinaryBytes(raw)` (`from odoo.tools import BinaryBytes`):
  core turned v19 `base64.b64encode(buf.getvalue())` into `BinaryBytes(buf.getvalue())`
  ([l10n_hu_edi_tax_audit_export.py:110](../../../../addons/l10n_hu_edi/wizard/l10n_hu_edi_tax_audit_export.py#L110)). Reads
  return a `BinaryValue`: `.content` for bytes, `.to_base64()` for base64
  ([l10n_se_sie4_import import_wizard.py:289](../../../../enterprise/l10n_se_sie4_import/wizard/import_wizard.py#L289)). A leftover
  `base64.b64decode(record.file)` decodes the raw bytes as base64 and raises `binascii.Error` or returns garbage. Found in
  `gec_income_tax_report` (2026-09-24): Export and the Explanation Workbook crashed on the first click.
  **`ir.attachment.datas` is removed:** `create({'datas': ...})` only warns "Use raw, datas has beeen removed" and drops the
  key, so the attachment is created **empty**, no error ([ir_attachment.py:535](../../../../odoo/addons/base/models/ir_attachment.py#L535)).
  Pass `'raw': pdf_bytes`; plain `bytes` are accepted for `raw` only ([fields_binary.py:109](../../../../odoo/orm/fields_binary.py#L109)).
- **Tests**: new `MockHTTPClient` context manager in
  [odoo/tests/common.py](../../../../odoo/tests/common.py) for asserting outbound HTTP.
  **Untagged test classes now default to `standard` + `post_install`** ([common.py:605](../../../../odoo/tests/common.py#L605));
  v19 gave them `at_install`. A v19 file without `@tagged` silently moves from install time to after all modules load;
  opt back in with `@tagged('at_install', '-post_install')`.
- **`odoo.tools.safe_eval` is a package** (`evaluation`, `expression`, `runtime`).
- **Font Awesome is removed — icons are Material Symbols** (commit `3e15a7be694`). Icons are
  font ligatures: `<i class="oi" data-icon="check"/>`, not `class="fa fa-check"`. Button
  `icon=` takes the Material Symbols name directly (`icon="search"`, `icon="refresh"`,
  `icon="edit_square"`) — [view_button.js:24](../../../../addons/web/static/src/views/view_button/view_button.js#L24)
  copies it into `data-icon` as-is. The temporary `fa-` mapping is gone, so a leftover
  `icon="fa-search-plus"` renders as broken text (`-🔍-`). Brand/custom icons use the `oi_`
  prefix (`data-icon="oi_github"`); `oi-filled`, `oi-fw`, `oi-lg`, `oi-spin` replace the
  `fa-` utility classes — [icons.scss](../../../../addons/web/static/src/webclient/icons.scss).
  Only names in the shipped font subset render — the list is `ICONS` in
  [addons/web/icons.py](../../../../addons/web/icons.py). SCSS keyed on `.fa-x` must move to
  `[data-icon="x"]`, and view validation warns when an `<i data-icon>` has no `title`,
  `aria-label` or text. Mapping table and rules: `views.md` → Icons.
- **Manifest `version` must start with `20.0.`** — [odoo/modules/module.py:500](../../../../odoo/modules/module.py#L500)
  (`check_version`, [module.py:598](../../../../odoo/modules/module.py#L598)) logs "The module X has
  an incompatible version, setting installable=False" and the module shows **uninstallable**
  before any of its code is read. Short versions (`'1.0'`) are adapted to the running series
  and are fine; a hard-coded `19.0.x.y.z` is not. Changing the series prefix is a migration
  step, not a "version bump" — flag it and ask before editing.

---

## 11. Accounting: payments, bank accounts, statements

Found while porting `basis_bank` (2026-09-23). Each one breaks v19 code at import, at registry
setup or silently at run time.

**`account.payment.state` lost `in_process`** — v20 selection is `draft, paid, reconciled,
canceled, rejected` ([account_payment.py:37](../../../../addons/account/models/account_payment.py#L37)).

| v19 | v20 | Meaning |
|---|---|---|
| `in_process` | `paid` | posted, waiting for the bank statement |
| `paid` | `reconciled` | matched with the statement (or all its bills paid) |

- Writing `'in_process'` raises `ValueError: Wrong value` ([fields_selection.py:231](../../../../odoo/orm/fields_selection.py#L231)).
  A search on it silently matches nothing.
- Rename in two steps: `'paid'` → `'reconciled'` first, then `'in_process'` → `'paid'`. A blind
  `in_process` → `paid` replace turns every old `state == 'paid'` check into "any posted payment".
- `action_post()` sets `paid` for every payment. v19 sent `asset_cash` outstanding accounts straight to paid.
- `action_validate()` now means paid → `reconciled`. It raises for `asset_cash` outstanding
  accounts and for any state other than `paid` ([account_payment.py:1221](../../../../addons/account/models/account_payment.py#L1221)).
- `_valid_payment_states()` moved from `account.batch.payment` to `account.payment` and now returns
  `['paid', 'reconciled']` or `['paid']` ([account_payment.py:290](../../../../addons/account/models/account_payment.py#L290)).
- Journal items and the move use `commercial_partner_id`, not `partner_id`. Recipient bank
  accounts come from `commercial_partner_id.bank_ids`.

**`account.move.line.amount_residual` is computed on every line**, not only on reconcilable and
cash accounts ([account_move_line.py:1210](../../../../addons/account/models/account_move_line.py#L1210)).
A payment whose outstanding account is not reconcilable keeps a non-zero liquidity residual and stays `paid`.

**`res.bank` is deleted** — commit `113d77eb35aa` "[IMP] *: Improve UX of bank accounts".

| v19 | v20 |
|---|---|
| `res.bank` model, `res.partner.bank.bank_id` | gone. `bank_name`, `bank_bic` (free Char, uppercased on save) and the address live on `res.partner.bank` ([res_partner_bank.py:59](../../../../odoo/addons/base/models/res_partner_bank.py#L59)) |
| `acc_number` / `sanitized_acc_number` / `acc_holder_name` | `account_number` / `sanitized_account_number` / `holder_name` |
| `account.journal.bank_id` / `bank_acc_number` | `bank_bic` / `bank_name` / `bank_account_number`, related to `bank_account_id` ([account_journal.py:249](../../../../addons/account/models/account_journal.py#L249)) |
| `from odoo.addons.base.models.res_bank import sanitize_account_number` | `...base.models.res_partner_bank import ...` — the old path fails at import |

`@api.depends('bank_id.bic')` on a journal fails registry setup with "Wrong @depends"
([fields.py:949](../../../../odoo/orm/fields.py#L949)). A typed BIC can be 8 or 11 characters
(`CBASGE22` or `CBASGE22XXX`), so compare `bank_bic[:8]`.

**Bank feeds**: the name-mangled `__get_bank_statements_available_sources` is gone. Override
`_get_bank_statements_available_sources` ([account_journal.py:57](../../../../addons/account/models/account_journal.py#L57)).
A leftover `__` override is never called: the option disappears from the dropdown, but writing
its value still works, because a method-based selection is not validated on write
([fields_selection.py:231](../../../../odoo/orm/fields_selection.py#L231) skips the check when
`_selection` is `None`). A static-list selection such as `account.payment.state` does raise.

**`_create_bank_statements()` returns three values**: `(statement_ids, ignored_duplicates,
ignored_zero_amount)`. Zero-amount lines are now skipped
([account_bank_statement_import/models/account_journal.py:282](../../../../enterprise/account_bank_statement_import/models/account_journal.py#L282)).
Unpacking two values raises after the statements were already created.

**Reconcile a statement line from code** the way the bank widget does:
`st_line.set_line_bank_statement_line(aml_ids)`
([account_accountant/models/account_bank_statement.py:1720](../../../../enterprise/account_accountant/models/account_bank_statement.py#L1720)).
It skips lines that are already reconciled. Bank-API precedent for payment states:
`account_online_payment` maps bank pending/accepted to `paid` and leaves `reconciled` to
statement matching (`ONLINE_STATUS_TO_STATE`).

Also proven while installing the gec modules on a test database (2026-09-23):

- **`account.group` is deleted** — commit `c3313b336b9f` "[IMP] account: Replace account groups
  with account parent". `_inherit = 'account.group'` stops the registry with "Model
  'account.group' does not exist in registry".
- **OdooBot cannot trust bank accounts**: `res.partner.bank._user_can_trust()` refuses uid 1
  outside install or test mode ([res_partner_bank.py:317](../../../../addons/account/models/res_partner_bank.py#L317)),
  so crons and `odoo-bin shell` scripts must use a real user (`with_user(...)`) to set
  `allow_out_payment`.
- Payroll: `hr.salary.rule.category_id` no longer exists and the xmlid
  `hr_payroll.hr_payslip_run_view_kanban` is gone. Payroll replacements: §12.

Found while planning the `l10n_ge` merge of `gec_localization` + `gec_l10n_ge_tax` (2026-09-23):

- **Withholding field renames** in `l10n_account_withholding_tax`: `account.tax.is_withholding_tax_on_payment`
  → `is_withholding_tax` ([account_tax.py:13](../../../../addons/l10n_account_withholding_tax/models/account_tax.py#L13));
  `account.payment.should_withhold_tax` (Boolean) → `withhold` (Selection `withhold_pay` / `withhold` / `payment`,
  [account_payment.py:13](../../../../addons/l10n_account_withholding_tax/models/account_payment.py#L13)).
  Views, domains and chart data using the old names fail at install.
- **`account.tax.group` lost its settlement accounts** (`tax_payable_account_id`, `tax_receivable_account_id`,
  `advance_tax_payment_account_id`). They moved to `account.return.type`, company-dependent. Full notes:
  `documentations/account_returns.md`.
- **Core ships `l10n_ge`** and owns chart template `'ge'`. Chart-template functions are registered by
  *method name*, top of the MRO wins ([chart_template.py:78](../../../../addons/account/models/chart_template.py#L78)):
  a custom module that reuses a core name such as `_get_ge_res_company` silently replaces it. Extend a
  core chart with unique method names and `depends` on the l10n module; only define `@template('xx')`
  (model `template_data`) when you really create a new chart.
- **Installing** a module with `@template(code, model)` functions loads them into every existing company
  on that chart ([ir_module.py:72](../../../../addons/account/models/ir_module.py#L72): `_pre_reload_data`
  + `_load_data`). An upgrade (`-u`) does not. A backfill `post_init_hook` is redundant; records added in
  a later version still need a maintenance function or a chart reload.
- **No Georgian VAT return type.** Return types live in enterprise `l10n_xx_reports` modules (e.g.
  `l10n_at_reports/data/account_return_data.xml`). There is no `l10n_ge_reports`, and `account_reports`
  ships only the annual CIT and audit types (`account_return_data.xml`).
- **Account hierarchy is native**: `account.account` is `_parent_store` with `parent_id` and `active`
  (l10n CSVs load header accounts inactive), and the form and list already show Parent Account
  ([account_account_views.xml:72](../../../../addons/account/views/account_account_views.xml#L72)).
  The form has no `page[@name='Description']` any more.
- **Payment register pays only receivable/payable lines**: `account.payment._get_valid_payment_account_types()`
  returns `asset_receivable`, `liability_payable` ([account_payment.py:247](../../../../addons/account/models/account_payment.py#L247)).
  With context `hr_payroll_payment_register`, `hr_payroll_account` adds `liability_current`
  ([account_payment.py:11](../../../../enterprise/hr_payroll_account/models/account_payment.py#L11)), so a salary
  NET on `l10n_ge`'s 310310 (Current Liabilities, reconcilable) is payable; a partnered authority leg without
  that context is not, and 332010 Pension is not reconcilable as shipped.
- **`hr.payslip.action_register_payment` is gone** from `hr_payroll_account` (v19 had it at
  `models/hr_payslip.py:277`). A `super().action_register_payment()` override raises AttributeError.
- **`hr.work.entry.type.is_leave` is gone**, replaced by `count_as` (Selection `working_time` / `absence`,
  [hr_work_entry_type.py:36](../../../../addons/hr_work_entry/models/hr_work_entry_type.py#L36)). Data files
  setting `is_leave` stop the module install.
- **Chart reload never changes `reconcile` on an existing account**
  ([chart_template.py:457](../../../../addons/account/models/chart_template.py#L457), "Prevents overriding user
  setting"). An extension module's `reconcile` override reaches only companies that load the chart after it is
  installed; a type change to Payable still forces `reconcile=True` through the compute.
- **`l10n_ge` sales taxes as shipped (checked on a clean DB, 2026-09-23)**: under "Georgia (VAT Registered)"
  the fiscal position replaces `18%` by all six taxes whose `original_tax_ids` is `ge_vat_sale_18`
  (`18% S`, `18% AD`, `18% O`, `0% EXT F/L/O`) — a 100 invoice totals 154; under "Georgia (non-VAT
  Registered)" `18%` is removed (it is only valid for the VAT fiscal position,
  [partner.py:161](../../../../addons/account/models/partner.py#L161)) — no VAT on B2C invoices.

---

## 12. Payroll: rules, inputs, versions, pay runs

Verified while reviewing `geo_payroll` (2026-09-23). v20 `hr_payroll` is a redesign, not a rename
pass. Paths are under `enterprise/hr_payroll/` unless noted.

**Salary rules** ([models/hr_salary_rule.py](../../../../enterprise/hr_payroll/models/hr_salary_rule.py)):

| v19 | v20 |
|---|---|
| `struct_id` Many2one | `struct_ids` Many2many, required (:27, commit `c2f18f3de7e`) |
| `category_id` Many2one | `category_ids` Many2many (:49, commit `778de155cc1`); same on `hr.payslip.line` |
| `appears_on_payslip` Boolean | Selection `always` / `never` / `non_zero` (:52) |
| `condition_select` / `amount_select` value `input` + `*_other_input_id` | gone; `property_input` reads `inputs[rule.code]` (:60, :71) |

- Data files: write `category_ids` as `[(6, 0, [ref(...)])]` or `[(5, 0, 0)]`, and set `country_id`,
  `condition_select`, `amount_select` and the python code explicitly. `create()` logs one warning
  per rule otherwise (:378), and the rule country defaults to the installing company's country.
- A non-superuser editing a critical field (code, formula, categories, structures) flips the rule's
  xmlid to `noupdate` and sets `modified_by_user` (:430): a `noupdate="0"` rule stops receiving
  module upgrades once an accountant edits its formula. Account fields are not critical.

**Inputs** — `hr.payslip.input.type` is deleted (commit `ed42b78f2c0`). `hr.payslip.input` points to
`salary_rule_id` ([hr_payslip_input.py:22](../../../../enterprise/hr_payroll/models/hr_payslip_input.py#L22)),
its `code` is the rule's code, and a rule that reads `inputs['X']` sets `input_usage_payslip=True`
(core: `default_deduction_salary_rule` in `data/hr_salary_rule_data.xml`). `inputs['X']` is still the
input record with `.amount` / `.name` ([hr_payslip.py:1661](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1661)).
Also gone: `hr.payroll.structure.input_line_type_ids`, `hr.payslip.payslip_properties`,
`_compute_payslip_properties`.

**BASIC is pre-filled.** `_get_localdict` seeds `categories` from worked days through
`hr.work.entry.type.category_ids` ([hr_payslip.py:1645](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1645));
core maps `generic_work_entry_type_attendance` to BASIC (`data/hr_work_entry_type_data.xml`).
`payslip.paid_amount` / `_get_paid_amount()` are gone (commit `abfbb6bc98b`). The core BASIC rule is
now `category_ids=[(5, 0, 0)]` with `result = payslip._get_basic_salary()` and
`if not categories['BASIC']: categories['BASIC'] = result`. A v19 BASIC rule that keeps category BASIC
counts attendance twice in GROSS; a paid work entry type without a category is shown on the BASIC
line but missing from GROSS. A rule that sets `categories['BASIC']` in its code loses that on a **line edit**:
core forces the edited line and every line before it (`_recompute_with_forced_lines`, context
`force_payslip_line_overrides`, [hr_payslip.py:787-806](../../../../enterprise/hr_payroll/models/hr_payslip.py#L787)) and skips a
forced line's code, so GROSS and NET keep the attendance pre-fill: an edited BASIC changes nothing below it. Set the
category from the forced total in a `_get_localdict` override (geo_payroll `hr_payslip.py`), as core's own test
`test_payslip_manual_line_edit_and_compute` expects NET to move.

**One payslip spans several versions.** `_compute_worked_days_line_ids` adds every version with the same
`(employee, contract_date_start, contract_date_end)` ([hr_version.py:653](../../../../enterprise/hr_payroll/models/hr_version.py#L653))
whose `date_version` falls in the slip period ([hr_payslip.py:2180](../../../../enterprise/hr_payroll/models/hr_payslip.py#L2180)),
and prices each worked-day line with its own `version_id`. A second, manually created slip for the
later version pays that slice again.

**New "Version update" dialog on the employee form (not in v19).** `hr_payroll` patches
`EmployeeFormController.onRecordChanged` ([version_record_patch.js:15](../../../../enterprise/hr_payroll/static/src/js/version_record_patch.js#L15)):
on the first change of an existing employee whose shown version is the latest one and has
`validated`/`paid` payslips, it asks "Create new version / Correct the current version". The only
exclusions are `contract_date_end` and `resource_calendar_id` (module-private const, not extensible).
**Pitfall:** it does not filter employee-only fields the way core `hr` does
(`record.fields[key].related?.includes('version_id')`, [form_view.js:40](../../../../addons/hr/static/src/views/form_view.js#L40)),
so a custom one2many on `hr.employee` (e.g. `geo_payroll.work_log_ids`) triggers it. "Create new
version" then sends the changes to `action_create_version_from_update`, which keeps only `hr.version`
fields, and discards the form: the employee-only edit is lost. Default date is broken
(`toISOString().slice(0, 8)` + `-01` = `2026-09--01`), so the date input starts empty.

**Pay runs** ([models/hr_payslip_run.py](../../../../enterprise/hr_payroll/models/hr_payslip_run.py)):

| v19 | v20 |
|---|---|
| `_get_valid_version_ids(...)` → ids | `_get_valid_versions(...)` → recordset, one version per contract, effective at `date_start` (:131) |
| `generate_payslips(version_ids, employee_ids)` | `_generate_payslips()`, no args, from `self.version_ids`, filtered on the structure type (:585) |
| `action_payroll_hr_version_list_view_payrun(..., schedule_pay)` | 5th argument is `employee_type_ids`; the action lists employees, not versions (:550) |
| `schedule_pay` field | gone |
| `structure_id` optional | required, defaults to the first structure of the company country (:51) |

`version_ids` is stored and filled at create from `_get_valid_versions` (:182).

**Also removed or renamed:**

| v19 | v20 |
|---|---|
| `hr.payslip.action_edit_payslip_lines` + `hr.payroll.edit.payslip.lines.wizard` | inline line edits: `write()` → `_recompute_with_forced_lines()` ([hr_payslip.py:787](../../../../enterprise/hr_payroll/models/hr_payslip.py#L787)); lines before the edited sequence are forced with their stored, cent-rounded `amount` × `quantity` |
| `hr.payslip._filter_not_in_contract_payslips` | warning record `hr_payroll_warning_no_running_contract` (`data/hr_payroll_warning_data.xml:436`), which skips slips with `ignore_worked_day_lines` |
| `correct_sheet()` | `_action_correct_payslips()` now copies the origin's input lines ([hr_payslip.py:1221](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1221)) |
| `hr.payroll.structure.unpaid_work_entry_type_ids` | gone; `is_paid` is `amount_rate != 0` |
| `hr.version.work_entry_source`, `contract_wage` | gone; attendance tracking is `attendance_based` (Boolean, `hr_attendance`) |
| `hr.version.hourly_wage` Monetary | Float, 4 digits |
| xmlid `hr_work_entry.work_entry_type_attendance` / `work_entry_type_unpaid_leave` | `hr_work_entry.generic_work_entry_type_attendance` / `generic_work_entry_type_unpaid_leave` |
| menu `hr_work_entry_enterprise.menu_hr_payroll_root` | `hr_payroll.menu_hr_payroll_root` (module deleted) |

**Register payment**: core keeps the `hr_payroll_payment_register` context and its
`_reconcile_payments` hook, but no longer opens the wizard from a payslip. Re-implement the action
without `super()`, the way [l10n_au_hr_payroll_account/models/hr_payslip.py:491](../../../../enterprise/l10n_au_hr_payroll_account/models/hr_payslip.py#L491)
does, and add the form button.

**Batch moves**: with `company.batch_payroll_move_lines`, `_get_account_move_vals` also posts the run's
**draft** slips ([hr_payroll_account/models/hr_payslip.py:56](../../../../enterprise/hr_payroll_account/models/hr_payslip.py#L56)).
An override that validates slip by slip lets the first slip post the others before their checks run.

**Payslip read access for a non-HR group breaks in v20** (verified 2026-09-24, `hr_customization`
team leaders). `hr.payslip.name` was stored in v19; in v20 it is non-stored and computed from
`employee_id.legal_name`, which is `hr.group_hr_user` only ([hr_payslip.py:53](../../../../enterprise/hr_payroll/models/hr_payslip.py#L53)).
A group given `r` on `hr.payslip` then fails on `name`, `display_name`, `allowed_version_ids` and
`employee_version_ids_count` (AccessError on form open). Fix: redefine those three with
`compute_sudo=True`, as core does for `is_wrong_duration` (:179). Also, the `hr_payroll_attendance`
stat button now hides on `attendance_based` (was `attendance_count`), restricted to
system / HR manager / payroll user ([hr_version.py:7](../../../../enterprise/hr_payroll_attendance/models/hr_version.py#L7)):
extend its `groups`, and give the group `r` on `hr.attendance`, because `attendance_count`
reads attendances as the user.

Found while porting `geo_payroll` and its 352 tests (2026-09-23):

| v19 | v20 | Bites |
|---|---|---|
| Monthly worked-day amount = wage x hours / the slip's own worked hours | wage x hours / the **calendar's** work hours in the period ([hr_payslip_worked_days.py:66](../../../../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66)) | a test that fakes 160 h for a 176 h month now gets 1454.55, not 1600 |
| `hr.payslip.worked_days.version_id` related to the payslip | required stored field of its own (:28) | hand-made worked days need `version_id` |
| Refund created as a draft | `_action_refund_payslips()` validates it on creation (`hr_payslip.py:1207`) | a refund needs a validated origin; draft-refund states are gone |
| Out-of-contract work entry code `OUT` | `000.00` (`hr_work_entry.generic_hr_work_entry_type_out_of_contract`) | code checks on `'OUT'` never match |
| `resource.calendar.tz` | gone; `res.company.tz` and a required `hr.version.tz` | `calendar.tz = ...` raises AttributeError |
| New structure: no rules | `rule_ids` defaults to copies of `hr_payroll.default_structure` rules | pass `rule_ids` explicitly in data (`eval="[]"`) to get none |
| Draft run opens its payslips | `action_open_payslips()` calls `_generate_payslips()` every time a draft run is opened (`hr_payslip_run.py:409`) | an override must not raise when nothing new is left to generate |
| New structure's journal = default structure's journal (often empty) | `hr.payroll.structure.create()` sets the salary journal for **every** company ([hr_payroll_account/models/hr_payroll_structure.py:27](../../../../enterprise/hr_payroll_account/models/hr_payroll_structure.py#L27)) | an account configurator that treats "journal already set" as "an accountant configured this company" skips every company, and payslips post journal entries with no lines |

`account.payment.register` refuses lines of more than one `account_type` in one wizard, with the
misleading message "both inbound and outbound moves" (`account_payment_register.py:1049`; same in v19).
Salary NET, pension and any tax account paid together must share one type (Payable).

**Payroll access levels** (found in `gec_payroll_bank`, 2026-09-23): v19 had two levels,
`group_hr_payroll_user` "Officer: Manage all contracts" and Administrator. v20 has three
([security/hr_payroll_security.xml:10](../../../../enterprise/hr_payroll/security/hr_payroll_security.xml#L10)):
`group_hr_payroll_user` is now **Assistant**, the new `group_hr_payroll_officer` is Officer, and
Administrator implies Officer plus `hr.group_hr_manager` (:30). A custom group that implies
`group_hr_payroll_user` "for Officer rights" now grants Assistant only.

**Payslip header cards and line explanations** (verified 2026-09-24, `geo_payroll`):

- The new form cards ([views/hr_payslip_views.xml:90](../../../../enterprise/hr_payroll/views/hr_payslip_views.xml#L90))
  read `sum_worked_paid_days/hours` (worked-day lines whose work entry type rate is non-zero, i.e. the
  schedule) and `basic_wage` = the `BASIC` line only (`_get_basic_wage_line_codes`,
  [models/hr_payslip.py:620](../../../../enterprise/hr_payroll/models/hr_payslip.py#L620)). A structure
  whose base sits in other codes shows Wage 0.00. l10n_be widens the code set; `geo_payroll` leaves the
  cards alone (user decision) and adds its own card beside them (xpath `//div[@name='payslip_summary_widget']/div[1]`).
- Per-line tooltip: rule field `explanation_template` (translatable) is `.format(**explanation_info)`,
  where the rule code sets `explanation_info = {...}` in localdict (:1854, :1915; l10n_be uses
  `{explanation}` and builds the text in Python). **Pitfall:** on a manual line edit the engine forces
  lines with stored amounts and sets `explanation_info = {}`, so any template with a placeholder turns
  into "Explanation couldn't be computed due to a syntax issue" — restore it in your
  `_recompute_with_forced_lines` override. Don't detect that text by comparing with `self.env._(...)`:
  `env._` picks the module from the caller's frame, so the Georgian lookup differs from core's.
- `formatLang` rounds HALF-EVEN by default; payslip line totals round half-up. Pass
  `rounding_method='HALF-UP'` for amounts shown next to lines (10.625 shows 10.62 otherwise, line 10.63).
- `hr.payslip.edited` is set by any inline line edit ([models/hr_payslip.py:806](../../../../enterprise/hr_payroll/models/hr_payslip.py#L806))
  and never cleared: not by Compute, not by Cancel → Set to Draft (`action_payslip_draft`, :843). Logic
  keyed on `edited` stays on for the payslip's life; the way out is a new payslip. The edit audit keys
  lines by `salary_rule_id`, so two lines of one rule (e.g. two benefit deductions) log as a rename.

### HR, recruitment, salary configurator

Found while porting `alta_hr_customization/hr_customization` (2026-09-24). Each one was proven by a
failed install or a live `/hr_customization/offer/accept` call on a scratch DB.

| v19 | v20 | Bites |
|---|---|---|
| module `hr_org_chart` | merged into `hr` (commit `ea8ddab54acb`); xmlids move with it, e.g. `hr.hr_department_hierarchy_view` | `depends` fails with "hr_org_chart is not available"; `ref="hr_org_chart.x"` fails at install |
| `hr.applicant.user_id` (recruiter, `res.users`) | `recruiter_id` Many2one `hr.employee` ([hr_applicant.py:101](../../../../addons/hr_recruitment/models/hr_applicant.py#L101)); use `recruiter_id.user_id` for the user | `<field name="user_id" position=...>` cannot be located; Python reads `False` |
| `hr.version.contract_type_id` → `hr.contract.type` | `employee_type_id` → `hr.employee.type` (commit `6057e25f8c12`) | a groups-only redefinition `contract_type_id = fields.Many2one(groups=...)` declares a new field with no comodel |
| `contract_date_start/end` narrowed to `hr_payroll.group_hr_payroll_user` by `hr_payroll` | `hr.group_hr_user` in `hr`, not narrowed any more | a copied v19 `groups=` override now takes the dates away from HR officers |
| `hr.version.hourly_wage` Monetary | Float, 4 digits (see §12) | a `fields.Monetary(groups=...)` override silently changes the field type |

**`hr_contract_salary` simulation** ([utils/hr_version.py](../../../../enterprise/hr_contract_salary/utils/hr_version.py)):

- The hand-written `flush_all()` + `cr.savepoint(flush=False)` + `rollback()` block is replaced by
  `with hr_version_context(request, invalidate=True):`. `offer._get_version()` is decorated
  `@requires_hr_version_context()` and raises `RuntimeError` outside it.
- The check reads the **record's own** `env.context`, so browse the offer inside the block, the way
  core `submit` does ([controllers/main.py:1082](../../../../enterprise/hr_contract_salary/controllers/main.py#L1082)).
  An offer browsed before the block fails.
- `create_new_version(version_vals, offer, benefits, ...)` takes the offer **record** (v19: `offer_id`) and
  calls `offer._get_version()` itself ([controllers/main.py:770](../../../../enterprise/hr_contract_salary/controllers/main.py#L770)),
  so it needs the offer browsed inside the block. Use a separate, normal-context record for writes after
  the block: the block's context carries `tracking_disable`.
- `hr.version._get_gross_from_employer_costs()` is gone. `_get_version()` now writes `wage` from
  `_get_wage_from_yearly_costs(offer.final_yearly_costs)` ([hr_contract_salary_offer.py:192](../../../../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L192)).
  Build `version_vals` with `self._compute_submit(version, offer, benefits, **kw)`.
- Templates: the `<h1>Customize your salary</h1>` heading is removed from `salary_package`; the
  "define a signature template" `alert-danger` became an `alert-info d-flex` "No PDF templates" alert
  (`invisible="has_any_template or sign_template_id"`); `#hr_cs_submit` in `salary_package_next_step_button`
  now has `t-if="resume_line_count"`. Extend that `t-if` with an attribute xpath instead of replacing
  the button.

---

## 13. Unchanged — do not "fix" these

Still correct in v20, despite churn elsewhere:

- `models.Constraint(...)` / `models.Index(...)` / `models.UniqueIndex(...)` class attributes
  (`_sql_constraints` has 1 remaining occurrence in all of `addons/`)
- `@api.model_create_multi`, `@api.depends`, `@api.constrains`, `@api.ondelete`, `@api.onchange`
- `_compute_display_name()` (not `name_get()`)
- `<list>` (0 `<tree>` tags left in core views), `invisible="..."` expressions, `<chatter/>`
- `type='jsonrpc'` for JSON routes
- `odoo.Command`, `odoo.fields.Domain`, `bypass_search_access` (the v19 replacement for `auto_join`)
- `check_company=True`, `_check_company_auto`, `company_dependent=True`
- `self.env._("...")` as the preferred translation call

---

## 14. Stock, accounting, HR and platform changes (verified 2026-09-24)

Each item was verified in the 20.0 source while `documentations/` was reviewed. Paths are relative to this file.

### Stock and manufacturing

| v19 | v20 | Bites |
|---|---|---|
| `stock.scrap` model | removed (commit `1c7d80a10b5d`): a scrap is a `stock.move` with `is_scrap` ([stock_move.py:139](../../../../addons/stock/models/stock_move.py#L139)), posted by `_action_scrap()` ([:2961](../../../../addons/stock/models/stock_move.py#L2961)); new fields `scrap_reason_tag_ids`, `should_replenish_scrapped` | `_inherit = 'stock.scrap'` stops the registry. Kits cannot be scrapped: the scrap form's product domain has `is_kits = False` ([mrp stock_move_views.xml:81](../../../../addons/mrp/views/stock_move_views.xml#L81)) |
| `stock.return.picking` wizard (`stock/wizard/stock_picking_return.py`) | removed (commit `36b4a0f5fb2b`): **Return** calls `stock.picking._create_return()`, which builds a draft return transfer with every line at 0 ([stock_picking.py:976](../../../../addons/stock/models/stock_picking.py#L976)); Return All / Clear / Exchange are picking buttons ([:823](../../../../addons/stock/models/stock_picking.py#L823), [:843](../../../../addons/stock/models/stock_picking.py#L843)). Override `_prepare_return_move_default_values()` / `_prepare_return_picking_default_values()` | code creating `stock.return.picking` or inheriting its view fails |
| `to_refund` on the return wizard line (debug column) | only `stock.move.to_refund` (default True, copied, [stock_account stock_move.py:27](../../../../addons/stock_account/models/stock_move.py#L27)); no view shows it | every return lowers Delivered / Received; "return without updating the SO/PO" needs code |
| `stock.picking._create_backorder(self, backorder_moves=None)` | `_create_backorder(self, backorder_moves=None, from_manual_backorder=False)` ([stock_picking.py:1397](../../../../addons/stock/models/stock_picking.py#L1397)); **Split** passes the flag by keyword ([:1260](../../../../addons/stock/models/stock_picking.py#L1260)), enterprise `quality_control` passes it positionally ([stock_picking.py:98](../../../../enterprise/quality_control/models/stock_picking.py#L98)) | an override with the v19 signature makes Split raise `TypeError` (verified with `rs_waybill`, 2026-09-25); with `quality_control` above it in the MRO every backorder would raise too (read from the signatures, not run). Override with the full v20 signature and forward both arguments |
| `stock.move.location_final_id` | `forecasted_location_id` ([stock_move.py:86](../../../../addons/stock/models/stock_move.py#L86)) | reads and domains on the old name fail |
| module `stock_picking_batch`, setting `module_stock_picking_batch` | merged into `stock`; setting `group_stock_picking_batch` ([res_config_settings.py:19](../../../../addons/stock/models/res_config_settings.py#L19)) | `depends` on the module fails |
| `stock.rule._run_push()` | removed; push rules are applied per move by `stock.move._push_apply()` ([stock_move.py:1270](../../../../addons/stock/models/stock_move.py#L1270)) | overrides are never called |
| `stock.move.line.action_revert_inventory()` | `action_revert()`, which also reverts scraps ([stock_move_line.py:1223](../../../../addons/stock/models/stock_move_line.py#L1223)) | |
| reception report, `group_stock_reception_report`, mrp `group_mrp_reception_report` | `stock.allocation.report` + operation-type field `auto_show_allocation_report` ([stock_picking_type.py:104](../../../../addons/stock/models/stock_picking_type.py#L104)) | |
| setting `default_picking_policy` | `res.company.picking_policy`; saving settings rewrites `move_type` on every operation type of the company ([res_config_settings.py:103](../../../../addons/stock/models/res_config_settings.py#L103)) | a per-type shipping policy is overwritten on the next settings save |
| `stock.quantity.history` wizard | removed | |
| `product.template.tracking = 'none'` | no such value; `False` means untracked ([product.py:835](../../../../addons/stock/models/product.py#L835)) | data files writing `'none'` fail |
| `security_lead`, `horizon_days` Float | Integer; the `module_delivery_*` settings are gone | |
| `stock.lot.partner_ids` computed | stored, and written at delivery ([stock_move_line.py:704](../../../../addons/stock/models/stock_move_line.py#L704)) | |
| BoM/MO `consumption` (flexible / warning / strict) | removed: a quantity mismatch always opens the warning; skip it with context `skip_consumption` ([mrp_production.py:1893](../../../../addons/mrp/models/mrp_production.py#L1893)) | code reading `bom.consumption` fails |
| `stock.move.manual_consumption` | removed: a picked move is simply not recomputed ([mrp stock_move.py:213](../../../../addons/mrp/models/stock_move.py#L213)) | |
| mrp setting `group_mrp_workorder_dependencies` | removed | |
| maintenance stage `done`, request `user_id`, `kanban_state`, `request_date`, instruction PDF / Google Slide fields | `state` ([maintenance.py:294](../../../../addons/maintenance/models/maintenance.py#L294)) and technicians `user_ids` ([:287](../../../../addons/maintenance/models/maintenance.py#L287)); internal users see only requests they created, follow or are assigned to ([ir.access.csv:5](../../../../addons/maintenance/security/ir.access.csv#L5)) | |

### Accounting and the Georgian localization

- **Currency rates apply from the next day.** `_get_rates()` takes the latest rate dated strictly before the document
  date ([res_currency.py:185](../../../../odoo/addons/base/models/res_currency.py#L185), commit `cba671dfb30d`). The
  National Bank of Georgia provider stores each rate under the day it becomes valid (`validFromDate`, [res_config_settings.py:501](../../../../enterprise/currency_rate_live/models/res_config_settings.py#L501)),
  so with automatic NBG rates every document is valued at the previous day's official rate. Checked against the live
  NBG feed on 2026-09-24.
- **A Bank and Cash or Credit Card account creates its journal** ([account_account.py:1129](../../../../addons/account/models/account_account.py#L1129)),
  also when a module installs such accounts into an existing company ([ir_module.py:80](../../../../addons/account/models/ir_module.py#L80)).
- Journal Items and invoice lines no longer offer Bank and Cash accounts ([account_move_views.xml:1536](../../../../addons/account/views/account_move_views.xml#L1536)).
- A move that was never posted can be deleted regardless of lock dates (`_can_be_unlinked`, [account_move.py:5919](../../../../addons/account/models/account_move.py#L5919)).
- `account.journal.code` lost its `size=7` limit.
- `account_online_synchronization` replaces `setting_init_bank_account_action` ([company.py:10](../../../../enterprise/account_online_synchronization/models/company.py#L10)):
  the dashboard's Bank card opens the online bank search, not the manual form.
- `res.partner._display_address(without_company=True)` raises `TypeError`: the signature is
  `_display_address(without_name=False, separator='\n')` ([res_partner.py:1307](../../../../odoo/addons/base/models/res_partner.py#L1307)).
  `without_name` is the renamed flag (drops the parent company line). v19 `' '.join(p._display_address(without_company=True).split())`
  is `p._display_address(without_name=True, separator=' ')` in 20, the core one-line form
  ([project_project.py:248](../../../../addons/project/models/project_project.py#L248)); the computed `address_inline` uses `', '`.
- **`res.partner.is_company` is computed from the Tax ID** (commit `f2965048f60f` "[REM] base: company_type is dead for good"):
  a contact is a company when it is its own commercial entity and has a VAT ([res_partner.py:946](../../../../odoo/addons/base/models/res_partner.py#L946)).
  `company_type` and the Person/Company switch are gone, and `is_company=False` written with or before a VAT is recomputed to
  True. 15 localizations override `_compute_is_company` (e.g. `l10n_uz`: only a 9-digit TIN is a company,
  [res_partner.py:8](../../../../addons/l10n_uz/models/res_partner.py#L8)); `l10n_ge` does not, so a Georgian individual whose
  11-digit personal number is in Tax ID is a company. Code that branches on `is_company` (name splitting, person-only fields)
  misreads such contacts. Proven on a scratch DB, 2026-09-24 (`gec_income_tax_report` split "ნუცა თორაძე" as a company).
- `l10n_account_withholding_tax`: when the register-payment wizard will create one payment per bill (no Group Payments),
  the withholding lines are not offered ([account_payment_register.py:151](../../../../addons/l10n_account_withholding_tax/wizards/account_payment_register.py#L151)).
- `l10n_ge` as shipped: "Georgia (VAT Registered)" means "the contact has a Tax ID" (`has_vat`, [partner.py:924](../../../../addons/account/models/partner.py#L924)),
  and under "Non-Georgia" one purchase `18%` is replaced by three reverse-charge taxes ([account.tax-ge.csv:134](../../../../addons/l10n_ge/data/template/account.tax-ge.csv#L134)).
  The sales mappings are in §11; all three defects and their fix options are in `documentations/l10n_ge.md`.
- **Default taxes on invoice lines** (`_get_computed_taxes`, commit `d069ce59e28f`): a product-less sales line typed in the
  invoice tab now gets `company.account_sale_tax_id`, and a company flagged `vat_disabled` gets it on every sales line
  ([account_move_line.py:1305](../../../../addons/account/models/account_move_line.py#L1305), :1316). Vendor-bill lines
  still never get `account_purchase_tax_id`; core says so at :1324 and leaves bill taxes to the product's
  `supplier_taxes_id`, the account's taxes and the fiscal position. Code that "applies the company default purchase tax
  like core" does not copy core. `l10n_ge` ships nine purchase taxes at exactly 18%, each on its own VAT-return box
  (24, 29-33, reverse charge 21-23/27), so a search on `amount = 18` picks one by `sequence, id`.

### HR, time off, payroll

- **One country-bound work entry type hides all generic ones.** Since core commit `f144f933c7ba` nine
  `_compute_allowed_work_entry_type_ids` (time off, allocations, accrual plans, both multi wizards, schedule lines,
  public holidays, company, payroll structure types, plus the holiday loader) offer only the country's types as soon
  as one active type with that country exists ([hr_leave.py:322](../../../../addons/hr_holidays/models/hr_leave.py#L322)).
  v19 had no such rule. Core gives a localized country a complete set in
  [hr_work_entry_type_data.xml](../../../../addons/hr_work_entry/data/hr_work_entry_type_data.xml) (32 countries, not
  Georgia) and remaps existing records with `res.country._adapt_work_entry_types_to_country`
  ([res_country.py:15](../../../../enterprise/hr_payroll/models/res_country.py#L15)) from the l10n payroll modules. Never
  ship a single `country_id`-bound time type; leave `country_id` empty. `geo_payroll`'s `GE_PUBLIC_HOLIDAY` did that
  and left Georgian companies with "Public Holiday" as the only choice; removed 2026-09-24.
- **hr_payroll's weekly cron "Payroll: Update data" sets `noupdate=False` on the xmlid of every time type not
  edited by a user**, ours included ([hr_work_entry_type.py:88](../../../../enterprise/hr_payroll/models/hr_work_entry_type.py#L88),
  cron `ir_cron_update_payroll_data`). `noupdate="1"` in our XML therefore stops protecting time types: once the
  cron has run, removing a type from module data makes the next `-u` delete it (`_process_end`), and before the
  first run the row stays. Proven on `gec20_geo_payroll_test` 2026-09-24 (both cases).
- `resource.calendar.calendar_type` values are `fixed` / `variable` / `undefined` ([resource_calendar.py:78](../../../../addons/resource/models/resource_calendar.py#L78)).
- Worked-day pricing tests `worked_days.code in '000.00'`, a substring test ([hr_payslip_worked_days.py:114](../../../../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L114)):
  custom codes such as `0`, `00` or `.` are priced at 0.
- The weekly time-rule cron handles only rules whose week start is the day it runs ([hr_time_rule_source_mixin.py:195](../../../../addons/hr_work_entry/models/hr_time_rule_source_mixin.py#L195)),
  and `hr.time.rule` requires start < stop ([hr_time_rule.py:226](../../../../addons/hr_work_entry/models/hr_time_rule.py#L226)), so a window across midnight cannot be defined.
- `hr.payslip.state` is `draft` / `validated` / `paid` / `cancel`. The payment report wizard's IBAN check filters
  `state == "done"` and therefore never runs ([hr_payroll_payment_report_wizard.py:11](../../../../enterprise/hr_payroll_account/wizard/hr_payroll_payment_report_wizard.py#L11)).
- `action_payslip_paid()` keeps a `paid_date` that is already set ([hr_payslip.py:1070](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1070)).
- `hr_payroll_attendance`'s pay-run warning filters on `overtime_status`, a field that no longer exists ([hr_payslip_run.py:19](../../../../enterprise/hr_payroll_attendance/models/hr_payslip_run.py#L19));
  not run, but a crash is likely when that warning is evaluated.
- `hr_contract_salary`: refusing or deleting an offer removes only the versions it created, keyed on `originated_offer_id`
  ([hr_contract_salary_offer.py:645](../../../../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L645)).

### Platform

- `ir.mail_server.max_email_size` and `action_retrieve_max_email_size` are gone; the limit is the system parameter
  `base.default_max_email_size`, 20 MB by default ([ir_mail_server.py:258](../../../../odoo/addons/base/models/ir_mail_server.py#L258)).
- Enterprise `ai` has no provider keys or `LLMApiService`: every call goes through Odoo AI over IAP
  (`call_odoo_ai`, [ai_utils.py:109](../../../../enterprise/ai/utils/ai_utils.py#L109)); install aborts without pgvector
  (`_pre_init_ai`, [ai/__init__.py:20](../../../../enterprise/ai/__init__.py#L20)). `ai_app` and `esg_csrd_ai` are deleted.
- The light-user group `base.group_user_regular` gates menus such as Dashboards ([menu_views.xml:13](../../../../addons/spreadsheet_dashboard/views/menu_views.xml#L13)).
- `auth_ldap`: `change_password(old, new)` is `_change_password(new_passwd)` ([res_users.py:52](../../../../addons/auth_ldap/models/res_users.py#L52));
  `auth_signup`: `res.users.state` can be `inactive` ([res_users.py:24](../../../../addons/auth_signup/models/res_users.py#L24)).
- **Sign:** `sign.completed.document` is replaced by `sign.request.document` ([sign_request_document.py:19](../../../../enterprise/sign/models/sign_request_document.py#L19),
  enterprise commit `d542cb352d8`); `render_document_with_items()` returns `(overlay, regions)` ([sign_document.py:594](../../../../enterprise/sign/models/sign_document.py#L594));
  completion runs `_finalize_documents()` ([sign_request_document.py:151](../../../../enterprise/sign/models/sign_request_document.py#L151));
  roles can require an external signature (`requires_external_signature`, [sign_item_role.py:44](../../../../enterprise/sign/models/sign_item_role.py#L44)).
  A module inheriting `sign.completed.document` (our `id_ge_sign`) does not load.

## 15. Payroll: work entries, payslip entries and payments (verified 2026-09-24)

- **No `hr.work.entry` model any more** (`'hr.work.entry' not in env`; v19 had `hr_work_entry/models/hr_work_entry.py`).
  Worked days come from the calendar at compute time; `generate_work_entries()` only builds values.
- **A payment through a method line without an Outstanding account has no journal entry**: it is `paid` but reconciles
  nothing ([account_payment.py:529](../../../../addons/account/models/account_payment.py#L529)). New bank journals'
  "Manual Payment" line has none, so a payroll Register Payment there leaves the payslip `validated` and its payables open
  (a later Pay Salaries pays them again). l10n_au refuses this case in its payroll wizard (`_create_payments`).
- **`hr.payslip.run.action_draft` keeps each slip's journal entry** ([hr_payslip_run.py:303](../../../../enterprise/hr_payroll/models/hr_payslip_run.py#L303));
  re-validation skips slips that have one ([hr_payroll_account hr_payslip.py:55](../../../../enterprise/hr_payroll_account/models/hr_payslip.py#L55)),
  so recomputed amounts never reach the books and Pay Salaries pays the old net. Only the payslip Cancel path unlinks or
  reverses the entry ([hr_payroll_account hr_payslip.py:29](../../../../enterprise/hr_payroll_account/models/hr_payslip.py#L29)).
- **The payslip list actions "Cancel" and "Set to Draft" run on any state** ([hr_payslip_views.xml:385](../../../../enterprise/hr_payroll/views/hr_payslip_views.xml#L385),
  [:346](../../../../enterprise/hr_payroll/views/hr_payslip_views.xml#L346)); `action_payslip_cancel` only stops non-managers
  on validated slips ([hr_payslip.py:1055](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1055)). A manager can cancel
  or reopen a paid slip; the form buttons hide both.
- **`_action_correct_payslips()` creates no refund**; the UI wizard does refund + correction
  ([hr_payslip_correction_wizard.py:80](../../../../enterprise/hr_payroll/wizard/hr_payslip_correction_wizard.py#L80)). Call the
  wizard (or both methods) in scripts and tests.
- **A one-cent rounding gap needs the salary journal's default account**: `_prepare_adjust_line` raises "The Expense Journal
  ... has not properly configured the default Account!" without it ([hr_payroll_account hr_payslip.py:260](../../../../enterprise/hr_payroll_account/models/hr_payslip.py#L260)).
  Rules computed on unrounded categories hit it on prorated wages (952.38 base: 19.05 + 186.67 + 746.67 = 952.39).
  Localizations pass `default_account=` to `_configure_payroll_account` (AU, AE, BE, HK).

## 16. Payroll: reset, cancel, inputs and pay-run validation (verified 2026-09-25)

- **A reset recomputes the lines, not the inputs.** Core `write` refreshes a slip whose state goes back to draft
  ([hr_payslip.py:696](../../../../enterprise/hr_payroll/models/hr_payslip.py#L696), :781, `action_refresh_from_work_entries` :1326-1335), but
  `_compute_input_line_ids` depends only on employee, version, structure and dates (:337-338). Inputs injected from other records
  (benefits, attachments you manage yourself) stay as they were while the slip sat validated or cancelled, and Validate does not
  recompute. Mark them in an `action_refresh_from_work_entries` override *before* `super()`; marking after the refresh leaves lines
  built from the old inputs (a changed deduction paid at the old amount, a once-bonus another slip took paid twice).
- **Core Cancel keeps a reversed entry linked.** hr_payroll_account's `action_payslip_cancel` calls `_unlink_or_reverse()`
  ([hr_payslip.py:29-32](../../../../enterprise/hr_payroll_account/models/hr_payslip.py#L29)); only a deleted move clears `move_id`. Under a
  lock date or hash it is reversed, under a restrictive audit trail cancelled, and the slip still points at it; after Set to Draft,
  validation skips any slip with `move_id` (:55), so no new entry is booked. Release before `super()` and clear `move_id`; unlink
  (never reverse again) an entry whose `reversal_move_ids` is set or whose state is `cancel`.
- **`inputs['CODE']` holding several inputs is core's aggregator proxy** ([hr_payslip.py:1671-1675](../../../../enterprise/hr_payroll/models/hr_payslip.py#L1671),
  :2457-2511): `.amount` sums, `.name` joins, every other field behaves as on a multi-record recordset (a Many2one returns the union,
  a scalar raises "Expected singleton", wrapped as "Wrong python code"). A helper that follows one input's link must loop over the records.
- **Pay-run Validate re-sends validated slips.** `hr.payslip.run.action_validate` filters only cancelled and line-less slips
  ([hr_payslip_run.py:384-386](../../../../enterprise/hr_payroll/models/hr_payslip_run.py#L384)), so `action_payslip_done` also gets the run's
  already validated ones; a guard written for drafts must filter drafts.
- **Edited lines are marked.** `hr.payslip.line.manually_modified` ([hr_payslip_line.py:58](../../../../enterprise/hr_payroll/models/hr_payslip_line.py#L58))
  is set on lines the user edited. A check that re-runs `_get_payslip_lines()` to compare with stored lines must replay them through
  `force_payslip_line_overrides`, or every edit reads as drift.

## 17. Fleet: license plates are unique (verified 2026-09-26)

- **Fleet license plates are unique.** `fleet.vehicle` has `models.Constraint('UNIQUE(license_plate)')`
  ([fleet_vehicle.py:158](../../../../addons/fleet/models/fleet_vehicle.py#L158), commit `1c8fb57eb5cb`); 19.0 had none. It spans all
  companies and archived vehicles. Code that found or created a vehicle per driver + plate now raises `UniqueViolation` for a truck
  shared by two drivers: find by plate alone with `active_test=False` and keep the driver on your own record. Do not do that lookup in
  an onchange that sets a vehicle when another onchange copies the vehicle's driver: onchanges cascade
  ([web models.py:2369](../../../../addons/web/models/models.py#L2369)) and overwrite the driver the user picked.
