from odoo import _, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    nfc_badge_counter = fields.Integer(groups='hr.group_hr_user', copy=False)

    def write(self, vals):
        if 'barcode' in vals:
            vals['nfc_badge_counter'] = 0
        return super().write(vals)

    def open_badge_scanner(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'pos_hr_mobile_nfc.badge_scanner',
            'name': _('Badge Scanner'),
        }
