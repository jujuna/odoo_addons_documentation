# Mail Configuration — Servers, Alias Domains, Aliases, Bounces & Notifications

> **Modules:** `base` (`ir.mail_server`) + `mail` (`mail.alias.domain`, `mail.alias`, `fetchmail.server`, `mail.mail`, `mail.thread`, `mail.blacklist`) | **Path:** [`odoo/addons/base/models/ir_mail_server.py`](../odoo/addons/base/models/ir_mail_server.py), [`addons/mail/models/`](../addons/mail/models/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

This is the subsystem that lets Odoo **send** email (notifications, invoices, mailings) and **receive** it (replies that thread onto records, new leads or tasks created from an inbox). A customer replies to a quotation email and the reply lands in the sales order chatter; a delivery failure (bounce) is detected and the address is flagged; a message to `jobs@company.com` creates an applicant.

Three things make this more involved than "set an SMTP server and go":

1. **Deliverability** — SPF/DKIM/DMARC reject a server sending "as" an address it is not authorized for. Odoo rewrites the visible `From` to stay authorized.
2. **Threading** — replies must find their way back to the right record. Odoo uses a `catchall` address as `Reply-To` plus Message-Id matching.
3. **Bounces** — failed deliveries must be attributed. Odoo uses a `bounce` address as the envelope sender.

The one object that ties the three together is the **Alias Domain**. Start there.

---

## The Big Picture — Two Flows

```
OUTGOING                                        INCOMING
--------                                        --------
message_post / notification / template          mail provider (IMAP/POP) or MTA pipe
   |                                                |
   v                                                v
mail.mail (queue, state=outgoing)               fetchmail.server._fetch_mail()  (cron, 5 min)
   |  grouped by (server, alias domain, from)       |   object_id = fallback model
   v                                                v
_find_mail_server -> pick ir.mail_server        MailThread.message_process()
   |  encapsulate From if not authorized            |
   v                                                v
ir.mail_server.send_email -> SMTP relay         message_route()  (bounce -> reply -> alias -> fallback)
   |  relay may rewrite From again                  |
   v                                                v
recipient                                       message_new (create) / message_update (append)
```

- **Outgoing** path: [mail_mail.py](../addons/mail/models/mail_mail.py) → [ir_mail_server.py](../odoo/addons/base/models/ir_mail_server.py).
- **Incoming** path: [fetchmail.py](../addons/mail/models/fetchmail.py) → [`message_process`](../addons/mail/models/mail_thread.py#L1495).

---

## 1. The Central Config Object — Alias Domain (`mail.alias.domain`)

Defined in [mail_alias_domain.py](../addons/mail/models/mail_alias_domain.py). One record per email domain; each company points at one through `res.company.alias_domain_id`.

| Field | Default | What it is for |
|---|---|---|
| `name` | — | The bare domain, e.g. `example.com` |
| `bounce_alias` → `bounce_email` | `bounce` → `bounce@domain` | **Envelope sender / Return-Path.** Delivery failures come back here ([`bounce_alias`](../addons/mail/models/mail_alias_domain.py#L28)) |
| `catchall_alias` → `catchall_email` | `catchall` → `catchall@domain` | **Reply-To.** Human replies go here and the gateway threads them onto the record ([`catchall_alias`](../addons/mail/models/mail_alias_domain.py#L33)) |
| `default_from` → `default_from_email` | `notifications` → `notifications@domain` | **Notifications address.** The visible sender when the real author is not authorized on the relay ([`default_from`](../addons/mail/models/mail_alias_domain.py#L38)) |
| `company_ids` | — | Companies using this domain (drives the multi-company check) |

`default_from` may be a bare local part **or** a full address (`x@other.com`); a value containing `@` is used verbatim ([`_compute_default_from_email`](../addons/mail/models/mail_alias_domain.py#L67)). Bounce and catchall are always `alias@name`.

**Company derivation.** `res.company` stores only `alias_domain_id` and computes `bounce_email`, `catchall_email`, `default_from_email` from it ([res_company.py](../addons/mail/models/res_company.py#L13)). All three addresses of a company come from **one** alias domain.

**Multi-company.** When an alias domain has `company_ids`, aliases on it must belong to a matching company — [`_check_alias_domain_id_mc`](../addons/mail/models/mail_alias.py#L100) raises otherwise. Per-record resolution: the record's company alias domain → the env company's → the first alias domain found ([`_mail_get_alias_domains`](../addons/mail/models/models.py#L110)).

**Seeding.** No XML record ships. The first alias domain created is attached to every company and every alias that has none ([`create`](../addons/mail/models/mail_alias_domain.py#L145)). When `mail` is installed on a database configured through `base` only, the post-init hook turns the ICPs `mail.catchall.domain`, `mail.bounce.alias`, `mail.catchall.alias`, `mail.default.from` into an alias domain ([`_migrate_icp_to_domain`](../addons/mail/models/mail_alias_domain.py#L255), called from [`_mail_post_init`](../addons/mail/__init__.py#L11)).

**Personal-server guard.** An alias domain's default-from may not be an address that a personal mail server is filtered on ([`_check_default_from_not_used_by_users`](../addons/mail/models/mail_alias_domain.py#L176)). The reverse check blocks a user from creating a personal server for an alias-domain address.

---

## 2. Outgoing Mail Servers (`ir.mail_server`)

Defined in [base ir_mail_server.py](../odoo/addons/base/models/ir_mail_server.py), extended by [mail ir_mail_server.py](../addons/mail/models/ir_mail_server.py). Ordered by `sequence, id`.

### Fields that are decision points

| Field | Default | Notes |
|---|---|---|
| `smtp_host` / `smtp_port` | — / `25` | 465 for SSL, 587 for STARTTLS by convention |
| `smtp_encryption` | `none` | `none`, `starttls` / `starttls_strict`, `ssl` / `ssl_strict`. `*_strict` validates the server certificate against the OS trust store; the other variants only encrypt ([`smtp_encryption`](../odoo/addons/base/models/ir_mail_server.py#L154)) |
| `smtp_authentication` | `login` | `login` (user/password), `certificate` (client SSL certificate; requires encryption, [`_certificate_requires_tls`](../odoo/addons/base/models/ir_mail_server.py#L181)), `cli` (use the `odoo.conf` SMTP values). `google_gmail` and `microsoft_outlook` add `gmail` / `outlook` OAuth |
| `from_filter` | empty | Comma-separated addresses **or** domains this server may send "From". **The deliverability gate** — see §3 |
| `sequence` | `10` | Labelled "Priority"; lower wins when no specific server is requested |

[`_onchange_encryption`](../odoo/addons/base/models/ir_mail_server.py#L954) sets the port to 465 only for `ssl`; every other choice, `ssl_strict` included, resets it to 25. Check the port after picking a strict variant.

### Maximum email size

There is no per-server size setting. [`_get_max_email_size`](../odoo/addons/base/models/ir_mail_server.py#L258) reads the ICP `base.default_max_email_size` (MB), seeded to `20` with `noupdate` ([data](../odoo/addons/base/data/ir_config_parameter_data.xml#L5)). When an email would exceed it, attachments owned by a business record are removed and sent as secure download links in the body ([mail_mail.py](../addons/mail/models/mail_mail.py#L538)); the composer warns before sending ([`_compute_attachment_links`](../addons/mail/wizard/mail_compose_message.py#L334)). `ir.mail_server.max_email_size` does not exist in 20.0; use the ICP.

### CLI / `odoo.conf` alternative

When no database server is used, Odoo falls back to the config values `--smtp`, `--smtp-port`, `--smtp-user`, `--smtp-password`, `--smtp-ssl` (means STARTTLS), `--email-from`, `--from-filter` ([config.py](../odoo/tools/config.py#L382); consumed in [`_connect__`](../odoo/addons/base/models/ir_mail_server.py#L452)). `--email-from` is the default From and bounce address when no alias domain applies ([`_get_default_from_address`](../odoo/addons/base/models/ir_mail_server.py#L620)). The ICP `mail.default.from_filter` overrides `--from-filter` ([`_get_default_from_filter`](../odoo/addons/base/models/ir_mail_server.py#L630)).

### Personal (per-user) outgoing servers

A user can connect their own mailbox (Preferences → outgoing server type **Gmail** or **Outlook**, added by [google_gmail](../addons/google_gmail/models/res_users.py#L9) / `microsoft_outlook`). Rules:

- Only internal users, and only when **Use Custom Email Servers** is on ([`action_setup_outgoing_mail_server`](../addons/mail/models/res_users.py#L611)). The server is created archived with port 587, STARTTLS and `from_filter` = the user's email, and activated once the OAuth login completes.
- Personal servers are **excluded from normal selection** ([`_find_mail_server_allowed_domain`](../addons/mail/models/ir_mail_server.py#L84)). A mail uses one only when the owner created the message; mails from several creators, or with the ICP `mail.disable_personal_mail_servers` set, use public servers ([`_filter_mail_mail_servers`](../addons/mail/models/mail_mail.py#L385)).
- They are **throttled**: 30 emails/minute by default (ICP `mail.server.personal.limit.minutes`, [`_get_personal_mail_servers_limit`](../addons/mail/models/ir_mail_server.py#L101)). [`_split_by_delayed_batch`](../addons/mail/models/mail_mail.py#L637) reschedules the overflow through `scheduled_date` and re-triggers the queue cron.
- Abandoned or replaced personal servers are deleted by an autovacuum ([`_gc_personal_mail_servers`](../addons/mail/models/res_users.py#L599)).

---

## 3. How the Visible `From` Is Resolved (the part that surprises people)

Every email has **two** sender addresses and either can be rewritten:

| | Header `From:` | Envelope sender (`MAIL FROM` → `Return-Path`) |
|---|---|---|
| Purpose | What the recipient sees | Authentication + bounce routing |
| Set from | The message author, then possibly encapsulated | The alias-domain **bounce** address, when the server allows it |

### Server selection — `_find_mail_server`

[`_find_mail_server(email_from)`](../odoo/addons/base/models/ir_mail_server.py#L848) tries, in order:

1. A server whose `from_filter` matches the **exact author email**, then one matching the **author's domain** → keep the author as `From`.
2. A server matching the **notifications address** (alias-domain `default_from_email`), exact then domain → send as notifications.
3. The first server with **no** `from_filter` → notifications address if one exists, else the author.
4. Any remaining server, with a log warning.
5. No database server → the CLI `from_filter`.

Steps 2–4 skip personal servers ([`_filter_mail_servers_fallback`](../addons/mail/models/ir_mail_server.py#L81)).

**`from_filter` matching** ([`_match_from_filter`](../odoo/addons/base/models/ir_mail_server.py#L930)): empty matches everything; an entry **with `@`** matches that **exact address only**; an entry **without `@`** matches the **whole domain** ([`email_domain_normalize`](../odoo/tools/mail.py#L1009) returns `False` for anything containing `@`). `test1@gmail.com` authorizes one address; `gmail.com` authorizes all of `@gmail.com`.

### Encapsulation — keeping the name, swapping the address

At send time, [`_prepare_email_message__`](../odoo/addons/base/models/ir_mail_server.py#L642) checks whether the chosen sender is the notifications address while the header `From` is not ([`notifications_email`](../odoo/addons/base/models/ir_mail_server.py#L673)). If so it **encapsulates**:

```
encapsulate_email("Dato" <dato@gmail.com>, notifications@your-domain)
   ->  "Dato" <notifications@your-domain>
```

[`encapsulate_email`](../odoo/tools/mail.py#L1084) keeps the **display name** and swaps the **address**. Without a display name, the local part of the original address becomes the name (`"dato" <notifications@your-domain>`).

The **envelope sender** becomes the bounce address only when the server's `from_filter` also covers it (empty filter, or the bounce domain); otherwise it stays equal to the header `From` ([`smtp_from = bounce_address`](../odoo/addons/base/models/ir_mail_server.py#L683)). The notifications and bounce addresses reach this layer through the `domain_notifications_email` / `domain_bounce_address` context set per alias domain in [`_split_by_mail_configuration`](../addons/mail/models/mail_mail.py#L586).

### The relay has the final say

After Odoo builds the headers, the SMTP relay applies its own policy. Gmail / Google Workspace rewrites `From:` to the authenticated account unless the address is a verified "Send mail as" alias [Unverified — Google-side behavior, not in Odoo source].

#### Worked example: server logs in as `test1@gmail.com`, author is `dato@gmail.com`

| Config | Visible `From:` to recipient |
|---|---|
| Gmail relay, `dato@gmail.com` not a verified Gmail alias | `test1@gmail.com` (display name "Dato" usually survives) — the relay forces it |
| Own domain + SPF/DKIM, `from_filter` not matching the author, notifications address set | `"Dato" <notifications@your-domain>` (encapsulated) |
| Server and relay authorized for `gmail.com` (`from_filter = gmail.com`) | `dato@gmail.com` |

A personal Gmail/Outlook mailbox therefore makes a poor company-wide outgoing server: it masks the real author. Use your own domain with SPF/DKIM and a notifications address.

---

## 4. Reply-To vs Return-Path — the two round-trip addresses

They are deliberately different so human replies and delivery failures go to different places:

- **Reply-To = catchall** ([`_notify_get_reply_to_batch`](../addons/mail/models/models.py#L610)). Priority: an alias owned by the document (e.g. a project's alias for its tasks) → the company `catchall_email` → the caller's default. Replies land on the gateway and thread onto the record. A 68-character guard drops the display name when the header would risk RFC folding that breaks some DKIM verifiers ([`_notify_get_reply_to_formatted_email`](../addons/mail/models/models.py#L678)).
- **Return-Path = bounce** of the record's alias domain ([`Return-Path`](../addons/mail/models/mail_thread.py#L4087)). Delivery failures go to `bounce@domain` for detection.

> **Owner vs target gotcha.** Reply-To resolution looks for aliases by their **owner** (`alias_parent_model_id` / `alias_parent_thread_id`, [models.py](../addons/mail/models/models.py#L650)), while incoming record *creation* uses the alias **target** (`alias_model_id`). A project alias is owned by the project and creates tasks.

**Reply-All support.** Notification emails list the thread's external recipients (customers, and To/Cc addresses of the incoming email that did not become partners) in their own `To`/`Cc` headers, so a customer's Reply-All reaches everyone ([`X-Msg-To-Add`](../addons/mail/models/mail_thread.py#L4083), merged in [`_alter_message__`](../odoo/addons/base/models/ir_mail_server.py#L698)). The SMTP recipient list is still limited to the intended recipient ([`_prepare_smtp_to_list`](../odoo/addons/base/models/ir_mail_server.py#L738)). With 50 or more external addresses the record counts as public and nobody is listed ([`_CUSTOMER_HEADERS_LIMIT_COUNT`](../addons/mail/models/mail_thread.py#L150)).

---

## 5. The Outgoing Queue (`mail.mail`)

[mail_mail.py](../addons/mail/models/mail_mail.py). States: `outgoing` (default) → `sent` / `exception` / `cancel`; `received` marks incoming copies ([`state`](../addons/mail/models/mail_mail.py#L79)).

- **Cron "Mail: Email Queue Manager"** runs `process_email_queue(batch_size=1000)` **hourly** ([ir_cron_data.xml](../addons/mail/data/ir_cron_data.xml#L4)) and is triggered earlier when personal-server batches are delayed. It picks `outgoing` mails whose `scheduled_date` is empty or past, up to ICP `mail.mail.queue.batch.size` ([`process_email_queue`](../addons/mail/models/mail_mail.py#L229)).
- **Grouping**: [`_split_by_mail_configuration`](../addons/mail/models/mail_mail.py#L586) groups mails by (server, alias domain, From) so one SMTP session serves each group, in batches of ICP `mail.session.batch.size` (1000).
- **Direct send**: notification emails are sent right after the transaction commits when there are fewer than ICP `mail.mail.force.send.limit` (100) of them; otherwise they wait for the cron ([`force_send`](../addons/mail/models/mail_thread.py#L3749)). The composer in mass mode applies the same limit ([mail_compose_message.py](../addons/mail/wizard/mail_compose_message.py#L682)). Set `0` to always queue.
- **Failures**: `failure_type` (`mail_smtp`, `mail_email_invalid`, `mail_from_invalid`, `mail_spam`, …) plus `failure_reason`. **No automatic retry** — a failed mail stays `exception` until [`action_retry`](../addons/mail/models/mail_mail.py#L208) resets it to `outgoing`. An invalid recipient is skipped so the others still receive the mail.
- **Auto-delete**: `auto_delete` mails are removed after sending, unless the failure was something other than an invalid or missing address ([`_postprocess_sent_message`](../addons/mail/models/mail_mail.py#L286)).
- **Cancelled mails** are purged after 6 months by an autovacuum (ICP `mass_mailing.cancelled_mails_months_limit`, `0` disables; [`_gc_canceled_mail_mail`](../addons/mail/models/mail_mail.py#L192)).

Failed mails are reviewed in **Settings → Technical → Email → Emails** ([menu](../addons/mail/views/mail_menus.xml#L80)), filtered on the failed state.

---

## 6. Incoming Mail Servers (`fetchmail.server`)

[fetchmail.py](../addons/mail/models/fetchmail.py), part of `mail`.

- **Types** (`server_type`): `imap`, `pop`, `local` (an MTA pipes mail into `odoo-mailgate.py`). OAuth `gmail` / `outlook` are added by [google_gmail](../addons/google_gmail/models/fetchmail_server.py#L12) / [microsoft_outlook](../addons/microsoft_outlook/models/fetchmail_server.py#L16) (XOAUTH2 IMAP login).
- **`object_id`** ("Create a New Record") is the fallback model for mail that matches no reply and no alias ([`object_id`](../addons/mail/models/fetchmail.py#L121)); it is passed as the gateway's `model` together with `default_fetchmail_server_id`.
- **`attach` / `original`**: strip attachments before processing, or keep a full copy of each email on the message ([`attach`](../addons/mail/models/fetchmail.py#L111)).
- **Cron "Mail: Fetchmail Service"** runs every **5 minutes** and is **auto-toggled**: active only while at least one confirmed, non-`local` server exists ([`_update_cron`](../addons/mail/models/fetchmail.py#L357)). Servers are processed by `priority`, then oldest fetch first.
- **Fetch loop** ([`_fetch_mail`](../addons/mail/models/fetchmail.py#L263)): IMAP reads `UNSEEN` messages and flags them `\Seen` after handling; POP retrieves all and **deletes** them after handling; at most 50 per server per run; a commit after each message so one bad email does not block the batch.
- **A message that fails processing is still marked handled** — IMAP flags it read, POP deletes it. Keep a copy in the mailbox (IMAP) if you need to replay failures.
- A server failing for more than 5 days is set back to draft and the administrator is notified ([`MAIL_SERVER_DEACTIVATE_TIME`](../addons/mail/models/fetchmail.py#L21)).

---

## 7. The Mail Gateway — How an Incoming Email Finds Its Record

[`message_process`](../addons/mail/models/mail_thread.py#L1495) parses the raw email, drops duplicates (same `Message-Id`, with an advisory lock against concurrent fetches, [`is_duplicate`](../addons/mail/models/mail_thread.py#L1540)), ignores replies to Odoo's own loop-detection bounces, then [`message_route`](../addons/mail/models/mail_thread.py#L1171) decides in **strict order**:

1. **Bounce** — handled as a bounce, **nothing** is created (§9). Any other email resets the sender's bounce counter.
2. **Reply** — the last 32 `References` / `In-Reply-To` ids are matched against `mail.message.message_id`. A hit appends to that record and **ignores alias defaults** (a reply never creates). If a recipient is an alias of a *different* model, the email is treated as a new message, not a reply.
3. **Direct write to catchall** — an email addressed only to catchall addresses is bounced back to the sender ([catchall bounce](../addons/mail/models/mail_thread.py#L1315)).
4. **Alias** — `mail.alias` is searched by full address (`alias_full_name`) or by local part when `alias_incoming_local` is set. Each match gives a route: `alias_force_thread_id` set → append to that record; else **create** a record of `alias_model_id`.
5. **Fallback model** — the `object_id` of the fetchmail server.
6. **Catchall plus unroutable addresses** → bounce; otherwise "No possible route found" is raised.

[`_message_route_process`](../addons/mail/models/mail_thread.py#L1394) then calls `message_update` (append) or `message_new` (create) and posts the message as OdooBot. When creation from an alias fails, the sender gets the alias bounce and the alias is flagged invalid.

**Loop detection** ([`_detect_loop_sender`](../addons/mail/models/mail_thread.py#L1053)): if 20 records were created from the same sender, or 20 emails from it landed on one record, within 120 minutes, the mail is dropped with one bounce (ICPs `mail.gateway.loop.threshold` / `mail.gateway.loop.minutes`). Addresses listed in `mail.gateway.allowed` (Settings → Technical → Email, developer mode) are exempt.

---

## 8. Aliases (`mail.alias`)

[mail_alias.py](../addons/mail/models/mail_alias.py). An alias maps an inbound address to a model.

- **`alias_model_id`** — model to create or append to (must inherit `mail.thread`).
- **`alias_defaults`** — Python dict literal of values applied on creation (e.g. `{'project_id': 5}`).
- **`alias_force_thread_id`** — every mail appends to this one record; nothing is created.
- **`alias_contact`** — who may write ([`alias_contact`](../addons/mail/models/mail_alias.py#L73)):
  - `everyone` (default) — anyone.
  - `partners` — only senders matching a known `res.partner`.
  - `followers` — only followers of the related record.
- **`alias_bounced_content`** — custom HTML returned to rejected senders.

**Contact-policy enforcement** ([`_routing_check_route`](../addons/mail/models/mail_thread.py#L892) → [`_alias_get_error`](../addons/mail/models/models.py#L721)): a rejected mail is **bounced back to the sender, not silently dropped** ([`_alias_bounce_incoming_email`](../addons/mail/models/mail_alias.py#L512)). A *configuration* error (e.g. `followers` policy on an alias without a record) also sets `alias_status='invalid'`.

**Attaching an alias to a model** — `mail.alias.mixin` (alias required, [mixin](../addons/mail/models/mail_alias_mixin.py#L10)) or `mail.alias.mixin.optional` (created when a name is set, [mixin](../addons/mail/models/mail_alias_mixin_optional.py#L11)). Models override `_alias_get_creation_values` to set the target model and defaults:

- **project.project** → the alias creates `project.task` with `project_id` set ([project_project.py](../addons/project/models/project_project.py#L844)).
- **crm.team** → the alias creates `crm.lead` with `type` (lead/opportunity) and `team_id` ([crm_team.py](../addons/crm/models/crm_team.py#L171)).

**Name safety**: an alias cannot reuse its domain's bounce or catchall name ([`_check_alias_domain_clash`](../addons/mail/models/mail_alias.py#L204)), is unique per (name, domain) ([`_name_domain_unique`](../addons/mail/models/mail_alias.py#L96)), and is sanitized: lowercased, accents stripped, disallowed characters replaced by `-` ([`_sanitize_alias_name`](../addons/mail/models/mail_alias.py#L366)).

---

## 9. Bounces & Blacklist

The bounce address is static (`bounce@domain`); ids are not encoded into it. Odoo finds the original message from the Message-Id embedded in the delivery report (also `X-Microsoft-Original-Message-ID`), then from `In-Reply-To` / `References` ([`_get_bounced_message_data`](../addons/mail/models/mail_thread.py#L1987)).

**Detection** ([`_detect_is_bounce`](../addons/mail/models/mail_thread.py#L1008)): a `To` equal to any alias domain's `bounce_email`, OR a `mailer-daemon` sender, OR a `multipart/report` delivery-status content type.

**On bounce** ([`_routing_handle_bounce`](../addons/mail/models/mail_thread.py#L831)):
- `message_bounce` is incremented on every blacklist-enabled record with that address ([`_message_receive_bounce`](../addons/mail/models/mail_thread_blacklist.py#L97)). The base mixin **only counts; it does not blacklist.**
- The linked `mail.notification` rows get `failure_type='mail_bounce'` and status `bounce`.
- A *normal* email later received from the address **resets** its counter to 0 ([`_routing_reset_bounce`](../addons/mail/models/mail_thread.py#L993)).

**Auto-blacklist lives in `mass_mailing`**: 5 or more bounced traces within 13 weeks, spread over more than a week (and the partner counter at 5 or more, when a partner is known), add the address to `mail.blacklist` ([mass_mailing mail_thread.py](../addons/mass_mailing/models/mail_thread.py#L48)).

**`mail.blacklist`** ([mail_blacklist.py](../addons/mail/models/mail_blacklist.py)): normalized email + active flag, managed through `_add` / `_remove`; the `mail.thread.blacklist` mixin computes `is_blacklisted`. It is enforced **only in mass sending**: the composer in mass mode cancels blacklisted recipients with `failure_type='mail_bl'` unless **Use Exclusion List** is unticked ([`use_exclusion_list`](../addons/mail/wizard/mail_compose_message.py#L217), [`_process_mail_values_state`](../addons/mail/wizard/mail_compose_message.py#L1478)), and mass mailings do the same. Chatter posts and notifications ignore the blacklist.

---

## 10. Notifications — Who Gets an Email vs an In-App Message

- **`res.users.notification_type`** ([res_users.py](../addons/mail/models/res_users.py#L38)): `email` (default) or `inbox` (Discuss only). Users can change it on their own profile. It mirrors membership in `mail.group_mail_notification_type_inbox`. **Portal/shared users cannot be `inbox`** (DB constraint [`_notification_type`](../addons/mail/models/res_users.py#L89)).
- **Recipient classification** ([`_get_recipient_data`](../addons/mail/models/mail_followers.py#L91)): each recipient is `user` (internal), `portal` (share user) or `customer` (partner without user). Notification **groups** ([`_notify_get_recipients_groups`](../addons/mail/models/mail_thread.py#L4411)) then pick the layout: only internal users get the document access button by default; the `portal` and `follower` groups are inactive unless a module enables them, so those recipients fall into `customer`, which has no button.
- **Email branding** ([`mail_notification_layout`](../addons/mail/data/mail_templates_email_layouts.xml#L4)): the access button uses `company.email_secondary_color` (default `#875A7B`) as background and `email_primary_color` (`#FFFFFF`) for text; the footer carries the company details and "Powered by Odoo".

---

## 11. Where You Configure This in the UI

Settings → General Settings → **Emails** block ([res_config_settings_views.xml](../addons/mail/views/res_config_settings_views.xml#L36)):

| Setting | Effect |
|---|---|
| Use Custom Email Servers (`external_email_server_default`) | Shows the **Incoming / Outgoing Email Servers** buttons and the Gmail/Outlook toggles; also required for personal servers |
| Alias Domain (company-dependent, always visible) | The company's `mail.alias.domain` — drives catchall, bounce and default-from |
| Use a Gmail / Outlook Server | Installs `google_gmail` / `microsoft_outlook` for OAuth server authentication |
| Restrict Template Rendering | Only Mail Template Editors may create or edit dynamic templates (ICP `mail.restrict.template.rendering`) |

**Email Templates** (Button Text / Button Color, Update Mail Layout) sit in the company block of the same page ([view](../addons/mail/views/res_config_settings_views.xml#L177)).

Technical menus under Settings → Technical → Email: Emails, Outgoing Mail Servers, Incoming Mail Servers, Templates, and in developer mode Aliases, Alias Domains, Mail Gateway Allowed ([mail_menus.xml](../addons/mail/views/mail_menus.xml#L85)). The blacklist is under Settings → Technical → Discuss → Email Blacklist.

There is **no global notification setting**; it is per user (`notification_type`). DNS records are **not** generated in-product; the Alias Domain setting only links to the SPF documentation.

---

## 12. DNS / Deliverability (operational, not in-product)

For mail sent from your domain to arrive, configure at the DNS level (Odoo does not do this):

- **SPF** — authorize the sending IP / relay for your domain.
- **DKIM** — sign outgoing mail; the Reply-To 68-character guard (§4) exists so headers do not break DKIM verification.
- **DMARC** — the policy tying SPF and DKIM together.

Encapsulation (§3) exists to stay SPF/DKIM-aligned: Odoo sends *as* your authorized notifications address, not as the customer's address.

---

## 13. Key System Parameters

Mail documents its own ICPs in [mail ir_config_parameter.py](../addons/mail/models/ir_config_parameter.py#L11).

| ICP | Default | Effect |
|---|---|---|
| `mail.default.from_filter` | CLI `--from-filter` | Default `from_filter` when no database server is used |
| `mail.catchall.domain` / `mail.bounce.alias` / `mail.catchall.alias` / `mail.default.from` | — | Read once by the `mail` post-init hook to create the first alias domain (§1) |
| `mail.catchall.domain.allowed` | unset | Restricts local-part alias matching (`alias_incoming_local`) to the listed domains |
| `mail.mail.force.send.limit` | `100` | Below this, notifications send directly; `0` = always queue |
| `mail.mail.queue.batch.size` | `1000` | Mails per queue-cron run |
| `mail.session.batch.size` | `1000` | Mails per SMTP session |
| `mail.batch_size` | `50` | Mail *generation* batch size |
| `mail.server.personal.limit.minutes` | `30` | Emails per minute for personal servers |
| `mail.disable_personal_mail_servers` | unset | Force public servers only |
| `mail.gateway.loop.threshold` / `mail.gateway.loop.minutes` | `20` / `120` | Inbound loop detection |
| `mail.restrict.template.rendering` | unset | Restrict dynamic template editing (Settings toggle) |
| `mass_mailing.cancelled_mails_months_limit` | `6` | Months before cancelled `mail.mail` are purged; `0` disables |
| `base.default_max_email_size` | `20` (MB) | Size above which record attachments become download links |

---

## 14. Common Scenarios & Troubleshooting

| Symptom | Likely cause |
|---|---|
| Recipients see `notifications@yourdomain`, not the author | Normal — the author matched no server `from_filter`, so Odoo encapsulated (§3) |
| Recipients see your Gmail login address regardless of config | The Gmail relay rewrites `From` to the authenticated account; not an Odoo bug (§3) |
| Bounces never reach Odoo | The server's `from_filter` does not cover the bounce address, so the envelope sender is the From address (§3) |
| Replies do not thread onto the record | Catchall not configured or not fetched, or Reply-To overridden; check the alias domain and incoming server (§4, §7) |
| Emails sent straight to `catchall@…` bounce | By design: a message addressed only to catchall is bounced (§7) |
| Inbound email to `jobs@…` does nothing | No matching `mail.alias`, or `alias_contact` rejected the sender (who got a bounce) (§8) |
| An incoming email vanished from a POP mailbox | It failed processing; POP deletes handled messages even when processing fails (§6) |
| Address keeps getting blacklisted | 5+ bounces over 13 weeks via mass mailing (§9) — check the address is real |
| Emails stuck in "Outgoing" | Queue cron disabled, or the mails are in `exception` (no auto-retry) — check Settings → Technical → Emails (§5) |
| Attachments arrive as links | The estimated size exceeded `base.default_max_email_size` (§2) |
| A user gets no notification emails | Their `notification_type` is `inbox`, or they authored the message (authors are not notified) (§10) |

---

## Dependencies & Gotchas

- **Alias domain is the hub** — catchall, bounce and default-from all come from one record; companies only point at it.
- **`from_filter` with a full address matches only that address**, never its domain; use a bare domain for domain-wide authorization.
- **Reply-To = catchall, Return-Path = bounce** — two different addresses by design.
- **Owner vs target** — Reply-To uses the alias owner; record creation uses the alias target.
- **Bounces are matched through the embedded Message-Id**, not an encoded address.
- **Blacklist enforcement is mass sending only** — chatter posts and notifications ignore it.
- **Picking `ssl_strict` does not set port 465** — only plain `ssl` does.
- **Do not use a personal Gmail/Outlook mailbox as the company outgoing server** — it masks the author and is rate-limited.

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`azure_entra_sso.md`](azure_entra_sso.md) — Microsoft modules, including the Outlook OAuth used by mail servers
