# gec_user_audit — code, security, quality and performance review

Reviewed: 2026-10-23. Module manifest version: `0.9.0`. Target: this workspace's Odoo 20 source.

**Assessment:** the module has a compact structure and useful integration tests, but its audit trail is incomplete and can be disabled by an ordinary RPC caller. Address the two P1 findings before relying on it to investigate financial changes or user activity. This review changes no runtime code.

Scope: all 16 Python files, 10 XML files, access CSV, manifest and README; relevant ORM, HTTP, authentication, export, pivot and session implementations in local Odoo. Review priorities: P1 = high, P2 = medium. No P0 issue was identified within this scope.

## Findings

| ID | Priority | Finding | Evidence |
| --- | --- | --- | --- |
| A01 | P1 | RPC context can disable auditing | Reproduced through `call_kw` |
| A02 | P1 | Editing existing document lines can leave no audit event | Reproduced with a purchase price change |
| A03 | P2 | Supported read paths are missing, including Odoo 20 pivots | Reproduced with two public methods |
| A04 | P2 | Changes to another language's translation disappear | Reproduced with a product name |
| A05 | P2 | Raw savepoint rollback leaves a false change in the audit buffer | Reproduced with a rolled-back phone edit |
| A06 | P2 | Record names bypass the access filtering applied to changes | Reproduced across two companies |
| A07 | P2 | Report date range uses UTC midnight instead of the user's local day | Reproduced with Asia/Tbilisi context |
| A08 | P2 | Relation diff is quadratic and resolves names it never displays | Code inspection plus isolated diff benchmark |

### A01 — Remove the client-controlled audit bypass

Location: [models/base.py:33](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:33).

`_gec_audit()` trusts `env.context['gec_user_audit_off']`. Odoo accepts arbitrary context from RPC callers: local `odoo/service/model.py::call_kw` applies the supplied context before invoking the method, and the JSON-2 controller also accepts it. A user who can perform an operation can silently suppress its audit entry without audit configuration access.

Reproduction: call `res.partner.create` normally and then with `kwargs={'context': {'gec_user_audit_off': True}}`. The first creation produced one event; the second created the record and produced zero events. The same guard controls write, unlink, read, export and import auditing.

Recommendation: remove this context switch from the trust boundary or replace it with a server-controlled mechanism that cannot be serialized through RPC. The module's own log writes already use `sudo()`, which the existing `env.su` check excludes; evaluate whether the switch is needed at all. Stripping it in only one controller would leave other RPC paths exposed.

Regression: ordinary internal user; create/write/unlink and enabled reads; each operation with the malicious context; assert that the expected audit entries still exist.

### A02 — Do not exclude document lines unless their changes are actually captured

Locations: [models/gec_user_audit_rule.py:16](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/gec_user_audit_rule.py:16), [models/base.py:51](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:51).

The default policy excludes `*.line` on the assumption that the parent logs the document's lines. However, the parent compares an x2many using only its sorted IDs. Updating a price, quantity, account or description on an existing line does not change those IDs. Readonly computed parent totals are also deliberately excluded from field comparisons.

Reproduction: create a purchase order containing a line priced at 10; write `order_line=[Command.update(line.id, {'price_unit': 999})]`. The price became 999 and **zero new audit events** were produced. Direct edits on the line are excluded too. This affects important default-excluded models such as `purchase.order.line` and `account.move.line`.

Recommendation: remove the broad `*.line` exclusion and control volume through explicit rules, or implement parent-aware child-field diffs before suppressing child events. Merely logging a generic parent event would establish that something changed but still lose the old and new financial values.

Regression: update and directly write an existing line; add/delete a line; change quantity, price and account; verify usable before/after values. The shipped purchase test checks adding a line, which changes membership and therefore misses this bug.

### A03 — Cover Odoo 20's other public read entry points

Locations: [models/base.py:205](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:205), [models/client_call.py:30](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/client_call.py:30).

The hooks cover `read`, `web_read`, `search_read`, `web_search_read`, `web_read_group` and `formatted_read_group`. They do not cover `formatted_read_grouping_sets`, `name_search` or several other public read methods. The exact entry-method comparison prevents a nested hooked method from compensating for a missing outer hook.

Reproduction with reads enabled: direct `read` returned data and produced one read event. `name_search` and `formatted_read_grouping_sets` each returned data and produced zero events. This is also a normal UI gap: the local Odoo 20 [pivot model](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/addons/web/static/src/views/pivot/pivot_model.js:938) calls `formattedReadGroupingSets`.

Recommendation: define the supported read surface explicitly and add hooks for the missing public entry points, starting with pivot grouping sets and name lookups. Preserve the distinction between client calls and internal ORM reads. Cover translation-dialog reads too: the controller marks `get_field_translations`, but there is no matching read hook.

Regression: HTTP and RPC coverage for each supported read entry point; a normal pivot load; assert one event per client call and no nested duplicates.

### A04 — Compare translated fields across the languages being changed

Locations: [models/base.py:55](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:55), [controllers/main.py:119](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/controllers/main.py:119).

For translated fields, `_gec_audit_value()` returns only the value in the current environment language. Core `update_field_translations()` can write a different language's value while leaving that displayed value unchanged. Marking the controller entry does not change the comparison.

Reproduction: with `lang='en_US'`, call `product.template.update_field_translations('name', {'fr_FR': 'Nom modifie par review'})`. The French name changed successfully and zero new audit events were produced.

Recommendation: capture old/new values for the language keys actually updated, using the local Odoo translation APIs, and include language codes in the logged changes. Avoid duplicate events when the translation operation invokes `write()`.

Regression: another-language update, deletion/fallback of a translation, and callable HTML translation behavior.

### A05 — Make audit buffering respect raw savepoint rollback

Location: [models/gec_user_audit_log.py:141](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/gec_user_audit_log.py:141).

`cr.precommit.data` holds the event list in Python memory. A normal flushing savepoint flushes/clears the relevant hooks, but `cr.savepoint(flush=False)` performs a SQL rollback without restoring that list. If a caller catches the failure and later commits the outer transaction, the rolled-back change can be recorded as successful.

Reproduction: inside `savepoint(flush=False)`, write phone 111 → 222, flush the ORM values, raise an exception, catch it outside and invalidate the ORM cache. The saved phone remained **111**, but flushing the audit buffer produced **Phone: 111 → 222**. This finding concerns raw savepoints; it does not claim that ordinary flushing savepoints or a full transaction rollback fail.

Recommendation: use transaction-backed event storage for business changes, or integrate buffering with savepoint lifecycle state. Immediate same-cursor log inserts respect SQL rollback naturally; assess their batching cost. Clearing the whole buffer on any savepoint failure would incorrectly lose valid outer-transaction events.

Regression: nested success and failure with both savepoint modes, caught exceptions, outer commit/rollback, and the separate-cursor failed-login path.

### A06 — Apply record visibility rules to stored names as well as changes

Locations: [models/base.py:181](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:181), [models/gec_user_audit_log.py:63](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/gec_user_audit_log.py:63), [models/gec_user_audit_log.py:85](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/gec_user_audit_log.py:85).

`res_name` is populated using `sudo().display_name` and remains a readable stored field. `_compute_changes_shown()` filters the changes based on the reader's access to the original record, but the log's name, computed display name and report Record column do not apply that filter. Audit logs have no company-based visibility restriction.

Reproduction: a permitted actor edits a partner belonging to another company. An audit reader with `base.group_system` and access only to the main company reads the log. `changes_shown` correctly says `changed (not readable by you)`, while `res_name` reveals `Confidential cross-company name`.

Recommendation: make the raw stored name restricted and expose a filtered presentation field, including in display names, exports and reports. Define an explicit policy for names of deleted records, where a current-record access check is no longer possible. If cross-company metadata visibility is intended for all audit readers, document that policy clearly instead of implying full record confidentiality.

Regression: unreadable company, model access denial, deleted records, list/form/export/PDF visibility, and record names derived from sensitive fields.

### A07 — Convert report date boundaries from the user's timezone to UTC

Location: [wizard/gec_user_audit_report_wizard.py:31](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/wizard/gec_user_audit_report_wizard.py:31).

The defaults use the user's local date, and datetime fields are displayed in local time, but `_domain()` constructs naive midnight values that Odoo treats as UTC. The report therefore covers a different day from the one the user selected.

Reproduction: with `tz='Asia/Tbilisi'` and both dates set to 2026-10-23, the domain is `[2026-10-23 00:00 UTC, 2026-10-24 00:00 UTC)`. The intended local-day bounds are `[2026-10-22 20:00 UTC, 2026-10-23 20:00 UTC)`. The current report omits the first four local hours and includes four hours of the following day.

Recommendation: construct midnight at the start date and at the next calendar day in the user's timezone, convert each to UTC, then remove timezone information for the Odoo domain. Calculate each boundary separately so daylight-saving transitions are handled correctly.

Regression: UTC, Asia/Tbilisi, a timezone with daylight-saving changes, and events immediately before/at both boundaries.

### A08 — Bound relation formatting work and replace tuple membership checks

Location: [models/base.py:79](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/custom_addons/extra_modules/gec_user_audit/models/base.py:79).

The x2many diff performs membership checks against tuples for every ID, making it O(n × m). It also resolves `display_name` for the union of all old/new IDs before identifying the differences, although only the first ten additions/removals are displayed. A single change to a large relation therefore triggers work for all unchanged members.

Isolated benchmark of the exact membership expressions, three runs averaged on this machine:

| IDs before/after | Current tuple checks | Set membership preserving output order |
| --- | ---: | ---: |
| 1,000 | 0.00420 s | 0.000027 s |
| 5,000 | 0.10558 s | 0.000164 s |
| 10,000 | 0.42634 s | 0.000274 s |

These timings measure only the Python diff, not total ORM/request latency. Result lists were checked for equality.

Recommendation: build old/new sets once, preserve ordering by iterating the original sequences, count all differences, and resolve names only for the IDs actually displayed. Batch those bounded lookups across the affected records. Apply the text length limit to related display names as well; the current relation branch bypasses `cut_texts()`.

Regression: unchanged large relations, one addition/removal, complete replacement, deterministic ordering, and the existing ten-item truncation behavior.

## Quality and operational observations

The implementation already does several things well:

- Restricts audit-log CRUD at the model access layer; ordinary audit readers receive read access only.
- Caches rule policy and decisions using the local Odoo cache mechanisms; the shipped tests exercise user-group invalidation.
- Avoids indiscriminate logging of internal ORM reads.
- Batches normal audit insertion on the transaction and deliberately separates rollback-surviving authentication events.
- Masks values of group-restricted fields and attachment tokens.
- Deletes retained logs in batches and cooperates with cron progress limits.
- Tests real HTTP paths, export, report rendering, authentication, idle termination and session revocation.

Additional improvements, separate from the confirmed defects:

1. **Measure query plans before adding indexes.** New-device email checks filter on user/event/IP/user-agent/date, while common log browsing filters by user/model/date and orders by ID. Inspect representative `EXPLAIN (ANALYZE, BUFFERS)` output before selecting composite indexes. Existing single-column indexes do not establish the best production index combination.
2. **Bound idle-session cron work.** `_cron_end_idle()` loads all candidate sessions, checks their files, builds all log events and revokes them in one invocation. Use batches and cron progress accounting for installations with many sessions. No large-session workload benchmark was performed in this review.
3. **Define authentication coverage precisely.** JSON-2 bearer authentication checks API keys directly in `ir.http`; second-factor validation has its own paths. These do not all pass through the overridden `_login()`. Non-stored inverse fields such as password are also outside the generic stored-field diff. Document the supported security events and add explicit hooks where required, without storing credentials.
4. **Define persistence failure policy.** Normal audit insertion errors propagate through precommit and can abort the business transaction, whereas separate writes catch errors and only warn. This difference should be deliberate and covered by tests and monitoring. Do not simply swallow normal insertion failures without a policy for losing audit evidence.
5. **Make defaults migration explicit.** The vendor-era settings heuristic infers intent from the stored exclusion list and presents reads as disabled, while runtime policy reads the existing parameter until settings are saved. A versioned migration and a clear migration notice would be easier to reason about than an inference during settings reads.
6. **State trust and coverage limits in the README.** `sudo()` activity is intentionally excluded; retention deletes history; only the first 20 record IDs are retained; only explicitly supported entry points are covered. Raw SQL writes are outside the ORM hooks. The result is an application activity log with these boundaries.

## Validation and evidence

- Created a new temporary database named `gec_user_audit_review_20261023_01`; installed this module and `purchase` so the optional product/purchase cases were exercised. Existing databases were not used for test mutations.
- Ran **all 37 named module tests**, including HTTP integration tests, successfully. Odoo's final run reported **0 failures / 0 errors across 39 test methods**, including two additional web test methods scheduled by the runner. Its module statistics include fixture work and therefore report a different count.
- Parsed all **16 Python files** with Python 3.12's AST parser and all **10 XML files** with lxml: passed.
- Executed separate rollback-only reproductions for A01–A07. For A06, a real permitted write generated the audit entry before reading it as the restricted reader.
- Measured the relation comparison expressions for A08; no production-scale throughput or full request-latency claim is made.
- Did not modify runtime source, access rules, views or shipped tests. No production database upgrade was performed.
- Removed the temporary review database and its runtime data after saving the evidence below.

Evidence files:

- [Odoo test log](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/output/gec_user_audit_review_20261023/test_run.log)
- [Rollback-only reproduction script](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/output/gec_user_audit_review_20261023/reproduce.py)
- [Captured reproduction results](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/output/gec_user_audit_review_20261023/reproduction_results.txt)
- [Reproduction startup log](/Users/datozhuzhunadze/Desktop/odoo_projects/odoo20/output/gec_user_audit_review_20261023/reproduction_run.log)

The reproduction script is intended to be piped into `odoo-bin shell` against a disposable database with this module and purchase installed. It prints `AUDIT_REPRO_RESULTS=...` and rolls back its changes. Use an explicit isolated database/configuration when rerunning it.

## Recommended implementation order

1. Remove the context bypass and restore document-line coverage; add regression tests for A01/A02.
2. Correct missing read paths, translation comparisons and raw-savepoint behavior.
3. Align name visibility and report timezone handling with the intended audit-reader policy.
4. Optimize relation formatting, then profile session cron, insertion volume, retention and representative log queries.
5. Run the complete existing suite plus new regressions after each group of changes; exercise multi-worker behavior and authentication extensions before deployment.
