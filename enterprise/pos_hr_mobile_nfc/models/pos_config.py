from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

from . import sdm


class PosConfig(models.Model):
    _inherit = 'pos.config'

    nfc_secure_login = fields.Boolean(string='Secure NFC Badges', copy=False, help='Badges encoded with the key skip the PIN.')
    nfc_encoding_key = fields.Char(string='Encoding Key', groups='point_of_sale.group_pos_manager', copy=False, help='SDM MAC key used to encode the badges, 32 hex digits.')
    nfc_manager_pin_required = fields.Boolean(string='PIN Required for Managers')

    @api.constrains('nfc_secure_login', 'nfc_encoding_key')
    def _check_nfc_encoding_key(self):
        for config in self:
            if config.nfc_encoding_key and not sdm.ENCODING_KEY.match(config.nfc_encoding_key):
                raise ValidationError(_('The NFC encoding key is an AES-128 key of 32 hexadecimal digits.'))
            if config.nfc_secure_login and not config.nfc_encoding_key:
                raise ValidationError(_('Secure NFC badges need the encoding key they were encoded with.'))

    def write(self, vals):
        if 'nfc_encoding_key' in vals:
            new_key = (vals['nfc_encoding_key'] or '').upper()
            rekeyed = self.sudo().filtered(lambda config: (config.nfc_encoding_key or '').upper() != new_key)
            self.env['hr.employee'].sudo().search([
                ('company_id', 'in', rekeyed.company_id.ids),
                ('nfc_badge_counter', '>', 0),
            ]).nfc_badge_counter = 0
        return super().write(vals)

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        for record in read_records:
            record.pop('nfc_encoding_key', None)
        return read_records

    def verify_nfc_badge(self, payload):
        self.ensure_one()
        parsed = sdm.parse(payload)
        if not self.nfc_secure_login or not parsed:
            return False
        uid, counter, mac = parsed
        domain = self._employee_domain(self.current_user_id.id) & Domain('barcode', '=', uid.hex().upper())
        employee = self.env['hr.employee'].sudo().search(domain, limit=1)
        key = bytes.fromhex(self.sudo().nfc_encoding_key)
        if not employee or counter <= employee.nfc_badge_counter or not sdm.is_genuine(key, uid, counter, mac):
            return False
        employee.nfc_badge_counter = counter
        return employee.id
