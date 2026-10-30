# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models
from odoo.exceptions import UserError


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    def write(self, vals):
        if self.env.context.get('gantt_reschedule', False) and 'equipment_id' in vals:
            raise UserError(self.env._('You are not allowed to change the equipment by dragging in this view.'))
        return super().write(vals)
