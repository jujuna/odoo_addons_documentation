# Implementation: understand, analyze, decide, validate

Use for client-specific setup or process design. Answer general learning questions directly.
Scale the depth to the decision: a small setting change should not become a full project.

## 1. Understand the need

Use existing conversation context before asking anything. Briefly restate the outcome,
and distinguish stated facts from your interpretation. Ask the most consequential missing
business questions first, usually 1–3 and no more than 4 at once. Wait for answers when they
change the design. Read-only research can help formulate questions; do not commit to a
solution around an unanswered essential requirement.

Relevant discovery areas (select, do not ask all):
- Desired result and a real example of today's problem; what would count as success.
- Actors, approval rules, and the event that starts and ends the process.
- Normal flow and important exceptions: partial quantities, returns, rejection, changes.
- Environment: target version, edition/hosting if relevant, existing apps/customizations,
  companies, localization, integrations and existing records.
- Practical constraints: deadline, volume, migration, reporting and maintenance ownership.

Ask business questions the user can answer. Explain unfamiliar choices before asking them
to choose. Ask for client environment facts unavailable from source, not facts you can
verify yourself. Offer “not sure—let's use one real example” when appropriate.

Do not automatically assume thresholds, payment terms, or user roles are cosmetic: they
can change controls, cash flow, permissions and acceptance tests. State provisional
assumptions only when safe or when the user authorizes you to proceed that way. “Not sure”
is an unresolved requirement, not agreement with your preferred policy.

Example first response to “The client wants purchase approvals”:

> You want purchases to follow the client's approval rules in Odoo. Before choosing a setup:
> 1. What needs approval: every purchase, purchases above an amount, or certain departments?
>    This determines the rule we need.
> 2. Who approves, and may that person approve their own purchases?
> 3. What must be prevented until approval: sending the order to the supplier, confirming
>    the order, or paying the bill? These are different control points.
> After that, I'll check the standard options and the effects on purchasing and accounting.

This example does not presume how the client works or promise a particular feature.

## 2. Analyze the process and its dependencies

Read [dependency-analysis.md](dependency-analysis.md) and the relevant parts of
[tracing-impact.md](tracing-impact.md). Check source for the target environment.

Keep a compact working snapshot as the conversation grows:
- Confirmed goal, environment and business rules.
- Decisions already made and why.
- Assumptions and unanswered questions, with who can answer them.

Present the useful findings, not the entire investigation:
- **Apps and setup:** required apps, automatic connecting modules, optional features,
  company scope, and data needed first.
- **Flow:** trigger → person/action → Odoo document/status → next person → business result.
- **Rules:** approval, permissions, calculations, validation blocks, warnings, timing.
- **Effects elsewhere:** relevant stock, accounting, payroll, reports and notifications.
- **Exceptions:** the realistic cases that change the recommended solution.

Distinguish the current business process from the proposed Odoo process. Ask for correction
when the mapping rests on an uncertain business interpretation. If it matches facts already
confirmed, continue without an artificial checkpoint.

## 3. Compare and settle material decisions

For a meaningful choice, show the simplest fitting option, an alternative if useful, and
the practical tradeoff. Classify as Standard, Configuration, Studio/automation or Development
using SKILL.md. Search standard features before declaring a gap.

Explain what the choice changes for daily work, controls, data and future maintenance.
Recommend based on the user's goals, not a generic preference. If a new decision changes
scope or policy, ask and wait before finalizing that part. Continue independent analysis.
A single clear option or an already accepted choice needs no repeated approval.

## 4. Produce a usable plan

For a small change, a short sequence is enough. A larger implementation plan includes:
1. Goal, scope, assumptions and the recommended end-to-end flow.
2. Setup order: apps/features → roles and master data → policies → sample transactions.
3. Verified click instructions where useful, including who can perform them.
4. Effects on existing records, migration/integrations and changes to people's work.
5. Acceptance scenarios and expected results, including relevant exceptions.
6. Open decisions and owners; for go-live, who validates, trains, deploys and supports it.

A practical acceptance test specifies **starting data, actor, action, expected result**.
Cover a normal case plus the relevant boundary, unauthorized role, partial/cancelled case,
and downstream effect. Test in a suitable test database before live changes. Describe
proposed tests as proposed; report tests as passed only if they were executed successfully.

For larger changes, identify a realistic recovery approach. Do not suggest uninstalling a
module as a harmless undo operation or assume an existing transaction can be reversed.

## 5. Hand off only when necessary

A functional specification should let a developer and tester agree on the result:
- Business goal and why verified standard/configuration options do not meet it.
- Scope, actors, documents and trigger; current versus desired behavior.
- Rules with examples, exceptions, permissions and company boundaries.
- Dependencies, integrations, existing-data effects and migration needs.
- Acceptance scenarios with expected outcomes; open questions and exclusions.

Prepare the spec when requested or already agreed. Keep implementation code outside this
consulting workflow. Do not require another approval just to save an authorized deliverable.
Use the user's location; otherwise a suitable default is `client_plans/<client_name>/`.
Preserve unrelated content in existing files.

## Keep questions helpful throughout

- Ask at a real uncertainty or decision, not after every research step.
- Explain why the answer matters and offer understandable options. Recommend a design when
  evidence supports it; never invent a recommendation for an unknown client fact.
- Separate business decisions from learning checks. A learning check can be “If only 6 of
  10 items arrive, what should the buyer be allowed to do next?”; it is not an approval gate.
- If the user says “you decide”, proceed with explicit assumptions and record tradeoffs.
- If an answer changes the plan, explain the affected part and revise that part only.
- Before changing a live system, ensure the exact action and target are authorized. Preserve
  existing authorization; a request for advice or a plan alone does not authorize execution.
