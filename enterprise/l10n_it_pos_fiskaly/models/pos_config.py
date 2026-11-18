from odoo import _, fields, models, release
from odoo.exceptions import UserError, ValidationError
from odoo.addons.l10n_it_pos_fiskaly.models.fiskaly_client import fiskaly_client

CASH_ROUNDING_PRECISION = 0.05
CASH_ROUNDING_METHOD = 'HALF-UP'

VAT_RATES = [
    {
        'code': 'STANDARD',
        'description': "Standard VAT rate",
        'historic': False,
        'percentage': '22',
    },
    {
        'code': 'REDUCED_1',
        'description': "Reduced VAT rate 1",
        'historic': False,
        'percentage': '10',
    },
    {
        'code': 'REDUCED_2',
        'description': "Reduced VAT rate 2",
        'historic': False,
        'percentage': '5',
    },
    {
        'code': 'REDUCED_3',
        'description': "Super-reduced VAT rate",
        'historic': False,
        'percentage': '4',
    },
]


class PosConfig(models.Model):
    _inherit = 'pos.config'

    l10n_it_fiskaly_system_id = fields.Char(string="Fiskaly System", readonly=True, copy=False)
    l10n_it_fiskaly_system_state = fields.Selection(
        selection=[
            ('ACQUIRED', "Acquired"),
            ('COMMISSIONED', "Commissioned"),
            ('DECOMMISSIONED', "Decommissioned"),
        ],
        string="Fiskaly System State",
        readonly=True,
        copy=False,
    )

    def _l10n_it_fiskaly_check_cash_rounding(self):
        if self.payment_method_ids.filtered(lambda p: p.type == 'cash'):
            if (
                not self.cash_rounding
                or self.rounding_method.rounding != CASH_ROUNDING_PRECISION
                or self.rounding_method.rounding_method != CASH_ROUNDING_METHOD
            ):
                raise ValidationError(_(
                    'A rounding method set to 0.05 and "Nearest" must be enabled to accept '
                    'cash payments.'
                ))

    def _l10n_it_fiskaly_cash_rounding(self):
        self.ensure_one()
        company = self.company_id
        Rounding = self.env['account.cash.rounding'].with_company(company)
        rounding = Rounding.search([
            ('company_id', '=', company.id),
            ('rounding', '=', CASH_ROUNDING_PRECISION),
            ('rounding_method', '=', CASH_ROUNDING_METHOD),
            ('strategy', '=', 'add_invoice_line'),
        ], limit=1)
        if rounding:
            return rounding
        ChartTemplate = self.env['account.chart.template'].with_company(company)
        profit_account = company.cash_rounding_profit_account_id or ChartTemplate.ref('3210', raise_if_not_found=False)
        loss_account = company.cash_rounding_loss_account_id or ChartTemplate.ref('4910', raise_if_not_found=False)
        if not profit_account or not loss_account:
            return Rounding
        return Rounding.create({
            'name': _("Cash Rounding 0.05"),
            'rounding': CASH_ROUNDING_PRECISION,
            'rounding_method': CASH_ROUNDING_METHOD,
            'strategy': 'add_invoice_line',
            'profit_account_id': profit_account.id,
            'loss_account_id': loss_account.id,
            'company_id': company.id,
        })

    def _l10n_it_fiskaly_apply_cash_rounding(self):
        self.ensure_one()
        rounding = self._l10n_it_fiskaly_cash_rounding()
        if not rounding:
            return
        self.write({
            'cash_rounding': True,
            'only_round_cash_method': True,
            'rounding_method': rounding.id,
        })

    def _l10n_it_fiskaly_is_active(self):
        self.ensure_one()
        return bool(self.l10n_it_fiskaly_system_id) and not any(
            printer.printer_type == 'it_fiscal_printer' for printer in self.receipt_printer_ids
        )

    def _check_before_creating_new_session(self):
        if self._l10n_it_fiskaly_is_active():
            self._l10n_it_fiskaly_check_cash_rounding()
            self._l10n_it_fiskaly_check_presets()
        return super()._check_before_creating_new_session()

    def _l10n_it_fiskaly_check_presets(self):
        if not self.use_presets:
            return
        return_presets = (self.default_preset_id | self.available_preset_ids).filtered('is_return')
        if return_presets:
            raise ValidationError(_(
                "Return presets cannot be used with fiskaly SIGN IT: a return must be made from the "
                "original order. Remove %(presets)s from the presets of %(register)s.",
                presets=", ".join(return_presets.mapped('name')),
                register=self.display_name,
            ))

    def l10n_it_fiskaly_get_taxpayer_mode(self):
        self.ensure_one()
        return self.company_id._l10n_it_fiskaly_taxpayer_mode()

    def action_l10n_it_fiskaly_commission_system(self):
        self.ensure_one()
        if not self.l10n_it_fiskaly_system_id:
            raise UserError(_("Please register %s with fiskaly first.", self.display_name))
        with fiskaly_client(self.company_id, subject=True) as client:
            return self._l10n_it_fiskaly_commission_system(client)

    def _l10n_it_fiskaly_commission_system(self, client):
        response = client.update_system(self.l10n_it_fiskaly_system_id, {'state': 'COMMISSIONED'})
        self.l10n_it_fiskaly_system_state = response.get('state')
        return self.l10n_it_fiskaly_system_state

    def action_l10n_it_fiskaly_create_system(self):
        self.ensure_one()
        company = self.company_id
        if company.l10n_it_fiskaly_location_state != 'COMMISSIONED':
            raise UserError(_(
                "%(company)s is not registered with fiskaly yet: open the company form and complete the "
                "fiskaly registration before registering %(register)s.",
                company=company.display_name,
                register=self.display_name,
            ))
        with fiskaly_client(company, subject=True) as client:
            if not self.l10n_it_fiskaly_system_id:
                response = client.create_system({
                    'type': 'FISCAL_DEVICE',
                    'location': {
                        'id': company.l10n_it_fiskaly_location_id,
                    },
                    'producer': {
                        'type': 'MPN',
                        'number': "ODOO SA",
                        'details': {
                            'name': self.name,
                        },
                    },
                    'software': {
                        'name': "Odoo Point of Sale",
                        'version': '.'.join(str(part) for part in release.version_info[:3]),
                    },
                })
                system_id = response.get('id')
                if not system_id:
                    raise UserError(_("Fiskaly did not return a system identifier."))
                self.write({
                    'l10n_it_fiskaly_system_id': system_id,
                    'l10n_it_fiskaly_system_state': response.get('state'),
                })
            # A new system is ACQUIRED: it must be COMMISSIONED before it can record transactions.
            self._l10n_it_fiskaly_commission_system(client)
        if self.l10n_it_fiskaly_system_state == 'COMMISSIONED':
            self._l10n_it_fiskaly_apply_cash_rounding()
        return self.l10n_it_fiskaly_system_id
