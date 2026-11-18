import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RsReplacePreview(models.TransientModel):
    _name = 'rs.einvoice.replace.preview'
    _description = 'rs.ge Cancel-and-Reissue Preview'

    line_ids = fields.One2many('rs.einvoice.replace.preview.line', 'preview_id', string='Pairs',
        help="One row per original ⇄ rs.ge correction pair. On Confirm each row is processed in sequence; rows that fail leave their parent bill "
        "untouched.")
    line_count = fields.Integer(compute='_compute_line_count', string='Pair Count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_confirm(self):
        """Each line runs in its own savepoint, so one failed pair does not roll back the others."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Nothing to process — close this dialog and pick at least one correction row in the inbox."))

        succeeded = self.env['account.move'].browse()
        failures = []
        for line in self.line_ids:
            if not line.parent_move_id or not line.correction_rs_id:
                failures.append((line, _("Missing original bill or rs.ge correction ID.")))
                continue
            try:
                with self.env.cr.savepoint():
                    new_draft = line.parent_move_id._rs_execute_cancel_and_reissue(correction_rs_id=line.correction_rs_id)
                if new_draft:
                    succeeded |= new_draft
                else:
                    failures.append((line, _("Cancel-and-reissue did not return a new draft. See the RS Logs on the original bill.")))
            except UserError as e:
                failures.append((line, str(e)))
            except Exception as e:
                _logger.exception("Cancel-and-reissue batch row failed (parent=%s, correction_rs_id=%s)", line.parent_move_id.id,
                    line.correction_rs_id)
                failures.append((line, _("Unexpected error: %s") % e))

        if failures and not succeeded:
            details = "\n".join("  • %s → rs.ge %s: %s" % (ln.parent_move_id.display_name or '—', ln.correction_rs_id or '—', err)
                for ln, err in failures)
            raise UserError(_("Cancel-and-reissue could not complete for any of the %(n)d pair(s):\n\n%(details)s", n=len(failures), details=details))

        if succeeded and not failures:
            return self._open_drafts_action(succeeded)

        fail_details = "\n".join("• %s → rs.ge %s: %s" % (ln.parent_move_id.display_name or '—', ln.correction_rs_id or '—', err)
            for ln, err in failures)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Cancel-and-Reissue: partial success"),
                'message': _(
                    "%(ok)d pair(s) succeeded. %(fail)d failed:\n\n"
                    "%(details)s\n\nThe failed pairs were not "
                    "modified — re-open the rs.ge inbox to retry."
                ) % {
                    'ok': len(succeeded),
                    'fail': len(failures),
                    'details': fail_details,
                },
                'type': 'warning',
                'sticky': True,
                'next': self._open_drafts_action(succeeded),
            },
        }

    def _open_drafts_action(self, moves):
        # Spell out 'views': this action is also a display_notification 'next', where clean_action() never runs.
        if not moves:
            return {'type': 'ir.actions.act_window_close'}
        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Vendor Bill (rs.ge correction)'),
                'res_model': 'account.move',
                'res_id': moves.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bills (rs.ge corrections)'),
            'res_model': 'account.move',
            'domain': [('id', 'in', moves.ids)],
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'context': {'create': False},
        }


class RsReplacePreviewLine(models.TransientModel):
    _name = 'rs.einvoice.replace.preview.line'
    _description = 'rs.ge Cancel-and-Reissue Preview Pair'
    _order = 'id'

    preview_id = fields.Many2one('rs.einvoice.replace.preview', required=True, ondelete='cascade')

    parent_move_id = fields.Many2one('account.move', string='Original Bill', required=True, readonly=True,
        help="Vendor bill in Odoo that the rs.ge correction supersedes. Cancelled once the correction is accepted on rs.ge.")
    parent_rs_id = fields.Char(string='Original rs.ge ID', readonly=True)
    parent_amount = fields.Float(string='Original Amount', readonly=True)
    parent_state = fields.Char(string='Original State', readonly=True)

    correction_rs_id = fields.Char(string='Correction rs.ge ID', required=True, readonly=True)
    correction_amount = fields.Float(string='Corrected Amount', readonly=True)
    correction_k_type = fields.Char(string='Correction Reason', readonly=True)
    correction_status = fields.Char(string='Correction Status', readonly=True)
