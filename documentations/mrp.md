# Manufacturing (MRP)

> **Module:** `mrp` (+ `mrp_account`, `mrp_subcontracting`; enterprise `mrp_workorder`, `quality_mrp*`, `mrp_mps`; `maintenance` + enterprise `mrp_maintenance`) | **Path:** [`addons/mrp/`](../addons/mrp/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Manufacturing turns components into finished products inside Odoo. A **Bill of Materials (BoM)** is the recipe: components, optional operations (steps on work centers) and optional by-products. A **Manufacturing Order (MO)** applies the recipe to a quantity: it creates stock moves that consume components and receive the finished product, and one **work order** per operation. Planners schedule work orders on work-center calendars, operators record time and quantities (in the back office or on the enterprise **Shop Floor** app), and `mrp_account` turns consumed components and work-center time into the finished product's cost. Quality checks (enterprise) and maintenance requests plug into the same work orders and work centers. The result: stock that matches what was really consumed and produced, a cost per MO, and a schedule per machine.

---

## Key Terms

| Term | Meaning |
|---|---|
| **BoM** | Recipe for a product: components (BoM lines), operations, by-products. Type **Manufacture this product** (`normal`) or **Kit** (`phantom`); `mrp_subcontracting` adds **Subcontracting** |
| **MO** | Order to produce a quantity of one product with one BoM |
| **Work order (WO)** | One operation of the MO, executed on a work center |
| **Operation** | A step on a BoM (`mrp.routing.workcenter`): work center, duration, cost mode |
| **Work center** | Machine, line or team with a calendar, capacity, efficiency and hourly cost |
| **Kit** | BoM that is never produced: it explodes into its components on sales, deliveries and parent MOs |
| **Backorder** | New MO for the quantity not produced when the MO is closed early |
| **Unbuild order** | Reverse of an MO: consumes the finished product and returns the components |
| **OEE** | Overall Equipment Effectiveness of a work center over the last month |
| **MPS** | Master Production Schedule (enterprise `mrp_mps`): demand forecast grid per period |

---

## The Big Picture — How It Works

```
BoM ──► MO Draft ──Confirm──► Confirmed ──Start / first WO started / first component picked──► In Progress
          │                        │                                                               │
          │  Plan (allowed         │  Plan: work orders get slots                                   │ all WOs done or cancelled
          │  in draft too)         │  on work-center calendars                                      ▼
          │                        │                                                            To Close
          ▼                        ▼                                                               │ Produce
       Cancel ◄──────────────── Cancel                                                             ▼
          │                                                                         Done (stock posted, MO locked)
          └─ Reset to Draft (Administrator)                        Set to In Progress (Administrator) ◄┘
                                                                   Backorder MO for the rest (if any)
```

1. **Draft.** The MO exists; component and finished moves and work orders are computed from the BoM and can still change. Draft MOs can already be planned.
2. **Confirm.** Moves are confirmed, missing components trigger procurement, pickings of 2/3-step manufacturing are confirmed, and work orders are chained ([`action_confirm()`](../addons/mrp/models/mrp_production.py#L1751)).
3. **Plan.** Each work order gets a time slot on its work center, dependency order respected ([`button_plan()`](../addons/mrp/models/mrp_production.py#L1829)).
4. **Execute.** Operators start and finish work orders, record quantities, consume components. The MO moves to **In Progress** as soon as a work order is in progress or done, or a component move is picked ([`_compute_state()`](../addons/mrp/models/mrp_production.py#L607)).
5. **Produce.** The **Produce** button checks consumption against the BoM, decides about a backorder, finishes open work orders, posts the stock moves and locks the MO ([`button_mark_done()`](../addons/mrp/models/mrp_production.py#L2379)).

### Key Decision Points
- **BoM type:** `normal` creates MOs; `phantom` (kit) never does, its components are used directly.
- **Work orders on or off** (Settings → Manufacturing → Work Orders): without them an MO is a single confirm-and-produce step with no scheduling or time tracking.
- **Operation type of the MO:** whether procurement MOs are confirmed automatically, whether a short production asks for, always creates or never creates a backorder.
- **Warehouse manufacturing steps:** 1, 2 or 3 steps decide whether components are picked to a pre-production location and whether finished goods pass through a post-production location.
- **Consumption:** there is no per-BoM "flexible/strict" option. Any mismatch between consumed and expected quantities opens a warning that every manufacturing user can confirm.

---

## When to Use It (and When Not To)

### This module is for:
- Manufacturers and assemblers who need component consumption and finished-goods receipts to hit stock.
- Workshops that schedule several steps on machines or lines and want time per operation.
- Companies that sell bundles (kits) and want stock kept at component level.
- Manufacturers that cost products from real consumption and work-center time (with `mrp_account`).

### Use something else when:
- You only resell products: Sales + Inventory are enough.
- A vendor makes the product from your components: use `mrp_subcontracting` (BoM type **Subcontracting**), not in-house MOs.
- You repair customer items: use `repair`.

---

## Real-World Scenarios

### Scenario 1: Furniture workshop with two steps
**Situation:** A workshop builds dining tables: frame assembly on "Assembly Line", then varnish in "Paint Booth".
**What they do:** Enable **Work Orders**. Create a BoM with the components and two operations. Create an MO for 10 tables, **Confirm**, **Plan**. The assembler starts the first work order; the painter's work order stays **Blocked** until assembly is done, then turns **To Do**. After varnishing, the MO is **To Close**; the planner clicks **Produce**.
**What happens:** Components are consumed at the BoM quantity (or what was recorded), 10 tables enter stock, each work order keeps its real duration, and the MO cost includes both work centers' time.

### Scenario 2: Partial production and a backorder
**Situation:** An electronics maker has an MO for 100 boards but only 80 are finished today.
**What they do:** Set **Quantity** producing to 80 and click **Produce**. With the manufacturing operation type's **Create Backorder** = *Ask*, a wizard offers **Create Backorder** or **Close Production**.
**What happens:** With a backorder, the MO is renamed `…-001` and closes for 80; a new MO `…-002` holds the remaining 20 (planned automatically if the original was planned). With **Close Production**, the remaining 20 are dropped and consumption is checked against the full 100.

### Scenario 3: Kit sold on a quotation
**Situation:** A webshop sells a "Starter Kit" of three products it never assembles.
**What they do:** Create a BoM of type **Kit** for the kit product.
**What happens:** Procurement for the kit is replaced by procurements for its components ([`StockRule.run()`](../addons/mrp/models/stock_rule.py#L43), `procurements_without_kit`), so the delivery shows three component lines. The kit's on-hand and forecast quantities are computed from its components. A kit cannot have a reordering rule ([`check_kit_has_not_orderpoint()`](../addons/mrp/models/mrp_bom.py#L379)) and cannot be scrapped.

### Scenario 4: Make to order from a sale
**Situation:** A chair maker produces each order on demand.
**What they do:** Give the chair a normal BoM. The **Manufacture** route is a warehouse route, active on the main warehouse by default (**Manufacture to Resupply**). Enable **Replenish on Order (MTO)** in Inventory settings and set that route on the product.
**What happens:** Confirming the sale order runs procurement, which finds the Manufacture rule and creates an MO ([`_run_manufacture()`](../addons/mrp/models/stock_rule.py#L83)). It is confirmed only if the operation type has **Auto Confirm Production** on.

### Scenario 5: Fixed batch sizes
**Situation:** A bakery mixes dough only in batches of 10 kg.
**What they do:** On the BoM's Miscellaneous tab tick **Batch Size** and set 10.
**What happens:** A replenishment of 25 kg creates three MOs of 10 kg each. Automatic MOs always use full batches, so the total is rounded up; batch-size BoMs never merge into an existing MO.

### Scenario 6: Continuous production
**Situation:** A plant cuts parts and assembles them; assembly should start as soon as the first parts are cut.
**What they do:** On the BoM tick **Continuous Production**. Operators record the **Quantity Done** on the cutting work order as they go.
**What happens:** The assembly work order becomes **To Do** as soon as cutting has reported some quantity, and its ready quantity follows what cutting has done ([`_compute_state()`](../addons/mrp/models/mrp_workorder.py#L163), [`_compute_qty_ready()`](../addons/mrp/models/mrp_workorder.py#L220)).

---

## Bills of Materials

### BoM types
- **Manufacture this product** (`normal`): creates MOs; the only type the Manufacture route accepts ([`_filter_warehouse_routes()`](../addons/mrp/models/stock_rule.py#L75)).
- **Kit** (`phantom`): exploded by [`explode()`](../addons/mrp/models/mrp_bom.py#L449) wherever it appears: sale deliveries, procurements and parent MOs. A kit inside a normal BoM puts its components directly on the parent MO; its operations become work orders of the parent MO when they differ from the parent's.
- **Subcontracting** (`subcontract`, from `mrp_subcontracting`, [`mrp_bom.py:11`](../addons/mrp_subcontracting/models/mrp_bom.py#L11)): see [Subcontracting](#subcontracting).

A **multi-level** product has components that have their own normal BoM. Each such component is procured separately; with the Manufacture route this creates a child MO, visible through the **Child MO** / **Source MO** buttons of the MO.

BoM selection for a product is [`_bom_find()`](../addons/mrp/models/mrp_bom.py#L411): among the BoMs of the variant or its template, the lowest **Sequence** wins; procurement first looks for a BoM with the rule's operation type.

### What a BoM holds
| Tab | Content | Notes |
|---|---|---|
| Components | Product, quantity, unit, **Apply on Variants**, **Consumed in Operation** | A line linked to an operation is consumed by that work order |
| Operations | Work center, duration, cost mode, **Blocked By** | Needs the Work Orders setting; **Copy Existing Operations** reuses another BoM's operations |
| By-products | Product, quantity, **Produced in Operation**, **Cost Share (%)** | Needs the By-Products setting; cost shares on one BoM cannot exceed 100% ([`_check_bom_lines()`](../addons/mrp/models/mrp_bom.py#L191)) |
| Miscellaneous | Options below | |

### Miscellaneous options that change behavior
| Option | Field | Effect |
|---|---|---|
| Operation Type | [`picking_type_id`](../addons/mrp/models/mrp_bom.py#L63) | Procurements for that operation type prefer this BoM (multi-step routes group) |
| Manufacturing Lead Time | [`produce_delay`](../addons/mrp/models/mrp_bom.py#L79) | Days of production; the MO start is the need date minus this ([`_get_date_planned()`](../addons/mrp/models/stock_rule.py#L207)) |
| Days to prepare | [`days_to_prepare_mo`](../addons/mrp/models/mrp_bom.py#L82) | Extra days the replenishment report adds to create MOs early ("Days to Supply Components" in lead-time details) |
| Batch Size | [`enable_batch_size`, `batch_size`](../addons/mrp/models/mrp_bom.py#L86) | Automatic MOs are created in full batches (Scenario 5) |
| Continuous Production | [`continuous`](../addons/mrp/models/mrp_bom.py#L90) | Next work order unblocks when the previous one reports quantity (Scenario 6) |
| Manufacturing Readiness | [`ready_to_produce`](../addons/mrp/models/mrp_bom.py#L59) | **When all components are available** or **When components for 1st operation are available**; drives the MO's **MO Readiness** |
| Custom Operation Dependencies | [`allow_operation_dependencies`](../addons/mrp/models/mrp_bom.py#L76) | Off: work orders run one after another in sequence. On: they run in parallel unless **Blocked By** says otherwise |
| Additional Notes | [`note`](../addons/mrp/models/mrp_bom.py#L89) | Copied to the MO and shown on the Shop Floor |
| Extra Cost | [`extra_cost`](../addons/mrp_account/models/mrp_bom.py#L8) (`mrp_account`) | Cost per unit added to the MO cost (labour, energy, packaging) |

The BoM form shows a lead-time popover that names the component with the longest lead time and its route ([`_compute_json_popover()`](../addons/mrp/models/mrp_bom.py#L353)), stat buttons **Components / Sub Assemblies**, **Operations Performance** and **BoM Overview** (the BoM structure and cost report).

Changing a BoM used by open MOs flags them **Outdated BoM**; the MO offers **Update BoM**.

---

## Manufacturing Orders

### States
| State | Label | Set when |
|---|---|---|
| `draft` | Draft | Created; nothing reserved |
| `confirmed` | Confirmed | **Confirm** ([`action_confirm()`](../addons/mrp/models/mrp_production.py#L1751)) |
| `progress` | In Progress | A work order is in progress or done, a component is picked, or **Start** is clicked ([`action_start()`](../addons/mrp/models/mrp_production.py#L3238)) |
| `to_close` | To Close | All work orders are done or cancelled |
| `done` | Done | **Produce** finished; stock moves done, MO locked |
| `cancel` | Cancelled | **Cancel**; finished moves all cancelled |

Rules: [`state`](../addons/mrp/models/mrp_production.py#L182) and [`_compute_state()`](../addons/mrp/models/mrp_production.py#L607).

**MO Readiness** ([`_compute_reservation_state()`](../addons/mrp/models/mrp_production.py#L693)) shows *Ready*, *Waiting* or *Waiting Another Operation* from the component moves. With **When components for 1st operation are available**, a partially reserved MO is *Ready* once the first operation's components are reserved ([`_get_ready_to_produce_state()`](../addons/mrp/models/mrp_production.py#L1571)).

### Buttons and actions
| Where | Action | What it does |
|---|---|---|
| Header | **Confirm** | Draft only. Confirms moves and work orders, runs procurement for missing components |
| Header | **Plan** / **Unplan** | Schedules work orders as soon as possible (sets the MO start to now); needs work orders. Unplan is refused once a work order started or finished ([`_unplan_workorders()`](../addons/mrp/models/mrp_production.py#L1873)) |
| Header | **Start** | Confirmed MOs: moves the MO to In Progress |
| Header | **Produce** | Closes the MO (below). Hidden in draft; highlighted once In Progress or To Close ([`_compute_validate_button_style()`](../addons/mrp/models/mrp_production.py#L585)) |
| Header | **Cancel** | Not for done MOs; cancels work orders and open moves ([`action_cancel()`](../addons/mrp/models/mrp_production.py#L1998)) |
| Header | **Reset to Draft** / **Set to In Progress** | Administrator only, on cancelled / done MOs (below) |
| Action menu | **Plan at Date** | Plans from the MO's own start date instead of now ([`action_plan_at_date`](../addons/mrp/views/mrp_production_views.xml#L220), `button_plan(as_soon_as_possible=False)`) |
| Action menu | **Split**, **Merge**, **Lock/Unlock**, **Scrap**, **Unbuild**, **Labels**, **Mark as Done**, **Confirm** | Server actions bound to the MO list, kanban or form |
| List view | **Plan**, **Reserve**, **Cancel**; **Unreserve** in the action menu | Bulk actions on selected MOs |
| Components tab | **Catalog** | Add components from the product catalog |

### How components are consumed
Each component is a `stock.move` in `move_raw_ids`. Its **unit factor** is the planned quantity divided by what is left to produce ([`_compute_unit_factor()`](../addons/mrp/models/stock_move.py#L144)); the expected consumption is `(qty_producing − qty_produced) × unit factor` ([`_compute_should_consume_qty()`](../addons/mrp/models/stock_move.py#L177)).

- Changing **Quantity** producing on the MO recomputes the consumed quantity of every component move that is **not picked** ([`_set_qty_producing()`](../addons/mrp/models/mrp_production.py#L1501)).
- Typing a consumed quantity on a component marks it **picked** ([`_onchange_quantity()`](../addons/mrp/models/stock_move.py#L213)); picked moves are never recomputed again.
- Finishing a work order sets and picks the moves of the components consumed in that operation ([`button_finish()`](../addons/mrp/models/mrp_workorder.py#L737)).

### What Produce does
[`button_mark_done()`](../addons/mrp/models/mrp_production.py#L2379), in order:
1. **Lots/serials.** For a tracked finished product without lots, it fills the quantity producing if empty and creates one lot, or one serial per unit. For serials, the number of serials must equal the quantity producing.
2. **Checks** ([`pre_button_mark_done()`](../addons/mrp/models/mrp_production.py#L2518)): serial uniqueness; by-products marked produced; consumption compared with the BoM ([`_get_consumption_issues()`](../addons/mrp/models/mrp_production.py#L1883)); quantity produced compared with the MO quantity ([`_get_quantity_produced_issues()`](../addons/mrp/models/mrp_production.py#L1975)).
3. **Backorder** split if requested ([`_split_productions()`](../addons/mrp/models/mrp_production.py#L2141)).
4. **Work orders** still open are finished; remaining component moves are picked.
5. **Stock** posted ([`_post_inventory()`](../addons/mrp/models/mrp_production.py#L2064)): picked components done, unpicked ones cancelled, finished moves receive the lots, the cost is computed (`_cal_price`, see Costing).
6. MO set to **Done**, end date now, **locked**; reports configured on the operation type are printed.

**Consumption warning.** The check compares each component's picked quantity with the BoM quantity for what is produced, and also flags components removed from the MO and components not on the BoM. The wizard ([`action_confirm()` / `action_set_qty()`](../addons/mrp/wizard/mrp_consumption_warning.py#L21)) offers **Confirm** (keep what was consumed), **Update Quantities & Validate** (set every line to the expected quantity, creating missing moves) and **Discard**. Any manufacturing user can confirm. When the MO is closed without backorder (or the operation type never creates backorders), the expected quantities are computed for the full MO quantity.

### Backorders
The manufacturing operation type's **Create Backorder** ([`create_backorder`](../addons/stock/models/stock_picking_type.py#L193)) decides: *Ask* opens the wizard (**Create Backorder** / **Close Production**, [`action_backorder()`](../addons/mrp/wizard/mrp_production_backorder.py#L47), [`action_close_mo()`](../addons/mrp/wizard/mrp_production_backorder.py#L33)); *Always* splits silently; *Never* closes the MO for what was produced.

[`_split_productions()`](../addons/mrp/models/mrp_production.py#L2141) keeps all MOs of the chain in one `production_group_id`, renames the original with `-001` and numbers the backorders `-002`, `-003` ([`_get_name_backorder()`](../addons/mrp/models/mrp_production.py#L2118)). Work orders of a backorder carry what the chain already did (**Carried Quantity**, [`qty_reported_from_previous_wo`](../addons/mrp/models/mrp_workorder.py#L133)); fully done operations are cancelled in the backorder. A backorder of a planned MO is planned automatically; with reservation at confirmation it is reserved right after the original closes.

### Reset to Draft and Set to In Progress
Two Administrator buttons reopen finished work:
- **Reset to Draft** (cancelled MOs, [`action_reset_to_draft()`](../addons/mrp/models/mrp_production.py#L2048)): work orders back to To Do with time logs deleted, moves back to draft.
- **Set to In Progress** (done MOs, [`action_reset_to_progress()`](../addons/mrp/models/mrp_production.py#L2039)): done moves are reverted in place. Quants move back to the source location and are reserved again ([`stock_move_line.py:757`](../addons/stock/models/stock_move_line.py#L757), `_action_reset_to_progress`); with `stock_account` the journal entries are removed and the valuation reset ([`stock_move.py:791`](../addons/stock_account/models/stock_move.py#L791), `_action_reset_to_progress`). Existing lots/serials are reused when the MO is produced again.

### Split, merge, lock
- **Split** ([`action_split()`](../addons/mrp/models/mrp_production.py#L2689)) needs a BoM. On a draft or confirmed MO with nothing producing, a wizard splits it by **# Splits** or **Max Batch Size** with a date and responsible per part. If the MO is in progress or has a quantity producing, Split immediately cuts the MO into the producing quantity and a backorder for the rest. The serial-number wizard's **Prepare MO** splits the MO into one MO per serial.
- **Merge** ([`action_merge()`](../addons/mrp/models/mrp_production.py#L2714)): at least two MOs, same product and BoM, same state (draft or confirmed), same operation type, no components or by-products outside the BoM ([`_pre_action_split_merge_hook()`](../addons/mrp/models/mrp_production.py#L3069)). The merged MO keeps the earliest start and deadline; the originals are cancelled.
- **Lock/Unlock:** a locked MO past draft has read-only **To Consume** quantities; a done MO is read-only while locked. MOs start unlocked when **Unlock Manufacturing Orders** is on ([`_get_default_is_locked()`](../addons/mrp/models/mrp_production.py#L78)).

---

## Work Orders, Operations and Work Centers

### How work orders are created and chained
- In draft, [`_compute_workorder_ids()`](../addons/mrp/models/mrp_production.py#L636) creates one work order per operation of the exploded BoM, skipping operations limited to other variants. Manual work orders are kept.
- At confirmation, [`_link_workorders_and_moves()`](../addons/mrp/models/mrp_production.py#L1793) sets dependencies: without **Custom Operation Dependencies**, each work order is blocked by the previous one in sequence; with it, dependencies come from each operation's **Blocked By**. Component and by-product moves are attached to the work order of their operation.
- Each work order stores the operation's cost mode at confirmation ([`_set_cost_mode()`](../addons/mrp/models/mrp_workorder.py#L1132)).

### Work order states
| State | Label | Rule ([`_compute_state()`](../addons/mrp/models/mrp_workorder.py#L163)) |
|---|---|---|
| `blocked` | Blocked | A predecessor is not done or cancelled, and (with continuous production) it has reported nothing yet |
| `ready` | To Do | No predecessors, predecessors done, or (continuous) some quantity is ready |
| `progress` | In Progress | Started, or a quantity was recorded |
| `done` | Done | Finished |
| `cancel` | Cancelled | MO cancelled or operation not needed in a backorder |

Work order actions (from [`button_start()`](../addons/mrp/models/mrp_workorder.py#L693) on):
- **Start** (`button_start`) opens a time log, sets the work order and the MO in progress, and books a calendar slot if the work order was not planned. Without continuous production it sets the quantity producing to what remains.
- **Pause** (`button_pending`) closes the user's open time log.
- **Done** (`button_finish`) picks the operation's components at the quantity producing, closes all time logs, records the quantity done and freezes the work center's hourly cost on the work order.
- Recording **Quantity Done** on a work order (without continuous production) becomes the MO's quantity producing ([`write()`](../addons/mrp/models/mrp_workorder.py#L490)).
- Work orders carry **Properties** defined per manufacturing operation type ([`properties`](../addons/mrp/models/mrp_workorder.py#L153)) and have their own chatter.

### Operations: duration and cost
| Setting | Values | Effect |
|---|---|---|
| **Duration Computation** ([`time_mode`](../addons/mrp/models/mrp_routing.py#L27)) | **Fixed** (`manual`, default 60 min) / **Computed** (`auto`) | Computed averages the last N done work orders with a produced quantity: real duration ÷ cycles, where cycles = produced qty ÷ capacity rounded up; falls back to the fixed value without history ([`_compute_time_cycle()`](../addons/mrp/models/mrp_routing.py#L76)) |
| **Cost based on** ([`cost_mode`](../addons/mrp/models/mrp_routing.py#L59)) | **Actual time** / **Theoretical time** | Actual uses tracked time; theoretical uses the expected duration |

**Expected duration** of a work order ([`_get_duration_expected()`](../addons/mrp/models/mrp_workorder.py#L873)):

```
cycles   = ceil(quantity to produce / capacity)
duration = setup + cleanup + cycles × cycle time × 100 / time efficiency
```

Capacity, setup and cleanup come from the work center's capacity lines ([`_get_capacity()`](../addons/mrp/models/mrp_workcenter.py#L437)): a line for the product wins, then a line for the MO's unit without product, then a line for the product's unit. **Without a capacity line the capacity is the BoM quantity**, so a BoM written for 10 units with a 60-minute operation needs 3 cycles (180 min) for 25 units.

Example: 100 brackets, capacity line 4, setup 10, cleanup 5, cycle 15 min, efficiency 100%: `10 + 5 + 25 × 15 = 390` minutes.

### Work centers
| Field | Effect |
|---|---|
| **Working Hours** (`resource_calendar_id`) | Work orders are planned inside this calendar |
| **Time Efficiency** ([`time_efficiency`](../addons/mrp/models/mrp_workcenter.py#L36)) | Below 100% stretches durations (80% turns 15 min into 18.75 min) |
| **Setup / Cleanup Time** | Minutes added once per work order |
| **Cost per hour** | Work-center cost; frozen on the work order when it finishes |
| **Alternative Work Centers** ([`alternative_workcenter_ids`](../addons/mrp/models/mrp_workcenter.py#L74)) | Planning may move a work order to the alternative that finishes it earliest |
| **Product Capacities** ([`capacity_ids`](../addons/mrp/models/mrp_workcenter.py#L84)) | Capacity and setup/cleanup per product or per unit |
| **Barcode** ([`barcode`](../addons/mrp/models/mrp_workcenter.py#L35)) | Scanned on the Shop Floor to select the work center |
| **OEE Target** | Reference value for the OEE figure |

**Status** ([`working_state`](../addons/mrp/models/mrp_workcenter.py#L60), [`_compute_working_state()`](../addons/mrp/models/mrp_workcenter.py#L201)) comes from the open time log: none = **Normal**; productive or performance = **In Progress**; availability or quality loss = **Blocked**. **Block** records a blocking reason and ends every running timer on the work center ([`button_block()`](../addons/mrp/models/mrp_workcenter.py#L593)); **Unblock** closes the blocking log ([`unblock()`](../addons/mrp/models/mrp_workcenter.py#L293)).

**Time logs** use productivity loss categories. A timer is *Productive* while within the expected duration; when it is closed after the expected duration, the excess is split into a separate *Performance* loss log ([`_close()`](../addons/mrp/models/mrp_workcenter.py#L607)).

**OEE** over the last month = productive time × 100 / (productive time + all other logged time), so performance overruns lower OEE too ([`_compute_oee()`](../addons/mrp/models/mrp_workcenter.py#L251)). **Performance** = expected duration ÷ real duration × 100 over the month's done work orders ([`_compute_performance()`](../addons/mrp/models/mrp_workcenter.py#L275)).

---

## Scheduling (Planning)

- **Plan** plans from now; **Plan at Date** plans from the MO start date. Both skip MOs already planned or without work orders, and work for draft MOs.
- [`_plan_workorders()`](../addons/mrp/models/mrp_production.py#L1851) plans the final work orders; [`_action_plan()`](../addons/mrp/models/mrp_workorder.py#L586) first plans each work order's blockers, then starts it after the last blocker ends.
- For the work center and each alternative, the duration is recomputed for that work center and the first free slot is searched ([`_get_first_available_slot()`](../addons/mrp/models/mrp_workcenter.py#L348)); the work center that finishes earliest wins.
- The slot search walks 14-day windows, 50 of them by default (700 days, system parameter `mrp.workcenter_max_planning_iterations`). Free time is the calendar's working time minus **absence** leaves (time off, maintenance blocks); other work orders' slots are conflicts. No slot raises "Impossible to plan the workorder".
- The chosen slot is stored as a `resource.calendar.leaves` record with **Count as = Working Time** on the work center, and the work order's dates follow it. Moving a work order in the Gantt view reschedules it; resequencing replans the MO.

---

## Procurement: MOs Created Automatically

MOs come from sale orders (MTO), reordering rules, the replenishment report, MPS and parent MOs, all through [`_run_manufacture()`](../addons/mrp/models/stock_rule.py#L83):

1. **BoM:** the one passed by the procurement, else the reordering rule's BoM, else a normal BoM for the rule's operation type, else any normal BoM ([`_get_matching_bom()`](../addons/mrp/models/stock_rule.py#L145)). No BoM, no MO.
2. **Merge into an existing MO** ([`_make_mo_get_domain()`](../addons/mrp/models/stock_rule.py#L155)): a draft or confirmed, **unplanned** MO with the same BoM, product, operation type, company and references and **no responsible** gets its quantity increased instead. For reordering rules its start or deadline must fall before the need date minus the lead time. MPS procurements and batch-size BoMs never merge; with enterprise quality, MOs with started checks do not merge ([`stock_rule.py:10`](../enterprise/mrp_workorder/models/stock_rule.py#L10), `_make_mo_get_domain`).
3. **Create** ([`_prepare_mo_vals()`](../addons/mrp/models/stock_rule.py#L178)): start = need date minus **Manufacturing Lead Time** (minus one hour when it is 0), deadline = need date, no responsible, created as the current user for manual replenishment and as superuser otherwise.
4. **Confirm** only if the operation type has **Auto Confirm Production** ([`_should_auto_confirm_procurement_mo()`](../addons/mrp/models/stock_rule.py#L35)). MOs for other demand are confirmed at once. MOs from reordering rules are created in draft and confirmed after all reordering rules of the run are processed ([`_post_process_scheduler()`](../addons/mrp/models/stock_orderpoint.py#L225)). An MO without components is confirmed at once only when it has no work orders and comes from a reordering rule or a make-to-stock demand.

**Lead days** for the forecast and reordering rules ([`_get_lead_days()`](../addons/mrp/models/stock_rule.py#L214)): Manufacturing Lead Time + pre-production picking delays (2/3 steps) + Days to prepare; 365 days when no BoM is found.

---

## Manufacturing Steps (1, 2, 3)

Warehouse field **Manufacture** ([`manufacture_steps`](../addons/mrp/models/stock_warehouse.py#L31), Inventory → Configuration → Warehouses):

| Value | Flow | Extra operation types |
|---|---|---|
| `mrp_one_step` — Manufacture (1 step) | Stock → production → Stock | none |
| `pbm` — Pick components then manufacture (2 steps) | Stock → Pre-Production (**Pick Components**) → production → Stock | `pbm_type_id` |
| `pbm_sam` — Pick components, manufacture, then store products (3 steps) | Stock → Pre-Production → production → Post-Production → Stock (**Store Finished Product**) | `pbm_type_id`, `sam_type_id` |

Rules per step: [`get_rules_dict()`](../addons/mrp/models/stock_warehouse.py#L72). **Manufacture to Resupply** ([`manufacture_to_resupply`](../addons/mrp/models/stock_warehouse.py#L12)) adds or removes the warehouse from the Manufacture route.

---

## Scrap and Unbuild

**Scrap.** `stock.scrap` does not exist in 20.0; a scrap is a `stock.move` with `is_scrap` ([`stock_move.py:139`](../addons/stock/models/stock_move.py#L139), `is_scrap`). **Scrap** from the MO action menu ([`action_scrap()`](../addons/mrp/models/mrp_production.py#L2572)) proposes the MO's open components or, on a done MO, its finished products; the source is the components location (or finished location when done) and the destination the company scrap location. Validation marks the move picked, numbers it with the scrap sequence and posts it; **Should Replenish** triggers a procurement for the scrapped quantity ([`_action_scrap()`](../addons/stock/models/stock_move.py#L2961)). Scraps are listed under Manufacturing → Operations → Scrap and on the MO's **Scraps** button. Kits cannot be scrapped: the scrap form's product domain excludes them ([`stock_move_views.xml:81`](../addons/mrp/views/stock_move_views.xml#L81), `is_kits`).

**Unbuild** ([`mrp.unbuild`](../addons/mrp/models/mrp_unbuild.py#L11), Manufacturing → Operations → Unbuild Orders or **Unbuild** on a done MO): consumes the finished product and its by-products and returns the components to the destination location.
- Several serials can be unbuilt in one order; lot-tracked products take one lot per order ([`lot_ids`](../addons/mrp/models/mrp_unbuild.py#L57)).
- When components or by-products are tracked, the order must point to the done MO, so the original lots come back ([`action_unbuild()`](../addons/mrp/models/mrp_unbuild.py#L173)).
- Not enough stock at the source opens an "Insufficient Quantity To Unbuild" warning ([`action_validate()`](../addons/mrp/models/mrp_unbuild.py#L329)). A note is posted on the MO.

---

## Costing and the MO Overview

### Cost of the finished product (`mrp_account`)
At posting, [`_cal_price()`](../addons/mrp_account/models/mrp_production.py#L71) computes:

```
total cost = value of consumed components + work-order cost + Extra Unit Cost × quantity
```

- Work-order cost = duration × hourly cost ([`_cal_cost()`](../addons/mrp/models/mrp_workorder.py#L675)); with **Theoretical time** the expected duration is used. With enterprise `mrp_workorder`, employee time at the **Employee Hourly Cost** is added ([`_cal_cost()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L769)).
- Only **FIFO and AVCO** products get this computed unit cost: `total × (1 − by-product share) / quantity`. **Standard-price** products keep their standard price; the difference is not written on the move.
- A FIFO/AVCO by-product receives `total × cost share`; a standard-price by-product keeps its standard price.
- **Labour entry** ([`_post_labour()`](../addons/mrp_account/models/mrp_production.py#L134)): when the MO is done, for a product with automated valuation and a production location that has a valuation account, one entry debits that account and credits each work center's **Expense Account** (or the product expense account).

### What reaches accounting when an MO is done
Two conditions decide it, and a new database meets neither: the product's category must be **Perpetual (at invoicing)** (company default: **Periodic (at closing)**), and the **Production** location must have a **Cost of Production** account (empty by default). If either is missing, the MO posts no journal entry: the cost lives only on the stock moves and the MO Overview, and reaches the ledger at the stock closing.

When both are set, each done move posts its own entry ([`_should_create_account_move()`](../addons/stock_account/models/stock_move.py#L766), [`_get_account_move_line_vals()`](../addons/stock_account/models/stock_move.py#L305)), plus the labour entry above:

| Move | Debit | Credit | Amount |
|---|---|---|---|
| Components consumed | Cost of Production | Stock Valuation | Component value |
| Finished product received | Stock Valuation | Cost of Production | Finished move value (standard price, or computed cost for FIFO/AVCO) |
| Labour (work orders) | Cost of Production | Work center Expense Account | Work-order cost |

For FIFO/AVCO the finished value equals the total, so Cost of Production nets to zero. For standard price the difference between actual and standard stays on the Cost of Production account; no price difference account is used.

Valuation methods, accounts and closing are in [`stock_valuation.md`](stock_valuation.md).

### MO Overview report
The **Overview** button on the MO ([`report.mrp.report_mo_overview`](../addons/mrp/report/mrp_report_mo_overview.py#L69), `_get_report_data`) shows components with availability, reservations, replenishment (child MOs, purchases, transit) and receipt dates, operations, by-products and one **MO Cost** column:
- **Before Done:** planned cost. Components = cost of their replenishments plus standard price × the rest ([`_format_component_move()`](../addons/mrp/report/mrp_report_mo_overview.py#L409)); operations = expected cost, or actual cost for done work orders ([`_get_operations_data()`](../addons/mrp/report/mrp_report_mo_overview.py#L237)).
- **Done:** actual cost. Components = unit cost × consumed quantity, where `mrp_account` uses the move's valuation price ([`_get_unit_cost()`](../addons/mrp_account/report/mrp_report_mo_overview.py#L34)); operations = real (or theoretical) hours × hourly cost ([`_get_finished_operation_data()`](../addons/mrp/report/mrp_report_mo_overview.py#L289)). Enterprise adds one line per employee, or an estimated employee-cost line ([`mrp_report_mo_overview.py:10`](../enterprise/mrp_workorder/report/mrp_report_mo_overview.py#L10), `_get_finished_operation_data`).
- Quantities and durations above plan are shown in red ([`_get_comparison_decorator()`](../addons/mrp/report/mrp_report_mo_overview.py#L231)).
- By-products take their cost share of the MO cost; the finished product keeps the rest ([`_get_byproducts_data()`](../addons/mrp/report/mrp_report_mo_overview.py#L329)). A done MO with cost-sharing by-products shows a cost breakdown per product ([`_get_cost_breakdown_data()`](../addons/mrp/report/mrp_report_mo_overview.py#L107)); the footer shows unit costs ([`_get_report_extra_lines()`](../addons/mrp/report/mrp_report_mo_overview.py#L92)).

---

## Shop Floor (Enterprise `mrp_workorder`)

`mrp_workorder` installs automatically with `mrp` in enterprise databases.

- **Shop Floor** setting (`group_mrp_wo_shop_floor`, [`res_config_settings.py`](../enterprise/mrp_workorder/models/res_config_settings.py#L11)) shows the **Shop Floor** app: a full-screen client action at `/odoo/shop-floor` ([`action_mrp_display`](../enterprise/mrp_workorder/views/mrp_production_views.xml#L14)) with one card per MO or work order, filtered by work center. **Maximum number of cards per page** defaults to 40. **Timer** (`group_mrp_wo_tablet_timer`) shows timers on the cards.
- **Employees.** Starting a work order needs an employee: in the back office the user must be linked to an employee; on the Shop Floor an employee must be logged in (PIN) and act as session owner ([`button_start()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L218)). A work center can limit **allowed employees** ([`employee_ids`](../enterprise/mrp_workorder/models/mrp_workcenter.py#L14)). Time logs are per employee ([`start_employee()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L736)); an employee can correct their logged time in the log-time dialog ([`set_employee_duration()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L761)).
- **Employee cost:** **Employee Hourly Cost** on the work center ([`employee_costs_hour`](../enterprise/mrp_workorder/models/mrp_workcenter.py#L19)) adds to the operation cost.
- Operators register components, lots/serials and by-products, see worksheets and the MO's **Additional Notes**, scan work-center barcodes, run quality checks, log notes and propose changes to instructions.
- Menus added: Manufacturing → **Overview** (work-center dashboard), Planning → **Work Orders** → Kanban / Planning, Planning → **Employees** → Planning (Gantt).

---

## Quality Checks in Manufacturing (Enterprise)

| Module | Adds |
|---|---|
| `quality` | Points, checks, alerts, teams |
| `quality_control` | Pass-Fail, Measure, Spreadsheet checks; control frequency |
| `quality_mrp` (auto-installed with `quality_control` + `mrp`) | Checks on MOs, alerts from MOs |
| `quality_mrp_workorder` (auto-installed with `mrp_workorder`) | Checks as steps of work orders |
| `quality_control_worksheet` | Worksheet checks |

**Enable:** Settings → Manufacturing → **Quality** (`module_quality_control`) and optionally **Quality Worksheet**. Every point and check needs a quality team; a default team is created.

**Flow:**
1. A quality point is attached to an operation of the BoM.
2. When the MO is confirmed, each work order creates its checks from its points ([`_create_checks()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L350), called from [`_action_confirm()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L534)). The checks form a chain (previous/next); *Register Consumed Materials* and *Register By-products* get one check per matching move.
3. Operators complete the current check and move to the next ([`_next()`](../enterprise/mrp_workorder/models/quality.py#L379)). A failed check with a failure message opens the failure wizard.
4. **Done** on the work order runs [`verify_quality_checks()`](../enterprise/mrp_workorder/models/mrp_workorder.py#L272): *Instructions*, *Register Consumed Materials* and *Register By-products* pass automatically; any other open check blocks with "complete Quality Checks using the Shop Floor".
5. MO-level checks (points without operation) block **Produce** until done, **except for Quality Managers**, who can close the MO with pending checks ([`pre_button_mark_done()`](../enterprise/quality_mrp/models/mrp_production.py#L53)). On-demand checks are started from the MO ([`action_open_on_demand_quality_check()`](../enterprise/quality_mrp/models/mrp_production.py#L107)).

**Check types** (`quality.point.test_type` records):

| Type | Module | Auto-pass at WO Done |
|---|---|---|
| Instructions, Take a Picture | `quality` | Instructions only |
| Pass - Fail, Measure, Spreadsheet | `quality_control` | No |
| Register Consumed Materials, Register Production, Register By-products, Print Product Label, Print Lot/SN Label | `mrp_workorder` | Consumed materials and by-products only |
| Worksheet | `quality_control_worksheet` | No |

*Register By-products* is inactive until the By-Products setting is on.

**Control frequency** ([`measure_frequency_type`](../enterprise/quality_control/models/quality.py#L26), [`check_execute_now()`](../enterprise/quality_control/models/quality.py#L122)): **All**; **Randomly** (percentage chance per check); **Periodically** (only if no check of that point exists within the last N days/weeks/months); **On-demand** (created by hand), which is refused on work-order points ([`_check_measure_frequency_type()`](../enterprise/quality_mrp_workorder/models/quality.py#L18)).

**Quality alerts** are raised from a check or work order with the work order, work center and product filled in. Stages: New → Confirmed → Action Proposed → Solved ([`quality_data.xml`](../enterprise/quality/data/quality_data.xml#L13), `quality_alert_stage_0`). Root causes: Workcenter Failure, Parts Quality, Work Operation, Others ([`quality_data.xml`](../enterprise/quality/data/quality_data.xml#L57), `reason_workcenter`). Priority: Normal, Low, High, Very High ([`priority`](../enterprise/quality/models/quality.py#L371)).

---

## Planning Tools, Subcontracting, PLM

### Master Production Schedule (enterprise `mrp_mps`)
Manufacturing → Planning → MPS → **Master Production Schedule**, also under Inventory. A grid with one block per product and one column per period (**Manufacturing Period** on the company: yearly, monthly (default), weekly, daily, [`res_company.py:13`](../enterprise/mrp_mps/models/res_company.py#L13), `manufacturing_period`). Planners enter forecast demand; Odoo proposes quantities to replenish from the **Safety Stock Target** ([`forecast_target_qty`](../enterprise/mrp_mps/models/mrp_mps.py#L48)) and min/max replenish quantities. **Replenish** ([`action_replenish()`](../enterprise/mrp_mps/models/mrp_mps.py#L230)) runs procurements with origin `MPS`, which always create new MOs or purchase orders. Setting: Settings → Manufacturing → **Master Production Schedule**.

### Subcontracting
With `mrp_subcontracting`, a BoM of type **Subcontracting** lists its **Subcontractors**. It cannot have operations or by-products ([`_check_subcontracting_no_operation()`](../addons/mrp_subcontracting/models/mrp_bom.py#L25)). Confirming a receipt from the subcontractor creates the subcontracting MO at the subcontractor's location ([`_action_confirm()`](../addons/mrp_subcontracting/models/stock_move.py#L143)): one MO for an untracked product, one per lot/serial for a tracked one. **Register Components** on the receipt opens a simplified MO form to record consumed components; receipt move lines and MOs stay in sync through the MO split mechanism.

### PLM
Enterprise `mrp_plm` manages engineering change orders on BoMs (its own **PLM** app). The `module_mrp_plm` settings field exists but is not shown in the Manufacturing settings page.

---

## Configuration & Settings

### Settings → Manufacturing ([`ResConfigSettings`](../addons/mrp/models/res_config_settings.py#L10))
| Setting | Field | Effect |
|---|---|---|
| **Work Orders** | `group_mrp_routings` | Operations on BoMs, work orders on MOs, planning, work centers. Turning it off archives all operations; turning it back on restores the last archived batch |
| **Subcontracting** | `module_mrp_subcontracting` | Installs `mrp_subcontracting` |
| **Barcode** | `module_stock_barcode` | Process MOs from the Barcode app (enterprise) |
| **Quality** / **Quality Worksheet** | `module_quality_control`, `module_quality_control_worksheet` | Quality checks on work orders; worksheet checks |
| **Unlock Manufacturing Orders** | `group_unlocked_by_default` | MOs start unlocked so users can edit quantities to consume; toggling it updates the lock of all open MOs |
| **By-Products** | `group_mrp_byproducts` | By-products tab on BoMs |
| **Master Production Schedule** | `module_mrp_mps` | Installs `mrp_mps` |
| **Shop Floor**, **Timer** (enterprise) | `group_mrp_wo_shop_floor`, `group_mrp_wo_tablet_timer` | See Shop Floor |

There is no "Work Order Dependencies" setting (dependencies are the BoM option **Custom Operation Dependencies**) and no "Allocation Report" setting (it is **Show Allocation** on the operation type).

### Manufacturing operation type (Inventory → Configuration → Operation Types)
| Option | Field | Effect |
|---|---|---|
| Auto Confirm Production | [`auto_confirm_production`](../addons/mrp/models/stock_picking.py#L31) | Off: procurement MOs are created in draft |
| Create Backorder | [`create_backorder`](../addons/stock/models/stock_picking_type.py#L193) | Ask / Always / Never at Produce |
| Show Allocation | [`auto_show_allocation_report`](../addons/stock/models/stock_picking_type.py#L104) | Shows the **Allocation** button when finished products can serve waiting demand ([`_compute_show_allocation()`](../addons/mrp/models/mrp_production.py#L775)) |
| Create New Lots/Serial Numbers for Components | [`use_create_components_lots`](../addons/mrp/models/stock_picking.py#L26) | Lets users create component lots on the MO |
| Auto-print options | [`auto_print_done_production_order`](../addons/mrp/models/stock_picking.py#L35) and following | Print the MO, product labels, lot/SN labels, allocation report when done |
| Workorder Properties | [`wo_properties_definition`](../addons/mrp/models/stock_picking.py#L64) | Custom fields on work orders of this type |
| Reservation Method | `reservation_method` | At confirmation / manually / before scheduled date, for component moves |

---

## Access Rights

- Groups: Manufacturing **User** (implies Inventory User) and **Administrator** ([`mrp_security.xml`](../addons/mrp/security/mrp_security.xml#L10), `group_mrp_user`). Reset to Draft / Set to In Progress are Administrator buttons.
- Company restrictions in [`ir.access.csv`](../addons/mrp/security/ir.access.csv#L24) (`mrp_production_rule`): MOs, work orders, unbuilds and time logs belong to one company; BoMs, BoM lines, by-products, operations and work centers may be shared (no company).
- The feature groups Work Orders, By-Products and Unlocked by default are also granted to light users ([`res_groups.py`](../addons/mrp/models/res_groups.py#L9), `_get_light_group_xmlids`).

---

## Dependencies

| Requires | Why |
|---|---|
| `product` | Products, variants, units |
| `stock` | Moves, quants, routes, warehouses, operation types |
| `resource` | Work-center calendars and leaves used for planning |

| Works With (optional) | What It Adds |
|---|---|
| `mrp_account` | Finished-product cost, labour entries, extra cost, analytic lines |
| `sale_mrp` / `purchase_mrp` | Kits and MOs from sales; kit costs and purchases |
| `mrp_subcontracting` | Subcontracting BoMs and receipts |
| `mrp_product_expiry`, `mrp_landed_costs`, `mrp_repair`, `mrp_delivery` | Expiry dates in manufacturing, landed costs on MOs, repair integration, carrier handling of kits |
| `mrp_workorder` (enterprise) | Shop Floor, employees, quality steps, Gantt planning |
| `quality_mrp`, `quality_mrp_workorder` (enterprise) | Quality checks and alerts |
| `mrp_mps`, `mrp_plm` (enterprise) | MPS, engineering change orders |
| `mrp_maintenance` (enterprise) | Maintenance of work centers (below) |

---

## Equipment & Maintenance

> **Modules:** `maintenance` (community, [`addons/maintenance/`](../addons/maintenance/)), `hr_maintenance`, `stock_maintenance`; enterprise `maintenance_enterprise` (Gantt views), `maintenance_worksheet`, `mrp_maintenance` ([`enterprise/mrp_maintenance/`](../enterprise/mrp_maintenance/))

Maintenance tracks machines and tools, the repair and service work on them, and how reliable they are. With `mrp_maintenance`, a maintenance request can block a work center so that no work order is planned during the maintenance.

### Equipment and categories
- **Categories** ([`maintenance.equipment.category`](../addons/maintenance/models/maintenance.py#L23)) group equipment, name a **Responsible** technician and define **Equipment Properties** (custom fields for all equipment of the category).
- **Equipment** ([`maintenance.equipment`](../addons/maintenance/models/maintenance.py#L113)): name, category, vendor, model, serial number, cost, warranty, effective date (start of the MTBF count), scrap date, owner, technician, maintenance team, properties. **Used By** ([`equipment_assign_to`](../addons/maintenance/models/maintenance.py#L152)) is *Other* in `maintenance`; `hr_maintenance` adds *Department* and *Employee* ([`equipment.py:14`](../addons/hr_maintenance/models/equipment.py#L14), `equipment_assign_to`). `stock_maintenance` adds the storage **Location** ([`location_id`](../addons/stock_maintenance/models/maintenance.py#L9)); `mrp_maintenance` links equipment to a work center.
- Each equipment can define **Maintenance Request Properties** ([`equipment_req_properties_definition`](../addons/maintenance/models/maintenance.py#L156)), filled on its requests.

### Maintenance requests
[`maintenance.request`](../addons/maintenance/models/maintenance.py#L240):

| Field | Behavior |
|---|---|
| **Maintenance Type** | *Corrective* (something broke, გაფუჭდა) or *Preventive* (planned, დაგეგმილი) |
| **Technicians** ([`user_ids`](../addons/maintenance/models/maintenance.py#L287)) | Several users; the equipment's (or category's) technician is added automatically ([`_compute_user_ids()`](../addons/maintenance/models/maintenance.py#L378)) |
| **Team** | Required; taken from the equipment when set |
| **Status** ([`state`](../addons/maintenance/models/maintenance.py#L294)) | In Progress, Changes Requested, Approved, Done, Cancelled. Moving the card to another stage resets Changes Requested / Approved to In Progress |
| **Stage** | Kanban column only; stages can be limited to teams ([`maintenance_team_ids`](../addons/maintenance/models/maintenance.py#L20)); a new request takes the team's first stage ([`_compute_stage_id()`](../addons/maintenance/models/maintenance.py#L390)) |
| **Planned Date** / **Scheduled End** | End defaults to start + 1 hour; duration in hours |
| **Recurrent** | Preventive only: repeat every N days/weeks/months/years, forever or until a date |
| Instructions, Properties | Rich-text instructions and the equipment's request properties |

**Done and recurrence** ([`write()`](../addons/maintenance/models/maintenance.py#L450)): setting the status to *Done* fills **Close Date**. For a recurrent preventive request, it also copies the request to planned date + interval (same duration, first stage), unless the new date is past the end date. Leaving *Done* clears the close date. **Cancel** stops the recurrence; **Reopen Request** puts it back in the first stage ([`reset_equipment_request()`](../addons/maintenance/models/maintenance.py#L334)).

Default stages: New Request, In Progress, Repaired (folded), Scrap (folded) ([`maintenance_data.xml`](../addons/maintenance/data/maintenance_data.xml#L6), `stage_0`). Stages carry no "done" flag; *Done* is the status.

### Reliability: MTBF and MTTR
`maintenance.mixin` ([`maintenance.py:69`](../addons/maintenance/models/maintenance.py#L69), `maintenance.mixin`) is used by equipment and, with `mrp_maintenance`, by work centers. It counts **done corrective** requests; a failure date is the request's planned date, else its creation date ([`_compute_maintenance_request()`](../addons/maintenance/models/maintenance.py#L95)).

| Figure | Formula |
|---|---|
| **MTBF** — Mean Time Between Failures (რამდენ ხანში ფუჭდება საშუალოდ) | (latest failure date − effective date) in days ÷ number of done corrective requests |
| **MTTR** — Mean Time To Repair (რამდენი ხანი სჭირდება შეკეთებას საშუალოდ) | average of (close date − failure date) in days |
| **Latest Failure Date** | latest failure date |
| **Estimated time before next failure** | latest failure date + MTBF |
| **Expected MTBF** | entered by hand, for comparison |

### Teams
[`maintenance.team`](../addons/maintenance/models/maintenance.py#L505) has members, equipment and an **email alias** that creates requests for the team. The dashboard counts open requests (not done or cancelled): total, scheduled, unscheduled, high priority, changes requested ([`_compute_todo_requests()`](../addons/maintenance/models/maintenance.py#L531)).

### Work-center maintenance (`mrp_maintenance`)
- A request is **For** *Equipment* or *Work Center* ([`maintenance_for`](../enterprise/mrp_maintenance/models/maintenance.py#L55)); for equipment, the work center comes from the equipment. Requests can be opened from an MO (Action menu → **Maintenance Request**) or from a work order on the Shop Floor ([`button_maintenance_req()`](../enterprise/mrp_maintenance/models/mrp_workorder.py#L9)); the MO and work order are filled in.
- **Block Workcenter** ([`block_workcenter`](../enterprise/mrp_maintenance/models/maintenance.py#L63)) with a planned date creates `resource.calendar.leaves` of type **Absence** on the work center ([`_recreate_leaves()`](../enterprise/mrp_maintenance/models/maintenance.py#L122)). Work-order planning treats them as non-working time. **Additional Leaves to Plan Ahead** ([`recurring_leaves_count`](../enterprise/mrp_maintenance/models/maintenance.py#L64)) blocks that many future occurrences of a recurrent preventive request.
- Leaves are only created while the request is not done or cancelled and its stage has **Request Confirmed** ticked ([`create_leaves`](../enterprise/mrp_maintenance/models/maintenance.py#L11)); they are rebuilt when dates, recurrence, stage or blocking change.
- Maintenance can sit outside working hours but not over planned work orders: a new request on a busy slot is refused ("Manufacturing Orders are already scheduled for this time slot"), a recurring copy is moved to the next free slot with a warning activity ([`_get_first_flexible_available_slot()`](../enterprise/mrp_maintenance/models/mrp_workcenter.py#L119)).
- Work centers get MTBF/MTTR and a maintenance tab; menus **Planning by Workcenter** and, from `maintenance_enterprise`, **Planning by Equipment** show requests in Gantt.

`maintenance_worksheet` adds worksheet templates and their properties to requests ([`worksheet_template_id`](../enterprise/maintenance_worksheet/models/maintenance_request.py#L9)).

### Access
From [`ir.access.csv`](../addons/maintenance/security/ir.access.csv#L5) (`equipment_request_rule_user`):

| Model | Internal user | Equipment Manager (`maintenance.group_equipment_manager`) |
|---|---|---|
| Equipment | Read | Full |
| Categories, Stages, Teams | Read | Full |
| Requests | Full, but only requests they created, follow or are assigned to | Full, all requests |

Equipment, categories, requests and teams are restricted to the user's companies; records without company are shared.

### Menus
Maintenance → **Dashboard**; **Maintenance** → Maintenance Requests (+ Planning by Equipment / by Workcenter); **Equipment** → Machines & Tools (+ Work Centers with `mrp_maintenance`); **Reporting**; **Configuration** → Maintenance Teams, Equipment Categories, Maintenance Stages (debug mode).

---

## Gotchas & Non-Obvious Behavior

- **No strict consumption.** The BoM has no flexible/warning/strict option; the warning always appears and anyone can confirm it. Code can skip it with the context key `skip_consumption`.
- **Default capacity is the BoM quantity.** Without a capacity line, a BoM for 10 units counts every started 10 units as one cycle of the operation.
- **Procurement MOs may stay draft.** With **Auto Confirm Production** off, procurement MOs stay draft and reserve nothing; reordering-rule MOs are draft until the scheduler run finishes.
- **Merged demand.** Procurements add quantity to an existing unplanned MO without responsible. Planning an MO or setting a responsible stops this.
- **Batch size rounds up.** Automatic MOs are always full batches.
- **Plan starts now.** **Plan** moves the MO start to now; use **Plan at Date** to keep the date.
- **Picked means frozen.** Once a component move is picked (typed quantity, finished work order, Shop Floor), changing the quantity producing leaves it unchanged.
- **Standard-price products are not re-costed.** The computed MO cost only becomes the unit cost for FIFO/AVCO products.
- **Set to In Progress rewrites history.** It reverts quants and removes journal entries of the done MO; restrict who is Administrator.
- **Enterprise needs employees.** With `mrp_workorder`, starting a work order fails for users without an employee.
- **Quality managers can bypass MO checks** but not open work-order checks: work orders still refuse Done while non-auto checks are open.
- **Maintenance blocks need a confirmed stage.** A request in a stage without **Request Confirmed** does not block the work center.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`inventory.md`](inventory.md) — moves, reservations, routes, multi-step operations used by MOs
- [`inventory_forecast_report.md`](inventory_forecast_report.md) — the forecast report that also shows MOs and component demand
- [`stock_valuation.md`](stock_valuation.md) — valuation methods and accounts behind MO costing
- [`resource_calendars.md`](resource_calendars.md) — calendars and leaves used by work-center planning
