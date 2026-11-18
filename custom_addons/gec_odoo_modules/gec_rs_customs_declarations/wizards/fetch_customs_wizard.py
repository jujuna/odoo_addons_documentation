from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GecCustomsFetchWizard(models.TransientModel):
    _name = 'gec.customs.fetch.wizard'
    _description = 'Fetch RS Customs Declarations'

    user_id = fields.Many2one(
        'res.users', string='RS Account', required=True,
        default=lambda self: self.env.user,
        help="Odoo user whose RS credentials will be used. The account must have "
             "the CustomsDeclarations module enabled on rs.ge.",
    )
    date_from = fields.Date(
        string='From', required=True,
        default=lambda self: fields.Date.context_today(self) - timedelta(days=7),
    )
    date_to = fields.Date(
        string='To (exclusive)', required=True,
        default=lambda self: fields.Date.context_today(self),
        help="End date is exclusive per RS API. Max 20 days between From and To.",
    )

    @api.constrains('date_from', 'date_to')
    def _check_range(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise UserError(_("'To' must be on or after 'From'."))
            if (rec.date_to - rec.date_from).days > 20:
                raise UserError(_(
                    "RS allows at most 20 days per call. You requested %s.",
                    (rec.date_to - rec.date_from).days,
                ))

    def action_fetch(self):
        self.ensure_one()
        Line = self.env['gec.customs.declaration.line']
        created, refreshed = Line.fetch_from_rs(
            self.date_from, self.date_to, user=self.user_id,
        )
        action = self.env['ir.actions.act_window']._for_xml_id(
            'gec_rs_customs_declarations.action_customs_declaration_line'
        )
        action['context'] = dict(self.env.context, search_default_recently_fetched=1)
        return {
            **action,
            'display_name': _("Customs Declarations — fetched %s new, refreshed %s",
                              created, refreshed),
        }
