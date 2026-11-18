# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    onss_expeditor_number = fields.Char(
        related="company_id.onss_expeditor_number",
        readonly=False,
        groups="hr_payroll.group_hr_payroll_user")
    onss_certificate_id = fields.Many2one(
        related="company_id.onss_certificate_id",
        readonly=False)
    onss_technical_user_name = fields.Char(
        related="company_id.onss_technical_user_name",
        readonly=False,
        groups="hr_payroll.group_hr_payroll_user")
    onss_sftp_private_key = fields.Many2one(
        related="company_id.onss_sftp_private_key",
        readonly=False,
        groups="hr_payroll.group_hr_payroll_user")
    nsso_immatriculation_date = fields.Date(
        related="company_id.nsso_immatriculation_date",
        readonly=False,
        groups="hr_payroll.group_hr_payroll_user")
    l10n_be_dimona_environment = fields.Selection(
        related='company_id.l10n_be_dimona_environment',
        readonly=False,
        groups='hr_payroll.group_hr_payroll_user')
    module_pos_blackbox_be = fields.Boolean(string="POS Blackbox BE")
    l10n_be_cash_register_active = fields.Boolean(
        related='company_id.l10n_be_cash_register_active',
        readonly=False)
    l10n_be_cash_register_number = fields.Char(
        related='company_id.l10n_be_cash_register_number',
        readonly=False)
    l10n_be_cash_register_registration_start = fields.Date(
        related='company_id.l10n_be_cash_register_registration_start',
        readonly=False)
    l10n_be_cash_register_registration_end = fields.Date(
        related='company_id.l10n_be_cash_register_registration_end',
        readonly=False)
    l10n_be_daily_registration_recording = fields.Selection(
        related='company_id.l10n_be_daily_registration_recording',
        readonly=False)
    l10n_be_employer_category_has_cp302 = fields.Boolean(
        related='company_id.l10n_be_employer_category_has_cp302')
    l10n_be_max_unused_cars = fields.Integer(string='Maximum unused cars', default=5,
        related="company_id.l10n_be_max_unused_cars", readonly=False, store=True
    )
    l10n_be_temporary_car_option = fields.Boolean(related="company_id.l10n_be_temporary_car_option",
        readonly=False, store=True)
    l10n_be_cbe_inscription = fields.Date(
        related='company_id.l10n_be_cbe_inscription',
        readonly=False,
        groups="hr_payroll.group_hr_payroll_user",
    )
    l10n_be_has_white_cash_register = fields.Boolean(
        related='company_id.l10n_be_has_white_cash_register',
        readonly=False
    )

    # Not stored: the choice is held by two mutually exclusive salary package benefits (with their salary
    # rule), shared by all the companies (benefits and rules have no company)
    l10n_be_loss_on_commission_pto = fields.Selection(
        selection=[
            ('monthly', 'Monthly'),
            ('double_holiday', 'With the Double Holiday Pay'),
        ],
        string="Loss on Commission for Paid Time Off",
        compute='_compute_l10n_be_loss_on_commission_pto',
        inverse='_inverse_l10n_be_loss_on_commission_pto',
        groups="hr_payroll.group_hr_payroll_user",
        help="How the loss on commission during the paid time off is compensated (JC 200), for all the companies:\n"
             "- Monthly: on the payslip of the month of the time off (Loss on Commission on Paid Time Off),\n"
             "- With the Double Holiday Pay: once a year, with the double holiday pay (Single Holiday Pay on "
             "Variable Salary).\n"
             "Switching to monthly after the double holiday pay of the year pays the paid time off of the year twice.")

    @api.depends('company_id')
    def _compute_l10n_be_loss_on_commission_pto(self):
        monthly, double_holiday = self._l10n_be_get_loss_on_commission_pto_benefits()
        if monthly.active:
            value = 'monthly'
        elif double_holiday.active:
            value = 'double_holiday'
        else:
            value = False
        for settings in self:
            settings.l10n_be_loss_on_commission_pto = value

    def _inverse_l10n_be_loss_on_commission_pto(self):
        monthly, double_holiday = self._l10n_be_get_loss_on_commission_pto_benefits()
        for settings in self:
            benefit = {'monthly': monthly, 'double_holiday': double_holiday}.get(settings.l10n_be_loss_on_commission_pto)
            if benefit and not benefit.active:
                # restoring one of the benefits archives the other one, with their salary rules
                benefit.active = True

    def _l10n_be_get_loss_on_commission_pto_benefits(self):
        Benefit = self.env['hr.contract.salary.benefit']
        return (
            self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly', raise_if_not_found=False) or Benefit,
            self.env.ref('l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday', raise_if_not_found=False) or Benefit,
        )

    def action_open_hr_payroll_localization(self):
        return {
            'name': self.env._('Payroll Localization'),
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.config.settings',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.company_id.id)],
            'target': 'current',
        }
