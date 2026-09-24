# Simplicity Law — Odoo 20

Ranked above every other reference file. If a rule here conflicts with a pattern in
`orm.md`, `sql.md`, `scaffold.md` or any other reference, this file wins.

The goal of a task is **the smallest correct change that a user and a developer both
understand on first read**. Not the most complete solution. Not the most defensive one.

---

## 1. Smallest change that works

Before writing code, answer: *what is the least I can touch?*

Ranked options — always take the highest one that solves the task:

1. Configuration / existing field or setting — no code
2. Extend an existing method or view on an existing model
3. Add a field or a method to an existing model
4. New model / wizard / view  ← needs a reason, state it
5. New module  ← needs a reason, state it

Never invent a model, wizard, menu, or setting the task did not require. A new model is
a permanent cost for the user (new menu, new access rules, new records to maintain).

## 2. No overthinking

- Solve the case in front of you, not the imagined future one
- No abstraction layer, hook, or generic engine for a single caller
- No configuration field for something with one sane value — hardcode the sane value
- If the simple version fails only in a case that cannot happen in this DB, ship the simple version

## 3. Proof, never guessing

Every claim about Odoo behavior must be backed by one of:

- a source file + line you actually read
- a `psql SELECT` result
- a test run output

If none exists, say so in plain words: *"not verified — this is my assumption."*
Never present an inferred field name, method name, or flow as fact. Never invent a
field, method, module, or option that you have not seen in the source.

## 4. Touching anything that already exists

Changing an existing method, field or view requires a dependency sweep first. Full procedure
and grep recipes: `dependencies.md`. The short version:

1. Read the original fully — every branch, every return, every side effect
2. `grep` every caller and every override in `addons/`, `enterprise/`, `custom_addons/`
3. `grep` every view that inherits it, if XML is involved
4. State the findings in the answer, then write the override with `super()` on the normal path

If step 2 was not done, do not change existing behavior. Prefer the extension point Odoo
already gives (a hook method, `_prepare_*`, a compute dependency) over rewriting a method.

The sweep is bounded: two greps and a sentence is a complete sweep for our own code. It is
there to catch the one override you did not know about, not to justify an audit.

## 5. Do it the Odoo way

Before inventing anything: find the same thing in `addons/` or `enterprise/` and copy the
pattern. This is not style advice — matching core is what keeps our code working across
upgrades.

- Naming: `action_*` for buttons, `_compute_*`, `_prepare_*`, `_get_*`, `_check_*`
- Wizard = `TransientModel` with one `action_*` confirm method
- Status = `Selection` `state` field, not booleans
- Reuse standard flows (accounting entries, payments, stock moves) — never hand-write GL,
  never bypass the ORM to shortcut a standard flow
- When a change has to land in several places, look at how core keeps those places
  consistent (a shared mixin, the same method name on both models) and do the same
- If you cannot find a single precedent anywhere in `addons/` or `enterprise/`, say so and
  reconsider the design before writing it

If the solution looks strange or clever, it is wrong. Find the boring Odoo equivalent.

## 5b. Multi-company is part of "correct"

A model holding business data without `company_id`, without `check_company=True` on its
scoped relations, and without a company restriction row is not a simpler solution — it is a
broken one. Simplicity never means dropping the company dimension. `multicompany.md`.

## 6. One place for the user

Anything the user must do to complete one business action belongs in **one place**.

- No flow that needs several menus, tabs, or records to finish one action
- Add the button, field, or smart button on the record the user is already looking at
- Do not create a second model to hold data that belongs on an existing one
- Do not duplicate a value into a new field when a `related` field or existing one is there
- Do not add a second method that does what an existing method already does — extend it

Test the design with: *"how many screens to finish this?"* More than one or two — redesign.

## 7. Few validations, few messages

- Block only what actually corrupts data or accounting
- One clear error at the real boundary (confirm / post / send), not on every write
- Never raise on something the user can obviously see and fix themselves
- No warning popups for normal work, no confirmation dialog on a reversible action
- Prefer making the wrong value impossible (domain, `readonly`, default) over raising an error
- Never add two constraints that fail on the same bad input

Error text: one sentence, says what to do next. Wrapped in `self.env._()`.

## 8. Clean but small code

Organized does not mean layered.

- One method, one job; short enough to read without scrolling
- Group by concern in the standard layout: `models/`, `views/`, `security/`, `wizard/`
- No dead code, no commented-out code, no unused imports, no leftover helper
- Explanations go in the method docstring (what it does and why, 1–4 lines), not in
  inline comments; skip it only for a trivial one-liner whose name says everything
- Inline comments only for a genuinely non-obvious line; never one that restates the code

## 9. Never do these

| Do not | Instead |
|---|---|
| Write a migration script | Solve it in code (compute, default, fill-only-if-empty pass) |
| Bump `version` in `__manifest__.py` | Leave it — the user decides releases |
| Add a model/wizard/menu that was not requested | Extend what exists |
| Add a setting with one realistic value | Hardcode it |
| Add tests, a `README`, or docs on your own | Ask first — say what you would cover |
| Rewrite a core method | Use `super()` + the existing hook |
| Duplicate a field's data | `related=` or read the source field |
| Add validation "just in case" | Only block real data corruption |
