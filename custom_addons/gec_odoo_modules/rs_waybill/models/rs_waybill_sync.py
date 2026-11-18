from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta, datetime
from .rs_waybill_soap_service import TBILISI_TZ
from markupsafe import Markup
import json
import logging


_logger = logging.getLogger(__name__)


DRIFT_COMPLETED_DAYS = 15


class RsWaybillSync(models.Model):
    _inherit = 'rs.waybill'


    @api.model
    def _get_rs_sync_user(self, company):
        """ The RS Responsible User of `company`, whose login the crons use for it. Empty when the
            company has none: it is then skipped, never synced through another user's login. """
        user = self.env['res.users']._rs_responsible_user(company)
        if not user:
            _logger.warning("Company %s has no RS Responsible User — its waybills are not synced. "
                            "Set one in that user's Preferences.", company.display_name)
        return user


    @api.model
    def _rs_sync_contexts(self):
        """ (company, user) pairs a sync pass runs for: each RS.GE account covers ONE taxpayer, so one pass per company.
            With caller credentials (Fetch All): only that user and their active company. """
        if not hasattr(self.env['res.users'], '_rs_responsible_user'):
            _logger.error("rs_base_methods is not installed - RS.GE waybill sync skipped")
            return []

        if self.env.user.rs_username and self.env.user.rs_password:
            return [(self.env.company, self.env.user)]
        contexts = []
        for company in self._rs_sync_companies():
            tin = (company.vat or '').strip()
            if not tin:
                continue
            user = self._get_rs_sync_user(company=company)
            if user:
                contexts.append((company, user))
        if not contexts:
            _logger.error("No company has an RS Responsible User — sync skipped.")
        return contexts


    @api.model
    def _rs_sync_companies(self):
        """ Companies a sync may run for, with their RS responsible user's login: all for cron and administrators,
            else only the user's companies. Never a login of a company the user could not open. """
        companies = self.env['res.company'].sudo().search([])
        if self.env.su or self.env.context.get('cron_id') or self.env.user._is_system():
            return companies
        return companies & self.env.user.company_ids


    @api.model
    def _rs_company_tin_map(self):
        """ {tin: res.company} for every company with a TIN; classifies ownership for ALL sync entry points.
            Both TINs ours: seller path (internal, type 1); buyer TIN ours: buyer path (PO/receipt or return delivery);
            seller TIN ours: seller path (SO + delivery). """
        res = {}
        for c in self.env['res.company'].sudo().search([]):
            tin = (c.vat or '').strip()
            if tin:
                res.setdefault(tin, c)
        return res

    def _rs_seller_is_own_company(self):
        """ True when the SELLER is one of OUR companies (intercompany): the goods are our own products,
            so the buyer side must NOT run the external-barcode mapping or flag lines 'unresolved';
            they resolve directly by barcode. """
        self.ensure_one()
        tin = (self.seller_tin or '').strip()
        return bool(tin) and tin in self._rs_company_tin_map()


    def _rs_run_per_company(self, label, func, contexts=None, problems=None):
        """ Run `func(scoped_self)` once per credentialed company; one company's RS.GE failure must not stop the others.
            No savepoint: the per-row engine commits as it goes; on failure cr.rollback() goes to the last commit. """
        results = []
        for company, user in (self._rs_sync_contexts() if contexts is None else contexts):
            scoped = self.with_user(user).with_company(company)
            try:
                results.append(func(scoped))
            except Exception:
                self.env.cr.rollback()
                _logger.exception("%s failed for company %s — continuing with the others.",
                                  label, company.display_name)
                if problems is not None:
                    problems.append(_("%(company)s: %(label)s failed (see the server log).")
                                    % {'company': company.display_name, 'label': label})
        return results


    @api.model
    def action_sync_all(self):
        """ Fetch All (Settings): seller, buyer, transporter and template imports, then ONE message with results and
            failures. A company whose RS.GE login is refused is skipped and named. """
        problems = []
        contexts = []
        for company, user in self._rs_sync_contexts():
            ok = self.env['rs.waybill.soap.service'].with_user(user).with_company(company).rs_login_ok()
            if ok:
                contexts.append((company, user))
            elif ok is False:
                problems.append(_("%s: RS.GE refused the login. Check RS Username and RS "
                                  "Password in Preferences.") % company.display_name)
            else:
                problems.append(_("%s: RS.GE could not be reached.") % company.display_name)
        synced = {company for company, _user in contexts}
        if not (self.env.user.rs_username and self.env.user.rs_password):
            for company in self._rs_sync_companies().filtered('vat'):
                if company not in synced and not self._get_rs_sync_user(company):
                    problems.append(_("%s: no RS Responsible User, not synced.") % company.display_name)
        parts = [
            (_("Sent"), "Seller sync", lambda scoped: scoped._sync_seller_waybills_one()),
            (_("Received"), "Buyer sync", lambda scoped: scoped._sync_buyer_waybills_one()),
            (_("Transporter"), "Transporter sync", lambda scoped: scoped._sync_transporter_waybills_one()),
            (_("Templates"), "Template sync", lambda scoped: scoped._sync_templates_one()),
        ]
        lines = []
        for title, label, func in parts:
            totals = self._rs_run_per_company(label, func, contexts=contexts, problems=problems) if contexts else []
            created = sum(t[0] for t in totals)
            updated = sum(t[1] for t in totals)
            lines.append(_("%(title)s: %(created)s created, %(updated)s updated")
                         % {'title': title, 'created': created, 'updated': updated})
        waiting = sum(len(self._rs_retry_load(company)) for company in synced)
        if waiting:
            problems.append(_("%s waybills could not be imported; they are retried "
                              "automatically (see the server log).") % waiting)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Sync finished with problems") if problems else _("Sync complete"),
                'message': '\n'.join(lines + problems),
                'type': 'warning' if problems else 'success',
                'sticky': bool(problems),
                'className': 'o_rs_sync_notification',
            },
        }


    @api.model
    def action_sync_seller_waybills(self):
        """ One fetch per credentialed company (see _rs_sync_contexts). """
        totals = self._rs_run_per_company(
            "Seller sync", lambda scoped: scoped._sync_seller_waybills_one())
        return self._notify_sync_done(*(sum(t[i] for t in totals) for i in range(3)))


    def _sync_seller_waybills_one(self):
        """ Seller-side fetch for the ONE RS.GE account the current user carries. """
        service = self.env['rs.waybill.soap.service']
        rows = self._fetch_waybills_chunked(service.get_waybills, days_back=30, chunk_days=3)
        _logger.info("Got %s seller rows from RS.GE", len(rows))
        # As in _rs_company_tin_map: rows with our BUYER_TIN go to the buyer path, except self-to-self rows.
        # Each bundle runs under ITS company. get_waybills: only this login's outgoing rows, so seller = this company.
        tin_map = self._rs_company_tin_map()
        own_tin = (self.env.company.vat or '').strip()
        bundles, left_to_buyer, unmatched = {}, 0, 0
        for r in rows:
            s = (r.get('SELLER_TIN') or '').strip() or own_tin
            b = (r.get('BUYER_TIN') or '').strip()
            if s and s == b and s in tin_map:
                bundles.setdefault(tin_map[s], []).append(r)
            elif b in tin_map:
                left_to_buyer += 1
            elif s in tin_map:
                bundles.setdefault(tin_map[s], []).append(r)
            else:
                unmatched += 1
        if left_to_buyer:
            _logger.info("Seller sync: %s intercompany rows left to the buyer path", left_to_buyer)
        if unmatched:
            _logger.warning("Seller sync: %s rows match no company Tax ID in this database and "
                            "were skipped (fetched for %s, Tax ID %r).",
                            unmatched, self.env.company.display_name, own_tin)
        created = updated = skipped = 0
        for company, rows_ in bundles.items():
            c, u, sk = self.with_company(company)._process_rs_rows(rows_, 'seller', {
                'seller_tin': (company.vat or '').strip(),
                'seller_name': company.name or '',
            })
            created += c; updated += u; skipped += sk
        return created, updated, skipped


    @api.model
    def action_sync_buyer_waybills(self):
        totals = self._rs_run_per_company(
            "Buyer sync", lambda scoped: scoped._sync_buyer_waybills_one())
        return self._notify_sync_done(*(sum(t[i] for t in totals) for i in range(3)))


    def _sync_buyer_waybills_one(self):
        """ Buyer-side fetch for the ONE RS.GE account the current user carries. """
        service = self.env['rs.waybill.soap.service']
        rows = self._fetch_waybills_chunked(service.get_buyer_waybills, days_back=30, chunk_days=3)
        _logger.info("Got %s buyer rows from RS.GE", len(rows))
        # Mirror of the seller sync: self-to-self rows go to the SELLER path; others to the BUYER_TIN company.
        # get_buyer_waybills returns only the login's incoming waybills: a row without BUYER_TIN is this pass's company.
        tin_map = self._rs_company_tin_map()
        own_tin = (self.env.company.vat or '').strip()
        bundles, left_to_seller, unmatched = {}, 0, 0
        for r in rows:
            s = (r.get('SELLER_TIN') or '').strip()
            b = (r.get('BUYER_TIN') or '').strip() or own_tin
            if s and s == b and s in tin_map:
                left_to_seller += 1
            elif b in tin_map:
                bundles.setdefault(tin_map[b], []).append(r)
            else:
                unmatched += 1
        if left_to_seller:
            _logger.info("Buyer sync: %s self-to-self rows left to the seller path", left_to_seller)
        if unmatched:
            _logger.warning("Buyer sync: %s rows match no company Tax ID in this database and "
                            "were skipped (fetched for %s, Tax ID %r).",
                            unmatched, self.env.company.display_name, own_tin)
        created = updated = skipped = 0
        for company, rows_ in bundles.items():
            c, u, sk = self.with_company(company)._process_rs_rows(rows_, 'buyer', {
                'buyer_tin': (company.vat or '').strip(),
                'buyer_name': company.name or '',
            })
            created += c; updated += u; skipped += sk
        return created, updated, skipped


    @api.model
    def action_sync_transporter_waybills(self):
        totals = self._rs_run_per_company(
            "Transporter sync", lambda scoped: scoped._sync_transporter_waybills_one())
        return self._notify_sync_done(*(sum(t[i] for t in totals) for i in range(3)))


    def _sync_transporter_waybills_one(self):
        """ Carrier-side fetch for the ONE RS.GE account the current user carries. The transporter_*
            overrides stamp env.company, already set by the caller to the company owning these credentials. """
        service = self.env['rs.waybill.soap.service']
        # Unlike the seller/buyer fetches this is one un-chunked call: report an RS.GE fault and let
        # the next run retry, instead of taking the hourly cron down.
        try:
            rows = service.get_transporter_waybills()
        except Exception as ex:
            _logger.error("Transporter fetch failed for %s: %s", self.env.company.display_name, ex)
            return 0, 0, 0
        _logger.info("Got %s transporter rows from RS.GE", len(rows))
        cutoff = fields.Datetime.now() - timedelta(days=30)
        wanted_statuses = {'-2', '0', '1', '2', '8'}
        # A row where WE are also seller or buyer belongs to those paths (else a direction-mismatch warning each sync).
        # Keep only true third-party-carrier rows (neither TIN is ours).
        tin_map = self._rs_company_tin_map()
        filtered = []
        dropped_own = 0
        for row in rows:
            if (row.get('STATUS') or '').strip() not in wanted_statuses:
                continue
            if ((row.get('SELLER_TIN') or '').strip() in tin_map
                    or (row.get('BUYER_TIN') or '').strip() in tin_map):
                dropped_own += 1
                continue
            create_date_str = row.get('CREATE_DATE')
            if create_date_str:
                try:
                    if fields.Datetime.from_string(create_date_str.replace('T', ' ')) < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            filtered.append(row)
        if dropped_own:
            _logger.info("Transporter sync: %s rows owned by the seller/buyer paths skipped", dropped_own)

        return self._process_rs_rows(filtered, 'transporter', {
            'transporter_tin': self.env.company.vat or '',
            'transporter_name': self.env.company.name or '', })


    @api.model
    def _rs_last_sync_key(self, company):
        """ The incremental cursor is PER COMPANY: each company is fetched with its own RS.GE account, so a
            shared cursor would let company A's pass advance company B's window past rows it never saw. """
        return 'rs_waybill.last_v1_sync.%s' % company.id


    @api.model
    def _rs_get_last_sync(self, company):
        """ Reads the per-company cursor, falling back ONCE to the legacy shared key so an upgraded
            database resumes where it left off instead of re-fetching 30 days for every company. """
        ICP = self.env['ir.config_parameter'].sudo()
        return (ICP.get_str(self._rs_last_sync_key(company), '')
                or ICP.get_str('rs_waybill.last_v1_sync', ''))


    @api.model
    def _cron_sync_updated_waybills(self):
        """ One incremental pass per credentialed company (see _rs_sync_contexts). """
        self._rs_run_per_company(
            "Incremental sync", lambda scoped: scoped._cron_sync_updated_waybills_one())


    def _cron_sync_updated_waybills_one(self):
        ICP = self.env['ir.config_parameter'].sudo()
        # Not named `company`: the classification loops below bind that name per bundle, and the cursor
        # must be stamped for the company whose ACCOUNT did the fetching.
        sync_company = self.env.company
        self._rs_retry_failed_rows()
        cursor_key = self._rs_last_sync_key(sync_company)
        last_sync = self._rs_get_last_sync(sync_company)
        now_ge = datetime.now(TBILISI_TZ).replace(tzinfo=None)
        now_str = now_ge.strftime('%Y-%m-%dT%H:%M:%S')

        if not last_sync:
            _logger.info("no last_v1_sync for %s, running full sync instead",
                         sync_company.display_name)
            self._sync_seller_waybills_one()
            self._sync_buyer_waybills_one()
            ICP.set_str(cursor_key, now_str)
            return

        service = self.env['rs.waybill.soap.service']

        last_sync_dt = datetime.strptime(last_sync, '%Y-%m-%dT%H:%M:%S')

        # RS caps get_waybills_v1 at 3-day windows; loop through chunks
        all_rows = []
        seen_ids = set()
        any_chunk_failed = False
        for chunk_s, chunk_e in self._datetime_chunks(last_sync_dt, now_ge, chunk_days=3):
            try:
                chunk_rows = service.get_waybills_v1(
                    last_update_start=chunk_s,
                    last_update_end=chunk_e,
                )
                _logger.info("Chunk %s..%s: %s waybills", chunk_s, chunk_e, len(chunk_rows))
                for row in chunk_rows:
                    rid = row.get('ID')
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        all_rows.append(row)
            except Exception as e:
                _logger.error("get_waybills_v1 chunk %s..%s failed: %s", chunk_s, chunk_e, e)
                any_chunk_failed = True

        _logger.info("Total %s unique waybills across all chunks", len(all_rows))

        # Classify against the TINs of ALL companies, not the sync user's (else bogus seller SOs).
        # BUYER side wins for intercompany rows: Odoo-issued already exists as seller; portal-issued becomes buyer.
        tin_to_company = self._rs_company_tin_map()
        companies = self.env['res.company'].sudo().search([])

        buyer_bundles = {}
        seller_bundles = {}
        unmatched = 0
        for row in all_rows:
            seller_tin = (row.get('SELLER_TIN') or '').strip()
            buyer_tin = (row.get('BUYER_TIN') or '').strip()
            if seller_tin and seller_tin == buyer_tin and seller_tin in tin_to_company:
                # Self-to-self = internal transport (type 1). The SELLER path owns it: type 1 makes an internal
                # transfer (no SO) in _rs_create_documents_if_missing; the buyer path would create nothing.
                seller_bundles.setdefault(tin_to_company[seller_tin], []).append(row)
            elif buyer_tin in tin_to_company:
                buyer_bundles.setdefault(tin_to_company[buyer_tin], []).append(row)
            elif seller_tin in tin_to_company:
                seller_bundles.setdefault(tin_to_company[seller_tin], []).append(row)
            else:
                unmatched += 1

        _logger.info("Split: %s seller / %s buyer / %s unmatched (per-company: %s)",
                     sum(len(r) for r in seller_bundles.values()),
                     sum(len(r) for r in buyer_bundles.values()), unmatched,
                     {c.name: (len(buyer_bundles.get(c, [])), len(seller_bundles.get(c, [])))
                      for c in companies})

        for company, rows_ in seller_bundles.items():
            tin = (company.vat or '').strip()
            self.with_company(company)._process_rs_rows(rows_, 'seller', {
                'seller_tin': tin,
                'seller_name': company.name or '',
            })

        for company, rows_ in buyer_bundles.items():
            tin = (company.vat or '').strip()
            self.with_company(company)._process_rs_rows(rows_, 'buyer', {
                'buyer_tin': tin,
                'buyer_name': company.name or '',
            })

        # Advance this company's cursor only if every chunk succeeded; else the next run retries the
        # same window for it (and only for it).
        if not any_chunk_failed:
            ICP.set_str(cursor_key, now_str)
        else:
            _logger.warning("At least one chunk failed for %s; last_sync not advanced — "
                            "next run will retry", sync_company.display_name)


    def _process_rs_rows(self, rows, direction, company_overrides):
        digest = []
        self = self.with_context(rs_notify_digest=digest)
        service = self.env['rs.waybill.soap.service']
        rs_ids = [int(r.get('ID') or 0) for r in rows if r.get('ID')]
        if not rs_ids:
            return 0, 0, 0

        # sudo: must see EVERY company's waybills; the multi-company record rule would hide another
        # company's record, the row would look new and the unique index on rs_internal_id would reject it.
        existing_records = self.sudo().search([('rs_internal_id', 'in', rs_ids)])
        existing_map = {}
        for r in existing_records:
            try:
                key = int(r.rs_internal_id)
            except (ValueError, TypeError):
                key = r.rs_internal_id
            existing_map[key] = r

        _logger.info("_process_rs_rows: %d rows, %d existing found in Odoo for direction=%s",
                     len(rows), len(existing_map), direction)

        client, su, sp, history = service._get_client()
        created = updated = skipped = failed = 0
        failed_ids = []
        for row in rows:
            rs_id = int(row.get('ID') or 0)
            if not rs_id:
                continue
            known = existing_map.get(rs_id)
            if (known and known.state == 'cancelled' and known.rs_cancel_cascade != 'pending'
                    and str(row.get('STATUS') or '').strip() == '-2'):
                # Cancelled here and on RS.GE: it never changes again, so no download.
                # (Completed ones still can: Adjustment, cancel of a distribution.)
                skipped += 1
                continue
            try:
                header, goods = service.get_full_waybill_with_client(client, su, sp, history, rs_id)
                if not header:
                    _logger.warning("Could not fetch full waybill for rs_id=%s, skipping", rs_id)
                    skipped += 1
                    failed_ids.append(rs_id)
                    continue

                vals = self._map_rs_waybill_vals(header)
                vals.update(company_overrides)
                existing = existing_map.get(rs_id)
                if existing:
                    if existing.waybill_direction == 'transporter' and direction in ('seller', 'buyer'):
                        # The transporter feed carries no SELLER_TIN, so our own sale that we also carry can be stored
                        # there first. Seller or buyer outranks carrier.
                        _logger.info("rs_id=%s: direction transporter -> %s", rs_id, direction)
                        existing.waybill_direction = direction
                    elif existing.waybill_direction != direction:
                        if existing.buyer_tin and existing.buyer_tin == existing.seller_tin:
                            skipped += 1
                            continue
                        _logger.warning(
                            "rs_id=%s exists as direction=%s, sync requested direction=%s "
                            "(buyer_tin=%s, seller_tin=%s) — skipping to preserve unique constraint",
                            rs_id, existing.waybill_direction, direction,
                            existing.buyer_tin, existing.seller_tin)
                        skipped += 1
                        continue

                    changed = {}
                    for k, v in vals.items():
                        try:
                            current = existing[k]
                            if not current and not v:
                                continue
                            # Many2one: existing[k] is a recordset, vals an int id (`recordset == int` is always
                            # False): compare ids.
                            if hasattr(current, '_name') and hasattr(current, 'id'):
                                if current.id == (v or False):
                                    continue
                                changed[k] = v
                                continue
                            if hasattr(current, 'strftime') and isinstance(v, str):
                                if current.strftime('%Y-%m-%d %H:%M:%S') == v:
                                    continue
                            elif current == v:
                                continue
                            changed[k] = v
                        except Exception:
                            changed[k] = v

                    goods_changed = self._goods_lines_changed(existing, goods)

                    had_doc = bool(existing.picking_id or existing.purchase_id)
                    was_confirmed = existing.is_confirmed == '1'

                    if changed or goods_changed:
                        _logger.info("Updating waybill rs_id=%s (number=%s): %d fields changed: %s",
                                     rs_id, existing.rs_waybill_number, len(changed), list(changed.keys()))
                        if changed:
                            existing.with_context(rs_from_rs=True).write(changed)
                            if 'buyer_id' in changed:
                                existing._sync_buyer_to_so_and_picking()
                        if goods_changed:
                            # Push the RS goods change down only to docs that ALREADY existed; else the
                            # backfill below builds them from the current lines and a diff would double up.
                            goods_snapshot = existing._build_line_snapshot()
                            existing._sync_goods_lines(goods)
                            if had_doc and existing._in_integration_scope():
                                existing._apply_rs_goods_diff_auto(goods_snapshot)
                        try:
                            existing._send_notification_email()
                        except Exception as e:
                            _logger.warning("Email failed for rs_id=%s: %s", rs_id, e)
                        updated += 1
                    else:
                        skipped += 1

                    # Run REGARDLESS of field changes: an in-scope waybill without docs gets them now.
                    # Everything no-ops when already satisfied, so re-syncing never duplicates.
                    if existing._in_integration_scope():
                        if not had_doc and direction in ('buyer', 'seller'):
                            existing._rs_build_documents()
                        if existing.state == 'completed':
                            existing._cascade_validate_picking()
                        if existing.is_confirmed == '1':
                            # Wrapped: a receipt Odoo cannot book yet (PO awaiting approval) must not undo this sync.
                            existing._rs_post_commit(_("Validate the incoming receipt"),
                                                     existing._cascade_validate_receipt)
                        if existing.state == 'cancelled':
                            existing._cascade_cancel_purchase()
                            existing._cascade_cancel_delivery()
                        # Seller edit reset the buyer decision (is_confirmed left '1'): flag re-confirm and tell the
                        # buyer, even for non-goods edits.
                        if (existing.waybill_direction == 'buyer' and was_confirmed
                                and existing.is_confirmed != '1'
                                and not existing.is_buyer_reconfirm_needed):
                            existing.is_buyer_reconfirm_needed = True
                            existing.message_post(body=_(
                                "Seller edited this waybill on RS.GE — your previous Receive "
                                "was reset. Review the changes and click Receive again (or Reject)."))
                else:
                    _logger.info("Creating new waybill rs_id=%s (number=%s, direction=%s)",
                                 rs_id, vals.get('rs_waybill_number'), direction)
                    vals['rs_internal_id'] = rs_id
                    vals['waybill_direction'] = direction
                    record = self.create(vals)
                    record._sync_goods_lines(goods)
                    # Auto-wire documents: seller via the reverse-direction helper, buyer (2/3/4) via PO+receipt
                    # helpers. Both guard against double-creation; a failure does not abort the sync (retry via button).
                    if record.state != 'cancelled' and record._in_integration_scope():
                        if direction in ('buyer', 'seller'):
                            record._rs_build_documents()
                        # Synced type-1 carries only address strings; if they did not match our warehouses, tell the
                        # operator ONCE (at creation); the run-regardless backfill picks it up later.
                        if (record.waybill_type == '1' and not record.picking_id
                                and direction == 'seller'):
                            record.message_post(body=Markup(_(
                                "Internal-transport waybill synced from RS, but the start/end "
                                "addresses don't match any warehouse. Set <b>Source Warehouse</b> "
                                "and <b>Destination Warehouse</b> on this waybill — the internal "
                                "transfer will be created automatically on the next sync.")))
                        # A waybill can arrive ALREADY completed (or confirmed): run the same status cascades as the
                        # existing branch, so ONE pass fully settles it. Both helpers guard direction internally.
                        if record.state == 'completed':
                            record._cascade_validate_picking()
                        if record.is_confirmed == '1':
                            record._rs_post_commit(_("Validate the incoming receipt"),
                                                   record._cascade_validate_receipt)
                    try:
                        record._send_notification_email(action='New')
                    except Exception as e:
                        _logger.warning("Email failed for rs_id=%s: %s", rs_id, e)
                    created += 1
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception("Failed to sync waybill rs_id=%s", rs_id)
                failed += 1
                failed_ids.append(rs_id)
                continue

        _logger.info("Sync %s done: %s created, %s updated, %s skipped (unchanged), %s FAILED",
                     direction, created, updated, skipped, failed)
        if failed:
            _logger.error("Sync %s: %d waybills FAILED — RS IDs: %s. "
                          "Check the traceback entries above for individual causes.",
                          direction, failed, failed_ids)
        self._rs_track_failed_rows(direction, rs_ids, failed_ids)
        if digest:
            try:
                self.with_context(rs_notify_digest=None)._rs_send_notification_digest(digest)
            except Exception as e:
                _logger.warning("Sync summary email failed: %s", e)
        return created, updated, skipped


    @api.model
    def _rs_retry_key(self, company):
        return 'rs_waybill.retry_ids.%s' % company.id


    @api.model
    def _rs_retry_load(self, company):
        try:
            return json.loads(self.env['ir.config_parameter'].sudo().get_str(
                self._rs_retry_key(company), '') or '{}')
        except ValueError:
            return {}


    @api.model
    def _rs_retry_save(self, company, retry):
        self.env['ir.config_parameter'].sudo().set_str(
            self._rs_retry_key(company), json.dumps(retry) if retry else '')
        self.env.cr.commit()


    @api.model
    def _rs_track_failed_rows(self, direction, processed_ids, failed_ids):
        """ Remember the RS IDs that failed in this pass (per company and direction), forget those that went through,
            since the cursor moves on regardless and drift only checks waybills already in Odoo. """
        company = self.env.company
        retry = self._rs_retry_load(company)
        failed = {str(rid) for rid in failed_ids}
        changed = False
        for rid in processed_ids:
            if str(rid) not in failed and retry.pop(str(rid), None):
                changed = True
        for rid in failed:
            if rid not in retry:
                retry[rid] = {'direction': direction,
                              'since': fields.Datetime.to_string(fields.Datetime.now())}
                changed = True
        if changed:
            self._rs_retry_save(company, retry)


    @api.model
    def _rs_company_overrides(self, company, direction):
        """ The values a fetched row of `direction` gets from our own company. """
        tin, name = (company.vat or '').strip(), company.name or ''
        return {'seller': {'seller_tin': tin, 'seller_name': name},
                'buyer': {'buyer_tin': tin, 'buyer_name': name},
                'transporter': {'transporter_tin': tin, 'transporter_name': name}}[direction]


    @api.model
    def _rs_retry_failed_rows(self):
        """ Re-fetch by ID this company's waybills that failed earlier. One still failing after a day gets one
            activity for the company's RS Responsible User; after 30 days it is dropped and logged. """
        company = self.env.company
        retry = self._rs_retry_load(company)
        if not retry:
            return
        _logger.info("Retrying %s RS.GE waybills that failed before for %s",
                     len(retry), company.display_name)
        for direction in ('seller', 'buyer', 'transporter'):
            ids = [rid for rid, entry in retry.items() if entry.get('direction') == direction]
            if ids:
                self._process_rs_rows([{'ID': rid} for rid in ids], direction,
                                      self._rs_company_overrides(company, direction))
        retry = self._rs_retry_load(company)
        now = fields.Datetime.now()
        changed = False
        for rid, entry in list(retry.items()):
            age = now - (fields.Datetime.to_datetime(entry.get('since')) or now)
            if age > timedelta(days=30):
                _logger.error("RS.GE waybill %s (%s) still fails after 30 days: no longer retried.",
                              rid, entry.get('direction'))
                retry.pop(rid)
                changed = True
            elif age > timedelta(days=1) and not entry.get('alerted'):
                user = self._get_rs_sync_user(company)
                company.partner_id.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("RS.GE waybill %s could not be imported") % rid,
                    note=_("Waybill with RS ID %(rid)s (%(direction)s) has failed to import since "
                           "%(since)s. It is retried every sync; check the server log for the "
                           "cause, or fetch it again with Fetch All.")
                         % {'rid': rid, 'direction': entry.get('direction'), 'since': entry.get('since')},
                    user_id=(user or self.env.ref('base.user_admin')).id)
                entry['alerted'] = True
                changed = True
        if changed:
            self._rs_retry_save(company, retry)


    def _map_rs_waybill_vals(self, row):
        status_map = {
            '0': 'draft',
            '1': 'active',
            '2': 'completed',
            '8': 'draft',
            '-1': 'cancelled',
            '-2': 'cancelled',
        }
        rs_status = row.get('STATUS') or '0'

        def _sel(value, valid, default=False):
            v = (value or '').strip()
            return v if v in valid else default

        # RS datetimes are Georgian local time (Asia/Tbilisi, UTC+4): convert to UTC for storage, else they
        # display 4h ahead. Shared with the adjustment snapshots.
        _clean_dt = self.env['rs.waybill.soap.service'].rs_local_to_utc

        WAYBILL_TYPES = {'1', '2', '3', '4', '5', '6'}
        TRANSPORT_TYPES = {'1', '2', '3', '4', '6', '7', '8'}
        COST_PAYERS = {'1', '2'}
        CATEGORIES = {'0', '1'}
        MEDICINE = {'0', '1'}
        CONFIRMED = {'0', '1', '2', '-1'}

        vals = {
            'rs_waybill_number': row.get('WAYBILL_NUMBER', ''),
            'waybill_status': rs_status,
            'state': status_map.get(rs_status, 'draft'),
            'waybill_type': _sel(row.get('TYPE'), WAYBILL_TYPES),
            'buyer_tin': row.get('BUYER_TIN', ''),
            'buyer_name': row.get('BUYER_NAME', ''),
            'seller_tin': row.get('SELLER_TIN', ''),
            'seller_name': row.get('SELLER_NAME', ''),
            'driver_tin': row.get('DRIVER_TIN', ''),
            'driver_name': (row.get('DRIVER_NAME') or '').strip(),
            'car_number': row.get('CAR_NUMBER', ''),
            # RS.GE's address is the truth (it may be another warehouse); the company street is only the
            # fallback for a waybill RS sends without one.
            'start_address': (row.get('START_ADDRESS') or '').strip()
                             or (self.company_id or self.env.company).street or '',
            'end_address': row.get('END_ADDRESS', ''),
            'transport_type': _sel(row.get('TRANS_ID'), TRANSPORT_TYPES),
            'comment': row.get('COMMENT', ''),
            'is_confirmed': _sel(row.get('IS_CONFIRMED'), CONFIRMED, default='0'),
            'is_medicine': _sel(row.get('IS_MED'), MEDICINE, default='0'),
            'category': _sel(row.get('CATEGORY'), CATEGORIES, default='0'),
            'transport_cost_payer': _sel(row.get('TRAN_COST_PAYER'), COST_PAYERS),
            'reception_info': row.get('RECEPTION_INFO', ''),
            'receiver_info': row.get('RECEIVER_INFO', ''),
            'other_transport': row.get('TRANS_TXT', ''),
            's_user_id': row.get('S_USER_ID', ''),
        }

        cost = row.get('TRANSPORT_COAST')
        if cost:
            try:
                vals['transport_cost'] = float(cost)
            except (ValueError, TypeError):
                pass

        activate = _clean_dt(row.get('ACTIVATE_DATE'))
        if activate:
            vals['activation_date'] = activate

        begin = _clean_dt(row.get('BEGIN_DATE'))
        if begin:
            vals['transport_start_date'] = begin

        delivery = _clean_dt(row.get('DELIVERY_DATE'))
        if delivery:
            vals['delivery_date'] = delivery

        # RS sets CLOSE_DATE on ANY close, normal completion included, so it is not a cancellation date;
        # cancel_date is written only by action_refuse_waybill.
        close = _clean_dt(row.get('CLOSE_DATE'))
        if close:
            vals['close_date'] = close

        buyer_tin = (row.get('BUYER_TIN') or '').strip()
        if buyer_tin:
            partner = self.env['res.partner'].search([('vat', '=', buyer_tin)], limit=1)
            if partner:
                vals['buyer_id'] = partner.id

        # Carrier (transport_type 7): RS sends TRANSPORTER_TIN in the full waybill. Set only when present,
        # never overwrite with '' (the transporter sync stamps these via overrides).
        transporter_tin = (row.get('TRANSPORTER_TIN') or '').strip()
        if transporter_tin:
            vals['transporter_tin'] = transporter_tin
            tp = self.env['res.partner'].search([('vat', '=', transporter_tin)], limit=1)
            if tp:
                vals['transporter_name'] = tp.name

        return vals


    def _goods_lines_changed(self, record, goods):
        """ True when the RS goods differ from the waybill lines in anything the sync writes: product
            (barcode), name, quantity, price, VAT type or unit. A name fixed on RS.GE counts too. """
        if record.rs_adjustment_error:
            # An Adjustment RS.GE refused waits in the lines: RS.GE's goods wait too.
            return False
        if len(record.line_ids) != len(goods):
            return True
        matched = record._rs_match_goods_lines(goods)
        if len(matched) != len(goods):
            return True
        for index, item in enumerate(goods):
            line = matched[index]
            if ((line.bar_code or '') != (item.get('BAR_CODE') or '').strip()
                    or (line.name or '') != ((item.get('W_NAME') or '').strip() or 'Unknown')
                    or line.quantity != float(item.get('QUANTITY') or 0)
                    or line.unit_price != float(item.get('PRICE') or 0)
                    or (line.vat_type or '0') != (item.get('VAT_TYPE') or '0')
                    or (line.unit_name or '') != (item.get('UNIT_TXT') or '')):
                return True
            # Unit code: only once known on both sides (lines from before it was stored learn it on the next sync).
            rs_code = self._rs_item_unit_code(item)
            if rs_code and line.rs_unit_code and rs_code != line.rs_unit_code:
                return True
        return False


    @api.model
    def _rs_item_unit_code(self, item):
        """ UNIT_ID of an RS.GE goods item as an int, 0 when missing or unreadable. """
        try:
            return int(item.get('UNIT_ID') or 0)
        except (ValueError, TypeError):
            return 0


    def _rs_match_goods_lines(self, goods):
        """ {item index: line} pairing RS goods items with waybill lines, strongest first: RS line ID + same barcode;
            barcode + name; barcode alone for a line without RS ID. Another barcode on the same RS line: no match. """
        self.ensure_one()
        matched = {}
        used = set()

        def norm(item):
            return ((item.get('BAR_CODE') or '').strip(),
                    (item.get('W_NAME') or '').strip() or 'Unknown',
                    str(item.get('ID') or '').strip())

        passes = [
            lambda line, bar_code, name, rs_id: (rs_id not in ('', '0')
                                                 and (line.rs_good_id or '') == rs_id
                                                 and (line.bar_code or '') == bar_code),
            lambda line, bar_code, name, rs_id: ((line.bar_code or '') == bar_code
                                                 and (line.name or '') == name),
            lambda line, bar_code, name, rs_id: (bar_code and (line.bar_code or '') == bar_code
                                                 and (line.rs_good_id or '') in ('', '0')),
        ]
        for matches in passes:
            for index, item in enumerate(goods):
                if index in matched:
                    continue
                bar_code, name, rs_id = norm(item)
                for line in self.line_ids:
                    if line.id not in used and matches(line, bar_code, name, rs_id):
                        matched[index] = line
                        used.add(line.id)
                        break
        return matched


    def _sync_goods_lines(self, goods):
        """Sync goods lines from RS.GE: diff existing, add new, remove unmatched. Buyer waybills past the cutoff:
        new lines resolved via _resolve_product; unresolved ones get unresolved=True for UI mapping."""
        self.ensure_one()
        if self.rs_adjustment_error:
            # Keep the user's unsent Adjustment; Submit again or Discard settles it.
            return

        use_mapping = (
                self.waybill_direction == 'buyer'
                and self._mapping_enabled()
                and not self._rs_seller_is_own_company()
        )
        seller_partner = self._get_seller_partner() if use_mapping else self.env['res.partner']

        pairs = self._rs_match_goods_lines(goods)

        matched_ids = set()
        for index, item in enumerate(goods):
            bar_code = (item.get('BAR_CODE') or '').strip()
            goods_name = (item.get('W_NAME') or '').strip() or 'Unknown'

            try:
                qty = float(item.get('QUANTITY') or 0)
            except (ValueError, TypeError):
                qty = 0.0
            try:
                price = float(item.get('PRICE') or 0)
            except (ValueError, TypeError):
                price = 0.0
            try:
                qty_ext = float(item.get('QUANTITY_EXT') or 0)
            except (ValueError, TypeError):
                qty_ext = 0.0

            existing_line = pairs.get(index)

            if existing_line:
                matched_ids.add(existing_line.id)
                changed = {}
                if existing_line.name != goods_name:
                    changed['name'] = goods_name
                if existing_line.quantity != qty:
                    changed['quantity'] = qty
                if existing_line.unit_price != price:
                    changed['unit_price'] = price
                if existing_line.rs_good_id != (item.get('ID') or ''):
                    changed['rs_good_id'] = item.get('ID', '')
                if existing_line.unit_name != (item.get('UNIT_TXT') or ''):
                    changed['unit_name'] = item.get('UNIT_TXT', '')
                if existing_line.vat_type != (item.get('VAT_TYPE') or '0'):
                    changed['vat_type'] = item.get('VAT_TYPE', '0')
                if existing_line.extra_quantity != qty_ext:
                    changed['extra_quantity'] = qty_ext
                rs_code = self._rs_item_unit_code(item)
                if rs_code and rs_code != existing_line.rs_unit_code:
                    changed['rs_unit_code'] = rs_code
                    # A real change of unit on RS.GE (not a line learning its code): the Odoo unit follows.
                    if existing_line.rs_unit_code:
                        uom, review = existing_line._rs_match_uom(
                            existing_line.product_id, rs_code, item.get('UNIT_TXT') or '')
                        changed.update(uom_id=uom.id, uom_review=review)
                if changed:
                    existing_line.write(changed)
            else:
                if use_mapping:
                    product = self._resolve_product(bar_code, seller_partner)
                    unresolved = not product
                else:
                    product = self.env['product.product'].search(
                        ['|', ('barcode', '=', bar_code), ('default_code', '=', bar_code)],
                        limit=1
                    ) if bar_code else self.env['product.product']
                    if not product:
                        product = self.env['product.product'].search(
                            [('name', '=', goods_name)], limit=1
                        )
                    if not product:
                        uom = self.env['uom.uom']._rs_uom_by_code().get(self._rs_item_unit_code(item))
                        # RS identifies goods by BARCODE: write the code there (not default_code), consistent with
                        # the product import, so the product can be pushed to / matched on RS.
                        product = self.env['product.product'].create({
                            'name': goods_name,
                            'barcode': bar_code,
                            'is_rs_product': True,
                            'is_storable': True,
                            'uom_id': uom.id if uom else self.env.ref('uom.product_uom_unit').id,
                        })
                    unresolved = False

                rs_code = self._rs_item_unit_code(item)
                uom, review = self.env['rs.waybill.line']._rs_match_uom(product, rs_code, item.get('UNIT_TXT') or '')
                if review and use_mapping and product:
                    # The unit picked last time for this seller's barcode and unit code.
                    ref = self._rs_product_ref(bar_code, seller_partner)
                    if (ref.rs_unit_code == rs_code
                            and ref.uom_id and ref.uom_id in (product.uom_id | product.uom_ids)):
                        uom, review = ref.uom_id, False
                new_line = self.env['rs.waybill.line'].create({
                    'rs_waybill_id': self.id,
                    'rs_good_id': item.get('ID', ''),
                    'product_id': product.id if product else False,
                    'name': goods_name,
                    'unit_name': item.get('UNIT_TXT', ''),
                    'uom_id': uom.id,
                    'rs_unit_code': rs_code,
                    'uom_review': review,
                    'quantity': qty,
                    'unit_price': price,
                    'bar_code': bar_code,
                    'vat_type': item.get('VAT_TYPE', '0'),
                    'extra_quantity': qty_ext,
                    'external_barcode': bar_code if use_mapping else False,
                    'external_name': goods_name if use_mapping else False,
                    'unresolved': unresolved,
                })
                matched_ids.add(new_line.id)

        to_remove = self.line_ids.filtered(lambda l: l.id not in matched_ids)
        if to_remove:
            to_remove.unlink()


    def _sync_rs_good_ids(self, goods_response):
        """Map RS-returned goods IDs from save_waybill back to local lines, else every later edit sends
        ID=0 and RS duplicates the products. RS returns goods in request order, so pair by index."""
        self.ensure_one()
        lines = self.line_ids.sorted('sequence')
        for line, g in zip(lines, goods_response):
            rs_id = (g.get('id') or '').strip()
            if rs_id and rs_id != '0':
                line.rs_good_id = rs_id
        # What RS.GE now holds after our save: the drift check compares against it. A buyer never sends goods.
        if self.waybill_direction == 'buyer':
            return
        for line in self.line_ids:
            unit_id, unit_txt = line._rs_send_unit()
            if line.rs_unit_code != unit_id or line.unit_name != unit_txt:
                line.write({'rs_unit_code': unit_id, 'unit_name': unit_txt})


    def _date_chunks(self, start_date, end_date, chunk_days=3):
        """Yield ('YYYY-MM-DD', 'YYYY-MM-DD') pairs covering [start, end]."""
        cur = start_date
        while cur < end_date:
            nxt = min(cur + timedelta(days=chunk_days), end_date)
            yield cur.strftime('%Y-%m-%d'), nxt.strftime('%Y-%m-%d')
            cur = nxt


    def _datetime_chunks(self, start_dt, end_dt, chunk_days=3):
        """Yield ('YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DDTHH:MM:SS') pairs covering [start, end], each at
        most chunk_days long (RS.GE's get_waybills_v1 caps requests at 3 days)."""
        cur = start_dt
        while cur < end_dt:
            nxt = min(cur + timedelta(days=chunk_days), end_dt)
            yield cur.strftime('%Y-%m-%dT%H:%M:%S'), nxt.strftime('%Y-%m-%dT%H:%M:%S')
            cur = nxt


    def _fetch_waybills_chunked(self, fetch_fn, days_back=30, chunk_days=3, **kwargs):
        today = fields.Date.today()
        start = today - timedelta(days=days_back)
        end = today + timedelta(days=2)  # include today's waybills
        seen = set()
        all_rows = []
        failed_chunks = 0
        for s, e in self._date_chunks(start, end, chunk_days=chunk_days):
            # Per-chunk guard, like the incremental cron: one RS.GE fault must not discard the chunks already fetched.
            try:
                chunk = fetch_fn(start_date=s, end_date=e, **kwargs)
            except Exception as ex:
                failed_chunks += 1
                _logger.error("Fetch chunk %s..%s failed: %s", s, e, ex)
                continue
            _logger.info("Chunk %s to %s: %s rows", s, e, len(chunk))
            for row in chunk:
                rid = row.get('ID')
                if rid and rid not in seen:
                    seen.add(rid)
                    all_rows.append(row)
        if failed_chunks:
            _logger.warning("%d of the fetch windows failed; syncing the %d rows that did "
                            "arrive. The next run re-covers the same 30 days.",
                            failed_chunks, len(all_rows))
        return all_rows


    @api.model
    def action_sync_templates(self):
        """Fetch all templates from RS.GE with full details and mirror them locally. Templates live inside
        an RS.GE account, so this runs once per credentialed company (see _rs_sync_contexts)."""
        totals = self._rs_run_per_company(
            "Template sync", lambda scoped: scoped._sync_templates_one())
        return self._notify_sync_done(*(sum(t[i] for t in totals) for i in range(2)))


    def _sync_templates_one(self):
        service = self.env['rs.waybill.soap.service']
        rows = service.get_waybill_templates() or []
        _logger.info("Got %s templates from RS.GE", len(rows))
        if not rows:
            return 0, 0

        tpl_ids = [int(r.get('ID')) for r in rows if r.get('ID')]
        existing_map = {r.rs_template_id: r for r in self.search([('rs_template_id', 'in', tpl_ids), ('is_template', '=', True), ])}
        client, su, sp, _history = service._get_client()
        created = updated = failed = 0
        failed_ids = []
        for row in rows:
            tpl_id = int(row.get('ID') or 0)
            if not tpl_id:
                continue
            # One template per iteration, committed on success (like _process_rs_rows): one malformed
            # template must not abort the run and discard those already processed.
            try:
                try:
                    resp = client.service.get_waybill_tamplate(su=su, sp=sp, id=tpl_id)
                    waybill_elem = resp.waybill_tamplate._value_1
                except Exception as e:
                    _logger.warning("Failed to fetch template %s: %s", tpl_id, e)
                    continue
                if waybill_elem is None:
                    continue

                vals = self._map_rs_waybill_vals_from_template(waybill_elem)
                vals['is_template'] = True
                vals['rs_template_id'] = tpl_id
                vals['template_name'] = row.get('NAME') or f"Template {tpl_id}"
                vals['waybill_direction'] = 'seller'
                goods = self._template_to_goods(waybill_elem)
                existing = existing_map.get(tpl_id)
                if existing:
                    existing.write(vals)
                    existing._sync_goods_lines(goods)
                    updated += 1
                else:
                    record = self.create(vals)
                    record._sync_goods_lines(goods)
                    created += 1
                self.env.cr.commit()
            except Exception:
                self.env.cr.rollback()
                _logger.exception("Failed to sync template %s", tpl_id)
                failed += 1
                failed_ids.append(tpl_id)
                continue

        _logger.info("Template sync: %s created, %s updated, %s FAILED", created, updated, failed)
        if failed:
            _logger.error("Template sync: %d template(s) FAILED — RS IDs: %s. "
                          "Check the traceback entries above for individual causes.",
                          failed, failed_ids)
        return created, updated


    def action_save_as_template(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Save as Template'),
            'res_model': 'rs.waybill.template.save.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_waybill_id': self.id},
        }


    def action_create_from_template(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create from Template'),
            'res_model': 'rs.waybill.template.picker.wizard',
            'view_mode': 'form',
            'target': 'new',
        }


    def action_delete_template(self):
        self.ensure_one()
        if not self.is_template or not self.rs_template_id:
            raise UserError(_("Not a saved RS template."))
        service = self._rs_service()
        service.delete_waybill_template(self.rs_template_id)
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}


    def _map_rs_waybill_vals_from_template(self, waybill_elem):
        """Map RS template <WAYBILL> element to rs.waybill create-vals."""
        row = self._template_to_row(waybill_elem)
        vals = self._map_rs_waybill_vals(row)
        for key in ('rs_internal_id', 'waybill_number', 'waybill_status',
                    'activation_date', 'cancel_date', 'close_date', 'delivery_date'):
            vals.pop(key, None)
        return vals


    def _template_to_row(self, waybill_elem):
        """Extract direct-child fields from a <WAYBILL> element into a flat dict."""
        if waybill_elem is None or not hasattr(waybill_elem, 'tag'):
            return {}
        result = {}
        for child in waybill_elem:
            if child.tag in ('GOODS_LIST', 'SUB_WAYBILLS', 'CorrectedWaybills',
                             'WOOD_DOCS_LIST', 'WOOD_LABELS'):
                continue
            text = ''.join(child.itertext()).strip()
            if text:
                result[child.tag] = text

        return result


    def _template_to_goods(self, waybill_elem):
        """Extract GOODS items as list of dicts from a <WAYBILL> element."""
        if waybill_elem is None or not hasattr(waybill_elem, 'tag'):
            return []
        goods = []
        goods_list = waybill_elem.find('GOODS_LIST')
        if goods_list is None:
            return []
        for good in goods_list.findall('GOODS'):
            item = {}
            for field in good:
                if field.text is not None:
                    item[field.tag] = field.text
            goods.append(item)
        return goods


    def _sync_driver_name_to_partner(self):
        """ If the linked partner's TIN matches the waybill's driver_tin but the names differ, update the
            partner's name to driver_name (same TIN = same person). Skipped when the operator set rs_name_locked. """
        self.ensure_one()
        if not self.driver_partner_id or not self.driver_tin or not self.driver_name:
            return
        partner = self.driver_partner_id
        if partner.rs_name_locked:
            return
        if partner.vat == self.driver_tin and partner.name != self.driver_name:
            _logger.info(
                "Driver name updated for TIN %s: %r → %r",
                self.driver_tin, partner.name, self.driver_name,
            )
            partner.name = self.driver_name


    def _notify_sync_done(self, created, updated, skipped=0):
            msg = f'{created} created, {updated} updated'
            if skipped:
                msg += f', {skipped} skipped (unchanged)'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sync Complete',
                    'message': msg + '.',
                    'type': 'success',
                    'sticky': False,
                }
            }


    @api.model
    def _cron_rs_drift_repair(self):
        """ Walk non-terminal waybills; RS is the source of truth: repair Odoo on drift in any mappable field or line.
            One pass per credentialed company: a waybill is visible only through its own company's RS.GE account. """
        self._rs_run_per_company(
            "Drift repair", lambda scoped: scoped._cron_rs_drift_repair_one())


    def _rs_claim_company(self, header, company):
        """ A waybill without a company (pre-dating the field) is seen by every company: if this company's RS.GE
            account reads it and a party has its tax ID, store it so no documents are built elsewhere. Never raises. """
        self.ensure_one()
        tin = (company.vat or '').strip()
        parties = {(header.get(key) or '').strip()
                   for key in ('SELLER_TIN', 'BUYER_TIN', 'TRANSPORTER_TIN')}
        if not tin or tin not in parties:
            return
        try:
            with self.env.cr.savepoint():
                self.company_id = company
        except Exception as e:
            _logger.warning("Could not set company %s on waybill %s: %s",
                            company.display_name, self.id, e)


    def _cron_rs_drift_repair_one(self):
        service = self.env['rs.waybill.soap.service']
        BATCH = 200
        sync_company = self.env.company
        # Completed waybills are checked for DRIFT_COMPLETED_DAYS after delivery (an Adjustment can still
        # come); older ones only while an Odoo step is unfinished.
        recent = fields.Datetime.now() - timedelta(days=DRIFT_COMPLETED_DAYS)
        domain = [('rs_internal_id', '!=', False),
                  ('is_template', '=', False),
                  '|', '|', '|', '|', '|',
                  ('state', 'in', ('draft', 'active')),
                  '&', ('state', '=', 'completed'), ('delivery_date', '>=', recent),
                  '&', '&', ('state', '=', 'completed'), ('delivery_date', '=', False),
                  ('activation_date', '>=', recent),
                  ('rs_cancel_cascade', '=', 'pending'),
                  ('rs_post_commit_error', '!=', False),
                  ('rs_goods_pending_snapshot', '!=', False),
                  # Only what this account can see. company_id = False rows predate the company field; sweep
                  # them with the first pass instead of leaving them unchecked.
                  '|', ('company_id', '=', sync_company.id), ('company_id', '=', False)]
        # Round-robin: never-checked first, then longest-unchecked: a fair, bounded slice per run, no rescans.
        # sudo: the multi-company rule would narrow this to the borrowed user's companies; the domain already scopes it.
        candidates = self.sudo().search(domain + [('rs_drifted_checked', '=', False)], limit=BATCH)
        if len(candidates) < BATCH:
            candidates |= self.sudo().search(
                domain + [('rs_drifted_checked', '!=', False)],
                order='rs_drifted_checked asc', limit=BATCH - len(candidates))
        repaired = 0
        skipped = 0
        for waybill in candidates:
            try:
                with self.env.cr.savepoint():
                    header, _goods = service.get_full_waybill(waybill.rs_internal_id)
                    if not header:
                        skipped += 1
                    else:
                        if not waybill.company_id:
                            waybill._rs_claim_company(header, sync_company)
                        vals = waybill._map_rs_waybill_vals(header)
                        drifted = {}
                        for k,v in vals.items():
                            try:
                                current = waybill[k]
                                if not current and not v:
                                    continue
                                if hasattr(current, '_name') and hasattr(current, 'id'):
                                    if current.id == (v or False):
                                        continue
                                if hasattr(current, 'strftime') and isinstance(v, str):
                                    if current.strftime('%Y-%m-%d %H:%M:%S') == v:
                                        continue
                                elif current == v:
                                    continue
                                drifted[k] = v
                            except Exception:
                                drifted[k] = v

                        goods_changed = waybill._goods_lines_changed(waybill, _goods)
                        was_confirmed = waybill.is_confirmed == '1'
                        if drifted:
                            waybill.with_context(rs_from_rs=True).write(drifted)
                            waybill._sync_driver_name_to_partner()
                            if 'buyer_id' in drifted:
                                waybill._sync_buyer_to_so_and_picking()
                        if goods_changed:
                            goods_snapshot = waybill._build_line_snapshot()
                            waybill._sync_goods_lines(_goods)
                            waybill._apply_rs_goods_diff_auto(goods_snapshot)
                        # Carrier (or portal) completed it out-of-band: validate our delivery so Odoo mirrors RS.
                        # No-op without a not-done picking.
                        if drifted.get('state') == 'completed':
                            waybill._cascade_validate_picking()
                        if drifted.get('is_confirmed') == '1':
                            waybill._rs_post_commit(_("Validate the incoming receipt"),
                                                    waybill._cascade_validate_receipt)
                        if drifted.get('state') == 'cancelled':
                            waybill._cascade_cancel_purchase()
                            waybill._cascade_cancel_delivery()
                        # Cascades above fire only on DRIFT. If Odoo and RS AGREE (both completed) but follow-through
                        # never happened (e.g. transfer failed after the close), it is retried here every sweep.
                        repaired_local = waybill._rs_repair_local_state()
                        # Seller edit reset the buyer decision (is_confirmed left '1'): flag re-confirm and tell the
                        # buyer, even for non-goods edits.
                        if (waybill.waybill_direction == 'buyer' and was_confirmed
                                and waybill.is_confirmed != '1' and not waybill.is_buyer_reconfirm_needed):
                            waybill.is_buyer_reconfirm_needed = True
                            waybill.message_post(body=Markup(_(
                                "Seller edited this waybill on RS.GE — your previous Receive was reset. "
                                "Review the changes and click <b>Receive</b> again (or <b>Reject</b>).")))
                        if drifted or goods_changed:
                            parts = []
                            if drifted:
                                parts.append('fields: ' + ', '.join('%s → %s' % (k, v) for k, v in drifted.items()))
                            if goods_changed:
                                parts.append('goods lines updated')
                            waybill.message_post(body=_("Drift repair from RS — %s") % '; '.join(parts))
                            repaired += 1
                        elif repaired_local:
                            repaired += 1
            except Exception as e:
                _logger.warning("Drift repair failed for waybill %s: %s", waybill.id, e)
                skipped += 1
            # Mark as checked outside the savepoint, so a failed/rolled-back repair still advances the
            # rotation, and save it now: a run cut by the cron time limit keeps what it did.
            waybill.rs_drifted_checked = fields.Datetime.now()
            if not self.env['ir.cron']._commit_progress(1):
                break
        _logger.info("Drift repair: %d repaired, %d skipped, %d candidates", repaired, skipped, len(candidates))
