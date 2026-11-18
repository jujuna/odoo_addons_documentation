# Platform Order Provider: Glovo (`pos_platform_order_glovo`) — Developer guide

For developers changing the Glovo provider. User steps: [README.md](README.md). API source of truth: the Glovo
Partners API definition (`glovo_api.md`, kept outside the repository). Shared base: `glovo_base`.

## 1. Purpose and facts

Glovo is one more provider of core `pos_platform_order`, next to GoFood and GrabFood. Glovo's three webhooks create,
pay and cancel POS orders; Set Food Ready calls Glovo's `ready_for_pickup`; Customer Picked Up calls
`customer_picked_up` and books the sale. Cashiers cannot change Glovo orders otherwise.

| | |
|---|---|
| Depends | `pos_platform_order` (the provider framework), `glovo_base` (`glovo.event` inbox, `GlovoClient`) |
| New models | `pos.glovo.order.resolve` (wizard) |
| Extended | `glovo.event`, `platform.order.provider`, `platform.order.entity`, `pos.order`, `pos.order.line`, `pos.payment`, `pos.session` |
| Hooks | `post_init_hook` → core `setup_provider`; `uninstall_hook` → core `reset_platform_provider` |
| Cron | `ir_cron_glovo_retry_failed_events`, every 5 minutes, `base.user_root` |
| Routes | `POST /glovo/order/dispatched`, `/glovo/order/picked_up`, `/glovo/order/cancelled` (`auth='public'`, `csrf=False`) |

Data in manifest order: the provider record (noupdate), the cron (noupdate), the provider form (Token), the event
list/form (Retry), the menu, the two wizard actions bound to `pos.order`, `security/ir.access.csv`.

## 2. Architecture

```text
Glovo ──POST──► Controller ──► Inbox event ──► Notification ──► POS order
                 token check    (glovo.event)   apply (savepoint)  create / pay / cancel
                                      ▲                                │
                 Retry button ────────┤                                ▼
                 Retry cron ──────────┘                        POS UI and kitchen
POS: Set Food Ready ──► pos.order ──► GlovoClient ──PUT──► Glovo ready_for_pickup
POS: Customer Picked Up ► pos.order (book in savepoint) ──PUT──► Glovo customer_picked_up
```

Controller = `controllers/main.py`; inbox = `glovo.event` (`glovo_base`); apply = `glovo.event._process_notification`;
POS order = `pos.order` through the core `platform.order.entity` hooks. Every notification is stored before it is
applied, and a failure is stored on the event while the webhook still answers 200: Glovo retries only non-2xx
answers, three times, and never cancels an order because of our error.

## 3. File map

| File | Holds |
|---|---|
| `__init__.py` | Install and uninstall hooks (core provider setup and reset) |
| `__manifest__.py` | Depends, data order, POS / preparation display / tour asset bundles |
| `const.py` | `PROVIDER_CODE = 'glovo'` |
| `controllers/__init__.py` | Imports `main` |
| `controllers/main.py` | The three webhook routes, store choice by token, inbox row creation or refusal of another store's row |
| `data/ir_cron_data.xml` | The retry cron (noupdate) |
| `data/platform_order_provider_data.xml` | The Glovo provider record (noupdate) |
| `i18n/ka_GE.po` | Georgian translation of every text |
| `models/__init__.py` | Imports the models |
| `models/glovo_event.py` | `order_id` link, Retry button, retry cron, `_process_notification`, `_apply_notification` with the store check and the replay |
| `models/platform_order_entity.py` | Order and line values from Glovo data, store lookup, total check, "shop closed" handling |
| `models/platform_order_provider.py` | `glovo_token`, provider payment method / pricelist lookups, removal that keeps accounting data |
| `models/pos_order.py` | Cashier lock (`write`, ondelete, sync wrapper), status update from notifications, payment values, Set Food Ready, Customer Picked Up, `_glovo_call` |
| `models/pos_order_line.py` | Lock on line fields of Glovo orders |
| `models/pos_payment.py` | Lock on payments of Glovo orders; deleting a payment is manager-only |
| `models/pos_session.py` | Session close message naming the Glovo drafts |
| `security/ir.access.csv` | Access rows (section 9) |
| `static/src/app/components/order_display/order_display.xml` | Glovo badge on the order display |
| `static/src/app/components/order_tabs/order_tabs.js` | Opening a Glovo floating order goes to its order list entry |
| `static/src/app/models/pos_order.js` | `isGlovoOrder`, `canMarkCustomerPickedUp` getters |
| `static/src/app/screens/ticket_screen/ticket_screen.js` | Refund of a Glovo order: managers only; Customer Picked Up click |
| `static/src/app/screens/ticket_screen/ticket_screen.xml` | Pickup code, courier, CASH / DELAYED line on the order list; Customer Picked Up button |
| `static/src/app/services/pos_store.js` | Blocks the product and payment screens for Glovo orders; drops unsynced local changes |
| `static/src/pos_preparation_display_app/components/order/order.js` | **Done** on the preparation display runs Set Food Ready |
| `static/tests/preparation_display/glovo_prep_display_tour.js` | Tour: Done calls Glovo |
| `static/tests/tours/glovo_customer_pickup_tour.js` | Tour: Customer Picked Up shows only on a pickup order, and the click books it |
| `static/tests/tours/glovo_cancel_tour.js` | Tour: deleting drafts removes a normal order and keeps the Glovo order |
| `static/tests/tours/glovo_lock_tour.js` | Tour: a Glovo order from the webhook cannot be opened for editing or payment |
| `static/tests/tours/glovo_payment_method_tour.js` | Tour: CASH / DELAYED shown on the order list |
| `static/tests/tours/glovo_resolve_form_tour.js` | Tour: the resolve wizard form |
| `static/tests/tours/glovo_sync_batch_tour.js` | Tour: a sync batch with a Glovo order, and Refund on a paid Glovo order |
| `tests/__init__.py` | Test imports |
| `tests/common.py` | Shared fixtures (provider, stores of two companies, products, taxes, branch POS) and the payload and webhook helpers; not imported by `tests/__init__.py`, as in core |
| `tests/test_glovo_cancel_tour.py` | Runs the cancel tour |
| `tests/test_glovo_customer_pickup.py` | Customer Picked Up: Glovo accepts (DELAYED, CASH), Glovo refuses, courier and paid orders refused, the POS tour |
| `tests/test_glovo_fixes.py` | Wizard access, cancel bypass, CASH booking, replay, retry, total recompute, locks, concurrency, cron |
| `tests/test_glovo_food_ready.py` | Set Food Ready: success, timeouts, Glovo errors, retry after ready |
| `tests/test_glovo_lock.py` | Cashier lock through RPC and POS sync, session close, wizard |
| `tests/test_glovo_resolve_form.py` | Runs the resolve form tour |
| `tests/test_glovo_retry_payment.py` | Retry of failed events, payment method, event row lock |
| `tests/test_glovo_scenarios.py` | End-to-end flows through the three routes with Glovo mocked, cross-company and cross-store cases of every entry point |
| `tests/test_glovo_setup_and_cleanup.py` | Install / uninstall / reinstall keeps one journal, method and pricelist; retention |
| `tests/test_glovo_webhook.py` | Webhook answers, disabled provider |
| `views/glovo_event_views.xml` | Retry button on the event list and form; POS Order on the form |
| `views/platform_order_provider_views.xml` | Token field on the provider form |
| `views/pos_platform_order_glovo_menus.xml` | **Glovo Events** menu under Platform Orders |
| `wizard/__init__.py` | Imports the wizard |
| `wizard/pos_glovo_order_resolve.py` | Mark picked up / mark cancelled through the notification path |
| `wizard/pos_glovo_order_resolve_views.xml` | Wizard form and the two actions bound to `pos.order` |

## 4. Webhook to POS order

1. `GlovoController._handle_notification`: parses the JSON body (`order_id`, `store_id` must be strings, else 400),
   finds every store with that external id (`platform.order.entity._find_store_from_data`, sudo) and keeps those whose
   provider `glovo_token` equals the `Authorization` header (`consteq`). Unknown store and wrong token both answer
   401. Two companies may hold the same store id with different tokens; the same token in two companies logs an
   error and takes the store of a non-disabled provider (never 401: the sender owns both records).
2. `_get_or_create_event`: returns the existing `glovo.event` for (order id, event type), or creates it in a
   savepoint. A `UniqueViolation` means a concurrent request inserted it: that request processes it, this one answers
   200. A processed event is answered 200 without work. An existing row of another company or store id is not
   reused: warning log, 200, nothing applied.
3. `glovo.event._process_notification`: `try_lock_for_update` (a locked event is left to its transaction); returns if
   the event is already processed; marks it failed when the provider is disabled; otherwise applies it in a savepoint.
   Concurrency errors (`PG_CONCURRENCY_EXCEPTIONS_TO_RETRY`) are re-raised so `odoo/http/retrying.py` re-runs the
   request; any other exception is stored on the event.
4. `_apply_notification`:
   - any type: an order found for the Glovo order id whose `platform_order_store_id` is not the authenticated store
     fails the event ("belongs to another store"); nothing is changed;
   - dispatched: `platform.order.entity._create_order_from_data` (core), then the replay: pending picked-up and
     cancelled events of the same order, company and store id, `order='id'`, each through `_process_notification`;
   - picked up / cancelled: `pos.order._find_order_from_data`, then `_update_order_status_from_data`.
5. After the savepoint, processed or failed: `order_id` = the order of this Glovo id **in this store**. No
   `check_company` on it: the order's company is the POS's, which may be a branch of the event's company.

## 5. Order values (dispatched)

Core `_create_order_from_data` calls our hooks on `platform.order.entity`:

1. `_prepare_order_values_from_data`: name from `order_code`, `platform_order_ref` = Glovo `order_id`, status
   `accepted` (Glovo orders need no accept call), pickup code, courier name, `glovo_payment_method`, allergy /
   special requirements / cutlery note, order type `pickup` when `is_picked_up_by_customer`.
2. `_convert_to_order_values`: adds the courier name and payment method to the core values.
3. `_find_or_create_partners_from_data`: no partner (Glovo sends anonymised initials).
4. `_prepare_order_lines_values_from_data`: one `product.product` search for all `default_code`s; line total =
   quantity × (`price` + attribute prices × attribute quantity + combo sub-products) − `discount`, in cents, tax
   included (`_glovo_unit_price_cents`); taxes split with `force_price_include` as core GoFood does. Unknown product →
   `ValidationError`, the event fails.
5. `_create_order_from_data` (override, after `super()`): compares `amount_total` with
   `partner_discounted_products_total / 100` and writes the difference on the dispatched event's `error`.
6. No open session: core calls `_cancel_order_from_data`, which marks the dispatched event failed ("No open POS
   session.") instead of refusing at Glovo (Glovo has no refuse API).

## 6. Status updates and payment

`pos.order._update_order_status_from_data`:
- `cancel_reason` in the body (cancelled notification, or the wizard): core `_set_cancelled`.
- picked up on a cancelled order, or on an order that already has payments: `UserError`, the event fails.
- otherwise core `_set_delivered`, which writes `_get_payment_method_values()`.

`_get_payment_method_values` (override): runs `_compute_prices()` first, so the payment is the total of the locked
lines and not a stored `amount_total`; then `super()` (store payment method, state paid). `CASH` replaces the
payment with the Point of Sale's cash method (`pos.config._get_cash_payment_method`), and raises `UserError` when there
is none; two cash methods raise core's own error.

## 7. Set Food Ready

POS button or preparation display **Done** → core `platform_order_status_update_from_ui('food_ready')` →
`_food_ready_handler` (an order already ready answers success, so **Done** may repeat it) →
`_send_food_ready_request`: `GlovoClient(base_url, token).ready_for_pickup(order ref, store external id)`, stage URL
when the provider state is `test`. `GlovoClient._request` retries 429 and 5xx (not 503) with backoff within 15
seconds; errors become one-sentence `UserError`s (token refused / Glovo not responding / refused), built in
`_glovo_call`, which both actions use.

**Customer Picked Up** (POS button on draft Glovo orders of type `pickup`) → `platform_order_status_update_from_ui(
'customer_picked_up')` → our `_order_status_update_handler`: refuses other orders; in a savepoint runs core
`_set_delivered` as superuser (payment as for a courier pickup, CASH included), `cr.flush()`, then Glovo's
`customer_picked_up` **last**. A refusal rolls the payment back; core's wrapper turns the `UserError` into
`{'success': False}` without a rollback of its own, so the savepoint is what keeps the books clean.

## 8. Retry

- **Button** `action_retry`: POS managers only (`AccessError`), all selected events lockable (else "being processed"),
  none processed; then `_retry_notifications`, in id order.
- **Cron** `_cron_retry_failed_events`: stores with an enabled or test provider whose POS has an open session
  (`current_session_id` filtered in Python: its search only supports `in`), failed events of those stores created in
  the last `pos_platform_order_glovo.event_retry_hours` hours (default 24), id order; `_commit_progress` per event.
- `_retry_notifications`: reloads the stored payload, takes the store with that id **in the event's company** (a
  broken payload or no such store marks the event failed), then `_process_notification`.
- The cron filters (`store_external_id`, `company_id`) pairs of the stores with an open session, not a cross product.

## 9. Guards and invariants

| Guard | Where | Blocks |
|---|---|---|
| Status, state cancel, state paid | `pos.order.write` (non-superuser) | Any user change of `platform_order_status`, cancel, mark paid |
| Customer, fiscal position | `pos.order.write` | Changes on Glovo orders (superuser paths are exempt in `_check_glovo_order_unchanged`) |
| Delete | `_unlink_except_glovo_not_cancelled` | Deleting a Glovo order that Glovo did not cancel |
| Lines | `pos.order.line` create / write / ondelete | `order_id`, `product_id`, `qty`, `price_unit`, `discount`, `tax_ids`, `extra_tax_data` |
| Payments | `pos.payment` create / write / ondelete | Payments by users; deleting one is POS-manager only (`_check_glovo_manager_only`) |
| POS sync | `_process_order`, `process_saved_payments` → `_sync_keeping_glovo_server_version` | A locked change in a sync batch: the server version is kept (`SERVER_ONLY_SYNC_KEYS` dropped) so other orders still sync |
| Reject | `_reject_order_handler` | Glovo has no refuse API |
| Store binding | controller token match, `_get_or_create_event`, `_retry_notifications`, `_apply_notification` | A notification of one store paying or cancelling another store's order, across companies too |
| Session close | core draft check + `pos.session.close_session_from_ui` | Closing with Glovo drafts; the message names them |
| Token | `_check_glovo_token_ascii` | A token that could never match a header |

Invariant other code relies on: every legitimate change of a Glovo order runs as superuser (webhook, cron, wizard,
core `_set_*` called from them). A new user-facing action on Glovo orders must go through the same path.

## 10. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `glovo.event` | POS manager | read | (`glovo_base` adds system crud and the company restriction) |
| `pos.glovo.order.resolve` | POS manager | crud | |
| `pos.glovo.order.resolve` | restriction (all) | crud | `[('create_uid', '=', user.id)]` |

`glovo_token`: `groups='point_of_sale.group_pos_manager'`, `copy=False` (core copies providers to new companies).

| `sudo()` | Why it is safe |
|---|---|
| Controller store lookup and inbox row | Public route; the token is checked right after the lookup, before anything is applied |
| `action_retry` | POS-manager check first; managers only read events |
| `_retry_notifications` store lookup, `_apply_notification` order lookup | Run on events already authorised (webhook token, manager, cron) |
| Cron searches | One run serves every company |
| `_send_food_ready_request` provider | The token is manager-only; the cashier only triggers the call |
| `_is_glovo_pos_manager` employee and configs | Reads `pos_hr` manager roles |
| Wizard orders | `check_access('write')` on the selected orders first (company scope); the access rows make the wizard manager-only |

## 11. Integration

- `glovo_base`: `glovo.event` (fields, `UNIQUE(glovo_order_id, event_type)`, retention autovacuum that deletes events
  of any state past `glovo_base.event_retention_days`) and `GlovoClient` / `const`. Renaming an event field or state breaks the controller, Retry and the cron.
- Core `pos_platform_order`: our overrides call `super()` for other providers; Wolt (`pos_platform_order_wolt`) uses
  the same hooks, so each override must keep its `provider_code` branch.
- No other module depends on this one.

## 12. Tests

```bash
odoo-bin -c <conf> -d <test db> -u glovo_base,pos_platform_order_glovo --test-tags /glovo_base,/pos_platform_order_glovo --stop-after-init
```

Tours need Chrome; use free `--http-port` / `--gevent-port` values when another Odoo runs. Tests that call the cron
patch `ir.cron._commit_progress` (a test cursor refuses commits). `test_glovo_pos_hr_manager_check` is skipped without
`pos_hr`. `TestGlovoEventLock` commits one event row on a separate cursor and deletes it.

## 13. Extending safely

- Keep every change of a Glovo order on a superuser path; never loosen `write` for one button.
- Keep the webhook answering 200 for our own errors; only token and payload errors are 4xx.
- Add a new locked field to `LOCKED_FIELDS` or the `write` lock, and to `SERVER_ONLY_SYNC_KEYS` when the POS client
  sends it on sync, or a sync batch fails.
- Never call Glovo from the webhook path: it is retried on serialization errors.
- New user texts need their `i18n/ka_GE.po` entry.

## 14. Known limitations

- One token field for stage and production: Glovo gives one token per environment, so switching the provider state
  needs the matching token.
- `UNIQUE(glovo_order_id, event_type)` has no company: a holder of another company's token who posts a real order id
  first blocks that order's event in the right company (warning log, 200). Normal Glovo traffic cannot do it.
- An order whose store was deleted and created again has no store: its notifications fail the store check; resolve
  it with the wizard.
- `currency` and the cancel `payment_strategy` are not read.
- `current_cashier_id` (sent by the POS client) decides the `pos_hr` manager check.
- An event that cannot heal is retried every 5 minutes with a logged traceback until the retry window ends.
- Menu sync, `delivered` and `out_for_delivery` are not implemented.
- Whether Glovo also sends a picked-up notification after `customer_picked_up` is not known; if it does, that event
  fails "Order already paid in Odoo" and is retried until the window ends.
- Preparation display bulk done / clear all bypass Set Food Ready (core `pos_enterprise`).
