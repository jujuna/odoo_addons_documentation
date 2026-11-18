# Signify E-Signature (`signify`)

Send a contract, an offer or any PDF or Word file from Odoo to Signify for signing (by email, SMS, a link, a
Georgian ID card or a signature pad), and get the signed file back into Odoo.

**Who this is for:** the people who send documents for signature, and the administrator who registers Odoo as an
application in Signify. Developers: [README_DEV.md](README_DEV.md).

## 1. What it does

| Feature | What you get |
|---|---|
| Send from Odoo | Upload a file, list who signs, approves or gets a copy, and press **Send**; Signify invites them |
| Send from any chatter | **Send with Signify** in the viewer of a PDF attached to a contact, a sale order, an employee... |
| Every signing method | Click to sign, SMS code, Georgian ID card, Georgian company stamp, EU qualified signature, signature pad, remote video ID |
| Status in Odoo | Each recipient shows Waiting, To Act, Done or Rejected; the document shows Sent, Signed, Rejected or Recalled |
| The signed file comes back | The signed PDF lands on the Signify document and on the record it is linked to |
| Our own signature | A recipient line can be our company, signed automatically by Signify with our seal |
| Your own Signify account | Each user connects their own Signify account; a document is sent, followed and recalled with the account of the user who pressed **Send** |
| With the Documents app | Signed files and evidence reports are also filed in the company's Signify folder (created at install, visible to the sender), and **Send with Signify** is pinned on it and can be pinned on other folders (module `signify_documents`: [../../../documentations/signify_documents.md](../../../documentations/signify_documents.md)) |

## 2. Quick facts

| | |
|---|---|
| Menu | **Signify > Documents**, **Signify > Configuration > Signify Accounts** |
| Button added to other screens | **Send with Signify** in the file viewer of a PDF in any chatter, for Signify users |
| Settings | **Settings > General Settings > Integrations > Signify** |
| Who can use it | **Signify: User** sends documents and sees only their own. **Signify: Administrator** sees and edits every document of their companies |
| What you need | A Signify account on the Business Pro or Enterprise plan for every user who sends, and the application's Client ID and Client Secret from Signify |
| Status updates | Every 15 minutes, or at once with **Refresh Status** |
| Recipients | Anyone with an email or a mobile number; they do not need Odoo |

## 3. How it works

```text
  Signify > Documents > New         Send with Signify (PDF in a chatter)
             │                                   │
             └─────────────────┬─────────────────┘
                               ▼
              Draft: file, Linked To, recipients
                               │ Send
                               ▼
              Sent: Signify emails or texts the recipients
                               │ every 15 minutes, or Refresh Status
                               ▼
              Signed: the signed file comes back to Odoo
```

You prepare a draft and press **Send**. From then on Signify runs the signing: it invites the recipients in the
order you chose and collects their signatures. Odoo asks Signify for the status every 15 minutes. When everyone has
signed, the signed file and Signify's evidence report are saved in Odoo. Side paths: **Rejected** (a recipient
refused), **Recalled** (you pressed **Recall**) and **Deleted** (the document was removed in Signify).

## 4. Set it up (once)

1. Ask Signify for the application's **Client ID** and **Client Secret** (one pair for the whole database) and give
   them the **Redirect URL** shown in **Settings > General Settings > Integrations > Signify**. Signify must allow
   that URL, one per Odoo address. Set the system parameter `web.base.url.freeze` so the address does not change.
2. In the same place fill in **Client ID** and **Client Secret**, and **Save**. Below them, **Signify Reminders** is
   set per company: **Reminder Frequency** (Every Hour, Every Day, Every 2 Days, Every Week, Never; default Every Day)
   and **Maximum Reminders** (default 3, at most 10). Signify sends the reminders itself, to signers and approvers
   whose turn has come and who have not acted, the same way as the invitation, email or SMS (not verified on a live
   document); link recipients get none. Example: Every 2 Days, 3 → a document sent on Monday is reminded on
   Wednesday, Friday and Sunday. Only documents sent after a change follow it.
3. Give people access in **Settings > Users**: privilege **Signify**, **User** or **Administrator**. The
   administrator gets **Administrator** at install.
4. Each person opens **Signify > Configuration > Signify Accounts**, presses **Connect Signify Account** and signs
   in to Signify. Odoo is then connected to that person's Signify account, for the company they work in. Switch company
   and repeat to connect for another company.
5. Check the contacts who will sign:
   - email, for email delivery;
   - mobile number in **Phone**, with the country set, for SMS delivery and SMS codes;
   - the 11-digit personal number, for Georgian ID card and remote ID signing: in the **Tax ID** of a private person,
     or in the **Personal Number** of the recipient line (section 8).

Without a connection you can still prepare drafts; **Send** stops with "Connect your Signify account before sending
this document." and the button **Open Signify Accounts**. The
scheduled action **Signify: Sync Document Status** must stay active, or statuses stop updating.

## 5. Recipients: who does what

Each line on the **Recipients** tab is one person (or our company). Drag the lines to set the order.

| Role | What happens |
|---|---|
| Signer | Signs with the method in **Signing Method** |
| Approver | Approves the document (Basic, SMS Code or Remote ID) |
| CC | Receives the signed copy; does nothing else |
| Automatic Signer | Our company: Signify signs automatically, with **Georgian Qualified** or **Company Seal** (**Automatic Signature**) |

**Send Invitation By**, how the recipient is invited:

| Send Invitation By | Invitation |
|---|---|
| Email | Signify sends an email |
| SMS | Signify sends an SMS to the contact's phone |
| Link | Nobody is invited; you open the signing page from Odoo (section 6.4) |

**Signing Method**, how the person signs:

| Signing Method | The signer... |
|---|---|
| Basic | opens the document and clicks to sign |
| SMS Code | confirms with a one-time code sent by SMS |
| Qualified | signs with a qualified signature; choose the kind in **Certificate**: **Georgian ID Card** (needs the 11-digit **Personal Number** of the recipient line), **Georgian Company Stamp** (uses the company's **Tax ID**), **EU Qualified**, **EU Qualified, One-Shot Allowed** |
| Signature Pad | signs by hand on a signature pad attached to the computer (section 6.4) |
| Remote ID | passes a video identification; when the line has a **Personal Number**, Signify checks it matches |

**Signing Order:** **In Order** invites one recipient after another, in line order; **All at Once** invites
everybody together.

**Signature Keyword:** a word printed in the file under the signature line, for example `Director`. Signify places
the signature there. Give one to every Signer and Automatic Signer.

## 6. Step by step

### 6.1 Send a document

1. **Signify > Documents > New**.
2. Upload the **File** (PDF, DOC or DOCX). The name fills in from the file name.
3. **Linked To** (optional): the record this document belongs to, such as a contact or a sale order. Notes and the
   signed copy go there.
4. Choose **Signing Order**, and add the lines on the **Recipients** tab (section 5).
5. **Message** tab (optional): text added to the invitation.
6. Press **Send**. The status bar shows **Sent**, the **Signify ID** appears, and the linked record gets the note
   "Sent for signature with Signify: ...".

### 6.2 Send a PDF straight from a chatter

1. On any record, click the PDF in the chatter to open the viewer.
2. Press **Send with Signify** in the viewer's top bar. A draft opens with the file and **Linked To** filled in, in
   the company of the linked record.
3. Add the recipients and press **Send**.

The button shows only on PDFs: Odoo's viewer does not open Word files, so send those through **Signify > Documents
> New**. A PDF from a Discuss channel or chat, or on a record that no longer exists, gives a draft that is not
linked. A PDF on a record you cannot read is refused with Odoo's access error.

### 6.3 Follow the signatures

The **Status** column on each recipient line:

| Status | Meaning |
|---|---|
| Waiting | Their turn has not come yet |
| To Act | It is their turn |
| Done | They did their part |
| Rejected | They refused; the chatter names them, with their reason when Signify gives one |
| Not Needed | The document was recalled or rejected before their turn |
| Interrupted | The document was recalled or rejected during their turn |

Statuses update every 15 minutes. Press **Refresh Status** to update now.

When everyone has signed, the document shows **Signed** and a **Signed Files** tab appears:
- the signed document, plus any files the signers attached in Signify;
- the **Evidence Report**: Signify's record of who signed, when and how. It can arrive one update later than the
  signed file; if its download fails, the document stays **Signed** and the next update tries again.

The linked record gets a copy of the signed document and the note "Signed with Signify: ..." (nothing when Signify
returns no signed document). The evidence report
and files attached by signers stay on the Signify document.

### 6.4 Sign in the office (link or signature pad)

1. Add the recipient with **Send Invitation By** = **Link** (and **Signing Method** = **Signature Pad** for the pad).
2. After **Send**, press the open icon (**Open Signing Page**) at the end of their line. Signify's signing page opens
   in a new tab.
3. The signer signs there, on the computer with the pad when one is used.

When you choose **Link**, **Signing Method** changes from **Basic** to **SMS Code**: on **Sign**, Signify texts a
one-time code to the contact's **Phone** and the signer types it. Signify's evidence report then shows which phone
confirmed, as Signify advises for link signing. Signature Pad, Qualified and Remote ID are kept as chosen.
**Send** refuses a Signer or Approver on **Link** with **Basic**, because anyone who opens the page would sign as
that recipient.

### 6.5 Recall a document

On a **Sent** document press **Recall** and confirm. The status becomes **Recalled** and the recipients can no
longer sign.

## 7. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Signify is not set up: ... | The Client ID or Client Secret is missing in Settings; **Connect Signify Account** shows it before leaving Odoo | The administrator fills them in (section 4) |
| Connect your Signify account before sending this document. | You pressed **Send** and have no connected account for this company | Press **Open Signify Accounts** in the message, then **Connect Signify Account** (section 4) |
| Connect your Signify account first ... | **Refresh Status**, **Recall** or the signing page on a document that has no Signify account (sent before accounts were connected per user, or from another database) | It cannot be updated from Odoo; check it in the Signify portal |
| The Signify account ... has expired ... | Signify no longer accepts the saved connection of the named user (revoked, expired or password changed) | That user presses **Connect Signify Account** again |
| Signify did not connect: ... | Signify refused the connection (for example you pressed Cancel) | Try again; the text after the colon is Signify's own |
| This Signify connection attempt was not found ... | The connection page was opened too late, in another browser, or at another Odoo address than the one you started from | Press **Back to Signify Accounts** on the page and start again; if it happens again, tell the administrator |
| Documents sent with this account are still in progress in Signify. | You pressed **Disconnect** while documents sent with it are waiting for signatures or the evidence report | Wait until they are signed, or recall them |
| Only a draft document can be sent. | The document was sent already | Use **Duplicate** for a new draft |
| This document is being sent already. | Someone pressed **Send** on it a moment ago | Wait a few seconds and reload |
| Choose SMS Code or another Signing Method for ... | A Signer or Approver has **Send Invitation By** = **Link** and **Signing Method** = **Basic** | Set **SMS Code** (or another method) on that line (section 6.4) |
| Add a mobile number to the Phone of ... | The line uses SMS invitation or **SMS Code**, and the contact has no **Phone** | Fill in the contact's mobile in **Phone**, with the country set |
| Signify did not confirm every recipient. | Signify's answer did not list every recipient line | Nothing was sent. Press **Send** again; if it repeats, tell the administrator |
| Signify did not confirm the share of ... | The connection to Signify failed in the last step of **Send**; the invitations may have gone out | The document stays a draft. Check the Signify portal before pressing **Send** again |
| Only a sent document can be recalled. | The document is not in **Sent** | Nothing to recall |
| Recall a sent document before deleting it. | You tried to delete a **Sent** document | Press **Recall** first |
| A signed document cannot be deleted: it keeps the signed files and the evidence report. | You tried to delete a **Signed** document | Keep it; the signed files and the evidence report live on it |
| Only link recipients have a signing page. | The recipient's **Send Invitation By** is not **Link** | Only **Link** recipients have one (section 6.4) |
| You don't have access to the linked document. | **Linked To** points to a record you cannot open | Choose another record, or ask someone who can open it |
| Only Signify can change the status ... | An import or automation tried to set a status or the signed files | Statuses and signed files come only from Signify |
| Signify did not answer in time. Please try again. | Signify was slow | Try again |
| Signify is unreachable. / The request to Signify failed. | No connection to Signify | Check the internet connection; try later |
| Signify answered with HTTP ... | Signify gave an unexpected answer | Tell the administrator |
| Any other text, such as "Uploaded file is corrupted" | Signify itself refused, and wrote why (in Georgian for Georgian users) | Do what the message says |

## 8. Rules to remember

- **Only drafts can be changed.** After **Send**, nothing on the document can be edited in Odoo: recall it and send
  a new one.
- **You see your own documents.** A Signify user sees only the documents they created; administrators see all.
- **The personal number.** Georgian ID card and remote ID signing need the person's own 11-digit number. The
  **Personal Number** of the recipient line fills in from the contact's **Tax ID** when that holds 11 digits, and you
  can type it there. A contact person of a company carries the company's 9-digit code, so no number is sent and
  Signify refuses the ID-card step until you fill in **Personal Number**. Never type a personal number into the
  **Tax ID** of a company's contact person: Odoo syncs it with the company, so it would replace the company's tax
  code for the company and all its contacts.
- **Status is not instant.** Up to 15 minutes, or **Refresh Status**.
- **Where files go.** The signed document goes to the linked record too; the evidence report and the signers'
  attachments stay on the Signify document.

## 9. Common questions

**Can I fix a mistake after sending?** Press **Recall**, then **Duplicate** the document: the copy is a draft with
the same file and the same recipients, which you can change before sending.

**Who is the sender in Signify's emails?** The Signify account of the user who pressed **Send**.

**What happens when I connect another Signify account?** The new one is used for new documents. The old one stays saved, so the documents sent with it keep updating; **Disconnect** it from the **Archived** filter when they are done.

**Can someone else send my draft?** An administrator can; it is then sent with the administrator's account.

**In which language are Signify's messages in Odoo?** Georgian for users working in Georgian, English otherwise.

**Do recipients need an Odoo account?** No. They sign in Signify, from the email, the SMS or the link.

## 10. Known limitations

- One file per document; no Signify templates; no text, date or checkbox fields for recipients.
- Reminders only as Signify sends them (section 4): fixed intervals, at most 10, one channel, none for link
  recipients. No expiry dates from Odoo: Signify's defaults apply, including that a signer may forward the document.
- Statuses arrive by the 15-minute update, not instantly.
- A document keeps the account it was sent with. If that Signify user is removed from the Signify team, the document
  can no longer be refreshed or recalled from Odoo.
- The connection lasts until Signify revokes it; after that the user connects again (section 7).

## 11. Glossary

| Word | Meaning |
|---|---|
| Signature Keyword | The word in the file where Signify places a signature |
| Evidence Report | Signify's PDF record of who signed, when and with which method |
| Signify ID | The document's number in Signify |
| Automatic Signer | Our company, signed by Signify without a person |
