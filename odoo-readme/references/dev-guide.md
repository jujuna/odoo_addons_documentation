# README_DEV.md — the developer guide

Reader: a developer who knows Odoo 20 but not this module and has to change it tomorrow. They
need a map (where things are), the flows (what runs, in which order), the guards (what must
never break) and the rules for extending it. The user guide covers the business; link to its
sections instead of repeating them.

## Sections, in this order

| # | Section | What goes in it |
|---|---|---|
| — | Title and first lines | `# <Module name> (`technical_name`) — Developer guide`, who it is for, links to README.md, `documentations/<module>.md` and any developer map |
| 1 | Purpose and facts | Two or three sentences, then a table: depends (and why each, a few words), new models, extended models, hooks, crons, controllers; then what the data files load, in manifest order |
| 2 | Architecture | One text diagram (a ```` ```text ```` block) of how data moves between the parts, with friendly names in the boxes and one line mapping them to model names, then two or three sentences |
| 3 | File map | Every file, grouped by folder, one line each: what it holds. Each file exactly once (compare with the code map) |
| 4+ | One section per area or flow | For each flow a user or cron triggers (button, compute, validation, cron, payment): numbered steps in execution order, each naming the method and what it does. Fields and behavior worth knowing go with the flow they belong to. Start the steps with the entry point that runs them. Numbered steps usually beat a diagram here; add a text diagram only when the steps alone are hard to follow |
| — | Data | What the data files create, which blocks are `noupdate`, what an upgrade changes and what it leaves alone |
| — | Guards and invariants | What the code refuses and where (method), in execution order when order matters; the invariants other code relies on |
| — | Security | Access rows as a table (model · group · rights · domain), field groups, and each `sudo()` with the reason it is safe |
| — | Integration | Modules that depend on this one or rely on its codes, fields or accounts, and what breaks if those change |
| — | Tests | How to run them (one command) and what each test file covers (one line each) |
| — | Extending safely | The rules a developer must keep, each with its reason |
| — | Known limitations | Current technical limits and debt, one line each with the consequence |
| — | Upgrading an existing database | Only when an upgrade needs a manual step: the condition to check and the fix, without dates |

## Leave out

- User click-paths and business explanations already in README.md: link to the section.
- History: version tables, "since", "was", the incident a guard came from, dated test runs,
  test counts.
- Line numbers and `#L` anchors: name the method; file links are fine.
- Whole formulas the data file states just as clearly. Show the key formula when the formula
  is the point (tax rules, for example).

## Writing a flow

A step names the method, then says what it does in plain terms and what it guarantees:

> 3. `_claim_timesheets`: takes the validated, unclaimed timesheets dated inside the claim
>    window, checks each is payable, and writes one ledger row per line at the hourly wage of
>    its work date.

One step per method call that matters; fold trivial calls into the step that uses them. When a
method needs more than two lines of explanation, give it its own short paragraph under the
flow, or improve its docstring and keep the step short.

For the complete method-by-method list, the code map is enough: the guide explains the methods
a developer will touch (entry points, core overrides, guards, helpers with surprising
behavior), not every compute and onchange.
