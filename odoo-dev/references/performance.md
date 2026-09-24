# Performance Patterns — Odoo 20

## Table of Contents

1. [The N+1 Problem](#1-the-n1-problem)
2. [Batch Operations](#2-batch-operations)
3. [Prefetching and Caching](#3-prefetching-and-caching)
4. [Search Optimization](#4-search-optimization)
5. [Computed Fields Strategy](#5-computed-fields-strategy)
6. [Write Optimization](#6-write-optimization)
7. [Database Indexes](#7-database-indexes)
8. [Recordset Operations](#8-recordset-operations)
9. [Memory Management](#9-memory-management)
10. [Profiling](#10-profiling)
11. [Relational Search Access](#11-relational-search-access)
12. [with_prefetch() Control](#12-with_prefetch-control)
13. [_order Performance](#13-_order-performance)
14. [Flush and Invalidate](#14-flush-and-invalidate)
15. [ORM vs Raw SQL Decision Matrix](#15-orm-vs-raw-sql-decision-matrix)
16. [Performance Review Workflow](#16-performance-review-workflow)
17. [Compute Field Batch Patterns](#17-compute-field-batch-patterns)
18. [Prefetch and Fetch Strategy](#18-prefetch-and-fetch-strategy)
19. [Domains and Query Shape](#19-domains-and-query-shape)
20. [Cron and Import Throughput](#20-cron-and-import-throughput)
21. [High-Risk Antipatterns](#21-high-risk-antipatterns)
22. [Performance Budgets](#22-performance-budgets)
23. [List View and Dashboard Performance](#23-list-view-and-dashboard-performance)
24. [Transaction Cost and Lock Time](#24-transaction-cost-and-lock-time)

---

## 1. The N+1 Problem

The most common Odoo performance issue. Happens when you query inside a loop.

### BAD — N+1 queries:
```python
def _compute_partner_email(self):
    for record in self:
        # This triggers a separate query for EACH record
        partner = self.env['res.partner'].search([('id', '=', record.partner_id.id)])
        record.partner_email = partner.email
```

### GOOD — Single query via prefetch:
```python
def _compute_partner_email(self):
    # Odoo auto-prefetches related fields on the same recordset
    for record in self:
        record.partner_email = record.partner_id.email
```

### GOOD — Explicit batch when needed:
```python
def action_send_emails(self):
    """Send emails to all selected partners."""
    # Pre-load all partners in one query
    partners = self.mapped('partner_id')
    # Now iterate — no additional queries
    for partner in partners:
        partner._send_notification_email()
```

---

## 2. Batch Operations

Batching is the first Odoo performance rule. A correct Odoo method should work
for 0, 1, or many records unless it explicitly enforces singleton behavior.

### create() — Always use multi-create:
```python
# BAD — N create calls
for vals in vals_list:
    self.env['my.model'].create(vals)

# GOOD — Single multi-create
self.env['my.model'].create(vals_list)
```

### create() override — preserve multi-create:
```python
@api.model_create_multi
def create(self, vals_list):
    """Create records without breaking batch creation."""
    for vals in vals_list:
        vals.setdefault('state', 'draft')
    records = super().create(vals_list)
    records._post_create_batch_hook()
    return records
```

### write() — Batch when possible:
```python
# BAD — N write calls
for record in records:
    record.write({'state': 'done'})

# GOOD — Single write call
records.write({'state': 'done'})

# GOOD — When values differ, group by value
for state, group_records in records.grouped('computed_state').items():
    group_records.write({'state': state})
```

### unlink() — Batch:
```python
# BAD
for record in records:
    record.unlink()

# GOOD
records.unlink()
```

---

## 3. Prefetching and Caching

### How Odoo prefetching works:
When you access a field on one record, Odoo loads that field for ALL records
in the same recordset (same prefetch group). Use this to your advantage.

```python
# The first access to record.name loads 'name' for ALL records in self
for record in self:
    print(record.name)  # Only 1 SQL query total, not N
```

### When prefetching breaks:
```python
# BAD — breaks prefetching by creating single-record recordsets
for record_id in self.ids:
    record = self.env['my.model'].browse(record_id)
    print(record.name)  # N queries!

# GOOD — iterate the recordset directly
for record in self:
    print(record.name)  # 1 query total
```

### Explicit prefetch for cross-model reads:
```python
def _process_orders(self):
    """Process orders with optimized field loading."""
    orders = self.search([('state', '=', 'pending')])
    # Force-read fields we'll need, in one batch
    orders.mapped('partner_id.name')
    orders.mapped('order_line_ids.product_id.name')
    # Now iterate — all data is cached
    for order in orders:
        self._process_single_order(order)
```

### Existing recordset: use fetch()
```python
def _export_records(self, records):
    """Export known records with predictable cache loading."""
    records.fetch(['name', 'partner_id', 'amount_total'])
    records.partner_id.fetch(['name', 'vat'])
    return [record._export_row() for record in records]
```

`fetch()` is for an existing recordset. `search_fetch()` is for search + known
field load in one step.

---

## 4. Search Optimization

### Use search_fetch() (v18+):
```python
# OLD — Two separate queries
records = self.search(domain)
data = records.read(['name', 'state', 'amount'])

# NEW — Combined search + fetch in one query
records = self.search_fetch(domain, ['name', 'state', 'amount'], limit=100)
```

**Rules:**
- Pass the smallest field list you need.
- Avoid fetching binary/html/blob fields unless required.
- Use `limit` when the UI or business rule only needs a bounded result.
- Use deterministic `order`, usually ending with `id`.

### search_count with limit:
```python
# When you only need to know "are there more than X?"
has_many = self.search_count(domain, limit=100) >= 100
```

### Efficient existence check:
```python
# BAD — loads all matching records
if self.search([('partner_id', '=', partner.id)]):
    ...

# GOOD — stops at first match
if self.search([('partner_id', '=', partner.id)], limit=1):
    ...

# ALSO GOOD — count with limit
if self.search_count([('partner_id', '=', partner.id)], limit=1):
    ...
```

### Shape domains around indexed/selective filters:
```python
domain = [
    ('company_id', '=', self.env.company.id),  # company-scoped and indexed
    ('state', '=', 'confirmed'),               # common indexed selection
    ('date', '>=', start_date),                # range filter
    ('name', 'ilike', search_term),            # expensive text search
]
```

Prefer `Domain` composition for dynamic conditions:
```python
from odoo.fields import Domain

domain = Domain('company_id', 'in', self.env.companies.ids)
if partner:
    domain &= Domain('partner_id', '=', partner.id)
if states:
    domain &= Domain('state', 'in', states)
records = self.search_fetch(domain, ['partner_id', 'state'], order='id')
```

---

## 5. Computed Fields Strategy

### v20: `compute_sql` before `store=True`

The old reflex — "it needs to be searchable, so store it" — is wrong in v20. A
`compute_sql` field is searchable, groupable and sortable with **no column, no index, no
recompute traffic and no staleness**.

```python
currency_id = fields.Many2one(
    'res.currency',
    compute='_compute_currency_id',
    compute_sql='_compute_sql_currency_id',
    compute_sudo=True,
)

def _compute_sql_currency_id(self, table):
    return SQL("COALESCE(%s, %s)", table.company_id.currency_id, fallback_currency_id)
```

Decision order: plain compute → `compute_sql` → `search='_method'` → `store=True`.

### When storing is still right:
```python
# STORE when:
# - the value cannot be expressed in SQL
# - it is read far more often than its dependencies change
# - the computation is genuinely expensive and its inputs are stable
total = fields.Float(compute='_compute_total', store=True)
```

### When NOT to store:
```python
# DON'T STORE when:
# - dependencies change on almost every write
# - the field is only shown on a form view (single record)
# - the value is time-dependent (it silently goes stale)
current_age = fields.Integer(compute='_compute_current_age')  # changes daily
```

### Optimize compute methods:
```python
@api.depends('line_ids.price_total')
def _compute_amount_total(self):
    """Compute total amount from order lines.

    Optimized: uses _read_group for batch aggregation instead of
    iterating lines per record.
    """
    if not self.ids:
        for record in self:
            record.amount_total = 0.0
        return
    # Batch aggregation — one SQL query for all records
    totals = self.env['my.model.line']._read_group(
        [('order_id', 'in', self.ids)],
        groupby=['order_id'],
        aggregates=['price_total:sum'],
    )
    totals_map = {order.id: total for order, total in totals}
    for record in self:
        record.amount_total = totals_map.get(record.id, 0.0)
```

### Compute count without N searches:
```python
@api.depends('invoice_ids')
def _compute_invoice_count(self):
    counts = self.env['account.move']._read_group(
        [('partner_id', 'in', self.ids)],
        groupby=['partner_id'],
        aggregates=['__count'],
    )
    count_by_partner = {partner.id: count for partner, count in counts}
    for partner in self:
        partner.invoice_count = count_by_partner.get(partner.id, 0)
```

**Compute performance rules:**
- Assign every record, even when there is no aggregate result.
- Avoid `search_count()` inside the compute loop.
- Avoid `mapped()` over huge One2many fields if `_read_group()` can aggregate.
- Keep dependencies precise; broad dependencies cause recompute storms.
- Store only when the field is searched/grouped/listed often or expensive and stable.

---

## 6. Write Optimization

### Avoid triggering unnecessary recomputation:
```python
# BAD — each write triggers recomputation of dependents
for record in self:
    record.field_a = value_a
    record.field_b = value_b  # triggers recompute AGAIN

# GOOD — single write, one recomputation pass
for record in self:
    record.write({'field_a': value_a, 'field_b': value_b})

# BEST — batch write when values are the same
self.write({'field_a': value_a, 'field_b': value_b})
```

### Use with_context to skip unnecessary operations:
```python
# Skip mail notifications during bulk import
records.with_context(mail_create_nolog=True, tracking_disable=True).create(vals_list)
```

---

## 7. Database Indexes

### Index syntax:
```python
class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'

    # Field-level index
    partner_id = fields.Many2one('res.partner', index=True)
    state = fields.Selection([...], index=True)
    date = fields.Date(index=True)

    # Composite indexes: declare named class attributes
    _partner_state_idx = models.Index("(partner_id, state)")
    _company_date_idx = models.Index("(company_id, date)")
```

### Index kind (`index=` accepts more than a bool):
- `True` / `'btree'` — standard BTREE; the default choice for Many2one and equality/range filters.
- `'btree_not_null'` — BTREE that excludes NULLs; smaller and faster when the column is mostly NULL or NULL is never searched.
- `'trigram'` — GIN trigram index; the right tool for `ilike` / substring search on text columns (a plain BTREE does not help `ilike '%x%'`).
- `False` / `None` — no index (default). No effect on non-stored/virtual fields.

### Index guidelines:
- Always index: `Many2one` fields, `state`/`status` fields, date fields used in search
- Index `company_id` — always used in record rules
- Use `'trigram'` for columns hit by leading-wildcard `ilike`; use `'btree_not_null'` for sparse optional columns
- Add composite indexes for common search combinations
- Don't over-index: each index slows down writes

---

## 8. Recordset Operations

### Efficient recordset manipulation:
```python
# Filtering an existing recordset with domain semantics
confirmed = self.filtered_domain([('state', '=', 'confirmed')])

# Mapping — collect related field values
partner_names = self.mapped('partner_id.name')  # returns list
partner_ids = self.mapped('partner_id')  # returns recordset

# Sorting
sorted_records = self.sorted(key=lambda r: r.date, reverse=True)

# Deduplication
unique_partners = self.mapped('partner_id')  # already deduplicated for recordsets
```

### Avoid Python-side filtering when DB can do it:
```python
# BAD — loads ALL records then filters in Python
all_records = self.search([])
filtered = all_records.filtered(lambda r: r.amount > 1000 and r.state == 'confirmed')

# GOOD — let the database do the filtering
filtered = self.search([('amount', '>', 1000), ('state', '=', 'confirmed')])
```

`filtered_domain()` evaluates a domain on an existing recordset and keeps the
same order. It is clean for already-loaded small/medium sets, but it is not a
replacement for `search()` on large tables.

---

## 9. Memory Management

### Large recordset processing:
```python
def _cron_process_large_batch(self):
    """Process records in chunks to control memory usage."""
    batch_size = 200
    while True:
        records = self.search(
            [('state', '=', 'pending')],
            limit=batch_size,
            order='id',
        )
        if not records:
            break
        with self.env.cr.savepoint():
            records._process_batch()
        # Commit and clear cache after each batch
        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()
```

Avoid `offset` for mutating batch jobs: once processed records leave the domain,
offset can skip rows. Repeatedly search the first batch ordered by `id`.

### Avoid loading large binary fields:
```python
# BAD — loads binary data for all records
records = self.search([])
for r in records:
    if r.attachment_data:  # loads potentially huge binary
        ...

# GOOD — only load binary when needed
records = self.search_fetch(domain, ['name', 'state'])  # no binary
for r in records:
    if r.has_attachment:  # boolean check first
        data = r.attachment_data  # load binary only when needed
```

`Binary` fields default to `attachment=True` (stored in `ir.attachment`, not a table column) and are never prefetched. When you only need the size — list views, "has file?" checks — read with `bin_size=True` in context so the field yields the human-readable size instead of the blob:

```python
size_str = record.with_context(bin_size=True).document  # e.g. "2.10 Mb", not the bytes
```

---

## 10. Profiling

### Enable Odoo profiling:
```python
# In your method, for debugging:
from odoo.tools.profiler import profile

@profile('/tmp/my_profile.log')
def action_heavy_computation(self):
    """Profile this method to find bottlenecks."""
    ...
```

### Quick query counting:
```python
import logging
_logger = logging.getLogger(__name__)

def action_debug_performance(self):
    """Count SQL queries for debugging."""
    cr = self.env.cr
    query_count_before = cr.sql_log_count
    # ... your code ...
    query_count_after = cr.sql_log_count
    _logger.info("Queries executed: %d", query_count_after - query_count_before)
```

### Key metrics to watch:
- **Query count**: Should be O(1) or O(models), never O(records)
- **Query time**: Use `--log-sql` flag to see slow queries
- **Memory**: Watch for large recordsets held in memory
- **Recomputation chains**: Long `@api.depends` chains can cascade

---

## 11. Relational Search Access

Use `bypass_search_access` intentionally on relational fields when you
need to bypass comodel search access checks. This is primarily a security behavior,
not a generic performance switch.

```python
class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'

    # Default and safest: respects comodel access checks
    partner_id = fields.Many2one('res.partner')

    # Use only when there is an explicit security reason and documented scope
    # (for example, controlled technical lookups where record exposure is filtered separately)
    technical_partner_id = fields.Many2one('res.partner', bypass_search_access=True)
```

**Rules:**
- Prefer normal relational fields (default access checks) in business code
- Treat `bypass_search_access=True` as security-sensitive and justify it with a comment
- Optimize search performance with proper domains and indexes, not access-bypass flags
- `auto_join` was removed. To filter on related records efficiently, use the `any` / `not any` domain operators (see `orm.md` section 4) rather than the old join flag.

---

## 12. with_prefetch() Control

Control the prefetch group to optimize memory usage when processing
subsets of a large recordset.

```python
def _process_in_chunks(self, records):
    """Process records with controlled prefetch groups.

    By default, accessing ANY field on one record prefetches that field
    for ALL records in the same recordset. For 100k records, this loads
    100k values into memory even if you process 100 at a time.
    """
    chunk_size = 200
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        # with_prefetch() creates a prefetch group limited to this chunk
        # so only 200 records are loaded into memory at a time
        for record in chunk.with_prefetch():
            record._do_expensive_work()
```

**When to use:**
- Processing very large recordsets (10k+) where you don't need all data in memory
- When combined with `cr.commit()` in batch processing
- Rebuilding a prefetch set after indexing into recordsets or browsing IDs

---

## 13. _order Performance

The `_order` attribute generates an ORDER BY clause on EVERY `search()`.
A bad `_order` can destroy performance.

```python
# BAD — sorts by a computed non-stored field (Python sort, not SQL)
_order = 'display_name'

# BAD — sorts by a non-indexed field on a large table
_order = 'description desc'

# GOOD — sorts by indexed fields
_order = 'create_date desc, id desc'

# GOOD — if you need to sort by date, make sure it's indexed
_order = 'date_order desc, id desc'
date_order = fields.Datetime(index=True)

# BEST — for large tables, always include `id` as tiebreaker for deterministic results
_order = 'sequence, id'
```

**Rules:**
- Always include `id` in `_order` as a tiebreaker (prevents non-deterministic pagination)
- Every field in `_order` should be indexed
- Never use non-stored computed fields in `_order` (triggers Python-side sort)
- For inherited models, check the parent's `_order` — you inherit it

---

## 14. Flush and Invalidate

Understanding when to flush/invalidate is critical for correct behavior
when mixing ORM and raw SQL.

```python
# After ORM operations, before raw SQL reads:
self.env.flush_all()  # writes all pending ORM changes to database
self.env.cr.execute("SELECT ...")  # now sees the latest data

# After raw SQL writes, before ORM reads:
self.env.cr.execute("UPDATE my_model SET state = 'done' WHERE ...")
self.env.invalidate_all()  # clears ORM cache so it re-reads from DB

# Per-recordset variants (more targeted, less overhead):
records.flush_recordset(['field_a', 'field_b'])  # flush specific fields
records.invalidate_recordset(['field_a'])  # invalidate specific fields
```

**Rules:**
- `flush_all()` before any raw SQL SELECT that reads data you changed via ORM
- `invalidate_all()` after any raw SQL UPDATE/DELETE that changes data ORM might have cached
- After `cr.commit()` always call `invalidate_all()` — the cache may reference stale data
- Prefer `flush_recordset`/`invalidate_recordset` over `_all` variants for better performance

---

## 15. ORM vs Raw SQL Decision Matrix

| Scenario | Use ORM | Use Raw SQL |
|----------|---------|-------------|
| Simple CRUD (create/read/update/delete) | Yes | No |
| Search with domain filters | Yes (`search()`) | No |
| Grouped aggregation (SUM, COUNT, AVG) | Yes (`_read_group()`) | Only if ORM too slow |
| Window functions (RANK, ROW_NUMBER, running totals) | No | Yes |
| Bulk update 10k+ rows without triggers | No | Yes |
| Complex JOINs across 4+ tables | Maybe | Usually yes |
| LATERAL JOIN, CTE, recursive queries | No | Yes |
| EXISTS subquery for performance | No | Yes |
| INSERT ... ON CONFLICT (upsert) | No | Yes |
| Row locking (FOR UPDATE) | Yes (`lock_for_update()` / `try_lock_for_update()`) | Raw only for exotic lock modes |
| Dashboard KPI (single fast query) | Depends | Often yes |
| COPY command for bulk data import | No | Yes |

**Always remember:** Raw SQL bypasses security (ACLs, record rules), tracking,
computed fields, and constraints. Every raw SQL usage needs explicit justification.

---

## 16. Performance Review Workflow

Use this workflow before optimizing code:

1. Identify the hot path: button, compute, list view, cron, import, controller, report.
2. Estimate volume: records per request, child records per parent, companies, users.
3. Count queries: query count should be O(1), O(models), or O(batches), never O(records).
4. Check data loaded: avoid loading unused fields, binary fields, and huge One2many chains.
5. Move filtering/aggregation to SQL via domains, `search_fetch()`, `fetch()`, `_read_group()`, or justified SQL.
6. Add an index only for a real repeated query shape.
7. Re-check security and multi-company behavior after optimizing.

---

## 17. Compute Field Batch Patterns

### Parent totals from children
```python
@api.depends('line_ids.amount')
def _compute_amount_total(self):
    grouped = self.env['my.line']._read_group(
        [('parent_id', 'in', self.ids)],
        ['parent_id'],
        ['amount:sum'],
    )
    amount_by_parent = {parent.id: amount for parent, amount in grouped}
    for record in self:
        record.amount_total = amount_by_parent.get(record.id, 0.0)
```

### Boolean existence
```python
@api.depends('line_ids.state')
def _compute_has_late_lines(self):
    grouped = self.env['my.line']._read_group(
        [('parent_id', 'in', self.ids), ('state', '=', 'late')],
        ['parent_id'],
        ['__count'],
    )
    late_parent_ids = {parent.id for parent, count in grouped if count}
    for record in self:
        record.has_late_lines = record.id in late_parent_ids
```

### Related display data
```python
@api.depends('partner_id')
def _compute_partner_vat_label(self):
    self.partner_id.fetch(['name', 'vat'])
    for record in self:
        partner = record.partner_id
        record.partner_vat_label = partner and "%s - %s" % (partner.name, partner.vat or '') or False
```

---

## 18. Prefetch and Fetch Strategy

| Situation | Best tool |
|---|---|
| Search records and immediately read known fields | `search_fetch(domain, field_names)` |
| Existing recordset, known fields | `records.fetch(field_names)` |
| Need related records as recordset | `records.mapped('partner_id')` |
| Need grouped recordsets by existing field | `records.grouped('field_name')` |
| Need aggregate count/sum per parent | `_read_group()` |
| Huge batch where cache grows too much | Chunk + `with_prefetch()` + invalidate after commit |

**Do not:**
- `browse(record_id)` inside loops when `browse(ids)` works.
- Repeatedly call `mapped()` inside loops.
- Use `prefetch_fields=False` globally unless you measured and understand the side effects.
- Fetch all fields (`field_names=None`) in export/report code when a small list is enough.

---

## 19. Domains and Query Shape

Good domains are selective, indexed, and company-aware.

```python
domain = (
    Domain('company_id', 'in', self.env.companies.ids)
    & Domain('state', '=', 'posted')
    & Domain('date', '>=', date_from)
    & Domain('date', '<=', date_to)
)
```

**Rules:**
- Include `company_id` when the business object is company-scoped.
- Include `active_test=False` only when archived records are required.
- Avoid leading wildcard `ilike` on large tables in hot paths.
- Avoid sorting large tables by unindexed text/computed fields.
- For repeated searches, index the combination that matches equality/range/order usage.
- Use partial indexes for common boolean/state subsets on very large tables.

---

## 20. Cron and Import Throughput

```python
def _cron_process_pending(self, limit=500):
    """Process pending records in resumable chunks."""
    records = self.search_fetch(
        [('state', '=', 'pending')],
        ['state', 'company_id'],
        limit=limit,
        order='id',
    )
    for company, batch in records.grouped('company_id').items():
        with self.env.cr.savepoint():
            batch.with_company(company)._process_pending_batch()
    if self._can_commit():
        self.env.cr.commit()
        self.env.invalidate_all()
```

**Rules:**
- Make jobs resumable; each committed batch must leave clear state.
- Use savepoints around recoverable batch units.
- Commit only after durable state changes.
- Never commit inside a compute/onchange/button request to hide errors.
- Keep external calls idempotent or persist idempotency keys.
- Load `transactions.md` before introducing manual commits.

---

## 21. High-Risk Antipatterns

```python
# N+1 count
for partner in partners:
    partner.invoice_count = Move.search_count([('partner_id', '=', partner.id)])

# Broken mutating pagination
offset = 0
while True:
    batch = Model.search(domain, offset=offset, limit=100)
    batch.write({'state': 'done'})
    offset += 100

# Cache/security bypass without discipline
self.env.cr.execute(f"UPDATE my_model SET state = '{state}' WHERE id IN {tuple(self.ids)}")
```

Replace with `_read_group()`, repeated first-page batches, and parameterized SQL
with flush/invalidate only when SQL is justified.

---

## 22. Performance Budgets

Use rough budgets to decide how hard to optimize:

| Path | Target |
|---|---|
| Button on 1 record | O(1) queries plus bounded related reads |
| Button on N selected records | O(models) or O(groups), not O(records) |
| Stored compute for list view | One aggregate query per child model |
| Cron/import chunk | Bounded memory, bounded locks, resumable state |
| Dashboard/KPI | One or a few aggregate queries, cached if expensive |
| Portal/controller list | Domain + indexed order + limit/pager |

**Review rule:** if query count grows linearly with selected records, child
records, companies, or users, stop and redesign the data access.

---

## 23. List View and Dashboard Performance

List views expose compute and related-field mistakes quickly.

**Rules:**
- Store expensive fields displayed in list/kanban/search/groupby.
- Avoid non-stored computes that read One2many lines per row.
- Use smart button counts computed by `_read_group()`, not per-record `search_count()`.
- Keep default `_order` indexed and deterministic.
- Avoid default filters that force unindexed `ilike` on large tables.
- For dashboard cards, prefer a dedicated aggregate method using `_read_group()` or justified SQL.
- Cache expensive dashboard results only when invalidation is well-defined.

```python
def _compute_move_count(self):
    grouped = self.env['account.move']._read_group(
        [('partner_id', 'in', self.ids), ('state', '=', 'posted')],
        ['partner_id'],
        ['__count'],
    )
    count_by_partner = {partner.id: count for partner, count in grouped}
    for partner in self:
        partner.posted_move_count = count_by_partner.get(partner.id, 0)
```

---

## 24. Transaction Cost and Lock Time

Performance is not only query speed. Long transactions hold locks, keep dead
tuples alive, delay vacuum, and increase serialization conflicts.

**Rules:**
- In requests/buttons, keep one atomic transaction and make it fast.
- In cron/import jobs, process chunks small enough to avoid long locks.
- Commit only at resumable boundaries, then invalidate the environment.
- For worker queues and read-then-write atomicity, lock rows with `try_lock_for_update(limit=...)` / `lock_for_update()` (ORM, `SKIP LOCKED`) instead of raw `FOR UPDATE`. See `transactions.md` section 10.
- Do external API calls outside broad database locks when possible.
- Never sleep inside a transaction unless the flow is explicitly designed for it.
