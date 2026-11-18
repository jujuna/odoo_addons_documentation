from odoo import fields, models

from .rs_form30_declaration import AUTONOMOUS_REPUBLICS


class HrWorkLocation(models.Model):
    _inherit = 'hr.work.location'

    rs_form30_autonomous_republic = fields.Selection(AUTONOMOUS_REPUBLICS, string='Form 30 Autonomous Republic',
        help="Income tax withheld from employees working here belongs to this republic's budget and is reported in cell 57¹ or 57² of the Form 30 "
        "main part. Empty means the rest of Georgia.")
