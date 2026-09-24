# Transaction, Commit, Savepoint, and Cache Safety — Odoo 20

Use this whenever code touches `cr.commit()`, `cr.rollback()`, savepoints, raw SQL writes,
external side effects, cron chunking, queue jobs, imports, or cache invalidation.

The default rule is simple: **Odoo owns the transaction. Do not manually commit unless
the operation is explicitly resumable and partial durability is part of the design.**

---

## 1. Mental Model

In normal Odoo request/RPC execution:

1. A cursor and environment are opened.
2. ORM writes, recomputes, mail tracking, and SQL all happen in one database transaction.
3. If the method returns successfully, Odoo commits at the service boundary.
4. If an exception escapes, Odoo rolls back the whole transaction.

Manual `cr.commit()` cuts that transaction into separate durable pieces. After that,
later exceptions cannot roll back the already committed part.

**Commit changes the contract from atomic to resumable.** Only do it when that is truly intended.

---

## 2. Commit Decision Matrix

| Code path | Manual commit? | Why |
|---|---:|---|
| Button/action called by a user | No | User expects all-or-nothing behavior. |
| `create()`, `write()`, `unlink()` override | No | Breaks ORM lifecycle and callers' transaction expectations. |
| Compute, inverse, onchange, constraint | Never | Can corrupt recompute flow and create partial data. |
| HTTP/controller request | Almost never | Let the request boundary commit or rollback. |
| Wizard | No, unless it starts a documented background/resumable operation | Wizard failures should normally rollback. |
| Cron processing thousands of independent records | Yes, per completed chunk if resumable | Prevents losing all progress and limits locks/cache/memory. |
| Queue job worker | Often yes, controlled by job runner | One job or chunk is the durability boundary. |
| Import/migration/backfill script | Yes, per deterministic chunk | Work is resumable and can be restarted safely. |
| External API sync | Sometimes | Only after local state is persisted enough to retry/idempotently reconcile. |
| Sending mail/webhooks | Sometimes | Durable send state can be committed per item/chunk. |
| Tests | No | Manual commits break test isolation; guard with `_can_commit()`. |

---

## 3. Safe Manual Commit Requirements

Manual commit is allowed only when all are true:

1. The code is cron, queue, migration, import, or a documented external-sync worker.
2. Each committed chunk leaves records in a valid state.
3. The job can be restarted without duplicating irreversible side effects.
4. The chunk records progress (`state`, `last_processed_id`, external idempotency key, log row).
5. Exceptions after commit are expected and handled as "retry next chunk", not as rollback.
6. Tests can disable the commit path.
7. The environment cache is cleared after commit.

```python
from odoo import modules, tools


def _can_commit(self):
    """Return whether this worker may commit its own chunks."""
    return not (tools.config['test_enable'] or modules.module.current_test)
```

---

## 4. Safe Chunk Commit Pattern

```python
def _cron_process_pending(self, limit=500):
    """Process pending records in durable, resumable chunks."""
    records = self.search_fetch(
        [('state', '=', 'pending')],
        ['state', 'company_id'],
        limit=limit,
        order='id',
    )
    if not records:
        return

    for company, batch in records.grouped('company_id').items():
        with self.env.cr.savepoint():
            batch.with_company(company)._process_pending_batch()

    if self._can_commit():
        self.env.cr.commit()
        self.env.invalidate_all()
```

**Rules:**
- Commit after a successful chunk, not after each record unless records are expensive/irreversible.
- Use savepoints inside the chunk for recoverable sub-failures.
- After `commit()`, call `env.invalidate_all()` before continuing with ORM reads.
- Do not use `offset` when processed rows leave the search domain; keep taking the first ordered chunk.

---

## 5. Savepoints vs Commits

Use savepoints for partial rollback inside the same transaction.

```python
for record in self:
    try:
        with self.env.cr.savepoint():
            record._validate_payload()
            record._sync_one()
            record.write({'state': 'done'})
    except UserError:
        raise
    except Exception:
        _logger.exception("Failed to sync %s(%s)", record._name, record.id)
        record.write({'state': 'error'})
```

| Tool | Durability | Later exception can rollback it? | Typical use |
|---|---:|---:|---|
| `savepoint()` | Not durable | Yes | Skip/mark one failed record while keeping main transaction alive. |
| `commit()` | Durable | No | Finish a resumable chunk. |
| `rollback()` | Discards current transaction | N/A | Worker-level recovery after database/serialization errors. |

Prefer savepoints for ordinary business flows. Prefer commits only for resumable workers.

---

## 6. How Commits Break Flows

Manual commit can introduce these bugs:

- **Commit-then-raise:** user sees an error, but records were already changed.
- **Partial workflow state:** header committed, lines/attachments/messages later fail.
- **Duplicate external side effects:** Odoo retries a request after serialization failure, but the external API call already happened.
- **Stale cache:** ORM cache still contains values from before/after commit unless invalidated.
- **Broken tests:** transactional tests expect rollback after each test.
- **Lost atomicity:** callers cannot wrap your method in their own all-or-nothing transaction.
- **Post-commit timing surprises:** cursor commit flushes and runs post-commit hooks.
- **Lock visibility changes:** other transactions can see partial state earlier than intended.

Never hide errors by committing first. Make partial progress an explicit design.

---

## 7. External API Durability Pattern

Use states and idempotency keys so retry is safe.

```python
def _sync_to_provider(self):
    """Send records to provider with retry-safe local state."""
    for record in self:
        with self.env.cr.savepoint():
            if not record.provider_request_key:
                record.write({
                    'provider_request_key': record._make_idempotency_key(),
                    'sync_state': 'sending',
                })

        # Durable boundary before the external side effect: a retry can reuse
        # provider_request_key instead of creating a duplicate provider object.
        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()

        with self.env.cr.savepoint():
            record = record.exists()
            response = record._provider_send(record.provider_request_key)
            record._apply_provider_response(response)
            record.write({'sync_state': 'sent'})

        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()
```

**Rules:**
- Persist an idempotency key before a retryable send.
- Store provider references immediately after successful responses.
- If provider confirms success but local write fails, next retry must query/reconcile, not create duplicates.
- Do not commit in an interactive button unless the button's contract clearly says it performs durable external submission.

---

## 8. Raw SQL and Cache/Recompute

Before raw SQL reads data changed by ORM:

```python
records.flush_recordset(['state', 'amount_total'])
self.env.cr.execute(
    "SELECT id FROM my_model WHERE state = %s AND amount_total > %s",
    ('posted', 0),
)
```

After raw SQL writes fields that ORM may have cached:

```python
Model = self.env['my.model']
Model.flush_model(['state'])
self.env.cr.execute("""
    UPDATE my_model
       SET state = %s,
           write_uid = %s,
           write_date = NOW() AT TIME ZONE 'UTC'
     WHERE state = %s
 RETURNING id
""", ('done', self.env.uid, 'ready'))
records = Model.browse([row[0] for row in self.env.cr.fetchall()])
records.invalidate_recordset(['state', 'write_uid', 'write_date'], flush=False)
records.modified(['state'])
```

**Rules:**
- `flush_model()` / `flush_recordset()` before SQL reads or SQL predicates that depend on pending ORM writes.
- `RETURNING id` lets you invalidate exactly the changed records.
- `invalidate_recordset(..., flush=False)` is appropriate immediately after a controlled SQL update when you already flushed before the SQL.
- `modified(fnames)` schedules recomputation of stored computed fields depending on changed fields.
- Use `env.invalidate_all()` only when targeted invalidation is not practical.

---

## 9. Rollback Discipline

Use rollback only at worker boundaries, not inside normal business methods.

```python
for tx in transactions:
    try:
        tx._post_process()
        if self._can_commit():
            self.env.cr.commit()
    except psycopg2.OperationalError:
        self.env.cr.rollback()
        self.env.invalidate_all()
        continue
```

**Rules:**
- After rollback, cached record values may not match the database; invalidate before continuing.
- Do not rollback from inside a method called by unknown callers; raise and let the boundary handle it.
- Catch database operational errors separately from business errors.
- A rollback also discards all uncommitted work from other code using the same cursor.

### Log, then raise — the log is rolled back too

`message_post()`, a log-model `create()` or any write made just before `raise UserError(...)`
disappears with the transaction. When the failure itself must stay visible (an external
system refused a document), write the trace in its own cursor, then raise. Core precedent,
shortened ([l10n_my_edi/models/myinvois_document.py:426](../../../../addons/l10n_my_edi/models/myinvois_document.py#L426)):

```python
with self.env.registry.cursor() as log_cr:
    log_env = self.env(cr=log_cr, user=SUPERUSER_ID)
    log_env['account.move'].browse(invoice_bodies)._message_log_batch(bodies=invoice_bodies)
raise UserError(error_message)
```

The separate cursor commits when the `with` block ends without error
([odoo/sql_db.py:331](../../../../odoo/sql_db.py#L331)). Only insert new rows there (messages,
log lines): updating a row the main transaction already changed waits on that transaction's
own lock and hangs the request.

---

## 10. Row Locking for Concurrency

When two transactions may modify the same rows (worker queues, sequence gaps, inventory reservations, "process exactly once" flows), take an explicit write-lock instead of hand-writing `SELECT ... FOR UPDATE`. The ORM exposes two methods on every recordset.

```python
from odoo.exceptions import LockError

# Block on these exact rows; raise LockError if any is already locked elsewhere
records.lock_for_update()
records._process_once()

# Worker-queue style: lock whatever is free now, skip the rest, process the subset
batch = self.search([('state', '=', 'pending')], limit=100, order='id')
locked = batch.try_lock_for_update(limit=100)
locked.write({'state': 'processing'})
```

Both use `SKIP LOCKED` (not `NOWAIT`), so a contended row does not abort the transaction:
- `lock_for_update(*, allow_referencing=False)` locks every row in `self` and raises `LockError` if it could not lock them all. Use when you must process exactly these records.
- `try_lock_for_update(*, allow_referencing=False, limit=None)` locks what it can and returns the locked subset. Use for queue workers so concurrent runs each grab a disjoint batch.
- `allow_referencing=True` takes the weaker `FOR NO KEY UPDATE` lock (other transactions may still create FK references to the row). Use it when you change non-identifier fields only.

**Rules:**
- `LockError` subclasses `UserError` — a broad `except UserError` will swallow it. Catch `LockError` explicitly when you want retry/skip behavior.
- Take the lock before reading the values your write depends on, so no other transaction can change them between your read and your write.
- Lock inside the transaction that performs the write; never hold a lock across an external API call or a sleep.
- Prefer a database `models.Constraint(...)` for plain uniqueness; reach for row locks only when the invariant needs read-then-write atomicity.

---

## 11. Review Checklist

Block manual transaction code unless it answers these questions:

- What is the durability boundary: record, batch, job, or migration step?
- What exact state proves a chunk is complete?
- Can the job resume after process kill at any line?
- Can it run twice without duplicate external side effects?
- What happens if an exception occurs after commit?
- How are tests protected from real commits?
- Are caches invalidated after commit/rollback/raw SQL writes?
- Are recomputations scheduled after raw SQL updates to dependency fields?
- Are locks held for the shortest practical time?
