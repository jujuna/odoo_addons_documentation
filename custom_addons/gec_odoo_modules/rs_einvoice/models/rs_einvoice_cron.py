import logging
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.fields import Domain

from .account_move import RS_BUYER_ACTIONABLE, rs_to_int
from .rs_soap_service import _rs_row_lookup

_logger = logging.getLogger(__name__)


def _parse_dt_aware(raw):
    """Parse an rs.ge timestamp, keeping tzinfo so callers take the local date or naive UTC without off-by-one days."""
    if not raw:
        return False
    s = str(raw).strip()
    if not s:
        return False
    if 'T' in s or ' ' in s:
        if '.' in s:
            head, _, tail = s.partition('.')
            tz_part = ''
            for marker in ('+', '-', 'Z'):
                idx = tail.find(marker)
                if idx > 0 or (marker == 'Z' and idx == 0):
                    tz_part = tail[idx:]
                    break
            s = head + tz_part
    s_norm = s[:-1] + '+00:00' if s.endswith('Z') else s
    dt = None
    try:
        dt = datetime.fromisoformat(s_norm)
    except ValueError:
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(s_norm, fmt)
                break
            except ValueError:
                continue
    return dt or False


def _to_naive_utc(dt):
    """For Odoo Datetime fields, which store naive UTC."""
    if not dt:
        return False
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_local_date(dt):
    """For Date fields: the day in the datetime's own timezone, not UTC."""
    if not dt:
        return False
    return dt.date()

# rs.ge statuses a posted document can still move out of without an action here.
RS_REFRESH_STATUSES = ('1', '2', '5', '6', '7', '8')
# A draft seller correction sent to the buyer (5) is posted when rs.ge reports it accepted.
RS_WAITING_DRAFT_CORRECTION = Domain([
    ('state', '=', 'draft'),
    ('rs_einv_replaces_id', '!=', False),
    ('rs_einv_replacement_mode', '=', 'correction'),
    ('rs_einv_status', '=', '5'),
])

_RS_ROW_ALIASES = {
    'seller_tin': ('saident_no_s', 'sa_ident_no'),
    'buyer_tin': ('saident_no_b', 'bu_ident_no'),
    'rs_id': ('id',),
    'operation_dt': ('operation_dt',),
    'reg_dt': ('reg_dt',),
    'k_id': ('k_id',),
    'k_type': ('k_type',),
    'status': ('status',),
    'amount': ('tanxa',),
    'series': ('f_series',),
    'number': ('f_number',),
    'seller_name': ('org_name',),
    'buyer_un_id': ('buyer_un_id',),
}


def _rs_row_get(row, key, default=None):
    for alias in _RS_ROW_ALIASES.get(key, (key,)):
        value = _rs_row_lookup(row, alias)
        if value not in (None, ''):
            return value
    return default


def _rs_find_partner_by_tin(env, tin, company_id):
    """(partner, ambiguous): company-specific wins over global; several commercial partners leave partner empty."""
    Partner = env['res.partner'].sudo()
    if not tin:
        return Partner.browse(), Partner.browse()
    candidates = Partner.search([('vat', '=', tin), ('company_id', 'in', (False, company_id)), ('active', '=', True)], order='company_id, id')
    if not candidates:
        return Partner.browse(), Partner.browse()

    commercial = candidates.mapped('commercial_partner_id') or candidates
    distinct_commercial = commercial.filtered(lambda p: p.active)
    if len(distinct_commercial) <= 1:
        company_specific = candidates.filtered(lambda p: p.company_id.id == company_id)
        chosen = company_specific[:1] or candidates[:1]
        return chosen, Partner.browse()
    return Partner.browse(), distinct_commercial


class AccountMoveRsCron(models.AbstractModel):
    """Cron entry points on their own AbstractModel, so ir.cron does not touch account.move."""
    _name = 'rs.einvoice.cron'
    _description = 'rs.ge Buyer-Invoice Sync CRON'

    @api.model
    def _rs_company_passes(self, label):
        """(company, responsible user) pairs to run: companies with a Tax ID whose RS Responsible User holds a login.
        Empty when rs_base_methods is not installed."""
        Users = self.env['res.users']
        if not hasattr(Users, '_rs_responsible_user'):
            _logger.error("rs.ge %s cron: rs_base_methods is not installed, nothing can run.", label)
            return []
        passes = []
        for company in self.env['res.company'].sudo().search([]):
            if not (company.vat or '').strip():
                continue
            user = Users._rs_responsible_user(company)
            if not user:
                _logger.info("rs.ge %s cron: %s has no RS Responsible User with a login for it — skipped.", label, company.display_name)
                continue
            passes.append((company, user))
        return passes

    @api.model
    def _cron_sync_buyer_invoices(self, lookback_hours=72):
        """One pass per company, as its RS Responsible User. Failing companies roll back without stopping the others.
        lookback_hours is clamped to 72 (rs.ge's 3-day window)."""
        lookback_hours = min(max(int(lookback_hours or 72), 1), 72)
        end_dt = (datetime.now(timezone.utc) .replace(tzinfo=None) - timedelta(seconds=60))
        start_dt = end_dt - timedelta(hours=lookback_hours)

        created_total = 0
        for company, user in sorted(self._rs_company_passes('buyer-sync'), key=lambda p: (len(p[0].parent_ids), p[0].id)):
            try:
                with self.env.cr.savepoint():
                    created = self.with_user(user).with_company(company)._sync_one_user(start_dt, end_dt)
            except Exception as e:
                _logger.error("rs.ge buyer-sync cron: sync failed for %s as %s: %s", company.display_name, user.login, e)
                continue
            if created:
                _logger.info("rs.ge buyer-sync cron: created %d new vendor bill(s) for %s as %s", created, company.display_name, user.login)
            created_total += created
            if not self.env['ir.cron']._commit_progress(1):
                break
        return created_total

    def _sync_one_user(self, start_dt, end_dt):
        """Runs as the company's responsible user with that company active, so its login and taxpayer id resolve."""
        service = self.env['rs.soap.service']
        try:
            service._check_auth()
            un_id = service._rs_company_un_id()
        except UserError as e:
            _logger.info("rs.ge cron: auth precheck failed for %s in %s — %s", self.env.user.login, self.env.company.display_name, e)
            return 0

        rows = service.get_user_invoices(un_id=un_id, last_update_s=start_dt, last_update_e=end_dt)
        if not rows:
            return 0

        Move = self.env['account.move'].sudo()
        purchase_journal = self.env['account.journal'].sudo().search([('type', '=', 'purchase'), ('company_id', '=', self.env.company.id)],
            order='sequence, id', limit=1)
        if not purchase_journal:
            _logger.info("rs.ge cron: no purchase journal for company %s, skipping", self.env.company.display_name)
            return 0

        created = 0
        for row in rows:
            rs_id = str(_rs_row_get(row, 'rs_id') or '').strip()
            if not rs_id:
                continue
            buyer_un_id = rs_to_int(_rs_row_get(row, 'buyer_un_id'), 0)
            if buyer_un_id != int(un_id):
                continue
            status = str(_rs_row_get(row, 'status') or '')
            if status not in RS_BUYER_ACTIONABLE:
                continue
            k_type = rs_to_int(_rs_row_get(row, 'k_type'), 0)
            if k_type and status in ('5', '8'):
                continue
            if Move.search([('rs_einv_id', '=', rs_id), ('company_id.vat', '=', (self.env.company.vat or '').strip())], limit=1):
                continue

            seller_tin = str(_rs_row_get(row, 'seller_tin') or '').strip()
            partner, ambiguous = _rs_find_partner_by_tin(self.env, seller_tin, self.env.company.id)
            if ambiguous:
                _logger.info("rs.ge cron: skip rs_id=%s — TIN %s matches multiple vendors (%d). Operator must use the manual inbox to pick the right "
                    "one.", rs_id, seller_tin or '—', len(ambiguous))
                continue
            if not partner:
                _logger.info("rs.ge cron: skip rs_id=%s — no vendor with TIN %s", rs_id, seller_tin or '—')
                continue

            op_aware = _parse_dt_aware(_rs_row_get(row, 'operation_dt'))
            op_local_date = _to_local_date(op_aware) or end_dt.date()
            try:
                with self.env.cr.savepoint():
                    if Move.search([('rs_einv_id', '=', rs_id), ('company_id.vat', '=', (self.env.company.vat or '').strip())], limit=1):
                        continue
                    move = Move.create({
                        'move_type': 'in_invoice',
                        'partner_id': partner.id,
                        'journal_id': purchase_journal.id,
                        'invoice_date': op_local_date,
                        'document_tax_mode': 'tax_excluded',
                    })
                    move.rs_einv_id = rs_id
                    move.action_rs_buyer_pull()
                    created += 1
            except UserError as e:
                _logger.info("rs.ge cron: skip rs_id=%s — %s", rs_id, e)
            except Exception as e:
                _logger.warning("rs.ge cron: unexpected error on rs_id=%s: %s", rs_id, e)
        return created

    @api.model
    def _cron_escalate_pending_actions(self, age_hours=24):
        """Nudges moves whose pending rs.ge action is stale, so an orphan after a SOAP timeout is not forgotten."""
        now = fields.Datetime.now()
        cutoff = now - timedelta(hours=age_hours)
        re_escalate_cutoff = now - timedelta(hours=max(age_hours, 23))
        Move = self.env['account.move'].sudo()
        stuck = Move.search([('rs_einv_pending_action', '!=', False), ('rs_einv_pending_action_at', '<', cutoff)])
        n_posted = 0
        for move in stuck:
            if (move.rs_einv_pending_action_escalated_at and move.rs_einv_pending_action_escalated_at > re_escalate_cutoff):
                continue
            move._rs_log("Pending rs.ge action '%s' has been open since %s — operator has not resolved it yet. Click 'Resolve Orphan' on the RS "
                "E-Invoice tab." % (move.rs_einv_pending_action, move.rs_einv_pending_action_at), 'warning')
            try:
                move.message_post(body=_("rs.ge action '%s' has been pending for more than %s hours. Click <em>Resolve Orphan</em> on the RS "
                    "E-Invoice tab to link the orphan draft on rs.ge.", move.rs_einv_pending_action, age_hours))
                move.write({'rs_einv_pending_action_escalated_at': now})
                n_posted += 1
            except Exception as e:
                _logger.warning("rs.ge escalate cron: chatter failed for move %s: %s", move.id, e)
        if n_posted:
            _logger.info("rs.ge escalate cron: nudged %d move(s) with stale pending actions", n_posted)
        return n_posted

    @api.model
    def _cron_detect_stuck_sends(self, age_days=7):
        """Status 1/5 awaits buyer Accept/Reject; status 6 (Cancel Sent) keeps the bill in AR/VAT until confirmed."""
        now = fields.Datetime.now()
        cutoff = now - timedelta(days=age_days)
        re_escalate_cutoff = now - timedelta(days=max(age_days - 1, 1))
        Move = self.env['account.move'].sudo()
        stuck = Move.search([
            ('rs_einv_status', 'in', ['1', '5']),
            ('rs_einv_sent_at', '!=', False),
            ('rs_einv_sent_at', '<', cutoff),
            ('rs_einv_is_buyer_side', '=', False),
        ])
        def _stuck_send_messages(move):
            return (_("Buyer has not acted on this document for %d+ "
                "days (sent %s, status '%s'). Consider following up.") % (age_days, move.rs_einv_sent_at, move.rs_einv_status),
                _("Buyer has not accepted or rejected this rs.ge document for more than %d days (sent on %s). Reach out to the buyer or use "
                "<em>Cancel on RS</em> / <em>Delete on RS</em> if the document should be retracted.", age_days, move.rs_einv_sent_at))
        n_posted = self._escalate_stuck_moves(stuck, re_escalate_cutoff, now, label='stuck-send', doc_label='invoice(s)',
            build_messages=_stuck_send_messages, age_days=age_days)
        stuck_cancels = Move.search([
            ('rs_einv_status', '=', '6'),
            ('rs_einv_cancel_pending_at', '!=', False),
            ('rs_einv_cancel_pending_at', '<', cutoff),
            ('rs_einv_is_buyer_side', '=', False),
        ])

        def _stuck_cancel_messages(move):
            return (_("Cancel on RS pending for %d+ days (sent %s) — "
                "buyer has not confirmed; bill still in AR/VAT.") % (age_days, move.rs_einv_cancel_pending_at),
                _("Cancellation on rs.ge has been pending buyer confirmation for more than %d days (requested on %s). The bill is still in AR/VAT "
                "until the buyer accepts the cancellation. Chase the buyer or escalate.", age_days, move.rs_einv_cancel_pending_at))
        n_cancel_posted = self._escalate_stuck_moves(stuck_cancels, re_escalate_cutoff, now, label='stuck-cancel', doc_label='cancellation(s)',
            build_messages=_stuck_cancel_messages, age_days=age_days)

        return n_posted + n_cancel_posted

    @api.model
    def _escalate_stuck_moves(self, moves, re_escalate_cutoff, now, *, label, doc_label, build_messages, age_days):
        posted = 0
        for move in moves:
            if (move.rs_einv_stuck_send_escalated_at and move.rs_einv_stuck_send_escalated_at > re_escalate_cutoff):
                continue
            log_msg, chatter_msg = build_messages(move)
            move._rs_log(log_msg, 'warning')
            try:
                move.message_post(body=chatter_msg)
                move.write({'rs_einv_stuck_send_escalated_at': now})
                posted += 1
            except Exception as e:
                _logger.warning("rs.ge %s cron: chatter failed for move %s: %s", label, move.id, e)
        if posted:
            _logger.info("rs.ge %s cron: %d %s older than %d days", label, posted, doc_label, age_days)
        return posted

    @api.model
    def _cron_refresh_status(self, is_buyer_side, batch_size=200):
        """Runs as each company's RS Responsible User. Status 6 catches 6 -> 7 (auto-reverse); 7 re-drives a reversal
        stranded by an interrupted tail."""
        if is_buyer_side:
            side_label = 'buyer'
            doc_label = 'bill(s)'
            move_types = ('in_invoice', 'in_refund')
        else:
            side_label = 'seller'
            doc_label = 'invoice(s)'
            move_types = ('out_invoice', 'out_refund')
        Move = self.env['account.move'].sudo()
        eligible_statuses = RS_REFRESH_STATUSES
        domain = Domain.AND([[
            ('move_type', 'in', move_types),
            ('rs_einv_is_buyer_side', '=', is_buyer_side),
            ('rs_einv_id', '!=', False),
            ('rs_einv_skip', '=', False),
        ], Domain([('state', '=', 'posted'), ('rs_einv_status', 'in', eligible_statuses)]) | RS_WAITING_DRAFT_CORRECTION])
        cron = self.env['ir.cron']
        found = 0
        refreshed = 0
        drifted = 0
        skipped_busy = 0
        out_of_time = False
        for company, user in self._rs_company_passes('%s-status' % side_label):
            moves = Move.search(domain & Domain('company_id', '=', company.id), order='write_date asc', limit=max(int(batch_size or 200), 1))
            found += len(moves)
            # sudo after with_user: keeps cron access; env.user stays the responsible user the rs.ge calls read.
            for move in moves.with_user(user).sudo().with_company(company):
                # SKIP LOCKED: skip (not block) a busy move; the rs.ge read under this lock stops stale clobbering.
                locked = move.try_lock_for_update(limit=1)
                if not locked:
                    skipped_busy += 1
                    continue
                locked.invalidate_recordset(['state', 'rs_einv_status', 'rs_einv_skip'])
                before = locked.rs_einv_status
                ok = False
                try:
                    with self.env.cr.savepoint():
                        if not locked.rs_einv_skip and ((locked.state == 'posted' and locked.rs_einv_status in eligible_statuses)
                                or locked.filtered_domain(RS_WAITING_DRAFT_CORRECTION)):
                            locked._rs_safe_refresh_status()
                            ok = True
                except Exception as e:
                    _logger.warning("rs.ge %s-status cron: refresh failed for move %s (rs_id=%s): %s", side_label, move.id, move.rs_einv_id, e)
                if ok:
                    refreshed += 1
                    if locked.rs_einv_status != before:
                        drifted += 1
                if not cron._commit_progress(1):
                    out_of_time = True
                    break
            if out_of_time:
                break
        if found:
            _logger.info("rs.ge %s-status cron: refreshed %d / %d %s; %d showed status drift; %d skipped (busy).",
                side_label, refreshed, found, doc_label, drifted, skipped_busy)
        return refreshed

    @api.model
    def _cron_refresh_buyer_status(self, batch_size=200):
        return self._cron_refresh_status(True, batch_size=batch_size)

    @api.model
    def _cron_refresh_seller_status(self, batch_size=200):
        return self._cron_refresh_status(False, batch_size=batch_size)

    @api.model
    def _rs_refresh_seller_statuses(self, company, limit=200):
        """Dashboard refresh: runs as the current user, not the RS responsible user; UserError is logged, not raised."""
        moves = self.env['account.move'].search(Domain.AND([[
            ('company_id', '=', company.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('rs_einv_is_buyer_side', '=', False),
            ('rs_einv_id', '!=', False),
            ('rs_einv_skip', '=', False),
        ], Domain([('state', '=', 'posted'), ('rs_einv_status', 'in', RS_REFRESH_STATUSES)]) | RS_WAITING_DRAFT_CORRECTION]),
            order='write_date asc', limit=limit)
        for move in moves.with_company(company):
            try:
                move._rs_safe_refresh_status()
            except UserError as e:
                move._rs_log("Status refresh from the dashboard failed: %s" % e, 'warning')

    @api.model
    def _cron_rs_recover_stranded_cancellations(self, batch_size=200):
        """Completes reversals stranded at rs.ge status 7, or originals whose correction is at 8. No rs.ge call,
        so it is safe with refresh crons off. Unreversible moves (payments, credit notes, locked period) are flagged."""
        Move = self.env['account.move'].sudo()
        superseded = Domain('rs_einv_replaced_by_id', 'any', [
            ('rs_einv_status', '=', '8'),
            ('state', '!=', 'cancel'),
            '|',
            ('rs_einv_replacement_mode', '=', 'correction'),
            ('rs_einv_is_buyer_side', '=', True),
        ])
        candidates = Move.search(Domain.AND([[
            ('move_type', 'in', ('out_invoice', 'in_invoice')),
            ('state', '=', 'posted'),
            ('rs_einv_skip', '=', False),
            ('payment_state', '!=', 'reversed'),
            ('rs_einv_reversal_pending_at', '=', False),
        ], Domain('rs_einv_status', '=', '7') | superseded]), order='write_date asc', limit=max(int(batch_size or 200), 1))
        cron = self.env['ir.cron']
        recovered = 0
        skipped_busy = 0
        for move in candidates:
            locked = move.try_lock_for_update(limit=1)
            if not locked:
                skipped_busy += 1
                continue
            locked.invalidate_recordset(['state', 'rs_einv_status', 'rs_einv_skip', 'payment_state', 'rs_einv_reversal_pending_at'])
            if not (locked.state == 'posted'
                    and not locked.rs_einv_skip
                    and locked.payment_state != 'reversed'
                    and not locked.rs_einv_reversal_pending_at):
                continue
            locked = locked.with_company(locked.company_id)
            try:
                with self.env.cr.savepoint():
                    if locked.rs_einv_status == '7':
                        locked.rs_einv_cancel_pending_at = False
                        done = locked._rs_auto_cancel_after_rs_cancellation()
                    else:
                        done = locked.rs_einv_replaced_by_id._rs_post_accepted_correction() and locked._rs_neutralize_after_correction_accepted()
                    if done:
                        recovered += 1
            except Exception as e:
                _logger.warning("rs.ge cancellation-recovery cron: auto-cancel failed on move %s (rs_id=%s): %s", move.id, move.rs_einv_id, e)
                locked.rs_einv_reversal_pending_at = fields.Datetime.now()
            if not cron._commit_progress(1):
                break
        if candidates:
            _logger.info("rs.ge cancellation-recovery cron: cancelled %d / %d stranded status-7/8 move(s); %d skipped (busy).", recovered,
                len(candidates), skipped_busy)
        return recovered

    @api.model
    def _cron_vacuum_rs_logs(self):
        """Shim so the cron targets one model; the line-snapshot vacuum runs with the log vacuum."""
        n_logs = self.env['rs.einvoice.log'].sudo()._cron_vacuum()
        n_snaps = self.env['rs.einvoice.correction.line'].sudo()._cron_vacuum_snapshots()
        return n_logs + n_snaps
