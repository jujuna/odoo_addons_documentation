# POS Wolt Drive

> **Module:** `pos_wolt_drive` | **Path:** [`custom_addons/gec_odoo_modules/pos_wolt_drive/`](../custom_addons/gec_odoo_modules/pos_wolt_drive/)

## What It Does & Why It Exists

A shop that sells in its own Point of Sale and delivers the order itself can hand the delivery to a Wolt courier
instead of its own driver. Wolt Drive is Wolt's on-demand courier service: the shop asks for a price, books a courier,
and Wolt reports where the courier is. This module puts that into the POS. The cashier opens a paid order, sees the
binding price and the arrival time, books the courier with one click, and follows the status on the receipt screen
and on the order. Orders that come in through the Wolt marketplace do not need it; they bring their own courier
(see [`pos_platform_order_wolt.md`](pos_platform_order_wolt.md)).

---

## The Big Picture — How It Works

```
Admin: Settings > Wolt Drive (venue, merchant, key) --> Register Status Webhook
Cashier: paid order with customer address --> "Wolt Courier" --> quote (price, ETA) --> book
Wolt: courier assigned --> at pickup --> picked up --> delivered / not delivered / rejected
      (signed webhook) --> order status, ETAs, chatter, POS badge refresh
```

1. An administrator enters the shop's Wolt Drive venue, merchant ID and API key, and registers the status webhook. The
   webhook gets its own signing secret per POS.
2. On the receipts screen the cashier selects a paid order. The **Wolt Courier** button appears when the order can get
   a courier: venue set, a paid sale (no refund, no negative total), no active courier, and a customer with a phone, a
   street and a city or zip ([`pos_order.js:23-33`](../custom_addons/gec_odoo_modules/pos_wolt_drive/static/src/app/pos_order.js#L23);
   the server checks the same in [`pos_order.py:112-120`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L112)).
3. The button asks Wolt for a **shipment promise** for the customer address and shows "Book the courier for 8.60, at
   the customer in about 25 minutes?". Only a binding promise is accepted.
4. On confirm the order is booked with the promise. Odoo stores the Wolt reference, price, tracking link and ETAs.
5. Wolt sends each courier event to the POS's webhook URL. Odoo checks the signature, moves the status forward, posts
   the change in the chatter and refreshes the order in the POS.
6. While the courier has not started the pickup, **Cancel Courier** cancels it at Wolt.

### Key Decision Points
- **Venue ID empty or set:** an empty venue turns the whole feature off for that POS; the other settings and the
  button are hidden.
- **Test mode:** on (the default) sends every call to Wolt's development API, off to production
  ([`drive_request.py:11-14`](../custom_addons/gec_odoo_modules/pos_wolt_drive/utils/drive_request.py#L11)).
- **Book or not:** the cashier sees the price and ETA first and can say no; nothing is booked before the confirm.

---

## When to Use It (and When Not To)

### This module is for:
- A restaurant or shop that takes phone or counter orders in the POS and wants a Wolt courier to deliver some of them.
- Shops with a Wolt Drive merchant account (merchant ID, API key) and a venue per pickup address.

### Use something else when:
- The order comes from the Wolt marketplace — use `pos_platform_order_wolt`; Wolt sends its own courier.
- Deliveries are planned in advance or batched — Wolt Drive books one courier per order, now.

---

## Real-World Scenarios

### Scenario 1: A phone order delivered by Wolt
**Situation:** A pizzeria takes a phone order from Nino, paid by card at the counter, with her phone, street and city.
**What they do:** in the open POS, **Orders** (top bar), filter **Paid**, select Nino's order, **Wolt Courier**, confirm
"Book the courier for 8.60, at the customer in about 25 minutes?".
**What happens:** Wolt books a courier. The order shows "Wolt courier requested" and a **Tracking link**; the backend
order gets a **Wolt Courier** page with the status, price 8.60, reference and ETAs. When the courier arrives, picks the
pizza up and delivers it, the badge changes to "Wolt courier on the way", "Wolt courier arrived", "Picked up by Wolt",
"Delivered by Wolt", and the chatter logs each step.

### Scenario 2: The customer cancels before the courier comes
**Situation:** Five minutes after booking, Nino calls to cancel.
**What they do:** Select the order, **Cancel Courier**, confirm "Cancel the Wolt courier?".
**What happens:** Wolt cancels the delivery, the status becomes Cancelled, the chatter says "Wolt courier cancelled.".
If the courier has already started the pickup, Odoo refuses: "Contact Wolt support to cancel: the courier is already
on the way." The order can be booked again later with a new Wolt reference (attempt 2).

### Scenario 3: The address is too vague
**Situation:** The customer gave only a street.
**What happens:** Wolt answers with a non-binding promise and Odoo stops: "Add the customer's street and city or zip
so Wolt can price the delivery." Without a phone or a street the button does not show at all.

---

## How Things Work Under the Hood

### Core Logic
- **wolt_drive_quote()** ([`pos_order.py:46-67`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L46))
  — sends the dropoff address (street + street2, city, zip, coordinates when the partner has them), the preparation
  minutes and the parcel to `POST /v1/venues/<venue>/shipment-promises`; returns the promise id, the dropoff location
  Wolt resolved, the price (Wolt's minor units converted, [`:131-132`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L131))
  and the ETA.
- **wolt_drive_book()** ([`pos_order.py:69-99`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L69))
  — books with the promise. The merchant reference is `<receipt number>-<attempt>`, and the attempt is stored only
  after Wolt accepted, so a retry after a timeout sends the same reference and Wolt answers `DUPLICATE_ORDER` instead of
  sending a second courier ([`:80-81`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L80)).
- **_wolt_drive_handle_event()** ([`pos_order.py:150-174`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L150))
  — finds the order by Wolt reference within the POS's company, maps the event to a status
  ([`:9-20`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L9)) and applies it only when it ranks
  higher than the current one, so a late "pickup started" after "picked up" changes nothing; a final status (delivered,
  not delivered, cancelled) never changes again. ETAs are updated from every event.
- **_wolt_drive_relink()** ([`pos_order.py:176-199`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_order.py#L176))
  — when Wolt reports a delivery Odoo does not know (the booking reached Wolt but Odoo rolled back), it finds the order
  by its receipt number and venue and links it, so the courier is not lost.
- **Webhook** ([`controllers/main.py:14-29`](../custom_addons/gec_odoo_modules/pos_wolt_drive/controllers/main.py#L14))
  — `POST /wolt_drive/webhook/<pos id>` with `{"token": <JWT>}`; the token must be HS256-signed with that POS's secret
  ([`pos_config.py:51-65`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_config.py#L51)), otherwise 403.

### Important Fields (only the ones that matter)
- `pos.order.wolt_drive_status` — Courier Requested, Courier on the Way, Courier Arrived, Picked Up, Delivered, Not
  Delivered, Cancelled. Cancel works only in Courier Requested; booking again works once the status is final.
- `pos.order.wolt_drive_ref` / `wolt_drive_attempt` — Wolt's reference and the attempt number behind the merchant
  reference; the attempt makes a rebook after a cancel a new delivery at Wolt.
- `pos.config.wolt_drive_venue_id` — the switch for the whole feature in one POS.

---

## Configuration & Settings

All in Point of Sale > Configuration > Settings > **Wolt Drive** (the Settings menu is for administrators,
[`point_of_sale_view.xml:54-59`](../addons/point_of_sale/views/point_of_sale_view.xml#L54)).

- **Venue ID** — the shop's venue in Wolt Drive. Empty: no Wolt couriers in this POS.
- **Merchant ID**, **API Key**, **Test Mode** — administrators only (`groups='base.group_system'`,
  [`pos_config.py:22-24`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_config.py#L22)); cashiers can neither
  see nor change them, although core lets them write other POS settings.
- **Preparation (min)** — minutes before the courier may pick up (default 30); sent with every quote.
- **Register Status Webhook** — creates a new 64-character signing secret and registers
  `<base URL>/wolt_drive/webhook/<pos id>` at Wolt with it ([`pos_config.py:34-49`](../custom_addons/gec_odoo_modules/pos_wolt_drive/models/pos_config.py#L34)).
  Without it the order keeps "Courier Requested" forever: Odoo never hears about the courier.

---

## Dependencies

| Requires | Why |
|---|---|
| `point_of_sale` | orders, receipts screen, POS settings, bus notifications to the POS |

---

## Gotchas & Non-Obvious Behavior

- **Register again after switching test mode:** the webhook lives in the environment it was registered in; a new
  registration does not remove the old Wolt webhook (no webhook id is stored; audit D4).
- **The token has no expiry check:** the JWT is checked for its signature only; `exp` / `dispatched_at` are not read.
- **Preparation "0-60" is a hint:** the help text says 0-60, but no constraint enforces it.
- **An administrator's POS loads the key:** the POS front end reads every `pos.config` field the user may read, so an
  administrator's browser receives the API key and webhook secret (audit D6, as in core `l10n_eg_edi_pos`).
- **Tests need `pos_restaurant`:** the test classes and the tour import `pos_restaurant`, which the manifest does not
  depend on (audit D5).
- **Georgian:** `i18n/ka_GE.po` covers every text (Python, JS, views, fields); "Venue" is "ობიექტი".

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`pos_platform_order_wolt.md`](pos_platform_order_wolt.md) — Wolt marketplace orders in the POS
- Work log and audit: `dev_notes/plans/wolt_fix_plan_20261031.md`, `dev_notes/plans/wolt_modules_audit_20261031.md`
