import logging
from datetime import datetime, time, timedelta

from markupsafe import Markup, escape

from odoo import fields, models, Command, _
from odoo.exceptions import UserError

from ..models.account_move import RS_PENDING_BUYER, rs_to_int, rs_to_float
from ..models.rs_einvoice_cron import _parse_dt_aware, _rs_find_partner_by_tin, _rs_row_get, _to_local_date, _to_naive_utc

_logger = logging.getLogger(__name__)

INBOX_STATUS = [
    ('-1', 'Deleted'),
    ('0', 'New / Draft'),
    ('1', 'Sent (awaiting your accept)'),
    ('2', 'Confirmed'),
    ('3', 'Corrected Original'),
    ('4', 'Correction Draft'),
    ('5', 'Correction Sent'),
    ('6', 'Cancellation Sent'),
    ('7', 'Cancellation Confirmed'),
    ('8', 'Correction Confirmed'),
]


def _rs_ambiguous_vendor_note(env, tin, vendors):
    names = ', '.join(p.display_name or '—' for p in vendors[:3])
    if len(vendors) > 3:
        names += env._(' (and %d more)') % (len(vendors) - 3)
    return env._("Multiple vendors share TIN %(tin)s: %(names)s. Pick a vendor on this row before importing.") % {'tin': tin, 'names': names}


class RsBuyerInboxWizard(models.TransientModel):
    _name = 'rs.einvoice.inbox.wizard'
    _description = 'rs.ge Buyer Inbox'

    date_from = fields.Date(string='Issued From', required=True, default=lambda self: fields.Date.today() - timedelta(days=30),
        help="Filter by rs.ge invoice registration date. Defaults to the last 30 days.")
    date_to = fields.Date(string='Issued To', required=True, default=lambda self: fields.Date.today())
    seller_tin = fields.Char(string='Seller TIN (optional)', help="Filter to a single supplier by their TIN. Leave empty for all suppliers.")
    invoice_no = fields.Char(string='Invoice Number (optional)', help="rs.ge invoice number fragment.")
    only_actionable = fields.Boolean(string='Action-Required Only', default=True,
        help="Show only records awaiting your accept (Sent or Correction Sent). Untick to see already-confirmed and historical records too.")
    line_ids = fields.One2many('rs.einvoice.inbox.line', 'wizard_id', string='Found Invoices')
    last_search_info = fields.Char(string='Last Search', readonly=True)

    def _compute_display_name(self):
        for wizard in self:
            wizard.display_name = _("rs.ge Inbox (Buyer)")

    def _resolve_company_un_id(self, service):
        """The company's rs.ge taxpayer id; the inbox lists invoices addressed to it, whatever login was used."""
        return service._rs_company_un_id()

    def action_search(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("'Issued From' must be on or before 'Issued To'."))

        service = self.env['rs.soap.service']
        service._check_auth()
        un_id = self._resolve_company_un_id(service)

        s_dt = datetime.combine(self.date_from, time.min)
        e_dt = datetime.combine(self.date_to, time.max)
        # rs.ge records operations per month; reusing the issue window drops the row.
        op_s_dt = s_dt - timedelta(days=400)
        op_e_dt = e_dt + timedelta(days=400)
        rows = service.get_buyer_invoices(un_id=un_id, s_dt=s_dt, e_dt=e_dt, op_s_dt=op_s_dt, op_e_dt=op_e_dt, invoice_no=self.invoice_no or '',
            sa_ident_no=self.seller_tin or '')

        if self.only_actionable:
            rows = [r for r in rows if str(r.get('status', '')) in RS_PENDING_BUYER]

        Move = self.env['account.move'].sudo()

        self.line_ids.unlink()

        rs_ids = {str(_rs_row_get(row, 'rs_id') or '').strip() for row in rows} - {''}
        existing_by_rs_id = {move.rs_einv_id: move for move in Move.search([
            ('rs_einv_id', 'in', list(rs_ids)),
            ('company_id', '=', self.env.company.id),
        ])}
        vendors_by_tin = {}

        line_vals = []
        seen_rs_ids = set()
        for row in rows:
            rs_id = str(_rs_row_get(row, 'rs_id') or '').strip()
            if not rs_id or rs_id in seen_rs_ids:
                continue
            seen_rs_ids.add(rs_id)

            seller_tin_raw = str(_rs_row_get(row, 'seller_tin') or '').strip()
            if seller_tin_raw not in vendors_by_tin:
                vendors_by_tin[seller_tin_raw] = _rs_find_partner_by_tin(self.env, seller_tin_raw, self.env.company.id)
            partner, ambiguous = vendors_by_tin[seller_tin_raw]
            existing = existing_by_rs_id.get(rs_id, Move)

            op_dt_aware = _parse_dt_aware(_rs_row_get(row, 'operation_dt'))
            reg_dt_aware = _parse_dt_aware(_rs_row_get(row, 'reg_dt'))
            note = ''
            selected = not existing
            if ambiguous:
                note = _rs_ambiguous_vendor_note(self.env, seller_tin_raw, ambiguous)
                selected = False
            line_vals.append({
                'wizard_id': self.id,
                'rs_inv_id': rs_id,
                'f_series': _rs_row_get(row, 'series') or '',
                'f_number': _rs_row_get(row, 'number') or '',
                'reg_dt': _to_naive_utc(reg_dt_aware) or False,
                'operation_dt': _to_naive_utc(op_dt_aware) or False,
                'operation_date': _to_local_date(op_dt_aware) or False,
                'status': str(_rs_row_get(row, 'status') or '') or False,
                'seller_tin': seller_tin_raw,
                'seller_name': _rs_row_get(row, 'seller_name') or '',
                'k_id': rs_to_int(_rs_row_get(row, 'k_id'), -1),
                'k_type': max(rs_to_int(_rs_row_get(row, 'k_type'), 0), 0),
                'amount': rs_to_float(_rs_row_get(row, 'amount')),
                'partner_id': partner.id if partner else False,
                'existing_move_id': existing.id if existing else False,
                'already_imported': bool(existing),
                'selected': selected,
                'import_note': note,
            })

        if line_vals:
            self.env['rs.einvoice.inbox.line'].create(line_vals)

        self.last_search_info = _("Found %(count)d invoice(s) between %(from)s "
            "and %(to)s") % {'count': len(line_vals), 'from': fields.Date.to_string(self.date_from), 'to': fields.Date.to_string(self.date_to)}

    def action_toggle_all(self):
        self.ensure_one()
        self.line_ids.selected = not all(self.line_ids.mapped('selected'))

    def action_import_selected(self):
        """Each ticked row runs the regular buyer-side Pull, with its party and status guards."""
        self.ensure_one()
        candidates = self.line_ids.filtered(lambda l: l.selected and not l.already_imported)
        if not candidates:
            raise UserError(_("Tick at least one row that has not been imported yet."))

        Move = self.env['account.move']
        purchase_journal = self.env['account.journal'].search([('type', '=', 'purchase'), ('company_id', '=', self.env.company.id)],
            order='sequence, id', limit=1)
        if not purchase_journal:
            raise UserError(_("No Purchase journal is configured for company %s. Set one up under Accounting > Configuration > Journals before "
                "importing vendor bills from rs.ge.", self.env.company.display_name))

        preview_candidates = []
        loop_candidates = []
        for line in candidates:
            if not ((line.k_id and line.k_id > 0) or line.k_type):
                loop_candidates.append(line)
                continue
            parent = line._rs_parent_bill()

            correction_status_ok = (line.status or '') in ('5', '8')
            if (parent and parent.state == 'posted' and correction_status_ok and not parent._rs_check_cancel_reissue_blockers()):
                preview_candidates.append((line, parent))
                continue
            loop_candidates.append(line)

        created_moves = Move.browse()
        error_notes = []
        for line in loop_candidates:
            note, move = line._do_import(Move, purchase_journal)
            line.import_status = 'imported' if move else 'error'
            line.import_note = note or ''
            if move:
                line.existing_move_id = move.id
                line.already_imported = True
                line.selected = False
                created_moves |= move
            elif note:
                error_notes.append("• %s (%s): %s" % (line.rs_inv_id or '—', line.f_series or line.f_number or line.seller_name or '—', note))

        if preview_candidates:
            preview = self.env['rs.einvoice.replace.preview'].create({
                'line_ids': [Command.create({
                    'parent_move_id': preview_parent.id,
                    'parent_rs_id': preview_parent.rs_einv_id or '',
                    'parent_amount': preview_parent.amount_total,
                    'parent_state': preview_parent.state,
                    'correction_rs_id': preview_line.rs_inv_id,
                    'correction_amount': preview_line.amount,
                    'correction_k_type': (str(preview_line.k_type) if preview_line.k_type else ''),
                    'correction_status': preview_line.status or '',
                }) for preview_line, preview_parent in preview_candidates],
            })

            for preview_line, preview_parent in preview_candidates:
                preview_line.import_status = 'pending'
                preview_line.import_note = _("Preview open — confirm or cancel in the dialog. "
                    "Original %s will be cancelled and a new draft created.") % (preview_parent.display_name or '—')
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'rs.einvoice.replace.preview',
                'res_id': preview.id,
                'view_mode': 'form',
                'target': 'new',
            }

        if not created_moves:
            message = _("No vendor bills were imported.")
            if error_notes:
                message = (_("No vendor bills were imported. Reasons:\n\n") + "\n".join(error_notes))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Import Selected"),
                    'message': message,
                    'type': 'warning',
                    'sticky': True,
                    # No 'next': the client navigates only if one is returned (action_plugin.js); omit it to stay here.
                },
            }

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Imported Vendor Bills'),
            'res_model': 'account.move',
            'domain': [('id', 'in', created_moves.ids)],
            'view_mode': 'list,form',
            'context': {'create': False},
        }
        if len(created_moves) == 1:
            action.update({'res_id': created_moves.id, 'view_mode': 'form'})
            action.pop('domain', None)
        return action


class RsBuyerInboxLine(models.TransientModel):
    _name = 'rs.einvoice.inbox.line'
    _description = 'rs.ge Buyer Inbox Line'
    _order = 'reg_dt desc, rs_inv_id desc'

    wizard_id = fields.Many2one('rs.einvoice.inbox.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Import', default=True)

    rs_inv_id = fields.Char(string='rs.ge ID', readonly=True, required=True)
    f_series = fields.Char(string='Series', readonly=True)
    f_number = fields.Char(string='Number', readonly=True)
    reg_dt = fields.Datetime(string='Issued Date', readonly=True,
        help="rs.ge registration timestamp — the date the 'Issued From/To' filter matches on.")
    operation_dt = fields.Datetime(string='Operation Date', readonly=True)
    operation_date = fields.Date(string='Operation Calendar Date', readonly=True,
        help="Calendar day of the rs.ge operation in the supplier's local timezone (Tbilisi). Used as invoice_date on the imported bill.")
    status = fields.Selection(INBOX_STATUS, string='Status', readonly=True)
    seller_tin = fields.Char(string='Seller TIN', readonly=True)
    seller_name = fields.Char(string='Seller Name', readonly=True)
    k_id = fields.Integer(string='k_id', readonly=True)
    k_type = fields.Integer(string='Correction Type', readonly=True)
    amount = fields.Float(string='Amount (GEL)', readonly=True)

    partner_id = fields.Many2one('res.partner', string='Matched Vendor',
        help="Matched by TIN. When several vendors share the TIN, pick one here; if none exists, create the vendor with this TIN and search again.")
    existing_move_id = fields.Many2one('account.move', string='Existing Bill', readonly=True)
    already_imported = fields.Boolean(string='Already Imported', readonly=True)
    import_status = fields.Selection([('pending', 'Pending'), ('imported', 'Imported'), ('error', 'Error')], string='Import Result', readonly=True,
        default='pending')
    import_note = fields.Char(string='Note', readonly=True)

    def _rs_parent_bill(self):
        """The Odoo bill this row corrects (rs.ge k_id) in the active company; empty if none or not imported."""
        self.ensure_one()
        parent_rs_id = str(self.k_id) if (self.k_id and self.k_id > 0) else ''
        if not parent_rs_id:
            return self.env['account.move']
        return self.env['account.move'].search([('rs_einv_id', '=', parent_rs_id), ('company_id', '=', self.env.company.id)], limit=1)

    def _do_import(self, Move, purchase_journal):
        self.ensure_one()
        if self.already_imported and self.existing_move_id:
            return (_("Already imported as %s") % self.existing_move_id.display_name, self.existing_move_id)
        if not self.partner_id:
            # A vendor created after the search ran stays unmatched without this retry.
            partner, ambiguous = _rs_find_partner_by_tin(self.env, self.seller_tin, self.env.company.id)
            if ambiguous:
                return (_rs_ambiguous_vendor_note(self.env, self.seller_tin or '—', ambiguous), False)
            self.partner_id = partner
        if not self.partner_id:
            return (_("No Odoo vendor found with TIN %s. Create the partner record first, then run the search again.") % (self.seller_tin or '—'),
                False)

        if (self.k_id and self.k_id > 0) or self.k_type:
            parent_rs_id = str(self.k_id) if (self.k_id and self.k_id > 0) else ''
            parent = self._rs_parent_bill()
            if not parent:
                return (_("This row is a supplier correction (rs.ge k_id %(k_id)s, k_type %(k_type)s) but its parent bill is not in Odoo yet. Import "
                    "the original first, then re-run the inbox search.", k_id=parent_rs_id or '—', k_type=self.k_type or '—'), False)
            if parent.state == 'cancel':
                _logger.info("rs.ge inbox: parent %s already cancelled, creating new draft for correction %s.", parent.display_name, self.rs_inv_id)
            elif parent.state == 'draft':
                return (_("Original bill %(name)s is still in Draft. Post or cancel it before importing the correction.",
                    name=parent.display_name or '—'), False)
            elif parent.state == 'posted':
                blockers = parent._rs_check_cancel_reissue_blockers()
                if blockers:
                    return (_(
                        "Cannot auto-cancel original bill %(name)s:\n%(reasons)s\n"
                        "Resolve the blockers above, or use 'Import "
                        "Supplier Correction' on %(name)s for the "
                        "delta credit-note path.",
                        name=parent.display_name or '—',
                        reasons="\n".join("  • %s" % r for r in blockers),
                    ), False)
                return (_("Original bill %(name)s is posted and ready for auto-cancel-and-reissue, but the inbox could not route this row to the "
                    "preview wizard. Click 'Import Selected' again with only this row ticked.", name=parent.display_name or '—'), False)
            else:
                return (_("Original bill %(name)s is in unexpected state '%(state)s'. Refuse to proceed.", name=parent.display_name or '—',
                    state=parent.state), False)

        invoice_date = (self.operation_date or (self.operation_dt.date() if self.operation_dt else False) or fields.Date.today())
        move_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'journal_id': purchase_journal.id,
            'invoice_date': invoice_date,
            'document_tax_mode': 'tax_excluded',
        }
        move = False
        try:
            with self.env.cr.savepoint():

                duplicate = Move.search([('rs_einv_id', '=', self.rs_inv_id), ('company_id', '=', self.env.company.id)], limit=1)
                if duplicate:
                    return (_("rs.ge ID %(rs_id)s is already linked to %(name)s in this company.", rs_id=self.rs_inv_id,
                        name=duplicate.display_name or '—'), False)
                move = Move.create(move_vals)
                move.rs_einv_id = self.rs_inv_id
                move.action_rs_buyer_pull()
        except UserError as e:
            return (str(e), False)
        except Exception as e:
            _logger.exception("rs.ge inbox: pull failed for rs_id=%s", self.rs_inv_id)
            return (_("Pull from rs.ge failed: %s") % e, False)
        if not move:
            return (_("Pull from rs.ge failed (no move created)."), False)

        if (self.k_id and self.k_id > 0):
            parent_rs_id = str(self.k_id)
            parent = Move.search([
                ('rs_einv_id', '=', parent_rs_id),
                ('company_id', '=', self.env.company.id),
                ('id', '!=', move.id),
                ('state', '=', 'cancel'),
            ], limit=1)
            if parent and not parent.rs_einv_replaced_by_id and not move.rs_einv_replaces_id:
                move.write({'rs_einv_replaces_id': parent.id, 'rs_einv_replacement_mode': 'fresh'})
                parent.write({'rs_einv_replaced_by_id': move.id})
                try:
                    parent_link = Markup('<a href="#" '
                        'data-oe-model="account.move" data-oe-id="%d">%s</a>') % (parent.id, parent.display_name or parent.name or '—')
                    move.message_post(body=Markup(_("Linked to cancelled original bill "
                        "%(parent)s via rs.ge correction chain (k_id=%(k_id)s).")) % {'parent': parent_link, 'k_id': escape(parent_rs_id)})
                except Exception:
                    _logger.exception("rs.ge inbox: chain chatter failed (move=%s, parent=%s)", move.id, parent.id)

        return (_("OK — pulled rs.ge status %s") % (move.rs_einv_status or '—'), move)
