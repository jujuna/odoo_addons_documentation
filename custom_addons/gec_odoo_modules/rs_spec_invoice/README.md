# RS Petroleum Invoice (`rs_spec_invoice`)

Files the rs.ge petroleum invoice (ნსაფ) straight from the customer invoice. For oil products the ნსაფ is the VAT
document, so a fuel invoice goes to rs.ge as a ნსაფ instead of an ordinary e-invoice.

**Who this is for:** accountants who invoice fuel, and the admin who sets up rs.ge.
Developers: see [README_DEV.md](README_DEV.md).

## 1. What it does

| Feature | What it gives you |
|---|---|
| Petroleum products from rs.ge | One click creates an Odoo product for each oil product on rs.ge's list (diesel, petrol grades, fuel oil, bitumen...) |
| Fuel products | Every invoice line with one of these products is treated as fuel |
| Petroleum invoice on the invoice | A posted fuel invoice shows a **Petroleum Invoice** section on its **RS E-Invoice** tab: route, transport, driver, documents |
| Save and send to rs.ge | **Save on rs.ge** files a draft ნსაფ, **Send to buyer** sends it for the buyer's confirmation |
| Status from rs.ge | **Check Status** reads the ნსაფ status (sent, confirmed, cancelled...) into the invoice |
| Safe books | While a ნსაფ is live on rs.ge, Odoo refuses to reset or cancel the invoice the e-invoice way |
| Corrections | A sent ნსაფ is corrected from a credit note with a corrected copy of the invoice (section 8b) |
| No waybill for fuel | A delivery or other transfer of fuel products only gets no rs.ge waybill: the ნსაფ replaces it |
| Buying fuel | Received ნსაფ are imported from rs.ge as vendor bills and accepted or rejected from Odoo (section 7b) |
| VAT declaration | Fuel invoices stay out of annexes ბ I and ბ II (ordinary invoices); tabs 13 (issued) and 14 (received) are filled by **Generate** |

## 2. Quick facts

| Item | Value |
|---|---|
| Menus | **Accounting > Customers > Petroleum Invoices**; **Accounting > Vendors > Received Petroleum Invoices**; **Accounting > Configuration > Sync Petroleum Products**; **Accounting > Configuration > RS Petroleum Sites** |
| Added to existing screens | Product form: **RS Petroleum ID** (read-only, on petroleum products); product search: filter **Petroleum (rs.ge)**. Customer invoice, **RS E-Invoice** tab: the **Petroleum Invoice** section and its buttons |
| Who can use it | Invoicing users (Accounting / Invoicing); **Sync Petroleum Products** needs product-manager rights; the **Car Plate** field needs Fleet rights |
| Needs | The rs.ge e-invoice modules and an rs.ge login per user and company (the same login as for e-invoices) |
| Covers today | Retail and wholesale sales from customer invoices; fuel bought with a ნსაფ from a supplier |

## 3. How it works

```text
 Fuel product ─► Customer invoice ─► Confirm ─► marked as petroleum invoice
                                                  │
                     fill route, vehicle, driver ◄┘
                                                  │
                         Save on rs.ge ──► draft ნსაფ on rs.ge (Draft)
                                                  │
                         Send to buyer ──► rs.ge gives series and number (Sent)
                                                  │
                    buyer confirms on rs.ge ──► Check Status ──► Confirmed
```

When you confirm a customer invoice whose product is a fuel product, Odoo marks it as a petroleum invoice. The
ordinary **Send to RS** buttons disappear and the **Petroleum Invoice** section appears on the **RS E-Invoice** tab.
You add the route and transport, save it on rs.ge, and send it to the buyer.

## 4. Set it up (once)

1. **Accounting > Configuration > Sync Petroleum Products**. Odoo creates one product per rs.ge petroleum product
   (rs.ge's name, the customs code as **Barcode**, rs.ge's 4-digit product code as **RS Product Code**) and loads your
   company's sites and the customs sites; the product list opens. The unit is **kg** for the three bitumen / fuel oil
   products (recognised by their customs code) and **Litre** for the rest. Several products share a name; the
   **Barcode** tells them apart, for example 27101931000 for diesel. Running it again updates names and codes, never
   your prices, taxes or accounts; a product rs.ge drops is archived. It changes the unit of an existing product only
   when no document uses the product yet; otherwise the unit stays and the product's chatter gets a note.
2. Open the products you sell (**Sales > Products**, filter **Petroleum (rs.ge)**) and set price and taxes (and the
   unit, if you sell one in another unit). **Excise Product** stays as it is.
3. For road transport, register your drivers (contact with **Is RS Driver**) and vehicles (**Fleet**), so they can be
   picked on the invoice. Without them you type the driver and car number by hand.

LPG and natural gas are not on rs.ge's petroleum list, so no product is created for them; they stay on the ordinary e-invoice. Only the synced products count as fuel: a product you create yourself is never a petroleum product.

## 5. The fuel invoice

| Rule | Why |
|---|---|
| Only fuel on the invoice | One invoice is either a ნსაფ or an ordinary e-invoice, never both |
| One fuel line per invoice | One ნსაფ holds one product and one vehicle: two products or two trucks are two invoices |
| A down-payment deduction line may stay | It is not another product |

The rules are checked when you click **Confirm**, also from the list (**Confirm Entries**).

### The Petroleum Invoice section

| Field | What to enter |
|---|---|
| **Petroleum Invoice Type** | **Retail** or **Wholesale** |
| **Petroleum Unit**, **Quantity (litres)**, **Quantity (kg)** | Filled from the invoice line (litres or kilograms, whichever the line's unit converts to); type the other quantity |
| **Start Site** | Your site the fuel leaves from (7-digit rs.ge code) |
| **End Site** | The buyer's site; leave empty for retail (sent as "-") |
| **Transport Type** | **Road**, **Railway**, **Pipeline**, **Re-registration (no transport)**, **Coupons**, **Plastic card**, **Other** |
| **Car Plate**, **Car Brand**, **Car Number** | Road only. Picking the car fills brand, number and its usual driver |
| **Driver (Partner)**, **Driver TIN**, **Driver Name**, **Driver is Foreigner** | Road only. Picking the driver fills the rest |
| **Carrier Name**, **Carrier TIN** | The carrier, when someone else transports |
| **Purchase Invoice Number / Date** | Box 11: the petroleum invoice you bought this fuel with |
| **Other Purchase Document** and its number | Box 11 when there is no purchase ნსაფ: extraction, production, auction... |
| **Customs Document Number / Date** | Box 10, for imported fuel |

Amounts and VAT come from the invoice line; you do not type them. The section can be edited while the ნსაფ is a
draft on rs.ge, and is read-only once sent.

**Load sites** reloads your sites and the buyer's sites from rs.ge, for example after the buyer registers a new
depot.

## 6. Example

Invoice: 1,000 litres of diesel at 3.00, VAT 18%.

| Sent to rs.ge | Value |
|---|---|
| Quantity | 1,000 litres (kg as you typed it) |
| Value incl. VAT | 3,540.00 |
| VAT | 540.00 (1,000 × 3.00 × 18%) |
| VAT kind | standard |
| Type | Wholesale |

Amounts go to rs.ge in GEL; an invoice in another currency is converted at its date's rate.

## 7. Step by step: a fuel sale

1. Create the customer invoice with the one fuel line and click **Confirm** → the **RS E-Invoice** tab shows
   "Filed on rs.ge as a petroleum invoice (ნსაფ), not as an e-invoice."
2. Fill the **Petroleum Invoice** section (type, sites, transport, driver, purchase document).
3. Click **Save on rs.ge** → the status card shows the rs.ge ID and **Draft**. Check the draft on the rs.ge portal
   if you like; edit and save again as often as needed.
4. Click **Send to buyer** → status **Sent (Pending)**, with the rs.ge series and number.
5. When the buyer has confirmed on rs.ge, click **Check Status** → **Confirmed**.

**Send to buyer** also saves first, so you can skip step 3. **Delete on rs.ge** removes a draft from rs.ge; the
invoice can then be saved again as a new ნსაფ.

## 7b. Buying fuel (received ნსაფ)

1. **Accounting > Vendors > Received Petroleum Invoices**, set the dates, click **Search rs.ge**.
2. Tick the ნსაფ you want and click **Import Selected**: Odoo creates a draft vendor bill for each and pulls its
   data from rs.ge. The bill's product is found by its rs.ge petroleum ID, so run **Sync Petroleum Products** first.
3. On the bill click **Accept on rs.ge** or **Reject on rs.ge**, as for ordinary supplier e-invoices.

Example (rs.ge test environment, 2026-11-07): a received ნსაფ at status 1 is imported; **Accept on rs.ge** moves it to
status 2 and posts the bill; **Reject on rs.ge** gives rs.ge status 0 and cancels the bill. An accepted bill is a
row of tab 14 of the VAT declaration.

## 8. Statuses and what you may do

| Status on rs.ge | Reset to Draft / Cancel the invoice | Credit Note |
|---|---|---|
| none (not saved yet) | allowed | allowed |
| Draft | allowed | only **Reverse** with **Only correct Odoo, not rs.ge**, or delete the draft on rs.ge first |
| Sent (Pending), Cancelled (Sent), Corrected (Original) | refused | only **Reverse** with **Only correct Odoo, not rs.ge** |
| Confirmed | refused | **Replace RS invoice with a corrected invoice** (section 8b), or **Reverse** with **Only correct Odoo, not rs.ge** |
| New Correction | allowed: this is how a saved, unsent correction is edited before **Send to buyer** | only **Reverse** with **Only correct Odoo, not rs.ge** |
| Correction Sent | refused | only **Reverse** with **Only correct Odoo, not rs.ge** |
| Correction Confirmed | refused | **Replace RS invoice with a corrected invoice** (section 8b; not after type 11), or **Reverse** with **Only correct Odoo, not rs.ge** |
| Cancellation Confirmed | Odoo cancels the invoice itself on **Check Status** | — |

Odoo reads the current status from rs.ge before it decides, so a buyer's confirmation a minute ago counts.

## 8b. Correcting a sent petroleum invoice

1. On the sent invoice click **Add Credit Note**. Keep **RS Treatment** on **Replace RS invoice with a corrected
   invoice**, pick the **Petroleum Correction Type**, click **Reverse and Create Invoice**.
2. Odoo opens a draft copy with the route, transport and documents of the original, and with its litres and kg.
   Edit the goods line only: the price, the VAT, or the quantity for type 14. For type 14 edit the line quantity and
   retype the other unit's quantity. Click **Confirm**.
3. Click **Save on rs.ge**: rs.ge creates the correction (status **New Correction**) and Odoo saves the goods line on
   it. **Send to buyer** does the same and then sends it (**Correction Sent**).
4. The buyer confirms on rs.ge. Click **Check Status** on either invoice: the correction shows **Correction
   Confirmed** and Odoo cancels the original. If the original is in an earlier month (or a lock date covers it), Odoo
   reverses it with a credit note dated today instead. If payments or credit notes are applied to the original, Odoo
   leaves it and creates a To-Do: unreconcile first, then click **Check Status** again.

| Type | Meaning | When |
|---|---|---|
| 11 | Taxable operation cancelled | Before transport starts. The copy gets quantity 0, as rs.ge zeroes it; the invoice cannot be corrected again |
| 12 | Taxable operation type changed | Before transport starts |
| 13 | Agreed price changed | Before transport starts |
| 14 | Goods returned | Before transport starts |
| 21 | Taxable operation type changed | Presumably after transport starts (rs.ge does not say so directly) |
| 22 | Agreed price changed | Presumably after transport starts (rs.ge does not say so directly) |

- A correction at **New Correction** can be reset to draft, edited and confirmed again before **Send to buyer**.
- A **Correction Confirmed** invoice can be corrected again with the same credit-note treatment, except after type 11.
- The buyer rejects the correction: **Check Status** returns the copy to draft; edit it, **Confirm** and send again.
- **Delete on rs.ge** removes a correction that is still **New Correction**; the original returns to its earlier
  status on the next **Check Status**.

## 9. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Invoice petroleum products on their own invoice | The invoice mixes fuel and other products | Put the other products on a second invoice |
| One petroleum product per invoice | Two fuel lines | One invoice per product and per vehicle |
| ... is filed on rs.ge as a petroleum invoice: keep its petroleum product line | You removed the fuel line from a filed ნსაფ | Put the line back, or delete the ნსაფ on rs.ge first |
| Cannot reset to draft — it is live on rs.ge / Cannot cancel — it is live on rs.ge | The ნსაფ is sent or confirmed on rs.ge | Leave the invoice as it is; to change it, correct it (section 8b) |
| Petroleum invoice ... is filed on rs.ge: correct it with 'Replace RS invoice with a corrected invoice' | The chosen credit-note treatment would try the e-invoice correction | Use **Replace RS invoice with a corrected invoice**, or **Reverse** with **Only correct Odoo, not rs.ge** for a books-only credit |
| rs.ge did not create the correction of petroleum invoice ... | rs.ge refused the correction, for example one is already open on rs.ge | Finish or delete the open correction on rs.ge, then **Save on rs.ge** again |
| rs.ge refused the petroleum invoice; check sites, transport and document numbers | rs.ge gives no reason | Check the site codes, transport type, car number and purchase document |
| rs.ge refused the goods line of the petroleum invoice | rs.ge refused the quantity, amount or product | Check litres, kg and that the product is a synced petroleum product |
| rs.ge rejected your credentials | Wrong or missing rs.ge login for this company | Fix it in your user preferences and click **Test RS Credentials** |
| rs.ge rejected the request: | rs.ge answered with an error | Read the error text; fix and retry |
| rs.ge did not accept the status change / did not delete the petroleum invoice | rs.ge refused the send or delete | Click **Check Status**, then retry |
| The invoice is busy: click Save on rs.ge again | Someone else was working on the invoice at that moment | Click **Save on rs.ge** again |
| rs.ge did not answer the last save of ... | The connection broke while rs.ge was saving, so rs.ge may already hold the ნსაფ | Look for it among your drafts on the rs.ge portal and link it with **Resolve Orphan**; if it is not there, click **Dismiss Pending** (possible 5 minutes after the save) and save again |
| rs.ge has no petroleum invoice with ID ... | rs.ge does not know the ID stored on the invoice | Check the ID on the rs.ge portal |

## 10. Rules to remember

- A fuel invoice is never sent as an ordinary e-invoice: the **Send to RS** buttons are hidden on it.
- An invoice already sent as an ordinary e-invoice stays one, even if its product later becomes a fuel product.
- A transfer that holds only fuel products never gets an rs.ge waybill, even on an operation type with
  **Create Waybill**; it validates without one. A transfer mixing fuel and other products still gets a waybill.
- A down payment on a fuel sale goes to rs.ge as an ordinary advance e-invoice; linking it to the ნსაფ is not
  available yet, so do not file a fuel sale that had a down payment from Odoo.
- A ნსაფ can be changed on rs.ge only while it is a draft; once sent, the invoice is locked and changes through a
  correction (section 8b).
- Purchase, sales and transfer lines have optional **Alt. Quantity** and **Alt. Unit** columns (hidden by default; show
  them from the column picker) for the second unit of fuel, kg beside litres: you type them per line, Odoo never
  converts them.

## 11. Common questions

**Why does a fuel invoice not appear in annex ბ I of the VAT declaration?** It is filed as a ნსაფ, which belongs
in the petroleum tab 13 (issued) or tab 14 (received) of the declaration. **Generate** on the VAT declaration fills both.

**Can I sell fuel at the pump through the Point of Sale?** POS invoices are not marked as petroleum invoices.

## 12. Known limitations

- Not available yet: cancelling a ნსაფ on rs.ge, starting transport, internal moves,
  imports and exports (types 3-5), automatic status updates.
- A correction never changes the header (sites, transport, buyer, date): only the goods line.
- Corrections made on the rs.ge portal are not seen by Odoo.
- Buyer rejection handling assumes rs.ge returns the correction to status 4; not verified on live rs.ge.
- **Check Status** on the original also refreshes its correction; a correction missing on rs.ge is logged, not
  raised.
- If rs.ge's answer is lost while **Save on rs.ge** creates the ნსაფ or its correction, **Save on rs.ge** and
  **Send to buyer** wait until you link the rs.ge document with **Resolve Orphan** or, if rs.ge has none, click
  **Dismiss Pending**.
- Nothing of the correction flow has been tested against live rs.ge yet.
- In a foreign currency a price correction also carries the exchange-rate change.
- Tabs 13 and 14 of the VAT declaration are filled by **Generate**. The month rule (tab 13 as annex ბ I, tab 14 as
  annex ბ II) is not yet confirmed by the accountant.
- Fuel sold through POS or posted automatically (not through **Confirm**) is not marked.

## 13. Glossary

| Word | Meaning |
|---|---|
| ნსაფ | Petroleum special tax invoice: rs.ge's VAT invoice for the oil products on its list |
| Site | A registered depot, station or tank with a 7-digit rs.ge code |
| Fuel product | A product created by **Sync Petroleum Products** (it has an **RS Petroleum ID**) |
