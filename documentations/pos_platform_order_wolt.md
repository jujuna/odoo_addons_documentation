# Platform Order Provider: Wolt

> **Module:** `pos_platform_order_wolt` | **Path:** [`custom_addons/gec_odoo_modules/pos_platform_order_wolt/`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/)

## What It Does & Why It Exists

Restaurants that sell on Wolt get orders on a Wolt tablet and retype them into the POS, and change prices or opening
hours twice. This module makes Wolt one more provider of core `pos_platform_order`, next to GoFood and GrabFood. Wolt
orders arrive in the POS by signed webhook, with lines, options, notes and the courier status. The cashier accepts or
rejects them, marks the food ready, and Odoo tells Wolt. The POS pays the order when Wolt's courier collects it or Wolt
reports it delivered. In the other direction Odoo pushes the menu, price and availability changes, the online/offline
switch and the weekly opening hours to Wolt. Each Odoo store links to one Wolt venue through Wolt's self-service
onboarding (SSIO).

---

## The Big Picture — How It Works

```
Admin: provider (Client ID/Secret, signing secret) --> store: Connect to Wolt --> Sync Menu
Wolt order --> webhook (signed) --> POS order "new"/"accepted" --> Accept / Reject / Set Food Ready
          --> courier, pickup, delivered notifications --> order paid --> session close
Product price/availability change --> queued --> cron pushes it (max once per 15 min per venue)
```

1. **Provider.** Point of Sale > Configuration > Platform Orders > Providers > Wolt: the administrator enters the
   **Client ID** and **Client Secret** from Wolt, generates the **Webhook Signing Secret**, and gives Wolt the **Order
   Webhook URL**, the **Redirect URL** and the secret
   ([`platform_order_provider_views.xml:10-28`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/views/platform_order_provider_views.xml#L10)).
   The provider's state (Test or Enabled) chooses Wolt's development or production hosts
   ([`const.py:5-17`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/utils/const.py#L5)).
2. **Store.** Platform Orders > Stores: the store gets its POS, payment method and pricelist, then **Connect to Wolt**
   opens Wolt's onboarding page; Wolt returns to Odoo with a one-time code, Odoo exchanges it for the venue's tokens and
   stores the venue id ([`platform_order_entity.py:53-99`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L53)).
3. **Menu.** **Sync Menu** posts the store's whole menu to Wolt: one category per product, tax-included prices in major
   units, options from attribute lines, descriptions, photos through a signed image link
   ([`:324-431`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L324)).
4. **Orders.** Each Wolt notification hits `/wolt/webhook`. A new order is fetched from Wolt and created in the POS;
   later notifications move its status ([`pos_order.py:42-87`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/pos_order.py#L42)).
5. **Payment.** When the courier collects the order or Wolt reports it delivered, the order is paid with the store's
   payment method in the open session.
6. **Every 5 minutes** a scheduled action imports queued orders, pays orders left unpaid, pushes queued price and
   availability changes and keeps idle venues' tokens alive.

### Key Decision Points
- **Accept or reject:** an instant order waits for the cashier (Wolt rejects it on its own after 3 minutes,
  [`platform_order_provider_data.xml:9-10`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/data/platform_order_provider_data.xml#L9));
  orders Wolt already accepted, or accepts itself, arrive as accepted
  ([`platform_order_entity.py:154-156`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L154)).
- **Unknown items:** set **Product for Unknown Wolt Items** on the store to import orders with items Odoo does not
  know; without it such an order is refused and retried.
- **Online or offline:** **Go Offline** stops Wolt orders for the venue until **Go Online**.

---

## When to Use It (and When Not To)

### This module is for:
- A restaurant that sells on Wolt and wants Wolt orders, prices and opening hours handled from the Odoo POS.
- Several venues (stores) per company, each linked to its own POS.

### Use something else when:
- The shop wants a Wolt courier for its own POS orders — use `pos_wolt_drive` ([`pos_wolt_drive.md`](pos_wolt_drive.md)).
- The marketplace is GoFood or GrabFood — use the core providers `pos_platform_order_gofood` / `_grabfood`.

---

## Real-World Scenarios

### Scenario 1: An instant delivery order
**Situation:** A burger restaurant's POS is open. A customer orders 2 burgers with cheese and a cola on Wolt.
**What they do:** The POS shows "New platform order received.". The cashier opens Orders, finds "Wolt #<number>",
clicks **Accept Order** within the countdown, prepares the food, clicks **Set Food Ready**.
**What happens:** Odoo accepts the order at Wolt and reports the food ready. When Wolt's courier picks it up, the
order becomes Collected and is paid with the "Wolt" payment method in the open session. The cheese shows on the
kitchen ticket as the line's option.

### Scenario 2: A preorder for tomorrow
**Situation:** On Monday evening a customer preorders for Tuesday 12:00.
**What happens:** The order arrives with its time (**Hour**, `preset_time`); the cashier confirms it with **Accept
Order**. At Monday's session close core detaches the future order from the session, so it does not block the close.
On Tuesday the scheduled action attaches it to the open session; it is paid there when Wolt reports the pickup or the
delivery ([`platform_order_entity.py:474-507`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L474)).

### Scenario 3: An order while the POS is closed
**Situation:** No POS session is open.
**What happens:** An instant order still waiting for the venue is rejected at Wolt with the reason "Shop is closed.".
A preorder, or an order Wolt already accepted, is queued; the scheduled action imports it as soon as a session opens
([`:286-304`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L286)).
If Wolt reports a queued order delivered while the POS is still closed, Odoo records the status and pays the order in
the next session.

### Scenario 4: A price change
**Situation:** The manager raises the cola from 3.00 to 4.00.
**What happens:** The product is queued under **Wolt Items to Push** on the store. Within 5 minutes (at most once per
15 minutes per venue, Wolt's limit) the scheduled action sends the new tax-included price in minor units (4.72 with
18% VAT becomes 472) and clears the queue ([`:448-472`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L448)).

### Scenario 5: Reject an order
**Situation:** The kitchen runs out of buns.
**What they do:** Delete icon on the order, confirm, pick the reason "Items unavailable".
**What happens:** Odoo rejects at Wolt with Wolt's code and a text the customer sees, then cancels the order. If Wolt
refuses (it may have accepted the order meanwhile), the order stays in the POS and the chatter says "Wolt refused the
rejection: ...". An order already accepted cannot be rejected from Odoo: "Contact Wolt support to reject an order that
is already accepted." ([`pos_order.py:89-102`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/pos_order.py#L89)).

---

## How Things Work Under the Hood

### Core Logic
- **wolt_webhook()** ([`controllers/main.py:20-37`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/controllers/main.py#L20))
  — finds the store by Wolt venue id, checks the `WOLT-SIGNATURE` header (hex HMAC-SHA256 of the raw body with the
  signing secret, [`platform_order_provider.py:43-50`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_provider.py#L43)),
  answers 403 for an unknown venue or a bad signature, 503 when a new order could not be imported (Wolt retries), 200
  otherwise.
- **_wolt_handle_notification()** ([`platform_order_entity.py:128-145`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L128))
  — an existing order gets its status updated; an unknown order is fetched from Wolt and created in a savepoint; when
  the fetch or the import fails, the order reference is queued for the scheduled action.
- **_update_order_status_from_data()** ([`pos_order.py:42-87`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/pos_order.py#L42))
  — courier, pickup, PRODUCTION and DELIVERED notifications first accept a still-new order (Wolt sends them only after
  acceptance), then move it: courier assigned, collected (paid), food ready, delivered (paid if not yet), cancelled. A
  notification for a status the order is already past is skipped.
- **_get_access_token()** ([`platform_order_wolt_token.py:31-63`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_wolt_token.py#L31))
  — Wolt refresh tokens are single-use and a replayed one revokes the new pair, so the refresh runs under a row lock on
  the token row in its own cursor and commits at once.
- **_cron_wolt_sync()** ([`platform_order_entity.py:509-537`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L509))
  — per connected store, in that store's company: attach detached drafts to the open session, pay collected or
  delivered drafts that have no payment yet (a failed payment is retried every run), import queued orders, push queued
  item changes, refresh a token that expired more than a day ago (Wolt's refresh token lives 30 days). Each store is
  committed on its own.

### Important Fields (only the ones that matter)
- `wolt_fallback_product_id` (**Product for Unknown Wolt Items**) — imports items Odoo does not know as this product
  with Wolt's item name; empty means such orders are refused.
- `wolt_pending_order_refs` — Wolt orders received while the POS was closed or whose import failed; not shown in any
  view, emptied by the scheduled action.
- `wolt_pending_product_tmpl_ids` (**Wolt Items to Push**) — products whose price or availability changed since the
  last push.
- `pos.order.wolt_order_type` (instant / preorder) and `wolt_self_delivery` (**Delivered by Venue**) — choose the
  accept call and whether the shop may click **Mark Delivered**.

---

## Configuration & Settings

- **Provider state** (Disabled / Test / Enabled) — Test uses Wolt's development hosts, Enabled production; while
  disabled, every Wolt call says "Enable the Wolt provider (test or production) first.".
- **Client ID / Client Secret** — from Wolt's developer portal; the secret is for administrators only.
- **Generate Signing Secret** — a new 64-character secret; Wolt keeps signing with the old one until it gets the new
  one, so notifications are refused in between (confirm text in the form).
- **Store > Wolt tab** — **Check Status**, **Go Online**, **Go Offline**, **Push Opening Hours** (sends the store's
  **Service Hours** as weekly windows; an empty calendar is refused because it would close the venue for the week,
  [`platform_order_entity.py:550-577`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L550)).
- **Product > Available for Platform Orders** — sent to Wolt as the item's enabled flag.

---

## Dependencies

| Requires | Why |
|---|---|
| `pos_platform_order` | the provider/store models, the POS order statuses, the accept / reject / food-ready flow and screens |

| Works With (optional) | What It Adds |
|---|---|
| `pos_wolt_drive` | Wolt couriers for the shop's own POS orders (independent; no shared code) |

---

## Gotchas & Non-Obvious Behavior

- **Menu prices in major units:** the full menu sends 10.00 as 10; Wolt does not document the unit for the menu POST
  (not verified, audit Q1). Item price pushes use minor units (472).
- **Only the POS company's products reach Wolt:** the store's menu keeps products of its POS's company, its parent
  companies and shared ones ([`platform_order_entity.py:441-446`](../custom_addons/gec_odoo_modules/pos_platform_order_wolt/models/platform_order_entity.py#L441)).
- **A failed Sync Menu** saves **Failed** and shows a red notification; while a store is Failed, core stops queuing price
  changes for it until a sync succeeds.
- **Customers only for self-delivery:** Wolt shares a phone number only when the venue delivers itself; the contact is
  matched by phone among the contacts the order's company may use (its own, a parent's, shared), a new one is
  created in that company, and an existing contact's address is not updated (audit W7).
- **Single-value attributes are left out of the menu,** so a product with one single-value line and one multi-value
  line can import the wrong variant (audit W6).
- **Queued orders are invisible:** nothing in a view shows `wolt_pending_order_refs` (audit W8).
- **The backend Payment button** on a Wolt order can add a second payment after the scheduled action paid it (core
  wizard); do not use it on Wolt orders.
- **Georgian:** `i18n/ka_GE.po` covers every text; "Venue" is "ობიექტი".

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`pos_wolt_drive.md`](pos_wolt_drive.md) — Wolt couriers for the shop's own POS orders
- Work log, audit and cleanup plan: `dev_notes/plans/wolt_fix_plan_20261031.md`,
  `dev_notes/plans/wolt_modules_audit_20261031.md`, `dev_notes/plans/wolt_modules_cleanup_plan_20261031.md`
