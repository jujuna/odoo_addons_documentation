from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    rs_form30_category_id = fields.Many2one('rs.form30.category', string='Form 30 Category', ondelete='set null',
        help="Existing category used only while this contact has no category history.")
    rs_form30_category_history_ids = fields.One2many('rs.form30.partner.category', 'partner_id', string='Form 30 Category History',
        help="Category effective on each payment date. Periods must not overlap.")
    rs_form30_current_category_id = fields.Many2one('rs.form30.category', string='Current Form 30 Category',
        compute='_compute_rs_form30_current_category_id')
    rs_form30_individual_entrepreneur = fields.Boolean(string='Individual Entrepreneur (ი/მ)',
        help="Registered sole trader: they declare and pay their own income tax, "
        "so service fees paid to them belong in Form 30 annex E, not annex A.")
    rs_form30_small_business = fields.Boolean(string='Small Business Status (მცირე მეწარმე)',
        help="Holds small business status: they declare and pay their own income tax, so service fees paid to them belong in Form 30 annex E, not "
        "annex A.")
    rs_form30_service_type_id = fields.Many2one('rs.form30.service.type', string="Form 30 Service Type", ondelete='set null',
        help="Annex E service type of this contact's journal entries when their Withholding Tax has none (individual entrepreneurs and small "
        "businesses).")
    rs_form30_exempt_limit = fields.Float(string='Tax Exempt Under International Agreement',
        help="Withholding tax this recipient is exempt from under an international agreement. Each Form 30 line draws on it and reports the draw in "
        "column 12 \"Tax exempt or reduced under an international agreement\". One allowance per person, shared by every company that pays them.")
    rs_form30_exempt_stamp = fields.Datetime(copy=False,
        help="Written when a Form 30 export draws this contact's treaty allowance, so two exports drawing at once fail and retry instead of "
        "over-drawing.")
    rs_form30_exempt_usage_ids = fields.One2many('rs.form30.exempt.usage', 'partner_id', string='International Agreement Exemptions')
    rs_form30_exempt_used = fields.Float(string='Exempted So Far', compute='_compute_rs_form30_exempt')
    rs_form30_exempt_remaining = fields.Float(string='Still Exemptible', compute='_compute_rs_form30_exempt')

    @api.depends('rs_form30_category_id', 'rs_form30_category_history_ids.category_id',
                 'rs_form30_category_history_ids.date_from', 'rs_form30_category_history_ids.date_to')
    @api.depends_context('tz')
    def _compute_rs_form30_current_category_id(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.rs_form30_current_category_id = partner._rs_form30_category_on(today)

    @api.depends('rs_form30_exempt_limit', 'rs_form30_exempt_usage_ids.amount')
    def _compute_rs_form30_exempt(self):
        for partner in self:
            partner.rs_form30_exempt_used = sum(partner.rs_form30_exempt_usage_ids.mapped('amount'))
            partner.rs_form30_exempt_remaining = partner.rs_form30_exempt_limit - partner.rs_form30_exempt_used

    def action_rs_form30_exempt_usage(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("International Agreement Exemptions: %s", self.display_name),
            'res_model': 'rs.form30.exempt.usage',
            'view_mode': 'list',
            'domain': [('partner_id', '=', self.id)],
            'context': {'create': False, 'edit': False},
        }

    def _rs_form30_pays_own_tax(self):
        """True when the recipient settles their own income tax, so nothing is withheld at source."""
        return any(p.rs_form30_individual_entrepreneur or p.rs_form30_small_business for p in self)

    def _rs_form30_category_on(self, payment_date):
        """Resolve by cash-payment date; an explicit history gap never uses the old default."""
        if not self or not payment_date:
            return self.env['rs.form30.category']
        self.ensure_one()
        history = self.rs_form30_category_history_ids
        if not history:
            return self.rs_form30_category_id
        payment_date = fields.Date.to_date(payment_date)
        return history.filtered(
            lambda entry: (not entry.date_from or entry.date_from <= payment_date)
            and (not entry.date_to or payment_date <= entry.date_to)
        )[:1].category_id
