# Platform Order Provider: Glovo (`pos_platform_order_glovo`)

Glovo orders arrive in the Point of Sale by themselves, and the sale is booked when the courier picks the order up.
No retyping from the Glovo tablet.

**Who this is for:** cashiers and kitchen staff who handle Glovo orders, POS managers who repair stuck orders, and the
admin who connects the store. Developers: [README_DEV.md](README_DEV.md).

## 1. What it does

| Feature | What you get |
|---|---|
| New Glovo order | A draft POS order with its lines, pickup code, courier name and how Glovo pays |
| Set Food Ready | Glovo is told the order is ready, from the POS or with **Done** on the preparation display |
| Courier picks up | The sale is booked and paid in the open session, without the cashier |
| Customer picks up | The cashier presses **Customer Picked Up**: Glovo is told, and only then the sale is booked |
| Glovo cancels | The POS order is cancelled |
| Locked orders | Cashiers cannot edit, pay, cancel or refund a Glovo order, so the books match what Glovo pays |
| Automatic retry | A notification that failed (POS closed, unknown product) is tried again every 5 minutes |
| Manager repair | **Retry** on a Glovo event, **Glovo: mark picked up** and **Glovo: mark cancelled** on an order |
| Georgian | Every screen text and message is translated |

## 2. Quick facts

| | |
|---|---|
| Menus | **Point of Sale > Configuration > Platform Orders > Providers / Stores / Glovo Events** |
| Added to POS orders | **Action > Glovo: mark picked up** and **Glovo: mark cancelled** (list and form) |
| Added to Glovo events | **Retry** |
| Who | Cashiers: Set Food Ready, Customer Picked Up. POS managers (Point of Sale / Administrator): provider, stores, events, repairs |
| Needs | Point of Sale with Platform Orders (Enterprise), a chart of accounts |
| Delivery | Glovo couriers, or the customer picks the order up at the store |

## 3. How it works

```text
Glovo: new order ──────► Draft POS order (accepted)
                              │  kitchen prepares
                              ▼
Cashier: Set Food Ready ──► Glovo: "ready for pickup"
                              │
Glovo: courier picked up ─► Sale booked and paid (delivered)
Cashier: Customer Picked Up ► Glovo told, then sale booked (customer pickup orders)

Glovo: cancelled ─────────► Order cancelled (any time before pickup)
```

Glovo sends three notifications: new order, picked up, cancelled. Each is saved as a **Glovo event** before Odoo
applies it, so nothing is lost when something goes wrong. If one arrives before the order exists (Glovo does not
promise an order), Odoo applies it as soon as the order is created, in the order they arrived.

## 4. Set it up (once)

1. **Provider** (**Point of Sale > Configuration > Platform Orders > Providers > Glovo**):
   - **Token**: the token from your Glovo account manager. Odoo sends it to Glovo and checks it on every notification.
   - **State**: **Test** uses Glovo's stage system, **Enabled** production. Notifications for a **Disabled** provider
     are saved as failed events.
2. **Store** (**Platform Orders > Stores**): **External ID** = Glovo's store address external ID; link the Point of
   Sale and the **Glovo** payment method.
3. **Products**: the **Internal Reference** of each Odoo product = Glovo's product ID.
4. **Cash payment method**: the Point of Sale needs one cash payment method for Glovo CASH orders (section 5).
5. **Give Glovo the three addresses** (HTTPS only, the token travels in a header):
   - `https://<your host>/glovo/order/dispatched`
   - `https://<your host>/glovo/order/picked_up`
   - `https://<your host>/glovo/order/cancelled`

   The host must open exactly one database: Glovo cannot choose one.

Installing creates the provider (disabled), a bank journal **GLOVO**, a payment method **Glovo** and a pricelist
**Glovo**. Uninstalling keeps them, because they can carry payments; a reinstall reuses them.

Two system parameters (**Settings > Technical > System Parameters**), both optional:

| Parameter | Default | Effect |
|---|---|---|
| `pos_platform_order_glovo.event_retry_hours` | 24 | How far back the automatic retry looks for failed events |
| `glovo_base.event_retention_days` | 90 | Events older than this are deleted daily, whatever their state; 0 keeps everything. The POS orders stay |

## 5. How a Glovo order is paid

Glovo says how it pays the store. The POS shows it on the order list.

| Glovo sends | Meaning | Booked on | POS shows |
|---|---|---|---|
| DELAYED | Glovo pays the store by invoice | the **Glovo** payment method | Paid by Glovo invoice |
| CASH | The courier pays the store at pickup | the Point of Sale's **cash** payment method | Courier pays cash: <total> |

The amount is the order total Odoo computes from the lines. Nobody can type another amount: the lines, their taxes and
the order's fiscal position are locked.

**Example: line prices.** Glovo sends prices in cents, tax included.

| Glovo line | Odoo line total |
|---|---|
| Burger 10.00, extra meat 3.00, quantity 2, discount 15.50 | 2 × (10.00 + 3.00) − 15.50 = 10.50 |
| Ice cream 4.80, quantity 1 | 4.80 |
| **Order** | **15.30** |

With an 18% VAT that is not included in the price, Odoo shows 12.97 untaxed and 2.33 tax: the total stays 15.30. If
Odoo's total differs from Glovo's total after discounts, the new-order event shows both in its **Error** field.

## 6. Glovo events and retries

**Point of Sale > Configuration > Platform Orders > Glovo Events** lists every notification.

| State | Meaning |
|---|---|
| Received | Saved, being applied |
| Processed | Applied |
| Failed | Not applied; the reason is in **Error** |

A failed event is tried again by itself every 5 minutes for 24 hours, but only while its store's Point of Sale has an
open session and the provider is not disabled. A POS manager can press **Retry** at any time, on one event or on
several selected events. An event that was already applied is never applied twice.

**Example.** The shop opens at 10:00, a Glovo order arrives at 09:50: the event fails with "No open POS session.".
The cashier opens the session at 10:00; by 10:05 the order is in the POS.

## 7. Step by step: one Glovo order

1. The order appears in the POS order list with a **Glovo** badge, the pickup code and the courier.
2. The kitchen prepares it. Press **Set Food Ready** in the POS, or **Done** on the preparation display.
3. The courier collects it. Glovo's picked-up notification books the sale: the order becomes paid, status delivered.
   Nothing to do at the till. **Customer pickup** (the order shows the pickup type): when the customer takes the
   bag, press **Customer Picked Up**. Odoo tells Glovo first; only when Glovo accepts is the sale booked. If Glovo
   refuses, nothing is booked and the POS says why.
4. At closing, the session cannot close while a Glovo order is still draft (section 9).

## 8. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Glovo orders can't be changed or paid in the POS | Glovo pays the store; the order is locked | Nothing: the courier's pickup books it |
| Glovo orders can't be cancelled here / Refuse the order in the Glovo Partner Webapp | Glovo has no way for the store to refuse an order | Refuse it in the Glovo Partner Webapp or through Glovo support |
| Only a POS manager can refund a Glovo order | Refunds and deleting payments are repair tools | Ask a POS manager |
| Glovo isn't responding | Glovo did not answer Set Food Ready | Try again in a minute |
| Glovo refused the store's token | The token is wrong or for the other system (test or production) | A POS manager checks the provider **Token** |
| Glovo couldn't mark this order ready / picked up | Glovo refused the call | Check the order in the Glovo Partner Webapp |
| Only an order the customer collects at the store can be marked picked up by the customer. | The order is a courier order, or already paid or cancelled | Nothing: the courier's pickup books a courier order |
| Glovo: order ... belongs to another store. | A notification named a store that does not own this order (two stores or companies use one Glovo store ID) | Check which store and company the order belongs to; the order was not changed |
| Glovo: no product with Internal Reference | A Glovo product ID is unknown | Set it as a product's **Internal Reference**; the retry picks it up |
| Add a cash payment method to | A CASH order was picked up and the Point of Sale has no cash method | Add one to the Point of Sale; the retry books it |
| No open POS session. | The new order arrived while the POS was closed | Open the session; the retry creates it |
| Order already paid in Odoo | Glovo's pickup arrived for an order already paid | Check the order; nothing was booked twice |
| Glovo: order ... was picked up by the courier but is cancelled in Odoo | Glovo's pickup arrived after a cancel | Check it in the Glovo Partner Webapp |
| Only a POS manager can retry Glovo events. | **Retry** needs a POS manager | Ask a POS manager |
| Processed Glovo events can't be retried. | The event was already applied | Nothing to do |
| This event is being processed right now | Glovo's notification is being applied at this moment | Try again in a moment |
| Select only Glovo orders. | The repair action was used on other orders | Select Glovo orders only |
| The Glovo token must contain only ASCII characters. | A pasted token has a hidden character | Paste the token again |

## 9. Repair a stuck order (POS managers)

The session close shows "Ask a POS manager to resolve Glovo order ..." while a Glovo order is still draft. Check the
order in the Glovo Partner Webapp, then on the POS order use **Action**:

| Action | Use it when | Result |
|---|---|---|
| **Glovo: mark picked up** | The courier or the customer collected the order but nothing booked it | The sale is booked as if Glovo had sent it |
| **Glovo: mark cancelled** | Glovo cancelled the order, or confirmed nobody will collect it | The order is cancelled |

Both ask for a **Reason**, which is posted on the order.

## 10. Rules to remember

- Glovo orders are paid only by Glovo's pickup notification (or **Glovo: mark picked up**), never at the till.
- Only Glovo can cancel a Glovo order; the store refuses it in the Glovo Partner Webapp.
- Set Food Ready tells Glovo for every Glovo order, courier or customer pickup.
- The provider has one **Token** field, but Glovo gives one token for test and another for production: change the
  **Token** whenever you switch the provider state.

## 11. Known limitations

- **Customer pickup:** Glovo's picked-up notification is sent for couriers; for an order the customer collects, the
  cashier presses **Customer Picked Up**. Whether Glovo accepts Set Food Ready for these orders is not confirmed.
- **Preparation display bulk actions:** "done" for all orders and "clear all" do not tell Glovo; use **Done** per order.
- **Cancel after pickup:** the sale stays booked and the cancel event fails; Glovo may still pay nothing. A manager
  decides on a refund.
- **Same store ID in two companies:** allowed when each company has its own Glovo token: Odoo picks the store whose
  token matches, and a notification never changes another store's order.
- **Totals:** a difference between Odoo's and Glovo's total is only shown on the event, not corrected.
- **Currency:** Glovo's order currency is not checked against the Point of Sale's currency.
- **A failure that cannot heal** (for example a cancel after pickup) is retried every 5 minutes until the retry window
  ends.
- **Not available:** menu synchronisation to Glovo, and the calls for stores that deliver with their own couriers.
