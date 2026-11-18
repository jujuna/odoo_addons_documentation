# Sign with Georgian ID Card (QES) (`id_ge_sign`)

Lets a signer sign an Odoo Sign document with their Georgian ID Card. The card's signature is
embedded in the PDF, and Odoo records who signed from the card's certificate.

**Who this is for:** people who send documents in Sign, the signers, and the administrator who
sets it up. Developers: see [README_DEV.md](README_DEV.md).

## 1. What it does

| Feature | What it gives you |
|---|---|
| "Georgian ID Card" as a role's authentication | Any Sign template can ask a signer to sign with the card, next to ordinary signers |
| Card signature inside the PDF | The signed PDF carries a signature any PDF reader can check, not only a drawn picture |
| Certificate check | Only cards issued under the state's signing certificates (id.ge) are accepted; they come with the module |
| Person check | When the signer's contact holds their personal number, only that person's card is accepted |
| Audit trail | The document's chatter and the Certificate of Completion name the card holder, personal number and certificate |
| Public links without typing | A visitor on a shared link signs with no name or email; the card provides both |
| Clear refusals | A refused card tells the signer to try again; the reason goes to the document as an internal note |

## 2. Quick facts

| | |
|---|---|
| Menu | **Sign > Configuration > Roles** (Sign administrators) |
| Settings | **Settings > Sign > Sign with Georgian ID Card** |
| Button the signer presses | **Proceed to Signing** (core Sign shows it for card roles) |
| Who can send | Anyone who can send Sign documents; nothing changes there |
| Signer needs | A desktop computer, a card reader, the Georgian ID Card application from id.ge, and the card's PIN3 |
| Requires | Odoo Sign (Enterprise) |
| Works with | Ordinary Sign signers on the same document; Contacts (the Tax ID field) |

## 3. How it works

```text
Sender sends the document
        │
        ▼
Signer opens it, fills the fields, presses Proceed to Signing
        │
        ▼
Odoo prepares the PDF and opens the Georgian ID Card application
        │
        ▼
Signer places the signature block and enters PIN3; the card signs
        │
        ▼
The application sends the signed PDF back to Odoo
        │
        ▼
Odoo checks the signature, the state certificate and the person
        │
        ├── accepted ──► document signed, next signer invited
        │
        └── refused ───► signer is asked to try again, reason in the chatter
```

The browser only starts the application; the application talks to Odoo directly and the
signing page waits until the signature arrives. Each attempt has 10 minutes. When the last
signer has signed, Sign completes the document as usual: the signed PDF and the Certificate of
Completion are sent to everyone.

## 4. Set it up (once)

1. **Install** the module. The state's signing certificates (GEO Signing CA G2 and GEO Signing
   CA, from id.ge) are saved automatically; nothing to paste.
2. **Give Odoo a public https address.** The card application downloads the document from Odoo
   and sends it back over the internet. In developer mode, **Settings > Technical > Parameters >
   System Parameters**: `web.base.url` = the public https address, and `web.base.url.freeze` =
   `True` so an administrator's login from another address does not change it.
3. **Turn on card signing for a role:** **Sign > Configuration > Roles**, set **Authentication**
   to **Georgian ID Card** on the role (for example "Employee" or "Customer"). Every template
   field assigned to that role is signed with the card.
4. **Tie contacts to their card** (recommended): put the person's 11-digit personal number in
   the contact's **Tax ID**. Then only their own card is accepted (see section 6).
5. **Shared links:** give every shared link with a card role a **Valid Until** date (see
   section 7).

Optional, in **Settings > Sign > Sign with Georgian ID Card**:

| Setting | Options | What it changes |
|---|---|---|
| Application language | Georgian · English | The language of the application's own screens |

Works without setup: the certificates and Georgian are already set.

**When id.ge publishes a new signing certificate:** in developer mode open **Settings >
Technical > Parameters > System Parameters**, key `id_ge_sign.trust_anchor`, and paste the new
certificate's PEM text after the ones already there. Do not delete the existing ones: cards
issued under them stay valid. Text that is not a certificate is refused on save.

## 5. Signing a document

The signer gets the document the usual Sign way: the invitation email, **Sign Now** for an
internal user, or a shared link.

1. Open the document. → The signature field already shows the signer's name in italics. It only
   marks where the card's block will go; there is no "Adopt Your Signature" step.
2. Fill the other fields and press **Proceed to Signing**. → A window **Sign with Georgian ID
   Card** shows "Preparing the document for signing...", then asks for PIN3.
3. The browser may ask to open the Georgian ID Card application: choose **Open** (or **Always
   allow**).
4. In the application, draw the signature block over the name mark, enter PIN3.
5. Wait. → The window closes by itself and Sign shows its usual thank-you or next-document
   screen.

In the window: **Open the application again** if it did not open; **Cancel** stops the attempt
and the document goes back to waiting, so the signer can start again; **Try again** after a
refusal starts a new attempt.

The block the application stamps shows the card holder's name and personal number from the
card. Odoo cannot change that text. The italic name mark stays in the PDF next to it.

## 6. Who may sign: the personal number check

When the signer's contact is a person (not a contact person of a company) and its **Tax ID** is
an 11-digit number, the card's personal number must be that number. A country prefix such as
"GE" is ignored.

| Signer's contact | Tax ID | Card's personal number | Result |
|---|---|---|---|
| Giorgi Beridze | 01001000001 | 01001000001 | Signed |
| Giorgi Beridze | GE01001000001 | 01001000001 | Signed |
| Giorgi Beridze | 01001000001 | 01001000009 | Refused: someone else's card |
| Nino Kapanadze, contact person of a company | 404123456 (the company's) | any | Signed, not compared |
| A person with no Tax ID | empty | any | Signed, not compared |

A contact person of a company carries the company's Tax ID, so Odoo cannot know their personal
number. For a strict check, send the document to a contact of their own.

## 7. Shared links (public signing)

A visitor who opens a shared link with a card role signs without typing a name or email.

1. Odoo creates a hidden contact "Georgian ID Card signer" and a document of its own for this
   visitor.
2. After a successful signature, the contact gets the card holder's name and their personal
   number as Tax ID.
3. The contact becomes visible, unless an active contact with that number already exists; then
   it stays hidden and keeps only this signature's history.

Example: the same person signs a shared link ten times → one visible contact, nine hidden ones.

A visitor who gives up leaves an unsigned document and a hidden contact behind. With **Valid
Until** set on the shared link, those documents expire on that date like any other.

**Never merge these contacts.** Merging rewrites the signature log, and the document then shows
an integrity warning.

## 8. Several signers on one document

- Ordinary signers sign first, card signers after them; Odoo puts them in that order when the
  document is created.
- Everyone signs one after another, even when the template let them sign at the same time. The
  send window shows the order as fixed.
- Two card signers: each one signs on top of the previous one's signed PDF, and earlier
  signatures stay valid. Not yet tried with two real cards.
- **Sign Now** is refused when the template has a card role and more than one role: send it
  instead.

**Changing a signer.** When the role has **Change Authorized**, the sender can replace the
signer of a sent document as in core Sign. If the old signer had started signing with the card,
that attempt is cancelled: their application can no longer send a signature, and the new signer
starts from the beginning.

## 9. What the document keeps

| Where | What you see |
|---|---|
| Chatter, after signing | "GIORGI BERIDZE signed with a Georgian ID Card (certificate chain verified, revocation not checked)." with the certificate, personal number, serial and expiry date |
| Chatter, when the card's name differs from the contact's | "... signed with a Georgian ID Card on the link sent to Giorgi Beridze ..." (also when only the script differs, Latin against Georgian) |
| Chatter, after a refusal | Internal note "The Georgian ID Card signature of Giorgi Beridze was refused: <reason>" |
| Certificate of Completion | Table **Georgian ID Card Signatures**: Signatory, Certificate, Personal Number, Serial, Valid Until, Assurance ("Chain verified (revocation not checked)") |

## 10. When Odoo refuses

What the signer or sender sees:

| Message starts with | Why | What to do |
|---|---|---|
| Signing with the Georgian ID Card is not set up yet. | The state certificates were removed from the settings | Administrator: update the module, which saves them again |
| The ID card signature was not accepted. | The card or the signed file was refused; the reason is in the internal note on the document | Signer: try again with their own card. Sender: read the note (table below) |
| Timed out waiting for the signature. | No signature arrived within 10 minutes | **Try again** |
| The signers before you have not signed yet. | Strict order (section 8) | Wait for the earlier signers |
| Georgian ID Card signing supports a single document per request. | The template has more than one PDF | Use one PDF per template |
| Documents that require secure signing need to be sent. | **Sign Now** with several roles | Send the document |
| The documents of this request are too large | The PDF is over 25 MB | Use a smaller PDF |
| Could not start Georgian ID Card signing. | The shared link is expired, cancelled or not a single card role | Ask the sender for a new link |
| Set valid PEM certificates for Georgian ID signing. | The certificates setting holds text that is not a certificate | Paste the full PEM text, including its BEGIN and END lines |

The reason in the internal note:

| Reason starts with | Meaning |
|---|---|
| The certificate personal number does not match the signer. | Someone else's card (section 6) |
| A trusted certificate chain is required | The card's certificate was not issued under the saved state certificates |
| The signing certificate is not valid at signing time. | The card's certificate has expired |
| Certificate key usage does not allow document signing. | The card used its login certificate, not its signing certificate |
| This signing session is no longer active. | 10 minutes passed, the signer was changed, the document was cancelled or expired, or a newer attempt started |
| The signed PDF does not match the document prepared by Odoo. | The application signed a different file |
| The signed PDF exceeds the allowed signature size. | The application added more than 5 MB |
| The signed PDF changes the document beyond adding one signature. | The returned file is not the prepared document plus one signature: page content, pages, notes or actions differ |
| The signature block covers too much of the page. | The visible signature block is larger than 2 % of its page: draw it smaller, or sign without a visible block |

## 11. Rules to remember

- **Card signers sign last, and everyone signs in order.** The card seals the document.
- **One PDF per document.** The card signs one file.
- **The Tax ID is the identity.** An 11-digit personal number on a person's contact locks the
  document to that person's card.
- **10 minutes per attempt.** After that the signer presses **Try again**.
- **Odoo says "chain verified, revocation not checked", never "qualified".** It checks that the
  certificate comes from the state, not whether it was revoked. Core's invitation email still
  calls the request a qualified signature request.
- **The visible block proves nothing; the embedded signature does.** Check a PDF in a PDF
  reader's signature panel.

## 12. Common questions

**Can a signer use a phone?** No. The Georgian ID Card application runs only on a desktop
computer.

**How do I check that a downloaded PDF is genuine?** Open it in Adobe Acrobat Reader (signature
panel) or an EU signature validator. It shows whether the file changed since signing and who
signed it.

**Do all our companies and databases use the same certificates?** Yes. They are the state's
public certificates; they hold no secret and are the same for everyone.

**The signer was refused but used the right card. Why?** Read the internal note on the document:
the most common reasons are an expired certificate, a Tax ID with another number, or more than
10 minutes.

## 13. Known limitations

| Limitation | Workaround |
|---|---|
| Desktop only | Sign on a computer with a card reader |
| One PDF per document | Split into several templates |
| Revocation is not checked; the signature has no timestamp | Validate an important PDF in an external validator |
| The signer chooses where the visible signature block goes; it may cover up to 2 % of its page | Leave free space for it in the template. Another limit: system parameter `id_ge_sign.max_signature_area_percent` |
| HR contracts signed by card are not filed in the employee's Documents folder | File the signed PDF by hand |
| Salary-package offers are completed by a step a card signer never reaches | Do not put a card role on salary-package templates |
| Two card signers have not been tried with real cards | Test once before using it |

## 14. Glossary

| Term | Meaning |
|---|---|
| Georgian ID Card application | The free desktop program from id.ge (Universal Program) that talks to the card reader |
| PIN3 | The card code that unlocks its signing key |
| State certificates | GEO Signing CA G2 and GEO Signing CA: the certificates that issue the cards' signing certificates |
| Chain verified | The card's certificate was issued by one of the state certificates |
| Revocation | A certificate cancelled before its expiry date; Odoo does not check it |
| Personal number | The 11-digit number on the card; Odoo compares it with the contact's Tax ID |
