# Documentation Template — Odoo Business Module

Use this structure for every module documentation file.
Replace all `<placeholders>` with real content. Delete sections that don't apply.

The documentation serves one primary goal: **help the reader understand the module** —
what it does, why it exists, how it works end-to-end, and when to use it.

This is NOT a field catalog or API reference. Write it like you're explaining the module
to a smart colleague who's never seen it before.

---

```markdown
# <Module Name>

> **Module:** `<technical_module_name>` | **Path:** [`<addons/module_name>/`](<addons/module_name>/)

## What It Does & Why It Exists

<5-8 sentences. What business problem does this solve? Who uses it? What's the end result?
Be concrete — name the roles, the documents produced, the decisions it supports.
A reader should finish this section knowing whether this module is relevant to them.>

---

## The Big Picture — How It Works

> Explain the end-to-end flow from the user's perspective. Walk through what happens
> from the moment someone starts using this module to the final business outcome.

```
<Visual flow: states, transitions, what triggers each step>
<Step 1>  -->  <Step 2>  -->  <Step 3>  -->  <Final Outcome>
```

<Narrative explanation of the flow. Connect the steps. Explain the "why" behind each transition.
What decisions does the user make at each point? What does Odoo do automatically?>

### Key Decision Points
- **<Decision>:** <What the user chooses and how it changes the flow>
- **<Decision>:** <...>

---

## When to Use It (and When Not To)

### This module is for:
- <Concrete scenario — name roles, company types, situations>
- <...>

### Use something else when:
- <Scenario> — use `<other_module>` instead because <reason>
- <...>

---

## Real-World Scenarios

### Scenario 1: <Descriptive Name>
**Situation:** <Who has what problem? Be specific — role, company type, context.>
**What they do:** <Walk through the steps in plain language — menu paths, buttons, choices.>
**What happens:** <Business outcome + what Odoo creates/changes behind the scenes.>

### Scenario 2: <Descriptive Name>
<Same structure. Cover the module's main features through scenarios.>

---

## How Things Work Under the Hood

> Only include what helps understanding. Skip obvious boilerplate.
> This section exists to answer "but how does it actually work?" — not to list every field.

### Core Logic
<Explain the key mechanisms. What methods drive the main flow? What's the important
business logic? Focus on the non-obvious parts — the things that would surprise someone
or that they need to know to work with this module effectively.>

- **<method_name>()** ([`file.py:nn`](<path/file.py#Lnn>)) — <what it does and why it matters>
- <Only list methods that are essential to understanding the flow>

### Important Fields (only the ones that matter)
<Don't list every field. Only mention fields that:
- Control business logic (selection fields that change flow)
- Are non-obvious (computed fields with surprising behavior)
- Are decision points the user needs to understand>

- `<field>` — <what it controls and why you'd care>

---

## Configuration & Settings

<For each setting, explain what behavior it changes — not just the field metadata.
Write it as: "Enable X to get Y behavior. Without it, Z happens instead.">

- **<Setting UI Name>** (Settings -> <path>) — <what changes when you flip it>

---

## Dependencies

| Requires | Why |
|---|---|
| `<module>` | <what it provides that this module needs — in plain language> |

| Works With (optional) | What It Adds |
|---|---|
| `<module>` | <what new capability appears when both are installed> |

---

## Gotchas & Non-Obvious Behavior

- **<Topic>:** <Something that surprises people or causes confusion. Be specific.>
- **<Topic>:** <Constraint or limit that's easy to miss.>

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`<other-module>.md`](<other-module>.md) — <why related>
```

---

## Writing Rules

1. **No fact without a source.** Link to a file you actually read.
2. **No vague language.** Not "handles various cases" — say what cases.
3. **Flow over fields.** Explain how things connect, not what every column stores.
4. **Methods only when essential.** Mention a method only if understanding it helps the reader grasp the flow.
5. **Fields only when they matter.** Selection fields that change flow, computed fields with surprising behavior, config fields that unlock features. Skip the rest.
6. **Business language first.** Explain in terms of what the user sees and does, then connect to code.
7. **Short sentences.** One idea per sentence. No padding.
8. **Update INDEX.md** when you create or update a module doc.
9. **Scenarios must be concrete.** Name roles, company types, specific situations.
10. **All source links use `../` prefix** — mandatory for correct resolution from `documentations/`.

## Research Rules

### Rule R1 — Link paths
All links in `documentations/*.md` MUST use `../` prefix.
- Correct: `[stock_quant.py:42](../addons/stock/models/stock_quant.py#L42)`
- Wrong: `[stock_quant.py:42](addons/stock/models/stock_quant.py#L42)`

### Rule R2 — Check settings before documenting config
Read `res_config_settings.py` before documenting any setting. Know what it actually does.

### Rule R3 — Understand before writing
Read the actual source code. Trace the flow. Don't guess based on field names or class names.
