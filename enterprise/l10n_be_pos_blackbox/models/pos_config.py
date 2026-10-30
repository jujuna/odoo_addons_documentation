from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.service.common import exp_version
import requests
from requests.exceptions import RequestException
from odoo.tools import float_compare
import logging

_logger = logging.getLogger(__name__)

FALLBACK_POS_ID = "CDEM0000000001"


class PosConfig(models.Model):
    _inherit = "pos.config"

    l10n_be_report_counter = fields.Integer(help="Count the number of reports generated for this POS configuration.", default=1)
    l10n_be_blackbox_be_id = fields.Many2one(
        comodel_name="pos.blackbox.be",
        string="POS Blackbox BE (v2)",
        help="The blackbox that is linked to this POS configuration.",
    )
    l10n_be_pos_id = fields.Char(
        string="POS ID",
        readonly=True,
        help="The ID of the POS configuration. This ID is used to identify the POS configuration in the blackbox.",
    )
    l10n_be_training_mode = fields.Boolean(
        string="Training Mode",
        help="If checked, the POS will be in training mode.",
        default=False,
    )
    pos_version = fields.Char('Odoo Version', compute='_compute_odoo_version')
    establishment_number = fields.Char(string="Establishment Number", help="The establishment number of the company using this POS configuration.")
    use_blackbox = fields.Boolean(
        string="Uses Blackbox",
        compute="_compute_use_blackbox",
        store=True,
        help="True if any of the sessions of this POS configuration use the blackbox.",
    )

    @api.depends("session_ids.use_blackbox")
    def _compute_use_blackbox(self):
        for config in self:
            config.use_blackbox = any(config.session_ids.mapped("use_blackbox"))

    @api.depends('l10n_be_blackbox_be_id')
    def _compute_local_data_integrity(self):
        super()._compute_local_data_integrity()

    def _get_pos_id_from_fdm(self):
        """Retrieve POS ID from FDM service"""
        db_uuid = self.env['ir.config_parameter'].sudo().get_str('database.uuid')
        if not db_uuid:
            raise UserError(_("Database UUID not found."))
        endpoint = "https://fdm.odoo.com/_fdm/pos/sequence/"

        url = f"{endpoint}{db_uuid}"
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            return response.text
        except RequestException as e:
            _logger.warning("Failed to retrieve POS ID from FDM service: %s", e)
            raise UserError(_("Failed to retrieve POS ID from FDM service"))

    def action_request_pos_id(self):
        self.ensure_one()
        if self.l10n_be_pos_id and self.l10n_be_pos_id != FALLBACK_POS_ID:
            raise UserError(_("A valid POS ID is already set for this configuration."))
        try:
            self.l10n_be_pos_id = self._get_pos_id_from_fdm()
        except UserError:
            with self.env.registry.cursor() as new_cr:
                self.with_env(self.env(cr=new_cr)).write({'l10n_be_pos_id': FALLBACK_POS_ID})
            raise

    def write(self, vals):
        if 'l10n_be_blackbox_be_id' in vals:
            for config in self:
                if config.has_active_session and config.l10n_be_blackbox_be_id.id != vals['l10n_be_blackbox_be_id']:
                    raise UserError(_(
                        "You cannot change the blackbox of the POS configuration %s while it has an open session. "
                        "Please close the session first.",
                        config.name,
                    ))
        if 'l10n_be_pos_id' in vals:
            for config in self:
                if config.has_active_session and config.l10n_be_pos_id != vals['l10n_be_pos_id']:
                    raise UserError(_(
                        "You cannot change the POS ID of the POS configuration %s while it has an open session. "
                        "Please close the session first.",
                        config.name,
                    ))
        if (vals.get('l10n_be_blackbox_be_id') or self.filtered('l10n_be_pos_id')):
            vals['iface_print_auto'] = True
            vals['set_tip_after_payment'] = False
            rounding_method = self.env['account.cash.rounding'].search([
                ('company_id', '=', self.env.company.id),
                ('name', '=', 'Round to 0.05'),
            ], limit=1)
            if rounding_method:
                vals['cash_rounding'] = True
                vals['rounding_method'] = rounding_method.id
                vals['only_round_cash_method'] = True
        return super().write(vals)

    def _check_l10n_be_before_opening(self):
        for config in self.filtered('l10n_be_pos_id'):
            config._check_blackbox_required()
        for config in self.filtered('l10n_be_blackbox_be_id'):
            config._check_cashier_l10n_be_insz_or_bis_number()
            config._check_cash_rounding()
            config._check_iface_printers()
            config._check_config_company_data()
            config._check_blackbox()
            config._check_self_order_blackbox()

    def open_ui(self):
        self._check_l10n_be_before_opening()
        return super().open_ui()

    def _check_blackbox_required(self):
        for config in self:
            signed_orders_count = self.env['pos.order'].search_count([
                *self.env['pos.order']._check_company_domain(self.company_id),
                ('l10n_be_short_signature', '!=', False),
            ], limit=1)
            if signed_orders_count and config.l10n_be_pos_id and not config.l10n_be_blackbox_be_id:
                raise ValidationError(_(
                    "This POS has a registered POS ID and requires a blackbox to be configured."
                ))

    def _check_iface_printers(self):
        for config in self:
            if not config.iface_print_auto:
                raise ValidationError(_("Automatic Receipt Printing must be activated"))

    def _check_config_company_data(self):
        for config in self:
            if not config.establishment_number:
                raise ValidationError(_("An establishment number must be set for this POS configuration."))
            if not config.company_id.vat:
                raise ValidationError(_("A VAT number must be set for the company using this POS configuration."))
            if not config.l10n_be_pos_id:
                raise ValidationError(_("A POS ID must be set for this POS configuration."))

    def _check_cashier_l10n_be_insz_or_bis_number(self):
        for config in self:
            if not self.env.user.l10n_be_insz_or_bis_number and not config.module_pos_hr:
                raise ValidationError(
                    _(
                        "%(user)s must have an INSZ or BIS number.",
                        user=self.env.user.name,
                    )
                )

    def _check_cash_rounding(self):
        if self.payment_method_ids.filtered(lambda p: p.type == 'cash'):
            if not self.cash_rounding:
                raise ValidationError(_("Cash rounding must be enabled"))
            if (
                not float_compare(self.rounding_method.rounding, 0.05, precision_digits=2) == 0
                or self.rounding_method.rounding_method != "HALF-UP"
            ):
                raise ValidationError(
                    _('The rounding method must be set to 0.05 and "Nearest"')
                )

    @api.constrains('l10n_be_training_mode')
    def _check_l10n_be_training_mode(self):
        for record in self:
            signed_order = self.env['pos.order'].search_count([
                ('session_id.config_id', '=', record.id),
                ('l10n_be_short_signature', '!=', False),
            ], limit=1)

            if signed_order and record.l10n_be_training_mode:
                raise ValidationError(_(
                    "You cannot enable training mode on a POS configuration that has already processed orders."
                ))

    def _check_self_order_blackbox(self):
        """
        Since 'l10n_be_pos_blackbox_self_order' now also depends on 'obox_pos_self_order', it's possible that we have the modules
        'l10n_be_pos_blackbox' and 'pos_self_order' installed but not 'l10n_be_pos_blackbox_self_order' (not automatically installed cause obox is not installed).
        If it's the case, we need to force the user to install it (to make sure self/kiosk orders are signed to the blackbox)
        """
        for config in self:
            if (
                'self_ordering_mode' in config._fields
                and config.self_ordering_mode in ('mobile', 'kiosk')
                and not self.env['ir.module.module'].sudo().search_count([
                    ('name', '=', 'l10n_be_pos_blackbox_self_order'),
                    ('state', '=', 'installed'),
                ], limit=1)
            ):
                raise UserError(_(
                    "The 'Belgian Registered Cash Register Self-Order Extension' module must be "
                    "installed to use self-ordering (QR ordering or Kiosk) with a Blackbox."
                ))

    def _check_blackbox(self):
        for config in self:
            if not config.l10n_be_blackbox_be_id.local_ip:
                raise ValidationError(_(
                    "The blackbox must have a local IP address configured."
                ))

    def _compute_odoo_version(self):
        self.pos_version = exp_version()['server_serie']

    @api.constrains('establishment_number')
    def _check_pos_establishment_number(self):
        for config in self:
            if config.establishment_number and not config.is_valid_est_number(config.establishment_number):
                raise ValidationError(
                    _(
                        "Invalid establishment number.\n\n"
                        "An establishment number must meet the following rules:\n"
                        "- It must contain exactly 10 digits\n"
                        "- The first digit must be between 2 and 8\n"
                    )
                )

    @api.model
    def is_valid_est_number(self, value):
        """ Validate an establishment unit number (estNo).
            Rules:
                - Length = 10
                - Digits only
                - Starts with a digit from '2' to '8'
                - Must pass the modulo 97 check
                - Example: 8789456149
        """
        if not value:
            return False

        if not value.isdigit() or len(value) != 10:
            return False

        base = int(value[:8])
        key = int(value[8:])
        expected_key = 97 - (base % 97)
        return key == expected_key
