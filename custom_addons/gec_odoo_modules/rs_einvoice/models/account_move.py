import hashlib
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from functools import partial

from odoo import models, fields, api, _
from odoo.exceptions import LockError, UserError, ValidationError
from odoo.tools import SQL

from .rs_soap_service import _TRANSIENT_EXCEPTIONS, _to_rs_dt

_logger = logging.getLogger(__name__)

_RS_KEEP_LEVEL = 'error'


def _rs_replay_after_rollback(registry, uid, context, queue):
    """Superuser so record rules cannot drop the failure record; the original uid stays author and assignee."""
    try:
        with registry.cursor() as replay_cr:
            env = api.Environment(replay_cr, uid, dict(context, rs_replaying_after_rollback=True), su=True)
            for move_id, method_name, args in queue:
                move = env['account.move'].browse(move_id).exists()
                if not move:
                    continue
                try:
                    with replay_cr.savepoint():
                        getattr(move, method_name)(*args)
                except Exception:
                    _logger.exception("rs.ge replay of %s failed on move %s", method_name, move_id)
    except Exception:
        _logger.exception("rs.ge replay after rollback failed")


MAX_LINE_NAME_LEN = 255  # rs.ge truncates over 255 chars, rejects empty
MAX_FUTURE_DAYS = 5      # too far ahead -> non-existent VAT period
MAX_PAST_YEARS = 5       # too far back -> closed period

MONTHS_GE = [
    ('1', 'იანვარი'),
    ('2', 'თებერვალი'),
    ('3', 'მარტი'),
    ('4', 'აპრილი'),
    ('5', 'მაისი'),
    ('6', 'ივნისი'),
    ('7', 'ივლისი'),
    ('8', 'აგვისტო'),
    ('9', 'სექტემბერი'),
    ('10', 'ოქტომბერი'),
    ('11', 'ნოემბერი'),
    ('12', 'დეკემბერი'),
]

RS_STATUS = [
    ('-1', 'Deleted'),
    ('0', 'Draft'),
    ('1', 'Sent (Pending)'),
    ('2', 'Confirmed'),
    ('3', 'Corrected (Original)'),
    ('4', 'New Correction'),
    ('5', 'Correction Sent'),
    ('6', 'Cancelled (Sent)'),
    ('7', 'Cancellation Confirmed'),
    ('8', 'Correction Confirmed'),
]

# Live on rs.ge -> block local reset/cancel.
RS_LOCKED_STATES = ('1', '2', '3', '5', '6', '8')

RS_CONFIRMED = ('2', '8')
RS_DRAFT_OR_NEW_CORRECTION = ('0', '4')
RS_PENDING_BUYER = ('1', '5')
RS_ACCEPTED = ('2', '3', '8')
RS_CORRECTION_IN_FLIGHT = ('4', '5')
RS_BUYER_ACTIONABLE = ('1', '2', '3', '5', '6', '7', '8')  # sent to the buyer, so it can be pulled

K_TYPE = [('1', 'Full cancellation'), ('2', 'Tax treatment changed'), ('3', 'Price or amount changed'), ('4', 'Goods Returned to Seller')]

# VAT-neutral skip reasons are not filed on rs.ge; 'replacement' is the local-only half of Correct & Reissue.
RS_SKIP_REASON = [
    ('bad_debt', 'Bad debt write-off (TC Arts.156-181 — no VAT reduction)'),
    ('netting', 'Netting / offset (no VAT event)'),
    ('down_payment', 'Down Payment internal offset (Odoo accounting only)'),
    ('warranty', 'Warranty cash compensation (not a price reduction)'),
    ('intercompany_mirror', 'Inter-company mirror entry (correction already filed by other side)'),
    ('commercial_gesture', 'Commercial gesture / compensation (not a discount)'),
    ('replacement', 'Replacement reversal (paired with corrected replacement invoice)'),
    ('other', 'Other (document the reason in invoice notes)'),
]

RS_ADVANCE_SETTLEMENT_MODE = [('net', 'Net down-payment offsets'), ('native_attach', 'Native rs.ge advance settlement')]

RS_ADVANCE_SYNC_STATE = [('synced', 'Synced'), ('partial', 'Partial'), ('error', 'Error')]

_RS_NON_PHYSICAL_SKIP_REASONS = ('bad_debt', 'netting', 'down_payment', 'warranty', 'intercompany_mirror', 'commercial_gesture', 'replacement')

_RS_VAT_NEUTRAL_SKIP_REASONS = ('bad_debt', 'warranty', 'commercial_gesture', 'intercompany_mirror')

# Deadline per MoF Order #996 Art.54.
_RS_DEADLINE_DONE_STATES = ('1', '2', '3', '5', '6', '7', '8', '-1')
_RS_DEADLINE_WARNING_DAYS = 25
_RS_DEADLINE_DAYS = 30

# write() refuses to change these once the move is on rs.ge.
_RS_IMMUTABLE_AFTER_RS = ('partner_id', 'currency_id', 'invoice_date', 'reversed_entry_id', 'move_type')


def _rs_status_label(code):
    if not code:
        return '—'
    return dict(RS_STATUS).get(str(code), code)


def _rs_clean_number(value):
    text = ('' if value is None else str(value)).strip()
    return '' if text.lower() in ('', '-1', '0', 'null', 'none') else text


def rs_to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def rs_to_float(value, default=0.0):
    if value in (None, ''):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AccountMove(models.Model):
    _inherit = 'account.move'

    rs_einv_id = fields.Char(string='RS Invoice ID', copy=False, index=True, tracking=True)
    rs_einv_status = fields.Selection(RS_STATUS, string='RS Status', copy=False, readonly=True, tracking=True)
    rs_einv_series = fields.Char(string='RS Series', copy=False, readonly=True)
    rs_einv_number = fields.Char(string='RS Number', copy=False, readonly=True)
    rs_einv_k_type = fields.Selection(K_TYPE, string='RS Correction Reason', copy=False, tracking=True,
        help="Why this document is being corrected on rs.ge — k_type sent with the correction request.")
    rs_einv_is_advance = fields.Boolean(string='Advance / Down-Payment Invoice', copy=False,
        help="Files this as a prepayment advance VAT invoice (save_invoice_a) on rs.ge.")
    rs_einv_advance_settlement_mode = fields.Selection(RS_ADVANCE_SETTLEMENT_MODE, string='Advance Settlement', default='net', copy=False,
        tracking=True,
        help="Net: offset down-payment lines before export. Native: send full delivery lines and attach prior advances via rs.ge v3.0.5.")
    rs_einv_advance_sync_state = fields.Selection(RS_ADVANCE_SYNC_STATE, string='Advance Sync', copy=False, readonly=True, tracking=True,
        help="State of native rs.ge advance settlement for this final invoice.")
    rs_einv_has_downpayment_offsets = fields.Boolean(string='Has Down-Payment Offsets', compute='_compute_rs_einv_has_downpayment_offsets')
    rs_einv_advance_settlement_ids = fields.One2many('rs.einvoice.advance.settlement', 'final_move_id', string='RS Advance Settlements', copy=False)
    rs_einv_advance_usage_ids = fields.One2many('rs.einvoice.advance.settlement', 'advance_move_id', string='Settled On Final Invoices', copy=False)
    rs_einv_note = fields.Char(string='RS Note', copy=False, size=255,
        help="Free-text note written into the rs.ge invoice PDF (uses save_invoice_n endpoint). Max 255 chars.")
    rs_einv_rejection_reason = fields.Text(string='RS Rejection Reason', copy=False, readonly=True,
        help="Buyer's rejection reason sent to rs.ge. Audit trail for correcting and reissuing.")
    rs_einv_skip = fields.Boolean(string='Skip rs.ge (VAT-neutral)', copy=False, tracking=True,
        help="No rs.ge filing — credit is outside the VAT chain. Requires a Skip Reason for the audit trail.")
    rs_einv_skip_reason = fields.Selection(RS_SKIP_REASON, string='Skip Reason', copy=False, tracking=True,
        help="Required when Skip rs.ge is ticked. Expense-type reasons (bad_debt, warranty, commercial_gesture, intercompany_mirror) must use "
        "expense accounts and carry no taxes.")
    rs_einv_is_spec = fields.Boolean(string='Petroleum Invoice (ნსაფ)', copy=False, readonly=True, index=True,
        help="Filed on rs.ge as a petroleum invoice (ნსაფ) through the petroleum service, not as an ordinary e-invoice.")
    rs_einv_replaces_id = fields.Many2one('account.move', string='Replaces Invoice', copy=False, readonly=True, index=True, tracking=True,
        check_company=True, ondelete='restrict', help="Points to the original invoice this one supersedes (Cancel & Reissue or Correct & Reissue).")
    rs_einv_replaced_by_id = fields.Many2one('account.move', string='Replaced by Invoice', copy=False, readonly=True, index=True, tracking=True,
        check_company=True, ondelete='restrict', help="Points to the new invoice that supersedes this one (Cancel & Reissue or Correct & Reissue).")
    rs_einv_can_clear_cancelled_replacement = fields.Boolean(string='Can Clear Cancelled Replacement',
        compute='_compute_rs_einv_can_clear_cancelled_replacement')
    rs_einv_correction_in_flight = fields.Boolean(string='rs.ge Replacement In Flight', compute='_compute_rs_einv_correction_in_flight',
        compute_sql='_compute_sql_rs_einv_correction_in_flight', compute_sudo=True,
        help="This invoice is still posted while its replacement exists. Until rs.ge accepts the replacement and Odoo cancels this invoice, both "
        "count in the sale order's invoiced quantity and, once the replacement is posted, in revenue, VAT and receivables. Exclude these at "
        "month-end close.")
    rs_einv_reversal_count = fields.Integer(string='Reversal Count', compute='_compute_rs_einv_reversal_count',
        help="Count of credit notes / reversals on this invoice. Drives the Credit Notes stat-button.")
    rs_einv_replacement_mode = fields.Selection([('fresh', 'New separate RS invoice'), ('correction', 'Corrected version of old RS invoice')],
        string='Replacement Mode', copy=False, readonly=True, index=True, tracking=True,
        help="New separate RS invoice: cancel old, then file as independent.\nCorrected version: replace the old invoice on rs.ge with this one.")
    rs_einv_latest_id = fields.Char(string='Latest RS Record ID', compute='_compute_latest', copy=False,
        help="Most recent non-deleted rs.ge record ID for this document.")
    rs_einv_latest_status = fields.Selection(RS_STATUS, string='Latest RS Status', compute='_compute_latest', copy=False,
        help="Status of the most recent non-deleted rs.ge record.")
    rs_einv_last_sync_hash = fields.Char(string='Sync Fingerprint', copy=False, readonly=True,
        help="Hash of the invoice line state at the last successful sync to rs.ge.")
    rs_einv_pending_action_escalated_at = fields.Datetime(string='Last Pending-Action Escalation', copy=False, readonly=True,
        help="Timestamp of the last chatter escalation for a stuck pending action — prevents daily re-spam.")
    rs_einv_stuck_send_escalated_at = fields.Datetime(string='Last Stuck-Send Escalation', copy=False, readonly=True,
        help="Timestamp of the last chatter escalation for a buyer who has not acted on a sent document — prevents daily re-spam.")
    rs_einv_cancel_pending_at = fields.Datetime(string='Cancellation Requested At', copy=False, readonly=True, index='btree_not_null',
        help="When Cancel on RS was sent. Drives the stuck-cancel cron until the buyer confirms.")
    rs_einv_reversal_pending_at = fields.Datetime(string='Reversal Escalated At', copy=False, readonly=True,
        help="Set when rs.ge voided this document (cancellation confirmed, status 7) or superseded it (correction accepted, status 8) but Odoo could "
        "not cancel it, e.g. because payments are applied. Cleared once the cancel succeeds.")
    rs_einv_has_pending_changes = fields.Boolean(string='Unsynced Line Changes', compute='_compute_has_pending_changes', copy=False,
        help="True when Odoo lines have changed since the last sync.")
    rs_einv_lines_sync_state = fields.Selection([('in_sync', 'In sync'), ('partial', 'Partially synced')], string='RS Line Sync State', copy=False,
        readonly=True, help="'partial' when Update on RS aborted mid-sync, leaving rs.ge with mixed lines. Cleared on success.")
    rs_einv_log_ids = fields.One2many('rs.einvoice.log', 'move_id', string='RS Logs', copy=False)
    rs_einv_pulled_line_ids = fields.One2many('rs.einvoice.correction.line', 'move_id', string='rs.ge Source Lines (read-only)',
        domain=[('snapshot_type', '=', 'rs_pulled')], copy=False,
        help="Supplier's lines as pulled from rs.ge. Refreshed on every Pull/Check Status for comparison before Accept or Reject.")
    rs_einv_pulled_lines_hash = fields.Char(string='Imported rs.ge Lines Fingerprint', copy=False, readonly=True,
        help="Fingerprint of the rs.ge lines this bill's lines were last taken from (Pull or Reimport Lines). Accept refuses when rs.ge's lines no "
        "longer have it: the supplier changed the invoice.")

    rs_einv_operation_month = fields.Selection(MONTHS_GE, string='Operation Month', compute='_compute_rs_operation_period', store=True)
    rs_einv_operation_year = fields.Char(string='Operation Year', compute='_compute_rs_operation_period', store=True)

    rs_einv_seller_tin = fields.Char(string='Seller TIN', compute='_compute_rs_einv_parties')
    rs_einv_seller_name = fields.Char(string='Seller Name', compute='_compute_rs_einv_parties')
    rs_einv_buyer_tin = fields.Char(string='Buyer TIN', compute='_compute_rs_einv_parties')
    rs_einv_buyer_name = fields.Char(string='Buyer Name', compute='_compute_rs_einv_parties')
    rs_einv_is_buyer_side = fields.Boolean(string='Buyer-Side Document', compute='_compute_rs_einv_is_buyer_side', store=True,
        help="True for vendor bills/credit notes. Switches the RS E-Invoice tab to buyer actions.")
    rs_einv_overhead_no = fields.Char(string='Declaration Sequence #', copy=False, readonly=True,
        help="Declaration sequence number from rs.ge (seller's on sales invoices, buyer's on vendor bills). Refreshed on Check Status.")
    rs_einv_seq_num_s = fields.Char(string='Seller Declaration #', copy=False, readonly=True)
    rs_einv_seq_num_b = fields.Char(string='Buyer Declaration #', copy=False, readonly=True)
    rs_einv_rejection_note = fields.Text(string='RS Rejection Note', copy=False, readonly=True,
        help="Odoo's note about a rejection on rs.ge. Cleared after a successful re-send.")
    rs_einv_supplier_k_id = fields.Char(string='Pending Supplier Correction ID', copy=False, readonly=True,
        help="Set when rs.ge reports a supplier correction against this vendor bill. Use Import Supplier Correction to bring it in.")
    # Set before an rs.ge request; left in place when recovery is needed.
    rs_einv_pending_action = fields.Selection([
        ('create', 'Create invoice on RS'),
        ('correction', 'Create correction on RS'),
        ('delete', 'Delete on RS'),
        ('send', 'Send to buyer'),
    ], string='Pending RS Action', copy=False, readonly=True,
        help="rs.ge is still processing this request or did not respond. If stuck, click Resolve Orphan to recover (Dismiss Pending for a "
        "correction).")
    rs_einv_pending_action_at = fields.Datetime(string='Pending Since', copy=False, readonly=True, index='btree_not_null',
        help="Time of the last rs.ge request that has not completed.")
    rs_einv_sent_at = fields.Datetime(string='Sent to Buyer At', copy=False, readonly=True, index='btree_not_null',
        help="Last time this document was sent to the buyer on rs.ge. Used to flag stuck-send escalations.")
    rs_einv_rejection_status = fields.Char(string='Rejection Tracker', copy=False, readonly=True,
        help="Internal deduplication key (curr_status:was_ref) for rejection chatter posts across repeated status checks.")
    rs_einv_overdue_days = fields.Integer(string='Days Since Operation', compute='_compute_rs_einv_overdue',
        help="Calendar days since operation date for invoices not yet sent to the buyer. Drives the deadline banner.")
    rs_einv_overdue_state = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Warning — approaching deadline'),
        ('overdue', 'Overdue — past #996 Art.54 deadline'),
    ], string='Deadline State', compute='_compute_rs_einv_overdue',
        help="Green up to 25 days, yellow 25–29, red from day 30 (#996 Art.54). Only for invoices not yet sent to the buyer.")
    _rs_einv_id_unique_per_company = models.Constraint('UNIQUE (rs_einv_id, company_id)',
        'The same rs.ge Invoice ID cannot be linked to two Odoo documents in the same company.')

    @api.depends('invoice_date')
    def _compute_rs_operation_period(self):
        for move in self:
            date = move.invoice_date
            move.rs_einv_operation_month = str(date.month) if date else False
            move.rs_einv_operation_year = str(date.year) if date else False

    @api.depends('move_type')
    def _compute_rs_einv_is_buyer_side(self):
        for move in self:
            move.rs_einv_is_buyer_side = move.is_purchase_document()

    @api.depends('rs_einv_is_buyer_side', 'company_id.vat', 'company_id.name', 'partner_id.vat', 'partner_id.name')
    def _compute_rs_einv_parties(self):
        for move in self:
            seller, buyer = ((move.partner_id, move.company_id) if move.rs_einv_is_buyer_side else (move.company_id, move.partner_id))
            move.rs_einv_seller_tin = seller.vat or False
            move.rs_einv_seller_name = seller.name or False
            move.rs_einv_buyer_tin = buyer.vat or False
            move.rs_einv_buyer_name = buyer.name or False

    @api.depends('move_type', 'invoice_line_ids.display_type', 'invoice_line_ids.quantity', 'invoice_line_ids.price_total')
    def _compute_rs_einv_has_downpayment_offsets(self):
        for move in self:
            move.rs_einv_has_downpayment_offsets = (
                move._rs_has_downpayment_offset_lines()
                if move.move_type in ('out_invoice', 'out_refund') else False
            )

    @api.depends('rs_einv_id', 'rs_einv_status')
    def _compute_latest(self):
        epoch = fields.Datetime.to_datetime('1970-01-01 00:00:00')
        persisted = self.filtered(lambda move: move.id and isinstance(move.id, int))
        candidates_by_move = {move.id: [] for move in persisted}
        if candidates_by_move:
            move_ids = list(candidates_by_move)
            Move = self.env['account.move']

            invoice_corrections = Move.search([
                ('rs_einv_replaces_id', 'in', move_ids),
                ('rs_einv_replacement_mode', '=', 'correction'),
                ('rs_einv_id', '!=', False),
            ])
            for inv in invoice_corrections:
                if inv.rs_einv_status and inv.rs_einv_status != '-1':
                    candidates_by_move[inv.rs_einv_replaces_id.id].append((inv.create_date or epoch, inv.id, inv.rs_einv_id, inv.rs_einv_status))

        for move in self:
            move_id = move.id if move.id and isinstance(move.id, int) else False
            candidates = candidates_by_move.get(move_id, [])
            if candidates:
                candidates.sort(reverse=True)
                move.rs_einv_latest_id = candidates[0][2]
                move.rs_einv_latest_status = candidates[0][3]
            else:
                move.rs_einv_latest_id = move.rs_einv_id or False
                move.rs_einv_latest_status = move.rs_einv_status or False

    @api.depends('rs_einv_replaced_by_id', 'rs_einv_replaced_by_id.state')
    def _compute_rs_einv_can_clear_cancelled_replacement(self):
        for move in self:
            replacement = move.rs_einv_replaced_by_id
            move.rs_einv_can_clear_cancelled_replacement = bool(replacement and replacement.state == 'cancel')

    @api.depends('state', 'payment_state', 'rs_einv_replaced_by_id.state')
    def _compute_rs_einv_correction_in_flight(self):
        """Window in which Odoo counts one sale twice: the original is posted, not reversed, with a live replacement."""
        for move in self:
            replacement = move.rs_einv_replaced_by_id
            move.rs_einv_correction_in_flight = bool(
                move.state == 'posted'
                and move.payment_state != 'reversed'
                and replacement
                and replacement.state != 'cancel'
            )

    def _compute_sql_rs_einv_correction_in_flight(self, table):
        replacement_state = table.rs_einv_replaced_by_id.state
        return SQL("(%s = 'posted' AND %s IS DISTINCT FROM 'reversed' AND %s IS NOT NULL AND %s != 'cancel')", table.state, table.payment_state,
            replacement_state, replacement_state)

    @api.depends('reversal_move_ids')
    def _compute_rs_einv_reversal_count(self):
        for move in self:
            move.rs_einv_reversal_count = len(move.reversal_move_ids)

    @api.depends('rs_einv_last_sync_hash', 'partner_id', 'currency_id', 'invoice_currency_rate', 'invoice_date', 'invoice_line_ids.name',
        'invoice_line_ids.product_id', 'invoice_line_ids.quantity', 'invoice_line_ids.price_total', 'invoice_line_ids.price_subtotal',
        'invoice_line_ids.product_uom_id', 'invoice_line_ids.tax_ids', 'invoice_line_ids.display_type')
    def _compute_has_pending_changes(self):
        for move in self:
            if not move.rs_einv_id:
                move.rs_einv_has_pending_changes = False
            elif not move.rs_einv_last_sync_hash:
                # Legacy record before the hash existed — show as pending.
                move.rs_einv_has_pending_changes = True
            else:
                move.rs_einv_has_pending_changes = (move._rs_compute_line_hash() != move.rs_einv_last_sync_hash)

    @api.depends('state', 'move_type', 'invoice_date', 'partner_id.vat', 'rs_einv_id', 'rs_einv_status', 'rs_einv_skip')
    def _compute_rs_einv_overdue(self):
        """Art.54 (MoF Order #996) 30-day deadline: customer invoices to a TIN partner, not skipped on rs.ge."""
        today = fields.Date.today()
        for move in self:
            if (move.state != 'posted' or move.move_type != 'out_invoice' or not move.partner_id.vat or move.rs_einv_skip):
                move.rs_einv_overdue_days = 0
                move.rs_einv_overdue_state = 'ok'
                continue
            if move.rs_einv_status in _RS_DEADLINE_DONE_STATES:
                move.rs_einv_overdue_days = 0
                move.rs_einv_overdue_state = 'ok'
                continue
            op_date = move.invoice_date
            if not op_date:
                move.rs_einv_overdue_days = 0
                move.rs_einv_overdue_state = 'ok'
                continue
            delta = (today - op_date).days
            move.rs_einv_overdue_days = delta
            if delta >= _RS_DEADLINE_DAYS:
                move.rs_einv_overdue_state = 'overdue'
            elif delta >= _RS_DEADLINE_WARNING_DAYS:
                move.rs_einv_overdue_state = 'warning'
            else:
                move.rs_einv_overdue_state = 'ok'

    @api.model
    def _cron_rs_einv_check_deadlines(self):
        """Any earlier [DEADLINE] log row on the move, whatever its date, blocks a repeat warning."""
        today = fields.Date.today()
        domain = [
            ('state', '=', 'posted'),
            ('move_type', '=', 'out_invoice'),
            ('partner_id.vat', '!=', False),
            ('rs_einv_skip', '=', False),
            ('rs_einv_status', 'not in', _RS_DEADLINE_DONE_STATES),
            ('invoice_date', '<=', fields.Date.subtract(today, days=_RS_DEADLINE_DAYS)),
        ]
        overdue = self.search(domain).filtered(lambda m: m.rs_einv_overdue_state == 'overdue')
        if not overdue:
            return
        marker = "DEADLINE"
        already_logged = set(self.env['rs.einvoice.log'].search([
            ('move_id', 'in', overdue.ids),
            ('name', '=like', '[%s%%' % marker),
        ]).mapped('move_id').ids)
        n_logged = 0
        for move in overdue:
            if move.id in already_logged:
                continue
            move._rs_log("[%s] %s days since posting — past the 30-day deadline (#996 Art.54). Send to RS and Send to buyer immediately to avoid a "
                "penalty." % (marker, move.rs_einv_overdue_days), 'error')
            move._rs_post(_("rs.ge deadline overdue: %(days)s days since posting (past the 30-day #996 Art.54 limit). Send to RS and Send to buyer "
                "immediately to avoid a penalty.") % {'days': move.rs_einv_overdue_days})
            n_logged += 1
        if n_logged:
            _logger.info("rs.einvoice deadline cron: %d overdue invoices logged", n_logged)

    def _rs_compute_line_hash(self):
        self.ensure_one()
        product_lines = self._rs_product_lines()
        header_parts = [self.partner_id.id, self.currency_id.id if self.currency_id else 0,
            self.invoice_date.isoformat() if self.invoice_date else '', self.rs_einv_advance_settlement_mode or 'net']
        if self.currency_id != self.company_currency_id:
            header_parts.append(self.invoice_currency_rate)
        parts = []
        seller = not self.rs_einv_is_buyer_side
        for line in product_lines:
            parts.append([str(line.product_id.id) if line.product_id and seller else (line.name or '').strip(),
                line.product_uom_id.name if line.product_uom_id else '', round(abs(line.quantity or 0.0), 4), round(abs(line.price_total or 0.0), 2),
                round(abs((line.price_total or 0.0) - (line.price_subtotal or 0.0)), 2), tuple(sorted(line.tax_ids.ids)),
                bool(getattr(line, 'is_downpayment', False))])
        parts.sort()
        canonical = json.dumps([header_parts, parts], sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]

    def _rs_pulled_lines_hash(self):
        """Line IDs and names are left out, so a supplier that renumbers its lines does not force a Reimport."""
        self.ensure_one()
        rows = sorted([round(snap.g_number, 4), round(snap.full_amount, 2), round(snap.drg_amount, 2)] for snap in self.rs_einv_pulled_line_ids)
        return hashlib.sha256(json.dumps(rows).encode('utf-8')).hexdigest()[:32]

    def _rs_stamp_sync_hash(self):
        self.ensure_one()
        self.rs_einv_last_sync_hash = self._rs_compute_line_hash()

    def _rs_keep_after_rollback(self, method_name, *args):
        """Re-run in a new cursor only on rollback, with the first queued call's uid and context; a commit drops it."""
        if self.env.context.get('rs_replaying_after_rollback') or not isinstance(self.id, int):
            return
        postrollback = self.env.cr.postrollback
        queue = postrollback.data.get('rs_einvoice_keep')
        if queue is None:
            queue = postrollback.data['rs_einvoice_keep'] = []
            postrollback.add(partial(_rs_replay_after_rollback, self.env.registry, self.env.uid, self.env.context, queue))
        queue.append((self.id, method_name, args))

    def _rs_mark_lines_partial(self):
        self.rs_einv_lines_sync_state = 'partial'
        self._rs_keep_after_rollback('_rs_mark_lines_partial')

    def _rs_log(self, message, level='info'):
        self.env['rs.einvoice.log'].create({
            'move_id': self.id,
            'name': message,
            'level': level,
        })
        if level == _RS_KEEP_LEVEL:
            self._rs_keep_after_rollback('_rs_log', message, level)

    def _rs_post(self, body):
        self.ensure_one()
        try:
            self.message_post(body=body)
        except Exception:
            _logger.exception("rs.ge chatter post failed on move %s", self.id)

    def _rs_product_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(lambda line: line.display_type == 'product')

    def _rs_notify(self, message, level='info', post_chatter=False,
                   activity_xmlid=None, activity_summary=None,
                   activity_note=None, activity_deadline=None):
        self.ensure_one()
        self._rs_log(message, level)
        if not post_chatter and not activity_xmlid:
            return
        side_args = (message, post_chatter, activity_xmlid, activity_summary, activity_note, activity_deadline)
        if level == _RS_KEEP_LEVEL:
            self._rs_keep_after_rollback('_rs_notify_side_channels', *side_args)
        self._rs_notify_side_channels(*side_args)

    def _rs_notify_side_channels(self, message, post_chatter, activity_xmlid, activity_summary, activity_note, activity_deadline):
        try:
            if post_chatter:
                self.message_post(body=message)
            if activity_xmlid:
                self.activity_schedule(activity_xmlid, summary=activity_summary, note=activity_note or message, user_id=self.env.user.id,
                    date_deadline=activity_deadline)
        except Exception:
            _logger.exception("rs.ge notify side-channel failed on move %s", self.id)

    @staticmethod
    def _rs_field_label(record, field_name, fallback='—'):
        value = record[field_name]
        return dict(record._fields[field_name].selection).get(value, value or fallback)

    def _rs_doc_label(self):
        self.ensure_one()
        return _('bill') if self.move_type == 'in_invoice' else _('invoice')

    def _rs_find_other_move_by_rs_id(self, rs_id, use_sudo=False):
        self.ensure_one()
        if not rs_id:
            return self.env['account.move']
        Move = self.env['account.move'].sudo() if use_sudo else self.env['account.move']
        return Move.search([('rs_einv_id', '=', str(rs_id)), ('company_id', '=', self.company_id.id), ('id', '!=', self.id)], limit=1)

    def _rs_awaiting_pull(self):
        """No rs.ge status yet (never pulled), so the rs.ge guards treat the vendor document as not linked."""
        self.ensure_one()
        return self.rs_einv_is_buyer_side and bool(self.rs_einv_id) and not self.rs_einv_status

    def _rs_is_sale_correction(self):
        self.ensure_one()
        return self.move_type == 'out_invoice' and self.rs_einv_replacement_mode == 'correction' and bool(self.rs_einv_replaces_id)

    @staticmethod
    def _rs_extract_status_triplet(result):
        return (str(getattr(result, 'status', '') or ''), getattr(result, 'f_series', '') or '', _rs_clean_number(getattr(result, 'f_number', '')))

    def _rs_get_fx_rate(self, target_date=None):
        self.ensure_one()
        target_date = target_date or self.invoice_date or fields.Date.today()
        return self.env['res.currency.rate'].sudo().search([
            ('currency_id', '=', self.currency_id.id),
            ('company_id', 'in', [False, self.company_id.id]),
            ('name', '<=', target_date),
        ], order='name desc', limit=1)

    def _rs_assert_no_blocking_replacement(self, original, replacement, guidance):
        if replacement.state == 'cancel':
            raise UserError(_("%(original)s has a cancelled replacement (%(replacement)s). Use 'Clear Cancelled Replacement' first.",
                original=original.display_name or original.name or '—', replacement=replacement.display_name or replacement.name or '—'))
        raise UserError(_("%(original)s already has a replacement (%(replacement)s, %(mode)s). %(guidance)s",
            original=original.display_name or original.name or '—', replacement=replacement.display_name or replacement.name or '—',
            mode=self._rs_field_label(replacement, 'rs_einv_replacement_mode'), guidance=guidance))

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        for move, vals in zip(moves, vals_list):
            if (move.move_type == 'out_invoice' and not move.rs_einv_is_advance and move._rs_is_downpayment_invoice()):
                move.rs_einv_is_advance = True
            if (move.move_type in ('out_refund', 'in_refund')
                    and not move.rs_einv_is_advance
                    and move.reversed_entry_id
                    and move.reversed_entry_id.rs_einv_is_advance):
                move.rs_einv_is_advance = True
            if (move.move_type == 'out_refund' and not move.reversed_entry_id and not move.rs_einv_skip and move._rs_is_downpayment_invoice()):
                move.write({'rs_einv_skip': True, 'rs_einv_skip_reason': 'down_payment'})
            if (move.move_type == 'out_invoice'
                    and 'rs_einv_advance_settlement_mode' not in vals
                    and not move.rs_einv_is_advance
                    and move._rs_has_downpayment_offset_lines()
                    and move._rs_native_advance_eligible()):
                move.rs_einv_advance_settlement_mode = 'native_attach'
        return moves

    def _rs_changed_immutable_fields(self, vals):
        self.ensure_one()
        changed = []
        for field_name in _RS_IMMUTABLE_AFTER_RS:
            if field_name not in vals:
                continue
            current = self[field_name]
            new_val = vals[field_name]
            if hasattr(current, 'id'):
                same = bool(new_val) and current.id == new_val
            else:
                same = current == new_val
            if not same:
                changed.append(field_name)
        return changed

    def write(self, vals):
        """Guards rs.ge fields: once on rs.ge they lock, except a never-pulled vendor bill (_rs_awaiting_pull)."""
        if 'rs_einv_id' in vals:
            self._rs_write_check_id(vals)
        if 'rs_einv_advance_settlement_mode' in vals:
            self._rs_write_check_settlement_mode(vals)
        self._rs_write_check_immutable_fields(vals)
        self._rs_write_check_skip_toggle(vals)
        if 'rs_einv_skip' in vals and not vals.get('rs_einv_skip'):
            if 'rs_einv_skip_reason' not in vals:
                vals = dict(vals)
                vals['rs_einv_skip_reason'] = False
        return super().write(vals)

    def _rs_write_check_id(self, vals):
        """rs.ge id cannot be cleared or changed unless the rs_allow_id_overwrite context is set (Delete on RS)."""
        new_id = vals.get('rs_einv_id')
        allow = self.env.context.get('rs_allow_id_overwrite')
        for move in self:
            old_id = move.rs_einv_id
            if old_id and not allow and not move._rs_awaiting_pull():
                if not new_id:
                    raise UserError(_("Cannot clear RS Invoice ID %s directly. Use "
                        "Delete on RS, or Resolve Orphan if the record is broken.") % old_id)
                if str(old_id) != str(new_id):
                    raise UserError(_("Cannot change the RS Invoice ID directly (was %s, "
                        "tried %s). Use Delete on RS or Resolve Orphan first.") % (old_id, new_id))
            if allow and old_id and (not new_id or str(old_id) != str(new_id)):
                _msg = _("RS Invoice ID overwritten via context "
                    "bypass (was: %(old)s, now: %(new)s) by %(user)s.") % {'old': old_id, 'new': new_id or '—', 'user': self.env.user.display_name}
                move._rs_notify(_msg, 'warning', post_chatter=True)

    def _rs_write_check_settlement_mode(self, vals):
        new_mode = vals.get('rs_einv_advance_settlement_mode') or 'net'
        for move in self:
            old_mode = move.rs_einv_advance_settlement_mode or 'net'
            if old_mode == new_mode:
                continue
            if move.rs_einv_id and move.rs_einv_status != '0':
                raise UserError(_("Cannot change Advance Settlement on '%(name)s' — already on rs.ge (status %(status)s). Change it only while the "
                    "record is Draft.", name=move.display_name or move.name or '—', status=_rs_status_label(move.rs_einv_status)))
            if old_mode == 'native_attach' and new_mode == 'net':
                successful = move.rs_einv_advance_settlement_ids.filtered(lambda s: s.rs_status == '200')
                if successful:
                    raise UserError(_("Cannot switch '%(name)s' to net — advances are already attached on rs.ge. Detach them or Delete on RS first.",
                        name=move.display_name or move.name or '—'))

    def _rs_write_check_immutable_fields(self, vals):
        if any(f in vals for f in _RS_IMMUTABLE_AFTER_RS):
            for move in self:
                if not move.rs_einv_id or move.rs_einv_skip or move._rs_awaiting_pull():
                    continue
                changed = move._rs_changed_immutable_fields(vals)
                if not changed:
                    continue
                raise UserError(_("Cannot change '%(field)s' on '%(name)s' — it is on rs.ge "
                    "(ID %(rs_id)s, status %(status)s). Delete it on RS first.", field=changed[0], name=move.display_name or move.name or '—',
                    rs_id=move.rs_einv_id, status=_rs_status_label(move.rs_einv_status)))

    def _rs_write_check_skip_toggle(self, vals):
        if 'rs_einv_skip' in vals:
            new_skip = vals.get('rs_einv_skip')
            for move in self:
                if move.state != 'posted' or bool(new_skip) == bool(move.rs_einv_skip):
                    continue
                raise UserError(_("Cannot toggle 'Skip rs.ge' on posted '%(name)s' — reset to draft, toggle, then re-post.",
                    name=move.display_name or move.name))

    def unlink(self):
        """Refuses to delete a live rs.ge move, which would leave an orphan; never-pulled bills pass."""
        for move in self:
            if move.rs_einv_id and not move.rs_einv_skip and not move._rs_awaiting_pull():
                raise UserError(_("Cannot delete '%s' — it is on rs.ge (ID %s, status %s). Use Delete on RS "
                    "first, or tick 'Skip rs.ge'.") % (move.display_name or move.name or '—', move.rs_einv_id, _rs_status_label(move.rs_einv_status)))
        return super().unlink()

    def _rs_is_downpayment_invoice(self):
        """Advance invoices, offset CNs and CNs reversing an advance: all product lines are down-payment lines."""
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        line_model = self.env['account.move.line']
        if 'is_downpayment' not in line_model._fields:
            return False
        product_lines = self._rs_product_lines()
        if not product_lines:
            return False
        return all(line.is_downpayment for line in product_lines)

    def _rs_has_downpayment_offset_lines(self):
        """True when offset rows are mixed with product lines; the rs.ge payload must subtract the offset."""
        self.ensure_one()
        line_model = self.env['account.move.line']
        if 'is_downpayment' not in line_model._fields:
            return False
        product_lines = self._rs_product_lines()
        has_dp = any(l.is_downpayment for l in product_lines)
        has_regular = any(not l.is_downpayment for l in product_lines)
        return has_dp and has_regular

    def _rs_uses_native_advance_attach(self):
        self.ensure_one()
        return (
            self.move_type == 'out_invoice'
            and self.rs_einv_advance_settlement_mode == 'native_attach'
            and self._rs_has_downpayment_offset_lines()
            and not self.rs_einv_is_advance
        )

    def _post(self, soft=True):
        """Refuses posts rs.ge would contradict; after posting, pushes a Sent (Pending) invoice's edits to rs.ge.
        A supplier correction is booked in the month it is accepted, the same month its original is reversed, so the declarations match rs.ge."""
        if not self.env.context.get('rs_buyer_accept_in_progress'):
            unaccepted = self.filtered(lambda m:
                m.rs_einv_is_buyer_side
                and m.rs_einv_id
                and not m.rs_einv_skip
                and m.rs_einv_status not in RS_ACCEPTED
            )
            if unaccepted:
                names = ", ".join(m.display_name or m.name or str(m.id) for m in unaccepted[:3])
                if len(unaccepted) > 3:
                    names += _(" (and %d more)") % (len(unaccepted) - 3)
                raise UserError(_("Cannot post buyer-side document(s) still pending on rs.ge: %(names)s. Use 'Accept on rs.ge' — it confirms and "
                    "posts in one step.", names=names))
        for move in self.filtered(lambda m: m.rs_einv_is_buyer_side and m.rs_einv_id and not m.rs_einv_skip and m.state == 'draft'):
            if move.rs_einv_pulled_lines_hash and move.rs_einv_pulled_line_ids and move._rs_pulled_lines_hash() != move.rs_einv_pulled_lines_hash:
                raise UserError(_("The supplier changed %s on rs.ge after the bill took its lines. Click Reimport Lines, check the bill and post "
                    "it again.", move.display_name))
        corrections_to_date = self.filtered(lambda m: m.rs_einv_is_buyer_side and m.state == 'draft' and m.rs_einv_replaces_id
            and m.rs_einv_status in ('5', '8') and not m.posted_before)
        corrections_to_date.date = fields.Date.context_today(self)
        draft_corrections = self.filtered(lambda m: m.state == 'draft' and m._rs_is_sale_correction())
        if draft_corrections and not self.env.context.get('rs_post_accepted_correction'):
            names = ", ".join(draft_corrections.mapped('display_name'))
            raise UserError(_("%s is posted automatically when the buyer accepts the correction on rs.ge.", names))
        for move in self.filtered(lambda m: m.move_type == 'out_invoice' and m.rs_einv_replaces_id):
            move._rs_assert_replacement_cancel_accepted()
        for move in self.filtered(
            lambda m: m.move_type in ('out_refund', 'in_refund')
                      and m.reversed_entry_id
                      and not m.rs_einv_id
                      and m.reversed_entry_id.rs_einv_replaced_by_id
                      and not (m.rs_einv_skip
                               and m.rs_einv_skip_reason == 'replacement')
        ):
            original = move.reversed_entry_id
            replacement = original.rs_einv_replaced_by_id
            move._rs_assert_no_blocking_replacement(original, replacement,
                _("Post corrections on the replacement invoice instead. Posting another credit note on the old invoice would create a duplicate "
                "local accounting reduction."))
        rs_tracked_cns = self.filtered(
            lambda m: m.move_type in ('out_refund', 'in_refund')
                      and m.reversed_entry_id
                      and not m.rs_einv_id
                      and not (m.rs_einv_skip
                               and m.rs_einv_skip_reason
                                   in _RS_NON_PHYSICAL_SKIP_REASONS)
        )
        originals_to_refresh = rs_tracked_cns.mapped('reversed_entry_id').filtered(lambda original: original.rs_einv_id)
        for original in originals_to_refresh:
            try:
                original._rs_safe_refresh_status()
            except (UserError, ValidationError) as e:
                original._rs_log("Could not refresh rs.ge status before posting a linked credit note: %s. Posted on the last-known status — run "
                    "Check Status on the original afterwards." % e, 'warning')
        for move in rs_tracked_cns:
            move._rs_check_cn_post_preconditions(refresh_original=False)
        for move in self.filtered(lambda m:
                m.move_type == 'out_invoice'
                and m.rs_einv_id
                and not m.rs_einv_skip
                and m.rs_einv_status == '1'
                and m.rs_einv_has_pending_changes):
            move._rs_assert_edits_can_reach_rs()
        posted = super()._post(soft=soft)
        posted._rs_auto_sync_pending_sent_edits()
        return posted

    def _rs_assert_edits_can_reach_rs(self):
        self.ensure_one()
        self._rs_safe_refresh_status()
        if self.rs_einv_status not in ('0', '1', '4'):
            raise UserError(_("Cannot post %(name)s with edited lines: the buyer confirmed it on rs.ge in the meantime (rs.ge status: %(status)s), "
                "so the edits can no longer be sent. Restore the lines rs.ge holds and post, then use Credit Note > 'Replace RS invoice with a "
                "corrected invoice' for the change.", name=self.display_name, status=_rs_status_label(self.rs_einv_status)))

    def _rs_auto_sync_pending_sent_edits(self):
        """A failure only warns and leaves the edits pending for a manual Update on RS."""
        for move in self.filtered(lambda m:
                m.move_type == 'out_invoice'
                and m.rs_einv_id
                and not m.rs_einv_skip
                and m.rs_einv_status == '1'
                and m.rs_einv_has_pending_changes):
            error = None
            try:
                with self.env.cr.savepoint():
                    move.action_rs_edit()
            except (UserError, ValidationError) as e:
                error = e.args[0] if e.args else str(e)
            except Exception as e:
                _logger.exception("Auto-sync after post crashed on move %s (rs_id=%s)", move.id, move.rs_einv_id)
                error = str(e)
            if error:
                move._rs_notify("Auto-sync of edited lines to rs.ge after posting "
                    "failed: %s. Click 'Update on RS' to push the changes manually." % error, 'warning', post_chatter=True)

    def _rs_check_cn_post_preconditions(self, refresh_original=True):
        self.ensure_one()
        original = self.reversed_entry_id
        if not original:
            return

        if original.rs_einv_replaced_by_id:
            self._rs_assert_no_blocking_replacement(original, original.rs_einv_replaced_by_id,
                _("Create the credit note on the replacement invoice, or finish that replacement flow before correcting this document again."))

        if original.rs_einv_id and refresh_original:
            original._rs_safe_refresh_status()
        if original.rs_einv_id and original.rs_einv_status:
            if original.rs_einv_status not in ('2', '3'):
                raise UserError(_("Original %(name)s is at rs.ge status %(status)s — corrections need Confirmed or Corrected. Or tick 'Skip rs.ge' "
                    "for a books-only credit.", name=original.display_name or original.name, status=_rs_status_label(original.rs_einv_status)))
            if original.rs_einv_status == '3':
                pending = original._rs_find_pending_correction_blocker(exclude_move=self)
                if pending:
                    raise UserError(_("Another correction is in flight on rs.ge: %(name)s (ID %(rs_id)s, status %(status)s). Finish or Delete it on "
                        "RS first.", name=pending.display_name or pending.name or '—', rs_id=pending.rs_einv_id or '—',
                        status=_rs_status_label(pending.rs_einv_status)))
                original._rs_assert_chain_has_local_confirmed_correction()

    def _rs_assert_can_be_reversed(self):
        self.ensure_one()
        if self.rs_einv_skip or not self.rs_einv_id:
            return
        replaced_by = self.rs_einv_replaced_by_id
        if replaced_by:
            mode_label = self._rs_field_label(replaced_by, 'rs_einv_replacement_mode')
            raise UserError(_("This invoice already has a replacement (%(name)s, %(mode)s). Continue from there, or finish/delete that flow first.",
                name=replaced_by.display_name or replaced_by.name or '—', mode=mode_label))
        status = self.rs_einv_status or ''
        if status in ('2', '3'):
            if status == '3':
                pending = self._rs_find_pending_correction_blocker()
                if pending:
                    raise UserError(_("Another correction is in flight on rs.ge: %(blk_name)s (ID %(rs_id)s, status %(status)s). Finish or Delete it "
                        "on RS first.", blk_name=pending.display_name or pending.name or '—', rs_id=pending.rs_einv_id or '—',
                        status=_rs_status_label(pending.rs_einv_status)))
                self._rs_assert_chain_has_local_confirmed_correction()
            return
        raise UserError(_("Original %(name)s is at status %(status)s — credit notes need Confirmed or Corrected. Or create it with 'Skip rs.ge' "
            "ticked.", name=self.display_name or self.name, status=_rs_status_label(status)))

    def _rs_locked_on_rs(self):
        self.ensure_one()
        if not self.rs_einv_id or self.rs_einv_skip:
            return False
        candidates = [self.rs_einv_status]
        if isinstance(self.id, int):
            invoice_children = self.env['account.move'].search([
                ('rs_einv_replaces_id', '=', self.id),
                ('rs_einv_replacement_mode', '=', 'correction'),
                ('rs_einv_id', '!=', False),
            ])
            for inv in invoice_children:
                candidates.append(inv.rs_einv_status)
        return any(s in RS_LOCKED_STATES for s in candidates if s)

    def _rs_raise_if_locked(self, action_label, allow_pending=False):
        """allow_pending lets a Sent (Pending) original through: rs.ge keeps it editable until the buyer answers,
        and a pending vendor document, whose local draft changes nothing on rs.ge."""
        self.ensure_one()
        if self.rs_einv_pending_action_at:
            raise UserError(_("Cannot %(action)s — an rs.ge action is still pending (started %(when)s). Click Resolve Orphan or Dismiss Pending on "
                "the RS E-Invoice tab first.", action=action_label, when=self.rs_einv_pending_action_at))
        if (self.env.context.get('rs_skip_lock_check') or not self.rs_einv_id or self.rs_einv_skip):
            return
        self._rs_safe_refresh_status()
        if allow_pending and self.rs_einv_is_buyer_side and self.rs_einv_status in RS_PENDING_BUYER:
            return
        if allow_pending and self.rs_einv_status == '1':
            self._rs_log("Reset to draft while rs.ge status is Sent (Pending) — buyer has not acted yet. Edit the lines and re-post; the changes "
                "sync to rs.ge automatically (or click Update on RS).", 'warning')
            return
        if self._rs_locked_on_rs():
            raise UserError(_("Cannot %s — it is live on rs.ge (ID %s, status %s). Cancel or Delete on RS first.", action_label, self.rs_einv_id,
                _rs_status_label(self.rs_einv_status)))
        if self.rs_einv_status == '7':
            raise UserError(_("Cannot %(action)s — cancelled on rs.ge (ID %(rs_id)s) and buyer-confirmed. Create a new invoice instead.",
                action=action_label, rs_id=self.rs_einv_id or '—'))

    @api.depends('rs_einv_id', 'rs_einv_status', 'move_type')
    def _compute_show_reset_to_draft_button(self):
        """Linked vendor bills leave posted only through the rs.ge flows (Reject, supplier cancellation)."""
        super()._compute_show_reset_to_draft_button()
        for move in self:
            if (move.rs_einv_id and move.move_type in ('in_invoice', 'in_receipt')
                    and not (move.state == 'cancel' and move.rs_einv_status in RS_PENDING_BUYER)):
                move.show_reset_to_draft_button = False

    def button_draft(self):
        resent = self.filtered(lambda m: m.state == 'cancel' and m.rs_einv_is_buyer_side and m.rs_einv_id and not m.rs_einv_skip)
        for move in self:
            if (move.rs_einv_skip and move.rs_einv_skip_reason == 'replacement'):
                raise UserError(_("Cannot reset '%(name)s' to draft — it is the paired reversal of a correction and must mirror the original. Undo "
                    "the replacement invoice instead.", name=move.display_name or move.name or '—'))
            move._rs_raise_if_locked(_('reset to draft'), allow_pending=True)
        res = super().button_draft()
        for move in resent:
            move._rs_merge_pulled_to_bill_lines()
        return res

    def button_cancel(self):
        for move in self:
            move._rs_raise_if_locked(_('cancel'))
        return super().button_cancel()

    def _rs_get_service(self, check_auth=False):
        """Service for the document's company, not the active one; check_auth validates login before the first write."""
        service = self.env['rs.soap.service'].with_company(self.company_id)
        if check_auth:
            service._check_auth()
        return service

    @property
    def _rs_inv_id_int(self):
        return int(self.rs_einv_id) if self.rs_einv_id else 0

    def _rs_chain_parent(self, modes=('correction',)):
        self.ensure_one()
        if self.reversed_entry_id:
            return self.reversed_entry_id
        if self.rs_einv_replacement_mode in modes:
            return self.rs_einv_replaces_id
        return self.env['account.move']

    def _rs_get_correction_base_id(self):
        """rs.ge ID the next correction chains onto: latest accepted replacement (status 8), else the original."""
        self.ensure_one()
        epoch = fields.Datetime.to_datetime('1970-01-01 00:00:00')
        candidates = []
        inv_confirmed = self._rs_find_invoice_corrections_of(self, status='8', exclude_self=True)
        for inv in inv_confirmed:
            k = inv._rs_inv_id_int
            if k > 0:
                candidates.append((inv.create_date or epoch, inv.id, k))
        if candidates:
            candidates.sort(reverse=True)
            local_head = candidates[0][2]
        else:
            local_head = self._rs_inv_id_int
        try:
            service = self._rs_get_service()
            verify = service.get_invoice(local_head)
            verify_status = str(getattr(verify, 'status', ''))
        except Exception as e:
            _logger.warning("Could not verify correction base %s against rs.ge: %s", local_head, e)
            return local_head
        if verify_status and verify_status not in RS_ACCEPTED:
            self._rs_log("Chain base %s on rs.ge is at status '%s' — expected an accepted base (2/3/8). The chain may have moved on; click 'Check "
                "Status' before retrying." % (local_head, _rs_status_label(verify_status)), 'warning')
            raise UserError(_("rs.ge shows record %(rs_id)s at status '%(status)s'. A correction must chain on an accepted record. Click 'Check "
                "Status' to refresh and try again.", rs_id=local_head, status=_rs_status_label(verify_status)))
        return local_head

    def _rs_find_pending_correction_blocker(self, exclude_move=None):
        """Status 6 ('Cancelled (Sent)') counts: rs.ge awaits the buyer, so a new correction is unsafe."""
        self.ensure_one()
        if not isinstance(self.id, int):
            return self.env['account.move']
        in_flight = ('4', '5', '6')
        pending = self._rs_find_invoice_corrections_of(self, status=in_flight, exclude_self=bool(exclude_move))
        if exclude_move:
            pending = pending.filtered(lambda m: m.id != exclude_move.id)
        return pending[:1]

    def _rs_find_invoice_corrections_of(self, original, status=None, exclude_self=False):
        if not original or not original.id or not isinstance(original.id, int):
            return self.env['account.move']
        domain = [
            ('state', '!=', 'cancel'),
            ('rs_einv_id', '!=', False),
            ('rs_einv_replaces_id', '=', original.id),
            ('rs_einv_replacement_mode', '=', 'correction'),
        ]
        if status:
            if isinstance(status, (list, tuple, set)):
                domain.append(('rs_einv_status', 'in', list(status)))
            else:
                domain.append(('rs_einv_status', '=', status))
        if exclude_self:
            domain.append(('id', '!=', self.id))
        return self.env['account.move'].search(domain).sorted(key=lambda c: c.id, reverse=True)

    def _rs_assert_chain_has_local_confirmed_correction(self):
        self.ensure_one()
        if (self.rs_einv_status != '3' or self._rs_find_invoice_corrections_of(self, status='8')):
            return
        raise UserError(_("Cannot continue the correction chain for %(name)s — rs.ge shows it corrected, but Odoo has no accepted correction linked. "
            "Click Check Status first.", name=self.display_name or self.name or '—'))

    def _rs_push_header_to_rs(self, service, target_id, label=None):
        seller_un_id = service._rs_company_un_id()
        buyer_un_id = service._rs_partner_un_id(self.partner_id)
        variant, note = self._rs_pick_save_variant()
        result = service.save_invoice(inv_id=target_id, operation_date=_to_rs_dt(self.invoice_date or fields.Date.today()), seller_un_id=seller_un_id,
            buyer_un_id=buyer_un_id, variant=variant, note=note)
        if not self._rs_save_succeeded(result):
            self._rs_log("Failed to push header to RS (variant=%s, target=%s, label=%s): %s" % (variant, target_id, label or '—', result), 'error')
            raise UserError(_("Could not update the header on rs.ge (ID %s). See RS Logs.", target_id))
        return result

    def _rs_pick_save_variant(self):
        self.ensure_one()
        if self.rs_einv_is_advance:
            return 'advance', ''
        if self.rs_einv_note:
            return 'note', self.rs_einv_note
        return 'regular', ''

    @staticmethod
    def _rs_save_succeeded(result):
        return any([getattr(result, 'save_invoiceResult', False), getattr(result, 'save_invoice_aResult', False),
            getattr(result, 'save_invoice_nResult', False)])

    @staticmethod
    def _rs_send_succeeded(result, flag_name='change_invoice_statusResult'):
        """A zeep result whose flag is False is a failure, so truthiness of the result is not enough."""
        if result is None:
            return False
        if isinstance(result, bool):
            return result
        flag = getattr(result, flag_name, None)
        if flag is None:
            return bool(result)
        return bool(flag)

    def _rs_target_is_correction(self, target_id):
        if not target_id:
            return False
        target_str = str(target_id)
        correction_move = self.env['account.move'].search([
            ('rs_einv_id', '=', target_str),
            ('company_id', '=', self.company_id.id),
            ('rs_einv_replaces_id', '!=', False),
            ('rs_einv_replacement_mode', '=', 'correction'),
        ], limit=1)
        if correction_move:
            return correction_move.rs_einv_status in ('4', '5', '8')
        if str(self.rs_einv_id or '') == target_str:
            return self.rs_einv_status in ('4', '5', '8')
        return False

    def _rs_mark_pending(self, action_code):
        """Commits at once, so the marker survives a rolled-back rs.ge request for orphan recovery."""
        self.ensure_one()
        self.rs_einv_pending_action = action_code
        self.rs_einv_pending_action_at = fields.Datetime.now()
        self.env.cr.commit()

    def _rs_clear_pending(self):
        self.ensure_one()
        if self.rs_einv_pending_action or self.rs_einv_pending_action_at:
            self.rs_einv_pending_action = False
            self.rs_einv_pending_action_at = False

    def _rs_acquire_row_lock(self, action_label):
        self.ensure_one()
        if not isinstance(self.id, int):
            return
        try:
            self.lock_for_update()
        except LockError:
            raise UserError(_("Another rs.ge action is still running on this document. Wait a moment and try %s again.", action_label))

    def _rs_relock_after_commit(self):
        """Re-lock one move (SKIP LOCKED) for the post-commit tail; empty if busy/gone."""
        self.ensure_one()
        self.env.invalidate_all()
        move = self.exists()
        return move.try_lock_for_update(limit=1) if move else move

    @staticmethod
    def _rs_round(amount, places=2):
        """ROUND_HALF_UP as Georgian VAT requires (round() is half-even); use for every rs.ge and tax value."""
        if amount is None:
            return 0.0
        try:
            d = Decimal(str(amount))
        except (TypeError, ValueError, ArithmeticError):
            return 0.0
        if places > 0:
            quant = Decimal('1.' + '0' * places)
        else:
            quant = Decimal('1')
        return float(d.quantize(quant, rounding=ROUND_HALF_UP))

    def _rs_safe_refresh_status(self):
        """A network failure stops the caller with a UserError: acting on a status that was not checked could contradict rs.ge."""
        self.ensure_one()
        if not self.rs_einv_id:
            if self.rs_einv_pending_action:
                self._rs_log("Refresh skipped — pending rs.ge action '%s' has no linked RS Invoice ID. Click 'Resolve Orphan' to locate the orphan "
                    "draft on rs.ge and link it." % (self.rs_einv_pending_action,), 'warning')
            return
        try:
            self.action_rs_refresh_status()
        except _TRANSIENT_EXCEPTIONS as e:
            _logger.warning("rs.ge status check failed for move %s: %s", self.id, e)
            raise UserError(_("rs.ge cannot be reached to check the status of %s. Try again when it is back.", self.display_name)) from e
