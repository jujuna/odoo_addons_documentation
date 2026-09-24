# ORM Excellence — Odoo 20

Use this reference for any non-trivial Odoo Python code. The default standard is:
**batch-safe, access-safe, company-safe, cache-correct, and easy to review.**

---

## 1. Decision Order

When writing Odoo ORM code, optimize in this order:

1. **Correctness:** preserve Odoo lifecycle, invariants, constraints, recompute, mail tracking.
2. **Security:** respect ACLs, record rules, company boundaries, portal/public ownership.
3. **Batch performance:** no N+1, no singleton assumptions, no per-record writes when one batch works.
4. **Maintainability:** small helpers, clear domains, explicit side effects.
5. **Micro-performance:** only after query count and data volume are understood.

If these conflict, do not pick speed over correctness or security. Use raw SQL only when the ORM cannot express the operation or the measured volume requires it.

---

## 2. Recordset Contract

Every model method must be honest about recordset size.

```python
def action_confirm(self):
    """Confirm selected records."""
    for order in self:
        order._check_can_confirm()
    self.write({'state': 'confirmed'})

def _prepare_invoice_values(self):
    """Prepare values for one invoice."""
    self.ensure_one()
    return {
        'partner_id': self.partner_id.id,
        'move_type': 'out_invoice',
    }
```

**Rules:**
- Public buttons may receive one or many records; loop or batch deliberately.
- Use `ensure_one()` only when the method truly requires one record.
- Empty recordsets are valid; avoid `self[0]` unless guarded.
- Do not mutate `self` while iterating. Build `to_process = self.filtered_domain(...)` first.
- Prefer recordsets over ID lists until you need serialization, SQL, or external API payloads.
- Use `exists()` before acting on stale IDs from external input or async jobs.

---

## 3. CRUD Overrides

### `create()`

```python
@api.model_create_multi
def create(self, vals_list):
    """Create records with batch-safe defaults."""
    Sequence = self.env['ir.sequence']
    for vals in vals_list:
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = Sequence.next_by_code('my.model') or _('New')
    records = super().create(vals_list)
    records._post_create_sync_if_needed()
    return records
```

**Rules:**
- Always use `@api.model_create_multi`.
- Accept and return a recordset matching `vals_list`.
- Precompute defaults before `super()`; side effects that need IDs happen after `super()`.
- Do not call `create()` in a loop when one multi-create works.
- Do not use `sudo()` for sequence/access shortcuts unless the target model really requires it; justify it.

### `write()`

```python
def write(self, vals):
    """Apply updates and run side effects once per batch."""
    if 'state' in vals and vals['state'] == 'done':
        invalid = self.filtered(lambda rec: not rec.line_ids)
        if invalid:
            raise UserError(_("Add lines before completing: %s", ', '.join(invalid.mapped('display_name'))))

    tracked_before = {rec.id: rec.state for rec in self} if 'state' in vals else {}
    result = super().write(vals)

    if 'state' in vals:
        changed = self.filtered(lambda rec: tracked_before.get(rec.id) != rec.state)
        changed._post_state_change_message()
    return result
```

**Rules:**
- `self` can be multi-record; validate in batch before `super()`.
- Call `super().write(vals)` once unless there is a strong reason not to.
- Capture old values before `super()` only for fields you actually need.
- Side effects after `super()` see final values and generated recomputes.
- Never write inside a compute method to fields that are part of the same recompute chain.

### `unlink()`

```python
@api.ondelete(at_uninstall=False)
def _unlink_except_done(self):
    """Prevent deletion of completed records."""
    blocked = self.filtered_domain([('state', '=', 'done')])
    if blocked:
        raise UserError(_("Completed records cannot be deleted."))
```

**Rules:**
- Prefer `@api.ondelete` for business delete restrictions.
- Use `unlink()` overrides only for real cleanup side effects.
- Batch cleanup and call `super().unlink()` once.

---

## 4. Domains

Use the `Domain` API for dynamic composition. It is safer and more readable than hand-building prefix-list operators.

```python
from odoo.fields import Domain

domain = (
    Domain('company_id', 'in', self.env.companies.ids)
    & Domain('state', '=', 'posted')
    & (Domain('partner_id', '=', partner.id) | Domain('commercial_partner_id', '=', partner.commercial_partner_id.id))
)
moves = self.env['account.move'].search_fetch(domain, ['partner_id', 'amount_total'], order='date desc, id desc')
```

### Relational sub-conditions: `any` / `not any`

Filter a record by a condition on its related records. This replaces nested subqueries and the removed `auto_join`:

```python
# orders having at least one late line
Domain('order_line', 'any', [('state', '=', 'late')])
# partners with no unpaid invoice
Domain('invoice_ids', 'not any', [('payment_state', '=', 'not_paid')])
```

- `any` on a many2one / `id` matches when the target satisfies the sub-domain (searched with `active_test=False`); on an x2many it searches the comodel with the field's context, applying the comodel's record rules.
- `any!` / `not any!` behave like `any` but **bypass the comodel's record rules** — security-sensitive, internal use only.
- Canonical operators are `in` / `not in` (the optimizer rewrites `=` / `!=` into them) plus `like`/`ilike`/`=like`/`=ilike` and their negations. In `in` values, `False` means "not set".
- `('f', 'not in', vals)` also matches records where `f` is empty (`NOT IN ... OR f IS NULL`, [odoo/orm/fields.py:1474](../../../../odoo/orm/fields.py#L1474)). Add `('f', '!=', False)` when empty must not match.

**Rules:**
- Start from `Domain.TRUE` / `Domain.FALSE` when conditionally composing.
- Use `Domain.AND([...])` and `Domain.OR([...])` for variable-length domain lists; negate with `~domain`.
- Keep company and active filters explicit when logic depends on them.
- Use `_check_company_domain(company)` when selecting company-dependent comodel records.
- Avoid Python filtering on large sets when the domain can express the condition.
- For a raw-SQL condition that must still survive `filtered_domain()`, use `Domain.custom(to_sql=..., predicate=...)` and supply both callables.
- Rewrite leaves (e.g. remap a field name) with `domain.map_conditions(fn)` instead of re-parsing the list.
- Never pass raw user text through `eval()`; parse controlled literals with `ast.literal_eval()` or JSON.

---

## 5. Relational Commands

Use `Command` helpers, not magic tuples.

```python
from odoo import Command

order.write({
    'order_line': [
        Command.create({'product_id': product.id, 'product_uom_qty': 2}),
        Command.update(existing_line.id, {'discount': 10}),
    ],
    'tag_ids': [Command.set(tags.ids)],
})
```

**Rules:**
- `Command.create(vals)` for new children.
- `Command.update(id, vals)` for existing linked records.
- `Command.unlink(id)` removes the relation; `Command.delete(id)` deletes the child.
- `Command.set(ids)` replaces all links; use carefully in concurrent flows.
- Avoid mixing user-provided IDs with `sudo()` without checking ownership/access first.

---

## 6. Batch Patterns

### Group existing records without losing prefetch

```python
for company, records in self.grouped('company_id').items():
    records.with_company(company)._process_company_batch()
```

`grouped()` returns recordsets sharing the same prefetch set. Use it when values differ by group but each group can still be processed in batch.

### Aggregate with `_read_group()`

```python
totals = self.env['sale.order.line']._read_group(
    [('order_id', 'in', self.ids)],
    groupby=['order_id'],
    aggregates=['price_total:sum'],
)
amount_by_order = {order.id: total for order, total in totals}
for order in self:
    order.amount_custom = amount_by_order.get(order.id, 0.0)
```

**Rules:**
- Use `_read_group()` for counts/sums per parent; do not loop and `search_count()`.
- Aggregate spec is `'field:agg'`. Beyond PostgreSQL aggregates (`sum`, `avg`, `max`, `min`, `bool_or`, ...), Odoo adds `__count` (group size), `count_distinct`, and `recordset` (like `array_agg`, returned as a prefetched recordset). A related groupby value also comes back as a recordset.
- Group by `'field:granularity'` for dates: `day`, `week`, `month`, `quarter`, `year`, plus integer parts like `month_number`, `iso_week_number`, `day_of_week`.
- In compute methods, assign every record every time.
- For known field reads after a search, prefer `search_fetch(domain, fields)`.
- For existing recordsets, use `records.fetch(fields)` before heavy loops.
- Need webclient-formatted groups (labels, ranges) rather than raw tuples? Use `formatted_read_group(...)` (same args, returns a list of dicts) — it lives in the web layer, not on `BaseModel`.
- Several groupings in one round-trip: `_read_grouping_sets(domain, grouping_sets, aggregates, order)`.

### Which of the three in v20

| Method | Layer | Relational values | Use for |
|---|---|---|---|
| `read_group(...)` | public, `@api.model`, `@typing.final` | ids | RPC / external callers |
| `_read_group(...)` | backend | recordsets | all server Python |
| `formatted_read_group(...)` | `addons/web` | formatted dicts | the web client |

`read_group()` is **not** deprecated in v20 — it was restored as the public wrapper with the
modern signature `(domain, groupby, aggregates, having, offset, limit, order)`. The old v16
form (`fields=`, `lazy=True`, returning dicts) no longer exists.

When overriding the group-by hooks, note the v20 signatures take a `TableSQL` first:
`_read_group_select(table, spec)`, `_read_group_groupby(table, spec)`,
`_read_group_having(table, domain)`, `_read_group_orderby(table, order, terms)`.

---

## 7. Compute, Inverse, Onchange

```python
@api.depends('line_ids.price_total')
def _compute_amount_custom(self):
    totals = self.env['my.line']._read_group(
        [('order_id', 'in', self.ids)],
        ['order_id'],
        ['price_total:sum'],
    )
    total_by_order = {order.id: total for order, total in totals}
    for record in self:
        record.amount_custom = total_by_order.get(record.id, 0.0)
```

**Rules:**
- Compute methods must assign the computed field for every record in `self`.
- Use precise `@api.depends(...)`; broad dependencies cause recompute storms.
- Use `@api.depends_context(...)` when output depends on context (`company`, `uid`, `lang`, pricing context).
- Stored computed fields are for search/group/list performance or expensive stable values.
- Non-stored computed fields are for cheap, context-sensitive, form-only values.
- Do not put business invariants in `@api.onchange`; onchanges are UI hints only.
- Constraints enforce invariants; computes derive values; onchanges improve UX.

---

## 8. Transactions and Cache

**Default:** let Odoo own the transaction.

```python
for record in self:
    try:
        with self.env.cr.savepoint():
            record._call_external_service()
            record.write({'state': 'done'})
    except UserError:
        raise
    except Exception:
        _logger.exception("Failed to process %s(%s)", record._name, record.id)
        record.write({'state': 'error'})
```

**Rules:**
- Use `savepoint()` to isolate recoverable per-record/per-batch failures.
- Do not call `cr.commit()` in normal request, button, compute, constraint, or onchange code.
- Cron/import/migration jobs may commit per chunk when the job is explicitly resumable.
- After manual `cr.commit()`, call `env.invalidate_all()`.
- Before raw SQL reads that depend on pending ORM writes, flush targeted records/fields.
- After raw SQL writes, invalidate targeted records/fields before ORM reads.
- After raw SQL changes fields with stored-compute dependents, call `records.modified(fnames)`.
- Do not catch `Exception` and continue silently. Log or convert to a user-facing error.

Load `references/transactions.md` before writing any manual commit, rollback, or raw-SQL cache logic.

---

## 9. Security and `sudo()`

`sudo()` is a security boundary bypass, not a convenience method.

```python
def action_portal_download(self, token):
    """Return a document only after ownership/token validation."""
    self.ensure_one()
    if not self._is_valid_portal_token(token):
        raise AccessError(_("You cannot access this document."))
    # sudo justified: attachment binary is protected, ownership was validated above.
    return self.attachment_id.sudo()._get_download_action()
```

**Rules:**
- Validate domain, ownership, company, and intended operation before `sudo()`.
- Keep sudoed recordsets as narrow as possible.
- Do not mix sudoed and non-sudoed recordsets in domains without thinking through leakage.
- Public/portal controllers must return 404/AccessError for unauthorized records.
- Never rely on view invisibility for security.

---

## 10. Multi-Company

```python
company = self.company_id or self.env.company
journals = self.env['account.journal'].search(
    self.env['account.journal']._check_company_domain(company)
    & Domain('type', '=', 'sale'),
    limit=1,
)
```

**Rules:**
- `company_id` is indexed and defaults to `self.env.company`.
- Every company-scoped Many2one uses `check_company=True`, and the model sets
  `_check_company_auto = True`.
- Cross-company processing groups by company: `for company, recs in self.grouped('company_id').items(): recs.with_company(company)...`
- Do not write records of several companies in one batch when defaults, sequences,
  journals, taxes or accounts depend on the company.
- `self.env.company` for the active company, `self.env.companies` for the visible set.
  Never `self.env.user.company_id` in business logic.
- Be explicit with `active_test=False` when archived records matter.

Company scoping in the database is enforced by a **restriction row** in
`security/ir.access.csv` (empty `group_id`), not by `ir.rule` — that model no longer exists.
Full rules, branch companies and the `parent_of` helpers: `multicompany.md`.

---

## 11. Concurrency

Prevent races with database constraints first, then locks when needed.

```python
_external_ref_unique = models.Constraint(
    'unique(company_id, external_ref)',
    'External reference must be unique per company.',
)
```

For read-then-write atomicity, take an explicit row lock instead of hand-writing `SELECT ... FOR UPDATE`:

```python
batch = self.search([('state', '=', 'pending')], limit=100, order='id')
locked = batch.try_lock_for_update(limit=100)  # SKIP LOCKED; returns lockable subset
locked.write({'state': 'processing'})
```

**Rules:**
- Use `models.Constraint(...)` for uniqueness and hard invariants.
- Use Python `@api.constrains` when the invariant needs ORM logic.
- For scarce resources (sequence gaps, one worker per row, inventory reservations), use `lock_for_update()` (must lock all, raises `LockError`) or `try_lock_for_update(limit=...)` (locks what it can, returns the subset). See `transactions.md` section 10.
- Detect hierarchy loops with `_has_cycle(field_name=None)` (returns `True` when a loop exists). `_check_recursion()` and `_check_m2m_recursion()` were **removed in v20**, and the boolean is inverted.
- Avoid check-then-create races; prefer SQL constraints or atomic upsert when the ORM cannot express it.

---

## 12. High-Standard Method Shape

```python
def action_process(self):
    """Process eligible records in a batch-safe way."""
    eligible = self.filtered_domain([('state', '=', 'ready')])
    if not eligible:
        return True

    eligible._check_process_allowed()
    vals_by_company = eligible._prepare_process_values_by_company()

    for company, records in eligible.grouped('company_id').items():
        records.with_company(company)._apply_process_values(vals_by_company[company.id])

    for record in eligible:
        record.message_post(body=_("Processing completed."))
    return True
```

Good methods tend to follow this order:

1. Normalize/select recordset.
2. Validate access, state, company, and required data.
3. Prepare data in batch.
4. Apply changes in the smallest number of ORM calls.
5. Run side effects after persistence.
6. Return an Odoo-native result (`True`, action dict, recordset, values dict).

---

## 13. Side-Effect Boundaries

Keep validation, value preparation, persistence, and irreversible side effects separate.

```python
def action_send_to_provider(self):
    """Validate and enqueue provider sync for selected records."""
    records = self.filtered_domain([('state', '=', 'ready')])
    records._check_can_send_to_provider()
    payload_by_id = records._prepare_provider_payloads()
    records._create_provider_jobs(payload_by_id)
    records.write({'state': 'queued'})
    return True
```

**Rules:**
- `_check_*` methods validate and raise, but do not write.
- `_prepare_*` methods return plain values/maps, but do not write or call external services.
- `_apply_*` or `_action_*` methods persist changes.
- External API calls live in explicit sync/job methods, not hidden inside computes/onchanges.
- Irreversible side effects need idempotency keys and transaction design.

---

## 14. Context Flags

Context flags are powerful and dangerous because they create hidden behavior.

```python
records.with_context(my_module_skip_provider_sync=True).write(vals)
```

**Rules:**
- Prefix custom context keys with the module/feature name.
- Use context flags for technical recursion guards or framework integration, not business state.
- Check context flags at the narrowest possible location.
- Do not let user-controlled context bypass access checks, validations, or accounting/stock invariants.
- Prefer an explicit method argument when only internal Python callers use the behavior.

---

## 15. Data Shape for Batch Helpers

Batch helpers should return structures that let callers write once per group.

```python
from collections import defaultdict


def _prepare_values_by_partner(self):
    """Return values grouped by partner for batch creation."""
    values_by_partner = defaultdict(list)
    for line in self:
        values_by_partner[line.partner_id].append(line._prepare_single_value())
    return values_by_partner

def _create_grouped_records(self):
    values_by_partner = self._prepare_values_by_partner()
    for partner, vals_list in values_by_partner.items():
        self.env['target.model'].with_company(partner.company_id).create(vals_list)
```

**Rules:**
- Return maps keyed by record/id/company/state when downstream writes differ by group.
- Return recordsets, not ID lists, when caller needs ORM behavior.
- Do not return partially-created records and expect caller cleanup on error.
- Keep helper names precise: `_get_*_domain`, `_prepare_*_values`, `_group_*`, `_apply_*`.

---

## 16. ORM Review Checklist

Before shipping ORM code, ask:

- Does it work for empty, singleton, and multi-recordsets?
- Are all domains company-aware where the model is company-scoped?
- Are all writes batched or grouped by value/company?
- Are compute methods assigning every record and avoiding side effects?
- Are x2many updates using `Command`?
- Are access checks preserved before any `sudo()`?
- Are external calls outside compute/onchange/constraints?
- Are manual commits absent or justified by `transactions.md`?
- Are raw SQL changes cache/recompute-correct?

---

## 17. Review Smells

Treat these as blockers unless there is a measured reason:

- `search()` / `search_count()` / `browse(id)` inside a loop.
- `ensure_one()` at the top of a method called from batch flows.
- `create()` override without `@api.model_create_multi`.
- `write()` override calling `super()` inside a loop.
- Compute method that does not assign all records.
- Onchange containing real business rules.
- `sudo()` before validating user-controlled IDs.
- Raw SQL without flush/invalidate and a security comment.
- Direct float equality on quantities, currency, or UoM values.
- `cr.commit()` outside cron/import/migration code.
- Domains assembled with fragile nested `|`/`&` lists when `Domain` would be clearer.
