# Scheduled Actions (Cron) — Odoo 20

## Table of Contents

1. [Cron XML Definition](#1-cron-xml-definition)
2. [Cron Method Patterns](#2-cron-method-patterns)
3. [Batch Processing](#3-batch-processing)
4. [_commit_progress API](#4-_commit_progress-api)
5. [Error Handling](#5-error-handling)
6. [Concurrency](#6-concurrency)
7. [Memory Management](#7-memory-management)
8. [Testing Cron Jobs](#8-testing-cron-jobs)
9. [Antipatterns](#9-antipatterns)

---

## 1. Cron XML Definition

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <record id="ir_cron_process_pending" model="ir.cron">
            <field name="name">My Module: Process Pending Records</field>
            <field name="model_id" ref="model_my_model"/>
            <field name="state">code</field>
            <field name="code">model._cron_process_pending()</field>
            <field name="user_id" ref="base.user_root"/>
            <field name="interval_number">1</field>
            <field name="interval_type">hours</field>
            <field name="active" eval="True"/>
        </record>
    </data>
</odoo>
```

### Field reference

| Field | Value | Purpose |
|---|---|---|
| `user_id` | `ref="base.user_root"` in core crons | Scheduler User: the job runs as this user (default: whoever creates the cron) |
| `interval_number` | integer > 0 | How many intervals between runs |
| `interval_type` | `minutes`, `hours`, `days`, `weeks`, `months` | Interval unit (default `months`) |
| `nextcall` | datetime | Next planned run (default: now) |
| `active` | `True`/`False` | Enable/disable |
| `priority` | integer | Lower = runs first (default: 5) |

`numbercall` and `doall` no longer exist on `ir.cron`
([ir_cron.py:108-124](../../../../odoo/addons/base/models/ir_cron.py#L108)). Putting them in
the XML fails the install with "Invalid field 'numbercall' in 'ir.cron'"
([odoo/orm/models.py:4131](../../../../odoo/orm/models.py#L4131)).

### Rules

- Always wrap in `<data noupdate="1">` — users may change the schedule
- Use descriptive `name` with module prefix
- Method must be on the model referenced by `model_id`
- `noupdate` also freezes `code`: renaming the method later breaks existing databases at run
  time, because `-u` does not rewrite the stored code. Keep cron method names stable

---

## 2. Cron Method Patterns

### Basic cron method

```python
def _cron_process_pending(self):
    """Cron: process all pending records.

    Called by ir.cron as its Scheduler User (user_id).
    """
    records = self.search([('state', '=', 'pending')], limit=500)
    for record in records:
        try:
            record._process_single()
        except Exception:
            _logger.exception("Failed to process %s(%s)", self._name, record.id)
```

### Key rules

- The `code` field is Python: arguments are allowed and core uses them
  (`model._gc_notifications(max_age_days=180)`, [mail/data/ir_cron_data.xml:36](../../../../addons/mail/data/ir_cron_data.xml#L36)).
  Give each argument a default so the method also runs without them
- The job runs as its `user_id` ([ir_cron.py:429](../../../../odoo/addons/base/models/ir_cron.py#L429),
  [:485](../../../../odoo/addons/base/models/ir_cron.py#L485)). With `base.user_root` (uid 1) the env
  is superuser, so ACLs and company rows do not apply ([odoo/orm/environments.py:66](../../../../odoo/orm/environments.py#L66));
  with a normal user they do. An admin can change the Scheduler User in the UI, so never rely on
  either: `sudo()` explicitly where the job needs it, filter companies explicitly
- `self.env.company` in a cron is the Scheduler User's default company (no
  `allowed_company_ids` in the context, [environments.py:263](../../../../odoo/orm/environments.py#L263)).
  A job serving several companies loops over them with `with_company()`
- Work that must run as a specific user (their credentials, their language) uses
  `with_user(user)` per user, not the cron's user
- Always add a `limit` to prevent unbounded processing
- Always handle exceptions per-record — one failure should not stop the batch
- Log errors with `_logger.exception()` for traceback

---

## 3. Batch Processing

For full commit rules, load `references/transactions.md`.

### Process in chunks with commit

```python
def _cron_process_large_batch(self):
    """Process records in chunks with periodic commits.

    Commits after each batch to:
    - Release DB locks
    - Save progress (so crashed batches don't re-process)
    - Free memory
    """
    batch_size = 200
    while True:
        records = self.search(
            [('state', '=', 'pending')],
            limit=batch_size,
            order='id',
        )
        if not records:
            break

        for record in records:
            try:
                with self.env.cr.savepoint():
                    record._process_single()
                    record.write({'state': 'done'})
            except Exception:
                _logger.exception("Failed to process %s", record.id)
                record.write({'state': 'error'})

        # Commit only when this cron is allowed to create resumable boundaries.
        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()
```

### Why commit + invalidate

```python
# After commit:
if self._can_commit():
    self.env.cr.commit()
    # Cache may reference data from before the commit.
    # If another transaction modified rows, our cache is stale.
    self.env.invalidate_all()  # MANDATORY after commit
```

---

## 4. _commit_progress API

`_commit_progress` handles commit timing and progress reporting for long-running cron tasks.
In v20 a job gets at least `MIN_TIME_PER_JOB = 120` seconds, each job runs in its own
`contextvars` context, and a repeatedly failing job notifies the admin before being
deactivated.

```python
def _cron_send_emails(self):
    """Send pending emails with progress tracking."""
    pending = self.search([('email_sent', '=', False)], order='id')
    remaining = len(pending)

    for record in pending:
        # Check if we should continue (respects time limits)
        if not self.env['ir.cron']._commit_progress(remaining=remaining):
            break

        try:
            record._send_email()
            record.write({'email_sent': True})
        except Exception:
            _logger.exception("Email send failed for %s", record.id)

        remaining -= 1
        self.env['ir.cron']._commit_progress(
            processed=1,
            remaining=remaining,
        )
```

### _commit_progress benefits

- Automatic periodic commits (no manual `cr.commit()`)
- Progress visible in cron log
- Respects `ir.cron` time limits — stops gracefully
- Returns `False` when time is up — use as loop condition

---

## 5. Error Handling

### Per-record error isolation with savepoints

```python
def _cron_process_orders(self):
    """Process orders with error isolation per record."""
    orders = self.search([('state', '=', 'to_process')], limit=500)

    success_count = 0
    error_count = 0

    for order in orders:
        try:
            with self.env.cr.savepoint():
                order._do_processing()
                order.write({'state': 'processed'})
                success_count += 1
        except Exception:
            _logger.exception(
                "Failed to process order %s(%s)",
                order.name, order.id,
            )
            # Savepoint rolled back — order is unchanged
            # Write error state OUTSIDE the failed savepoint
            try:
                order.write({'state': 'error'})
            except Exception:
                _logger.exception("Could not mark order %s as error", order.id)
            error_count += 1

    _logger.info(
        "Cron complete: %d processed, %d errors",
        success_count, error_count,
    )
```

### Never catch and silently ignore

```python
# BAD — hides bugs, loses all errors
def _cron_process(self):
    try:
        self._do_everything()
    except Exception:
        pass

# GOOD — log every error with context
def _cron_process(self):
    for record in self.search([...]):
        try:
            record._process()
        except Exception:
            _logger.exception("Cron error on %s(%s)", self._name, record.id)
```

---

## 6. Concurrency

### FOR UPDATE SKIP LOCKED for parallel workers

When multiple cron workers may run the same job:

```python
def _cron_process_queue(self):
    """Process queue items with concurrent worker safety.

    Uses SKIP LOCKED to avoid deadlocks when multiple
    cron workers process the same queue.
    """
    self.env.cr.execute("""
        SELECT id FROM my_queue
        WHERE state = 'pending'
        ORDER BY priority, id
        LIMIT 100
        FOR UPDATE SKIP LOCKED
    """)
    ids = [row[0] for row in self.env.cr.fetchall()]
    if not ids:
        return

    records = self.browse(ids)
    for record in records:
        try:
            with self.env.cr.savepoint():
                record._process()
                record.write({'state': 'done'})
        except Exception:
            _logger.exception("Queue item %s failed", record.id)
```

---

## 7. Memory Management

### Use with_prefetch() for large recordsets

```python
def _cron_process_all(self):
    """Process with controlled memory usage."""
    records = self.search([('state', '=', 'pending')], order='id')
    chunk_size = 200

    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        # Limit prefetch to this chunk only
        for record in chunk.with_prefetch():
            record._process_single()

        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()
```

### Avoid loading binary fields

```python
# BAD — loads potentially huge binary data for all records
records = self.search([('state', '=', 'pending')])
for r in records:
    if r.file_data:  # loads binary
        ...

# GOOD — search_fetch without binary, load only when needed
records = self.search_fetch(
    [('state', '=', 'pending')],
    ['name', 'state', 'has_file'],  # no binary fields
)
for r in records:
    if r.has_file:
        data = r.file_data  # load binary per-record
```

---

## 8. Testing Cron Jobs

```python
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMyCron(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.records = cls.env['my.model'].create([
            {'name': 'R1', 'state': 'pending'},
            {'name': 'R2', 'state': 'pending'},
            {'name': 'R3', 'state': 'done'},  # should be skipped
        ])

    def test_cron_processes_pending_only(self):
        """Test cron processes only pending records."""
        self.env['my.model']._cron_process_pending()
        self.assertEqual(self.records[0].state, 'done')
        self.assertEqual(self.records[1].state, 'done')
        self.assertEqual(self.records[2].state, 'done')  # unchanged

    def test_cron_handles_errors_gracefully(self):
        """Test cron continues after per-record error."""
        # Make first record fail
        self.records[0].write({'name': False})  # will trigger validation error
        self.env['my.model']._cron_process_pending()
        # Second record should still be processed
        self.assertEqual(self.records[0].state, 'error')
        self.assertEqual(self.records[1].state, 'done')
```

---

## 9. Antipatterns

### No limit on search

```python
# BAD — may load millions of records
def _cron_process(self):
    records = self.search([('state', '=', 'pending')])

# GOOD — always limit
def _cron_process(self):
    records = self.search([('state', '=', 'pending')], limit=1000)
```

### Commit without invalidate

```python
# BAD — cache is stale after commit
self.env.cr.commit()
print(record.state)  # may return old value!

# GOOD
if self._can_commit():
    self.env.cr.commit()
    self.env.invalidate_all()
```

### No error handling

```python
# BAD — one error stops entire cron
def _cron_process(self):
    for record in self.search([...]):
        record._process()  # if this raises, all remaining records are skipped

# GOOD — isolate errors per record
def _cron_process(self):
    for record in self.search([...]):
        try:
            with self.env.cr.savepoint():
                record._process()
        except Exception:
            _logger.exception("Failed: %s", record.id)
```

### Using time.sleep in cron

```python
# BAD — blocks the worker thread
import time
def _cron_poll_api(self):
    while True:
        result = self._call_api()
        if result:
            break
        time.sleep(60)  # blocks for 60 seconds!

# GOOD — let the cron scheduler handle intervals
def _cron_poll_api(self):
    result = self._call_api()
    if result:
        self._process_result(result)
    # Cron will call again at the configured interval
```
