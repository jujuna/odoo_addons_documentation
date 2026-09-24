# SQL & PostgreSQL Patterns — Odoo 20

## Table of Contents

1. [When to Use Raw SQL](#1-when-to-use-raw-sql)
2. [Safe Query Execution](#2-safe-query-execution)
3. [Common Query Patterns](#3-common-query-patterns)
4. [PostgreSQL-Specific Features](#4-postgresql-specific-features)
5. [EXPLAIN ANALYZE — Reading Query Plans](#5-explain-analyze)
6. [Indexing Strategy](#6-indexing-strategy)
7. [Odoo ORM-to-SQL Mental Model](#7-orm-to-sql-mental-model)
8. [Migrations and Data Scripts](#8-migrations-and-data-scripts)
9. [Database Maintenance](#9-database-maintenance)
10. [Antipatterns](#10-antipatterns)
11. [Commit and Cache Safety](#11-commit-and-cache-safety)

---

## 1. When to Use Raw SQL

**Default: Use the ORM.** Only use raw SQL when:

| Situation | Example | Why ORM fails |
|-----------|---------|---------------|
| Complex aggregation | Window functions, LATERAL JOIN | Not expressible via `_read_group` |
| Bulk data update | UPDATE 100k rows at once | ORM `write()` triggers compute/tracking per record |
| Reporting queries | Multi-table pivot, crosstab | ORM has no pivot support |
| Performance-critical paths | Dashboard stats, cron counts | ORM adds Python overhead |
| Schema inspection | Check column existence | Not an ORM concept |
| Database-level locking | `SELECT ... FOR UPDATE SKIP LOCKED` | ORM has no locking API |

**Every raw SQL call MUST have:**
1. A comment explaining WHY the ORM cannot do the job
2. Parameterized queries (`%s` — NEVER string interpolation)
3. A docstring documenting the query purpose
4. Flush/invalidate/`modified()` discipline if SQL interacts with ORM-cached data

---

## 2. Safe Query Execution

### Parameterized queries (MANDATORY):
```python
# CORRECT — parameters as tuple
self.env.cr.execute(
    "SELECT id, name FROM res_partner WHERE company_id = %s AND active = %s",
    (self.env.company.id, True),
)

# CORRECT — IN clause with tuple
partner_ids = (1, 2, 3)
self.env.cr.execute(
    "SELECT id FROM sale_order WHERE partner_id IN %s",
    (tuple(partner_ids),),  # Note: tuple of tuple for IN
)

# CORRECT — LIKE with %% escaping
self.env.cr.execute(
    "SELECT id FROM res_partner WHERE name ILIKE %s",
    (f"%{search_term}%",),
)

# WRONG — SQL injection vectors
self.env.cr.execute(f"SELECT id FROM res_partner WHERE name = '{name}'")
self.env.cr.execute("SELECT id FROM res_partner WHERE id IN (%s)" % ','.join(ids))
```

### Fetching results:
```python
# Single dict per row
self.env.cr.execute("SELECT id, name FROM res_partner WHERE id = %s", (partner_id,))
row = self.env.cr.dictfetchone()  # {'id': 1, 'name': 'John'} or None

# All rows as dicts
self.env.cr.execute("SELECT id, name FROM res_partner LIMIT 100")
rows = self.env.cr.dictfetchall()  # [{'id': 1, 'name': 'John'}, ...]

# All rows as tuples (faster, less memory)
self.env.cr.execute("SELECT id, name FROM res_partner LIMIT 100")
rows = self.env.cr.fetchall()  # [(1, 'John'), (2, 'Jane'), ...]

# Single value
self.env.cr.execute("SELECT COUNT(*) FROM res_partner WHERE active = %s", (True,))
count = self.env.cr.fetchone()[0]
```

### Using the SQL builder (v18+):
```python
from odoo.tools import SQL           # composed, injection-safe SQL
from odoo.models import Query      # v20: moved from odoo.tools

# SQL builder is injection-safe by construction
query = SQL(
    "SELECT id FROM %s WHERE company_id = %s AND state IN %s",
    SQL.identifier('sale_order'),  # safe table name
    self.env.company.id,
    tuple(['draft', 'sent']),
)
self.env.cr.execute(query)
```

---

## 3. Common Query Patterns

### Batch existence check:
```python
def _get_existing_partner_emails(self, emails: list[str]) -> set[str]:
    """Return the subset of emails that already exist in res.partner.

    Raw SQL justified: checking thousands of emails in one query
    without loading full partner records.
    """
    if not emails:
        return set()
    self.env.cr.execute(
        "SELECT LOWER(email) FROM res_partner WHERE LOWER(email) IN %s",
        (tuple(emails),),
    )
    return {row[0] for row in self.env.cr.fetchall()}
```

### Bulk UPDATE bypassing ORM:
```python
def _bulk_archive_old_records(self, cutoff_date):
    """Archive records older than cutoff date.

    Raw SQL justified: mass-update thousands of records without
    triggering compute fields, tracking, and mail notifications
    that ORM write() would fire.
    """
    Model = self.env['my.model']
    Model.flush_model(['active', 'state', 'date'])
    self.env.cr.execute("""
        UPDATE my_model
        SET active = FALSE,
            write_date = NOW() AT TIME ZONE 'UTC',
            write_uid = %s
        WHERE date < %s
            AND active = TRUE
            AND state = 'done'
        RETURNING id
    """, (self.env.uid, cutoff_date))
    records = Model.browse([row[0] for row in self.env.cr.fetchall()])
    records.invalidate_recordset(['active', 'write_date', 'write_uid'], flush=False)
    records.modified(['active'])
    _logger.info("Archived %d records before %s", len(records), cutoff_date)
```

### Aggregation with window functions:
```python
def _get_running_totals(self):
    """Compute running total of invoice amounts per partner.

    Raw SQL justified: window functions (SUM OVER) not available
    via ORM _read_group.

    Returns:
        list[dict]: Rows with partner_id, move_name, amount, running_total.
    """
    self.env.cr.execute("""
        SELECT
            am.partner_id,
            am.name AS move_name,
            am.amount_total,
            SUM(am.amount_total) OVER (
                PARTITION BY am.partner_id
                ORDER BY am.invoice_date, am.id
            ) AS running_total
        FROM account_move am
        WHERE am.move_type = 'out_invoice'
            AND am.state = 'posted'
            AND am.company_id = %s
        ORDER BY am.partner_id, am.invoice_date
    """, (self.env.company.id,))
    return self.env.cr.dictfetchall()
```

### Upsert (INSERT ... ON CONFLICT):
```python
def _upsert_partner_stats(self, partner_id, total_orders, total_amount):
    """Upsert partner statistics in a single atomic operation.

    Raw SQL justified: INSERT ON CONFLICT is atomic and avoids
    the check-then-insert race condition.
    """
    self.env.cr.execute("""
        INSERT INTO partner_stats (partner_id, total_orders, total_amount, write_date)
        VALUES (%s, %s, %s, NOW() AT TIME ZONE 'UTC')
        ON CONFLICT (partner_id) DO UPDATE SET
            total_orders = EXCLUDED.total_orders,
            total_amount = EXCLUDED.total_amount,
            write_date = EXCLUDED.write_date
    """, (partner_id, total_orders, total_amount))
```

### Locking rows for concurrent processing:
```python
def _claim_next_batch(self, batch_size: int = 50):
    """Claim a batch of unprocessed records for this worker.

    Uses SKIP LOCKED to allow multiple cron workers to process
    different records concurrently without deadlocks.

    Raw SQL justified: SELECT FOR UPDATE SKIP LOCKED not available in ORM.
    """
    self.env.cr.execute("""
        SELECT id FROM queue_job
        WHERE state = 'pending'
        ORDER BY priority, id
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """, (batch_size,))
    ids = [row[0] for row in self.env.cr.fetchall()]
    return self.browse(ids)
```

---

## 4. PostgreSQL-Specific Features

### Array operations:
```python
# Check if a value is in a PostgreSQL array column
self.env.cr.execute("""
    SELECT id FROM my_model
    WHERE %s = ANY(tag_ids)
""", (tag_id,))
```

### JSONB queries (for serialized_json fields):
```python
# Query inside a JSONB column
self.env.cr.execute("""
    SELECT id, data->>'email' AS email
    FROM my_model
    WHERE data @> %s::jsonb
""", (json.dumps({'status': 'active'}),))
```

### Date/time operations:
```python
# Records created in the last 30 days
self.env.cr.execute("""
    SELECT id FROM sale_order
    WHERE create_date >= NOW() - INTERVAL '30 days'
        AND company_id = %s
""", (self.env.company.id,))

# Truncate to month for grouping
self.env.cr.execute("""
    SELECT
        DATE_TRUNC('month', date_order) AS month,
        COUNT(*) AS order_count,
        SUM(amount_total) AS total
    FROM sale_order
    WHERE state = 'sale' AND company_id = %s
    GROUP BY DATE_TRUNC('month', date_order)
    ORDER BY month
""", (self.env.company.id,))
```

### CTE (Common Table Expressions) for complex logic:
```python
def _get_partner_lifetime_value(self):
    """Compute lifetime value per partner using CTE for readability.

    Raw SQL justified: multi-step aggregation with CTE not expressible
    in ORM.
    """
    self.env.cr.execute("""
        WITH order_totals AS (
            SELECT
                partner_id,
                SUM(amount_total) AS order_total,
                COUNT(*) AS order_count
            FROM sale_order
            WHERE state IN ('sale', 'done')
                AND company_id = %s
            GROUP BY partner_id
        ),
        invoice_totals AS (
            SELECT
                partner_id,
                SUM(amount_total_signed) AS invoice_total
            FROM account_move
            WHERE move_type = 'out_invoice'
                AND state = 'posted'
                AND company_id = %s
            GROUP BY partner_id
        )
        SELECT
            rp.id AS partner_id,
            rp.name,
            COALESCE(ot.order_total, 0) AS total_ordered,
            COALESCE(ot.order_count, 0) AS order_count,
            COALESCE(it.invoice_total, 0) AS total_invoiced
        FROM res_partner rp
        LEFT JOIN order_totals ot ON ot.partner_id = rp.id
        LEFT JOIN invoice_totals it ON it.partner_id = rp.id
        WHERE rp.customer_rank > 0
        ORDER BY COALESCE(ot.order_total, 0) DESC
        LIMIT 100
    """, (self.env.company.id, self.env.company.id))
    return self.env.cr.dictfetchall()
```

---

## 5. EXPLAIN ANALYZE

### How to diagnose slow queries:

```python
# In shell or debugger — prepend EXPLAIN ANALYZE
self.env.cr.execute("""
    EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
    SELECT so.id
    FROM sale_order so
    JOIN res_partner rp ON rp.id = so.partner_id
    WHERE so.state = 'sale'
        AND so.company_id = %s
        AND rp.country_id = %s
""", (company_id, country_id))
for row in self.env.cr.fetchall():
    print(row[0])
```

### Reading the plan — key things to look for:

| What you see | What it means | Fix |
|-------------|--------------|-----|
| `Seq Scan` on large table | Full table scan — no index used | Add index on filter columns |
| `Nested Loop` with high row count | N+1 at SQL level | Rewrite as JOIN or use IN |
| `Sort` with `external merge` | Data too big for `work_mem` | Add index to avoid sort, or increase `work_mem` |
| `Hash Join` | Normal for joining tables | Usually fine |
| `Bitmap Heap Scan` | Index used but many rows match | Usually fine — index is helping |
| Actual rows >> Estimated rows | Bad statistics | Run `ANALYZE tablename;` |
| Actual time much higher than planned | I/O bottleneck or lock wait | Check disk, check for lock contention |

### Useful PostgreSQL settings for debugging:
```sql
-- In psql or Odoo shell:
SET log_min_duration_statement = 100;  -- log queries > 100ms
SET auto_explain.log_min_duration = 100;
SET auto_explain.log_analyze = true;
```

---

## 6. Indexing Strategy

### Odoo automatic indexes:
- Every `Many2one` field with `index=True` gets a B-tree index
- `_rec_name` field is indexed if it's `Char`
- Primary key (`id`) is always indexed
- `company_id` should ALWAYS have `index=True`

### When to add custom indexes:
```python
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # composite indexes for common query patterns
    _partner_state_idx = models.Index("(partner_id, state)")
    _company_date_order_idx = models.Index("(company_id, date_order)")
    _state_create_date_idx = models.Index("(state, create_date)")
```

### Partial indexes via SQL (for special cases):
```python
def init(self):
    """Create a partial index for active draft records only.

    This is much smaller than a full index and speeds up
    the most common dashboard query.
    """
    self.env.cr.execute("""
        CREATE INDEX IF NOT EXISTS idx_my_model_active_draft
        ON my_model (create_date DESC)
        WHERE state = 'draft' AND active = TRUE
    """)
```

### Index guidelines:
- **DO index:** `company_id`, `state`, `partner_id`, date fields used in search, fields used in record rules
- **DO add composite indexes** for your most common domain filter combinations
- **DON'T index:** Text/Html fields, Boolean fields (low cardinality), fields only used on form views
- **DON'T over-index:** Each index slows down INSERT/UPDATE. 3-5 indexes per table is typical

---

## 7. ORM-to-SQL Mental Model

Understanding what SQL the ORM generates helps you write efficient code.

### search() generates:
```sql
-- self.env['sale.order'].search([('state', '=', 'sale'), ('partner_id', '=', 5)], limit=10)
SELECT "sale_order"."id"
FROM "sale_order"
WHERE ("sale_order"."state" = 'sale')
    AND ("sale_order"."partner_id" = 5)
    -- + record rules appended automatically:
    AND ("sale_order"."company_id" IN (1))
ORDER BY "sale_order"."id"  -- or _order
LIMIT 10;
```

### Prefetch generates:
```sql
-- Accessing record.partner_id.name triggers:
SELECT "res_partner"."id", "res_partner"."name", ...  -- ALL fields of res.partner
FROM "res_partner"
WHERE "res_partner"."id" IN (1, 2, 3, 4, 5, ...);  -- ALL partner_ids from the prefetch group
```

### write() generates:
```sql
-- records.write({'state': 'done'}) triggers:
UPDATE "sale_order"
SET "state" = 'done',
    "write_date" = '2026-02-17 12:00:00',
    "write_uid" = 2
WHERE "id" IN (1, 2, 3);
-- THEN: recompute stored computed fields that depend on 'state'
-- THEN: create mail.tracking.value records for tracked fields
-- THEN: flush all pending computations
```

### _read_group() generates:
```sql
-- self.env['sale.order.line']._read_group(
--     [('order_id', 'in', [1,2,3])],
--     groupby=['order_id'],
--     aggregates=['price_total:sum'],
-- )
SELECT "sale_order_line"."order_id",
       SUM("sale_order_line"."price_total")
FROM "sale_order_line"
WHERE "sale_order_line"."order_id" IN (1, 2, 3)
GROUP BY "sale_order_line"."order_id";
```

---

## 8. Migrations and Data Scripts

> **Not our practice.** Do not write migration scripts in this project (see `simplicity.md` §9).
> Handle data changes in code — a compute, a field default, or a fill-only-if-empty pass.
> This section is reference-only, for reading migration scripts that already exist in `addons/`.

### Pre-migration script (runs BEFORE module update):
```python
# migrations/<version>/pre-migrate.py
import logging

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Rename old column before ORM creates the new one.

    This prevents data loss when renaming a field.
    """
    if not version:
        return
    _logger.info("Pre-migration: renaming old_field to new_field")
    cr.execute("""
        ALTER TABLE my_model
        RENAME COLUMN old_field TO new_field
    """)
```

### Post-migration script (runs AFTER module update):
```python
# migrations/<version>/post-migrate.py
import logging
from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Backfill new computed data after schema changes."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("Post-migration: setting default values for new_field")
    cr.execute("""
        UPDATE my_model
        SET new_status = 'active'
        WHERE new_status IS NULL
            AND state IN ('confirmed', 'done')
    """)
    _logger.info("Updated %d records", cr.rowcount)
```

### End-migration script (runs at the very end):
```python
# migrations/<version>/end-migrate.py
# Use for operations that need the fully updated registry
```

### Migration folder naming:
```
migrations/
└── <version>/           # matches the new version in __manifest__.py
    ├── pre-migrate.py    # before ORM update
    ├── post-migrate.py   # after ORM update
    └── end-migrate.py    # after all modules updated
```

---

## 9. Database Maintenance

### Vacuum and analyze (for DBAs):
```sql
-- After large bulk operations:
VACUUM ANALYZE sale_order;

-- Check table bloat:
SELECT
    schemaname, relname,
    n_dead_tup,
    n_live_tup,
    round(n_dead_tup * 100.0 / NULLIF(n_live_tup, 0), 1) AS dead_pct
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

### Check missing indexes:
```sql
-- Find tables with high sequential scan ratio (potential missing indexes):
SELECT
    relname,
    seq_scan,
    idx_scan,
    CASE WHEN seq_scan + idx_scan > 0
        THEN round(100.0 * seq_scan / (seq_scan + idx_scan), 1)
        ELSE 0
    END AS seq_scan_pct,
    n_live_tup
FROM pg_stat_user_tables
WHERE n_live_tup > 10000
    AND seq_scan > idx_scan
ORDER BY n_live_tup DESC;
```

### Check slow queries in PostgreSQL:
```sql
SELECT
    calls,
    round(total_exec_time::numeric, 1) AS total_ms,
    round(mean_exec_time::numeric, 1) AS mean_ms,
    LEFT(query, 100) AS query_preview
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

---

## 10. Antipatterns

### Never concatenate user input into SQL:
```python
# CRITICAL VULNERABILITY
cr.execute("DELETE FROM my_model WHERE name = '%s'" % name)
# If name = "'; DROP TABLE res_users; --" → database destroyed

# SAFE
cr.execute("DELETE FROM my_model WHERE name = %s", (name,))
```

### Never use `%s` inside the SQL string with `%` operator:
```python
# BUG — Python string formatting, NOT parameterized
cr.execute("SELECT * FROM t WHERE id = %s" % record_id)

# CORRECT — parameters as second argument
cr.execute("SELECT * FROM t WHERE id = %s", (record_id,))
```

### Don't forget to invalidate cache after raw SQL:
```python
# After UPDATE/DELETE via raw SQL, invalidate the changed records/fields:
Model = self.env['my.model']
if not ids:
    return Model.browse()
Model.flush_model(['state'])
cr.execute("""
    UPDATE my_model
       SET state = %s
     WHERE id IN %s
 RETURNING id
""", ('done', tuple(ids)))
records = Model.browse([row[0] for row in cr.fetchall()])
records.invalidate_recordset(['state'], flush=False)
records.modified(['state'])
```

### Don't use SELECT * in production code:
```python
# BAD — loads all columns, fragile to schema changes
cr.execute("SELECT * FROM sale_order WHERE id = %s", (order_id,))

# GOOD — explicit columns
cr.execute("SELECT id, name, state, amount_total FROM sale_order WHERE id = %s", (order_id,))
```

### Don't run queries without LIMIT in user-facing code:
```python
# DANGEROUS — could return millions of rows
cr.execute("SELECT id FROM sale_order WHERE state = 'draft'")

# SAFE — always limit
cr.execute("SELECT id FROM sale_order WHERE state = 'draft' LIMIT %s", (1000,))
```

### Don't use raw SQL for simple CRUD:
```python
# WRONG — reinventing the ORM, skipping security
cr.execute("INSERT INTO res_partner (name) VALUES (%s)", ("John",))

# CORRECT — ORM handles security, tracking, computed fields
self.env['res.partner'].create({'name': "John"})
```

---

## 11. Commit and Cache Safety

For full transaction rules, load `references/transactions.md`.

### Default: do not commit manually

Odoo commits successful requests/jobs at the framework boundary and rolls back
when an exception escapes. Manual `cr.commit()` makes previous changes durable
even if later code fails.

```python
# BAD in buttons, CRUD overrides, computes, constraints, onchanges
self.write({'state': 'done'})
self.env.cr.commit()
raise UserError(_("Later validation failed."))  # state is already committed
```

### When manual commit is acceptable

Use manual commit only for resumable workers: cron, queue jobs, imports,
migrations, or carefully documented external sync flows.

```python
def _cron_backfill(self, limit=1000):
    """Backfill records in durable chunks."""
    records = self.search([('needs_backfill', '=', True)], limit=limit, order='id')
    if not records:
        return
    with self.env.cr.savepoint():
        records._backfill_chunk()
    if self._can_commit():
        self.env.cr.commit()
        self.env.invalidate_all()
```

### SQL read after ORM write

```python
records.write({'state': 'ready'})
records.flush_recordset(['state'])
self.env.cr.execute(
    "SELECT COUNT(*) FROM my_model WHERE state = %s",
    ('ready',),
)
```

### SQL write before ORM read

```python
Model = self.env['my.model']
if not ids:
    return Model.browse()
Model.flush_model(['state'])
self.env.cr.execute("""
    UPDATE my_model
       SET state = %s
     WHERE id IN %s
 RETURNING id
""", ('done', tuple(ids)))
records = Model.browse([row[0] for row in self.env.cr.fetchall()])
records.invalidate_recordset(['state'], flush=False)
records.modified(['state'])
```

**Rules:**
- Flush before SQL reads or SQL predicates that depend on pending ORM writes.
- Invalidate after SQL writes before ORM reads changed fields.
- Call `modified()` after SQL updates fields used by stored computes.
- Prefer targeted `flush_model`, `flush_recordset`, `invalidate_recordset`.
- Use `env.invalidate_all()` after manual `commit()`/`rollback()` or broad SQL changes.
- Never commit to hide errors. Commit only to create a deliberate resumable boundary.
