from odoo import models
from odoo.exceptions import UserError

from .tools import gec_lock_for_update


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _gec_direct_correction_members(self):
        self.ensure_one()
        refunds = self.related_payslip_ids.filtered(lambda slip: slip.credit_note and slip.is_refund_payslip)
        corrections = self.related_payslip_ids.filtered(lambda slip: not slip.credit_note and not slip.is_refund_payslip)
        return refunds, corrections

    def _gec_check_correction_chains(self):
        """Validated corrections may not outnumber validated refunds."""
        malformed_standalone = self.filtered(lambda slip: (slip.credit_note or slip.is_refund_payslip) and not slip.origin_payslip_id)
        if malformed_standalone:
            raise UserError(self.env._("These refund payslips are not linked to the payslip they refund and cannot be validated: %(names)s. Create "
                "a refund with the Correct button of the original payslip.", names=', '.join(malformed_standalone.mapped('name'))))

        confirming_ids = set(self.filtered(lambda slip: slip.state == 'draft').ids)
        for origin in self.mapped('origin_payslip_id'):
            gec_lock_for_update(origin)
            refunds, corrections = origin._gec_direct_correction_members()
            active_refunds = refunds.filtered(lambda slip: slip.state in ('validated', 'paid') or slip.id in confirming_ids)
            active_corrections = corrections.filtered(lambda slip: slip.state in ('validated', 'paid') or slip.id in confirming_ids)
            if len(active_corrections) > len(active_refunds):
                raise UserError(self.env._("Correction payslip %(correction)s has no matching validated refund for payslip %(origin)s and would pay "
                    "the base salary twice: validate the refund first.", correction=', '.join(active_corrections.mapped('name')),
                    origin=origin.name))

    def _gec_check_correction_balance_after_removal(self, operation):
        """Keep a refund for every active correction."""
        removing_ids = set(self.ids)
        for origin in self.mapped('origin_payslip_id'):
            gec_lock_for_update(origin)
            refunds, corrections = origin._gec_direct_correction_members()
            remaining_refunds = refunds.filtered(lambda slip: slip.state in ('validated', 'paid') and slip.id not in removing_ids)
            remaining_corrections = corrections.filtered(lambda slip: slip.state in ('validated', 'paid') and slip.id not in removing_ids)
            if len(remaining_corrections) > len(remaining_refunds):
                raise UserError(self.env._("The refund payslip cannot be %(operation)s because it would leave %(corrections)s validated "
                    "correction(s) but only %(refunds)s validated refund(s) for payslip %(origin)s: cancel the correction first.",
                    operation=operation, corrections=len(remaining_corrections), refunds=len(remaining_refunds), origin=origin.name))
