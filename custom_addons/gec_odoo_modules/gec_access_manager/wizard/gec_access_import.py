from odoo import _, fields, models
from odoo.exceptions import UserError


class GecAccessImport(models.TransientModel):
    _name = 'gec.access.import'
    _description = 'Import Access Profiles'

    file = fields.Binary(string='File', required=True)
    filename = fields.Char()
    replace = fields.Boolean(
        string='Replace Profiles of the Same Name',
        help="A profile with the same name in this database is replaced. If unticked, the imported profile is added "
             "next to it, as '<name> (imported)'.")
    with_users = fields.Boolean(
        string='Also Assign the Users',
        help="Give the profiles to the users listed in the file. Users are matched by their login.")

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Choose the file to import."))
        content = self.file.decode('utf-8', errors='replace')
        profiles = self.env['gec.access.profile']._gec_import(content, replace=self.replace, with_users=self.with_users)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Imported Profiles"),
            'res_model': 'gec.access.profile',
            'view_mode': 'list,form',
            'domain': [('id', 'in', profiles.ids)],
        }
