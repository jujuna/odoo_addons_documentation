import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.business_data import street_split
from odoo.addons.l10n_it_pos_fiskaly.models.fiskaly_client import fiskaly_client

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_it_fiskaly_test_mode = fields.Boolean(string="Test Sign IT", default=False)
    l10n_it_fiskaly_api_key = fields.Char(string="Fiskaly API Key (ITA)", groups="base.group_system", copy=False)
    l10n_it_fiskaly_api_secret = fields.Char(string="Fiskaly API Secret (ITA)", groups="base.group_system", copy=False)
    l10n_it_fiskaly_access_token = fields.Char(string="Organization Access Token", groups="base.group_system", copy=False)
    l10n_it_fiskaly_organization_id = fields.Char(string="Fiskaly Organization", readonly=True, copy=False)
    l10n_it_fiskaly_subject_id = fields.Char(string="Fiskaly Subject", readonly=True, copy=False)
    l10n_it_fiskaly_subject_api_key = fields.Char(string="Fiskaly Subject API Key", groups="base.group_system", readonly=True, copy=False)
    l10n_it_fiskaly_subject_api_secret = fields.Char(string="Fiskaly Subject API Secret", groups="base.group_system", readonly=True, copy=False)
    l10n_it_fiskaly_subject_access_token = fields.Char(string="Subject Access Token", groups="base.group_system", copy=False)
    l10n_it_fiskaly_taxpayer_id = fields.Char(string="Fiskaly Taxpayer", readonly=True, copy=False)
    l10n_it_fiskaly_taxpayer_state = fields.Selection(
        selection=[
            ('ACQUIRED', "Acquired"),
            ('COMMISSIONED', "Commissioned"),
            ('DECOMMISSIONED', "Decommissioned"),
        ],
        string="Fiskaly Taxpayer State",
        readonly=True,
        copy=False,
    )
    l10n_it_fiskaly_location_id = fields.Char(string="Fiskaly Location", readonly=True, copy=False)
    l10n_it_fiskaly_location_state = fields.Selection(
        selection=[
            ('ACQUIRED', "Acquired"),
            ('COMMISSIONED', "Commissioned"),
            ('DECOMMISSIONED', "Decommissioned"),
        ],
        string="Fiskaly Location State",
        readonly=True,
        copy=False,
    )
    l10n_it_fisconline_tax_id = fields.Char(string="Fisconline Tax ID Number", size=16, copy=False,
        help="Codice fiscale of the Fisconline user allowed to access the services of the Agenzia delle Entrate")
    l10n_it_fisconline_pin = fields.Char(string="Fisconline PIN", groups="base.group_system", copy=False)
    l10n_it_fisconline_password = fields.Char(string="Fisconline Password", groups="base.group_system", copy=False)

    def write(self, vals):
        res = super().write(vals)
        if not {'l10n_it_fiskaly_api_key', 'l10n_it_fiskaly_api_secret'} & vals.keys():
            return res
        for company in self.filtered(lambda c: not c.parent_id):
            root = company.sudo()
            if not root.l10n_it_fiskaly_api_key or not root.l10n_it_fiskaly_api_secret:
                root.l10n_it_fiskaly_access_token = False
                continue
            try:
                with fiskaly_client(company) as client:
                    client.refresh_bearer()
            except UserError as error:
                root.l10n_it_fiskaly_access_token = False
                _logger.warning("Could not authenticate %s with fiskaly: %s", company.display_name, error)
        return res

    def action_l10n_it_fiskaly_authenticate_organization(self):
        self.ensure_one()
        with fiskaly_client(self) as client:
            client.refresh_bearer()

    def action_l10n_it_fiskaly_authenticate_subject(self):
        self.ensure_one()
        with fiskaly_client(self, subject=True) as client:
            client.refresh_bearer()

    def action_l10n_it_fiskaly_create_organization(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_organization_id:
            with fiskaly_client(root) as client:
                response = client.create_organization(root.name)
            organization_id = response.get('id')
            if not organization_id:
                raise UserError(_("Fiskaly did not return an organization identifier."))
            root.l10n_it_fiskaly_organization_id = organization_id
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_l10n_it_fiskaly_create_subject(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_organization_id:
            raise UserError(_("Please create the fiskaly organization of %s first.", root.display_name))
        if not root.l10n_it_fiskaly_subject_id:
            slug = ''.join(char for char in root.name.lower() if char.isascii() and char.isalnum())
            with fiskaly_client(root) as client:
                response = client.create_subject(f"odoo-{slug}"[:30], root.l10n_it_fiskaly_organization_id)
            subject_id = response.get('id')
            if not subject_id:
                raise UserError(_("Fiskaly did not return a subject identifier."))
            credentials = response.get('credentials', {})
            root.sudo().write({
                'l10n_it_fiskaly_subject_id': subject_id,
                'l10n_it_fiskaly_subject_api_key': credentials.get('key'),
                'l10n_it_fiskaly_subject_api_secret': credentials.get('secret'),
            })
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    @api.constrains('l10n_it_fisconline_tax_id')
    def _check_l10n_it_fisconline_tax_id(self):
        for company in self:
            if company.l10n_it_fisconline_tax_id and len(company.l10n_it_fisconline_tax_id) != 16:
                raise ValidationError(_(
                    "The Fisconline Tax ID Number of %s must be exactly 16 characters long.",
                    company.display_name,
                ))

    def _l10n_it_fiskaly_vat_id_number(self):
        self.ensure_one()
        vat = self.vat or ''
        return vat[2:] if vat[:2].isalpha() else vat

    def _l10n_it_fiskaly_tax_id_number(self):
        self.ensure_one()
        return self._l10n_it_fiskaly_vat_id_number()

    def _l10n_it_fiskaly_address_line(self):
        self.ensure_one()
        street = street_split(self.street)
        if not street['street_number']:
            raise UserError(_("Could not read a street number from the address of %s.", self.display_name))
        return {
            'type': 'STREET_NUMBER',
            'street': street['street_name'],
            'number': street['street_number'],
        }

    def _l10n_it_fiskaly_check_location_fields(self):
        self.ensure_one()
        street = street_split(self.street)
        missing = [
            label
            for label, value in (
                (_("Company Name"), self.name),
                (_("Street"), street['street_name']),
                (_("Street Number"), street['street_number']),
                (_("Zip"), self.zip),
                (_("City"), self.city),
                (_("Country"), self.country_id),
            )
            if not value
        ]
        if missing:
            raise UserError(_("The following information is required to register %(company)s with fiskaly: %(fields)s",
                company=self.display_name, fields=", ".join(missing)))
        if not re.fullmatch(r'\d{5}', self.zip or ''):
            raise UserError(_(
                "The zip of %(company)s must be a 5-digit Italian postal code, %(zip)s is not.",
                company=self.display_name, zip=self.zip,
            ))

    def _l10n_it_fiskaly_check_taxpayer_fields(self):
        self.ensure_one()
        self._l10n_it_fiskaly_check_location_fields()
        company = self.sudo()
        missing = [
            label
            for label, value in (
                (_("Tax ID"), self._l10n_it_fiskaly_tax_id_number()),
                (_("VAT"), self._l10n_it_fiskaly_vat_id_number()),
                (_("Fisconline Tax ID Number"), company.l10n_it_fisconline_tax_id),
                (_("Fisconline PIN"), company.l10n_it_fisconline_pin),
                (_("Fisconline Password"), company.l10n_it_fisconline_password),
            )
            if not value
        ]
        if missing:
            raise UserError(_("The following information is required to register %(company)s with fiskaly: %(fields)s",
                company=self.display_name, fields=", ".join(missing)))

    def _l10n_it_fiskaly_taxpayer_name(self):
        self.ensure_one()
        if self.partner_id.is_company:
            return {
                'legal': self.name,
                'trade': self.name,
            }
        return {
            'legal': self.name,
            'person': {
                'gender': 'DIVERSE',
                'forename': ' '.join(self.name.split()[:1]),
                'surname': ' '.join(self.name.split()[1:]),
            },
        }

    def _l10n_it_fiskaly_taxpayer_payload(self):
        self.ensure_one()
        company = self.sudo()
        return {
            'type': 'COMPANY' if self.partner_id.is_company else 'INDIVIDUAL',
            'name': self._l10n_it_fiskaly_taxpayer_name(),
            'address': {
                'line': self._l10n_it_fiskaly_address_line(),
                'code': self.zip,
                'city': self.city,
                'country': self.country_id.code,
            },
            'fiscalization': {
                'type': 'IT',
                'tax_id_number': self._l10n_it_fiskaly_tax_id_number(),
                'vat_id_number': self._l10n_it_fiskaly_vat_id_number(),
                'credentials': {
                    'type': 'FISCONLINE',
                    'pin': company.l10n_it_fisconline_pin,
                    'password': company.l10n_it_fisconline_password,
                    'tax_id_number': company.l10n_it_fisconline_tax_id,
                },
            },
        }

    def _l10n_it_fiskaly_taxpayer_mode(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            return False
        with fiskaly_client(root, subject=True) as client:
            return client.get_taxpayer(root.l10n_it_fiskaly_taxpayer_id).get('mode', False)

    def action_l10n_it_fiskaly_update_fisconline_password(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            raise UserError(_("Please create the fiskaly taxpayer of %s first.", root.display_name))
        root._l10n_it_fiskaly_check_taxpayer_fields()
        with fiskaly_client(root, subject=True) as client:
            client.update_taxpayer_while_suspended(root.l10n_it_fiskaly_taxpayer_id, {
                'fiscalization': root._l10n_it_fiskaly_taxpayer_payload()['fiscalization'],
            })

    def action_l10n_it_fiskaly_create_taxpayer(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            root._l10n_it_fiskaly_check_taxpayer_fields()
            with fiskaly_client(root, subject=True) as client:
                response = client.create_taxpayer(root._l10n_it_fiskaly_taxpayer_payload())
            taxpayer_id = response.get('id')
            if not taxpayer_id:
                raise UserError(_("Fiskaly did not return a taxpayer identifier."))
            root.write({
                'l10n_it_fiskaly_taxpayer_id': taxpayer_id,
                'l10n_it_fiskaly_taxpayer_state': response.get('state'),
            })
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_l10n_it_fiskaly_update_taxpayer(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            raise UserError(_("Please create the fiskaly taxpayer of %s first.", root.display_name))
        root._l10n_it_fiskaly_check_taxpayer_fields()
        with fiskaly_client(root, subject=True) as client:
            response = client.update_taxpayer_while_suspended(
                root.l10n_it_fiskaly_taxpayer_id,
                root._l10n_it_fiskaly_taxpayer_payload(),
            )
        root.l10n_it_fiskaly_taxpayer_state = response.get('state')
        return root.l10n_it_fiskaly_taxpayer_state

    def action_l10n_it_fiskaly_commission_taxpayer(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            raise UserError(_("Please create the fiskaly taxpayer of %s first.", root.display_name))
        with fiskaly_client(root, subject=True) as client:
            response = client.update_taxpayer(root.l10n_it_fiskaly_taxpayer_id, {'state': 'COMMISSIONED'})
        root.l10n_it_fiskaly_taxpayer_state = response.get('state')
        return root.l10n_it_fiskaly_taxpayer_state

    def _l10n_it_fiskaly_location_payload(self):
        self.ensure_one()
        return {
            'name': self.name[:32],
            'address': {
                'line': self._l10n_it_fiskaly_address_line(),
                'code': self.zip,
                'city': self.city,
                'country': self.country_id.code,
            },
        }

    def action_l10n_it_fiskaly_update_location(self):
        self.ensure_one()
        if not self.l10n_it_fiskaly_location_id:
            raise UserError(_("Please create the fiskaly location of %s first.", self.display_name))
        self._l10n_it_fiskaly_check_location_fields()
        with fiskaly_client(self, subject=True) as client:
            response = client.update_location_while_suspended(
                self.l10n_it_fiskaly_location_id,
                self._l10n_it_fiskaly_location_payload(),
            )
        self.l10n_it_fiskaly_location_state = response.get('state')
        return self.l10n_it_fiskaly_location_state

    def action_l10n_it_fiskaly_create_location(self):
        self.ensure_one()
        root = self.root_id
        if not root.l10n_it_fiskaly_taxpayer_id:
            raise UserError(_("Please create the fiskaly taxpayer of %s first.", root.display_name))
        if not self.l10n_it_fiskaly_location_id:
            self._l10n_it_fiskaly_check_location_fields()
            with fiskaly_client(self, subject=True) as client:
                response = client.create_location({
                    'type': 'BRANCH',
                    'taxpayer': {
                        'id': root.l10n_it_fiskaly_taxpayer_id,
                    },
                    **self._l10n_it_fiskaly_location_payload(),
                })
            location_id = response.get('id')
            if not location_id:
                raise UserError(_("Fiskaly did not return a location identifier."))
            self.write({
                'l10n_it_fiskaly_location_id': location_id,
                'l10n_it_fiskaly_location_state': response.get('state'),
            })
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_l10n_it_fiskaly_commission_location(self):
        self.ensure_one()
        if not self.l10n_it_fiskaly_location_id:
            raise UserError(_("Please create the fiskaly location of %s first.", self.display_name))
        with fiskaly_client(self, subject=True) as client:
            response = client.update_location(self.l10n_it_fiskaly_location_id, {'state': 'COMMISSIONED'})
        self.l10n_it_fiskaly_location_state = response.get('state')
        return self.l10n_it_fiskaly_location_state
