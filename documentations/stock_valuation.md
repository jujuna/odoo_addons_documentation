# Stock Valuation (Inventory Valuation)

> **Module:** `stock_account` + `stock_landed_costs` | **Path:** [`addons/stock_account/`](../addons/stock_account/) + [`addons/stock_landed_costs/`](../addons/stock_landed_costs/)
> **Odoo Apps category:** Inventory / Accounting
> **Verified from source:** Odoo 20 (`20.0` branch of this checkout) on 2026-09-22; journal-entry, Anglo-Saxon, account and COGS-eligibility passages corrected 2026-09-25 (see [`stock_transfers_corrections.md`](stock_transfers_corrections.md))

## How to Read This Document

This doc is organized **top-down**: business concepts first, then technical details.

- **Sections 1-9 (up to "Decision Matrix")** -- Pure business logic. No code. Read these to understand what stock valuation IS and why it exists.
- **"What Accounts Are Involved"** -- The bridge between business and code. Explains the accounting entries in plain English.
- **"Core Concepts" onward** -- Technical reference. Models, fields, methods, code traces. Come back here when you need to understand HOW Odoo implements a concept.

If you're learning Odoo business flows, read straight through the walkthroughs. Each one builds on the previous. If you already know accounting, skip to the Decision Matrix and then the walkthroughs for your use case.

---

## What It Does

Tracks the monetary value of inventory as products move between locations. Assigns a cost to every stock move using one of three costing methods (Standard, FIFO, Average). When configured for perpetual (real-time) valuation, automatically creates journal entries that keep the balance sheet in sync with physical stock. Supports lot-level valuation, landed cost allocation, and periodic closing for companies that don't use perpetual mode.

**Odoo 20 architecture note:** There is no `stock.valuation.layer` model. Valuation is computed directly on `stock.move` fields (`value`, `remaining_qty`, `remaining_value`). Historical adjustments are tracked via `product.value` records. All cost calculations (FIFO stack, AVCO average) are computed on-the-fly from move history.

**`move.value` is signed.** An outgoing move stores a *negative* value, an incoming move a positive one. Every ratio, sum and aggregate in the code relies on this -- that is why `_get_valued_qty(signed=True)` exists and why the stock move list view ships its own signed-aggregate renderer, [stock_account_move_list_view.js](../addons/stock_account/static/src/views/stock_account_move_list_view.js).

**Changed in 20 -- where the code lives.** In 19 the whole valuation stack (configuration fields, COGS generation, price differences, periodic closing, the valuation report) lived in `stock_account` and `purchase_stock`. In 20 the *accounting* half was lifted into `account` itself, so that a database without `stock` still has a working (approximate) inventory valuation:

| Concern | Odoo 19 | Odoo 20 |
|---|---|---|
| `inventory_valuation`, `cost_method`, `inventory_period`, `account_stock_valuation_id`, `account_stock_journal_id` on the company | `stock_account/models/res_company.py` | [`account/models/company.py`](../addons/account/models/company.py) |
| `property_valuation`, `property_cost_method`, `property_stock_journal`, `property_stock_valuation_account_id`, `property_price_difference_account_id` on the category | `stock_account/models/product.py` | [`account/models/product.py`](../addons/account/models/product.py) |
| `account_stock_variation_id` / `account_stock_expense_id` on the account | `stock_account/models/account_account.py` | [`account/models/account_account.py`](../addons/account/models/account_account.py) |
| `_get_product_accounts()` | `stock_account/models/product.py` | [`account/models/product.py`](../addons/account/models/product.py) |
| COGS lines on customer invoices | `stock_account._stock_account_prepare_realtime_out_lines_vals()` | [`account.move._create_cogs_lines()`](../addons/account/models/account_move.py#L5966) |
| Purchase price difference lines | `purchase_stock/models/account_invoice.py` (file deleted) | [`account.move._get_price_difference_lines_vals()`](../addons/account/models/account_move.py#L6064) |
| Periodic closing | `stock_account.res_company.action_close_stock_valuation()` | [`account.res_company.action_close_stock_valuation()`](../addons/account/models/company.py#L1278) |
| Inventory Valuation report | `stock_account/report/stock_valuation_report.py` | [`account/report/account_stock_valuation_report.py`](../addons/account/report/account_stock_valuation_report.py) |

`stock_account` now *overrides* those hooks to swap the `qty_available * standard_price` approximation for the real move-based valuation. `use_stock_account()` is the flag that tells `account` which of the two it is running with -- [res_company.py:32](../addons/stock_account/models/res_company.py#L32).

---

## Why Inventory Valuation Matters (Business Context)

Every company that holds physical stock needs to answer two questions for accounting:

1. **How much is the inventory on our balance sheet worth right now?** (Balance Sheet -- Current Assets)
2. **When we sell something, what did it cost us?** (Profit & Loss -- Cost of Goods Sold)

Without inventory valuation, a company knows what it sold products *for* (revenue) but not what those products *cost* (expense). That means no accurate profit margin, no correct financial statements, and no way to pass an audit.

Odoo's `stock_account` module bridges the gap between the warehouse (physical goods) and accounting (financial records). Every time goods enter or leave the warehouse, the system can optionally create a journal entry that moves value between accounts.

---

## The Two Big Decisions

Before using inventory valuation, a company must make two choices. These are set per product category (so different product types can use different rules).

### Decision 1: When Should Accounting Know About Stock Changes?

| Choice | Name | How it works | Best for |
|---|---|---|---|
| **After the fact** | Periodic (at closing) | No journal entries during daily operations. At the end of the month/quarter, an accountant runs a "closing" that compares physical inventory value to the books and posts the difference. | Small companies, companies with an accountant who reconciles manually, companies that don't need real-time financial reporting. |
| **When goods are billed or invoiced** | Perpetual (UI: "Perpetual (at invoicing)") | Receipts and deliveries post nothing themselves. The vendor bill debits the Stock Valuation account and the customer invoice carries COGS lines (core help: "An accounting entry is automatically created to value the inventory when a product is billed or invoiced", [`product.py:38`](../addons/account/models/product.py#L38)). Goods received but not billed, or delivered but not invoiced, reach the books at the Stock Closing. | Companies that need real-time financial visibility, companies with auditors who expect automated inventory tracking, any company using FIFO or AVCO seriously. |

**Where to set it:** Inventory > Configuration > Product Categories > "Inventory Valuation" field.

### Decision 2: How Should We Calculate the Cost of Each Unit?

This is the "costing method." It determines what cost Odoo assigns when you send a product out the door.

| Method | Plain English | Best for | Example |
|---|---|---|---|
| **Standard Price** | Every unit costs the same fixed amount. You set the price manually and it stays until you change it. | Manufacturing (where you set planned costs), simple businesses with stable purchase prices, companies that don't track actual purchase cost per receipt. | You set "Desk Lamp" cost = $25. No matter if you bought some for $23 and some for $27, Odoo values every lamp at $25 until you change it. |
| **First In First Out (FIFO)** | The oldest purchase cost is used first when you sell. Each receipt keeps its actual cost, and deliveries "consume" from the oldest receipt forward. | Trading companies, retail, any business where purchase prices change often and you want actual cost tracking. Required for accurate cost reporting in most industries. | You bought 10 lamps at $23, then 10 at $27. When you sell 12, Odoo costs 10 at $23 + 2 at $27 = $284. |
| **Average Cost (AVCO)** | Every receipt recalculates a running weighted average. All units in stock share the same average cost. | Companies that buy the same product frequently at varying prices and want a smoothed cost. Common in food/commodity industries. | You have 10 lamps at $23 ($230 total). You buy 10 more at $27 ($270 total). New average = $500 / 20 = $25/unit. |

**Where to set it:** Inventory > Configuration > Product Categories > "Costing Method" field.

---

## Anglo-Saxon vs Continental Accounting

The two accounting styles decide **when expenses are recognized**:

> **Anglo-Saxon** = "I'll record the expense only when I sell the product" (cost stays on the balance sheet until the sale)
> **Continental** = "I'll record the expense when I buy the product" (cost goes to P&L at purchase, then the change in inventory is adjusted at period end)

**In Odoo 20 the valuation mode decides which style you get, not the Anglo-Saxon flag.** `anglo_saxon_accounting` ([`company.py:147`](../addons/account/models/company.py#L147)) is read in one place only: it adds price-difference lines to vendor bills ([`account_move.py:6001`](../addons/account/models/account_move.py#L6001)). COGS lines and the bill account follow the product's valuation.

| Aspect | Perpetual (`real_time`) | Periodic (`periodic`) |
|---|---|---|
| **Style** | Anglo-Saxon | Continental |
| **Receipt / delivery validated** | No journal entry (unless a location has a valuation account) | No journal entry |
| **Vendor bill line account** | Stock Valuation ([`account_move_line.py:790`](../addons/account/models/account_move_line.py#L790)) | Expense |
| **COGS lines on customer invoices** | Yes, whatever the Anglo-Saxon flag ([`account_move.py:5998`](../addons/account/models/account_move.py#L5998)) | No |
| **When is expense recognized?** | At customer invoice, through COGS lines | At vendor bill, adjusted by the Stock Closing variation |
| **Stock Closing** | Manual only; the cron skips perpetual companies | Cron (daily / monthly) or manual |
| **Purchase price difference** | Standard cost only, with the Anglo-Saxon flag and a category Price Difference Account | Not applicable |

A perpetual company can still present a continental P&L. When its stock valuation account has both a Stock Variation and a Stock Expense account, the closing posts the period's change of the Stock Valuation balance between those two accounts ([`_get_continental_realtime_variation_vals()`](../addons/account/models/company.py#L1522)).

### How It Affects the Purchase Flow

**Perpetual -- step by step:**
1. You receive goods -> the move is valued at the PO price; no journal entry
2. You post the vendor bill -> the bill debits Stock Valuation (not Expense) and credits AP; the receipt takes the bill's price
3. The cost sits on the balance sheet until you sell the product
4. Only when you invoice a customer does the cost move from Stock Valuation to COGS (expense)

**Periodic -- step by step:**
1. You receive goods -> the move is valued; no journal entry
2. You post the vendor bill -> the bill debits **Expense** (P&L) and credits AP -- the cost is expensed now
3. At closing, the change in inventory value is posted between Stock Valuation and Stock Variation
4. No COGS lines are generated on customer invoices

**The practical difference:** Mid-month, perpetual shows billed inventory on the balance sheet (goods received but not billed are missing until the bill or the closing). Periodic shows purchases as expense immediately, so the P&L follows purchases, not sales, until the closing.

### How It Affects the Sale Flow

**Perpetual:** On customer invoice posting, COGS lines move cost from Stock Valuation to Expense. This is the moment the "cost of the sale" appears on the P&L. Source: [`_get_cogs_lines_vals()`](../addons/account/models/account_move.py#L6020), called from [`_create_cogs_lines()`](../addons/account/models/account_move.py#L5966)

**Periodic:** No COGS lines on invoices. The Stock Closing posts the difference between inventory value and the Stock Valuation account ([`_get_stock_valuation_account_vals()`](../addons/account/models/company.py#L1489)). The P&L only shows accurate cost-of-sales figures after the closing is run.

### Purchase Price Difference (Anglo-Saxon + Standard Cost Only)

When a vendor bill price differs from `standard_price`, Odoo creates price difference lines on the bill.

Source: [`_get_price_difference_lines_vals()`](../addons/account/models/account_move.py#L6064)

> **Changed in 20.** This used to live in `purchase_stock/models/account_invoice.py` (`_stock_account_prepare_anglo_saxon_in_lines_vals()`). That file is gone; the logic is now in `account` and runs for any purchase document, not only one coming from a PO.

**Condition:** `company.anglo_saxon_accounting = True`, the line passes `_use_inventory_valuation()` (storable + perpetual), and the product resolves a price difference account -- which [`_get_price_diff_account()`](../addons/account/models/product.py#L322) only does when `cost_method == 'standard'`.

**Example:** Product standard price = $9, vendor bills $10:
```
Original bill line:    Debit Stock Valuation $10, Credit AP $10
Price diff lines:      Debit Price Difference $1, Credit Stock Valuation $1
Net effect:            Stock Valuation = $9 (standard), Price Diff = $1 (variance)
```

The price difference account comes from `product.categ_id.property_price_difference_account_id`. **Changed in 20:** there is no expense-account fallback any more -- if the category has no price difference account, no price difference lines are created at all and the bill simply posts at the billed amount.

Source: [`_get_price_diff_account()`](../addons/account/models/product.py#L322)

---

## Complete Business Flow Walkthroughs

These walkthroughs follow real user actions in the Odoo UI, explaining what happens behind the scenes at each step.

---

### Walkthrough 1: "I Buy Products and Sell Them" (Trading Company, Perpetual + AVCO)

This is the most common scenario. A company buys goods from suppliers and resells them to customers.

**The complete lifecycle in one sentence:** You receive goods (stock quantity and value increase, no journal entry) -> you post the bill (confirms the cost; the inventory appears on the balance sheet) -> you deliver (stock decreases, still no journal entry) -> you invoice the customer (COGS lines move the cost to the P&L, revenue recorded).

**Setup:**
- Product Category "Merchandise": Costing Method = Average Cost (AVCO), Inventory Valuation = Perpetual
- Product "USB Cable": Category = Merchandise, Sale Price = $15
- Accounts configured: Stock Valuation = 1400, COGS/Expense = 5100, Revenue = 4000

#### Step 1: First Purchase (PO + Receipt)

**User action:** Create Purchase Order: 100 USB Cables @ $8 each, confirm it.

**User action:** Go to receipt, validate it (click "Validate").

**What happens:**
- Odoo creates a stock move: Supplier Location -> WH/Stock
- This is an "incoming" move (unvalued location -> valued location)
- Move value = $8 x 100 = $800
- Product `standard_price` updated to $8.00 (this IS the average cost)
- No journal entry: neither Vendors nor WH/Stock carries a valuation account ([`_should_create_account_move()`](../addons/stock_account/models/stock_move.py#L755))

**Result:** The inventory report shows $800; the Stock Valuation account is still 0 until the bill is posted. Product cost = $8.00.

#### Step 2: Receive Vendor Bill

**User action:** Vendor sends invoice for $8/unit. Create bill from PO, post it.

**What happens:**
- The bill line is redirected from expense to the Stock Valuation account (taxes left out):

| Account | Debit | Credit |
|---|---|---|
| 1400 Stock Valuation | $800 | |
| Accounts Payable | | $800 |

- The bill confirms the cost was indeed $8 -- no change to move value
- If the vendor billed $9 instead, the move value would be updated from $800 to $900, and the average cost would change to $9.00

#### Step 3: Second Purchase at a Different Price

**User action:** New PO: 50 USB Cables @ $10 each. Confirm, receive, validate.

**What happens:**
- New move value = $10 x 50 = $500
- AVCO recalculation:
  - Total inventory value = $800 (from first purchase) + $500 = $1,300
  - Total quantity = 100 + 50 = 150
  - New average cost = $1,300 / 150 = **$8.67/unit**
- Product `standard_price` updated to $8.67
- No journal entry at the receipt; its bill later debits Stock Valuation $500

**Result:** 150 units in stock, total value $1,300, unit cost $8.67.

#### Step 4: Sell to a Customer

**User action:** Create SO: 80 USB Cables @ $15 each (sale price). Confirm, deliver.

**What happens at delivery validation:**
- Stock move: WH/Stock -> Customer Location
- This is an "outgoing" move (valued -> unvalued)
- Move value = $8.67 x 80 = $693.60
- No journal entry YET from the stock move itself (COGS are posted at invoice time)

**Remaining inventory:** 70 units, value = $606.40 ($8.67 x 70), average cost stays $8.67.

#### Step 5: Invoice the Customer

**User action:** Create invoice from SO, post it.

**What happens -- the invoice gets these lines:**

| Account | Debit | Credit | Type |
|---|---|---|---|
| 1200 Accounts Receivable | $1,200 | | Normal invoice line |
| 4000 Revenue | | $1,200 | Normal invoice line |
| 5100 COGS | $693.60 | | Auto-generated (COGS) |
| 1400 Stock Valuation | | $693.60 | Auto-generated (COGS) |

**This is the key moment:** The COGS lines are auto-generated. They record:
- The cost of the goods you just sold ($693.60) as an expense (Profit & Loss)
- Reduction of inventory value on the balance sheet by the same amount

**Profit on this sale:** Revenue $1,200 - COGS $693.60 = **$506.40 gross profit** (42.2% margin).

---

### Walkthrough 2: "I Need to Track Exact Purchase Costs" (Perpetual + FIFO)

FIFO is used when you want the actual purchase cost to flow through to COGS, not a blended average. This gives the most accurate cost tracking but creates more complexity.

**Real-world analogy:** Think of a grocery store shelf stocked from the back. The oldest items are at the front (customers grab them first). Each batch has a different cost written on the box. When you sell, you sell the oldest batch first and record THAT batch's cost as your expense. That's FIFO.

**Setup:**
- Product "Olive Oil (1L)": FIFO, Perpetual valuation
- Three purchases at different prices over time

#### The FIFO Stack in Action

```
Jan 5:  Receive 200 bottles @ $6.00 each  =  $1,200
Jan 20: Receive 150 bottles @ $7.50 each  =  $1,125
Feb 10: Receive 100 bottles @ $8.00 each  =  $800

FIFO Stack (oldest at top):
  Layer 1: 200 @ $6.00  ($1,200)
  Layer 2: 150 @ $7.50  ($1,125)
  Layer 3: 100 @ $8.00  ($800)
  Total: 450 bottles, $3,125 value
```

#### Customer Order: 280 Bottles

**User action:** SO for 280 bottles, deliver and invoice.

**FIFO consumes from oldest first:**
```
  From Layer 1: 200 bottles @ $6.00 = $1,200  (layer fully consumed)
  From Layer 2:  80 bottles @ $7.50 = $600    (70 remain in layer)
  Total COGS = $1,800

  Remaining stack:
    Layer 2:  70 @ $7.50  ($525)
    Layer 3: 100 @ $8.00  ($800)
    Total: 170 bottles, $1,325 value
```

**COGS on the invoice = $1,800** (not $1,944 which would be AVCO at $6.94, not $1,680 which would be standard at $6.00).

**Why FIFO matters here:** The actual cost of the bottles you sold was $1,800. If you used AVCO, you'd report $1,944 -- overstating COGS by $144 and understating profit. FIFO gives the real picture.

#### What Happens to standard_price?

After this delivery, Odoo updates `standard_price`:
```
Remaining value / Remaining qty = $1,325 / 170 = $7.79/unit
```
This is used as a display price and fallback, not for FIFO calculations.

---

### Walkthrough 3: "We Import Goods and Have Shipping/Customs Costs" (Landed Costs)

Landed costs let you add freight, insurance, customs duties, and other costs to the actual product cost so your inventory valuation reflects the TRUE cost of getting goods to your warehouse.

**Why this matters:** If you buy a product for $10 from China but pay $3 in shipping and $2 in customs, your TRUE cost is $15/unit, not $10. Without landed costs, your inventory is undervalued, your margins look better than they are, and your cost analysis is wrong. Landed costs fix this by distributing the extra costs across the products in the shipment.

**Setup:**
- Enable "Landed Costs" in Inventory > Settings
- Product "Ceramic Tile" (AVCO or FIFO, Perpetual)

#### The Scenario

You import two products in one shipment:

| Product | Quantity | Unit Price | Total |
|---|---|---|---|
| Ceramic Tile (Box) | 500 | $12 | $6,000 |
| Marble Slab | 100 | $45 | $4,500 |
| **Subtotal** | | | **$10,500** |

Additional costs from the shipment:
- Ocean freight: $1,500
- Customs duty: $800
- Insurance: $200

**Total true cost:** $10,500 + $2,500 = $13,000

Without landed costs, your inventory would show $10,500 -- understating the true cost by $2,500.

#### Step-by-Step in Odoo

**1. Receive the goods** -- validate the receipt as normal. Inventory shows $10,500.

**2. Create a Landed Cost** (Inventory > Operations > Landed Costs):
- Link it to the receipt picking
- Add cost lines. Each line can be narrowed to specific products with **Apply On** (`apply_on_product_ids`, new in 20) -- leave it empty to spread the cost over every product in the transfer.

| Cost Product | Amount | Split Method | Why this split |
|---|---|---|---|
| Ocean Freight | $1,500 | By Volume | Larger items take more container space |
| Customs Duty | $800 | By Current Cost | Duty is typically proportional to value |
| Insurance | $200 | By Current Cost | Insurance is proportional to value |

**3. Click "Compute"** -- Odoo calculates how to distribute:

**By Volume (Freight $1,500):** If tiles have volume 0.05 m3/box and marble has 0.2 m3/slab:
- Total volume: (500 x 0.05) + (100 x 0.2) = 25 + 20 = 45 m3
- Tiles: $1,500 x (25/45) = $833.33
- Marble: $1,500 x (20/45) = $666.67

**By Current Cost (Customs $800):**
- Tiles: $800 x ($6,000/$10,500) = $457.14
- Marble: $800 x ($4,500/$10,500) = $342.86

**By Current Cost (Insurance $200):**
- Tiles: $200 x ($6,000/$10,500) = $114.29
- Marble: $200 x ($4,500/$10,500) = $85.71

**4. Click "Validate":**

| Product | Original Cost | Freight | Customs | Insurance | **New Total** | **New Unit Cost** |
|---|---|---|---|---|---|---|
| Ceramic Tile | $6,000 | $833 | $457 | $114 | **$7,404** | **$14.81** |
| Marble Slab | $4,500 | $667 | $343 | $86 | **$5,596** | **$55.96** |

Now when you sell a box of tiles, COGS will be $14.81 instead of $12.00 -- reflecting the true landed cost.

> **Changed in 20.** Odoo 19 refused to build valuation lines for standard-cost products and raised *"Landed costs can only be applied for products with FIFO or average costing method"*. That filter is gone from [`get_valuation_lines()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L166): a landed cost can now target any product. Standard-cost products still do not absorb the cost into their unit cost -- `standard_price` stays where you set it -- so in practice the allocation only changes the valuation of AVCO and FIFO products.

---

### Walkthrough 4: "We Manufacture Products" (Standard Cost + Production)

Standard costing is the most common method for manufacturers. You set a planned cost, and any difference between planned and actual becomes a variance.

**Setup:**
- Product "Wooden Chair": Standard Price = $50, Perpetual valuation
- Components: Wood ($15), Screws ($2), Cushion ($8) = $25 material
- Labor: $15/chair, Overhead: $10/chair

#### Why Standard Cost for Manufacturing?

Manufacturing has a problem: you don't know the final cost of a product until production is complete. But you need to value WIP (Work In Progress) and finished goods as they move through the factory.

Standard cost solves this by using a **planned cost** ($50/chair). At the end of the period, you compare planned vs actual and book the variance.

#### The Flow

**1. Set standard price = $50** on the Wooden Chair product.

**2. Produce 20 chairs:**
- Raw materials consumed: 20 x $25 = $500 (actual)
- Labor recorded: 20 x $15 = $300 (actual)
- Overhead applied: 20 x $10 = $200 (actual)
- Actual cost: $1,000

**3. Production order validated:**
- Finished goods valued at standard: 20 x $50 = **$1,000**
- In this case, actual = standard, so no variance

**4. If actual cost was $1,100 instead:**
- Standard valuation: 20 x $50 = $1,000
- Actual cost: $1,100
- Variance: $100 unfavorable (you spent more than planned)
- The MO uses no Price Difference account: the $100 stays on the Production location's **Cost of Production** account, and only if the MO posts entries at all (perpetual category and that account set; see [`mrp.md`](mrp.md), "What reaches accounting when an MO is done")

**5. Sell 10 chairs at $80 each:**
- Revenue: $800
- COGS (at standard): 10 x $50 = $500
- Gross profit: $300

**Key point:** With standard cost, COGS is predictable and consistent. Variances are tracked separately, giving management visibility into cost control.

---

### Walkthrough 5: "Our Prices Change Constantly and We Need Smooth Costs" (AVCO Flow)

**Setup:** Product "Coffee Beans (kg)", Average Cost, Perpetual valuation

#### Month of Purchases and Sales

```
Week 1: Buy 500 kg @ $4.00/kg = $2,000
  -> Average cost: $4.00
  -> Inventory: 500 kg, value $2,000

Week 1: Sell 200 kg
  -> COGS: 200 x $4.00 = $800
  -> Inventory: 300 kg, value $1,200

Week 2: Buy 400 kg @ $5.00/kg = $2,000
  -> New average: ($1,200 + $2,000) / (300 + 400) = $3,200 / 700 = $4.57
  -> Inventory: 700 kg, value $3,200

Week 3: Sell 500 kg
  -> COGS: 500 x $4.57 = $2,285
  -> Inventory: 200 kg, value $914

Week 4: Buy 300 kg @ $4.50/kg = $1,350
  -> New average: ($914 + $1,350) / (200 + 300) = $2,264 / 500 = $4.53
  -> Inventory: 500 kg, value $2,264
```

**Why AVCO is good here:** Coffee prices change every week. FIFO would give you wildly different COGS from sale to sale. AVCO smooths the cost, so management sees a consistent margin trend.

---

### Walkthrough 6: "We Track Costs Per Lot/Serial Number" (Lot Valuation)

**The problem without lot valuation:** Normally, Odoo treats all units of the same product as having the same cost (AVCO average or FIFO stack). But what if different batches of the same product have VERY different costs, and you need to track profitability per batch? Standard AVCO would blend all costs together, hiding which batches are profitable.

**Use case:** A wine distributor buys different vintages at different prices. Lot "Chateau 2020" costs $15/bottle, Lot "Chateau 2022" costs $22/bottle. When they sell from "Chateau 2020," the COGS should be $15, not the average of all lots.

**Setup:** Product "Red Wine", `lot_valuated = True` (checkbox "Valuation by Lot/Serial"), AVCO

**What changes with lot valuation:**
- Each lot gets its own `standard_price`
- When Lot 2020 is received at $15, that lot's cost = $15
- When Lot 2022 is received at $22, that lot's cost = $22
- On delivery, Odoo uses the **lot's cost**, not the product average
- The product's `total_value` = sum of all lots' values

**When to use:** Wine, pharmaceuticals, electronics with serial numbers that have different acquisition costs, any product where the lot/serial identity matters for cost tracking.

---

### Walkthrough 7: Periodic Valuation (Manual Closing Flow)

Not every company wants the Stock Valuation account moved by every bill and invoice. Smaller companies or those with a dedicated accountant might prefer periodic valuation: bills go to expense, invoices carry no COGS, and one closing entry per period adjusts the stock account.

**How it differs:**
- During the month, receipts and deliveries happen normally
- **No journal entries are created from stock moves**
- The inventory module tracks all quantities and values internally
- At month-end the accountant opens the **Inventory Valuation** report (Accounting > Review > Inventory > Inventory Valuation, menu shipped by `account_reports`) and clicks **Generate Entries**
- Odoo compares:
  - What the inventory system says the value is (based on quants + cost method)
  - What the accounting ledger shows for the stock valuation account
  - Posts the **difference** as a single journal entry

**Example:**
```
Jan 1:  Stock Valuation account balance = $50,000
Jan:    Purchased $12,000 of goods, sold $8,000 of goods (at cost)
        But no JEs were posted during the month
Jan 31: Inventory system says total value = $54,000
        Accounting shows = $50,000 (no changes during month)
        Closing entry:
          Debit:  Stock Valuation  $4,000
          Credit: Stock Variation  $4,000
```

**Automated closing:** In Settings, you can set `inventory_period` to "Daily" or "Monthly" to have a cron job create closing entries automatically.

> **Changed in 20.** The closing engine moved from `stock_account` into `account` ([`action_close_stock_valuation()`](../addons/account/models/company.py#L1278)), the cron record is now `account.ir_cron_post_stock_valuation`, and the entry point is the report button rather than an Inventory menu. The button also asks for **accruals**: with `include_accruals=True` the closing additionally posts (and auto-reverses) accrual entries for goods received-not-billed and delivered-not-invoiced, via the `account.accrued.orders.wizard` -- [`_create_accrual_moves()`](../addons/account/models/company.py#L1346).

---

### Walkthrough 8: Dropship (Supplier Ships Directly to Customer)

**Setup:** Product "Custom Part", AVCO, Perpetual. Route: Dropship.

**Flow:**
1. SO created, generates PO automatically
2. Vendor ships directly to customer (no warehouse receipt)
3. Stock move: Supplier Location -> Customer Location

**Valuation:**
- Move detected as dropship by [`_is_dropshipped()`](../addons/stock_account/models/stock_move.py#L683): `location.usage == 'supplier'` (or a company-less transit location) AND `location_dest.usage == 'customer'` (idem)
- `is_dropship = True`, but `is_in = False` and `is_out = False` (goods never enter company stock)
- Move gets valued like an incoming move: `move.value = _get_value()`
- `standard_price` is updated
- No inventory on balance sheet since goods bypass the warehouse

> **Changed in 20:** `is_valued` is now `is_in or is_out or is_dropship` -- [`_compute_is_valued()`](../addons/stock_account/models/stock_move.py#L111). In 19 dropship moves were not "valued", which is why they were skipped by the journal-entry check. They still produce no stock journal entry, but for a different reason: `_should_create_account_move()` also requires one of the two locations to carry a `valuation_account_id`, and supplier/customer locations do not.

**Return flow:**
- Customer returns to supplier: Customer Location -> Supplier Location
- Detected by [`_is_dropshipped_returned()`](../addons/stock_account/models/stock_move.py#L694)

---

### Walkthrough 9: Customer Return (Reverse Flow)

**Scenario:** Customer returns 10 units from a sale where COGS was $8.67/unit.

**Flow:**
1. Click **Return** on the done delivery; it creates a draft return transfer with every line at 0 ([`_create_return()`](../addons/stock/models/stock_picking.py#L976))
2. Return stock move: Customer Location -> WH/Stock
3. This is an "incoming" move (`is_in = True`)

**Value determination:**
- `_get_value_data()` walks its priority chain and reaches `_get_value_from_returns()`
- If the original outgoing move exists: `value = abs(origin_move.value) * return_qty / origin_valued_qty`
- So returned value = $8.67 * 10 = $86.70 (preserves original cost). The `abs()` is needed because the origin out move's `value` is negative.
- Inventory increases by $86.70

Source: [`_get_value_from_returns()`](../addons/stock_account/models/stock_move.py#L575)

**On credit note:** COGS lines are reversed, moving value back from Expense to Stock Valuation.

---

## When to Use What -- Decision Matrix

| Business Type | Recommended Costing | Recommended Valuation | Why |
|---|---|---|---|
| **Retailer/Trader** | FIFO | Perpetual | You resell what you buy. FIFO tracks actual purchase cost. Perpetual gives real-time COGS. |
| **Manufacturer** | Standard | Perpetual | Planned costs are set in advance. Variances tracked separately. |
| **Food/Commodity** | AVCO | Perpetual | Prices fluctuate constantly. AVCO smooths the cost. |
| **Small Business** | Standard | Periodic | Simple setup. Accountant reconciles at month-end. |
| **Importer** | FIFO + Landed Costs | Perpetual | Each shipment has different costs. Landed costs capture freight/duty. |
| **Wine/Pharma/Serialized** | FIFO or AVCO + Lot Valuation | Perpetual | Different lots have different costs. Need per-lot tracking. |
| **Dropshipper** | Standard | Periodic | Never holds inventory. Valuation is minimal. |

---

## What Accounts Are Involved -- Plain English

Understanding the accounts is crucial. Here are the accounts involved and what each one represents in business terms:

| Account | Type | What it represents | When it changes |
|---|---|---|---|
| **Stock Valuation** (e.g., 1400) | Balance Sheet -- Current Asset | "How much inventory do we own right now?" | Perpetual: debited by vendor bills, credited by COGS lines on customer invoices (credit notes and vendor refunds reverse them). Both modes: Stock Closing entries, and entries of moves that touch a location with a valuation account |
| **COGS / Expense** (e.g., 5100) | Profit & Loss -- Expense | "What did the products we sold this period cost us?" | Perpetual: debited by COGS lines when a customer invoice is posted. Periodic: debited by vendor bills |
| **Price Difference** | P&L -- Expense | "Difference between the standard cost and what we actually paid" | On vendor bills: standard cost, Anglo-Saxon flag and a category Price Difference Account only |
| **Inventory Loss** (the location's Loss Account) | P&L -- Expense | "Value of goods lost/damaged/stolen" | Only when the Inventory adjustment location has a Loss Account (`valuation_account_id`); otherwise the loss reaches the books at the Stock Closing |
| **Stock Variation** | P&L -- Expense | "Change in inventory value not yet in the books" | At the Stock Closing |

There are no Stock Input / Stock Output interim accounts in 20. Receipts and deliveries post nothing ([`_should_create_account_move()`](../addons/stock_account/models/stock_move.py#L755)). Goods received but not billed, or delivered but not invoiced, are covered by the accruals the Stock Closing can post ([`_create_accrual_moves()`](../addons/account/models/company.py#L1346)).

### How Money Flows Through Accounts (Perpetual AVCO)

```
PURCHASE FLOW:
                         Receipt                    Vendor Bill
  Vendor                Validated                    Posted
    |                      |                           |
    |   stock + units      |                           |
    |   move value +$1,000 |                           |
    |   (no journal entry) |     Stock Valuation    <--+-->  Accounts Payable
    |                      |     (Asset) + $1,000          (Liability) + $1,000

SALE FLOW:
                        Delivery                   Customer Invoice
  Customer              Validated                    Posted
    |                      |                           |
    |   stock - units      |                           |
    |   move value -$800   |                           |
    |   (no journal entry) |     Stock Valuation    <--+  (COGS auto-line)
    |                      |     (Asset) - $800        |
    |                      |                           |
    |                      |     COGS Expense       <--+  (COGS auto-line)
    |                      |     (P&L) + $800          |
    |                      |                           |
    |                      |     Revenue            <--+  (Invoice line)
    |                      |     (P&L) + $1,200        |
    |                      |                           |
    |                      |     Accounts Receivable<--+  (Invoice line)
    |                      |     (Asset) + $1,200      |
```

Between the receipt and the bill, and between the delivery and the invoice, the inventory report and the Stock Valuation account disagree. The Stock Closing shows and settles the gap.

### How Money Flows (Perpetual + Anglo-Saxon + Standard Cost -- Purchase Price Difference)

```
PURCHASE FLOW WITH PRICE DIFFERENCE:

  Receipt validated (100 units, standard_price = $9):
    Move value $900. No journal entry.

  Vendor bill posted ($10/unit = $1,000 total):
    Debit:  Stock Valuation  $1,000   (bill line account overridden to stock val)
    Credit: Accounts Payable $1,000

    Auto price diff lines (display_type='cogs'):
    Debit:  Price Difference  $100    (10 - 9 = $1/unit * 100 units)
    Credit: Stock Valuation   $100

  Net effect on Stock Valuation: +$1,000 (bill) -$100 (price diff) = $900 = standard
```

---

## Common Questions from Odoo Users

### Q: I changed the product cost. What happened to existing inventory?

**Standard cost:** Changing `standard_price` immediately changes the displayed total value of your stock. But it does NOT create any journal entry (`product.value` records carry none, see below). The accounting books won't match until the next Stock Closing, in both modes. Selling at the new price does not close the gap: the COGS lines use the new price while the account still holds the old one.

**AVCO:** You normally don't manually change the cost -- Odoo recalculates it on every receipt. If you DO manually change it, Odoo creates a `product.value` record marking the override, and from Odoo 20 it replays the valuation from that date forward, so the out moves after it are re-costed at the new average (and their COGS journal items re-priced in place).

**FIFO:** Manual price changes are ignored on purpose -- `_change_standard_price()` skips FIFO products outright, so no `product.value` record is even created. FIFO always uses the actual receipt costs; `standard_price` is just kept updated for display and for estimating.

### Q: What happens if I sell more than I have (negative stock)?

Odoo allows negative stock if "No Negative Stock" is not enforced. For valuation:
- **FIFO:** Extrapolates cost using the last known receipt price. When goods eventually arrive, the cost may be corrected.
- **AVCO:** Uses the current `standard_price` (the running average). If stock was already at zero, uses the last known average.
- **Standard:** Always uses the fixed price, so negative stock doesn't affect the cost.

**Risk:** Selling into negative stock means your COGS is estimated, not actual. This can lead to corrections later.

### Q: Can I change the costing method after I have transactions?

Technically possible by changing the product category's costing method. Odoo will recompute `standard_price` for all products in that category. However, **this does not rewrite historical journal entries.** Past COGS entries stay as they were. This is a major decision -- do it at the start of a fiscal year with an accountant's guidance.

### Q: What's the difference between "Standard Price" on the product and the actual inventory value?

- `standard_price` is a **per-unit** number on the product card
- `total_value` is the **computed total** value of all stock on hand
- For Standard cost: `total_value = standard_price x qty_on_hand` (always)
- For AVCO: `standard_price` IS the average, so `total_value = standard_price x qty_on_hand`
- For FIFO: `standard_price` is an approximation (total_value / qty_on_hand). The real value comes from the FIFO stack.

### Q: Where do I see the inventory valuation in Odoo?

- **Per product:** `avg_cost` / `total_value` columns on the product list, and the Update Quantity / valuation views
- **Per quant:** Inventory > Reporting > Inventory Valuation (shows `value` per location/lot)
- **Per move:** the `value`, `remaining_qty` and `remaining_value` optional columns on any `stock.move` list, plus the "Aging Report" and "Intercompany Deliveries" saved filters shipped in [stock_move_views.xml](../addons/stock_account/views/stock_move_views.xml)
- **In accounting:** General Ledger for the Stock Valuation account
- **The report:** Accounting > Review > Inventory > Inventory Valuation -- the OWL client action `account.action_report_stock_valuation`, backed by the `account.stock.valuation.report` abstract model. It is also where periodic closing entries are generated.

### Q: When does a vendor bill change the move value?

When `account.move._post()` is called on a vendor bill, it triggers `_set_value()` on the linked incoming stock moves. The `_get_value_data()` priority chain then picks up the bill amount via `_get_value_from_account_move()` (which returns the actual invoiced price), replacing the PO-based estimate. This updates `move.value`, then `_update_standard_price()` adjusts the product's `standard_price`.

Source: [`account_move.py:50`](../addons/stock_account/models/account_move.py#L50) -- `self.line_ids.cogs_move_ids.filtered(lambda m: m.is_in or m.is_dropship)._set_value()`. The same call is made from `button_draft()` and `button_cancel()`, so un-posting a bill reverts the move to its PO-based value.

The bridge between an invoice line and the stock moves that back it is the computed `cogs_move_ids` field: a stub in `stock_account` ([account_move_line.py:14](../addons/stock_account/models/account_move_line.py#L14)) filled in by `purchase_stock`, `sale_stock` and `mrp_subcontracting_purchase`.

---

## Dependencies

### Requires
| Module | Why |
|---|---|
| `stock` | Core inventory engine -- locations, pickings, moves, quants |
| `account` | Journal entries, accounts, fiscal positions |

### Optional Integrations
| Module | What it enables |
|---|---|
| `stock_landed_costs` | Allocates freight/customs/other costs to receipt moves, adjusting their value |
| `purchase_stock` | Supplies `_get_value_from_account_move()` (bill price) and `_get_value_from_quotation()` (PO price), and links bill lines to receipt moves via `cogs_move_ids` |
| `sale_stock` | Links invoice lines to delivery moves via `cogs_move_ids` / `cogs_aml_ids`, so COGS follows the actual delivered moves |
| `mrp` | Production cost valuation (WIP accounts) |

### Provides To
| Consumer | What they use |
|---|---|
| `account.move` | COGS journal items on customer invoices -- `account` builds them and owns the eligibility rule `_use_inventory_valuation()` (extended by `stock_dropshipping`, `repair`, `sale_stock_renting`); `stock_account` supplies the values via `_get_cogs_value()` |
| `stock.quant` | `value` field computed from product valuation |
| `account.stock.valuation.report` | Real move-based figures (and the Inventory Loss section) in place of the `qty_available * standard_price` approximation |
| `account_reports` (enterprise) | The Inventory Valuation menu entry under Accounting > Audit |

---

## Glossary (Quick Reference for Learners)

| Term | Plain English |
|---|---|
| **COGS** | Cost of Goods Sold. The amount you paid for products you sold. Shows on the Profit & Loss as an expense. |
| **Balance Sheet** | A snapshot of what your company OWNS (assets) and OWES (liabilities) at a point in time. Inventory is an asset. |
| **P&L / Income Statement** | Shows revenue minus expenses over a period. COGS is an expense here. Revenue minus COGS = Gross Profit. |
| **Journal Entry (JE)** | A record of a financial transaction. Always has equal debits and credits. For inventory, Odoo creates them from vendor bills, customer invoices (COGS lines), the Stock Closing, and moves that touch a location with a valuation account; receipts and deliveries post none. |
| **Debit / Credit** | Debit = left side, Credit = right side. For assets: debit increases, credit decreases. For expenses: debit increases. For liabilities/revenue: credit increases. |
| **Valued Location** | A location where inventory has monetary value (internal warehouses, transit). Supplier/Customer locations are NOT valued. |
| **Stock Move** | A record of products moving from one location to another. Every pick, delivery, receipt, and transfer creates stock moves. |
| **Perpetual Valuation** | "Perpetual (at invoicing)": bills debit the Stock Valuation account and customer invoices carry COGS lines. Stock moves themselves post nothing. |
| **Periodic Valuation** | Batch accounting. Bills go to expense and invoices carry no COGS. One closing entry per period adjusts the Stock Valuation account. |
| **Standard Price** | The `standard_price` field on a product. For Standard costing = manual fixed cost. For AVCO = running average. For FIFO = display approximation. |

---

> **From here on, the document becomes technical.** The sections below explain HOW Odoo implements the business flows described above -- models, fields, methods, and code traces. Refer back to the walkthroughs if you need context on WHY something works the way it does.

---

## Core Concepts

### Valued Locations

Only locations with `usage` in `['internal', 'transit']` **and** a `company_id` **belonging to the current company** are considered "valued". Everything else (customer, supplier, production, inventory loss, another company's warehouse) is unvalued.

Source: [`_should_be_valued()`](../addons/stock_account/models/stock_location.py#L30)

```
_should_be_valued() = bool(self.company_id) and self.company_id == self.env.company and self.usage in ['internal', 'transit']
```

**Changed in 20:** the `company_id == self.env.company` clause is new, and it is what makes an inter-company transfer look like an *out* for the sender and an *in* for the receiver. Callers must therefore evaluate it in the right company -- `_get_in_move_lines()` / `_get_out_move_lines()` do `move_line.with_company(move_line.company_id)` before asking.

A searchable `is_valued` boolean was added on the location so valuation domains can be expressed in SQL -- [stock_location.py:15](../addons/stock_account/models/stock_location.py#L15).

### Move Direction Detection

| Direction | Condition | Method |
|---|---|---|
| **Incoming** (`is_in`) | Has picked move lines Unvalued -> Valued, and not dropship-returned | [`_is_in()`](../addons/stock_account/models/stock_move.py#L643) |
| **Outgoing** (`is_out`) | Has picked move lines Valued -> Unvalued, and not dropship | [`_is_out()`](../addons/stock_account/models/stock_move.py#L673) |
| **Dropship** (`is_dropship`) | Supplier -> Customer (or via company-less transit on either end) | [`_is_dropshipped()`](../addons/stock_account/models/stock_move.py#L683) |
| **Dropship Return** | Customer -> Supplier (idem) | [`_is_dropshipped_returned()`](../addons/stock_account/models/stock_move.py#L694) |

A move is **valued** (`is_valued`) if `is_in OR is_out OR is_dropship` -- **changed in 20**, dropship used to be excluded. Computed on done moves only.

Source: [`_compute_is_valued()`](../addons/stock_account/models/stock_move.py#L111)

**Direction detection algorithm:** The classification is done line by line, not move by move. [`_get_in_move_lines()`](../addons/stock_account/models/stock_move.py#L623) and [`_get_out_move_lines()`](../addons/stock_account/models/stock_move.py#L653) walk `move_line_ids` and keep the lines that are `picked`, not excluded by ownership, and whose source/destination pass `_should_be_valued()` in the line's own company. A single move can therefore have both in-lines and out-lines (an inter-company transfer, for instance), and `_get_valued_qty()` sums only the lines matching the direction it was asked about.

`is_in` and `is_out` are **stored**, so they are usable in domains and in `_read_group` -- the periodic closing and the aging filters rely on that.

### Consignment Exclusion

Moves with `restrict_partner_id` different from the company's partner are excluded from valuation. This handles consigned goods that the company doesn't own.

Source: [`_should_exclude_for_valuation()`](../addons/stock_account/models/stock_move.py#L766) (move), [`stock_move_line.py:40`](../addons/stock_account/models/stock_move_line.py#L40) (line), [`stock_quant.py:39`](../addons/stock_account/models/stock_quant.py#L39) (quant)

---

## Valuation Methods

### Periodic vs Perpetual

Set at **product category** level (company-dependent) or falls back to **company** default.

| Method | Technical value | UI Label | When journal entries are created |
|---|---|---|---|
| Periodic | `periodic` | "Periodic (at closing)" | Only during manual/scheduled closing |
| Perpetual | `real_time` | "Perpetual (at invoicing)" | Automatically on every stock move + COGS on invoice posting |

**Product Category field:**
- `property_valuation` (Selection, company_dependent): [`account/models/product.py:30`](../addons/account/models/product.py#L30)

**Company default:**
- `inventory_valuation` (Selection, default=`'periodic'`): [`account/models/company.py:343`](../addons/account/models/company.py#L343)

**Product Template computed field:**
- `valuation` -- computed from `categ_id.property_valuation`, falls back to `company.inventory_valuation`: [`account/models/product.py:108`](../addons/account/models/product.py#L108), compute at [`:197`](../addons/account/models/product.py#L197), with a `_search_valuation()` so it can be used in domains.

> **Changed in 20:** all three fields moved from `stock_account` into `account`. `stock_account` no longer defines them at all.

---

## Costing Methods

Set at **product category** level (company-dependent) or falls back to **company** default.

| Method | Technical value | UI Label | How outgoing cost is determined |
|---|---|---|---|
| Standard | `standard` | "Standard Price" | Fixed `standard_price` on product |
| FIFO | `fifo` | "First In First Out (FIFO)" | Oldest incoming move's actual cost consumed first |
| Average | `average` | "Average Cost (AVCO)" | Weighted average recomputed on every receipt |

**Product Category field:**
- `property_cost_method` (Selection, company_dependent): base selection `standard` / `average` in [`account/models/product.py:52`](../addons/account/models/product.py#L52); `fifo` is added by `stock_account` with `selection_add` -- [`product.py:749`](../addons/stock_account/models/product.py#L749)

**Company default:**
- `cost_method` (Selection, default=`'standard'`): [`account/models/company.py:367`](../addons/account/models/company.py#L367), `fifo` added at [`res_company.py:13`](../addons/stock_account/models/res_company.py#L13)

This split is deliberate: `account` alone can value inventory at standard or average cost from invoice quantities, and FIFO only becomes meaningful once `stock` supplies real move history. Changing `company.cost_method` replays the valuation of every affected product since the last closing -- [`res_company.py:18`](../addons/stock_account/models/res_company.py#L18).

---

### Standard Price -- How It Works

The simplest method. A fixed `standard_price` on the product is used for all valuations.

**Incoming move value:**
```
move.value = standard_price * quantity
```

**Outgoing move value:**
```
move.value = - standard_price * quantity
```

**When standard_price changes:** A `product.value` record is created to track the history. This does NOT retroactively change existing move values.

Source: [`_change_standard_price()`](../addons/stock_account/models/product.py#L213) -- **changed in 20**: it now takes a `{product: old_price}` dict (so a multi-product `write()` is handled in one pass) plus an optional `valuation_date`, and it stores the full before/after picture on the `product.value` record (`quantity`, `old_cost`, `new_cost`, `old_value`, `new_value`).

**Historical price lookup:** `_get_standard_price_at_date()` no longer exists. For reporting at a past date, [`_run_standard(at_date=...)`](../addons/stock_account/models/product.py#L337) resolves the price through [`_get_last_product_value()`](../addons/stock_account/models/product.py#L283), which picks the newest `product.value` row per product at or before that date with a single `DISTINCT ON` query.

**Example:**
```
Product "Widget A" -- Standard Price: $10

Receipt: 100 units from Supplier
  move.value = $10 * 100 = $1,000

Delivery: 30 units to Customer
  move.value = $10 * 30 = $300

Change standard price to $12
  product.value record created (old=$10, new=$12)

Next delivery: 20 units
  move.value = $12 * 20 = $240
```

---

### FIFO -- How It Works

Builds a stack of incoming moves ordered oldest-first. Outgoing moves consume from the oldest layer.

> **Changed in 20 -- three methods where 19 had two.** `_run_fifo(quantity)` was split. `_run_fifo()` now values a *whole recordset of products* for reporting, `_get_fifo_value()` answers "what does this next outgoing quantity cost", and the stack builder was renamed.

| Method | Signature | Returns | Used for |
|---|---|---|---|
| [`_run_fifo()`](../addons/stock_account/models/product.py#L507) | `(at_date=None, lot=None, correction=False)` | `({product_id: unit_price}, {product_id: total_value})` | `total_value` / `avg_cost` on a batch of products; with `correction=True` it *replays* and rewrites out-move values |
| [`_get_fifo_value()`](../addons/stock_account/models/product.py#L616) | `(quantity, lot=None, stack_size_extra_qty=0)` | a single float cost | valuing one outgoing move |
| [`_get_fifo_stack()`](../addons/stock_account/models/product.py#L655) | `(lot=None, at_date=None, allow_negative=False, stack_size_extra_qty=0)` | `([moves oldest-first], qty_on_first_move)` | building the stack itself (was `_run_fifo_get_stack()`) |

**Consumption algorithm** (`_get_fifo_value`):
1. Build the stack with `_get_fifo_stack()`
2. Pop moves from the stack (oldest first), accumulating cost until the requested quantity is consumed
3. If quantity exceeds available stock, extrapolate using the last popped move's unit price (or `standard_price` if the stack was empty)

**Stack construction** (`_get_fifo_stack`):
1. Determine `fifo_stack_size` = `qty_available` in the valuation context, **plus `stack_size_extra_qty`**
2. Search moves ordered by `date desc, id desc` (newest first) -- `is_in` moves normally
3. Walk backwards from newest until accumulated quantity >= `fifo_stack_size`
4. Reverse the stack so oldest is first
5. Return `remaining_qty_on_first_stack_move` for partial consumption of the bottom layer

**New in 20 -- negative stacks.** If on-hand is negative (oversold), `allow_negative=True` makes the method build a stack of the *outgoing* moves that created the shortage, with negative quantities. A later incoming move can then find those moves and re-cost them retroactively. Without the flag the stack comes back empty and the caller extrapolates instead.

**Why search newest-first then reverse?** Performance. The FIFO stack only needs the most recent incoming moves that account for current on-hand quantity. By searching newest-first, Odoo stops as soon as it has enough moves to cover `qty_available`. This avoids loading the entire purchase history.

**Performance:** Fetches in pages of 100 moves to avoid loading everything at once.

**Outgoing move valuation:** [`_set_value()`](../addons/stock_account/models/stock_move.py#L345)
```python
valued_qty = move._get_valued_qty()
move.value = - move.product_id._get_fifo_value(
    valued_qty, stack_size_extra_qty=-fifo_qty_already_processed[move.product_id]
)
fifo_qty_already_processed[move.product_id] += valued_qty
```

**Changed in 20:** the `fifo_qty_already_processed` *context key* is gone. `_set_value()` keeps a local tally and passes it as the `stack_size_extra_qty` argument. It also pre-seeds that tally with every out move in the batch before valuing any of them, so the stack is read as it stood *before* the batch -- this is what replaces the old "value the outs before `super()._action_done()`" trick.

**Standard price update after FIFO out:** After outgoing moves, `standard_price` is updated to `total_value / qty_available`. If no stock remains, it uses the last incoming move's unit price.

Source: [`_update_standard_price()`](../addons/stock_account/models/product.py#L716)

**Example:**
```
Receipt #1: 50 units @ $8 each = $400
Receipt #2: 30 units @ $12 each = $360
Receipt #3: 20 units @ $10 each = $200
  Total stock: 100 units, total value: $960

Delivery: 60 units
  FIFO consumes:
    50 units from Receipt #1 @ $8 = $400
    10 units from Receipt #2 @ $12 = $120
  move.value = $520

  Remaining stack:
    20 units from Receipt #2 @ $12 = $240
    20 units from Receipt #3 @ $10 = $200
  standard_price updated: $440 / 40 = $11.00
```

---

### Average Cost (AVCO) -- How It Works

Recomputes a weighted average from all incoming and outgoing moves in chronological order.

**Key method:** [`_run_avco(at_date=None, lot=None, force_recompute=None, correction=False)`](../addons/stock_account/models/product.py#L370)

**Returns:** `({product_id: avco_unit_value}, {product_id: avco_total_value})` -- **changed in 20**, it works on a recordset and returns dicts keyed by product id, not a scalar tuple.

**Fast path:** with neither `at_date` nor `force_recompute`, it does not replay anything -- it trusts the stored `standard_price` and returns `qty_available * standard_price`. The replay only runs for historical dates, for an explicit recompute, or for a correction.

**Algorithm (replay):**
1. Seed from the latest `product.value` manual update at or before `at_date`, if any, and restrict the move search to moves after it
2. Load all `is_in` / `is_dropship` / `is_out` moves in `date, id` order, in batches of 50,000 with model-cache invalidation between batches (millions of moves are expected)
3. Process chronologically:
   - **On incoming/dropship move:** add quantity and value, recalculate the average `avco_value = value / quantity`
   - **On outgoing move:** deduct quantity and proportional value `out_value = out_qty * avco_value`
   - **On a price change** (`correction=True` only): override `avco_value` and recompute the running total
4. Handle negative stock: when `previous_qty <= 0`, reset the average to the incoming move's unit price instead of averaging
5. With `correction=True`, write the recomputed value back onto each out move

**Outgoing move valuation:** For AVCO, outgoing moves use `- standard_price * quantity` (since `standard_price` is kept in sync with the running average). With `lot_valuated`, each move line uses its own `lot_id.standard_price`.

Source: [`_set_value()`](../addons/stock_account/models/stock_move.py#L345)

**Standard price update after AVCO receipt:** After incoming moves, `standard_price` is set from `_run_avco(force_recompute=True)[0]` (the current unit average).

Source: [`_update_standard_price()`](../addons/stock_account/models/product.py#L716)

**AVCO and negative stock:** When stock goes to zero or negative, the average cost is "frozen" at the last known value. When new stock arrives, the average resets to the incoming move's unit price (because there's nothing to average against). This can cause cost jumps -- a common source of confusion.

**Example:**
```
Receipt #1: 100 units @ $10 = $1,000
  avco_value = $10.00, total = $1,000
  standard_price updated to $10.00

Receipt #2: 50 units @ $16 = $800
  avco_total = $1,000 + $800 = $1,800
  avco_value = $1,800 / 150 = $12.00
  standard_price updated to $12.00

Delivery: 80 units
  move.value = $12.00 * 80 = $960
  avco_total = $1,800 - $960 = $840
  quantity = 70
  avco_value stays $12.00

Receipt #3: 30 units @ $15 = $450
  avco_total = $840 + $450 = $1,290
  avco_value = $1,290 / 100 = $12.90
  standard_price updated to $12.90
```

---

### Comparison of Costing Methods

| Aspect | Standard | FIFO | AVCO |
|---|---|---|---|
| `standard_price` meaning | Manually set cost | Approximation: `total_value / qty_available` | Running weighted average (authoritative) |
| Updated when? | Manual only | After outgoing moves | After incoming moves |
| Outgoing value formula | `standard_price * qty` | Stack-based (oldest first) | `standard_price * qty` |
| Incoming value source | Priority chain (bill > PO > std price) | Priority chain (bill > PO > std price) | Priority chain (bill > PO > std price) |
| Landed costs? | Allocated but does not change the unit cost | Supported | Supported |
| Negative stock handling | Uses fixed price (safe) | Extrapolates from last receipt (risky) | Uses frozen average (risky) |
| Performance | Fastest | Slowest (stack computation) | Medium |
| Accuracy | Low (manual) | Highest (actual costs) | Medium (smoothed) |

---

## Incoming Move Value Priority

When computing the value of an incoming move, Odoo checks sources in this priority order:

| Priority | Source | Method | When used |
|---|---|---|---|
| 1 | Manual override | [`_get_manual_value()`](../addons/stock_account/models/stock_move.py#L551) | User created a `product.value` record for this move |
| 2 | Vendor bill | [`_get_value_from_account_move()`](../addons/stock_account/models/stock_move.py#L567) | Posted bill linked to the move (overridden in `purchase_stock`, `mrp_subcontracting_purchase`, `mrp_subcontracting_dropshipping`) |
| 3 | Production | [`_get_value_from_production()`](../addons/stock_account/models/stock_move.py#L570) | Manufacturing order cost (overridden in `mrp_account`) |
| 4 | PO/SO line | [`_get_value_from_quotation()`](../addons/stock_account/models/stock_move.py#L573) | Purchase order line price (overridden in `purchase_stock`) |
| 5 | Return origin | [`_get_value_from_returns()`](../addons/stock_account/models/stock_move.py#L576) | Proportional value from the original outgoing move |
| 6 | **Previous company** | [`_get_value_from_previous_company()`](../addons/stock_account/models/stock_move.py#L605) | **New in 20** -- inter-company transfer: carries over the value of the single originating move from the other company (sign-flipped, since that move was an *out*) |
| 7 | Standard price | [`_get_value_from_std_price()`](../addons/stock_account/models/stock_move.py#L587) | Fallback: `standard_price * quantity` (or the lot's price when the move has exactly one lot) |
| 8 | Extra costs | [`_get_value_from_extra()`](../addons/stock_account/models/stock_move.py#L617) | Landed costs (overridden in `stock_landed_costs`) |

Full logic: [`_get_value_data()`](../addons/stock_account/models/stock_move.py#L442)

Each source returns `{'value': float, 'quantity': float, 'description': str}`. The system works through the priority list, reducing `remaining_qty` at each step. If a manual update covers the full quantity, extra costs are skipped.

**Changed in 20:** every method in this chain lost its `at_date` parameter, and `_get_value_data()` lost it too. Point-in-time valuation is no longer done by re-deriving each move's value at a date -- it is done by replaying the whole product timeline (`_run_avco` / `_run_fifo` with `at_date`), which is both cheaper and consistent.

**Important detail:** the last step (extra costs from landed costs) is additive -- it uses the full `valued_qty`, not `remaining_qty`. It adds ON TOP of whatever base value was determined. However, if a manual override covers the full quantity (`add_extra_value` becomes `False`), extra costs are skipped.

**The descriptions are user-facing.** Each step appends a sentence, and the concatenation ends up in `move.value_justification`, shown on the Adjust Valuation dialog so a user can see *why* a move is worth what it is worth.

---

## Business Flow -- Perpetual Valuation

```
Stock Move Done  -->  _action_done()  -->  _set_value()  -->  _create_account_move()
       |                                       |                       |
       |                              Compute move.value        Create JE if:
       |                              using cost method         - product.is_storable
       |                              (signed: out is < 0)      - move.is_valued
       |                                       |                - location has valuation_account_id
       |                                       |                - quantity is not zero
       |                                       v                - product.valuation == 'real_time'
       |                              _update_standard_price()
       |                              (FIFO & AVCO only)
       |                                       |
       |                                       v
       |                              cogs_aml_ids._set_cogs()
       |                              (re-price COGS lines already posted)
       v
Invoice Posted  -->  account.move._post()  -->  _create_cogs_lines()   [in `account`]
                                           |
                                   Create COGS lines (display_type='cogs')
                                   Debit: Expense/COGS account
                                   Credit: Stock Valuation account
```

### Step-by-Step: `_action_done()`

Source: [`stock_move.py:248`](../addons/stock_account/models/stock_move.py#L248)

1. `self = self.sudo()` -- valuation reads accounts and product costs the operator may not have access to
2. Call `super()._action_done()` (marks moves as done, updates quants, finalises move lines)
3. `moves_out._set_value()` -- outgoing moves
4. `moves_in._set_value()` -- incoming and dropship moves
5. `moves.cogs_aml_ids._set_cogs()` -- re-price COGS journal items on already-posted invoices whose backing moves just got a value
6. `_create_account_move()` -- create journal entries for real-time valued moves
7. `_create_analytic_move()` -- analytic lines for in and out moves

> **Changed in 20 -- the ordering flipped.** Odoo 19 valued outgoing moves *before* `super()._action_done()`, so that the FIFO stack was read before incoming moves in the same batch changed it. That ordering is gone. `super()` now always runs first, and the batch problem is solved differently: `_set_value()` walks its out moves once to build a `fifo_qty_already_processed` tally, then passes the negated tally as `stack_size_extra_qty` so `_get_fifo_stack()` reconstructs the stack as it stood before the batch. Anything the tally cannot express -- a backdated move, an oversell that a later receipt has to re-cost -- is handled by the replay path described below.
>
> The practical consequence: `standard_price` is no longer bumped incrementally through a `std_price_incremental_recompute` context key (removed in 20); `_update_standard_price()` recomputes from the current state.

### The replay path (new in 20)

`_set_value(recompute_date=None, skip_check=False)` -- [stock_move.py:345](../addons/stock_account/models/stock_move.py#L345) -- does more than assign a number. Before valuing anything it checks whether any of the moves it was handed is an incoming move whose `remaining_qty` no longer equals its valued quantity, i.e. part of it has already been sold. If so, re-valuing it in isolation would leave the out moves that consumed it costed against the old price. It therefore:

1. picks the earliest impacted date as `recompute_date` (for FIFO, extending it back to cover any oversold out moves that a receipt has to re-cost),
2. refreshes the in-move values with `skip_check=True`,
3. calls [`_correct_inventory_valuation(from_date)`](../addons/stock_account/models/product.py#L247), which replays `_run_standard` / `_run_avco` / `_run_fifo` with `correction=True` from that date forward and **rewrites the value of every affected out move**.

This is what makes the following safe in 20, all of which were lossy or unsupported in 19: editing a done move's date ([`write()`](../addons/stock_account/models/stock_move.py#L181)), adjusting a move's value by hand (`product.value`), a vendor bill arriving after the goods were already sold, and resetting a manufacturing order to draft or in progress ([`_action_reset_to_draft()`](../addons/stock_account/models/stock_move.py#L797), which also deletes the stock journal entries). Transfers have no reset: only [`mrp_production.py:2039`](../addons/mrp/models/mrp_production.py#L2039) calls these methods.

### Journal Entry Creation

Source: [`_create_account_move()`](../addons/stock_account/models/stock_move.py#L260)

**Eligibility check** [`_should_create_account_move()`](../addons/stock_account/models/stock_move.py#L756):
- Product is storable
- Move is valued (`is_in`, `is_out` or `is_dropship`)
- At least one location (source or destination) has `valuation_account_id`
- Moved quantity is not zero
- Product valuation is `'real_time'`

One `account.move` is created per `_action_done()` batch (not per stock move), its `ref` being the joined move references truncated to 43 characters, and each contributing move gets `account_move_id` set.

**Account determination** [`_get_account_move_line_vals()`](../addons/stock_account/models/stock_move.py#L296):

| Scenario | Debit Account | Credit Account |
|---|---|---|
| Source location has `valuation_account_id` | Product's Stock Valuation account | Source location's `valuation_account_id` |
| Dest location has `valuation_account_id` | Dest location's `valuation_account_id` | Product's Stock Valuation account |

The debit/credit amount is `value if is_in else -value`, which turns the signed `move.value` back into a positive figure. The journal entry is auto-posted immediately.

**Journal used:** `company.account_stock_journal_id` (not the category-level `property_stock_journal`). Source: [`stock_move.py:278`](../addons/stock_account/models/stock_move.py#L278)

**Entry date:** `context['force_period_date']` if set (that is how a quant's `accounting_date` is honoured), otherwise today.

---

## Business Flow -- Periodic Valuation

No journal entries are created during stock moves. Instead, a closing process compares inventory value vs accounting value and posts the difference.

> **Changed in 20:** the whole closing engine now lives in `account`, so a database without `stock` can still close its inventory (on a `qty_available * standard_price` approximation). `stock_account` overrides a handful of hooks to substitute the real move-based numbers.

### Closing Process

Source: [`action_close_stock_valuation()`](../addons/account/models/company.py#L1278), which delegates the line building to [`_action_close_stock_valuation()`](../addons/account/models/company.py#L1434).

Three sub-steps run in sequence, each returning journal item values that are appended to the same entry:

| Step | Method | What it does |
|---|---|---|
| 1. Extra entries (location reclassification) | [`_get_extra_closing_aml_vals()`](../addons/account/models/company.py#L1592), overridden in `stock_account` to call [`_get_location_valuation_vals()`](../addons/stock_account/models/res_company.py#L82) | For locations with `valuation_account_id` (inventory loss, scrap, production): `_read_group`s move values since the last closing per location + product category and reclassifies them |
| 2. Stock variation global | [`_get_stock_valuation_account_vals()`](../addons/account/models/company.py#L1489) | Compares inventory value ([`get_inventory_value()`](../addons/account/models/company.py#L1377), overridden at [res_company.py:36](../addons/stock_account/models/res_company.py#L36)) against the accounting balance ([`get_inventory_accounting_value()`](../addons/account/models/company.py#L1420)) and posts the difference to the variation account |
| 3. Continental perpetual variation | [`_get_continental_realtime_variation_vals()`](../addons/account/models/company.py#L1522) | For perpetual + continental: posts the inventory variation over the fiscal period to the variation/expense accounts |

The entry is created on `company.account_stock_journal_id` with `inventory_closing=True`, and the closing raises a clear `UserError` if that journal or `account_stock_valuation_id` is not configured.

**Accruals (new in 20).** When called with `include_accruals=True` -- which is what the report's button does -- the closing also drives [`_create_accrual_moves()`](../addons/account/models/company.py#L1346): for each accrual section (bills to receive, billed-not-received, invoices to issue, invoiced-not-delivered, supplied by `purchase`/`sale` through `_get_accrual_candidate_lines()`) it runs the `account.accrued.orders.wizard` and posts an auto-reversing entry. The ordering matters and is documented in the source: with real stock valuation the accrual is posted **before** the closing is computed; without it, **after**.

### Automated Closing (Cron)

Source: [`_cron_post_stock_valuation()`](../addons/account/models/company.py#L1447)

| `inventory_period` | UI Label | Frequency |
|---|---|---|
| `manual` | "Manual" | Never (user clicks the report button) |
| `daily` | "Daily" | Every day |
| `monthly` | "Monthly" | Last day of each month |

Cron job record: `account.ir_cron_post_stock_valuation` (moved from `stock_account` in 20) -- calls `res_company._cron_post_stock_valuation()`, which only picks companies whose `inventory_valuation != 'real_time'`.

**Closing date tracking -- changed in 20.** The last closing date is no longer an `ir.config_parameter`. It is read from the most recent *posted* `account.move` carrying `inventory_closing = True` -- [`_get_last_closing_move()`](../addons/account/models/company.py#L1610). `account` reads its `date`; `stock_account` overrides [`_get_closing_date_field()`](../addons/stock_account/models/res_company.py#L73) to read `closing_datetime` instead, because stock moves are timestamped and a day's granularity is not enough. Only moves after that instant are included in the next closing. Cancelling a closing entry therefore genuinely re-opens the period.

---

## COGS on Customer Invoices (Perpetual)

When a customer invoice is posted, Odoo auto-generates two additional journal lines per eligible product line. Eligibility depends on perpetual valuation, not on the Anglo-Saxon flag.

> **Changed in 20 -- ownership moved to `account`.** `_stock_account_prepare_realtime_out_lines_vals()` no longer exists. `account.move._post()` calls [`_create_cogs_lines()`](../addons/account/models/account_move.py#L5966), which builds *both* the customer-invoice COGS lines ([`_get_cogs_lines_vals()`](../addons/account/models/account_move.py#L6020)) and the vendor-bill price difference lines ([`_get_price_difference_lines_vals()`](../addons/account/models/account_move.py#L6064)). `stock_account` contributes only the numbers and the eligibility rule.

**Conditions** (in `_get_cogs_lines_vals()`):
- Invoice is a sale document (`is_sale_document(include_receipts=True)`)
- The line passes `_use_inventory_valuation()`
- Both a stock valuation account and an expense account resolve (the journal's default account is the expense fallback)
- The resulting balance and unit price are not zero

### COGS Value Computation

Source: [`_get_cogs_value()`](../addons/stock_account/models/account_move_line.py#L80) (the `stock_account` override; the base in `account` simply returns `product.standard_price`)

The COGS unit price is determined by:
1. No product, or zero quantity: fall back to the line's own `price_unit`
2. If the line has backing stock moves (`cogs_move_ids`): `moves._get_price_unit(include_consigned=True, product=...)`
   - the moves' signed `value` divided by their signed quantity, which yields the actual FIFO/AVCO cost
   - `include_consigned=True` divides by the *full* moved quantity, so the consigned share (which carries no value) generates no COGS
   - for a kit, `product` is required and its `standard_price` is used instead
3. If no stock moves: `product.standard_price` for Standard/AVCO, `product._get_fifo_value(qty) / qty` for FIFO
4. Final: `abs(price_unit * cogs_qty / line_quantity_uom)`, where `_get_cogs_qty()` flips the sign for `out_refund`

Source for the move-side price: [`_get_price_unit()`](../addons/stock_account/models/stock_move.py#L321) -- **new in 20**, it replaces `_get_cogs_price_unit()`. `_get_price_unit_delivery()` ([`stock_move.py:808`](../addons/stock_account/models/stock_move.py#L808), used by `sale_stock_margin`) and `_get_price_unit_dropshipped()` ([`:823`](../addons/stock_account/models/stock_move.py#L823)) still exist.

### Re-pricing already-posted COGS

New in 20. A move's value can change *after* the invoice is posted -- a late vendor bill, a landed cost, a manual adjustment. [`_set_cogs()`](../addons/stock_account/models/account_move_line.py#L50) walks the `cogs_origin_id` back to the invoice line, recomputes the price, and rewrites the two existing COGS journal items in place (with `check_move_validity=False`, since both sides move symmetrically). It is triggered from `stock.move.write()` when `value` changes and from `_action_done()`.

### Eligible for Stock Account

Source: [`_use_inventory_valuation()`](../addons/account/models/account_move_line.py#L3818) in `account`, extended by [`stock_dropshipping`](../addons/stock_dropshipping/models/account_move_line.py#L7), [`repair`](../addons/repair/models/account_move_line.py#L19) and `sale_stock_renting`. `stock_account` does not override it.

> **Renamed in 20:** this was `_eligible_for_stock_account()`.

Returns `True` only if:
- Product is storable (`is_storable`) -- base check
- Product `valuation == 'real_time'` -- base check (**new**: the perpetual test is part of the predicate now, not a separate condition)
- ALL linked stock moves are NOT dropshipped -- `stock_dropshipping` check
- (`repair` adds a further exclusion for already-accounted lines)

Dropshipped products don't get COGS lines because they never enter the company's stock.

### Purchase Bill Account Override

For vendor bills with real-time valuation, the invoice line account is overridden from the expense account to the stock valuation account. This defers the expense until goods are sold.

Source: [`_compute_account_id()`](../addons/account/models/account_move_line.py#L725) (the stock branch is at [`:790`](../addons/account/models/account_move_line.py#L790)) -- **moved to `account` in 20**, gated on the same `_use_inventory_valuation()` predicate.

**Example:** Buy product for $9, sell for $10.

**Original invoice lines:**

| Account | Debit | Credit |
|---|---|---|
| 101200 Account Receivable | 10.00 | |
| 200000 Product Sales | | 10.00 |

**Auto-generated COGS lines** (`display_type='cogs'`):

| Account | Debit | Credit |
|---|---|---|
| 500000 COGS (expense) | 9.00 | |
| 110100 Stock Valuation | | 9.00 |

**On draft/cancel:** COGS lines are automatically deleted -- by `account.move.button_draft()` itself, with `stock_account.button_cancel()` repeating the unlink defensively because it can be reached over RPC. Both also re-run `_set_value()` on the backing incoming moves, so the move falls back to its PO-based value.

Source: [`button_draft()`](../addons/stock_account/models/account_move.py#L54), [`button_cancel()`](../addons/stock_account/models/account_move.py#L60)

**On posting:** Incoming move values are also recomputed (vendor bill amounts become known).

Source: [`_post()`](../addons/stock_account/models/account_move.py#L40)

---

## Key Models

### `stock.move` -- Valuation Fields
> [`stock_move.py`](../addons/stock_account/models/stock_move.py)

| Field | Type | Purpose |
|---|---|---|
| `value` | Monetary | Current monetary value of the move, **signed**: positive in, negative out. Zero if not valued. |
| `value_justification` | Text (computed) | Human-readable description of how value was determined |
| `value_computed_justification` | Text (computed) | Description of computed vs actual value difference |
| `value_manual` | Monetary (computed, inverse) | User-adjustable value, creates `product.value` on write |
| `remaining_qty` | Float (computed, searchable) | Quantity still in stock (from the FIFO stack position) |
| `remaining_value` | Monetary (computed) | Value of remaining quantity |
| `is_in` | Boolean (computed, stored) | True if the move has picked lines Unvalued -> Valued |
| `is_out` | Boolean (computed, stored) | True if the move has picked lines Valued -> Unvalued |
| `is_dropship` | Boolean (computed, stored) | True if supplier -> customer (or the return of one) |
| `is_valued` | Boolean (computed) | `is_in OR is_out OR is_dropship` |
| `cogs_aml_ids` | Many2many(account.move.line) | **New in 20.** Posted COGS journal items whose value derives from this move; stub here, filled by `sale_stock`. Used to re-price them when the move's value changes. |
| `origin_company_id` | Many2one(res.company) (computed, searchable) | **New in 20.** Set when the move comes from another company's document. Stub here, filled by `sale_stock` / `purchase_stock`. |
| `order_partner_id` | Many2one(res.partner) (computed, `compute_sql`) | **New in 20.** The originating company's partner for an inter-company move, otherwise the move's partner. `compute_sql` makes it groupable in the Intercompany Deliveries pivot without storing it. |
| `product_value_ids` | One2many(product.value) | Manual value adjustments recorded against this move |
| `account_move_id` / `invoice_line_ids` | Many2one / One2many | The stock journal entry created for this move, and the invoice lines pointing at it |
| `price_unit` | Float | Legacy field (to be removed, use `value`) |
| `standard_price` | Float (computed) | `product_id.with_company(move.company_id).standard_price` |
| `to_refund` | Boolean | Trigger SO/PO quantity update on returns. **Changed in 20:** the `stock.return.picking` wizard extension that propagated it was deleted; it is now carried by [`stock.picking._prepare_return_move_default_values()`](../addons/stock_account/models/stock_picking.py#L34). No view shows the field in 20, so every return updates SO/PO quantities. |

**`remaining_qty` and `remaining_value`** -- These represent how much of an incoming move's quantity is still in stock (not consumed by outgoing FIFO moves). For FIFO, this drives the stack and `remaining_value` is prorated from `move.value`. For AVCO/Standard, `remaining_value = remaining_qty * standard_price`. Neither is stored, so `stock.move` overrides [`_read_group_select()`](../addons/stock_account/models/stock_move.py#L198) / [`_read_group_postprocess_aggregate()`](../addons/stock_account/models/stock_move.py#L207) to sum them in Python -- that is what makes the Aging Report pivot work.

---

### `product.value` -- Price History & Manual Adjustments
> [`product_value.py`](../addons/stock_account/models/product_value.py)

Tracks manual value updates for products, lots, and individual moves. This is the cost history: **Inventory → Reporting → Valuation Adjustments**, shown in developer mode only ([`valuation_adjustments_menu`](../addons/stock_account/views/product_value_views.xml#L80), `base.group_no_one`).

| Field | Type | Purpose |
|---|---|---|
| `product_id` | Many2one(product.product) | Related product |
| `lot_id` | Many2one(stock.lot) | Optional lot-specific value |
| `move_id` | Many2one(stock.move) | Optional move-specific override |
| `value` | Monetary | New unit price (for product/lot) or total value (for move) |
| `quantity`, `old_cost`, `new_cost`, `old_value`, `new_value` | Float / Monetary | **New in 20.** The full before/after snapshot, filled in `create()`. `adjustment` is the computed delta. |
| `date` | Datetime | When the change was made |
| `user_id` | Many2one(res.users) | Who made the change |
| `description` | Char | Auto-generated sentence naming the old/new value, quantity and user |
| `account_move_id` | Many2one(account.move) | **New in 20.** Declared (with an "open entry" action), but nothing in 20.0 writes it: a value adjustment books no journal entry; the difference reaches the books at the Stock Closing |
| `current_value_details`, `current_value_description`, `computed_value_description` | computed, display-only | What the move is currently worth and why -- surfaced on the Adjust Valuation dialog so the user sees the justification before overriding it |

**On create -- changed in 20:** it no longer just re-values the targeted moves. For a move-level record it calls `moves._set_value(recompute_date=...)`; for a product/lot-level record it first resolves the affected moves through `_get_fifo_stack()`. Either way the replay path runs, so every downstream out move is re-costed from that date forward.

Source: [`create()`](../addons/stock_account/models/product_value.py#L90)

**Role in AVCO:** Manual `product.value` records act as "price resets" in the AVCO timeline. `_run_avco()` seeds its replay from the newest one at or before the requested date and, in correction mode, applies each later one as it walks the moves.

**Role in Standard:** When `standard_price` is changed, `_change_standard_price()` creates a `product.value` record, which is how [`_run_standard(at_date=...)`](../addons/stock_account/models/product.py#L337) can answer "what was the cost on that date".

---

### `product.product` -- Valuation Computed Fields
> [`product.py`](../addons/stock_account/models/product.py)

| Field | Type | Purpose |
|---|---|---|
| `avg_cost` | Monetary (computed) | Average cost per unit |
| `total_value` | Monetary (computed) | Total inventory value |
| `company_currency_id` | Many2one (computed) | Company currency |

**Value computation** [`_compute_value()`](../addons/stock_account/models/product.py#L99):
- Products are bucketed by cost method and valued in batches: `_run_standard()`, `_run_avco()`, `_run_fifo()` -- each returning `{product_id: unit_price}, {product_id: total_value}`
- Lot-valuated products are handled first, by summing their lots' `total_value`
- Runs once per company in `self.env.companies` and converts each company's figure into the current company's currency, so a multi-company user sees a consolidated value
- Supports `to_date` context for historical valuation (a plain date is widened to end-of-day)
- Supports `warehouse_id` context for warehouse-scoped valuation -- the total is computed company-wide and then prorated by the warehouse's share of `qty_available`

---

### `product.template` -- Valuation Configuration Fields
> [`product.py`](../addons/stock_account/models/product.py)

| Field | Type | Defined in | Purpose |
|---|---|---|---|
| `cost_method` | Selection (computed) | [`account`](../addons/account/models/product.py#L116), `fifo` added by [`stock_account`](../addons/stock_account/models/product.py#L21) | From `categ_id.property_cost_method` or `company.cost_method` |
| `valuation` | Selection (computed, searchable) | [`account`](../addons/account/models/product.py#L108) | From `categ_id.property_valuation` or `company.inventory_valuation` |
| `lot_valuated` | Boolean (computed, stored, editable) | [`stock_account`](../addons/stock_account/models/product.py#L24) | Enable per-lot cost tracking. Forced off when the product is not lot/serial tracked; enabling it is refused if any valued on-hand quant has no lot. |

`property_price_difference_account_id` is a **product category** field, not a template field -- see the Account Configuration section.

---

### `stock.lot` -- Lot-Level Valuation
> [`stock_lot.py`](../addons/stock_account/models/stock_lot.py)

When `product_template.lot_valuated = True`, each lot/serial gets its own cost tracking.

| Field | Type | Purpose |
|---|---|---|
| `standard_price` | Float (company_dependent) | Cost per unit for this lot |
| `avg_cost` | Monetary (computed, stored) | Average cost per unit |
| `total_value` | Monetary (computed) | Total inventory value for this lot |
| `lot_valuated` | Boolean (related) | From `product_id.lot_valuated` |

**Lot valuation logic** [`_compute_value()`](../addons/stock_account/models/stock_lot.py#L23):
- Standard (or nothing on hand company-wide): `lot.standard_price * qty_valued`
- AVCO: `product._run_avco(lot=lot, force_recompute=True)[1]` -- lot-filtered weighted average
- FIFO: `product._run_fifo(lot=lot)[1]` -- lot-filtered FIFO stack
- In both cases the company-wide figure is prorated by `qty_valued / qty_available`, so a `warehouse_id` context narrows it correctly

**On lot creation:** If the product is lot-valuated, the lot inherits `product.standard_price`.

Source: [`create()`](../addons/stock_account/models/stock_lot.py#L48)

**Writing a lot's cost** creates a `product.value` row (AVCO only) through [`_change_standard_price()`](../addons/stock_account/models/stock_lot.py#L81), and [`_update_standard_price()`](../addons/stock_account/models/stock_lot.py#L66) is what keeps it in sync after each move.

**How lot valuation changes outgoing moves:** In `_set_value()`, when `product.lot_valuated = True`, outgoing moves iterate over `move_line_ids` and price each line by its lot. For FIFO that means a per-lot `_get_fifo_value()` call with its own `stack_size_extra_qty` tally; for Standard/AVCO it is `lot_id.standard_price * quantity_product_uom`.

Source: [`_set_value()`](../addons/stock_account/models/stock_move.py#L345)

---

### `stock.quant` -- Quant-Level Value
> [`stock_quant.py`](../addons/stock_account/models/stock_quant.py)

| Field | Type | Purpose |
|---|---|---|
| `value` | Monetary (computed) | Quant's proportional value |
| `accounting_date` | Date | Override date for inventory adjustment JEs |
| `cost_method` | Selection (computed) | From product category |

**Value computation** [`_compute_value()`](../addons/stock_account/models/stock_quant.py#L48):
```
quant.value = quant.quantity * (product.total_value / product.qty_available)
```
For lot-valuated products, uses lot-level `total_value` and `product_qty` instead.

**Exclusions:** Returns 0 if location is not valued, owner is not the company (consignment), quantity is zero.

`value` is not stored, so `stock.quant` overrides [`_read_group_select()`](../addons/stock_account/models/stock_quant.py#L67) to sum it in Python -- otherwise the Inventory Valuation list could not show a total.

**Inventory adjustments:** When `_apply_inventory()` is called, it respects `accounting_date` for the journal entry date via the `force_period_date` context, and names the resulting move `... [Accounted on <date>]`.

Source: [`_apply_inventory()`](../addons/stock_account/models/stock_quant.py#L80)

---

### `stock.landed.cost` -- Landed Costs
> [`stock_landed_cost.py`](../addons/stock_landed_costs/models/stock_landed_cost.py)

| Field | Type | Purpose |
|---|---|---|
| `name` | Char | Auto-sequence (LC/YYYY/####) |
| `date` | Date | Landed cost date |
| `picking_ids` | Many2many(stock.picking) | Target transfers |
| `cost_lines` | One2many(stock.landed.cost.lines) | Individual cost items |
| `valuation_adjustment_lines` | One2many(stock.valuation.adjustment.lines) | Computed per-product adjustments |
| `state` | Selection | `draft` / `done` / `cancel` |
| `account_move_id` | Many2one(account.move) | Created journal entry |
| `account_journal_id` | Many2one(account.journal) | Journal for posting -- defaults to `company.lc_journal_id`, falling back to the category's `property_stock_journal` |
| `vendor_bill_id` | Many2one(account.move) | Linked vendor bill |
| `allowed_product_ids` | Many2many(product.product) (computed) | **New in 20.** The products actually present in the targeted transfers; constrains what a cost line's "Apply On" can point at |

**States:**

| State | Meaning | Can Transition To |
|---|---|---|
| `draft` | Not yet applied | `done`, `cancel` |
| `done` | Validated, JE created, move values updated | -- (cannot cancel, must create negative LC) |
| `cancel` | Cancelled | -- |

**Creating from vendor bill:** [`button_create_landed_costs()`](../addons/stock_landed_costs/models/account_move.py#L21) on `account.move` filters invoice lines with `is_landed_costs_line=True` and creates cost lines automatically, pre-linking the PO's pickings that have at least one valued move and converting each line's subtotal into company currency at the bill date. Cost products must have `landed_cost_ok=True` (service type only); the product can also carry a default `split_method_landed_cost` and a default `landed_cost_on_product_ids` target list.

---

### `stock.landed.cost.lines` -- Cost Line Items
> [`stock_landed_cost.py:298`](../addons/stock_landed_costs/models/stock_landed_cost.py#L298)

| Field | Type | Purpose |
|---|---|---|
| `product_id` | Many2one(product.product) | The cost product (e.g., "Freight") |
| `price_unit` | Monetary | Total cost amount |
| `split_method` | Selection | How to distribute across products |
| `account_id` | Many2one(account.account) | Expense account for the cost |
| `apply_on_product_ids` | Many2many(product.product) | **New in 20.** Restrict this cost line to specific products in the transfer. Empty = every product. Seeded from the cost product's `landed_cost_on_product_ids` and intersected with `cost_id.allowed_product_ids`. |

### Split Methods

| Value | UI Label | Formula |
|---|---|---|
| `equal` | "Equal" | `cost / total_lines` |
| `by_quantity` | "By Quantity" | `cost * (line_qty / total_qty)` |
| `by_current_cost_price` | "By Current Cost" | `cost * (line_former_cost / total_cost)` |
| `by_weight` | "By Weight" | `cost * (line_weight / total_weight)` |
| `by_volume` | "By Volume" | `cost * (line_volume / total_volume)` |

Source: [`get_valuation_lines()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L166)

> **Changed in 20:** the split arithmetic moved out of `compute_landed_cost()` and into `get_valuation_lines()`, which now returns finished `stock.valuation.adjustment.lines` values in one pass instead of creating empty lines and writing amounts into them afterwards. `compute_landed_cost()` is now a three-line wrapper.

Each cost line's totals (quantity, weight, volume, current cost, line count) are computed over **only the moves it applies to** -- that is what `apply_on_product_ids` narrows.

**Rounding:** `currency.round()` per allocated amount; the leftover of `price_unit - sum(allocated)` is added to the **last line of that cost line**, so each cost line reconciles exactly to its own amount.

---

### `stock.valuation.adjustment.lines` -- Per-Move Adjustments
> [`stock_landed_cost.py:340`](../addons/stock_landed_costs/models/stock_landed_cost.py#L340)

| Field | Type | Purpose |
|---|---|---|
| `move_id` | Many2one(stock.move) | The receipt move being adjusted |
| `quantity` | Float | Move quantity |
| `weight` | Float | Product weight * quantity |
| `volume` | Float | Product volume * quantity |
| `former_cost` | Monetary | Original move value |
| `additional_landed_cost` | Monetary | Computed adjustment amount |
| `final_cost` | Monetary | `former_cost + additional_landed_cost` |

---

## Landed Costs -- Full Flow

### Restriction -- removed in 20

Odoo 19 skipped any move whose product was not FIFO or AVCO, and raised *"Landed costs can only be applied for products with FIFO or average costing method"* when that left nothing to allocate. [`get_valuation_lines()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L166) no longer filters on `cost_method` at all -- a landed cost can be raised against any product in a transfer, and the only remaining guard is [`_check_can_validate()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L273), which just requires targeted transfers.

What did **not** change is the effect: a standard-cost product's `standard_price` is a manual figure, so the allocation is recorded and posted but the product's unit cost stays put. The field help says as much. Only AVCO and FIFO products absorb the cost into their valuation.

### Validation Flow

Source: [`button_validate()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L114)

1. `_check_can_validate()` -- only draft costs, and each must have targeted transfers
2. `compute_landed_cost()` on any cost that has no adjustment lines yet -- splits costs across products using the chosen split method
3. [`_check_sum()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L281) -- validates that total adjustment equals `amount_total` **and** each cost line's adjustments sum to its `price_unit`
4. For each adjustment line whose product has `valuation == 'real_time'`:
   - [`_create_accounting_entries()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L381): Debit Stock Valuation, Credit the cost line's account (falling back to the cost product's expense account)
   - Proportional to `remaining_qty / quantity` -- only the still-in-stock portion is capitalised. A negative `remaining_qty` (oversold) reverses the entry.
5. Posts the journal entry (if any lines were produced) and sets `state = 'done'`
6. Calls `_set_value()` on all adjusted moves -- recomputes their values with the landed cost included, which in turn triggers the replay of any downstream out moves

### How Landed Costs Integrate with Move Value

When `_get_value_data()` runs on a move that has landed costs, the `_get_value_from_extra()` method (overridden in `stock_landed_costs`) adds the landed cost amount to the move's base value.

Source: [`_get_value_from_extra()`](../addons/stock_landed_costs/models/stock_move.py#L12). It only counts adjustment lines whose landed cost is in state `done`, and it appends a human-readable line (naming the landed cost and, if present, its vendor bill) to the move's value justification.

This means landed costs become part of the move's `value` field, which then feeds into FIFO stack calculations and AVCO computations.

**Example:**
```
Receipt: 100 units of Product A @ $10 = $1,000
Receipt: 50 units of Product B @ $20 = $1,000

Landed Cost: $300 freight, split "By Quantity"
  Product A: $300 * (100/150) = $200 additional
  Product B: $300 * (50/150) = $100 additional

Product A move value: $1,000 + $200 = $1,200 (effective cost: $12/unit)
Product B move value: $1,000 + $100 = $1,100 (effective cost: $22/unit)

Journal Entry:
  Debit: Stock Valuation Account  $300
  Credit: Freight Expense Account  $300
```

---

## Account Configuration

> **Changed in 20:** every field in this section now lives in `account`, not `stock_account`. The two exceptions are the `fifo` selection value and the two Production WIP accounts.

### Product Accounts

Source: [`_get_product_accounts()`](../addons/account/models/product.py#L125), public wrapper [`get_product_accounts(fiscal_pos=None)`](../addons/account/models/product.py#L166)

Returns `{'income', 'expense', 'stock_valuation', 'stock_variation'}`; the public wrapper maps each through the fiscal position and adds `'stock_journal'`.

**Fallback order for Stock Valuation Account** -- [`_get_category_account()`](../addons/account/models/product.py#L150):
1. Walk **up the product category hierarchy** (`categ_id`, then `parent_id`, ...) looking for `property_stock_valuation_account_id`
2. `res.company.account_stock_valuation_id`

The hierarchy walk is new in 20 -- a child category no longer needs to repeat its parent's accounts.

**Stock Variation Account:** `stock_valuation_account.account_stock_variation_id` (related field on the account itself).

**Caching:** the result is memoised per `(product_tmpl, company)` in the cursor cache for the duration of the transaction, because the closing and the report call it once per product. Overrides that mutate the dict (`mrp_account`, `l10n_de`) get a copy.

### Account-Level Fields

Source: [`account/models/account_account.py:156`](../addons/account/models/account_account.py#L156)

| Field | Type | Purpose |
|---|---|---|
| `account_stock_variation_id` | Many2one(account.account) | "Variation Account" -- inventory variation at closing |
| `account_stock_expense_id` | Many2one(account.account) | "Expense Account" -- counterpart for closing adjustments |

These are set by the localisation chart templates (`l10n_de`, `l10n_fr`, `l10n_be`, ...), which is why Continental closings work out of the box in those countries.

### Product Category Fields

Source: [`account/models/product.py:30-70`](../addons/account/models/product.py#L30), plus the `fifo` extension at [`stock_account/models/product.py:749`](../addons/stock_account/models/product.py#L749)

| Field | Technical Name | UI Label | Type | Purpose |
|---|---|---|---|---|
| Valuation | `property_valuation` | "Inventory Valuation" | Selection (company_dependent) | `periodic` or `real_time` |
| Cost Method | `property_cost_method` | "Costing Method" | Selection (company_dependent) | `standard`, `average`; `fifo` added by `stock_account` |
| Stock Journal | `property_stock_journal` | "Stock Journal" | Many2one (company_dependent) | Journal for automated JEs |
| Stock Valuation Account | `property_stock_valuation_account_id` | "Stock Valuation Account" | Many2one (company_dependent) | Balance sheet inventory account |
| Price Difference Account | `property_price_difference_account_id` | "Price Difference Account" | Many2one (company_dependent) | Holds standard vs bill price difference. Only visible when cost method is Standard and valuation is Perpetual. |
| Stock Variation Account | `account_stock_variation_id` | "Stock Variation Account" | Many2one (related) | From `property_stock_valuation_account_id.account_stock_variation_id` |
| Anglo-Saxon Accounting | `anglo_saxon_accounting` | -- | Boolean (computed) | From `company.anglo_saxon_accounting`; defined in [`stock_account`](../addons/stock_account/models/product.py#L753) |

Changing `property_cost_method` on a category replays the valuation of every product in it since the last closing -- [`ProductCategory.write()`](../addons/stock_account/models/product.py#L761).

### Company-Level Fields

Source: [`account/models/company.py:331-376`](../addons/account/models/company.py#L331), plus [`stock_account/models/res_company.py:11-16`](../addons/stock_account/models/res_company.py#L11)

| Field | Technical Name | Defined in | Default |
|---|---|---|---|
| Stock Journal | `account_stock_journal_id` | `account` | -- |
| Stock Valuation Account | `account_stock_valuation_id` | `account` | -- |
| Price Difference Account | `price_difference_account_id` | `account` | -- |
| Inventory Period | `inventory_period` | `account` | `manual` |
| Valuation | `inventory_valuation` | `account` | `periodic` |
| Cost Method | `cost_method` | `account` (+ `fifo` from `stock_account`) | `standard` |
| Anglo-Saxon | `anglo_saxon_accounting` | `account` ([`:147`](../addons/account/models/company.py#L147)) | `False` |
| Production WIP Account | `account_production_wip_account_id` | `stock_account` | -- |
| Production WIP Overhead | `account_production_wip_overhead_account_id` | `stock_account` | -- |

The four `company_default_for(...)` fields (`account_stock_valuation_id`, `inventory_valuation`, `account_stock_journal_id`, `cost_method`) are declared as the company-level fallback of the matching `product.category` property, which is what makes "unset on the category" fall through to the company automatically.

### Location-Level Fields

Source: [`stock_location.py:11`](../addons/stock_account/models/stock_location.py#L11)

| Field | Technical Name | Purpose |
|---|---|---|
| Stock Valuation Account | `valuation_account_id` | Location-specific expense account for reclassification |
| Is Valued | `is_valued` | Computed + searchable flag mirroring `_should_be_valued()`; used to scope `qty_available` to valued locations |

When a location has `valuation_account_id`, moves into/out of that location create separate reclassification journal entries (debiting the location's account and crediting the product's stock valuation account, or vice versa).

---

## Configuration (Settings)

Source: [`res_config_settings.py`](../addons/stock_account/models/res_config_settings.py) -- unchanged in 20.

| Setting | Technical Name | Type | Effect |
|---|---|---|---|
| Landed Costs | `module_stock_landed_costs` | Boolean | Installs the `stock_landed_costs` module |
| Display Lots on Invoices | `group_lot_on_invoice` | Boolean | `implied_group='stock_account.group_lot_on_invoice'` -- shows lot/serial numbers on invoice lines |

Note what is **not** here: valuation method, costing method, the stock journal and the valuation account are not `stock_account` settings. They are `account` settings (Accounting > Configuration > Settings) plus per-category overrides, because `account` owns them in 20.

### Landed Costs Settings

Source: [`addons/stock_landed_costs/models/res_config_settings.py`](../addons/stock_landed_costs/models/res_config_settings.py)

| Setting | Technical Name | Type | Effect |
|---|---|---|---|
| LC Journal | `lc_journal_id` | Many2one(account.journal) | Default journal for landed cost entries (related to `company.lc_journal_id`) |

---

## Key Methods

| Method | File:Line | Purpose |
|---|---|---|
| `_action_done()` | [`stock_move.py:248`](../addons/stock_account/models/stock_move.py#L248) | Orchestrates valuation on move completion |
| `_set_value()` | [`stock_move.py:345`](../addons/stock_account/models/stock_move.py#L345) | Assigns the signed value to moves; detects and drives the replay |
| `_get_value_data()` | [`stock_move.py:442`](../addons/stock_account/models/stock_move.py#L442) | Priority-based value resolution for incoming moves |
| `_get_valued_qty()` | [`stock_move.py:535`](../addons/stock_account/models/stock_move.py#L535) | Quantity in product UoM for the valued move lines; `signed=True` mirrors `value` |
| `_create_account_move()` | [`stock_move.py:260`](../addons/stock_account/models/stock_move.py#L260) | Creates and posts one stock journal entry per batch |
| `_should_create_account_move()` | [`stock_move.py:756`](../addons/stock_account/models/stock_move.py#L756) | Eligibility check for JE creation |
| `_get_account_move_line_vals()` | [`stock_move.py:296`](../addons/stock_account/models/stock_move.py#L296) | Determines debit/credit accounts and amounts |
| `_get_price_unit()` | [`stock_move.py:321`](../addons/stock_account/models/stock_move.py#L321) | Unit price of a set of moves; the COGS price source (replaces `_get_cogs_price_unit()`) |
| `_get_in_move_lines()` / `_get_out_move_lines()` | [`stock_move.py:623`](../addons/stock_account/models/stock_move.py#L623) / [`:653`](../addons/stock_account/models/stock_move.py#L653) | Classify move lines as in/out based on location valuation |
| `_clear_journal_entries()` / `_reset_valuation()` | [`stock_move.py:782`](../addons/stock_account/models/stock_move.py#L782) / [`:787`](../addons/stock_account/models/stock_move.py#L787) | Undo valuation when a move is reset to draft/progress |
| `_run_standard()` | [`product.py:337`](../addons/stock_account/models/product.py#L337) | Standard-cost value (and replay) for a set of products |
| `_run_fifo()` | [`product.py:507`](../addons/stock_account/models/product.py#L507) | FIFO value (and replay) for a set of products |
| `_get_fifo_value()` | [`product.py:616`](../addons/stock_account/models/product.py#L616) | FIFO cost of one outgoing quantity |
| `_get_fifo_stack()` | [`product.py:655`](../addons/stock_account/models/product.py#L655) | Builds the ordered FIFO stack (was `_run_fifo_get_stack()`) |
| `_run_avco()` | [`product.py:370`](../addons/stock_account/models/product.py#L370) | Weighted average value (and replay) for a set of products |
| `_correct_inventory_valuation()` | [`product.py:247`](../addons/stock_account/models/product.py#L247) | Replays valuation from a date and rewrites affected out-move values |
| `_update_standard_price()` | [`product.py:716`](../addons/stock_account/models/product.py#L716) | Updates standard_price from FIFO/AVCO computation |
| `_compute_value()` | [`product.py:99`](../addons/stock_account/models/product.py#L99) | Computes `total_value` and `avg_cost` on product |
| `_get_product_accounts()` | [`account/models/product.py:125`](../addons/account/models/product.py#L125) | Returns income/expense/stock valuation/variation accounts |
| `_change_standard_price()` | [`product.py:213`](../addons/stock_account/models/product.py#L213) | Creates product.value records on manual price change |
| `_with_valuation_context()` | [`product.py:311`](../addons/stock_account/models/product.py#L311) | Adds valued locations and owner filters to context |
| `_get_remaining_moves()` | [`product.py:315`](../addons/stock_account/models/product.py#L315) | Returns remaining inventory by move (FIFO stack) |
| `action_close_stock_valuation()` | [`account/models/company.py:1278`](../addons/account/models/company.py#L1278) | Manual/auto closing entry creation |
| `_get_location_valuation_vals()` | [`res_company.py:82`](../addons/stock_account/models/res_company.py#L82) | Location reclassification lines for the closing entry |
| `_create_cogs_lines()` | [`account/models/account_move.py:5966`](../addons/account/models/account_move.py#L5966) | COGS + price difference line generation on posting |
| `_get_price_difference_lines_vals()` | [`account/models/account_move.py:6064`](../addons/account/models/account_move.py#L6064) | Purchase price difference lines (Anglo-Saxon + Standard) |
| `_get_cogs_value()` | [`account_move_line.py:80`](../addons/stock_account/models/account_move_line.py#L80) | COGS value per invoice line |
| `_set_cogs()` | [`account_move_line.py:50`](../addons/stock_account/models/account_move_line.py#L50) | Re-prices already-posted COGS lines when a move's value changes |
| `_use_inventory_valuation()` | [`account/models/account_move_line.py:3818`](../addons/account/models/account_move_line.py#L3818) | Checks if a line qualifies for COGS / valuation account (was `_eligible_for_stock_account()`); dropship exclusion in `stock_dropshipping` |
| `_compute_account_id()` | [`account/models/account_move_line.py:725`](../addons/account/models/account_move_line.py#L725) | Overrides purchase bill account to stock valuation |
| `button_validate()` | [`stock_landed_cost.py:114`](../addons/stock_landed_costs/models/stock_landed_cost.py#L114) | Validates landed cost, creates JE, updates move values |
| `get_valuation_lines()` | [`stock_landed_cost.py:166`](../addons/stock_landed_costs/models/stock_landed_cost.py#L166) | Splits costs across products (the split arithmetic lives here in 20) |

---

## Technical Scenarios (Code-Level Trace)

> For business-level walkthroughs, see "Complete Business Flow Walkthroughs" at the top of this document.
> These scenarios show what methods are called under the hood.

### Scenario 1: Purchase Receipt -- Code Trace (Perpetual FIFO)

```
1. Receipt validated -> stock.picking.button_validate()
   -> stock.move._action_done()  (sudo)
   -> super()._action_done() first: move lines finalised, is_in computed -> True
   -> _set_value(): move.value = _get_value()   (positive)
      Priority chain: _get_value_from_quotation() returns PO line price * qty
   -> _update_standard_price(): standard_price = total_value / qty_available
   -> _create_account_move(): no entry -- neither Vendors nor WH/Stock has a
      valuation_account_id

2. Vendor bill posted -> account.move._post()
   -> super()._post() -> _create_cogs_lines() (price difference lines, if standard cost)
   -> line_ids.cogs_move_ids.filtered(is_in or is_dropship)._set_value()
   -> _get_value_from_account_move() now returns the actual bill amount
   -> if part of the receipt is already sold, _set_value() escalates to
      _correct_inventory_valuation(recompute_date) and re-costs the out moves
   -> move.value updated, standard_price updated
   -> stock.move.write() sees `value` change -> cogs_aml_ids._set_cogs()
      re-prices any COGS lines already posted against those moves
```

### Scenario 2: Customer Delivery + Invoice -- Code Trace (AVCO)

```
1. Delivery validated -> stock.move._action_done()
   -> super()._action_done() runs first
   -> is_out = True (WH/Stock is valued, Customers is unvalued)
   -> _set_value(): move.value = - standard_price * valued_qty   (negative)
   -> _create_account_move(): only if a location has valuation_account_id

2. Invoice posted -> account.move._post()
   -> account.move._create_cogs_lines() -> _get_cogs_lines_vals()
   -> For each line passing _use_inventory_valuation():
      -> line._get_cogs_value()
      -> cogs_move_ids._get_price_unit(include_consigned=True, product=...)
         = sum(signed value) / sum(signed qty)  -> the AVCO cost actually moved
   -> Creates display_type='cogs' lines (cogs_origin_id -> the invoice line):
      Debit COGS/Expense, Credit Stock Valuation
```

### Scenario 3: Purchase Receipt + Bill -- Code Trace (Anglo-Saxon Standard Cost)

```
1. Receipt validated -> stock.move._action_done()
   -> _set_value(): move.value = _get_value()
      No bill yet -> _get_value_from_quotation() returns PO price * qty
   -> _create_account_move(): no entry (no location with valuation_account_id)

2. Bill line account: account.move.line._compute_account_id() (in `account`)
   -> _use_inventory_valuation() True -> account overridden from expense
      to accounts['stock_valuation']

3. Vendor bill posted -> account.move._post()
   -> _create_cogs_lines() -> _get_price_difference_lines_vals()
      (purchase document + company.anglo_saxon_accounting)
   -> product._get_price_diff_account(): non-empty only when cost_method == 'standard'
   -> balance = price_subtotal / invoice_currency_rate - standard_price * qty
   -> If non-zero, creates two display_type='cogs' lines:
        Debit:  property_price_difference_account_id
        Credit: line.account_id (the stock valuation account)
   -> stock_account._post() then re-values the incoming moves
```

### Scenario 4: Inventory Adjustment -- Code Trace

```
1. User updates quant quantity -> stock.quant._apply_inventory()
   -> quants grouped by accounting_date; a set date is passed down as
      context['force_period_date'], which dates both the move name and the JE
   -> Creates stock.move: WH/Stock -> Inventory Loss location
   -> is_out = True (valued -> unvalued)
   -> move.value = - standard_price * adjustment_qty
   -> JE only if the Inventory adjustment location has a valuation_account_id
      (Loss Account): Debit that account, Credit Stock Valuation. A fresh chart
      sets none, so by default no entry is created
```

### Scenario 5: Landed Cost Validation -- Code Trace

```
1. button_validate() called
   -> _check_can_validate(): draft only, transfers required
   -> compute_landed_cost() -> get_valuation_lines(): computes each cost line's
      totals over the moves it applies to (apply_on_product_ids), allocates,
      rounds, dumps the remainder on that cost line's last row, and creates
      the stock.valuation.adjustment.lines in one create()
   -> _check_sum(): total == amount_total AND per-cost-line sums match
   -> For each adjustment line whose product is real_time:
      _create_accounting_entries():
        diff = additional_landed_cost * (remaining_qty / quantity)
        Debit Stock Valuation, Credit the cost line's account
        (negative diff reverses debit/credit)
   -> Creates account.move with all lines, posts it, state = 'done'
   -> _set_value() re-called on all adjusted moves
      -> _get_value_from_extra() now includes landed cost amounts
      -> partially-sold receipts escalate to _correct_inventory_valuation()
   -> _update_standard_price() on affected products
```

### Scenario 6: Customer Return -- Code Trace

```
1. Return picking validated -> stock.move._action_done()
   -> is_in = True (Customer is unvalued, WH/Stock is valued)
   -> _set_value(): move.value = _get_value()
      -> _get_value_from_returns(): abs(origin_move.value) * qty / origin_valued_qty
         (abs() because the origin out move's value is negative)
   -> _create_account_move(): no entry (Customers has no valuation_account_id)
   -> _update_standard_price(): AVCO/FIFO recalculated

2. Credit note posted -> account.move._post() -> _create_cogs_lines()
   -> sign = -1 (out_refund), and _get_cogs_qty() flips too
   -> COGS lines reversed:
      Credit COGS/Expense, Debit Stock Valuation
```

### Scenario 7: Dropship -- Code Trace

```
1. Dropship move done -> stock.move._action_done()
   -> _is_dropshipped() = True (supplier -> customer)
   -> is_in = False, is_out = False, is_dropship = True
   -> is_valued = True  (changed in 20: dropship now counts as valued)
   -> moves_in (= is_in or is_dropship)._set_value()
      -> move.value = _get_value() (treated like incoming for value, positive)
   -> _create_account_move(): NOT created -- _should_create_account_move() also
      requires a location with valuation_account_id, and supplier/customer
      locations have none
   -> _update_standard_price() called

2. Customer invoice posted
   -> _use_inventory_valuation() returns False for the line (all its moves are
      dropshipped), so NO COGS lines are generated.

Note: Dropship moves update standard_price and feed the AVCO replay
(_run_avco processes is_dropship as both an in and an out), but they
never create a stock journal entry since goods never enter company stock.
```

---

## Historical Valuation (Reporting at Past Dates)

Odoo supports computing inventory value at any past date using context keys.

**Context key:** `to_date` -- when set, all valuation computations filter moves up to this date.

**How it works:**
- `_compute_value()` reads `to_date` and passes it as `at_date` to `_run_standard()`, `_run_avco()` and `_run_fifo()`. A plain date is widened to end-of-day, so "as of the 31st" includes the whole day.
- `_get_fifo_stack()` filters moves with `date <= at_date`, and the stack size comes from `qty_available` in the same `to_date` context
- `_run_avco()` filters moves with `date <= at_date` and seeds from the last manual `product.value` before it
- `_run_standard()` resolves the price of the day through `_get_last_product_value(at_date)`

**Changed in 20:** `_get_standard_price_at_date()` is gone, and so is the `at_date` argument that used to thread through the whole `_get_value_data()` priority chain. Historical valuation is now a full replay of the product's timeline rather than a per-move re-derivation -- more work per call, but it is the only way the FIFO stack and the AVCO running average can be reconstructed consistently.

**Where used:** the Inventory Valuation report (`at_date` picker), the periodic closing (which values inventory at the closing date), and accounting reports needing point-in-time inventory values.

Source: [`_compute_value()`](../addons/stock_account/models/product.py#L99) -- checks `self.env.context.get('to_date')`

---

## Security & Access

> **Changed in 20.** `ir.model.access` and `ir.rule` no longer exist. Both modules dropped `security/ir.model.access.csv` (and `stock_landed_costs` dropped its `*_security.xml` rule file entirely) in favour of a single `security/ir.access.csv` with the columns `id,name,model_id,group_id/id,operation,domain`. It is loaded **last** in the manifest; only the groups file still loads first. A row with an empty `group_id` is a *restriction* (the old global `ir.rule`); a row with a group is a *permission*.

### stock_account

> [`security/ir.access.csv`](../addons/stock_account/security/ir.access.csv)

| Model | Group | Operation | Domain |
|---|---|---|---|
| `product.value` | `stock.group_stock_manager` | `crud` | -- |
| `product.value` | `account.group_account_manager` | `crud` | -- |
| `product.value` | *(restriction)* | `crud` | `[('company_id','in', company_ids)]` |
| `stock.avco.report` | `stock.group_stock_manager`, `account.group_account_readonly` | `r` | -- |
| `stock.avco.report` | *(restriction)* | `crud` | `[('company_id','in', company_ids)]` |
| `account.account`, `account.journal` | `stock.group_stock_manager` | `r` | -- |
| `stock.picking`, `stock.move` | `account.group_account_readonly` / `account.group_account_invoice` | `r` / `cru` | -- |

The accounting-side grants are what let an accountant open the Inventory Valuation report and drill into the moves behind a figure without holding an Inventory role.

The only group this module defines is `stock_account.group_lot_on_invoice` ("Display Serial & Lot Number on Invoices") -- [stock_account_security.xml](../addons/stock_account/security/stock_account_security.xml).

### stock_landed_costs

> [`security/ir.access.csv`](../addons/stock_landed_costs/security/ir.access.csv)

| Model | Group | Operation | Domain |
|---|---|---|---|
| `stock.landed.cost` | `stock.group_stock_manager` | `crud` | -- |
| `stock.landed.cost` | *(restriction)* | `crud` | `[('company_id', 'in', company_ids)]` |
| `stock.landed.cost.lines` | `stock.group_stock_manager` | `crud` | -- |
| `stock.valuation.adjustment.lines` | `stock.group_stock_manager` | `crud` | -- |

**Row-level security:** only `stock.landed.cost` carries the multi-company restriction; its lines inherit isolation through the parent's `ondelete='cascade'` relation rather than a rule of their own.

---

## Edge Cases & Gotchas

- **`move.value` is signed.** Out moves store a negative value. Any custom code summing `move.value`, comparing it to a quantity, or feeding it into a report must account for that, and should use `_get_valued_qty(signed=True)` on the quantity side. This is the single most common source of breakage when porting v19 valuation code.

- **Negative stock with FIFO:** When outgoing quantity exceeds available stock, `_get_fifo_value()` extrapolates using the last popped move's unit price; if the stack was empty, it falls back to `standard_price`. **New in 20:** the oversold out moves are remembered as a *negative* FIFO stack (`_get_fifo_stack(allow_negative=True)`), so the next incoming move re-costs them retroactively through the replay. COGS is estimated at first and corrected later, rather than staying wrong.

- **Multiple outgoing moves validated simultaneously:** `_set_value()` keeps a local `fifo_qty_already_processed` tally and passes the negated figure as `stack_size_extra_qty`, so each move consumes from where the previous one stopped. **The `fifo_qty_already_processed` *context key* no longer exists** -- passing it does nothing in 20.

- **Landed costs are no longer restricted to FIFO/AVCO.** The `cost_method not in ('fifo', 'average')` filter was removed from `get_valuation_lines()` in 20. Standard-cost products get allocation lines and journal entries, but their `standard_price` still does not move.

- **Cannot cancel validated landed costs:** You must create a negative landed cost to reverse. Source: [`button_cancel()`](../addons/stock_landed_costs/models/stock_landed_cost.py#L108)

- **COGS lines have `display_type='cogs'`:** These are auto-managed. `account.move._create_cogs_lines()` creates them on `_post()`, `button_draft()` / `button_cancel()` delete them, and `_set_cogs()` re-prices them in place. Never manually edit them. The `cogs_origin_id` field links them back to the originating invoice line -- and `copy_data()` only strips the ones that *have* a `cogs_origin_id`, so a synthetic COGS line (the accrual wizard's, for instance) survives duplication. Source: [`copy_data()`](../addons/stock_account/models/account_move.py#L23)

- **Vendor bill revalues receipt:** When a vendor bill is posted, `_post()` calls `_set_value()` on the backing incoming moves. This updates the move value from PO price to actual bill price -- critical for FIFO accuracy. Un-posting the bill runs the same call and reverts it.

- **`disable_auto_revaluation` context:** Used internally to prevent infinite recursion when `_update_standard_price()` writes to `standard_price`, which would normally trigger `_change_standard_price()` again.

- **Consignment goods excluded:** Quants and moves whose owner is not the company partner are excluded from valuation. This is the `_should_exclude_for_valuation()` check on [`stock.move`](../addons/stock_account/models/stock_move.py#L766), [`stock.move.line`](../addons/stock_account/models/stock_move_line.py#L40) and [`stock.quant`](../addons/stock_account/models/stock_quant.py#L39).

- **Closing date tracking -- changed in 20:** no longer an `ir.config_parameter`. It is the `closing_datetime` of the most recent posted `account.move` with `inventory_closing = True`. Only moves after that instant are included in the next closing. Source: [`_get_last_closing_date()`](../addons/stock_account/models/res_company.py#L76).

- **Category change triggers recomputation:** Changing a product's category (which may change cost method or valuation type) triggers `_update_standard_price()` on all variants. Source: [`ProductTemplate.write()`](../addons/stock_account/models/product.py#L36). Changing the *category's* cost method, or the *company's*, goes further and replays the valuation from the last closing -- [`ProductCategory.write()`](../addons/stock_account/models/product.py#L761), [`ResCompany.write()`](../addons/stock_account/models/res_company.py#L18).

- **Editing a done move's date replays the valuation.** `stock.move.write()` detects a date change on a valued move and calls `_set_value(recompute_date=min(old, new))`, which re-costs everything from that instant forward. Source: [`write()`](../addons/stock_account/models/stock_move.py#L181). Backdating is additionally blocked inside a locked fiscal period by a constraint on `stock.picking.date_done` -- [`_check_backdate_allowed()`](../addons/stock_account/models/stock_picking.py#L13), bypassable with the `stock_account.skip_lock_date_check` system parameter.

- **Resetting a move to draft clears its journal entry.** `_action_reset_to_draft()` / `_action_reset_to_progress()` draft and unlink the stock `account.move`, zero the move value, and replay the product's valuation. Source: [`_clear_journal_entries()`](../addons/stock_account/models/stock_move.py#L781). Only manufacturing orders call them ([`mrp_production.py:2039`](../addons/mrp/models/mrp_production.py#L2039)); a transfer cannot be reset.

- **Purchase price difference only for Standard + Anglo-Saxon:** [`_get_price_difference_lines_vals()`](../addons/account/models/account_move.py#L6064) runs only on purchase documents of an Anglo-Saxon company, and only produces lines when `_get_price_diff_account()` resolves -- which it does only for `cost_method == 'standard'`. FIFO and AVCO products don't get price difference entries because their cost is dynamic. **Changed in 20:** there is no expense-account fallback; an unset category account means no lines at all.

- **COGS not created for dropship:** `_use_inventory_valuation()` returns `False` if any linked stock move is a dropship. Dropship COGS is handled through the stock move's direct valuation.

- **Currency conversion on price difference -- changed in 20:** the bill's subtotal is converted with the move's own `invoice_currency_rate` (the rate locked in on the invoice), not at today's rate. Source: [`account_move.py:6078`](../addons/account/models/account_move.py#L6078).

- **The `stock.move` list renders signed totals in JS.** `quantity` is stored positive while `value` is signed, so the footer would otherwise mix conventions. [stock_account_move_list_view.js](../addons/stock_account/static/src/views/stock_account_move_list_view.js) recomputes the quantity aggregate with the out-move sign on flat lists; grouped lists rely on the server-side `_read_group_postprocess_aggregate` overrides instead.

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`inventory.md`](inventory.md) -- Core inventory (warehouses, routes, quants, reservations)
- [`accounting_coa.md`](accounting_coa.md) -- Chart of Accounts setup (stock accounts configuration)
- [`accounting_fixed_costs_guide.md`](accounting_fixed_costs_guide.md) -- Account types and reconciliation
- [`mrp.md`](mrp.md) -- Manufacturing: MO Overview valuation, production costing, work center costs
