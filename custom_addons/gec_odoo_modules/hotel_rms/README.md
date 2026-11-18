# Hotel Revenue Management — user guide

This app helps you decide **what to charge for each room type on each night**. It reads bookings,
estimates how full the hotel will be, and suggests prices with explanations. You review and publish them.

**Bookings → Forecast → Suggested prices → Your decision → Export or apply**

The calculations use rules and booking history; they do not call an AI service.

## Find what you need

- [Start here: setup and daily routine](#start-here)
- [Calendar: colors, symbols, New, and No change](#read-the-calendar)
- [Calendar buttons and view controls](#calendar-controls)
- [Price details and decision buttons](#review-and-decide)
- [Run now and Learn booking curve](#run-now-and-learn-booking-curve)
- [Hotel setup: rooms, seasons, events, and rules](#hotel-settings)
- [How forecasts and prices are calculated](#how-calculations-work)
- [Import bookings and current prices](#import-data)
- [Export or apply approved prices](#publish-prices)
- [Insights and reports](#insights-and-reports)
- [Permissions, demo data, and troubleshooting](#help-and-access)

<a id="start-here"></a>
## Start here

### First setup

1. As an Administrator, open **Revenue → Configuration → Hotels → New**.
2. Add room types and room counts. Choose one **Reference room**.
3. Add seasons covering the dates you want to price. Enter base/minimum/maximum prices and expected occupancy.
4. Bring in historical and upcoming bookings. Import current prices too, if using files.
5. Press **Run now**, then **Open calendar**.

With the optional Sales connection, link room types to Odoo rental products and select a pricelist
instead of importing that data. See [publishing and the Odoo connection](#publish-prices).

The setup checklist marks rooms, season coverage, booking data, and a completed run. The default
planning period is **90 nights starting today**. Currency comes from the hotel's company.

### Daily routine

1. Refresh your booking data. For linked Odoo bookings, **Run now** reads them for you.
2. Open **Revenue → Pricing Calendar** and check the **Updated…** indicator.
3. Choose **Review N prices**. Read the explanation and accept, change, reject, or skip each price.
4. Press **Export approved** or **Apply to pricelist** to send your decisions out.
5. Check **Insights** periodically to see booking trends and forecast quality.

<a id="read-the-calendar"></a>
## Read the calendar

Each **column is one night**, each **row is a room type**, and each cell shows a nightly price.
Normally the number is the recommendation. After **Use my price** or a percentage adjustment,
it shows your own approved price instead.

### Colors and symbols in Changes view

The cell background answers **“What decision did I make?”** The text below its price answers
**“How does this price compare with the recorded current price?”** These are different things.

| Appearance | Meaning |
|---|---|
| **Green cell + check mark** | **Accepted**: you approved the recommendation. Green alone does not prove it was published. |
| **Blue cell + pencil** | **Own price**: you entered a price or used a percentage adjustment. |
| **Neutral/gray cell + purple dot** | **Needs decision**: an unlocked suggestion is waiting for you. |
| **Neutral cell without a dot** | May be **No change suggested**, rejected, or locked. Hover or open it to read the status. |
| **Muted price text** | **Rejected**: you chose to keep the last exported/applied price. The cell may still display the recommendation you rejected. |
| **Lock icon** | The engine leaves this price alone until you unlock it. |
| **Purple outline around one cell** | The selected cell. Its details are open or it is selected for keyboard actions. |
| **Tint across a row and column** | Mouse hover helps you follow the room and night. It does not change data. |
| **Tint on several selected cells** | Bulk selection; the bottom action bar applies to those cells. |
| **Hatched cell / Not for sale** | The linked pricelist gives price 0. This night has no price recommendation. |

Colors follow the Odoo theme, so shades differ in light and dark mode. Use icons and status labels
as well as color. **Price level** and **Occupancy** views use a different color scale, explained below.

### New, No change, and arrows

In the calendar and its side panel, the comparison price is the **last recorded imported, exported,
or pricelist price**. An export records that a file was generated; it cannot verify an external website.

| Text below the price | Meaning | Example |
|---|---|---|
| **New** | No nonzero comparison price is recorded yet. It does not mean a new booking or room. | Suggested 105, no current price imported → **105 / New**. |
| **No change** | The displayed amount equals the comparison price, at currency precision. | Displayed 110, comparison 110 → **110 / No change**. |
| **↑ 15** | The displayed amount is 15 currency units higher. This is an amount, not a percentage. | Current 100, suggestion 115. |
| **↓ 10** | The displayed amount is 10 currency units lower. | Current 100, suggestion 90. |
| **—** | No nonzero price is available to display. | No usable recommendation yet. |
| **No season** | This night has no season configured, so it has no normal price calculation. | Add a season covering the date, then Run now. |

**Why can both green and gray cells say “No change”?**

- **Green + No change:** the recommendation was accepted, and now matches the comparison price.
- **Blue/pencil + No change:** your own price matches the comparison price. The blue-gray cell in the screenshot is this case.
- **Neutral gray + No change:** the amounts match, without the accepted/own-price color. Open it to see its exact status.

For example: current price **100**, recommendation **110** → accept it → green **110 / ↑ 10**.
After exporting/applying **110**, it becomes green **110 / No change**. The decision remains accepted;
the comparison changed. Accepting a price equal to the current one also produces green **No change**.

### Date backgrounds and occupancy bars

| What you see | Meaning |
|---|---|
| **Shaded Saturday and Sunday columns** | Weekends. The shading itself does not increase the price. Weekday pricing rules control that. |
| **Purple line under a date header** | Today, using the hotel's time zone. |
| **Month heading / vertical separators** | Month and week boundaries to help you read the grid. |
| **Highlighted date column after clicking Insights** | The night you opened from a chart. |
| **75% beneath a date** | Forecast occupancy for the whole hotel that night. With 20 rooms, 75% means about 15 expected bookings. |
| **Solid colored part of the bar** | Rooms already booked. |
| **Lighter extension of the bar** | Additional rooms expected by the stay date. |
| **Hatched forecast section** | Low confidence: little supporting history. |
| **Event name below the date** | An event affects that night. Hover for all names; `+1` means one additional event. |

**In the October 2026 screenshot:** October **25** is Sunday, **31** is Saturday, and November **1**
is Sunday, so all three are shaded. October **25** also has the today marker.

### The four summary cards

These summarize the **next 30 nights from today**, even when you navigate to another calendar period.

| Card | Plain meaning |
|---|---|
| **Booked occupancy** | Share of available room nights already booked. |
| **Forecast occupancy** | Share expected to be booked by the stay dates. |
| **ADR on the books** | Average room revenue per booked room night. Example: 1,000 GEL / 10 room nights = 100 GEL. |
| **Estimated RevPAR** | ADR × forecast occupancy. At ADR 100 and occupancy 80%, this is 80 GEL per available room night. It is an estimate, not profit. |

Comparisons use an available successful run from at least 7 days ago. **+5 pts** means occupancy
rose, for example, from 70% to 75%. Money cards show percentage changes. No comparison appears
when the required earlier data is unavailable.

<a id="calendar-controls"></a>
## Calendar buttons and view controls

| Control | What it does |
|---|---|
| **Hotel selector** | Switches between hotels you can access. |
| **Updated… / Data … days old · prices frozen** | Shows when booking data was refreshed. “Frozen” stops new recommendations, not all manual actions. |
| **Run now** | Reads connected sources and recalculates forecasts and suggestions. It does not approve or publish. [Details below](#run-now-and-learn-booking-curve). |
| **Review N prices** | Opens a guided review of pending, unlocked suggestions in the loaded calendar period. |
| **Accept all** | After confirmation, accepts all eligible pending suggestions in that calendar period. It does not publish them. |
| **Export approved / Apply to pricelist + count** | Publishes prices waiting to be sent. The count covers the hotel, not just visible cells. |
| **Previous / Next arrows** | Moves backward/forward by the displayed number of nights. |
| **Today** | Returns the starting date to today. |
| **Date picker** | Starts the calendar at your chosen date. It does not run the engine. |
| **Fit / 14 nights / 30 nights** | Changes how many dates are displayed. Fit adapts to screen width; small screens also offer 7 nights. |
| **All nights / Needs decision** | Shows all cells or only eligible pending suggestions. On phones, the pending filter is called **To decide**. Hidden cells are not deleted. |
| **Calendar / Insights** | Switches between daily pricing and trend reports. |
| **Side-panel toggle** | Shows or hides the details panel on wide screens. |
| **More (three dots)** | Holds actions such as Run now on compact screens. |

### Three display modes

| Mode | What the cell colors and extra numbers mean |
|---|---|
| **Changes** | Decision colors, with New / No change / increase / decrease below the price. |
| **Price level** | Position within the season's reference-room range: 0% = minimum, 100% = maximum. Example: price 120 in a range 80–160 is 50%. |
| **Occupancy** | Forecast occupancy. The same night's percentage repeats across room types because the forecast is for the whole hotel. |

In Price level and Occupancy modes, colors follow the **0 / 25 / 50 / 75 / 100% legend** instead of
accepted/own-price backgrounds. Icons still identify decisions. Price level uses the reference season
range even for derived rooms; 100% can therefore mean at or above that range's maximum.

### Faster actions

- Click a cell, then **Shift+click** another to select a rectangle of rooms and nights.
- Use **Ctrl/Cmd+click** to add/remove individual cells. On touch screens, long-press to start selection.
- The bulk bar offers **Accept**, **−5%**, **+5%**, **Lock**, and **Clear**. Clear removes the selection only.
- Keyboard: **arrows** move; **Enter** opens details; **A** accepts; **R** rejects; **L** locks/unlocks;
  **J/K** move next/previous during review; **Esc** clears selection or closes the panel.
- On a phone's pending-price feed, **swipe right** to accept and **left** to reject. Tap to read details.

<a id="review-and-decide"></a>
## Review and decide

### What the price panel shows

Click a calendar cell to open its details.

| Part | What to read |
|---|---|
| **Price and status** | Suggested or own price, comparison with current, and Needs decision / Accepted / Own price / Rejected. |
| **Price-position bar** | Season minimum/maximum, current price, model target, and recommendation. The model target is before safety rules and rounding. |
| **Why this price** | Reasons in words and a step-by-step chart from the base price to the recommendation. |
| **Already booked** | Booked rooms out of hotel capacity. |
| **Forecast occupancy** | How full the hotel is expected to be. |
| **Bookings vs usual** | How far bookings are ahead of or behind the normal level at this point before arrival. |
| **Days left** | Time until the night being priced. |
| **Confidence** | Low, medium, or high support from history and data freshness. |
| **Booking chart** | Already-booked versus usual bookings across saved forecast dates. It needs previous runs to build a history. |
| **History** | Who acted, when, and the old/new prices. |
| **Show details** | Expands the full explanation on compact screens. |
| **Open full record** | Opens the price form, including Technical details such as the run, decision date, and To Publish flag. |

The explanation chart describes the **engine recommendation**. After choosing your own price,
the headline can differ from the recommendation explained in that chart.

### Decision buttons

| Button | Action and consequence |
|---|---|
| **Accept** | Saves the recommendation as your approved price, records who accepted it, and turns the cell green. Publishing is a separate step. |
| **Accept & next** | Accepts and moves to the next suggestion in guided review. |
| **−10%, −5%, +5%, +10%** | Adjusts the recommendation, not the previous selling price. Example: recommendation 120, +5% → 126 before rounding. Records this as Own price. |
| **My price → Use my price** | Saves your entered amount as Own price. Add an optional note to explain your decision. It does not enforce season bounds. |
| **Reject** | Restores the last exported/applied amount as the approved price and marks the suggestion rejected. It also discards an acceptance that was not yet published. |
| **Undo** | Reverses the latest eligible decision. An accepted/own price must still be waiting for publication; a rejection can also be undone. Undoing rejection reopens the decision rather than recovering a discarded unpublished approval. |
| **Lock** | Prevents engine updates and normal accept/edit/reject actions on that price. It does not publish a price or clear an existing publication queue. |
| **Unlock** | Allows decisions and future engine updates again. It does not recalculate immediately. |
| **Skip** | Moves to the next review item without a decision. The skipped item still needs review. |
| **Previous** | Returns to the previous review item without undoing its decision. |
| **Close / ×** | Closes details or the review summary; already saved decisions remain. |

The percentage buttons use rounding and, when a usable price step exists, the season range.
Do not assume manual actions have all the automatic engine protections.

**A decision made today is protected from later runs that day.** On a later day, an unlocked price
may receive a new suggestion. Use Lock for longer protection. “All done” means you reached the end
of the review queue; skipped prices may still be pending, and approved prices may still need publishing.

Some notifications say **“Your price is published”** after choosing an own price. In this version,
that means the choice was saved inside Revenue: you must still use Export approved / Apply to pricelist.

<a id="run-now-and-learn-booking-curve"></a>
## Run now and Learn booking curve

These buttons do different jobs.

### Run now: refresh today's forecasts and suggestions

Use it after changing seasons, events, or pricing settings, or when you want updated calculations.

1. Reads any configured Odoo booking/pricelist connection.
2. Checks booking-data freshness. Without fresh data, it records **Data too old** and stops calculation.
3. Forecasts each night in **Days Ahead** and creates/updates price suggestions.
4. Leaves locked prices and prices decided today unchanged by the recommendation engine.
5. Updates actual booking totals for past nights and records the result in **Engine Runs**.

It **does not** accept suggestions, publish prices, learn a new booking curve, or fetch a new CSV from
your computer. If using files, import fresh bookings first. A booking import already runs the engine;
pressing Run now again is usually unnecessary.

A scheduled job also runs daily. The exact time depends on Odoo's scheduled-action configuration.
Running repeatedly on the same day refreshes that day's forecast rather than creating separate
intraday forecast history.

### Learn booking curve: replace the expected booking-timing pattern

A booking curve describes **what share of the final bookings normally exists before arrival**.
For example, “7 days left → 80%” means that a night which eventually sells 10 rooms would normally
already have 8 booked a week ahead. It does not mean the hotel itself is 80% full.

The button:

1. Reads booking history already stored in Revenue for the last **365 days**.
2. Looks at past nights that had bookings and calculates typical booked shares at your existing lead times.
3. **Replaces** the booking-curve values in Advanced and marks their source **learned**.

By default, at least **30 past nights with bookings** are required. These are stay nights, not 30
reservation records. With too little history it shows a warning and keeps the existing curve.

Use it after importing reliable history or when you want to refresh an old booking pattern. It does
not synchronize sources, run automatically every day, or immediately change suggestions. Refresh
bookings first, learn the curve, then press **Run now** to use it in the next calculation.

The curve helps calculate “usually booked” in the **Cold start** method. A night already using
historical comparable nights may not change after learning the curve.

<a id="hotel-settings"></a>
## Hotel settings

Open **Revenue → Configuration → Hotels** and select your hotel.

### Hotel buttons

| Button | What it opens or changes |
|---|---|
| **Open calendar** | This hotel's pricing calendar. |
| **Import bookings** | A new import with this hotel selected. |
| **Run now / Learn booking curve** | The actions explained above. |
| **Needs decision / Review** | The Prices list for the hotel. Check active filters; the list normally starts with pending prices in the next 30 nights. |
| **Bookings** | This hotel's reservation records. |
| **Imports** | Previous imports and their results. |
| **Engine runs** | Calculation history and the latest run status. |
| **Remove demo hotel** | After confirmation, deletes the demo hotel and its related sample records. Available on demo hotels only. |

### Rooms and “Priced as”

| Field | Meaning |
|---|---|
| **Name** | Room type shown in the calendar, such as Standard or Deluxe. |
| **Code** | Identifier used to match imported bookings/prices to this type. |
| **Rooms** | How many rooms of this type exist. The total across active types is hotel capacity. |
| **Priced as / Amount / %** | How this type's suggestion follows the reference room; see the example below. |
| **Active** | Archive a type you no longer sell. Existing bookings/prices remain. |
| **Drag handle** | Changes display order. |
| **Odoo room product** | With the Sales module, the rental product whose bookings and prices belong to this type. |

Only one active type can be the **Reference room**. Its recommendation is calculated first.
Other types add a fixed amount or a percentage to it, separately for each night.

| Room | Priced as | Amount / % | Reference = 100 GEL | Reference = 120 GEL |
|---|---|---:|---:|---:|
| Standard | Reference room | — | 100 | 120 |
| Deluxe | Fixed amount above reference | 40 | 100 + 40 = **140** | 120 + 40 = **160** |
| Suite | Percent above reference | 25 | 100 × 1.25 = **125** | 120 × 1.25 = **150** |

Rounding and each derived room's minimum-change check can affect the final amount. Room types do
not get independent demand forecasts. Archive rather than delete types that already have bookings/prices.

### Seasons

| Field/action | Meaning |
|---|---|
| **From / To** | First and last affected nights, both included. Seasons for one hotel cannot overlap. |
| **Base Price** | Reference room's starting price before adjustments. |
| **Minimum / Maximum Price** | Bounds for its automatic recommendation. Base must fall between them. |
| **Expected Occupancy %** | Expected final fullness used when there is too little historical data. |
| **Copy to next year** | Creates another season one year later with the same settings. Check for overlapping dates. |

Example: winter base **100**, minimum **80**, maximum **160**, expected occupancy **60%**.
A night without a season receives no normal recommendation. Seasons do not repeat automatically.

### Events

Add an event in the hotel's **Events** tab or **Revenue → Configuration → Events**.
Enter its name, inclusive dates, **Price Impact %**, and an optional note.
Positive percentages raise the price; negative percentages lower it. **Category** (Event/Holiday)
changes the event-calendar color, not the pricing formula.

If events overlap, the largest **absolute** percentage wins: +10% and −20% use −20%, not their sum.
A positive selected event impact suppresses the last-minute discount. Save, then Run now to refresh suggestions.

### Pricing rules

| Setting | Default | Example/effect |
|---|---:|---|
| **Price Step** | 1 | Rounds to multiples: step 5 gives 100, 105, 110. Zero skips rounding. |
| **Maximum Change %** | 15 | Normally keeps a reference recommendation within ±15% of its current approved price. |
| **Minimum Change %** | 3 | Keeps the current price when the calculated change is smaller than 3%. |
| **Monday % … Sunday %** | 0 | A Saturday setting of +10 raises Saturday's starting calculation by 10%. |
| **Pricelist** | Optional | With Sales integration, selects the source and destination of nightly prices. |

The season range takes priority over other limits; rounding can also exceed the normal change band
when no rounded price fits it. Derived rooms do not receive their own full set of bounds/change limits.
An exact **My price** entry bypasses the automatic season bounds.

### Advanced settings

These appear for Administrators. Defaults are a starting point, not a guarantee of suitable hotel prices.

| Setting | Default | Meaning |
|---|---:|---|
| **Company / Time Zone** | Your company/user zone | Ownership, currency, and which local date counts as today. |
| **Days Ahead** | 90 | Nights calculated from today. Calendar navigation does not extend this horizon. |
| **Data Stale After Days** | 2 | Maximum age of the last booking refresh before new calculations pause. |
| **Protect Within Days / From Occupancy %** | 7 / 85% | Tries to avoid lowering a nearly full night's price close to arrival. Season bounds take priority. |
| **Last Minute Within Days / Below Occupancy % / %** | 3 / 60% / −10% | Discount factor for approaching quiet nights, unless a positive event impact applies. |
| **Pace Threshold %** | 10 | How far bookings must be ahead/behind usual before pace affects price. |
| **Pace Adjustment %** | 5 | Price factor when that threshold is exceeded; halved to 2.5% for the History forecast method. |
| **Minimum Comparable Nights** | 3 | Minimum historical comparisons needed for the History method. |
| **Comparable Window Days** | 21 | Search around the matching period of previous years, keeping the same weekday. |
| **Comparable Years** | 2 | How many earlier years to consider. |
| **Comparable Recent Weeks** | 8 | Recent same-weekday nights also considered. |
| **Nights Needed To Learn Curve** | 30 | Past nights with bookings required by Learn booking curve. |

**Demand curve** sets the adjustment for forecast occupancy. The default bands are:

| Forecast occupancy | Below 40% | 40–59% | 60–74% | 75–84% | 85–91% | 92%+ |
|---|---:|---:|---:|---:|---:|---:|
| Price adjustment | −10% | −5% | 0% | +5% | +10% | +15% |

The highest threshold reached applies; these are steps, not a smooth percentage increase.

**Booking curve** sets the share of final bookings usually present at each lead time. Defaults:

| Days left | 180 | 90 | 60 | 30 | 14 | 7 | 3 | 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Share already booked | 5% | 15% | 28% | 48% | 68% | 82% | 92% | 100% |

Values between points are interpolated. **Source** identifies default or learned points.

<a id="how-calculations-work"></a>
## How calculations work

### Forecast: how many rooms might sell?

**History method:** looks at similar past weekdays, including recent weeks and matching periods in
earlier years. It adds the typical remaining booking growth to today's bookings, capped at capacity.
Example: 12 rooms already booked + typical remaining growth of 5 = **17 forecast rooms**.
For 20 rooms, that is **85% forecast occupancy**.

**Cold start:** when too few comparable nights are available, uses season expected occupancy.
Example: 20 rooms × 60% = **12 forecast rooms**, unless already-booked rooms are higher.
The booking curve estimates how many of those bookings should normally exist by now, informing pace.

**Pace:** already booked / usually booked. A value of **1.25** means **25% ahead of usual**;
0.8 means 20% behind. If the usual count is too small, pace is unavailable.

**Confidence:** a rule-based score for method, number of comparisons, and freshness. Low is below 40,
medium 40–69, high 70+. It is not a measured probability that a forecast will be correct.

### Price: from base to recommendation

Adjustments multiply in this order: **weekday → event → demand → pace → last minute**.
Then the engine applies season bounds, busy-night protection, maximum change, rounding, and the
minimum-change rule. Other room types derive their suggestions from the reference result.

Example: base 100, Friday +20%, demand +10%, History pace +2.5%, current price 105,
season range 80–160, maximum change 15%, price step 5:

| Step | Price |
|---|---:|
| Base | 100.00 |
| Friday +20% | 120.00 |
| Demand +10% | 132.00 |
| Pace +2.5% | 135.30 — model target |
| Maximum change from 105 | 120.75 |
| Rounding inside the allowed range | **120.00 — recommendation** |

A minimum-change rule can then keep an existing price instead of making a tiny adjustment.
The calculation does not measure competitor prices or predict how a specific price change will affect demand.

<a id="import-data"></a>
## Import data

Open **Revenue → Import** and choose a hotel and file type. CSV and Excel **.xlsx** are supported.

| Button/result | Meaning |
|---|---|
| **Download template** | Downloads column names for the selected file type. |
| **Download sample data** | Downloads an example bookings file. Import it into a sample hotel for practice. |
| **Check file** | Validates and previews rows; does not import bookings or prices. |
| **Import** | Validates again, saves the data, and runs the engine. A row validation error prevents the whole import. |
| **Created / Updated** | Number of records added or changed. Identical existing records are not counted as updates. |
| **Kept, waiting for publish** | Current-price rows skipped to preserve your approved but unpublished prices. |
| **Errors** | Problems to fix before trying again. |
| **Open calendar / Import another** | Opens the result in the calendar or starts a fresh import. |

### Booking file

| Column | Meaning |
|---|---|
| `reference` | Required booking identifier. The same reference within a hotel updates the existing booking. |
| `booked_on` | Required date the booking was made. Needed to reconstruct booking pace. |
| `arrival` / `departure` | Required first night and checkout date. Oct 25–27 means nights Oct 25 and 26. |
| `room_type` | Required room code or name. Code is matched first. |
| `rooms` | Number of rooms; defaults to 1. |
| `revenue` | Total room revenue of the whole stay, not the nightly price. Use a consistent tax basis. |
| `status` | `confirmed`, `cancelled`, or `no_show`; blank means confirmed. |
| `cancelled_on` | Cancellation date, used to reconstruct when the rooms stopped counting as booked. |
| `channel` | Optional source such as Direct or Booking.com; descriptive, not a separate pricing rule. |

Revenue is spread evenly over the stay's nights. No-shows count as booked. Cancelled bookings count
until their cancellation date; with no cancellation date, the calculation treats them as cancelled
from their booking date. Reimporting a file does not automatically cancel bookings omitted from it.

### Current-price file

Use **`date`, `room_type`, `price`**: one room type and night per row. This establishes the recorded
selling-price baseline, which removes “New” when a nonzero price is known. It does not update an
external selling system. Hotels with a linked pricelist must read current prices from that pricelist.

Dates can be `2026-11-14`, `2026-11-14 00:00:00`, `14.11.2026`, `14/11/2026`, or Excel dates.
A date with `/` whose day is 12 or less, such as `11/7/2026`, can mean 11 July or 7 November:
the import refuses that row and asks for `2026-07-11`. Use UTF-8 CSV.
For comma-separated CSV, write `1200.50`; for semicolon-separated files, comma decimals such as
`1.234,56` are supported.

A booking import refreshes the booking-data timestamp; a current-price import does not.
An import can succeed even if the following engine run fails—check **Engine Runs** separately.

<a id="publish-prices"></a>
## Publish prices

**Approval saves your choice. Publishing sends it out.** The To Publish flag means the approved
amount differs from the last exported/applied amount. Reaccepting the same amount creates no price
difference to send. Locking does not remove a waiting price from the publication queue.

### Export approved — file workflow

Downloads a CSV with `date`, `room_type`, and `price` for the hotel's waiting prices, then records
those amounts as exported. Load the file into your booking system/channel manager yourself.
The module cannot confirm that a downloaded file was imported elsewhere.

### Apply to pricelist — optional Odoo connection

The [hotel_rms_sale module](../hotel_rms_sale/README.md) installs automatically when Hotel Revenue
Management and Rental are installed. Configure:

1. **Rooms → Odoo room product:** one rental product per room type. A product cannot be mapped to two types.
2. **Pricing rules → Pricelist:** the company's currency should match. Use the pricelist your bookings use.
3. **Run now:** reads bookings and prices, then calculates suggestions.

| Feature | What happens |
|---|---|
| **Booking sync** | Each run reads confirmed rental order lines for mapped products. Quotations are ignored. Cancellations, reconfirmations, and removed/changed lines update the Revenue records. |
| **Booking dates/revenue** | Booked On uses order creation date, capped at arrival. Nights come from rental periods; revenue uses the untaxed order-line subtotal converted to company currency. |
| **Current-price sync** | Reads the pricelist for mapped products and each upcoming night. Approved amounts waiting to publish are preserved. |
| **Zero pricelist price** | Marks the night Not for sale. Reopen it in the source pricelist and Run now to refresh the flag. |
| **Apply to pricelist** | Writes a fixed price per mapped room product and night, tonight or later, within the hotel's local day. Applying again updates the linked rule. |
| **No pricelist selected** | Publishing continues to use CSV export. |

The apply count includes only eligible mapped, for-sale dates from tonight onward. It can be smaller
than the general To Publish list. Applying needs **Sales: Administrator** or **Product: Manager**
pricelist access in addition to Revenue permissions.

Sync occurs on runs, not instantly after every booking change. A sync with linked room products
refreshes the booking-data timestamp. Use matching hotel/user time zones for nightly price lookup,
and check that your seasons use the intended pricelist tax basis; synced booking revenue is untaxed.
The module writes pricelist rules, not existing customer invoice amounts.

### A naming detail worth knowing

In the **Prices list**, the column named **Current** can already show your approved, unsent amount.
The list's Recommended column compares against that amount, so its change label can differ from the calendar.
In the **calendar and side panel**, the comparison uses the last imported/exported/pricelist amount.
Use **To publish**, the publish-button count, and Price History to tell whether an amount was sent.

<a id="insights-and-reports"></a>
## Insights and reports

### Insights tab

| Section/control | What it tells you or does |
|---|---|
| **Next 30 / 60 / 90 nights** | Changes the main reporting period. The weekly pickup heatmap stays at 60 upcoming nights; last-year comparison stays at 30. |
| **Revenue on the books** | Revenue already booked for the chosen future nights, compared with 7 days ago. This is not cash received or total projected future sales. Click for bookings. |
| **New bookings / Cancellations, last 7 days** | Room nights gained/lost for the selected upcoming period. One room for 3 nights is 3 room nights, not 3 reservations. Click for the underlying records. |
| **Forecast occupancy** | Expected occupancy for the chosen period. Click for forecasts. |
| **Next N nights chart** | Already-booked and forecast rooms, with reference-room recommended prices and events. Click a night or drag across dates to open the calendar there. |
| **Bookings gained this week** | Net rooms gained per stay night in the last 7 days. Positive shades mean gains, red shades mean losses, neutral means no net change. Hover for counts; click to open that night. |
| **Bookings vs last year** | Compares advance bookings with the same weekdays 364 days earlier, as known at the comparable time. It is not a comparison with last year's final occupancy. |
| **Decisions this month** | Counts accept/edit/reject actions, so repeated decisions can count more than once. Click a slice for Price History. |
| **Own prices vs recommended** | Overall percentage difference between your manual decisions and their recommendations. |
| **Acceptance trend** | Weekly share of decisions that accepted the recommendation; needs multiple weeks to show a trend. |
| **Forecast quality** | How far forecasts made 7/30 days ahead were from later booked-room totals. Lower error is better. |
| **Latest price changes** | Recent exports/applies, with date, room, old/new amount, user, and time. Click to open the price record. |

The lists behind the cards and the decisions chart open in a pop-up over Insights, so closing it keeps
your place. **Open full list** shows the same list on its own page (click a row there or in the pop-up
to open the record); Back returns to Insights with the same period.

“Needs 2 weeks of history” requires enough **completed nights with saved forecasts made 7 days ahead**;
importing two weeks of old bookings alone does not create those forecasts. Quality uses average
occupancy error: up to 5 points = Good, up to 10 = Fair, above 10 = Poor.

### Other menus

| Menu | Use it for |
|---|---|
| **Prices** | Filter and group all price records; select rows for Accept, +5%, −5%, or Lock. Default filters show pending prices in the next 30 nights—remove them to see other records. |
| **Forecast** | Graph/list of hotel-wide occupancy predictions. Show optional columns for booked rooms, usual bookings, pace, method, confidence, and later actuals. |
| **Bookings** | Inspect bookings, cancellation dates, room counts, revenue, and channels; use pivot reporting by period or type. |
| **Reports → Price History** | Audit trail for decisions, imports, locks/unlocks, undo, exports, and applies. Records include user, time, old/new amount, and notes. |
| **Reports → Forecast accuracy** | Compare past forecasts with actual booking totals, including 7- and 30-day lead times. |
| **Reports → Engine Runs** | Inspect run status, time, duration, nights forecast, prices changed, message, and the settings used. “Prices Changed” refers to recommendations, not published selling prices. |

**Actual rooms** means booked rooms reconstructed for that stay date, including no-shows; it is not
verified physical check-ins. Multiple same-day runs share that day's forecast. Historical accuracy
therefore needs ongoing daily runs and reliable booking/cancellation history.

<a id="help-and-access"></a>
## Permissions, demo data, and troubleshooting

### Who can do what?

Set **Settings → Users → Hotel Revenue**:

| Role | Access |
|---|---|
| **Viewer** | Read the hotel data, calendar, and reports. |
| **Revenue Manager** | Decide/publish prices, import, run calculations, learn the booking curve, and manage rooms, seasons, events, and operating rules. |
| **Administrator** | Also create/delete hotels, access the Advanced tab, and manage demo data. |

Users only see permitted companies. Applying to a pricelist also requires the pricelist permissions
mentioned above. Some buttons are hidden until the hotel is saved or the user has the right access.

### Demo hotel

**Revenue → Configuration → Demo Data** creates a sample hotel with rooms, seasons, events,
bookings, forecasts, and example decisions, then opens its calendar. Clicking it again opens the
existing demo. It is marked **Demo** and uses a much longer stale-data allowance for practice. **Remove demo hotel**
deletes it and its related records after confirmation; real hotels are separate.

### When something is unclear

| What you see | Meaning / next step |
|---|---|
| **No booking data · prices frozen** | Import bookings or configure and run the Odoo connection. |
| **Data too old** | Refresh bookings. Run now alone cannot refresh a file-based source. |
| **Run: Done** | Calculation completed. Read the message and counts too: a run can finish with no rooms or no reference room configured. |
| **Run: Busy** | A run is active, or another run prevented this attempt. Check the latest completed run. |
| **Run: Failed** | Read its message; an administrator can inspect the server log. |
| **Run now changed nothing** | Check stale data, locks, decisions made today, missing seasons, missing reference room, and small-change rules. Unchanged inputs can give identical results. |
| **Learn booking curve changed no visible prices** | It updates settings only. Run now afterward; History-method nights may not use that curve. |
| **Not enough history** | The required number of past stay nights with bookings is unavailable. Keep the default curve or import more history. |
| **All caught up / empty Prices list** | Current filters may hide decided or out-of-period prices. Switch to All nights/remove filters. |
| **Green accepted price, but nothing to publish** | Its approved amount already equals the recorded exported/applied amount. With Sales, also check mapped product, date, and Not for sale. |
| **No season / blank future cells** | Add a covering season, verify Days Ahead, then Run now. |
| **Two reference rooms / overlapping seasons** | Keep one active reference type and non-overlapping season dates. |
| **Cannot delete a room type** | Existing prices/bookings refer to it. Archive the type instead. |

The app does not provide competitor-rate collection, direct channel-manager publishing, minimum-stay
or arrival restrictions, group quotations, or independent demand-based pricing for each room type.
