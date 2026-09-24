# Fields — Odoo 20

Reference for declaring fields, computes, relations, constraints, and onchanges. Sourced from `odoo/orm/fields.py`, `fields_relational.py`, `fields_binary.py`, and `decorators.py`.

---

## 1. Field Types Overview

| Type | Python class | DB column | Key kwargs |
|---|---|---|---|
| `Char` | `fields.Char` | `varchar` | `size`, `trim`, `translate` |
| `Text` | `fields.Text` | `text` | `translate` |
| `Html` | `fields.Html` | `text` | `translate`, `sanitize` |
| `Integer` | `fields.Integer` | `int4` | `aggregator` |
| `Float` | `fields.Float` | `float8` | `digits=(precision, scale)`, `aggregator` |
| `Monetary` | `fields.Monetary` | `numeric` | `currency_field` |
| `Boolean` | `fields.Boolean` | `bool` | |
| `Date` | `fields.Date` | `date` | |
| `Datetime` | `fields.Datetime` | `timestamp` | UTC in DB |
| `Binary` | `fields.Binary` | `bytea` / attachment | `attachment` (default `True`) |
| `Image` | `fields.Image` | attachment | `max_width`, `max_height`, `verify_resolution` |
| `Selection` | `fields.Selection` | `varchar` | `selection`, `group_expand` |
| `Reference` | `fields.Reference` | `varchar` | `selection` |
| `Many2one` | `fields.Many2one` | `int4` (FK) | `ondelete`, `check_company`, `delegate`, `domain` |
| `One2many` | `fields.One2many` | _(virtual)_ | `comodel_name`, `inverse_name` |
| `Many2many` | `fields.Many2many` | _(junction)_ | `relation`, `column1`, `column2`, `ondelete` |
| `Json` | `fields.Json` | `jsonb` | |
| `Properties` | `fields.Properties` | `jsonb` | `definition` |

---

## 2. Common Attributes

Available on every field:

- `string` — UI label; defaults to the capitalized field name.
- `help` — tooltip.
- `required=True` — `NOT NULL` in DB (for stored fields).
- `readonly=True` — UI-only; code assignment still works on stored/inversable fields.
- `default` — static value or `default=lambda self: ...`. Use `default=None` to drop an inherited default.
- `copy` — copied by `copy()`? Default `True`, but `False` for `One2many`, computed, related, and property fields.
- `groups` — CSV of group XML ids; restricts field read/write to those groups (field-level security; also strip it from views).
- `index` — see below.
- `prefetch` — prefetch group; `False` disables prefetching (default for `Binary`); a string names a shared prefetch group.
- `tracking=True` — log changes in the chatter (requires `mail.thread`).

---

## 3. Indexing

`index` accepts a kind, not just a bool (`fields.py`):

| Value | Index | Use |
|---|---|---|
| `True` / `"btree"` | standard BTREE | Many2one, state/date filters |
| `"btree_not_null"` | BTREE excluding NULLs | column is mostly NULL, or NULL is never searched |
| `"trigram"` | GIN trigram | `ilike` / full-text search on text columns |
| `False` / `None` | none (default) | |

No effect on non-stored or virtual fields. For composite indexes use `models.Index("(col_a, col_b)")` as a named class attribute.

```python
name = fields.Char(index='trigram')          # speeds up ilike searches
partner_id = fields.Many2one('res.partner', index=True)
_partner_state_idx = models.Index("(partner_id, state)")
```

---

## 4. Computed Fields

```python
amount_total = fields.Monetary(compute='_compute_amount_total', store=True, currency_field='currency_id')

@api.depends('line_ids.price_total')
def _compute_amount_total(self):
    for record in self:          # assign every record, always
        record.amount_total = sum(record.line_ids.mapped('price_total'))
```

Key compute attributes (`fields.py`):

- `compute='_method'` — implies `store=False` and `copy=False` unless overridden.
- `store=True` — persist; needed for search/group/list on the field.
- `compute_sudo` — recompute as superuser (default `True` for stored, `False` for non-stored).
  So a non-stored compute that searches or reads another model runs with the user's rights:
  a user without read access on that model gets an AccessError when the form loads.
- `precompute=True` — compute *before* the INSERT instead of at flush. A provided default value or explicit value disables it. Good for `One2many` lines created in batch; counterproductive when records are created one-by-one (loses prefetch batching).
- `recursive=True` — **required** when the field depends on itself through a relation (`parent_id.x`). Must be explicit or recomputation is wrong.
- `inverse='_method'` — makes a non-stored/computed field writable; the inverse persists the assignment.
- `search='_method'` — makes a non-stored field searchable. Receives `(operator, value)`, returns a domain, or `return NotImplemented` for unsupported operators. Domain optimizations run first (e.g. `=` becomes `in`).
- `compute_sql='_method'` — **v20**. Expresses the field in SQL so it can be searched, grouped *and* ordered without storing it. Requires an explicit `compute_sudo=`. See section 4b.
- `init_storage='_method'` — **v20**. Populates the column when it is first created.

### Storage decision order

Take the first one that works:

1. plain `compute` — the value is only ever read per record
2. `compute` + `compute_sql` — it must be searchable / groupable / sortable
3. `compute` + `search='_method'` — it must be searchable but cannot be expressed in SQL
4. `compute` + `store=True` — the value is stable and read far more often than written

`store=True` is the expensive option: a column, an index, recompute traffic on every
dependency write, and a stale-data risk. Do not reach for it just to enable a filter.

---

## 4b. `compute_sql` (v20)

```python
currency_id = fields.Many2one(
    'res.currency', 'Currency',
    compute='_compute_currency_id',
    compute_sql='_compute_sql_currency_id',
    compute_sudo=True,              # mandatory when compute_sql is set
)

@api.depends('company_id')
def _compute_currency_id(self):
    for template in self:
        template.currency_id = template.company_id.sudo().currency_id or main_currency

def _compute_sql_currency_id(self, table):
    main_company = self.env['res.company']._get_main_company()
    return SQL("COALESCE(%s, %s)", table.company_id.currency_id, main_company.currency_id.id)
```

- the SQL method takes `(self, table)` where `table` is a `TableSQL`, and returns an `SQL`
- `table` supports **dotted traversal that auto-joins**: `table.company_id.currency_id`
- keep the Python compute and the SQL expression in sync — they must give the same value
- the framework warns if `compute_sql` is set without `compute`, or without an explicit
  `compute_sudo` ([odoo/orm/fields.py:471](../../../../odoo/orm/fields.py#L471))

82 core fields use it. Real examples:
[product_template.py:99](../../../../addons/product/models/product_template.py#L99),
[mail_activity_mixin.py:172](../../../../addons/mail/models/mail_activity_mixin.py#L172).

**Rules:**
- Compute methods assign the field for *every* record in `self`.
- Use precise `@api.depends(...)`; broad dependencies cause recompute storms.
- `@api.depends` cannot depend on `'id'` (raises `NotImplementedError`).
- `@api.depends` also accepts a single callable returning the dependency list (for dynamic deps).
- Store only when the field is searched/grouped/listed or expensive and stable.

### Context-dependent computes

```python
@api.depends_context('company')
def _compute_price(self):
    ...
```

Special context keys with built-in support: `company`, `uid` (user id + superuser flag), `active_test`. All declared dependencies must be hashable.

---

## 5. Related Fields

```python
partner_email = fields.Char(related='partner_id.email', store=True, readonly=False)
```

- A related field is a compute under the hood (`copy=False`, `readonly=True` by default).
- Set `store=True` when you search/group/sort on it.
- Set `readonly=False` to make it writable (writes propagate to the source field via the implicit inverse).

---

## 6. Relational Fields

### Many2one (`fields_relational.py`)

```python
partner_id = fields.Many2one('res.partner', ondelete='restrict', check_company=True, index=True)
```

- `ondelete` — `'set null'` (framework default), `'restrict'`, or `'cascade'`. **Always set it explicitly.**
- `check_company=True` — the ORM verifies company compatibility in `_check_company`. For non-company-dependent fields it constrains the target's `company_id` to the record's; for company-dependent fields, to the active company.
- `delegate=True` — exposes the comodel's fields on this model; corresponds to `_inherits = {'comodel': 'field_name'}`. Implies `bypass_search_access=True` and must be declared together with `_inherits`.
- `bypass_search_access=True` — skip comodel access-rule checks during search. Security-sensitive; justify with a comment.
- `domain`, `context` — client-side candidate filtering / context.

> `auto_join` was **removed**. Relational filtering now uses the `any` / `not any` domain operators and the search-access model (see `orm.md` section 4).

### One2many

```python
line_ids = fields.One2many('sale.order.line', 'order_id', copy=True)
```

- `comodel_name` + `inverse_name` (the `Many2one` on the comodel) are mandatory except for related/extended fields.
- `copy=False` by default — set `copy=True` to duplicate children with the parent.

### Many2many

```python
tag_ids = fields.Many2many('my.tag', relation='my_model_tag_rel', column1='model_id', column2='tag_id')
```

- `relation`, `column1`, `column2` are auto-generated from the model names when omitted (requires `model_name != comodel_name`).
- Two `Many2many` fields cannot share the same implicit relation table — give explicit `relation`/`column1`/`column2` when you need several m2m to the same comodel.
- `ondelete='cascade'` by default on the `column2` foreign key.

### x2many writes — use Command

```python
from odoo import Command
order.write({'line_ids': [Command.create(vals), Command.set(ids), Command.unlink(line.id)]})
```

See `orm.md` section 5 for the full `Command` set.

---

## 7. Selection, Aggregation, Group Expansion

```python
state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], default='draft', group_expand='_expand_states')
amount = fields.Float(aggregator='sum')
```

- `aggregator` — default webclient Group By aggregate: `count`, `count_distinct`, `bool_and`, `bool_or`, `max`, `min`, `avg`, `sum`. (Renamed from `group_operator`, which is deprecated since 18.0.)
- `group_expand` — method (or `True` on a `Selection`) that fills in empty groups in kanban/list/gantt so all states show even with no records.

---

## 8. Company-Dependent Fields

```python
property_account_id = fields.Many2one('account.account', company_dependent=True)
```

- `company_dependent=True` stores the value as a `jsonb` dict keyed by company id (not a plain column).
- Fallbacks come from `ir.default`. Reading/writing resolves against the active company.
- Pair with `check_company=True` on relational targets.

---

## 9. Binary and Image (`fields_binary.py`)

```python
document = fields.Binary('Document', attachment=True)
logo = fields.Image('Logo', max_width=1920, max_height=1920)
```

**Binary:**
- `attachment=True` (default) stores the value as an `ir.attachment`, not a table column. `attachment=False` stores it in a `bytea` column. A non-stored binary forces `attachment=False`.
- `prefetch=False` by default — blobs are never batch-loaded.
- With `bin_size=True` in context (or `bin_size_<field>`), reads return the human-readable size instead of the content — use it in list views to avoid loading blobs.
- **Security:** SVG uploads are rejected for non-system users ("Only admins can upload SVG files") — an XSS guard. Keep it.

**Image (extends Binary):**
- `max_width` / `max_height` (default `0` = no limit) — auto-resizes keeping aspect ratio.
- `verify_resolution=True` (default) — rejects images above the max resolution (~50 Mpx), a decompression-bomb guard.
- The model should have `_log_access=True` (the field warns otherwise).
- If you set no max size and `verify_resolution=False`, use a plain `Binary` instead.

---

## 10. Constraints (`decorators.py`)

### Python constraint

```python
@api.constrains('date_start', 'date_end')
def _check_dates(self):
    for record in self:
        if record.date_end < record.date_start:
            raise ValidationError(_("End date must be after start date."))
```

**Caveats (often cause silent bugs):**
- Only **simple field names** are supported. Dotted names (`partner_id.country_id`) are **ignored**.
- The constraint fires only when a declared field is present in the `create`/`write` call. Fields absent from the view will not trigger it on create — override `create()` to enforce always-required invariants.
- Raise `ValidationError` on failure.

### Database constraint

```python
_amount_positive = models.Constraint('CHECK(amount >= 0)', "Amount must be positive.")
_ref_unique = models.Constraint('unique(company_id, ref)', "Reference must be unique per company.")
```

Prefer DB constraints for uniqueness and simple invariants — they are race-proof. Use `@api.constrains` when the check needs ORM logic.

### Delete restriction

```python
@api.ondelete(at_uninstall=False)
def _unlink_except_posted(self):
    if any(rec.state == 'posted' for rec in self):
        raise UserError(_("Posted entries cannot be deleted."))
```

- Name the method `_unlink_if_<condition>` or `_unlink_except_<not_condition>`.
- `at_uninstall=False` almost always — so uninstalling the module does not raise. Set `True` only when the check must hold even during uninstall.
- Prefer `@api.ondelete` over a full `unlink()` override for business delete rules.

---

## 11. Onchange (`decorators.py`)

```python
@api.onchange('partner_id')
def _onchange_partner_id(self):
    self.payment_term_id = self.partner_id.property_payment_term_id
    if not self.partner_id:
        return {'warning': {'title': _("No partner"), 'message': _("Select a partner first.")}}
```

**Caveats:**
- Onchanges are **UI hints only** — they run on a pseudo-record of unsaved form values. Put real invariants in `@api.constrains` and derived values in `@api.depends` computes.
- Only simple field names; dotted names are ignored.
- Do **not** call `create`/`read`/`write`/`unlink` on the pseudo-record — assign fields or use `update()`.
- A `One2many`/`Many2many` field cannot modify itself via onchange (webclient limitation).
- Return `{'warning': {...}}` to surface a dialog/notification.
- A value assigned to a field that is **not in the form view** is not sent back and not
  saved, and its own onchanges do not cascade: `onchange()` diffs and cascades over
  `fields_spec` only ([web/models/models.py:2381-2391](../../../../addons/web/models/models.py#L2381)).
  Put the field in the view (`invisible="1"`) or make it a compute.

---

## 12. v20 Field Changes

| Old | New | Notes |
|---|---|---|
| `store=True` to enable search/groupby | `compute_sql='_method'` | v20 — no column, no recompute traffic |
| — | `init_storage='_method'` | v20 — populate a new column at install |
| `uom.rounding` | `env['decimal.precision'].precision_get('Product Unit')` | the UoM `rounding` field is gone |
| `digits='Product Price'` for display only | `min_display_digits='Product Price'` | controls the minimum decimals shown |
| `group_operator='sum'` | `aggregator='sum'` | deprecated since 18.0; warns |
| `auto_join=True` | `bypass_search_access=True` | plus `any` / `not any` domain operators |
| `index=True` only | `index='btree_not_null'` / `'trigram'` | pick the index kind to fit the query |
| `fields.Date.today()` (default) | `fields.Date.today` | callable, no parens |

Rounding quantities in v20:

```python
digits = self.env['decimal.precision'].precision_get('Product Unit')
fields.Float.round(self.product_uom_qty, precision_digits=digits)
fields.Float.is_zero(self.product_uom_qty, precision_digits=digits)
fields.Float.compare(self.product_uom_qty, self.qty_done, precision_digits=digits)
```
