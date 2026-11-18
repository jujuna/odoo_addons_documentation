# Fix Test Plan — `rs_base` + `rs_invoice`

Self-test guide for the four fixes. Do them in order (easy → hard). All on the test DB / rs.ge test taxpayer.

**Labels used below:** *Create RS Invoice from Waybills* (bridge wizard), *Send to RS*, *Update on RS*, *Check Status*, *Correct & Reissue* / *Cancel & Reissue*, the **RS Waybills** tab on the invoice, and the waybill field **Locked by invoice**.

---

## 0. Deploy first

| Change | Action |
|---|---|
| XML view (native button) | upgrade `rs_base`: `-u rs_base` |
| Python (`rs_einvoice` FX) | restart Odoo |

`-u rs_base` reloads its Python too, so: **upgrade `rs_base` + restart Odoo**, then hard-refresh the browser.

---

## 1. Native invoice button is hidden on waybill SOs

**Why:** stops a second, unlinked rs.ge invoice for the same goods (double VAT). The bridge must be the only invoicing path.
**When:** any Sale Order that has a waybill.

**Setup:** one confirmed SO (state *Sales*) that has a waybill linked (the `waybill_id` field is set).

**Steps:**
1. Open the SO form.
2. Look at the top buttons.

**Pass:** only **Create RS Invoice** shows. The standard **Create Invoice** is gone.
**Fail:** both buttons show (→ `-u rs_base` didn't run, or hard-refresh needed).

**Also check (no regression):** open a normal SO with **no** waybill → the standard **Create Invoice** is still there.

---

## 2. Matcher no longer grabs an unrelated Sale Order

**Why:** before, a standalone waybill invoice silently bumped the oldest open SO of that customer+product — corrupting an unrelated order. Now it leaves the line *unmatched* instead of guessing.
**When:** invoicing a waybill that has **no** clear Sale Order.

**Setup:**
1. Customer **A**, product **P**.
2. **SO-OLD:** for customer A, one line of product P — confirm it, deliver it, **do not invoice it** (so it sits "to invoice").
3. A separate waybill **WB** for customer A + product P, **not linked** to SO-OLD (a standalone rs.ge waybill, `sales_order_id` empty).

**Steps:**
1. From the **waybill list**, select WB → **Create RS Invoice from Waybills** (opens in standalone mode).
2. Look at the wizard line for product P.

**Pass:** the line shows **"Unmatched — invoice line will not update qty_invoiced"** and **Sale Order** is empty.
**Fail:** the line silently shows SO-OLD as its Sale Order.

**Verify after creating the invoice:** open **SO-OLD** → its *Invoiced* quantity is **unchanged** (still 0 / to invoice).

**Sanity (no regression):** repeat with a waybill that **is** linked to its own SO → that line **does** match its own SO line (matching still works when there's a real anchor).

---

## 3. Reissue carries the waybill links to the new invoice (C1)

**Why:** rs.ge moves the waybill to the new invoice on a correction, but Odoo used to build the replacement with **no** links → the waybill showed unlocked and traceability was lost. Now Odoo re-creates the links on the replacement when the original is cancelled.
**When:** Correct & Reissue (or Cancel & Reissue) of a waybill-linked invoice, done **through Odoo**.

**Setup:** a waybill-linked invoice that is live on rs.ge — created via the bridge, **Send to RS**, buyer **accepted** (rs.ge status 2). Confirm its **RS Waybills** tab shows the waybill(s), and the waybill's **Locked by invoice** = this invoice.

**Steps:**
1. On that invoice, click **Correct & Reissue**, pick a correction reason.
2. A replacement **draft** opens. *(It has no waybill links yet — expected; links carry only when the original is cancelled.)*
3. **Post** the replacement, **Send to RS**.
4. As the buyer, **accept the correction** on rs.ge (status 8). Back in Odoo click **Check Status** on the original.

**Pass:** after the original auto-cancels —
- the **replacement** invoice's **RS Waybills** tab now lists the waybill(s); and
- the waybill's **Locked by invoice** now points to the **replacement**.

**Fail:** the replacement has 0 waybills and the waybill shows unlocked.

**Verify (optional, shell):**
```python
orig = env['account.move'].browse(<original_id>)
rep  = orig.rs_einv_replaced_by_id
print('replacement links:', rep.rs_einv_waybill_link_ids.mapped('waybill_id').ids)
print('waybill locked by:', rep.rs_einv_waybill_link_ids.waybill_id.mapped('locked_by_move_id').mapped('name'))
```

---

## 4. Foreign-currency advance settled at the right rate (FX / NEW-5)

**Why:** a USD advance was settled on the final using the **final month's** exchange rate, not the rate the advance VAT was actually filed at → wrong GEL VAT on rs.ge. Now it uses the **advance's own** filed rate (= rs.ge's `full_drg`). GEL deals are unaffected.
**When:** a non-GEL (e.g. USD) sale with a down payment, advance and final in **different months** whose FX rates differ.

**Setup:**
1. Confirm USD has **different daily rates** in month M and M+1 (Accounting → Currencies → USD → Rates). If not, add two rates that differ.
2. A **USD** Sale Order for a customer.
3. Create a **down-payment (advance) invoice** dated **month M**, post, **Send to RS**, buyer **accepts** it.
4. **Next month (M+1):** create the **final** invoice from the SO (it carries the negative down-payment line). Advance Settlement should auto-pick **Native**.

**Steps:**
1. On the final, **Send to RS**, then **Send to buyer** (this runs the advance attach).

**Pass:** the advance VAT settled = the **advance's filed GEL** (month-M rate), not the final-month value.
**Fail:** the settled VAT equals the offset converted at the final's month rate (the old, wrong number).

**Verify (easiest — shell, no rs.ge write):**
```python
final = env['account.move'].browse(<final_id>)
for item in final._rs_expected_advance_settlements(force=True):
    adv = item['advance_move']
    print('settle GEL:', item['vat_amount'],
          '| advance filed GEL:', final._rs_move_vat_abs_gel(adv))
```
**Pass = the two numbers match** (within a cent). Before the fix, `settle GEL` would differ by the FX delta.

*(Tell me the advance + final ids and I can also read what rs.ge actually stored via SOAP — `drg_amount` should equal `full_drg`.)*

---

## 5. Drift scan (existing 6509-type records)

**Why:** find invoices whose Odoo `rs_einv_id` no longer matches the waybill's live rs.ge `INVOICE_ID` (left by old reissues; fix #3 stops new ones).
**When:** once, after deploying.

**Run:**
```
odoo-bin shell -d gec_modules2 < custom_addons/gec_odoo_modules/rs_base_methods/scripts/detect_invoice_id_drift.py
```
It prints each drifted record (read-only). Reconcile those by hand (e.g. *Resolve Orphan* on the move, or re-link) — share the list with me if you want help deciding per record.

---

## Quick reference

| # | Fix | 1-line pass check |
|---|---|---|
| 1 | Native button hidden | waybill SO shows only *Create RS Invoice* |
| 2 | Matcher | standalone line for an unrelated SO = *Unmatched*, SO-OLD qty unchanged |
| 3 | Reissue links | replacement invoice lists the waybill; waybill locked by replacement |
| 4 | FX advance | `settle GEL` == `advance filed GEL` in the shell check |
| 5 | Drift scan | script prints 0 new drift after fix #3 is in use |
