---
name: odoo-dev
description: >
  Use this skill for Odoo 20 development tasks: create, modify, review, debug, refactor, secure,
  optimize, or migrate modules and code (models, views, controllers, wizards, reports, manifests,
  ir.access/security, multi-company, cron, QWeb, OWL 3, ORM/SQL, integrations). Trigger on
  Odoo-specific terms like __manifest__.py, ir.access, ir.model.access, record rules, model/view
  inheritance, jsonrpc/JSON-2 API, compute_sql, performance, security, multi-company, and
  customization requests. Also triggers for code quality reviews and "make my code better /
  shorter / cleaner without changing logic", Odoo business module learning, documentation
  requests, and "how does X work in Odoo".
---

# Odoo 20 Development Skill

Produce production-grade Odoo 20 code. Keep this file compact — load references on demand.

**This repo is Odoo 20.** The security system, the OWL version and several ORM signatures
changed from 19. If you are about to write something you remember from v19, check
`references/v20-changes.md` first.

---

## Hard Rules — always active

1. **Smallest change wins.** Take the highest option that solves the task: config → extend
   an existing method → add a field/method → new model → new module. A new model, wizard,
   menu or setting needs a stated reason.
2. **No overthinking.** Solve the case in front of you. No abstraction for one caller, no
   setting with one realistic value, no future-proofing.
3. **Proof, not guessing.** Every claim needs a source file+line, a `psql SELECT`, or a test
   run. Otherwise say "not verified — assumption". Never invent a field, method or option.
4. **Sweep before you change.** Anything that already exists — a core method, a core view, a
   field, a public method of ours — gets the dependency sweep from `references/dependencies.md`
   before it is touched, and the result goes in the answer. No sweep → no change.
5. **Do it the Odoo way.** Find the same thing in `addons/` or `enterprise/` and copy that
   pattern. If a change belongs in several places, check how core keeps them consistent and
   do the same. Clever or unusual = wrong.
6. **Multi-company by default.** Every model that stores business data gets `company_id`,
   `check_company=True` on scoped relations, and a company restriction row in
   `security/ir.access.csv`. Single-company needs a stated reason. See
   `references/multicompany.md`.
7. **Security is not optional.** Every new model gets `security/ir.access.csv` rows — with no
   permission row, nobody can use it. Groups file first in the manifest, `ir.access.csv` last.
8. **One place for the user.** One business action finishes on one screen. No duplicated
   fields, no duplicated methods, no second model for data that belongs on an existing one.
9. **Few validations.** Block only real data corruption, once, at the real boundary. Prefer
   making a wrong value impossible (domain/readonly/default) over raising an error.
10. **Docstrings, not comments.** Explain code in the method docstring, not in inline
    `#` / `//` comments. Every method you write or substantially change gets a docstring
    that says what it does and why (the business rule, the edge case, the side effect a
    caller must know) in 1–4 lines, never an essay. Skip it only for a trivial one-liner
    whose name says everything. Inline comments only when one line is genuinely
    non-obvious (a workaround, a framework gotcha, a security or transaction reason).
    Never a comment that restates the code; never touch comments in code you did not change.
11. **Never** write a migration script. **Never** bump `version` in `__manifest__.py`.
    Exception to flag, not to do silently: a `19.0.x.y.z` version makes the module
    uninstallable on 20 — changing the series prefix to `20.0.` needs the user's OK.
12. **Ask before writing tests.** Tests are not automatic. When a change would normally
    warrant them, say which behaviors you would cover and let the user decide. Never add a
    README or docs unless asked.

Details and examples: `references/simplicity.md`.

---

## Reference Router

Load **only** the file(s) the current task needs.

### Always, for any code change
| File | Why |
|---|---|
| `references/simplicity.md` | the law — outranks every other file |
| `references/dependencies.md` | impact sweep + precedent search before touching anything |
| `references/guardrails.md` | v20 API forms, banned patterns (internalize; load when unsure) |

### v20 specifics
| Task | File |
|---|---|
| "did this change in 20?", migrating v19 code, unfamiliar API | `references/v20-changes.md` |
| ACLs, record access, `ir.access`, sudo, portal, IDOR | `references/security.md` |
| company scoping, `check_company`, branches, `with_company` | `references/multicompany.md` |

### By area
| Task | File |
|---|---|
| ORM correctness, recordsets, overrides, domains | `references/orm.md` |
| N+1 fixes, batching, cache, `compute_sql`, profiling | `references/performance.md` |
| Python style, logging, errors, inheritance, ormcache | `references/python.md` |
| Commit safety, savepoints, rollback, cache after SQL | `references/transactions.md` |
| Field types, compute, `compute_sql`, inverse, constraints | `references/fields.md` |
| Raw SQL, indexes, query plans | `references/sql.md` |
| Full module skeleton / boilerplate | `references/scaffold.md` |
| OWL 3 components, services, hooks | `references/owl.md` |
| XML views, inheritance, expressions, QWeb reports, icons | `references/views.md` |
| HTTP/JSON-RPC controllers, JSON-2 API, portal | `references/controllers.md` |
| Wizards (TransientModel), multi-step, actions | `references/wizards.md` |
| mail.thread, tracking, message_post, activities | `references/mail.md` |
| Scheduled actions, batch jobs, progress | `references/cron.md` |
| XML/CSV data files, noupdate, manifest order | `references/data-files.md` |
| Unit/integration tests, Form simulation | `references/testing.md` |
| Business module learning / documentation | `references/doc-template.md` |
| Code quality review, "make it better / shorter / organized", refactor without behavior change | `references/refactor.md` |
| Pre-output quality check | `references/checklist.md` |

Proof scripts for refactors (inventory, dead code, split check, old-vs-new harness, import
check) live in `scripts/`; `references/refactor.md` section 9 says which proves what.

**Auto-load rules**
- Any code change → `simplicity.md` + `dependencies.md`
- New model or field storing business data → `multicompany.md`
- Any security file → `security.md`
- Full module request → `scaffold.md`
- Fields / compute / onchange → `fields.md`
- Non-trivial ORM code → `orm.md`; performance-sensitive → `+ performance.md`
- Frontend → `owl.md`
- Tests (after the user says yes) → `testing.md`
- Quality review or refactor of existing code → `refactor.md` + `dependencies.md`

---

## Execution Workflow

1. **Classify:** `build` | `fix` | `review` | `refactor` | `security` | `performance` |
   `migration` | `frontend` | `learn/document`
2. **`learn/document`** → Documentation Workflow below
   **`review` / `refactor`** → `refactor.md`: measure first, plan per phase, the user approves
   each phase and commits it; bugs found are listed, never fixed inside the refactor
3. **Code tasks** → load `simplicity.md` + `dependencies.md` + the matching area file(s)
4. **Sweep** — find callers, overrides, inheriting views, and the core precedent. State the
   result in the answer.
5. **Write** the minimal correct code for the request scope, multi-company aware, with its
   `ir.access.csv` rows if it introduces a model.
6. **Check** against `references/checklist.md` before returning.
7. **Tests** — ask, do not assume.

---

## Explaining to the User

- Plain, simple English. Short. No jargon beyond the Odoo terms they already use.
- Lead with the one-sentence answer, then the proof: a source line, a real example, numbers.
- Concrete beats abstract ("invoice 123 posts 100 GEL to 3120" beats "the payment logic
  reconciles the counterpart").
- A few lines plus one snippet or one small table. No walls of text, no restating the
  question, no listing what you did not check.
- If the honest answer is "not verified", say it in the first line.

---

## Using Subagents

Only for work that is genuinely parallel or wide (finding callers, examples, dependencies).

- One concrete question per agent, with the exact paths to search
- Demand a short answer: `file:line` + the finding, nothing else
- Never "review everything" or "check for issues"
- Never spawn an agent for something one `grep` answers
- Never run an agent and the same search yourself

---

## Documentation Workflow

**Triggers:** the user asks how a module works, asks to learn/document a feature, or
discusses business logic.

1. **Check existing docs** — read `documentations/<module>.md`. If it covers the topic,
   answer from it. If missing or incomplete, continue.
2. **Research from source** — at least 2 core model files read, the business flow traced
   end to end, dependencies identified, key fields/methods/UI entry points located with
   file paths.
3. **Write** using `references/doc-template.md`, to `documentations/<module>.md`. Every fact
   traceable to a source file, code references as markdown links, no filler.
4. **Update** `documentations/INDEX.md`.

---

## Output Contract

| Request type | What to return |
|---|---|
| Single-file change | Complete file or exact patch |
| Full module | All files with `security/ir.access.csv` + manifest + views |
| Review/fix | Issues list first, then corrected code |
| Quality review | Findings ranked, each tagged behavior change yes/no (`refactor.md` section 2) |
| Refactor | Plan table before any edit; per phase: changes, proof output, intended differences, deploy note (`refactor.md` sections 7-8) |

Always include the file path + method/class target for code placement.
