---
name: odoo-readme
description: >
  Write, rewrite or review the two README files of an Odoo 20 module: README.md, a user guide
  for the people who run the module (what it is for, one-time setup, the steps they follow,
  examples with real numbers, what Odoo refuses and what to do), and README_DEV.md, a developer
  guide (architecture, file map, each flow with the methods that run it, guards, data,
  security, safe-extension rules). Short, scannable, checked against the code. Use it whenever
  someone asks for a module README, user guide or developer guide in custom_addons, wants
  existing READMEs shortened, reviewed, made clearer or brought up to date, or asks to
  "document this module" for users or developers. Not for documentations/<module>.md
  (odoo-dev's doc template) or manual test checklists (odoo-manual-tests).
---

# Odoo module READMEs

Every module gets two files for two readers. Write each one for its reader only: a fact that
does not help that reader goes to the other file, or nowhere.

| File | Reader | Answers |
|---|---|---|
| `README.md` | The people who use the module: accountants, HR, payroll, the admin who sets it up, a consultant | What is it for? What do I set up once? What do I do each day or month? What will I see? Why did Odoo refuse, and what now? |
| `README_DEV.md` | A developer who has to change the module | Where is the code? What runs when I click this? Which rule protects which data? How do I extend it without breaking it? |

The goal: someone reads the file once and can explain the module to a colleague. That comes
from structure, not length: a clear first screen, one topic per section, tables for facts,
real examples with numbers, and nothing the reader has to skip.

## Workflow

1. **Collect the facts.** Two scripts do most of it (`<scratchpad>` is the session scratchpad
   directory from the system prompt, not `/tmp`):
   ```bash
   python3 .claude/skills/odoo-readme/scripts/code_map.py <module_dir> > <scratchpad>/code_map.md
   python3 .claude/skills/odoo-manual-tests/scripts/module_inventory.py <module_dir> --db gec20_prod1 --port 5433 --full > <scratchpad>/inventory.md
   ```
   `code_map.py` lists models, fields, every method with its first docstring line, data
   records, inherited views, access rows and tests. `module_inventory.py` lists the exact menu
   paths, buttons, pop-up titles, states and error messages the user sees (`--db` adds the live
   menu paths of the working database). Then read the manifest, the existing READMEs,
   `documentations/<module>.md` and any `CODE_REVIEW.md` or `KNOWN_ISSUES`, and the methods
   behind the main buttons: enough to explain each flow, not every helper.
2. **Write `README.md`** following [references/user-guide.md](references/user-guide.md).
3. **Write `README_DEV.md`** following [references/dev-guide.md](references/dev-guide.md).
4. **Check** both files (list below), then reply.

When rewriting an existing README, keep every fact that is still true and still useful to its
reader. The rewrite changes structure and wording, not content: facts for the other reader
move there, and history and dated states go (see below). Back the old files up in the
scratchpad before overwriting them when the module has no git history for them.

## What makes these READMEs easy to read

- **The first screen answers "what is this for".** Title, one sentence of purpose, who the
  file is for, then a short "What it does" list. A reader who stops there should still know
  whether the module concerns them.
- **One fact, one place.** Each rule or number lives in one section; other sections point to
  it. Repeated facts drift apart at the next change, and readers notice the contradiction
  before they notice the repetition.
- **Examples with real numbers.** "Wage 1,000, pension member → net 784.00" explains a formula
  faster than the formula. Give every rule that computes money or dates an example, and check
  its arithmetic.
- **Tables for facts, short prose for flows and reasons.** Compare options, states, accounts
  and guards in tables; explain a flow as numbered steps; give each rule its reason in one
  sentence. A paragraph longer than about four lines usually hides a list or a table.
- **The reader's words.** In `README.md` use the labels printed on the screen (from the
  inventory) and no model, method or file names; show codes only where the screen shows them,
  such as salary rule codes on a payslip. In `README_DEV.md` name the real methods and fields,
  because the developer will grep for them.
- **Current behavior only.** No version history, release notes, "since 1.32", "no longer",
  "was changed", or the story of a bug. The reader needs the rule as it is today; history lives
  in git and in `documentations/<module>.md`. Release notes, if the team wants them, go in a
  separate `CHANGELOG.md`.
- **Nothing that rots unnoticed.** No test counts, line numbers, `#L` anchors, "all green on
  <date>", database names or module versions in the text. Link files, not lines; name the
  method instead of pointing at a line.
- **Verified.** Every label, rule, account and number comes from the code, the data files, the
  inventory or a `psql SELECT`. When something cannot be checked, leave it out or mark it
  "(not verified)".
- **Diagrams in plain text.** Draw a flow inside a ```` ```text ```` block with box characters
  (`─ │ ┌ ┐ └ ┘ ├ ┼ ▼ ►`), or use a table. Many Markdown viewers, including the ones this team
  reads READMEs in, show a Mermaid block as raw code whose node IDs (`C`, `TS`, `BF`) mean
  nothing to the reader. Keep text diagrams under about 80 characters wide, and check that
  every vertical line and arrow sits in the same column as the box it connects.
- **Consistent formatting within a file:** amounts as the English screen shows them
  (1,000.00), `→` for "becomes", `×` for "times", one term for one thing.

Size follows the module, not a target. A small module's user guide fits on two or three
screens; a large one needs more, but every section should read on its own in under a minute.
A section that grows past a screen is doing two jobs: split it, or move the detail to the
other file.

Illustration of the difference (not a template):

> Hard to read: "Timesheet claims in a draft payslip are released and re-priced when the
> hourly wage, projects, cutoff or scheme change, whereas work-log claims keep their snapshot,
> and once the payslip is validated the settlement is frozen in both cases."
>
> Easy to read:
>
> | Source | Price fixed when | A wage change while the payslip is a draft |
> |---|---|---|
> | Work log | the manager approves it | changes nothing |
> | Timesheet | the payslip is validated | re-prices it |

## Manifest description

The module's `__manifest__.py` needs a `description`: a few plain sentences (no Markdown)
ending with "Full documentation: README.md and README_DEV.md in the module directory."
Without it, Odoo takes `README.md` as the description and renders it as reStructuredText
(`odoo/modules/module.py`: the `README` file list and the `description` default), so the Apps
page shows mangled text and every module update logs docutils errors. Add it when it is
missing and say so in the reply; it does not change the version.

## Check before replying

- `python3 .claude/skills/odoo-readme/scripts/code_map.py <module_dir> --check README_DEV.md`
  lists backticked names found nowhere in the code or in other addons. Fix or remove each one,
  and run it on `README.md` too.
- Every menu path, button and message in `README.md` appears in the inventory, or is a core
  label you looked up.
- Every file of the module appears exactly once in the developer guide's file map.
- Every example adds up.
- No ```` ```mermaid ```` blocks are left, and each text diagram lines up in a monospace font.
- Relative links resolve from the module folder.
- The two files do not repeat each other: the developer guide points to user-guide sections
  for user steps.

## Reply to the user

Keep it short: what the files cover now and the three to five biggest changes, the size before
and after, what could not be verified, and any defect found in the code while reading (file
and method), offered as separate work rather than fixed inside the README task.
