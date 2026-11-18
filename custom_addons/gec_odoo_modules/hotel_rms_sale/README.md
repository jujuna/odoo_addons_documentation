# Hotel Revenue Management - Sales & Pricelist (`hotel_rms_sale`)

**In one sentence:** if your hotel takes bookings in Odoo (the Hotel app, rental orders, the website),
this module feeds those bookings and prices to Hotel Revenue Management and writes your approved prices
back, so there are no files to import or export.

**Who this is for:** hotels using the Odoo Hotel app. The main guide is
[hotel_rms/README.md](../hotel_rms/README.md); this page explains only what the link adds.

---

## The idea in one minute

```text
 Odoo bookings (rental orders) ──► Revenue: forecast ──► recommendation
 Odoo pricelist (today's price) ──►                         │
                                                            ▼
                                                       you decide
                                                            │
 Odoo pricelist (new price for that night) ◄── Apply to pricelist
```

Without this module you import bookings and prices from files and export approved prices to a file.
With it, Odoo is both the source and the destination.

## Set it up (once, 2 minutes)

It installs by itself when Hotel Revenue Management and Rental are both installed.

| Step | Where | What | Why |
|---|---|---|---|
| 1 | Hotel → **Rooms** tab → **Odoo room product** | The Odoo product of each room type (in the Hotel app: La Claudia, La Maria, La Nina, or yours) | Tells Revenue which bookings and prices belong to which room type |
| 2 | Hotel → **Pricing rules** tab → **Pricelist** | The pricelist your bookings use (only pricelists in the company currency are offered) | The source of today's price and where approved prices go |
| 3 | **Run now** | — | The first sync and recommendations |

Also give every user who works with bookings the hotel's time zone in their preferences (see Rules to
remember).

---

## The features, one by one

### Bookings from Odoo

| | |
|---|---|
| **What** | Every run reads the rental orders of your room products and turns them into the hotel's bookings |
| **Why** | The forecast always works with today's bookings, without any import |
| **When** | Automatically: daily, after **Run now**, and after every import |
| **How** | Nothing to do. **Revenue > Bookings** shows them |
| **Connected to** | Booking data never gets old while Odoo bookings are linked, because every run reads them fresh |

| In Odoo | In Revenue |
|---|---|
| Confirmed rental order | A booking: arrival and nights from the rental dates, rooms = quantity, revenue = amount without tax, booked on = the day the order was created (never later than arrival) |
| Order cancelled | The booking counts as cancelled from that day |
| Cancelled order confirmed again | Confirmed again |
| Order line deleted or product changed | Cancelled |
| Quotations (not confirmed) | Ignored |

### Today's price from the pricelist

| | |
|---|---|
| **What** | For every night ahead, the price the pricelist gives your room product today |
| **Why** | A recommendation is always compared with the price guests really see |
| **When** | Every run |
| **How** | Nothing to do. A price you approved but did not yet apply is kept, not overwritten |
| **Connected to** | The **Current prices** import is switched off for a hotel with a pricelist: the pricelist is the source |

### Not for sale

| | |
|---|---|
| **What** | Nights where the pricelist gives price 0 |
| **Why** | The Hotel app uses price 0 to close far-future dates (its booking blocker). Revenue must never reopen them |
| **When** | Automatic |
| **How** | Those cells show **Not for sale**: no recommendation, no decision possible. The **Not for sale** filter in **Prices** lists them |
| **Connected to** | Open the night in the pricelist and it becomes a normal night at the next run |
| **Limit** | A price you already applied for a night wins over a closing rule added later for the same dates: the night stays for sale. To close it, delete that night's price line in the pricelist; the next run shows it as **Not for sale** |

### Apply to pricelist

| | |
|---|---|
| **What** | The publish button, now writing approved prices into the Odoo pricelist |
| **Why** | The website and every new booking charge the new price at once |
| **When** | After your decisions; the button shows how many prices wait |
| **How** | **Apply to pricelist** in the calendar header. Each approved price becomes a fixed price for that room product and that night only, midnight to midnight in the hotel's time zone. Applying the same night again updates that price instead of adding a second one. Only future nights are applied |
| **Connected to** | Needs **Sales: Administrator** or **Product: Manager**; others can decide but not apply. Each apply is recorded in **Price History** |

**Example:** the pricelist gives La Claudia 95 on Saturday 14 November. You accept the recommendation
115 and press **Apply to pricelist**. A booking for that Saturday now costs 115 per night; Friday and
Sunday keep 95.

---

## Rules to remember

| Rule | Why it matters |
|---|---|
| **Room options keep their surcharge.** Revenue prices the room product; options like breakfast or extra guests add their own amount on top | In the Hotel app "La Claudia, 1 person, breakfast" costs 20 more than the room: apply 81 and that option is charged 101 |
| **One Odoo product per room type** | Two room types on one product would overwrite each other's prices |
| **Set every user's time zone** to the hotel's | Odoo reads a night's price in the time zone of the person asking; a user without one sees an applied price one night early in the Hotel app's daily revenue lines |
| **Prices in the pricelist's terms** | The Hotel app's prices include tax, so enter seasons and limits on the same basis |

## When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| An Odoo product can be the room product of one room type only. | The product is already used | Pick another product |
| The current prices of this hotel come from its pricelist. | Current-prices import while the pricelist is linked | Import bookings only, or none: they come from Odoo |
| Applying prices to the pricelist needs the access right | Missing pricelist rights | Ask an administrator for Sales: Administrator or Product: Manager |

## Good to know

- When a guest checks in or out, the Hotel app recalculates that booking's daily revenue lines at
  today's pricelist price. After a price change those lines can show the new price; the booking's
  invoice does not change.
