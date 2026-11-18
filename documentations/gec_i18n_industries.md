# GEC Georgian Translations: Industries

> **Module:** `gec_i18n_industries` (+ `gec_i18n_pos_category`) | **Path:** [`custom_addons/gec_odoo_modules/gec_i18n_industries/`](../custom_addons/gec_odoo_modules/gec_i18n_industries/)

## What It Does & Why It Exists

Odoo's industry packages (Hotel, Spa Resort, Fitness, Hair Salon, Cleaning Services, Sports Facilities,
Property Management and the shared base data) are not installed like apps: Apps > Industries imports them
from a zip as data modules. Odoo then reads their translations only from that zip, so our Georgian files never
reach them through the normal translation loading of `gec_i18n_base`. This module ships one Georgian file per
package (`i18n_extra/<package>/ka_GE.po`) and applies it whenever a package is imported or upgraded and whenever
this module is installed or upgraded.

An import also copies things outside the reach of any translation file: the "Start here!" Knowledge article
(rendered once into a plain html body), buttons whose links carry this database's record ids, and, when started
from the Apps screen, demo bookings linked to a module that does not exist. The module repairs all three, so a new
database needs no manual step and an existing one only needs the module upgrade.

---

## The Big Picture — How It Works

```
Apps > Industries > Activate ──> import wizard > Install ──> _import_zipfile (active_* keys dropped)
                                                                  │
               for each package, in dependency order:  data + demo ──> _load_module_terms
                                                                  │        └─ our files, one package at a time
                                                                  │           + links rebased + articles + booking links
                                                                  └─ Odoo renders the "Start here!" article
                                                                     in the importing user's language
                                                         after the import: article re-rendered in Georgian
```

The same refresh (`_refresh_industries`) runs when `gec_i18n_industries` is installed or upgraded and from
**Settings > Translations > Apply Georgian Translations (GEC)**.

### Key Decision Points
- **One package at a time.** Several packages rename the same record: each industry calls Odoo's retail shop setup,
  which creates a new shop and moves the id `point_of_sale.pos_config_retail` onto it, then names it "Front Desk",
  "Thermes & Spa", "Fitness Center", ... A shared pass would keep only one of these names per record. Each shop is
  translated while it holds the id, and keeps that Georgian after the next industry takes the id.
- **Articles extended by hand are kept.** An article is re-rendered only while its tag structure still matches the
  template. Adding or removing a block keeps it out of later refreshes; editing text inside the existing blocks
  does not, so an upgrade replaces such text with our current translation.
- **Language of the article.** Odoo renders it in the importing user's language. We re-render it in Georgian (the
  user's language when it is one we ship, otherwise the first installed one), so an import done with an English
  interface still gives Georgian users a Georgian guide.

---

## When to Use It (and When Not To)

### This module is for:
- Every GEC database where industry packages are imported; it installs automatically with `gec_i18n_base` and
  `base_import_module`.
- Refreshing the Georgian after an update of the files: upgrade the module, nothing else.

### Use something else when:
- A record lost its id before it was ever translated (see Limitations): rename it in the form; no file can reach it.
- Texts of the core apps (Point of Sale, Sales, ...) are wrong: those live in the other `gec_i18n_*` areas.

---

## Real-World Scenarios

### Scenario 1: New client database, Hotel imported by a consultant with an English interface
**What they do:** Apps > Industries > Hotel > Activate > Install, with demo data.
**What happens:** our files are applied as each package loads; the shop links are matched to this database's ids;
Odoo renders the "Start here!" article in English and it is immediately re-rendered in Georgian; the demo bookings
carry no link to the Apps screen and open normally.

### Scenario 2: A translation update is deployed to an existing database
**What they do:** deploy the code, restart Odoo, upgrade `gec_i18n_industries` (and `gec_i18n_pos` if its files
changed).
**What happens:** all industry texts are re-applied; every "Start here!" article that still has the template's
structure is re-rendered with the new texts; booking links left by older imports are cleared.

### Scenario 3: A Georgian user sees English Point of Sale category paths
**What happens:** with `gec_i18n_pos_category` installed, lists, tags and pickers show the path built from the
translated names ("ბარი / სასმელები"), and typing a Georgian name finds the category.

---

## How Things Work Under the Hood

### Core Logic
- **`_refresh_industries()`** ([`ir_module.py:174`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L174))
  — the whole pass: files, articles, booking links. Called from `_load_module_terms` (at once when the registry is
  ready, otherwise from `_register_hook`), and from the settings button.
- **`_apply_per_package()`** ([`ir_module.py:158`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L158))
  — loads each package's file into its own `SourceCheckedImporter` and saves with `force_overwrite`. The importer
  drops a record translation whose English no longer matches, so a renamed shop is never given another package's name.
- **`_rebase_moved_terms()`** ([`ir_module.py:116`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L116))
  — industry data builds some links from record ids (`/shop/%(xmlid)d`,
  [`convert.py`](../odoo/tools/convert.py)), so the term in our file carries the ids of the database it was
  exported from and Odoo's exact term match skips it. When the text is identical, the translation is moved to the
  stored term and takes its attributes, using core's own rule for changed terms
  ([`translate.py:718-743`](../odoo/tools/translate.py#L718)).
- **`_render_welcome_articles()`** ([`ir_module.py:60`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L60))
  — Odoo writes the article body once, after loading translations
  ([`base_import_module/models/ir_module.py:305-317`](../addons/base_import_module/models/ir_module.py#L305)).
  The body is re-rendered when its tag structure equals the template's and it differs from the Georgian render,
  only in a language we ship a file for (activating another language never touches the articles).
- **`_import_zipfile()`** ([`ir_module.py:213`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L213))
  — drops `active_model`/`active_id`/`active_ids`. The Apps screen opens the import wizard with the remote
  module's negative id ([`action_plugin.js:1710`](../addons/web/static/src/webclient/actions/action_plugin.js#L1710)),
  and `calendar.event` copies both onto every booking
  ([`calendar_event.py:125-132`](../addons/calendar/models/calendar_event.py#L125)); opening such a booking fails
  ([`fields_reference.py:40`](../odoo/orm/fields_reference.py#L40)).
- **`_unlink_apps_links()`** ([`ir_module.py:96`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/ir_module.py#L96))
  — clears that link on bookings created by earlier imports. Writing only the link sends no invitation.
- **`action_gec_force_georgian()`** ([`res_lang.py:10`](../custom_addons/gec_odoo_modules/gec_i18n_industries/models/res_lang.py#L10))
  — the settings button of `gec_i18n_base` plus the industry pass.
- **`pos.category._compute_display_name()`** ([`gec_i18n_pos_category/models/pos_category.py:12`](../custom_addons/gec_odoo_modules/gec_i18n_pos_category/models/pos_category.py#L12))
  — Odoo shows `complete_name`, stored once in one language
  ([`pos_category.py:15,30`](../addons/point_of_sale/models/pos_category.py#L15)); the path is built from the
  translated names instead, as [`website_sale`](../addons/website_sale/models/product_public_category.py#L105)
  does for eCommerce categories. `_rec_names_search` adds `name`, and `_search_display_name`
  ([`pos_category.py:27`](../custom_addons/gec_odoo_modules/gec_i18n_pos_category/models/pos_category.py#L27))
  also matches the translated path exactly, so products exported in Georgian (category written as
  „მაღაზია / აღჭურვილობა“) import back ([`ir_fields.py:547`](../odoo/addons/base/models/ir_fields.py#L547)).

### JavaScript strings
`_get_imported_module_translations_for_webclient` adds the JavaScript entries of our files (gantt flags such as
„ადრეული ჩექ-ინი“) to the ones Odoo serves from the zip, so they need no upgrade step.

---

## Limitations

| Case | Why | What to do |
|---|---|---|
| A shop that lost its id before it was ever translated (horeca: "Front Desk", the older "Bar") | The retail and bar setup functions move the shared id to each new shop; a record without an id cannot be targeted, and matching by English name could undo a name chosen by the client | Rename it once in Point of Sale > Configuration > Point of Sale, in the Georgian interface |
| A "Start here!" article with added or removed blocks | Kept on purpose | Edit it by hand |
| Odoo core issues behind the repairs | `calendar_event.py:125-132` trusts `active_model`; `pos_category.py:30` stores one language; `pos_restaurant/models/pos_config.py:61` names the bar shop with an untranslated literal | Candidates for upstream reports |
