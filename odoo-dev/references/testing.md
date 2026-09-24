# Testing — Odoo 20

**Tests are not automatic. Ask first.** Before writing any test, tell the user which
behaviors you would cover and let them decide. Push for a yes when the change touches
security, money, or a state machine; accept a no everywhere else. Never create a `tests/`
folder on your own initiative.

This file is what to do once the user says yes.

## Table of Contents

1. [Test Class Types](#1-test-class-types)
2. [Test Data Setup](#2-test-data-setup)
3. [Form Simulation](#3-form-simulation)
4. [Access Rights Testing](#4-access-rights-testing)
5. [Testing Compute and Constraints](#5-testing-compute-and-constraints)
6. [Mocking Patterns](#6-mocking-patterns)
7. [HTTP and Controller Testing](#7-http-and-controller-testing)
8. [Tour Testing](#8-tour-testing)
9. [Test Assertions](#9-test-assertions)
10. [Running Tests](#10-running-tests)
11. [Antipatterns](#11-antipatterns)

---

## 1. Test Class Types

| Class | Use case | DB behavior |
|-------|----------|-------------|
| `TransactionCase` | Most tests | Rollback after each test method |
| `HttpCase` | Controller/tour tests | Rollback after each test method, HTTP server |
| `SingleTransactionCase` | Tests sharing state | Single transaction for ALL methods (rarely needed) |

### Tags and decorators:

```python
from odoo.tests import tagged, TransactionCase

# Default: runs at install time
@tagged('post_install', '-at_install')  # run only after all modules installed
class TestMyModel(TransactionCase):
    ...

@tagged('at_install')  # default — runs during module install
class TestMyModelInstall(TransactionCase):
    ...

@tagged('post_install', '-at_install', 'my_custom_tag')
class TestSpecific(TransactionCase):
    ...
```

**Tag rules:**
- `at_install` — runs during module installation (default)
- `post_install` — runs after all modules are installed
- `-at_install` — exclude from install-time tests
- Custom tags can be used for filtering: `--test-tags my_custom_tag`
- Use `post_install` for tests that depend on other modules being fully loaded

---

## 2. Test Data Setup

### setUpClass pattern (preferred):
```python
from odoo.tests import TransactionCase, tagged
from odoo import Command


@tagged('post_install', '-at_install')
class TestSaleOrder(TransactionCase):
    """Tests for custom sale order logic."""

    @classmethod
    def setUpClass(cls):
        """Set up test data shared across all test methods."""
        super().setUpClass()

        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'email': 'test@example.com',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
            'type': 'consu',
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [
                Command.create({
                    'product_id': cls.product.id,
                    'product_uom_qty': 5,
                }),
            ],
        })
```

### Command helpers for relational fields:
```python
from odoo import Command

# Create a linked record
Command.create({'name': 'Line 1', 'quantity': 5})  # (0, 0, vals)

# Link an existing record
Command.link(record.id)  # (4, id, 0)

# Replace all links
Command.set([id1, id2, id3])  # (6, 0, [ids])

# Unlink (remove relation, don't delete)
Command.unlink(record.id)  # (3, id)

# Delete the related record
Command.delete(record.id)  # (2, id)

# Clear all links
Command.clear()  # (5, 0)

# Update a linked record
Command.update(record.id, {'quantity': 10})  # (1, id, vals)
```

### Using existing demo data:
```python
@classmethod
def setUpClass(cls):
    super().setUpClass()
    # Reference demo/test data by XML ID
    cls.partner = cls.env.ref('base.res_partner_2')
    cls.user_demo = cls.env.ref('base.user_demo')
    cls.company = cls.env.ref('base.main_company')
```

---

## 3. Form Simulation

The `Form` helper simulates the UI form — triggers `onchange`, `default_get`,
and compute methods exactly as the web client does.

### Basic usage:
```python
from odoo.tests.common import Form

def test_onchange_partner_sets_address(self):
    """Test that selecting a partner fills the address fields."""
    form = Form(self.env['sale.order'])
    form.partner_id = self.partner
    # After setting partner_id, onchange has fired
    self.assertEqual(form.partner_invoice_id, self.partner)

    # Save the form to create the record
    order = form.save()
    self.assertEqual(order.partner_id, self.partner)
```

### Editing an existing record:
```python
def test_update_quantity(self):
    """Test updating quantity recalculates totals."""
    form = Form(self.order)
    with form.order_line.edit(0) as line:
        line.product_uom_qty = 10
    order = form.save()
    self.assertEqual(order.order_line.product_uom_qty, 10)
```

### One2many manipulation:
```python
def test_add_order_line(self):
    """Test adding a line via form simulation."""
    form = Form(self.order)

    # Add a new line
    with form.order_line.new() as line:
        line.product_id = self.product
        line.product_uom_qty = 3

    # Edit existing line (by index)
    with form.order_line.edit(0) as line:
        line.product_uom_qty = 7

    # Remove a line (by index)
    form.order_line.remove(1)

    order = form.save()
    self.assertEqual(len(order.order_line), 1)
```

### Form with specific view:
```python
def test_with_specific_view(self):
    """Test using a specific form view (for visibility conditions)."""
    form = Form(
        self.env['sale.order'],
        view='sale.view_order_form',
    )
    form.partner_id = self.partner
    order = form.save()
```

---

## 4. Access Rights Testing

### Testing with specific users:
```python
@classmethod
def setUpClass(cls):
    super().setUpClass()

    # Create test users with specific groups
    cls.sale_user = cls.env['res.users'].create({
        'name': 'Sale User',
        'login': 'sale_user_test',
        'group_ids': [
            Command.set([
                cls.env.ref('sales_team.group_sale_salesman').id,
                cls.env.ref('base.group_user').id,
            ]),
        ],
    })
    cls.sale_manager = cls.env['res.users'].create({
        'name': 'Sale Manager',
        'login': 'sale_manager_test',
        'group_ids': [
            Command.set([
                cls.env.ref('sales_team.group_sale_salesman_all_leads').id,
                cls.env.ref('base.group_user').id,
            ]),
        ],
    })

def test_user_cannot_delete(self):
    """Test that a regular user cannot delete confirmed orders."""
    self.order.action_confirm()
    with self.assertRaises(AccessError):
        self.order.with_user(self.sale_user).unlink()

def test_user_can_read_own_records(self):
    """Test record rule: user sees only their own records."""
    self.order.user_id = self.sale_user
    # User can read their own order
    order = self.order.with_user(self.sale_user)
    order.read(['name'])  # should not raise

def test_user_cannot_read_others_records(self):
    """Test record rule: user cannot see other's records."""
    self.order.user_id = self.sale_manager
    with self.assertRaises(AccessError):
        self.order.with_user(self.sale_user).read(['name'])
```

### Testing access explicitly (v20 API):
```python
def test_access_permissions(self):
    order = self.order.with_user(self.sale_user)
    order.check_access('read')            # raises AccessError on failure
    order.check_access('write')
    self.assertFalse(order.has_access('unlink'))
    with self.assertRaises(AccessError):
        order.check_access('unlink')

def test_access_subset(self):
    orders = self.orders.with_user(self.sale_user)
    self.assertEqual(orders._filtered_access('write'), self.own_orders)
```

`check_access_rights()`, `check_access_rule()` and `_filter_access_rules()` were removed in
v20 — use `check_access()`, `has_access()` and `_filtered_access()`. All three return
"allowed" under `sudo()`, so always call them on a `with_user(...)` recordset.

### Testing the multi-company restriction

```python
def test_other_company_is_invisible(self):
    user = self.sale_user.with_company(self.company_b)
    with self.assertRaises(AccessError):
        self.order_company_a.with_user(user).check_access('read')
```

A model with a company restriction row deserves this test more than it deserves a happy-path
compute test.

---

## 5. Testing Compute and Constraints

### Testing computed fields:
```python
def test_compute_amount_total(self):
    """Test that amount_total is correctly computed from lines."""
    self.env['sale.order.line'].create({
        'order_id': self.order.id,
        'product_id': self.product.id,
        'product_uom_qty': 2,
        'price_unit': 50.0,
    })
    # Computed fields update automatically after create
    self.assertAlmostEqual(self.order.amount_total, 100.0, places=2)
```

### Testing constraints:
```python
def test_constraint_positive_quantity(self):
    """Test that negative quantity raises ValidationError."""
    with self.assertRaises(ValidationError):
        self.env['sale.order.line'].create({
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_uom_qty': -1,
        })

def test_constraint_unique_reference(self):
    """Test that duplicate reference raises IntegrityError."""
    from psycopg2 import IntegrityError
    with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
        self.env['my.model'].create({'reference': self.record.reference})
```

### Testing state transitions:
```python
def test_workflow_draft_to_done(self):
    """Test complete workflow: draft -> confirmed -> done."""
    self.assertEqual(self.order.state, 'draft')

    self.order.action_confirm()
    self.assertEqual(self.order.state, 'confirmed')

    self.order.action_done()
    self.assertEqual(self.order.state, 'done')

def test_cannot_confirm_from_done(self):
    """Test invalid state transition raises UserError."""
    self.order.action_confirm()
    self.order.action_done()
    with self.assertRaises(UserError):
        self.order.action_confirm()
```

---

## 6. Mocking Patterns

### Mocking external API calls:
```python
from unittest.mock import patch, MagicMock

def test_external_api_call(self):
    """Test behavior when external API returns success."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'status': 'ok'}

    with patch('odoo.addons.my_module.models.my_model.requests.post',
               return_value=mock_response):
        result = self.record.action_sync_external()
        self.assertEqual(self.record.sync_status, 'synced')

def test_external_api_failure(self):
    """Test behavior when external API fails."""
    with patch('odoo.addons.my_module.models.my_model.requests.post',
               side_effect=ConnectionError("Timeout")):
        with self.assertRaises(UserError):
            self.record.action_sync_external()
```

### Freezing time:
```python
from freezegun import freeze_time

@freeze_time('2026-03-14')
def test_date_dependent_logic(self):
    """Test logic that depends on current date."""
    self.record.date = '2026-03-13'  # yesterday
    self.assertTrue(self.record.is_overdue)

    self.record.date = '2026-03-15'  # tomorrow
    self.assertFalse(self.record.is_overdue)
```

### Muting loggers (suppress expected warnings):
```python
from odoo.tools import mute_logger

def test_expected_error_logged(self):
    """Test error handling that logs warnings."""
    with mute_logger('odoo.addons.my_module.models.my_model'):
        self.record.action_risky()
```

### Mocking mail sending:
```python
def test_email_sent_on_confirm(self):
    """Test that confirmation sends an email."""
    with self.mock_mail_gateway():
        self.order.action_confirm()
    # Check that mail was "sent"
    mail = self.env['mail.mail'].search([
        ('res_id', '=', self.order.id),
        ('model', '=', 'sale.order'),
    ])
    self.assertTrue(mail)
```

---

## 7. HTTP and Controller Testing

### HttpCase basics:
```python
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestMyController(HttpCase):
    """Test HTTP controllers."""

    def test_json_endpoint(self):
        """Test JSON-RPC endpoint returns expected data."""
        self.authenticate('admin', 'admin')
        response = self.url_open(
            '/my_module/get_data',
            data=json.dumps({'jsonrpc': '2.0', 'params': {'record_id': 1}}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn('result', result)

    def test_http_page(self):
        """Test HTTP page renders correctly."""
        self.authenticate('admin', 'admin')
        response = self.url_open('/my_module/page')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Expected Content', response.content)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated access is rejected."""
        response = self.url_open('/my_module/get_data')
        # Should redirect to login
        self.assertEqual(response.status_code, 303)
```

### Authentication:
```python
# Login as specific user
self.authenticate('sale_user_test', 'sale_user_test')

# Login as admin
self.authenticate('admin', 'admin')

# No authentication (public user)
self.authenticate(None, None)
```

---

## 8. Tour Testing

### Running a JS tour:
```python
@tagged('post_install', '-at_install')
class TestMyTour(HttpCase):
    """Test UI tours."""

    def test_my_feature_tour(self):
        """Test the feature tour runs successfully."""
        self.start_tour(
            '/odoo/my-module',      # URL to start at
            'my_module_tour',       # tour name
            login='admin',
        )
```

### Defining a tour (JS):
```javascript
/** @odoo-module */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("my_module_tour", {
    url: "/odoo/my-module",
    steps: () => [
        {
            trigger: ".o_list_button_add",
            content: "Click Create button",
            run: "click",
        },
        {
            trigger: "div.o_field_widget[name='name'] input",
            content: "Enter a name",
            run: "edit Test Record",
        },
        {
            trigger: ".o_form_button_save",
            content: "Save the record",
            run: "click",
        },
        {
            trigger: ".o_statusbar_status button:contains('Confirm')",
            content: "Confirm the record",
            run: "click",
        },
    ],
});
```

---

## 9. Test Assertions

### Common Odoo assertions:
```python
# Record count
self.assertEqual(len(records), 3)
self.assertFalse(records)  # empty recordset
self.assertTrue(records)   # non-empty recordset

# Float comparison (respects precision)
from odoo.tools import float_compare
self.assertEqual(float_compare(1.005, 1.01, precision_digits=2), 0)
self.assertAlmostEqual(record.amount, 100.0, places=2)

# Record values (bulk assertion)
self.assertRecordValues(order.order_line, [
    {'product_id': product_a.id, 'product_uom_qty': 5},
    {'product_id': product_b.id, 'product_uom_qty': 3},
])

# Exception testing
with self.assertRaises(UserError):
    record.action_dangerous()

with self.assertRaises(ValidationError):
    self.env['my.model'].create({'bad_field': -1})

with self.assertRaises(AccessError):
    record.with_user(limited_user).write({'state': 'done'})

# String content
self.assertIn('expected', record.description)
self.assertNotIn('secret', response.content.decode())
```

### assertRecordValues — batch record assertion:
```python
def test_line_values(self):
    """Test multiple record values at once."""
    self.assertRecordValues(
        self.order.order_line.sorted('sequence'),
        [
            {
                'product_id': self.product_a.id,
                'product_uom_qty': 5.0,
                'price_unit': 100.0,
                'price_total': 500.0,
            },
            {
                'product_id': self.product_b.id,
                'product_uom_qty': 2.0,
                'price_unit': 50.0,
                'price_total': 100.0,
            },
        ],
    )
```

---

## 10. Running Tests

### CLI commands:
```bash
# Run all tests for a module
./odoo-bin -d mydb -i my_module --test-enable --stop-after-init

# Run tests for an already-installed module
./odoo-bin -d mydb -u my_module --test-enable --stop-after-init

# Run specific test tags
./odoo-bin -d mydb --test-tags /my_module

# Run a specific test class
./odoo-bin -d mydb --test-tags /my_module:TestMyModel

# Run post_install tests only
./odoo-bin -d mydb --test-tags post_install

# Run with a custom tag
./odoo-bin -d mydb --test-tags my_custom_tag

# Exclude slow tests
./odoo-bin -d mydb --test-tags /my_module,-slow
```

### Test tag format:
```
[/module_name][:TestClassName][.test_method_name]

Examples:
  /my_module                          — all tests in my_module
  /my_module:TestSaleOrder            — specific test class
  /my_module:TestSaleOrder.test_confirm — specific test method
  post_install                        — all post_install tagged tests
```

---

## 11. Antipatterns

### DO NOT test implementation details:
```python
# BAD — tests internal method call, breaks on refactor
def test_confirm_calls_internal(self):
    with patch.object(MyModel, '_internal_method') as mock:
        self.record.action_confirm()
        mock.assert_called_once()

# GOOD — tests the observable outcome
def test_confirm_changes_state(self):
    self.record.action_confirm()
    self.assertEqual(self.record.state, 'confirmed')
```

### DO NOT create data in test methods when it can be in setUpClass:
```python
# BAD — creates same data in every test method
def test_feature_a(self):
    partner = self.env['res.partner'].create({'name': 'Test'})
    ...

def test_feature_b(self):
    partner = self.env['res.partner'].create({'name': 'Test'})
    ...

# GOOD — shared in setUpClass
@classmethod
def setUpClass(cls):
    super().setUpClass()
    cls.partner = cls.env['res.partner'].create({'name': 'Test'})
```

### DO NOT forget to test error paths:
```python
# INCOMPLETE — only tests happy path
def test_confirm(self):
    self.record.action_confirm()
    self.assertEqual(self.record.state, 'confirmed')

# COMPLETE — tests both success and failure
def test_confirm_success(self):
    self.record.action_confirm()
    self.assertEqual(self.record.state, 'confirmed')

def test_confirm_already_confirmed_raises(self):
    self.record.action_confirm()
    with self.assertRaises(UserError):
        self.record.action_confirm()
```

### DO NOT modify setUpClass data in tests:
```python
# BAD — modifies shared data, breaks other tests
def test_something(self):
    self.partner.write({'name': 'Changed'})  # affects all subsequent tests!

# GOOD — create a copy or use fresh data
def test_something(self):
    partner = self.partner.copy({'name': 'Changed'})
    ...
```
