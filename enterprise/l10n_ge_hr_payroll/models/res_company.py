# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ge_tax_regime = fields.Selection([
        ('standard', "Standard Company"),
        ('international', "International Company (ICS)"),
        ('rnd', "R&D Service Company"),
        ('startup_1', "Innovative Start-up (Years 1-3)"),
        ('startup_4', "Innovative Start-up (Years 4-6)"),
        ('startup_7', "Innovative Start-up (Years 7-10)"),
        ('innovative_sme', "Innovative SME"),
        ('vzp', "Virtual Zone Person (VZP)"),
        ('fiz', "Free Industrial Zone (FIZ)"),
    ], string="GE: Income Tax Regime", default='standard', required=True,
        help="Standard Company: income tax of 20% (Tax Code, art. 79, 81 and 101).\n"
             "International Company (ICS): 5% (Tax Code, art. 23(7)).\n"
             "R&D Service Company: 5% (Law on Innovations, art. 15^7).\n"
             "Innovative Start-up: salary exempt up to GEL 10,000 a month in the years 1 to 3 of the status, 20% on "
             "the excess, then 5% in the years 4 to 6 and 10% in the years 7 to 10 (Law on Innovations, art. 15^3).\n"
             "Innovative SME and Virtual Zone Person (VZP): 20%, no reduced rate on the salaries.\n"
             "Free Industrial Zone (FIZ): no income tax withheld (Law on Free Industrial Zones), the employees pay "
             "their 4% pension contribution themselves.")
    l10n_ge_annual_leave_type_id = fields.Many2one(
        'hr.work.entry.type', string="GE: Annual Leave Time-off Type",
        default=lambda self: self.env.ref('hr_work_entry.ge_work_entry_type_legal_leave', raise_if_not_found=False),
        help="Time-off type of the annual leave: the days allocated and not taken nor expired on the departure are paid "
             "to the employee (Labour Code, art. 31(5)).")
