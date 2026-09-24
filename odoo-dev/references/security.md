# Security — Odoo 20

Odoo 20 replaced `ir.model.access` **and** `ir.rule` with a single model, `ir.access`.
If you write v19-style security files they will not load. Read section 1 before writing
any security file.

Source: [odoo/addons/base/models/ir_access.py](../../../../odoo/addons/base/models/ir_access.py),
[odoo/orm/models.py:3603](../../../../odoo/orm/models.py#L3603) (`_access_domain`).

1. [The one access model](#1-the-one-access-model)
2. [Writing `ir.access.csv`](#2-writing-iraccesscsv)
3. [Groups and privileges](#3-groups-and-privileges)
4. [The `access` domain operator](#4-the-access-domain-operator)
5. [Field-level security](#5-field-level-security)
6. [Programmatic access checks](#6-programmatic-access-checks)
7. [`sudo()` discipline](#7-sudo-discipline)
8. [Portal and public routes](#8-portal-and-public-routes)
9. [Raw SQL safety](#9-raw-sql-safety)
10. [CSRF and webhooks](#10-csrf-and-webhooks)
11. [Secrets and sensitive data](#11-secrets-and-sensitive-data)
12. [Vulnerability table](#12-vulnerability-table)

---

## 1. The one access model

Every access row is an `ir.access` record. The `group_id` decides what the row *is*:

| `group_id` | Kind | Effect |
|---|---|---|
| set | **permission** | grants the listed operations on matching records |
| empty | **restriction** | limits the listed operations for *everyone*, including admins of other companies |

The ORM resolves them into one domain per operation:

```python
# odoo/orm/models.py:3647
return Domain.OR(permissions) & Domain.AND(restrictions)
```

Three consequences you must internalize:

- **No permission row → no access.** `Domain.OR([])` is `FALSE`. A new model with no
  `ir.access.csv` row is invisible to every non-superuser.
- **Permissions are unioned.** A user in two groups gets the union of their domains. To
  widen access, add a row; never edit another module's row.
- **Restrictions are intersected and unconditional.** This is where multi-company scoping
  lives. A restriction cannot be escaped by adding a group.

The evaluation context for `domain` is `user`, `time`, `company_id`, `company_ids` —
[ir_access.py:`_eval_context`](../../../../odoo/addons/base/models/ir_access.py#L312).

---

## 2. Writing `ir.access.csv`

One file per module: `security/ir.access.csv`. The header is fixed and identical in all
506 core files:

```csv
id,name,model_id,group_id/id,operation,domain
```

| Column | Value |
|---|---|
| `id` | XML id, unique in the module |
| `name` | human label, shown in access-error messages |
| `model_id` | the **model name** (`sale.order`), not `model_sale_order` |
| `group_id/id` | group XML id, or empty for a restriction |
| `operation` | a subset of `crud` in that order: `r`, `ru`, `cru`, `crud`, `cud`, … |
| `domain` | optional; quoted if it contains commas |

`operation` is a single Selection value, not four booleans. The legal subsets are listed in
[`CRUD_SELECTION`](../../../../odoo/addons/base/models/ir_access.py#L16).

### Template

```csv
id,name,model_id,group_id/id,operation,domain
access_my_model_user,my.model user,my.model,my_module.group_my_module_user,cru,
access_my_model_manager,my.model manager,my.model,my_module.group_my_module_manager,crud,
access_my_model_line_user,my.model.line user,my.model.line,my_module.group_my_module_user,crud,
my_model_comp_rule,My Model multi-company,my.model,,crud,"[('company_id', 'in', company_ids)]"
my_model_own_records,My Model: own records only,my.model,my_module.group_my_module_user,cru,"[('user_id', '=', user.id)]"
access_my_wizard,my.wizard,my.wizard,base.group_user,crud,"[('create_uid', '=', user.id)]"
```

Read the real thing before writing your own —
[addons/sale/security/ir.access.csv](../../../../addons/sale/security/ir.access.csv).

### Manifest placement

```python
'data': [
    'security/my_module_security.xml',   # groups + privilege — FIRST
    'data/...', 'report/...', 'wizard/...', 'views/...', 'views/menus.xml',
    'security/ir.access.csv',            # access — LAST
],
```

Verified in `account`, `stock`, `project`, `hr`, `purchase`, `mail`, `sale`: groups file is
entry 0, `ir.access.csv` is the last entry. This is the opposite of the v19 convention.

### Translating a v19 module

| v19 | v20 |
|---|---|
| `perm_read=1,perm_write=1,perm_create=1,perm_unlink=0` | `operation` = `cru` |
| `perm_read=1` only | `operation` = `r` |
| `<record model="ir.rule">` with `groups` | a permission row with that group + `domain` |
| `<record model="ir.rule">` without `groups` | a restriction row (empty `group_id`) + `domain` |
| `domain_force` | the `domain` column |
| one ACL row + one rule row for the same group | **one** row carrying both |

---

## 3. Groups and privileges

File: `security/<module>_security.xml`, first in `data`. Three levels:
`ir.module.category` ▶ `res.groups.privilege` ▶ `res.groups`.

```xml
<odoo>
<data>
    <record model="res.groups.privilege" id="res_groups_privilege_my_module">
        <field name="name">My Module</field>
        <field name="sequence">20</field>
        <field name="category_id" ref="base.module_category_operations"/>
    </record>

    <record id="group_my_module_user" model="res.groups">
        <field name="name">User</field>
        <field name="sequence">10</field>
        <field name="privilege_id" ref="res_groups_privilege_my_module"/>
        <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
    </record>

    <record id="group_my_module_manager" model="res.groups">
        <field name="name">Administrator</field>
        <field name="sequence">20</field>
        <field name="privilege_id" ref="res_groups_privilege_my_module"/>
        <field name="implied_ids" eval="[(4, ref('group_my_module_user'))]"/>
        <field name="user_ids" eval="[(4, ref('base.user_root')), (4, ref('base.user_admin'))]"/>
    </record>
</data>
</odoo>
```

Pattern copied from
[addons/purchase/security/purchase_security.xml](../../../../addons/purchase/security/purchase_security.xml).

- `res.groups` has no `category_id` — it has `privilege_id` (labelled "Scope" in the UI)
- `user_ids`, not `users`
- Manager implies User; never restate a permission a group already implies
- A group with no privilege is a plain feature flag (e.g. `group_warning_purchase`)
- `res.groups.access_ids` is the reverse of `ir.access.group_id` (was `model_access` +
  `rule_groups`)

---

## 4. The `access` domain operator

New in v20. On a many2one (or `id`), `('field', 'access', 'read')` means *"the user must
have that operation on the related record"*. It replaces hand-copied cross-model domains
on line/detail models.

```csv
sale_order_line_rule_portal,Portal Sales Orders Line,sale.order.line,base.group_portal,r,"[('order_id', 'access', 'read')]"
base_user_account_move_line_rule,Normal User Account Move Line,account.move.line,sales_team.group_sale_salesman,r,"[('move_id', 'access', 'read')]"
```

Use it for every child model whose visibility should follow its parent. It keeps the two
in sync forever, and it is what the access-error message uses to name the groups that
would grant access.

Constraints — [odoo/orm/domains.py:1921](../../../../odoo/orm/domains.py#L1921):
- only `many2one` fields and `id`
- value must be `'read'`, `'write'`, `'create'` or `'unlink'`
- not supported on properties

---

## 5. Field-level security

```python
internal_cost = fields.Monetary(
    string="Internal Cost",
    currency_field='currency_id',
    groups='my_module.group_my_module_manager',
)
```

```xml
<field name="internal_cost" groups="my_module.group_my_module_manager"/>
```

A `groups=` field is stripped from reads, writes, exports and the web client for users
outside the group — enforced by `check_field_access()` /
`has_field_access()`, [models.py:2703](../../../../odoo/orm/models.py#L2703). Put it on the
field first; the view attribute alone only hides it in the UI.

---

## 6. Programmatic access checks

```python
records.check_access('read')            # raises AccessError
if records.has_access('write'): ...     # bool
allowed = records._filtered_access('unlink')   # the subset the user may touch
self.env['my.model'].browse().check_access('create')   # model-level check

model.check_field_access(model._fields['cost'], 'write')   # raises
model.has_field_access(model._fields['cost'], 'read')      # bool
```

- operations: `'read'`, `'write'`, `'create'`, `'unlink'`
- all of them short-circuit to "allowed" under `sudo()` / `env.su` — call them on the
  **non-sudoed** recordset
- `create()` / `write()` / `unlink()` already call `check_access` internally; only re-check
  when you bypass the ORM or wrap something in `sudo()`
- `Model._access_domain(op)` returns the resolved domain — useful for debugging why a
  record is invisible, and it is `@api.ormcache`'d on `self.env._access_context`

---

## 7. `sudo()` discipline

Order of operations, every time:

```python
def action_generate_invoice(self):
    self.ensure_one()
    # 1. permission: is this user allowed to trigger the action at all?
    if not self.env.user.has_group('sale.group_sale_salesman'):
        raise AccessError(self.env._("Only salespersons can generate invoices."))
    # 2. business state, before any sudo
    if self.state != 'sale':
        raise UserError(self.env._("Only confirmed orders can be invoiced."))
    # 3. prepare values with the user's own rights
    invoice_vals = self._prepare_invoice()
    # 4. sudo only for the step that needs it, with the reason on one line
    # sudo: sale users have no create access on account.move
    return self.env['account.move'].sudo().create(invoice_vals)
```

Never:

```python
records = self.sudo().search([])                      # silencing an access error
self.sudo().write({'field': value_from_request})      # unvalidated user input
self.sudo().search([('company_id', '!=', self.env.company.id)])   # cross-company leak
```

`sudo()` bypasses `ir.access` completely — both permissions and restrictions, which means
it also bypasses every multi-company restriction. Any `sudo()` on a company-scoped model
must re-add the company filter by hand.

---

## 8. Portal and public routes

```python
class MyPortal(CustomerPortal):

    @http.route('/my/records/<int:record_id>', type='http', auth='user', website=True)
    def portal_record(self, record_id, **kw):
        record = request.env['my.model'].sudo().browse(record_id)
        if not record.exists() or record.partner_id != request.env.user.partner_id:
            raise request.not_found()      # 404, not 403 — do not confirm the id exists
        return request.render('my_module.portal_record', {'record': record})
```

- filter by `partner_id` (or `commercial_partner_id`) yourself — never trust the URL id
- 404 on mismatch, so ids cannot be enumerated
- `sudo()` here is justified *because* of the explicit ownership filter above it — say so
- never expose cost, margin, internal notes or other staff-only fields in portal templates
- portal access rows use `base.group_portal` with a domain, e.g.
  `[('partner_id','child_of',[user.commercial_partner_id.id])]`

---

## 9. Raw SQL safety

Raw SQL bypasses `ir.access` entirely — there is no ACL, no record rule, no company
restriction. Use the ORM for business CRUD; use SQL only for reporting shapes the ORM
cannot express, and re-apply the security filter yourself.

```python
self.env.cr.execute("""
    SELECT p.id, COUNT(o.id) AS order_count, SUM(o.amount_total) AS total
      FROM res_partner p
      LEFT JOIN sale_order o ON o.partner_id = p.id
     WHERE o.company_id IN %s
       AND o.state IN %s
       AND o.date_order >= %s
     GROUP BY p.id
""", (tuple(self.env.companies.ids), ('sale',), date_from))
rows = self.env.cr.dictfetchall()
```

Never build SQL with `f""`, `%`-formatting or `+`. Prefer `odoo.tools.SQL` for composed
queries — it is injection-safe by construction.

---

## 10. CSRF and webhooks

- `type='http'` POST routes are CSRF-checked automatically; QWeb forms include the token
- `type='jsonrpc'` uses session auth and is not CSRF-relevant
- `csrf=False` is only for endpoints that must accept external callers, and it must be
  paired with a real authentication step:

```python
@http.route('/my/webhook', type='http', auth='none', csrf=False, methods=['POST'])
def webhook(self, **post):
    if not hmac.compare_digest(post.get('signature', ''), expected_signature):
        raise Forbidden()
```

Use `hmac.compare_digest` for every secret comparison — `==` leaks timing.

---

## 11. Secrets and sensitive data

```python
# never in a data file
<field name="value">sk_live_abc123</field>

# ship it empty, let the admin fill it
<field name="value"></field>

api_key = self.env['ir.config_parameter'].sudo().get_str('my_module.api_key')
if not api_key:
    raise UserError(self.env._("API key not configured (Settings > Technical > Parameters)."))
```

- never log a password, token or key — `_logger.info("calling %s", url)` is fine
- token fields carry `groups='base.group_system'` and `copy=False`
- `ir.config_parameter` reads need `sudo()`; that is expected and does not need a comment

---

## 12. Vulnerability table

| Vulnerability | Shape | Fix |
|---|---|---|
| SQL injection | `execute(f"... {value}")` | `%s` parameters or `tools.SQL` |
| Missing access row | new model, no `ir.access.csv` entry | nobody can use it — add the row |
| Over-broad permission | empty `group_id` used to "grant to all" | empty group means **restriction**, not grant |
| IDOR | `browse(id_from_url)` with no ownership check | ownership filter + `check_access('read')` + 404 |
| Broken access via sudo | `sudo()` before validating the user | permission check → state check → `sudo()` |
| Cross-company leak | no restriction row, or `sudo()` on a scoped model | company restriction + re-filter under `sudo()` |
| XSS in QWeb | `t-out` on raw HTML from users | escape, or sanitize the stored HTML |
| Stored XSS via SVG | SVG upload | `Binary`/`Image` block SVG for non-admins — keep it |
| Mass assignment | `write(request.params)` | whitelist the fields |
| Path traversal | user-controlled file path | validate against a fixed root |
| Open redirect | redirect to a user-supplied URL | allow only internal targets |
| Timing attack | `token == expected` | `hmac.compare_digest` |
