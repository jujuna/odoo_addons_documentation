# Signify - Documents

> **Module:** `signify_documents` | **Path:** [`custom_addons/gec_odoo_modules/signify_documents/`](../custom_addons/gec_odoo_modules/signify_documents/)
> Status: built 2026-11-06, auto-installed with `signify` + `documents`; 5 tests pass on gec20_signify_test.
> Parent module: [`signify.md`](signify.md). Core twin: `documents_sign`.

## What It Does & Why It Exists

Without this bridge, the signed files Signify sends back stay on the Signify document and in the linked record's
chatter; the Documents app never sees them. This module does what Odoo's own `documents_sign` does for Sign: the
Signify document becomes a Documents record holder, so every signed file and evidence report that lands on it is
filed in a per-company Documents folder. It also adds a "Send with Signify" action inside the Documents app, so a
contract that already lives in Documents can be sent for signature from there.

---

## The Big Picture — How It Works

1. **Setting.** Settings > Documents > Files Centralization > Signify > Folder. One folder per company. Empty folder
   = nothing is filed (the module stays silent).
2. **Filing.** When a Signify document reaches Signed, the signed files and, a little later, the evidence report are
   created as attachments on the Signify document. Core Documents turns every new attachment on a
   `documents.mixin` record into a `documents.document` in the record's folder
   ([`enterprise/documents/models/ir_attachment.py:153-179`](../enterprise/documents/models/ir_attachment.py#L153)).
   The module only answers two questions of the mixin: which folder
   ([`signify_document.py`](../custom_addons/gec_odoo_modules/signify_documents/models/signify_document.py))
   and which contact (the first signer). Same attachment, no copy.
3. **Not filed.** The uploaded file (`file` field) is a field attachment and is skipped by core; the copy on the
   linked record is created with `no_document`, as Sign does, so a contract never appears twice.
4. **Send from Documents.** The server action "Send with Signify" (usage `documents_embedded`, group Signify User)
   is pinned on a folder by the administrator (folder > Actions). On a PDF or Word file it opens a new Signify draft
   whose "Linked To" is that Documents record; the signed copy later lands on that record's chatter.

### Key Decision Points

| Choice | Effect |
|---|---|
| Folder per company (setting) | one Signify folder per company; a group with several companies sets it once per company |
| No folder set | signed files stay on the Signify document only, exactly as before this module |
| Evidence report filed too | the legal proof is in Documents next to the signed file (both carry the Signify document as Contact source) |
| Action not pinned automatically | `documents_sign` pins its action in a post-init hook on named folders; here the administrator pins it where contracts live |

---

## How Things Work Under the Hood

- [`models/signify_document.py`](../custom_addons/gec_odoo_modules/signify_documents/models/signify_document.py):
  `_inherit = ['signify.document', 'documents.mixin']`, `_get_document_folder` = company folder,
  `_get_document_partner` = first signer. Core precedent
  [`enterprise/documents_sign/models/sign_request.py:10,65-69`](../enterprise/documents_sign/models/sign_request.py#L10).
- [`models/documents_document.py`](../custom_addons/gec_odoo_modules/signify_documents/models/documents_document.py):
  `action_signify_send` refuses anything but a binary PDF/Word document, then calls the parent module's
  `action_new_from_attachment` (same read check, same draft shape as the chatter button).
- [`data/ir_actions_server_data.xml`](../custom_addons/gec_odoo_modules/signify_documents/data/ir_actions_server_data.xml):
  the embedded action, `noupdate`, like
  [`enterprise/documents_sign/data/ir_action_server_data.xml`](../enterprise/documents_sign/data/ir_action_server_data.xml).
- Settings: [`models/res_company.py`](../custom_addons/gec_odoo_modules/signify_documents/models/res_company.py)
  `documents_signify_folder_id` (`check_company`), related field on `res.config.settings`, block copied from
  `documents_hr`.

## Configuration & Settings

| Where | What |
|---|---|
| Settings > Documents > Files Centralization > Signify | the folder; shown once the module is installed |
| Documents > a folder > Actions | pin "Send with Signify" |
| Access | the action needs Signify User; the filed documents follow the folder's own access rules |

## Dependencies

| Requires | Why |
|---|---|
| `signify` | the documents and the draft creation |
| `documents` | the mixin, folders and embedded actions |

## Gotchas & Non-Obvious Behavior

- **Chatter uploads become documents too.** A file a user drops in the Signify document's chatter is an attachment
  on a mixin record and is filed in the folder, as with Sign requests. Keep the chatter for notes.
- **One file at a time.** Selecting several Documents and running the action raises; Signify takes one file per
  document in our connector.
- **Folder deleted or archived.** The setting keeps pointing at it; new files are then filed nowhere. Set a new folder.
- **Access.** A Documents user who can see the folder sees the signed contract even without the Signify group. Choose
  the folder's members accordingly.

## Related Docs

- [`signify.md`](signify.md)
- [`dev_notes/plans/signify_review_20261106.md`](../dev_notes/plans/signify_review_20261106.md) section 5
