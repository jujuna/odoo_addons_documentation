# Python Best Practices — Odoo 20 (Python 3.12–3.14)

This file covers the Python language layer for Odoo code. For ORM-specific
contracts (recordsets, CRUD overrides, domains, transactions, multi-company),
load `references/orm.md` first.

## Table of Contents

1. [Type Hints in Odoo](#1-type-hints-in-odoo)
2. [Generators and Lazy Evaluation](#2-generators-and-lazy-evaluation)
3. [Context Managers](#3-context-managers)
4. [Collections and Data Structures](#4-collections-and-data-structures)
5. [String Handling](#5-string-handling)
6. [Error Handling Patterns](#6-error-handling-patterns)
7. [Logging Standards](#7-logging-standards)
8. [Functional Patterns](#8-functional-patterns)
9. [Match Statements (3.10+)](#9-match-statements)
10. [Model Inheritance Patterns](#10-model-inheritance-patterns)
11. [ORM Method Overrides](#11-orm-method-overrides)
12. [Context Patterns](#12-context-patterns)
13. [Dangerous Antipatterns](#13-dangerous-antipatterns)
14. [Odoo Python Standards](#14-odoo-python-standards)
15. [Production Python Review Standard](#15-production-python-review-standard)
16. [Fast, Clean, High-Standard Python](#16-fast-clean-high-standard-python)
17. [Safe and Performant by Default](#17-safe-and-performant-by-default)
18. [Caching Model Methods (ormcache)](#18-caching-model-methods-ormcache)

---

## 1. Type Hints in Odoo

Odoo core does NOT use type hints extensively, but for custom modules they
improve readability and IDE support. Use them on private/utility methods —
skip on ORM overrides (the framework types are complex).

```python
from collections.abc import Iterable

def _prepare_invoice_values(self) -> dict:
    """Prepare dictionary for account.move creation."""
    self.ensure_one()
    return {
        'partner_id': self.partner_id.id,
        'move_type': 'out_invoice',
    }

def _get_partner_ids_from_domain(self, domain: list) -> list[int]:
    """Extract partner IDs matching the given domain."""
    return self.env['res.partner'].search(domain).ids

def _split_into_batches(self, records, size: int = 200) -> Iterable:
    """Yield successive batches of the given size."""
    for i in range(0, len(records), size):
        yield records[i:i + size]
```

**Rules:**
- Use on private helpers and utility methods
- Skip on `create`, `write`, `unlink`, `search` overrides (signature is defined by ORM)
- Use `dict` not `Dict`, `list` not `List`
- Use `X | None` not `Optional[X]`; PEP 695 generics (`def f[T](...)`) are available

---

## 2. Generators and Lazy Evaluation

Use generators when processing large datasets to avoid loading everything into
memory at once. Critical for cron jobs and data migration.

```python
def _iter_pending_records(self, batch_size: int = 500):
    """Yield pending records for read-only processing.

    Use offset only when the loop does not mutate records out of the domain.
    """
    offset = 0
    while True:
        batch = self.search(
            [('state', '=', 'pending')],
            limit=batch_size,
            offset=offset,
            order='id',
        )
        if not batch:
            return
        yield batch
        offset += batch_size

def _iter_mutating_pending_records(self, batch_size: int = 500):
    """Yield first-page batches for mutating/resumable processing."""
    while True:
        batch = self.search(
            [('state', '=', 'pending')],
            limit=batch_size,
            order='id',
        )
        if not batch:
            return
        yield batch

def _cron_process_all(self):
    """Process all pending records in memory-safe, resumable batches."""
    for batch in self._iter_mutating_pending_records(batch_size=200):
        batch._process_batch()
        # Commit only in resumable cron/import/migration jobs, never in requests.
        if self._can_commit():
            self.env.cr.commit()
            self.env.invalidate_all()
```

### Use `any()` / `all()` for short-circuit checks:
```python
# BAD — evaluates ALL records even if first one fails
has_draft = bool([r for r in self if r.state == 'draft'])

# GOOD — stops at first match
has_draft = any(r.state == 'draft' for r in self)

# GOOD — checks ALL pass
all_confirmed = all(r.state == 'confirmed' for r in self)
```

---

## 3. Context Managers

### Environment savepoints for atomic operations:
```python
def action_process_risky(self):
    """Process with rollback safety on partial failure."""
    for record in self:
        try:
            # Creates a SQL SAVEPOINT — rolls back on exception
            with self.env.cr.savepoint():
                record._do_risky_operation()
                record.write({'state': 'done'})
        except Exception:
            _logger.warning(
                "Failed to process record %s, skipping.", record.id,
                exc_info=True,
            )
            record.write({'state': 'error'})
```

### Temporary context change:
```python
# Use with_context for temporary env changes — don't mutate self.env.context
records_no_track = self.with_context(tracking_disable=True)
records_no_track.write({'state': 'done'})
# Original self still has normal context
```

### Suppress file operations:
```python
from contextlib import suppress

with suppress(FileNotFoundError):
    os.unlink(temp_file_path)
```

---

## 4. Collections and Data Structures

### defaultdict for grouping:
```python
from collections import defaultdict

def _group_lines_by_product(self):
    """Group order lines by product for consolidated processing.

    Returns:
        dict: Mapping of product_id to list of line recordsets.
    """
    grouped = defaultdict(lambda: self.env['sale.order.line'])
    for line in self.order_line:
        grouped[line.product_id] |= line  # recordset union
    return grouped
```

### Use `dict.setdefault` and `dict.get`:
```python
# BAD — verbose and error-prone
if key in my_dict:
    value = my_dict[key]
else:
    value = default_value

# GOOD
value = my_dict.get(key, default_value)

# Accumulating in a dict
vals = {}
vals.setdefault('invoice_line_ids', []).append((0, 0, line_vals))
```

### Tuple unpacking in loops:
```python
# BAD
for item in totals:
    order = item[0]
    total = item[1]

# GOOD — structured unpacking
for order, total in totals:
    order.amount_total = total

# With _read_group results:
totals = self.env['sale.order.line']._read_group(
    [('order_id', 'in', self.ids)],
    groupby=['order_id'],
    aggregates=['price_total:sum'],
)
totals_map = {order.id: total for order, total in totals}
```

### Iterate by item; use enumerate/zip:
```python
# BAD — index gymnastics
for i in range(len(records)):
    line_no = i + 1
    record = records[i]

# GOOD — enumerate for index + value
for line_no, record in enumerate(records, start=1):
    ...

# GOOD — zip to walk parallel sequences together
for record, vals in zip(records, vals_list):
    ...
```

---

## 5. String Handling

### Translation-safe string formatting:
```python
# CORRECT — self.env._() needs no import and uses the env's language
msg = self.env._("Order %s cannot be deleted (state: %s).", self.name, self.state)

# CORRECT — named placeholders for complex messages
msg = self.env._("%(count)s orders for %(partner)s.", count=len(self), partner=self.partner_id.name)

# WRONG — f-string breaks translation extraction
msg = self.env._(f"Order {self.name} cannot be deleted.")

# WRONG — .format() also breaks extraction
msg = self.env._("Order {} cannot be deleted.".format(self.name))
```

`self.env._()` is the preferred form in v19+ and is what new core code uses. The imported
`from odoo import _` reads the language from the caller's `context` / `kwargs` / `self.env`
locals (`odoo/tools/translate.py` `_get_lang`); do not mix the two styles inside one file.

| Where the text is | Use | Why |
|---|---|---|
| method with `self` | `self.env._("...")` | env language, no import |
| module-level helper (no `self`) | pass `env`, call `env._("...")` | bare `_()` there uses the HTTP request's language when there is one; in a cron it logs a warning and returns English |
| module-level constant | `_lt = LazyTranslate(__name__)`, `LABEL = _lt("...")`, later `env._(LABEL)` | translated when used, not at import (`translate.py:1213`; core: `auth_signup/models/res_users.py:18`) |

Code translations are looked up by (addon of the calling file, exact source text)
(`translate.py:2599`): moving a text inside one addon keeps its translation; rewording it,
or moving it into another addon, loses it until that addon's `.po` has it.

### String building for large outputs:
```python
# BAD — O(n²) string concatenation
result = ""
for line in lines:
    result += line.name + "\n"

# GOOD — join a list
result = "\n".join(line.name for line in lines)
```

---

## 6. Error Handling Patterns

### Granular exception handling:
```python
# BAD — catches everything, hides bugs
try:
    record.action_confirm()
except Exception:
    pass

# GOOD — catch specific exceptions
from odoo.exceptions import UserError, ValidationError, AccessError

try:
    record.action_confirm()
except (UserError, ValidationError) as e:
    _logger.warning("Could not confirm %s: %s", record.name, e)
except AccessError:
    raise  # always re-raise access errors
```

### Use `ensure_one()` properly:
```python
# GOOD — at the start of single-record methods
def action_confirm(self):
    """Confirm this record."""
    self.ensure_one()  # raises ValueError if recordset is empty or multi
    ...

# GOOD — for optional single-record access
partner = self.env['res.partner'].search(domain, limit=1)
if partner:
    partner.do_something()  # safe, we know it's 0 or 1 records
```

### Never bare-except in production code:
```python
# FORBIDDEN in production
except:
    pass

# ACCEPTABLE only in truly defensive contexts (cron, mixin fallback)
# and always with logging:
except Exception:
    _logger.exception("Unexpected error processing %s", record)
```

---

## 7. Logging Standards

```python
import logging

_logger = logging.getLogger(__name__)

# Levels and when to use them:
_logger.debug("Query returned %d results", count)         # development only
_logger.info("Processing batch of %d records", len(self))  # normal operations
_logger.warning("Skipped record %s: missing partner", r.id)  # recoverable issues
_logger.error("Payment gateway returned error: %s", resp)    # non-fatal errors
_logger.exception("Unhandled error in cron job")              # with traceback

# RULES:
# 1. Always use lazy formatting (%, not f-strings)
_logger.info("Processing %s", record.name)      # GOOD — lazy
_logger.info(f"Processing {record.name}")        # BAD  — evaluated even if not logged

# 2. Use %r for untrusted values (shows repr with quotes)
_logger.warning("Invalid input: %r", user_input)

# 3. Never log sensitive data (passwords, tokens, PII)
_logger.info("Auth token: %s", token)  # FORBIDDEN

# 4. Use _logger.exception() inside except blocks (auto-includes traceback)
try:
    self._process()
except Exception:
    _logger.exception("Failed to process %s(%s)", self._name, self.id)
```

---

## 8. Functional Patterns

### Chained operations on recordsets:
```python
# Odoo recordsets support mapped/filtered/sorted natively
confirmed_partner_names = (
    self
    .filtered(lambda o: o.state == 'confirmed')
    .mapped('partner_id')
    .sorted('name')
    .mapped('name')
)
```

### Use `operator.itemgetter` for sorting dicts:
```python
from operator import itemgetter

# When sorting a list of dicts (common in report data)
data = [{'name': 'B', 'amount': 200}, {'name': 'A', 'amount': 100}]
sorted_data = sorted(data, key=itemgetter('amount'), reverse=True)
```

### Walrus operator (Python 3.8+, common in 3.10+):
```python
# Useful in Odoo for conditional processing
self.ensure_one()
if partner := self.partner_id:
    partner.message_post(body=_("New order created."))

# In list comprehensions
valid = [
    inv
    for so in self
    if (inv := so.invoice_ids.filtered(lambda i: i.state == 'posted'))
]
```

---

## 9. Match Statements

Structural pattern matching — useful for state machines and
dispatchers in Odoo.

```python
def _get_next_state(self) -> str:
    """Determine the next workflow state.

    Returns:
        str: The next state value.

    Raises:
        UserError: If current state has no valid transition.
    """
    match self.state:
        case 'draft':
            return 'confirmed'
        case 'confirmed':
            return 'in_progress'
        case 'in_progress':
            return 'done'
        case 'done' | 'cancelled':
            raise UserError(_("No transition from state '%s'.", self.state))
        case _:
            raise UserError(_("Unknown state: %s", self.state))

def _dispatch_action(self, action_type: str, **kwargs):
    """Dispatch to the correct handler based on action type."""
    match action_type:
        case 'email':
            return self._send_email(**kwargs)
        case 'sms':
            return self._send_sms(**kwargs)
        case 'webhook':
            return self._call_webhook(**kwargs)
        case _:
            _logger.warning("Unknown action type: %r", action_type)
```

---

## 10. Model Inheritance Patterns

Odoo has three distinct inheritance mechanisms. Confusing them is the #1
source of architectural mistakes.

### Classical Inheritance (`_inherit` without `_name`)
Extends an existing model in-place. No new DB table.

```python
class ResPartner(models.Model):
    """Add custom fields to the existing res.partner model."""

    _inherit = 'res.partner'

    loyalty_points = fields.Integer(string='Loyalty Points', default=0)

    def action_add_loyalty(self):
        """Add loyalty points to this partner."""
        self.loyalty_points += 10
```

**Use when:** Adding fields/methods/overrides to an existing model.
**DB effect:** Adds columns to the existing table.
**Key rule:** Do NOT set `_name` — that would create a new model.

### Prototype Inheritance (`_inherit` with new `_name`)
Copies the parent model into a new, independent model with its own table.

```python
class BookingOrder(models.Model):
    """New model based on sale.order structure."""

    _name = 'booking.order'
    _description = 'Booking Order'
    _inherit = 'sale.order'

    booking_date = fields.Datetime(string='Booking Date')
```

**Use when:** You want a new model that starts with the same schema as another.
**DB effect:** Creates a NEW table with all parent columns + your additions.
**Key rule:** Rarely used — most of the time you want classical or delegation.

### Delegation Inheritance (`_inherits`)
Composition pattern. The child model links to a parent record via a required
Many2one. Fields from the parent are accessible on the child transparently.

```python
class EventTicket(models.Model):
    """Event ticket that embeds a product.product record."""

    _name = 'event.ticket'
    _description = 'Event Ticket'
    _inherits = {'product.product': 'product_id'}

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='cascade',
    )
    event_id = fields.Many2one('event.event', string='Event', required=True)
```

**Use when:** Your model "is a" parent record (e.g., a ticket IS a product).
**DB effect:** New table with a FK to the parent. Parent record auto-created.
**Key rule:** Parent fields are read/write-through. `event_ticket.name` reads from `product_product.name`.

### Mixin Inheritance (`_inherit` with AbstractModel)
Reusable behavior that adds fields/methods without creating a table.

```python
class TrackingMixin(models.AbstractModel):
    """Mixin that adds GPS tracking fields."""

    _name = 'tracking.mixin'
    _description = 'GPS Tracking Mixin'

    latitude = fields.Float(string='Latitude', digits=(10, 7))
    longitude = fields.Float(string='Longitude', digits=(10, 7))
    last_tracked = fields.Datetime(string='Last Tracked')

    def action_update_location(self, lat, lng):
        """Update GPS coordinates."""
        self.write({
            'latitude': lat,
            'longitude': lng,
            'last_tracked': fields.Datetime.now(),
        })


class DeliveryOrder(models.Model):
    """Delivery order with GPS tracking."""

    _name = 'delivery.order'
    _description = 'Delivery Order'
    _inherit = ['mail.thread', 'tracking.mixin']  # multiple mixins

    name = fields.Char(string='Reference', required=True)
```

**Use when:** Sharing behavior across unrelated models (like `mail.thread`).
**DB effect:** Mixin columns are added to each model that inherits it.
**Key rule:** Use `AbstractModel` for the mixin — it has no table of its own.

### Quick Reference

| Pattern | `_name` | `_inherit` | New table? | Use case |
|---------|---------|------------|------------|----------|
| Classical | omit | `'existing.model'` | No | Add fields/override methods |
| Prototype | new name | `'existing.model'` | Yes | Clone schema into new model |
| Delegation | new name | omit | Yes (with FK) | "is-a" composition |
| Mixin | omit | `['mixin1', 'mixin2']` | No | Reusable behaviors |

---

## 11. ORM Method Overrides

For full ORM contracts, use `references/orm.md`. This section is the short
Python syntax reminder.

### create() — always use `@api.model_create_multi`:
```python
@api.model_create_multi
def create(self, vals_list):
    """Create records with custom pre-processing.

    Always use @api.model_create_multi — the ORM calls create() with
    a list of dicts, and this decorator ensures batch creation works.
    """
    for vals in vals_list:
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('my.model') or _('New')
    return super().create(vals_list)
```

### write() — batch-aware override:
```python
def write(self, vals):
    """Override write to add side effects.

    Important: `self` is a multi-record recordset. Use `self.filtered()`
    if you need to act only on a subset.
    """
    if 'state' in vals and vals['state'] == 'done':
        # Pre-write validation on all records at once
        for record in self:
            if not record.line_ids:
                raise UserError(_("Cannot complete '%s': no lines.", record.name))
    result = super().write(vals)
    if 'state' in vals and vals['state'] == 'done':
        self._post_completion_actions()
    return result
```

### copy() — handle duplication:
```python
def copy(self, default=None):
    """Duplicate with modified name and reset state."""
    self.ensure_one()
    default = dict(default or {})
    default.setdefault('name', _("%s (copy)", self.name))
    return super().copy(default)
```

### _name_search — custom search-as-you-type:
```python
def _name_search(self, name='', domain=None, operator='ilike', limit=None, order=None):
    """Allow searching by reference code or name.

    This is called when typing in a Many2one field.
    """
    domain = domain or []
    if name:
        domain = ['|', ('name', operator, name), ('code', operator, name)] + domain
    return self._search(domain, limit=limit, order=order)
```

### _rec_name and _rec_names_search:
```python
class ProductVariant(models.Model):
    _name = 'product.variant'
    _description = 'Product Variant'
    _rec_name = 'display_name'  # field used for display_name
    _rec_names_search = ['name', 'default_code', 'barcode']  # fields searched in name_search
```

---

## 12. Context Patterns

### with_company() — switch company context:
```python
# When you need to read/write in another company's context
other_company = self.env['res.company'].browse(other_company_id)
record.with_company(other_company).write({'field': value})

# Common in multi-company logic
for company in self.env['res.company'].search([]):
    records = self.with_company(company).search([('company_id', '=', company.id)])
    records._process_for_company()
```

### with_context() — common patterns:
```python
# Skip mail tracking during bulk operations
self.with_context(tracking_disable=True).write(vals)

# Skip mail notifications during import
self.with_context(mail_create_nolog=True).create(vals_list)

# Force active_test=False to include archived records
all_records = self.with_context(active_test=False).search([])

# Pass default values to a sub-creation
self.with_context(default_partner_id=partner.id).action_open_wizard()

# Set allowed companies
self.with_context(allowed_company_ids=[company_1.id, company_2.id])
```

**Rules:**
- Context is immutable from the caller's point of view; never mutate `self.env.context`.
- Prefer explicit context keys with a module prefix for custom behavior.
- Do not use context as hidden business state when a real field or argument is clearer.
- Preserve `allowed_company_ids` unless intentionally changing company scope.

---

## 13. Dangerous Antipatterns

### Mutable default arguments:
```python
# BUG — the list is shared across all calls
def action_process(self, tags=[]):
    tags.append('processed')
    ...

# CORRECT
def action_process(self, tags=None):
    """Process with optional tags."""
    tags = tags or []
    tags.append('processed')
    ...
```

### Late binding in closures (lambdas in loops):
```python
# BUG — all lambdas capture the LAST value of `rec`
handlers = []
for rec in self:
    handlers.append(lambda: rec.action_confirm())
# All handlers will confirm the LAST record!

# CORRECT — bind with default argument
handlers = []
for rec in self:
    handlers.append(lambda r=rec: r.action_confirm())
```

### Comparing with `is` vs `==`:
```python
# Use `is` ONLY for singletons (None, True, False)
if value is None:      # CORRECT
if value is False:     # CORRECT
if value == 0:         # CORRECT (0 is not False in Odoo context)
if record is True:     # WRONG for Odoo — recordsets are truthy/falsy

# For recordsets, use truthiness:
if record:             # CORRECT — non-empty recordset
if not record:         # CORRECT — empty recordset
```

### Never modify `self` during iteration:
```python
# BUG — modifying the recordset you're iterating
for record in self:
    if record.state == 'cancelled':
        self -= record  # UNDEFINED BEHAVIOR

# CORRECT — filter first, then act
to_process = self.filtered(lambda r: r.state != 'cancelled')
for record in to_process:
    record._process()
```

### Avoid `eval()` / `exec()`:
```python
# FORBIDDEN — arbitrary code execution
domain = eval(user_provided_string)

# CORRECT — use ast.literal_eval for safe literals
import ast
domain = ast.literal_eval(user_provided_string)

# BEST — use json.loads if the format permits
import json
domain = json.loads(user_provided_string)
```

### Module-level mutable state:
```python
# BUG — shared across requests/workers, not thread-safe, never invalidated
_CACHE = {}

def _get_thing(self, key):
    if key not in _CACHE:
        _CACHE[key] = self._compute_thing(key)
    return _CACHE[key]

# CORRECT — use ormcache (registry-aware, invalidated on data change) — see section 18.
# Module-level names should be immutable constants only.
```

---

## 14. Odoo Python Standards

### Imports

```python
import logging
from collections import defaultdict

from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)
```

**Rules:**
- All imports at module top — never import inside a method by default. The only exceptions are breaking a circular import or deferring a heavy/optional dependency; mark those with a short reason / `# noqa: PLC0415`.
- Standard library imports first, then Odoo imports, then local module imports.
- Import `Command` when writing x2many values.
- Import `Domain` when composing dynamic domains.
- Import float helpers when comparing quantities, currencies, or UoM values.

### Comments and docstrings

Explain in the docstring, not in inline comments. A reader should learn what a method does
and why from its docstring alone; the body should read without narration.

```python
# GOOD — the docstring carries the intent and the non-obvious rule; the body has no comments
def _prepare_invoice_values(self):
    """Build the account.move values for this order.

    Uses the order's fiscal position, not the partner's current one, so a partner change
    after confirmation does not re-tax an already agreed price.
    """
    self.ensure_one()
    return {
        'partner_id': self.partner_id.id,
        'move_type': 'out_invoice',
        'fiscal_position_id': self.fiscal_position_id.id,
    }

# AVOID — inline comments narrating the code, the real reason nowhere
def _prepare_invoice_values(self):
    self.ensure_one()  # make sure it is a single record
    # build the values
    return {'partner_id': self.partner_id.id}  # return the dict

# AVOID — an essay: restates the name, walks through the body line by line
def _prepare_invoice_values(self):
    """
    This method prepares and returns the dictionary of values that will later be used
    to create the customer invoice for the current order. First it checks that...
    """
```

JS follows the same rule with a short `/** ... */` block above the method:

```js
/**
 * Make the clicked KPI card's state filter the only active one.
 * Clicking the already active card, or Total, clears them all.
 */
onKpiClick(key) {
```

**Rules:**
- Every method you write or substantially change gets a docstring: a summary line, then
  the *why* only when there is one — business rule, edge case, side effect a caller must
  know. Usually 1–4 lines. Never an essay, never a restatement of the method name.
- Skip the docstring only for a trivial one-liner whose name says everything
  (`action_draft`, a plain `_compute_x` sum).
- Inline comments (`#`, `//`, `<!-- -->`) only when a single line is genuinely
  non-obvious: a workaround, a framework gotcha, a security or transaction reason. One
  short line, explaining *why*.
- No commented-out code, no comments that restate the code, no banner comments.
- Do not add docstrings, comments, or type annotations to code you did not change.

### Method shape

```python
def action_validate(self):
    """Validate selected records."""
    ready = self.filtered_domain([('state', '=', 'draft')])
    if not ready:
        return True

    ready._check_validate_allowed()
    ready.write({'state': 'validated'})
    for record in ready:
        record.message_post(body=_("Validated."))
    return True
```

**Rules:**
- Keep methods short enough to review: select, validate, prepare, write, side effects.
- Name helpers after intent: `_check_*`, `_prepare_*_values`, `_get_*_domain`, `_sync_*`.
- Return Odoo-native values: `True`, action dict, recordset, values dict, or primitive data.
- Do not mix external API payload construction, ORM writes, and UI action building in one large method.

### Exceptions

```python
if not self.env.user.has_group('module.group_manager'):
    raise AccessError(_("Only managers can approve this document."))

if record.state != 'draft':
    raise UserError(_("Only draft records can be approved."))

if float_is_zero(record.quantity, precision_rounding=record.product_uom_id.rounding):
    raise ValidationError(_("Quantity must be greater than zero."))
```

**Rules:**
- `AccessError` for permissions.
- `UserError` for recoverable business-flow blockers.
- `ValidationError` for invalid data/invariants.
- Preserve original exceptions when they indicate security or programming errors.

### Dates, datetimes, and floats

```python
today = fields.Date.context_today(self)
now_utc = fields.Datetime.now()

if float_compare(qty_done, qty_expected, precision_rounding=uom.rounding) < 0:
    ...
```

**Rules:**
- Use `fields.Date.context_today(record)` for user/company-context dates.
- Use `fields.Datetime.now` as a default callable; store datetimes in UTC.
- Never compare floats directly for quantities/currency/UoM.
- Use currency rounding for money and UoM rounding for quantities.

### External calls

```python
def _send_payload(self, payload):
    """Send payload to external service and return parsed response."""
    self.ensure_one()
    try:
        response = self._client().post(payload)
        response.raise_for_status()
    except TimeoutError as exc:
        raise UserError(_("The external service timed out. Try again later.")) from exc
```

**Rules:**
- Keep network calls out of compute/onchange/constraints.
- Use timeouts and idempotency keys for retryable calls.
- Persist enough status to retry safely from cron.
- Never log credentials, tokens, full payloads with PII, or raw response bodies from sensitive services.

### Constants and tooling

```python
# BAD — magic numbers/strings scattered through logic
if order.amount_total > 1000 and order.state == 'sale':
    ...

# GOOD — named constants; frozenset/tuple for fixed collections
LARGE_ORDER_THRESHOLD = 1000.0
CONFIRMED_STATES = frozenset(('sale', 'done'))

if order.amount_total > LARGE_ORDER_THRESHOLD and order.state in CONFIRMED_STATES:
    ...
```

**Rules:**
- Name magic numbers/strings as module-level constants; use `frozenset`/`tuple` for fixed sets, not mutable `list`/`dict`.
- Module-level names must be immutable (see section 13 on global mutable state).
- Format and lint with `ruff format` + `ruff check` before committing — keep style machine-enforced, not hand-argued.

---

## 15. Production Python Review Standard

Use this checklist before considering Odoo Python "high standard":

- The method is honest about recordset size and tested with multiple records when multi is supported.
- Data access is batched; helpers return maps/recordsets instead of forcing caller loops.
- Domains are composed with `Domain` when dynamic.
- x2many commands use `Command`.
- Exceptions are typed: `AccessError`, `UserError`, `ValidationError`, or a re-raised original.
- Logging is lazy and contains record model/id/reference, not sensitive payloads.
- External calls are isolated from compute/onchange/constraints and are retry-safe.
- Manual commits are absent unless the method is a documented resumable worker.
- Raw SQL is justified, parameterized, flushed/invalidated, and recompute-aware.
- Helpers are named by intent and small enough to review without scrolling through unrelated concerns.

---

## 16. Fast, Clean, High-Standard Python

Fast Odoo Python is usually not clever Python. It is code that avoids unnecessary
work, keeps data shapes simple, and lets the ORM/database do the heavy lifting.

### Default standard

```python
from collections import defaultdict


def _prepare_lines_by_product(self):
    """Return order lines grouped by product without extra searches."""
    lines_by_product = defaultdict(lambda: self.env['sale.order.line'])
    for line in self.order_line:
        if line.display_type:
            continue
        lines_by_product[line.product_id] |= line
    return lines_by_product
```

**Rules:**
- Prefer simple loops when they avoid repeated ORM calls or unclear chained expressions.
- Use early `continue` / `return` to avoid nested branches.
- Build maps/sets once; do not recompute the same lookup in every iteration.
- Keep recordsets as recordsets until IDs are required for SQL, RPC, or serialization.
- Avoid "smart" abstractions unless they remove real duplication or make batch behavior safer.

### Collapse redundant branches; keep distinct ones

Merge guards and branches that are the *same* thing written several times; keep
branches that genuinely *differ*. The wins below are behavior-preserving — apply
them; the guardrails after are where merging silently breaks things — respect them.

```python
# BAD — consecutive guards with an identical body
if self.move_type not in ('out_refund', 'in_refund'):
    return
if self.rs_einv_k_type_user_set:
    return
if self.rs_einv_k_type:
    return
self.rs_einv_k_type = self._suggest_k_type()

# GOOD — one guard. `A or B or C` short-circuits exactly like the sequential
# ifs, so a later condition (even one that calls a method) still runs only when
# the earlier ones are False. Identical behavior.
if (self.move_type not in ('out_refund', 'in_refund')
        or self.rs_einv_k_type_user_set
        or self.rs_einv_k_type):
    return
self.rs_einv_k_type = self._suggest_k_type()
```

```python
# BAD — if/else assigns the SAME fields, differing only in which side is seller
if is_buyer_side:
    move.seller_tin = move.partner_id.vat or False
    move.seller_name = move.partner_id.name or False
    move.buyer_tin = move.company_id.vat or False
    move.buyer_name = move.company_id.name or False
else:
    move.seller_tin = move.company_id.vat or False
    move.seller_name = move.company_id.name or False
    move.buyer_tin = move.partner_id.vat or False
    move.buyer_name = move.partner_id.name or False

# GOOD — pick the operands once, assign once
seller, buyer = (
    (move.partner_id, move.company_id) if is_buyer_side
    else (move.company_id, move.partner_id)
)
move.seller_tin = seller.vat or False
move.seller_name = seller.name or False
move.buyer_tin = buyer.vat or False
move.buyer_name = buyer.name or False
```

```python
# BAD — guard then else over one target           # BAD — branches set one field, then continue
flag = getattr(result, 'someResult', None)         for line in self:
if flag is None:                                       if not line.move_id.rs_einv_id:
    success = bool(result)                                 line.state = 'not_sent'
else:                                                       line.synced = False
    success = bool(flag)                                    continue
                                                       ...
# GOOD — value-pick                                 # GOOD — elif over the target; derive the rest once
success = bool(flag if flag is not None else result)  for line in self:
                                                          if not line.move_id.rs_einv_id:
                                                              line.state = 'not_sent'
                                                          elif ...:
                                                              line.state = ...
                                                          else:
                                                              line.state = ...
                                                          line.synced = line.state in SYNCED_STATES
```

**Rules:**
- Merge consecutive `if COND: return` / `continue` / `return X` guards that share an **identical body** into one `if A or B or ...:`. This is *always* behavior-preserving — `or` evaluates in the same order with the same short-circuit as the separate ifs, even when a condition has a side effect or calls a method.
- Collapse if/else that assigns the **same target(s)** differing only by value into a ternary, or a `(a, b) if cond else (c, d)` value-pick, then assign once.
- Turn a single-target guard cascade into one `if/elif/else` chain and compute any **derived** field once after it, instead of repeating that line in every branch.

**Do NOT merge when:**
- **Bodies differ** — guards that `raise` *different* `UserError`/`ValidationError` messages, or branches that set different dict *keys* / different fields / log different text. The specific message and shape is the whole point; keep them separate.
- **Code sits between the guards** — an assignment between two `if`s means they are not consecutive; merging would reorder logic or skip a needed step.
- **Readability drops** — do not fold a long multi-line expression into a trailing `... if cond else x`. A two-line if/else beats a cramped ternary.

### Avoid unnecessary allocations

```python
# BAD — builds a full list just to check existence
has_errors = bool([line for line in self.line_ids if line.state == 'error'])

# GOOD — stops at first match
has_errors = any(line.state == 'error' for line in self.line_ids)

# BAD — builds list then set
partner_ids = set([line.partner_id.id for line in self.line_ids])

# GOOD — one pass
partner_ids = {line.partner_id.id for line in self.line_ids if line.partner_id}
```

**Rules:**
- Use generator expressions for `any()`, `all()`, `sum()`, `min()`, `max()`.
- Use set/dict comprehensions for membership and lookup.
- Do not call `list()` unless you need indexing, reuse, sorting, mutation, or serialization.
- Do not sort unless the order is user-visible, deterministic behavior requires it, or SQL cannot do it.

### Cache local references in hot code

```python
def _prepare_payloads(self):
    """Prepare external payloads with stable local lookups."""
    company = self.env.company
    currency = company.currency_id
    payloads = {}
    for record in self:
        payloads[record.id] = {
            'name': record.name,
            'company_vat': company.vat,
            'currency': currency.name,
        }
    return payloads
```

**Rules:**
- Store repeated environment/model references in local variables in hot loops.
- Create contextualized recordsets once: `Model = self.env['x.model'].with_context(...)`.
- Do not call `with_context()`, `sudo()`, `with_company()`, or `browse()` repeatedly inside loops when one outer recordset works.
- Use `records.fetch([...])` before loops that read a known field set on large recordsets.

### Push filtering and aggregation down

```python
# BAD — loads all records then filters in Python
late = self.search([]).filtered(lambda rec: rec.state == 'late' and rec.company_id == self.env.company)

# GOOD — database filters first
late = self.search([
    ('state', '=', 'late'),
    ('company_id', '=', self.env.company.id),
])
```

**Rules:**
- Use domains for filtering large tables.
- Use `_read_group()` for counts/sums per parent.
- Use `search_fetch()` when you will immediately read known fields from search results.
- Use Python-side `filtered()` only for small/already-loaded sets or conditions not expressible as a domain.

### Keep helper outputs efficient

```python
def _get_existing_refs(self, refs):
    """Return existing external refs as a set for O(1) membership checks."""
    if not refs:
        return set()
    records = self.search_fetch([('external_ref', 'in', list(refs))], ['external_ref'])
    return set(records.mapped('external_ref'))
```

**Rules:**
- Return `set` for membership checks.
- Return `dict` for id/ref to value lookups.
- Return recordsets when caller needs ORM operations.
- Avoid returning lists of single-use dicts when a map makes the next step O(1).

### Avoid hidden expensive work

```python
# BAD — repeated relational traversal inside loop body
for line in lines:
    if line.order_id.partner_id.commercial_partner_id.country_id.code == 'GE':
        ...

# GOOD — prefetch known chains, then loop
lines.mapped('order_id.partner_id.commercial_partner_id.country_id.code')
for line in lines:
    if line.order_id.partner_id.commercial_partner_id.country_id.code == 'GE':
        ...
```

**Rules:**
- Be suspicious of repeated relational chains in large loops.
- Do not call `mapped()` inside another loop unless the inner set is tiny.
- Avoid reading Binary/Html/large Text fields unless needed.
- Avoid `read()` when normal field access or `fetch()` is enough.

### High-standard means no unnecessary code

**Remove or avoid:**
- One-line helpers used once that hide simple logic.
- Broad `try/except Exception` around code that should fail loudly.
- Dead context flags, unused variables, unused imports, placeholder comments.
- Recomputing values that can be prepared once before the loop.
- Logging every record in large batches unless diagnosing a failure.
- Premature raw SQL when a batched ORM pattern is clear and fast enough.

**Keep:**
- Clear names over clever abbreviations.
- Small methods with one responsibility.
- Explicit data shapes: `*_by_id`, `*_by_company`, `*_vals_list`.
- The why in the method docstring; inline comments only for a non-obvious line.

---

## 17. Safe and Performant by Default

The best Odoo Python fails early, validates once, batches work, and avoids
surprising side effects. Safety and performance usually improve together.

### Fail before expensive work

```python
def action_post_to_service(self):
    """Validate records before preparing payloads or calling services."""
    invalid = self.filtered(lambda rec: rec.state != 'ready')
    if invalid:
        raise UserError(_("Only ready records can be sent."))

    missing_partner = self.filtered(lambda rec: not rec.partner_id)
    if missing_partner:
        raise UserError(_("Partner is required before sending."))

    payloads = self._prepare_service_payloads()
    return self._enqueue_service_payloads(payloads)
```

**Rules:**
- Validate state, required fields, access, and company before payload creation.
- Fail before external API calls, attachments, reports, or expensive aggregation.
- Do not partially write records before validation unless the flow is explicitly resumable.

### Avoid quadratic loops

```python
# BAD — O(records * lines)
for order in orders:
    order_lines = lines.filtered(lambda line: line.order_id == order)
    order.total_qty = sum(order_lines.mapped('product_uom_qty'))

# GOOD — one grouping pass
qty_by_order = defaultdict(float)
for line in lines:
    qty_by_order[line.order_id.id] += line.product_uom_qty
for order in orders:
    order.total_qty = qty_by_order[order.id]
```

**Rules:**
- Do not filter the same large recordset inside a loop.
- Build `dict` / `defaultdict` / `set` once, then do O(1) lookups.
- If the data is in the database and grouped totals are needed, prefer `_read_group()`.

### Validate before sudo

```python
def _get_private_attachment_for_portal(self, token):
    """Return sudoed attachment only after public access is proven."""
    self.ensure_one()
    if not self._is_valid_access_token(token):
        raise AccessError(_("Invalid access token."))

    # sudo justified: ownership/token was validated above.
    return self.attachment_id.sudo()
```

**Rules:**
- Never use `sudo()` to make code "work" before understanding access rules.
- Validate user-controlled IDs in non-sudo mode first.
- Keep sudoed recordsets narrow and short-lived.
- Do not pass broad sudoed recordsets into helper methods that may leak data.

### Keep writes intentional

```python
def _mark_processed(self):
    """Mark records processed in one write."""
    to_process = self.filtered_domain([('state', '=', 'ready')])
    if to_process:
        to_process.write({'state': 'processed'})
```

**Rules:**
- Write once per recordset or grouped recordset.
- Do not assign multiple fields one by one when one `write()` works.
- Do not write in `_prepare_*`, `_get_*`, or `_check_*` helpers.
- Do not write in compute/onchange methods except assigning the computed/onchange target fields.

### Keep inputs and outputs boring

```python
def _prepare_vals_by_record_id(self):
    """Return primitive values keyed by source record id."""
    return {
        record.id: {
            'name': record.display_name,
            'partner_id': record.partner_id.id,
        }
        for record in self
    }
```

**Rules:**
- Prefer primitive dict/list/set payloads at integration boundaries.
- Prefer recordsets inside ORM/business logic.
- Name output shape in the method name: `*_by_id`, `*_by_record`, `*_vals_list`.
- Avoid returning mixed shapes like `False | dict | recordset`; they create defensive code everywhere.

### Safe performance review gates

Before approving Python code, reject it if it has:

- `search()`, `search_count()`, `browse(id)`, `with_context()`, `sudo()`, or external API calls inside an avoidable loop.
- Nested loops over recordsets where a `dict`, `set`, `grouped()`, or `_read_group()` would work.
- `ensure_one()` in a method reachable from multi-record actions without a clear reason.
- `try/except Exception` that hides programming, access, or transaction errors.
- `sudo()` before access/company/ownership validation.
- Manual commit without `transactions.md` reasoning.
- Repeated relational chains in a hot path without prefetch/fetch.
- Large `mapped()` / `filtered()` use where a domain or `_read_group()` would be better.
- Helpers that do hidden writes or external calls despite being named `_get_*` or `_prepare_*`.

The target is boring, fast, safe code: validate first, batch data access, write
intentionally, and keep side effects visible.

---

## 18. Caching Model Methods (ormcache)

For pure, frequently-called, rarely-changing lookups (config resolution, permission maps, parsed metadata), cache the result with Odoo's registry-aware cache — never `functools.lru_cache` / `functools.cache`.

```python
from odoo import api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.ormcache('self.env.company.id', 'feature_code')
    def _get_feature_setting(self, feature_code):
        """Return a cached primitive — never a recordset."""
        return self.env['ir.config_parameter'].sudo().get_str(f'mymod.{feature_code}') or False
```

### Why not `lru_cache`
- `lru_cache`/`cache` on a model method keys on `self`, pinning records and an environment/cursor that later closes — stale data across transactions and `psycopg2.InterfaceError` when the cached value is reused.
- It is process-global, never invalidated when the data changes, and not cleared on module upgrade.

### `ormcache` rules
- Arguments are string expressions over the method signature; they build the key (which always also includes `self._name` and the method). Examples: `'model_name'`, `'self.env.uid'`, `'self.env.company.id'`.
- **Never return a recordset** — return ids, dicts, tuples, or scalars, and `browse()` again in the caller. A cached recordset raises `psycopg2.InterfaceError` once its cursor closes.
- Cache only pure functions of the key: no side effects, and no context-sensitive result unless that context value is part of the key.
- **v20 import: `from odoo import api` → `@api.ormcache(...)`.** `odoo.tools.ormcache` still resolves but warns, and `ormcache_context` is gone.
- Invalidate when the underlying data changes: `self.env.transaction.invalidate_ormcache()` (or `invalidate_ormcache('name')` for one bucket). `registry.clear_cache()` was **removed in v20**.
- `@ormcache(skiparg=...)` and `@ormcache_context(...)` are gone — put context values in the key directly, e.g. `@api.ormcache('self.env.context.get("lang")')`.
- Use `@api.ormcache(cache='name')` for a named bucket you can invalidate independently. Core uses `'stable'` for access data and `'groups'` for group implications.
- For a whole small reference table read on nearly every request, `models.CachedModel` does this for you — see `v20-changes.md` section 6.
