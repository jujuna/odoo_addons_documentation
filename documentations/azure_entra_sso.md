# Azure / Microsoft Entra ID ↔ Odoo

> **Modules:** `auth_oauth`, `auth_signup`, `auth_ldap`, `auth_timeout`, `microsoft_account`, `microsoft_outlook`, `microsoft_calendar` | **Path:** [`addons/auth_oauth/`](../addons/auth_oauth/), [`addons/auth_signup/`](../addons/auth_signup/), [`addons/auth_ldap/`](../addons/auth_ldap/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

Odoo has **no Azure/Entra connector**. It has a generic OAuth2 login module (`auth_oauth`) and a generic LDAP module (`auth_ldap`). Entra ID is integrated by hand-configuring an `auth.oauth.provider` record with Microsoft's identity-platform endpoints. No Microsoft provider record ships — [`auth_oauth_data.xml`](../addons/auth_oauth/data/auth_oauth_data.xml#L4) seeds only Odoo.com, Facebook and Google. There is no SAML and no SCIM module in Community or Enterprise.

The practical consequence: **Entra becomes an authentication source, not a user-management source.** Odoo has no provisioning endpoint, no group-claim mapping and no deprovisioning hook. Access rights, activation and archiving of Odoo users stay in Odoo.

`microsoft_outlook` / `microsoft_calendar` use Microsoft OAuth for mail and calendar. They are unrelated to login and are covered at the bottom.

---

## The Big Picture — SSO Login Flow

```
User clicks "Sign in with Microsoft" on /web/login (or on a signup / reset-password page)
   -> Odoo builds the authorize URL with response_type=token          (implicit flow)
   -> Entra authenticates (password + MFA + Conditional Access)
   -> redirect to /auth_oauth/signin with #access_token=... in the URL fragment
   -> Odoo turns the fragment into a query string, calls the UserInfo URL with the token
   -> takes the subject (`sub`) -> looks up res.users by (oauth_provider_id, oauth_uid)
        MATCH    -> log in, store the access token on the user
        NO MATCH -> auth_signup.signup() -> invitation token? link : free signup? portal user : refused
```

The flow type matters. [`list_providers`](../addons/auth_oauth/controllers/main.py#L27) hardcodes [`response_type='token'`](../addons/auth_oauth/controllers/main.py#L36) — **implicit flow**, not authorization code + PKCE. Odoo never validates an `id_token` JWT (the `nonce` line is commented out). It takes the opaque access token and calls the provider's UserInfo endpoint ([`_auth_oauth_validate`](../addons/auth_oauth/models/res_users.py#L63)). It also does not check the token's audience; the check is only a comment in [`auth_oauth`](../addons/auth_oauth/models/res_users.py#L137).

The identity anchor is the subject claim — `sub`, falling back to `id` or `user_id` — stored on `res.users.oauth_uid`, unique per provider ([constraint](../addons/auth_oauth/models/res_users.py#L27)). Not the email. Change a user's UPN in Entra and the link survives; delete and recreate the Entra account and it breaks.

---

## Entra-Side Configuration

The Entra values below come from Microsoft's identity platform, not from Odoo source; confirm them against Microsoft's documentation for your tenant.

App registration in the Azure portal:

| Setting | Value |
|---|---|
| Redirect URI (platform: Web) | `https://<your-odoo>/auth_oauth/signin` |
| Authentication → Implicit grant | **Access tokens** checked |
| Supported account types | Single tenant (unless you genuinely need guests / multi-tenant) |
| API permissions | `openid`, `profile`, `email`, `User.Read` (delegated) |

Odoo-side provider record (Settings → General Settings → Integrations → OAuth Authentication → **OAuth Providers**, or Settings → Users & Companies → OAuth Providers in developer mode; model `auth.oauth.provider`, [fields](../addons/auth_oauth/models/auth_oauth.py#L13)):

| Field | Value |
|---|---|
| Provider name | `Microsoft Entra ID` |
| Client ID | Application (client) ID of the app registration |
| Authorization URL | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize` |
| Scope | `openid profile email` (the field default) |
| UserInfo URL | `https://graph.microsoft.com/oidc/userinfo` |
| Login button label (`body`, required) | `Sign in with Microsoft` |
| Allowed (`enabled`) | ticked |
| Icon (developer mode) | A Material Symbols name, default `login`; the shipped brand set has `oi_windows`, no Microsoft logo ([`icon`](../addons/auth_oauth/models/auth_oauth.py#L20)) |

**Required system parameter:** `auth_oauth.authorization_header` = `True`. [`_auth_oauth_rpc`](../addons/auth_oauth/models/res_users.py#L47) reads it as a boolean: `True`, `1`, `yes`, `on` send the token as `Authorization: Bearer`; anything else — missing, `False`, or an unparseable value (logged as a warning) — sends it as an `access_token` **query parameter**, which Microsoft's UserInfo endpoint does not accept [Unverified — Microsoft-side behavior]. This is the most common cause of a failing Entra login.

No client secret is used or stored — the implicit flow has no token exchange.

---

## What You Can and Cannot Control From Entra

### You genuinely control

| Capability | Where |
|---|---|
| Who may obtain a token at all | Enterprise application → Properties → **Assignment required = Yes**, then assign users/groups |
| MFA, device compliance, IP/location, risk | Conditional Access policies on that enterprise app |
| Password policy, rotation, self-service reset | Entra |
| Sign-in audit trail | Entra sign-in logs |
| Blocking future SSO logins | Disable/delete the Entra account — new tokens stop being issued |

### You do **not** control

| Gap | Reality |
|---|---|
| **Provisioning** | No SCIM endpoint; Entra "Automatic provisioning" cannot target Odoo. |
| **Group / role mapping** | Odoo groups are set only inside Odoo. No claim is read into groups. |
| **Deprovisioning** | Disabling the Entra account does not archive the Odoo user. |
| **Password fallback** | Local password login stays enabled; there is no "SSO only" setting. A user disabled in Entra can still log in with an Odoo password if one is set. |
| **Session revocation** | Revoking sessions in Entra does not end an existing Odoo session. `auth_timeout` bounds it (below). |

**The last pair is the security-relevant one.** SSO without removing local passwords gives the appearance of central control, not the substance.

### Bounding session lifetime with `auth_timeout`

`auth_timeout` adds two settings per user group, on the group form's Settings tab ([`res_groups.py`](../addons/auth_timeout/models/res_groups.py#L36)):

- **Logout every N minutes, hours or days** (`lock_timeout`) — forces a new login regardless of activity. A user disabled in Entra loses Odoo access at the next forced logout, provided they have no local password.
- **Lock screen after N of inactivity** (`lock_timeout_inactivity`) — asks for identity again.

Each can also require two-factor authentication.

---

## User Linking — the part that surprises people

[`_auth_oauth_signin`](../addons/auth_oauth/models/res_users.py#L105) matches **only** on `(oauth_provider_id, oauth_uid)`. It does not match on login or email. An existing internal user without `oauth_uid` is not recognised on the first Microsoft login.

On no match, it builds user values from UserInfo (`login` = `email` claim) and calls [`auth_signup.signup()`](../addons/auth_signup/models/res_users.py#L44):

- **With a signup token** (from an invitation or reset link) on a partner that already has a user → writes `oauth_provider_id` + `oauth_uid` onto that user. **This is the supported linking path.**
- **Without a token**, [`_signup_create_user`](../addons/auth_signup/models/res_users.py#L98) refuses unless free signup is on (`auth_signup.invitation_scope` = `b2c`). With `b2c` it refuses when any user (archived included) already has that email ([check](../addons/auth_signup/models/res_users.py#L107)); otherwise it copies the template portal user and creates a **portal** user — never an internal one.

**Free signup is the install default.** The Settings field **Customer Account** (General Settings → Permissions) defaults to *Free sign up* ([`auth_signup_uninvited`](../addons/auth_signup/models/res_config_settings.py#L13)), and the module data writes `b2c` on install ([data](../addons/auth_signup/data/ir_config_parameter_data.xml#L5)). Switch it to *On invitation* unless the portal is meant to be public.

Ways to put an internal Odoo user on Entra SSO:

1. Create the user in Odoo and send a token: **Send an Invitation Email** on the user form (new users), **Send Password Reset**, the admin-only **Copy Reset Password Link** ([`get_reset_password_link`](../addons/auth_signup/models/res_users.py#L162)), or the invitation from the employee form ([`action_send_invitation`](../addons/hr/models/hr_employee.py#L1269)). The user opens the link and clicks **Sign in with Microsoft** on that page; the token travels in the OAuth state.
2. Set **OAuth Provider** and **OAuth User ID** (the `sub` value UserInfo returns) directly on the user, in developer mode.

Invitation tokens expire after 144 hours, reset tokens after 4 hours (ICPs `auth_signup.signup.validity.hours` / `auth_signup.reset_password.validity.hours`, [res_partner.py](../addons/auth_signup/models/res_partner.py#L188)).

There is no self-service path where an Entra employee logs in and becomes an internal Odoo user.

### What the user sees when it fails

The `/auth_oauth/signin` controller maps failures to login-page messages ([`web_login`](../addons/auth_oauth/controllers/main.py#L70)):

| Message | Cause |
|---|---|
| "Access Denied" | UserInfo call failed — typically the missing `auth_oauth.authorization_header`, or implicit access tokens not enabled |
| "You do not have access to this database or your invitation has expired…" | Token valid, but no linked user and signup refused (no invitation, `b2b` scope, expired token, or email already used) |
| "Sign up is not allowed on this database." | `auth_signup` not installed |

---

## The LDAP Alternative — and why it usually isn't one

`auth_ldap` has what OAuth lacks: a **Template User** and **Create User** option ([`user`](../addons/auth_ldap/models/res_company_ldap.py#L67), [`create_user`](../addons/auth_ldap/models/res_company_ldap.py#L69)). The first successful bind for an unknown login creates an internal user copied from the template ([`_get_or_create_user`](../addons/auth_ldap/models/res_company_ldap.py#L222)) — real auto-provisioning with real groups. A password changed in Odoo is written to the directory's `userPassword` attribute with the bind account's credentials ([`_change_password`](../addons/auth_ldap/models/res_company_ldap.py#L251)).

The blocker: **Entra ID exposes no LDAP interface.** You would need either

- **Entra Domain Services** — a separate paid managed domain offering LDAPS, or
- on-premises AD reachable from the Odoo host over VPN / private link.

If either already exists, LDAP is the better fit for onboarding and worth evaluating. Otherwise it is a new paid dependency added purely for authentication, and Conditional Access / MFA do not apply to LDAP binds.

---

## Getting Real Control — what a custom module would need

Everything below is missing from stock Odoo. If "control Odoo users from Azure" is a hard requirement, this is the scope:

| Need | Implementation |
|---|---|
| Deprovisioning | Scheduled action calling Graph (`/users?$filter=accountEnabled eq false` or a delta query), archiving matched `res.users` by `oauth_uid` |
| Group → Odoo-group mapping | On login, read Graph `/me/memberOf`, map to `res.groups` through a config model, write `group_ids` |
| Auto-provision internal users | Override `_auth_oauth_signin` / `_generate_signup_values` to create from an internal template user instead of falling into `auth_signup` |
| SSO-only enforcement | Blank the password on SSO-linked users; keep one break-glass local admin |
| Authorization code + PKCE, id_token validation | Substantial override of the `auth_oauth` controller and model — the flow is implicit-only |

The pragmatic middle ground: OAuth login + Entra assignment-required + Conditional Access, passwords cleared on SSO users, one break-glass admin, *On invitation* signup, an `auth_timeout` forced logout, and a documented offboarding step (archive the Odoo user) in the HR leaver checklist.

---

## Unrelated Microsoft Integrations

| Module | What it does |
|---|---|
| `microsoft_account` | OAuth token plumbing used by `microsoft_calendar` |
| `microsoft_outlook` | OAuth authentication for incoming and outgoing mail servers and personal servers (replaces SMTP/IMAP passwords). Uses the Client ID / Secret from Settings; without them, Enterprise databases go through Odoo's IAP proxy ([mixin](../addons/microsoft_outlook/models/microsoft_outlook_mixin.py#L90)). Default endpoint is the multi-tenant `common` one, overridable with ICP `microsoft_outlook.endpoint` ([`_get_microsoft_endpoint`](../addons/microsoft_outlook/models/microsoft_outlook_mixin.py#L280)). See [`mail_configuration.md`](mail_configuration.md) |
| `microsoft_calendar` | Two-way calendar sync with Outlook / Microsoft 365 |
| `appointment_microsoft_calendar` (enterprise) | Availability lookup for the Appointments app |

None of these affect who can log into Odoo. They use their own app registration and consent.

Azure as **infrastructure** (VMs, PostgreSQL Flexible Server, Blob Storage for the filestore) is orthogonal — Odoo runs there like on any Linux host, with no Odoo module involved.

---

## Edge Cases & Gotchas

- **`auth_oauth.authorization_header` unset or not a boolean → login fails** with "Access Denied".
- **Implicit access tokens not enabled** on the app registration → Entra returns an error in the fragment; Odoo shows a generic failure.
- **Microsoft `sub` values are pairwise per application** [Unverified — Microsoft-side behavior]. Re-creating the app registration would issue new values and orphan every `oauth_uid`.
- **Deleting an Entra user does not end an active Odoo session** and does not touch the Odoo record.
- **Free signup (`b2c`) is on by default.** Combined with a multi-tenant app registration, any Microsoft account that can get a token could create an Odoo portal user.
- **The access token is stored** in `res.users.oauth_access_token` (`groups=NO_ACCESS`, [field](../addons/auth_oauth/models/res_users.py#L24)) and is part of the session-token hash ([`_get_session_token_fields`](../addons/auth_oauth/models/res_users.py#L169)) — clearing it invalidates that user's sessions.
- **The token also works as a credential**: `_check_credentials` accepts a stored OAuth token for interactive logins, or for RPC when the user is not restricted to API keys ([`_check_credentials`](../addons/auth_oauth/models/res_users.py#L152)).
- **Guest (B2B) accounts** authenticate but may return an `email` claim in an unexpected shape; check what UserInfo returns before relying on it as `login` [Unverified — Microsoft-side behavior].

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`mail_configuration.md`](mail_configuration.md) — Outlook OAuth mail servers and personal servers
