# README.md — the user guide

Reader: the people who use the module and the admin who sets it up. They know their job
(payroll, accounting, HR, sales) and the Odoo screens they already use; they do not read code.
Write so they can find their task, follow it, and predict the result.

## Sections, in this order

Drop a section that has nothing to say, but keep the order, so every module's guide feels the
same to someone who has read another one.

| # | Section | What goes in it |
|---|---|---|
| — | Title and first lines | `# <Module name> (`technical_name`)`, one or two sentences on what it is for, "Who this is for", a link to README_DEV.md |
| 1 | What it does | Three to nine rows: a feature and what it gives the reader, one sentence each |
| 2 | Quick facts | Menus (exact paths), buttons the module adds to existing screens, who can use it (groups in plain words), what must be installed, what else works with it |
| 3 | How it works | One small text diagram of the business flow (a ```` ```text ```` block, steps named in business words, top to bottom), then two or three sentences that walk through it |
| 4 | Set it up (once) | Numbered steps with the menu path and what each setting changes; what works without setup; what must stay off |
| 5+ | One section per topic the reader works with | The things they create or decide (schemes, logs, programs, rates...): a table of options, the steps, and who may do what |
| — | Examples | Worked examples with real numbers, next to the rule they illustrate: inputs → what Odoo computes |
| — | Step by step | The routine the reader repeats (the month-end, the daily sync): numbered steps "do this → you see this" |
| — | When Odoo refuses | Table: the start of the message (from the inventory) · why · what to do |
| — | Rules to remember | The few rules that surprise people, each with its reason. A recap is fine here; point to the section that explains it |
| — | Common questions | **Question?** then one or two sentences. Only questions the sections above do not already answer at a glance |
| — | Known limitations | What the module does not do, and the workaround |
| — | Glossary | Only words the module invents or uses differently from Odoo |

## Leave out

- Model, field, method, file and class names; code links; line numbers.
- How the code enforces a rule. Say that it is enforced and what the user sees.
- Rule sequences, formulas written as code, internal states the screen does not show.
- Upgrade and migration steps, database repairs (they go in README_DEV.md).
- Version history, dates, "since version", test plans (odoo-manual-tests builds those).

## Small things that help

- Put the menu path in bold: **Payroll > Payslips > Pay Runs**. Take it from the live menus in
  the inventory; the XML parent alone does not give the full path.
- Name buttons exactly as printed: **Register Payment**, not "the pay button".
- Quote messages by their first words, exactly as the inventory prints them.
- A step says what the reader will see after it when that is not obvious.
- For a record with several states, one or two lines of text show the main path and a
  sentence covers the side paths:
  ```text
  Draft ──Submit──► Submitted ──Approve──► Approved
                        │
                        └──Reject──► Rejected
  ```
