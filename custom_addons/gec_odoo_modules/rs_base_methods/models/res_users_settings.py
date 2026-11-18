from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsersSettings(models.Model):
    _inherit = 'res.users.settings'

    rs_username = fields.Char(string='RS Username', company_dependent=True)
    rs_password = fields.Char(string='RS Password', company_dependent=True)
    rs_user_id = fields.Char(string='RS User ID (SOAP)', company_dependent=True)
    rs_un_id = fields.Integer(string='RS Taxpayer ID', company_dependent=True)
    rs_is_responsible = fields.Boolean(string='RS Responsible User', company_dependent=True)
    rs_access_token = fields.Char(string='RS Access Token (REST)', company_dependent=True)
    rs_token_expiry = fields.Datetime(string='RS Token Expiry (REST)', company_dependent=True)
    rs_device_code = fields.Char(string='RS Device Code (REST)', company_dependent=True)
    rs_device_paired_on = fields.Datetime(string='RS Device Paired On', company_dependent=True)

    @api.model
    def _get_fields_blacklist(self):
        """Keep the rs.ge login, ids and tokens out of session_info: only the server uses them."""
        return super()._get_fields_blacklist() + ['rs_username', 'rs_password', 'rs_user_id', 'rs_un_id', 'rs_is_responsible', 'rs_access_token',
            'rs_token_expiry', 'rs_device_code', 'rs_device_paired_on']

    @api.constrains('rs_is_responsible')
    def _check_single_rs_responsible(self):
        """One responsible user per company, since the crons run its rs.ge operations as that user."""
        for settings in self.filtered('rs_is_responsible'):
            other = self.search([('rs_is_responsible', '=', True), ('user_id.active', '=', True), ('id', '!=', settings.id)], limit=1)
            if other:
                raise ValidationError(_("%(other)s is already the RS Responsible User of %(company)s. Untick the flag there before assigning it to "
                    "%(user)s.", other=other.user_id.display_name, company=self.env.company.display_name, user=settings.user_id.display_name))
