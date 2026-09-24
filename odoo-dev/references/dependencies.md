# Dependency & Impact Sweep

Before changing anything that already exists, find out what depends on it. The point is
**not** exhaustive analysis — it is to avoid the one specific failure of changing something
with an override, a caller, or a view inheriting it, that you did not look at.

Size the sweep to the blast radius. Most changes are Tier 1 and take two greps.

---

## Tier 0 — new code only, no sweep

Adding a new model, a new field on our own model, a new method nobody calls yet: just check
the name is free.

```bash
grep -rn "my_new_field" custom_addons/ addons/ enterprise/ --include="*.py" --include="*.xml"
```

Field-name collisions on an inherited model are the only real risk here, and they are
silent: defining `state` on a model that already has `state` replaces it.

---

## Tier 1 — changing our own code (the common case)

Two greps, always:

```bash
# 1. who calls it
grep -rn "\.method_name(\|'method_name'\|\"method_name\"" custom_addons/ --include="*.py" --include="*.xml"

# 2. who overrides it
grep -rn "def method_name\b" custom_addons/ addons/ enterprise/ --include="*.py"
```

For a field, add the view/domain sweep:

```bash
grep -rn "field_name" custom_addons/ --include="*.xml"     # views, domains, reports
grep -rn "'field_name'" custom_addons/ --include="*.py"    # domains, depends, vals
```

Report the count and the hits that matter. If both come back empty, say "no callers or
overrides" and move on — that *is* the sweep.

---

## Tier 2 — overriding or changing core behaviour

Required, in order, before you write the override:

1. **Read the original method in full** — every branch, what it returns, what it writes,
   which context keys it reads.
2. **Find every override** across the three trees:
   ```bash
   grep -rn "def _prepare_invoice\b" addons/ enterprise/ custom_addons/ --include="*.py"
   ```
   (`sale._prepare_invoice` has 8 overrides in `addons/` alone — a change that assumes one
   implementation breaks seven modules.)
3. **Find every caller**:
   ```bash
   grep -rn "_prepare_invoice(" addons/ enterprise/ custom_addons/ --include="*.py"
   ```
4. **Find what inherits the view / template**, if the change touches XML:
   ```bash
   grep -rn 'inherit_id.*view_order_form' addons/ enterprise/ custom_addons/ --include="*.xml"
   ```
5. **List the findings in the answer** — file:line plus one line each on why it is or is
   not affected.
6. **Write the override with `super()` on the normal path.** Change the shortest possible
   branch; never re-implement a method you are extending.

No sweep → no change to core behaviour. This rule has no exception.

### Which extension point

Prefer, in this order:

1. an existing hook (`_prepare_*`, `_get_*`, `_compute_*`, `_search_*`, `_selection_*`)
2. a `@api.depends` on a new field instead of an override
3. `super()` override of the smallest method that exists
4. a new method + a call inserted in a `super()` override
5. rewriting the method — almost always wrong

---

## Tier 3 — module-level impact

When touching a model that other modules extend, or adding a dependency:

```bash
# which modules depend on the one you are changing
grep -rln "'sale'" addons/*/__manifest__.py enterprise/*/__manifest__.py custom_addons/*/__manifest__.py

# which modules extend the model
grep -rn "_inherit = .sale.order." addons/ enterprise/ custom_addons/ --include="*.py"
```

Adding a module to `depends` is a one-way door for the user: it installs apps. Adding a
dependency needs a stated reason and the smallest module that provides what you need
(`account` not `sale_management`, `portal` not `website`).

---

## The precedent search — do it the Odoo way

Every change also needs the *"has Odoo already solved this?"* pass. This is not optional
polish; matching core is what makes our code survive upgrades.

```bash
# find the same kind of field
grep -rn "compute_sql=" addons/ --include="*.py" | head

# find the same kind of button/action
grep -rn "def action_confirm" addons/*/models/*.py | head

# find the same view widget
grep -rn 'widget="badge"' addons/*/views/*.xml | head

# find the same security shape
grep -rn "access.*,,crud," addons/*/security/ir.access.csv | head
```

Rules:

- Find at least one core example of the thing you are about to write, and follow its shape:
  naming, method order, return type, where the logic lives.
- If a change is needed in several places (a field on `sale.order` and on `purchase.order`),
  check how core keeps them consistent and do the same — usually a shared mixin or the same
  method name on both.
- If you cannot find a precedent anywhere in `addons/` or `enterprise/`, that is a signal
  the design is off. Say so and reconsider before writing it.
- Clever, unusual or "elegant" is wrong. Boring and identical to core is right.

---

## Reporting format

Keep it to a few lines in the answer:

```
Sweep: sale.order._prepare_invoice
- overrides: sale_stock:306, l10n_in_sale:75, l10n_it_edi_doi:121 (+5 l10n) — all call super() and only add keys
- callers: _create_invoices() in sale_order.py:1902 only
- views inheriting sale.view_order_form: 14, none touch the invoice button
Change: add one key in the vals dict, super() first. No caller reads the removed key.
```

If a sweep turns up something you cannot resolve, stop and say what it is. Do not guess and
do not "handle it defensively" with a try/except.

---

## What this is not

- Not a reason to read every module that mentions the model
- Not a reason to add abstraction "in case someone overrides it later"
- Not a reason to add defensive checks around your own change
- Not a reason to refactor code you were not asked to touch

Two greps and a sentence is a complete Tier 1 sweep. Ten minutes of grepping is a complete
Tier 2 sweep. Anything longer means the change itself is too big — shrink the change.
