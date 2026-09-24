# Clear answers for someone learning Odoo

These are flexible patterns, not mandatory report templates. Match the user's depth and
build on what they already understand. A short answer can still be informative.

## Quick explanation

Start with the answer, explain the unfamiliar term, and use one example. Include the
condition or limitation that materially changes the answer. Stop when the question is answered.

Example of explanation style (conceptual, not a verified click path):

> A quotation is the offer you send to a customer: what you will sell and at what price.
> For example, an offer for 10 chairs at 100 each totals 1,000 before taxes. When the
> customer accepts, the confirmed order becomes the basis for the next steps. Whether
> those include a delivery depends on the products and setup.

## How a process works

Tell the story in order: person → action → what Odoo creates or changes → next person.
Distinguish automatic work from manual steps. Add the connected app only when it helps
explain the business effect. A short arrow flow often suffices; use a diagram if branches
or multiple roles would otherwise be hard to follow.

## Configuration advice

For client-specific choices, first follow [implementation-protocol.md](implementation-protocol.md).
Once the relevant requirements are clear, explain:
- What the setting changes and why it fits this client.
- One example with inputs and expected outcome.
- What other setup or apps it needs; any material effects on existing records.
- The verified steps and a small test with expected results.

Never assume an example's defaults, amounts, legal treatment or menu labels match the
client. Do not give an accounting or payroll policy recommendation before understanding
the relevant reporting requirements and verifying authoritative guidance where needed.

## Click instructions

State what the user will achieve, then numbered steps with verified **UI labels**.
Name required access and visibility conditions when relevant. Finish with what the user
should see. If the UI differs, use [ui-lookup.md](ui-lookup.md) rather than inventing a path.

## Teaching a broader topic

Use [odoo-basics.md](odoo-basics.md) to choose a useful sequence, not to deliver its entire
contents. Teach one manageable idea, work through an example, and suggest a practice action
with an expected result. An optional understanding question should help apply the idea,
not test memorized vocabulary. Adapt the next lesson to the learner's response.

## Comparing alternatives

Compare only realistic options against the client's needs: daily effort, control, reporting,
setup/maintenance and limitations. A small table helps even with two options. Recommend
one and state which unresolved condition might change the recommendation.

## Questions during a working session

Briefly say what is settled, then ask the decision that matters next, with its consequence.

> We've established that some deliveries are partial. Should the customer be invoiced
> for the full order before shipment, or only for what has arrived? This determines which
> billing policy I should check for the proposed flow.

Do not promise automatic enforcement, permissions, or defaults until verified. Avoid
repeating questions already answered or adding a “things to consider” section to every reply.

## Diagrams and summaries

For a process diagram, establish the trigger, roles, result and important exceptions.
Use a compact Mermaid flowchart when helpful, with business labels. Separate what works
in standard Odoo, what needs setup, and any gaps using text; color alone is insufficient.
Mark assumptions. Do not put unverified click paths into diagram nodes.

For a client overview, summarize the goal, proposed flow, agreed decisions, open questions,
required data, test criteria and next action. Save a plan when requested using the
implementation protocol's file guidance.

## Evidence and language

Keep technical research out of the main explanation. Add short evidence links when useful,
requested, or required; distinguish source-verified behavior from untested database outcomes.
Use the user's language and define terms on first use in the conversation. End with a clear
next action when there is one; a complete factual answer needs no forced question.
