# Controllers & API — Odoo 20

## Table of Contents

1. [Controller Basics](#1-controller-basics)
2. [Route Types](#2-route-types)
3. [JSON-RPC Controllers](#3-json-rpc-controllers)
4. [HTTP Controllers](#4-http-controllers)
5. [JSON-2 External API](#5-json-2-external-api)
6. [Portal Controllers](#6-portal-controllers)
7. [Authentication](#7-authentication)
8. [Input Validation](#8-input-validation)
9. [File Upload / Download](#9-file-upload--download)
10. [Controller Inheritance](#10-controller-inheritance)
11. [Antipatterns](#11-antipatterns)

---

## 1. Controller Basics

Controllers handle HTTP requests. Define them in `controllers/` and import in `controllers/__init__.py`.

```python
# controllers/__init__.py
from . import main

# controllers/main.py
from odoo import http
from odoo.http import request
```

In `__manifest__.py`, no `data` entry is needed — controllers are auto-discovered via the Python import chain.

---

## 2. Route Types

| Type | Content-Type | Use case | CSRF |
|------|-------------|----------|------|
| `type='jsonrpc'` | `application/json` | AJAX calls, OWL components, API | No (session auth) |
| `type='http'` | `text/html` or form data | Web pages, form submissions, downloads | Yes (auto) |

**Route types:** `type='jsonrpc'` (422 core usages) and `type='http'`. `type='json'` is a
deprecated alias — never write it. In v20 `odoo.http` is a package: helpers moved, e.g.
`odoo.http.dispatcher.serialize_exception`.

---

## 3. JSON-RPC Controllers

### Basic pattern:
```python
from odoo import http
from odoo.http import request

class MyController(http.Controller):

    @http.route('/my_module/get_data', type='jsonrpc', auth='user', methods=['POST'])
    def get_data(self, record_id, **kwargs):
        """Fetch record data for authenticated users.

        Args:
            record_id (int): ID of the record to fetch.

        Returns:
            dict: Record data with name and state.
        """
        if not isinstance(record_id, int) or record_id <= 0:
            raise ValueError("Invalid record ID")

        record = request.env['my.model'].browse(record_id)
        record.check_access('read')
        return {
            'id': record.id,
            'name': record.name,
            'state': record.state,
        }
```

### Calling from OWL (frontend):
```javascript
// Using RPC service
const result = await this.rpc("/my_module/get_data", { record_id: 42 });

// Using ORM service (preferred for standard CRUD)
const records = await this.orm.searchRead("my.model", domain, fields);
```

---

## 4. HTTP Controllers

### Page rendering:
```python
@http.route('/my_module/page', type='http', auth='user', website=True)
def my_page(self, **kwargs):
    """Render a web page with record data."""
    records = request.env['my.model'].search([], limit=50)
    return request.render('my_module.my_page_template', {
        'records': records,
    })
```

### Form submission:
```python
@http.route('/my_module/submit', type='http', auth='user', methods=['POST'], website=True)
def submit_form(self, name, email, **post):
    """Handle form submission.

    CSRF token is validated automatically by Odoo for type='http' POST.
    """
    # Validate input
    if not name or not email:
        return request.redirect('/my_module/page?error=missing_fields')

    # Create record
    request.env['my.model'].create({
        'name': name,
        'email': email,
    })
    return request.redirect('/my_module/page?success=1')
```

### Redirect and response:
```python
# Redirect
return request.redirect('/my_module/success')

# JSON response from HTTP route
return request.make_json_response({'status': 'ok'})

# Custom response with headers
return request.make_response(
    csv_content,
    headers=[
        ('Content-Type', 'text/csv'),
        ('Content-Disposition', 'attachment; filename="export.csv"'),
    ],
)
```

---

## 5. JSON-2 External API

The external API. Endpoints follow `/json/2/<model>/<method>`.

Served by the `rpc` module (auto-installed), which also provides `/xmlrpc` and `/jsonrpc` —
[addons/rpc/controllers/json2.py:49](../../../../addons/rpc/controllers/json2.py#L49).

```bash
curl -X POST https://myodoo.com/json/2/res.partner/search_read \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"domain": [["is_company", "=", true]], "fields": ["name", "email"], "limit": 10}'
```

### The contract, exactly

- `POST` only, `auth='bearer'` with `bearer_scope='rpc'` — the key comes from
  `res.users.apikeys` with scope `rpc`
- the body is a **flat JSON object of keyword arguments** — not wrapped in `{"params": ...}`
  like JSON-RPC
- two reserved keys: `ids` (the recordset to call the method on) and `context`
- everything else is bound to the method signature; a mismatch returns 422
- the response is the **raw result**, not a JSON-RPC envelope
- a recordset result is returned as a list of ids
- multi-database servers need an `X-odoo-database` header
- only **public** methods are callable — resolved through `models.get_public_method()`, so
  anything starting with `_` or decorated `@api.private` is a 404
- calling an `@api.model` method with `ids` is a 422
- `ir.access` permissions and restrictions apply as the API key's user, including the
  company restriction

### Key duration
Group-driven via `res.groups.api_key_duration` (days), not a global setting.

### Creating API-friendly methods on models:
```python
class MyModel(models.Model):
    _name = 'my.model'
    _description = 'My Model'

    @api.model
    def api_get_dashboard_data(self, date_from=None, date_to=None):
        """Public API method for dashboard data.

        Designed for external consumption via JSON-2 API.
        Validates parameters and returns a serializable dict.

        Args:
            date_from (str, optional): Start date (YYYY-MM-DD).
            date_to (str, optional): End date (YYYY-MM-DD).

        Returns:
            dict: Dashboard statistics.
        """
        domain = []
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))

        records = self.search(domain)
        return {
            'total': len(records),
            'amount': sum(records.mapped('amount_total')),
            'by_state': dict(
                self._read_group(domain, groupby=['state'], aggregates=['__count'])
            ),
        }
```

---

## 6. Portal Controllers

### Extending the portal:
```python
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request


class MyPortal(CustomerPortal):
    """Portal pages for my module."""

    def _prepare_home_portal_values(self, counters):
        """Add record count to the portal home page."""
        values = super()._prepare_home_portal_values(counters)
        if 'my_model_count' in counters:
            partner = request.env.user.partner_id
            values['my_model_count'] = request.env['my.model'].sudo().search_count([
                ('partner_id', '=', partner.id),
            ])
        return values

    @http.route('/my/records', type='http', auth='user', website=True)
    def portal_my_records(self, sortby=None, **kwargs):
        """List portal user's records."""
        partner = request.env.user.partner_id
        domain = [('partner_id', '=', partner.id)]

        # sudo() justified: portal user has no ACL on my.model,
        # but we pre-filter by their partner_id above
        records = request.env['my.model'].sudo().search(domain, order='date desc')
        return request.render('my_module.portal_my_records', {
            'records': records,
            'page_name': 'my_records',
        })

    @http.route('/my/records/<int:record_id>', type='http', auth='user', website=True)
    def portal_record_detail(self, record_id, **kwargs):
        """Show a single record's detail page.

        CRITICAL: Must verify ownership to prevent IDOR.
        """
        record = request.env['my.model'].sudo().browse(record_id)
        if not record.exists() or record.partner_id != request.env.user.partner_id:
            raise request.not_found()  # 404, not 403 — prevents enumeration
        return request.render('my_module.portal_record_detail', {
            'record': record,
        })
```

### Portal security rules:
- ALWAYS filter by `partner_id` — never trust URL parameters alone
- Return 404 (not 403) when record doesn't belong to user (prevents enumeration)
- Use `sudo()` with ownership filter — portal users have no direct ACL
- Never expose internal fields (cost, margin) in portal templates

---

## 7. Authentication

| Auth type | Who | Use case |
|-----------|-----|----------|
| `auth='user'` | Logged-in internal users | Backend pages, API for employees |
| `auth='public'` | Anyone (logged in or not) | Website pages, public info |
| `auth='none'` | No auth, no `request.env` | Health checks, webhooks |

```python
# Public page (website visitors)
@http.route('/my_module/public', type='http', auth='public', website=True)
def public_page(self, **kwargs):
    """Public page — accessible without login."""
    # request.env.user is the public user if not logged in
    ...

# Webhook with no auth — validate manually
@http.route('/my_module/webhook', type='http', auth='none', csrf=False, methods=['POST'])
def webhook(self, **post):
    """External webhook receiver.

    csrf=False required because external services can't provide CSRF token.
    Must validate request authenticity via shared secret.
    """
    import hmac
    secret = post.get('secret', '')
    expected = request.env['ir.config_parameter'].sudo().get_str('my_module.webhook_secret')
    if not hmac.compare_digest(secret, expected):
        raise Forbidden()
    ...
```

---

## 8. Input Validation

Always validate inputs before processing. Never trust client data.

```python
@http.route('/my_module/update', type='jsonrpc', auth='user', methods=['POST'])
def update_record(self, record_id, values, **kwargs):
    """Update a record with validated input.

    Args:
        record_id (int): Record to update.
        values (dict): Fields to update.
    """
    # Type validation
    if not isinstance(record_id, int) or record_id <= 0:
        raise ValueError("Invalid record ID")
    if not isinstance(values, dict):
        raise ValueError("Values must be a dictionary")

    # Whitelist allowed fields — NEVER pass raw user input to write()
    allowed_fields = {'name', 'description', 'date', 'partner_id'}
    clean_values = {k: v for k, v in values.items() if k in allowed_fields}
    if not clean_values:
        raise ValueError("No valid fields to update")

    # Access check through ORM
    record = request.env['my.model'].browse(record_id)
    record.check_access('write')
    record.write(clean_values)
    return {'success': True}
```

---

## 9. File Upload / Download

### Upload:
```python
@http.route('/my_module/upload', type='http', auth='user', methods=['POST'])
def upload_file(self, file, record_id, **kwargs):
    """Handle file upload and attach to record.

    Args:
        file: Uploaded file object.
        record_id: Target record ID.
    """
    record = request.env['my.model'].browse(int(record_id))
    record.check_access('write')

    attachment = request.env['ir.attachment'].create({
        'name': file.filename,
        'datas': base64.b64encode(file.read()),
        'res_model': 'my.model',
        'res_id': record.id,
    })
    return request.redirect(f'/my/records/{record_id}')
```

### Download:
```python
@http.route('/my_module/download/<int:record_id>', type='http', auth='user')
def download_report(self, record_id, **kwargs):
    """Download a record's PDF report."""
    record = request.env['my.model'].browse(record_id)
    record.check_access('read')

    pdf_content, _ = request.env['ir.actions.report']._render_qweb_pdf(
        'my_module.action_report_my_model', [record_id]
    )
    return request.make_response(
        pdf_content,
        headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="{record.name}.pdf"'),
        ],
    )
```

---

## 10. Controller Inheritance

### Extending an existing controller:
```python
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleCustom(WebsiteSale):
    """Extend the website sale controller."""

    @http.route()  # Empty route() inherits parent's route definition
    def shop(self, page=0, category=None, search='', **post):
        """Override shop page to add custom logic."""
        response = super().shop(page=page, category=category, search=search, **post)
        # Add custom values to the response
        response.qcontext['custom_banner'] = 'Welcome!'
        return response
```

### Key rules:
- Use `@http.route()` with no arguments to inherit the parent route
- Always call `super()` unless you're completely replacing behavior
- Access `response.qcontext` to add template variables to existing responses

---

## 11. Antipatterns

### DO NOT use `type='json'` in new code:
```python
# WRONG (deprecated alias)
@http.route('/api/data', type='json', auth='user')

# CORRECT
@http.route('/api/data', type='jsonrpc', auth='user', methods=['POST'])
```

### DO NOT pass raw user input to ORM write/create:
```python
# WRONG — mass assignment vulnerability
@http.route('/api/update', type='jsonrpc', auth='user', methods=['POST'])
def update(self, record_id, **kwargs):
    request.env['my.model'].browse(record_id).write(kwargs)  # DANGEROUS

# CORRECT — whitelist fields
def update(self, record_id, name=None, description=None, **kwargs):
    vals = {}
    if name is not None:
        vals['name'] = name
    if description is not None:
        vals['description'] = description
    request.env['my.model'].browse(record_id).write(vals)
```

### DO NOT disable CSRF without alternative auth:
```python
# WRONG — anyone can POST
@http.route('/api/action', type='http', auth='public', csrf=False, methods=['POST'])
def action(self, **post):
    ...  # No verification at all

# CORRECT — validate via secret/signature
@http.route('/webhook', type='http', auth='none', csrf=False, methods=['POST'])
def webhook(self, **post):
    if not self._verify_webhook_signature(post):
        raise Forbidden()
    ...
```

### DO NOT return recordsets from controllers:
```python
# WRONG — recordsets are not JSON serializable
@http.route('/api/partners', type='jsonrpc', auth='user', methods=['POST'])
def get_partners(self, **kwargs):
    return request.env['res.partner'].search([])  # CRASH

# CORRECT — return serializable data
def get_partners(self, **kwargs):
    partners = request.env['res.partner'].search_read(
        [], ['name', 'email'], limit=100
    )
    return partners  # list of dicts
```

### DO NOT forget access checks in controllers:
```python
# WRONG — no access verification
def get_record(self, record_id, **kwargs):
    record = request.env['my.model'].sudo().browse(record_id)
    return {'name': record.name}  # Leaks data

# CORRECT — verify access or filter by user
def get_record(self, record_id, **kwargs):
    record = request.env['my.model'].browse(record_id)
    record.check_access('read')  # raises AccessError if denied
    return {'name': record.name}
```
