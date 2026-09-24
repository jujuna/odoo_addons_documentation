# Multi-Company — Odoo 20

**Default assumption: every model we build is multi-company.** Single-company is the
exception and needs a stated reason. A model that leaks records across companies is a data
breach, not a bug — it is the most expensive class of mistake in this codebase, and the
cheapest to prevent.

Odoo 20 also has **branch companies**: companies form a tree (`parent_id`, `parent_path`,
`root_id`), so "the same company" often means "this company or one of its parents" —
[odoo/addons/base/models/res_company.py:88](../../../../odoo/addons/base/models/res_company.py#L88).

1. [The four things every model needs](#1-the-four-things-every-model-needs)
2. [Company vs companies](#2-company-vs-companies)
3. [The restriction row](#3-the-restriction-row)
4. [`check_company` and consistency](#4-check_company-and-consistency)
5. [Branch companies](#5-branch-companies)
6. [`company_dependent` fields](#6-company_dependent-fields)
7. [Writing across companies](#7-writing-across-companies)
8. [Shared records (`company_id = False`)](#8-shared-records-company_id--false)
9. [Cron, sudo and background jobs](#9-cron-sudo-and-background-jobs)
10. [Review checklist](#10-review-checklist)

---

## 1. The four things every model needs

```python
class MyModel(models.Model):
    _name = 'my.model'
    _description = "My Model"
    _check_company_auto = True          # 3. auto-verify on create/write

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,     # 1. the column
    )
    partner_id = fields.Many2one('res.partner', check_company=True)   # 2. scoped relations
    journal_id = fields.Many2one('account.journal', check_company=True)
```

```csv
my_model_comp_rule,My Model multi-company,my.model,,crud,"[('company_id', 'in', company_ids)]"
```
4. the restriction row in `security/ir.access.csv` — empty `group_id`.

Missing any one of the four leaves a hole:

| Missing | What breaks |
|---|---|
| `company_id` | records are global; every user of every company sees them |
| restriction row | the column exists but nothing filters on it |
| `check_company=True` | a record in company A can point at a journal of company B |
| `_check_company_auto` | `check_company=True` is declared but never enforced |

---

## 2. Company vs companies

| Expression | Meaning | Use it for |
|---|---|---|
| `self.env.company` | the **active** company (first of `allowed_company_ids`) | defaults, new-record ownership, currency, config |
| `self.env.companies` | every company currently **enabled** in the switcher | domains, restrictions, "what can I see" |
| `self.env.user.company_ids` | every company the user is **allowed** to enable | permission questions only |
| `self.env.user.company_id` | the user's default company | **do not use in business logic** |

`self.env.user.company_id` ignores the company switcher, so code using it silently reads
the wrong company whenever the user switches. In the `ir.access` domain language these map
to `company_id` and `company_ids` —
[ir_access.py:`_eval_context`](../../../../odoo/addons/base/models/ir_access.py#L312).

---

## 3. The restriction row

A multi-company rule is an `ir.access` row with an **empty `group_id`**. Empty group means
restriction: it is AND-ed for every user, so no group can escape it.

```csv
id,name,model_id,group_id/id,operation,domain
my_model_comp_rule,My Model multi-company,my.model,,crud,"[('company_id', 'in', company_ids)]"
```

The three shapes used in core, and when each applies:

| Domain | Meaning | Example in core |
|---|---|---|
| `[('company_id', 'in', company_ids)]` | strict: only records of enabled companies | `sale.order`, `account.move` |
| `['\|', ('company_id', '=', False), ('company_id', 'parent_of', company_ids)]` | shared records + own branch tree | `account.cash.rounding` |
| `[('company_ids', 'parent_of', company_ids)]` | model with a company **M2M** | `account.account` |

See [addons/account/security/ir.access.csv](../../../../addons/account/security/ir.access.csv)
lines 4–90 for the full set.

One restriction row covers `crud` — do not write four rows.

---

## 4. `check_company` and consistency

`check_company=True` on a relational field means: the target record must belong to a
compatible company. `_check_company_auto = True` makes `create()` and `write()` run that
check — [models.py:3351](../../../../odoo/orm/models.py#L3351).

It does two things:

- **validation**: raises `UserError` when a record in company A links to a record of
  company B
- **UI**: injects the company domain into the field's domain, so the dropdown only offers
  valid records — [fields_relational.py:127](../../../../odoo/orm/fields_relational.py#L127)

Default compatibility rule is `company_id in companies + [False]`
([models.py:3339](../../../../odoo/orm/models.py#L3339)). Override it per model when the
record must be usable by child companies:

```python
class AccountJournal(models.Model):
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of
```

| Helper | Accepts a record whose… |
|---|---|
| default | `company_id` is False or in the given companies |
| `models.check_company_domain_parent_of` | `company_id` is False or a **parent** of the given companies |
| `models.check_companies_domain_parent_of` | `company_ids` contains a parent of the given companies |

Set `check_company=True` on every M2O pointing at company-scoped data: partner bank,
journal, account, warehouse, pricelist, analytic account, tax, product-with-company. Do
not set it on genuinely global data (country, currency, uom, language).

---

## 5. Branch companies

Companies are a tree. A record owned by a parent is usable by its branches; the reverse is
never true.

- `parent_id`, `child_ids`, `all_child_ids`, `parent_ids`, `root_id`, `parent_path` on
  `res.company`
- domain operators: `('company_id', 'parent_of', company_ids)` and
  `('company_id', 'child_of', ...)`
- `parent_of` is what the two `check_company_domain_*` helpers expand to, using
  `parent_path`

Rule of thumb: configuration and master data (journals, accounts, taxes, payment terms)
use `parent_of` so a branch inherits the parent's setup. Transactional documents (orders,
invoices, moves) use plain `in company_ids` so they stay in their own company.

---

## 6. `company_dependent` fields

A `company_dependent=True` field stores **one value per company** in a property, not one
value per record.

```python
property_account_income_categ_id = fields.Many2one(
    'account.account', company_dependent=True, check_company=True,
)
```

- the value read is the one for `self.env.company`
- `check_company` on a company-dependent field validates against `self.env.company`, not
  against `record.company_id` — [models.py:3409](../../../../odoo/orm/models.py#L3409)
- it is the right tool for *configuration attached to a shared record* (a product's income
  account), and the wrong tool for a value that is part of the document itself

---

## 7. Writing across companies

When one action touches several companies, group by company and switch explicitly:

```python
for company, records in self.grouped('company_id').items():
    records.with_company(company)._do_the_thing()
```

`with_company(company)` sets `env.company = company` and puts it first in `env.companies`
— [models.py:5468](../../../../odoo/orm/models.py#L5468). Use it whenever the code reads a
company-dependent field, a currency, a sequence, or a config parameter while processing
records of another company.

Never build cross-company logic on `self.env.company` inside a loop over mixed records:
the first record silently decides the currency for all of them.

---

## 8. Shared records (`company_id = False`)

`company_id = False` means "belongs to every company". Use it only for genuine master data
the user is expected to share (a payment term, a product category). When a model allows it:

- the restriction domain must include the `'|', ('company_id', '=', False)` branch
- `required=True` on `company_id` and shared records are mutually exclusive — pick one
- a shared record must never point at a company-scoped record; `check_company` enforces
  this in the right direction automatically

---

## 9. Cron, sudo and background jobs

`sudo()` bypasses `ir.access` **including the multi-company restriction**. Any sudo call on
a company-scoped model must re-add the filter by hand:

```python
# sudo: cron runs as root and has no company switcher
orders = self.env['sale.order'].sudo().search([
    ('company_id', 'in', companies.ids),
    ('state', '=', 'sale'),
])
```

Cron jobs start with no `allowed_company_ids`, so `env.companies` is the cron user's
companies. A cron that must act per company iterates explicitly:

```python
for company in self.env['res.company'].sudo().search([]):
    self.with_company(company)._process_company()
```

---

## 10. Review checklist

- [ ] `company_id` exists, `index=True`, with a `self.env.company` default
- [ ] restriction row in `ir.access.csv` (empty `group_id`) with the right domain shape
- [ ] `_check_company_auto = True` when any field has `check_company=True`
- [ ] every company-scoped M2O has `check_company=True`
- [ ] `_check_company_domain` overridden when branches must inherit the record
- [ ] no `self.env.user.company_id` in business logic
- [ ] loops over mixed-company recordsets use `grouped('company_id')` + `with_company`
- [ ] every `sudo()` on a company-scoped model re-applies the company filter
- [ ] monetary fields resolve their currency from the record's company, not `env.company`,
      when the record belongs to another company
- [ ] the cron/import path sets the company explicitly instead of inheriting the caller's
