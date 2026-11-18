from odoo import models
from odoo.exceptions import AccessError


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _record_to_stream(self, record, field_name):
        """ Refuse a hidden binary field (or one derived from it), always or under a condition when ``record`` matches.
        An access token gives a sudo record, so the user's rules are judged on ``record.sudo(False)``. A plain
        AccessError, not a profile refusal: one audit line per image would flood the log. """
        if record._name != 'ir.attachment' and not self.env.su:
            rules = self.env['gec.access.profile']._current_rules()
            if rules.enabled:
                user_record = record.sudo(False)
                hidden = user_record._gec_binary_family(user_record._gec_hidden(rules, record._name))
                if field_name in hidden or user_record._gec_hides_binary(rules, field_name):
                    raise AccessError(self.env._("Sorry, you are not allowed to access this document."))
        return super()._record_to_stream(record, field_name)
