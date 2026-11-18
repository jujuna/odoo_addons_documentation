from markupsafe import Markup

from odoo import _, api, models


class GecAccessHistoryMixin(models.AbstractModel):
    _name = 'gec.access.history.mixin'
    _description = 'History of the Lines of an Access Profile'

    def _gec_history_kind(self):
        """ What a line is, for the note: "data rule", "field"... """
        return self._description

    def _gec_history_label(self):
        return self.display_name or ''

    def _gec_log(self, verb, changed=()):
        lines = self.filtered(lambda line: line.profile_id)
        if not lines:
            return
        lines.profile_id._gec_version_later()
        if self.env.context.get('gec_access_no_history'):
            # a restore or an import notes itself once, not line by line
            return
        detail = ''
        if changed:
            detail = ' (%s)' % ', '.join(self._fields[name].string for name in changed if name in self._fields)
        for profile, profile_lines in lines.grouped('profile_id').items():
            items = Markup('').join(
                Markup('<li>%s%s</li>') % (line._gec_history_label(), detail) for line in profile_lines)
            profile.message_post(
                body=Markup('<p>%s</p><ul>%s</ul>') % (
                    _("%(verb)s: %(kind)s", verb=verb, kind=self._gec_history_kind()), items),
                subtype_xmlid='mail.mt_note',
            )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.profile_id._gec_check_editor()
        lines._gec_log(_("Added"))
        return lines

    def write(self, vals):
        self.profile_id._gec_check_editor()
        result = super().write(vals)
        if 'profile_id' in vals:
            self.profile_id._gec_check_editor()
        self._gec_log(_("Changed"), changed=[name for name in vals if name != 'profile_id'])
        return result

    def unlink(self):
        self.profile_id._gec_check_editor()
        self._gec_log(_("Removed"))
        return super().unlink()
