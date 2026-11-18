# bsc_demo — a worked example you can click through

Installs one complete scorecard **and then runs it**, so every feature is
visible in the state a real user would meet it in. An empty demo scorecard
teaches nothing; this one has every quarter before today's behind it.

> **Scratch databases only.** It writes ordinary records, not XML data, so
> uninstalling the module does **not** remove them.

## Install

```bash
odoo-bin -d <scratch-db> -i bsc_demo --stop-after-init
```

Pulls in `bsc_strategy`, which now carries the automation and the map. Safe to
re-run: it checks for its own scorecard and skips if present.

## What it builds

**Strategy "Growth and Delivery <year>"**, quarterly, with a weighted
perspective split (Financial 40 / Customer 30 / Process 20 / Learning 10).

**8 objectives**, including one qualitative (`L2 Keep the team engaged`) that
carries no KPI at all — because not every objective becomes a number.

**9 cause-effect links**, each written down as a hypothesis with a believed
strength. The strong ones are exactly the chain capability → delivery →
retention → revenue, so the thickest arrows on the map tell the story.

**12 KPIs** covering every direction the arithmetic supports — higher is
better, lower is better (including `Accounts churned`, where zero is a real
result and a naive scorecard divides by it), and a target range
(`Satisfaction score`, 7.5–9, where too high is as suspicious as too low).

## The state you land in

The quarters follow today's date: the quarter containing today is the live
one, and every earlier quarter of the year is closed. In January to March the
demo runs the previous year, with its Q4 as the live quarter.

| | |
|---|---|
| **First quarter** | Closed. Good quarter, delivery missed by a day and nobody minded. Review **done**, with minutes. |
| **Later closed quarters** | Delivery slipped, rework rose, accounts churned, revenue missed. The last closed review created a corrective hiring initiative. |
| **Current quarter** | **Open, half-collected.** Figures entered but not yet validated, two KPIs still unreported, and both automation guards visibly fired. |

**5 initiatives** across the whole lifecycle: one proposed, two in progress with
budget burn, one done with a result summary, and one that came out of the last
closed review (when at least two quarters are closed). The delivery redesign
runs as an Odoo project.

## The story, and why it is the point

It is deliberately a causal chain, not a set of unrelated red cells:

```
L1 capability ─→ P1 delivery ─→ C1 retention ─→ F1 revenue
   (green)         (RED)          (amber)          (red)
```

Senior engineers left → delivery time went from 11 to 15 days → churn tripled →
revenue missed. Open **Strategy → Strategy Map**, find the red card at the top,
follow the arrows down, and you arrive at the process perspective. That is the
conversation a list of KPIs cannot start, and it is what the whole method is
for.

## Where to look

| Screen | What it demonstrates |
|---|---|
| **Strategy → Strategy Map** | The chain above; click any arrow to read its hypothesis |
| **Strategy → Scorecards** | Rolled-up index, per-perspective scores, the Board Pack PDF |
| **Data Entry** | Current-quarter rows waiting, with `Auto` and `Sync` columns |
| **Reviews → Periods → current quarter** | A banner listing the figures automation **refused to publish** |
| **Reviews → Strategy Reviews** | One review per closed quarter, with frozen snapshots and real decisions |
| **Configuration → KPI Data Sources** | Two sources, one of them deliberately broken |

## The two guards, firing

Both are invisible until they trigger, so the demo triggers them:

* **`New customers`** returns 40 for the current quarter against 15-18 in the
  one before — more than double. It is **held back, not published**, and waits
  for someone to press *Confirm*. Read the current period form.
* **`Escalations logged`** points at a tag that does not exist. It matched no
  records, so the figure is left **empty and flagged** — never published as a
  zero. This is what a filter that has quietly stopped working looks like, and
  it is the failure mode that makes automated scorecards dangerous.

## Resetting

Delete the scorecard (as a BSC Administrator) and the demo partners
(`ref = BSC-DEMO`), then reinstall the module. Or just drop the database.

## Licence

LGPL-3.
