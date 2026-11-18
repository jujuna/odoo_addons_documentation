from odoo import models


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _mail_get_partner_fields(self, introspect_fields=False):
        """Include partner field set automatically by studio as an SMS recipient."""
        fields = super()._mail_get_partner_fields(introspect_fields=introspect_fields)
        field = self._fields.get('x_studio_partner_id')
        if field and field.type == 'many2one' and field.comodel_name == 'res.partner':
            fields.append('x_studio_partner_id')
        return fields

    def _track_get_fields(self):
        # `_track_get_fields` shouldn't call `fields_get` as superuser.
        if self.env.context.get('studio'):
            return super(MailThread, self.with_context(studio=False))._track_get_fields()
        return super()._track_get_fields()
