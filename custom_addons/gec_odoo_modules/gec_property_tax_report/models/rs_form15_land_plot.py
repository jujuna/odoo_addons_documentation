from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RsForm15LandPlot(models.Model):
    """A taxable land plot; its accounting, if any, is the optional linked asset."""
    _name = 'rs.form15.land.plot'
    _description = 'Property Tax Land Plot'
    _order = 'land_territory_id, name'
    _check_company_auto = True

    name = fields.Char(string='Address / Description', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    land_territory_id = fields.Many2one(
        'rs.form15.land.territory', string='Territorial Unit', required=True, index=True,
        ondelete='restrict', help="Declaration column 2. Drives the rate.")
    land_type_id = fields.Many2one(
        'rs.form15.land.type', string='Land Type', required=True, index=True,
        ondelete='restrict', help="Declaration column 3. Drives the rate and the unit of area.")
    unit = fields.Selection(related='land_type_id.unit', readonly=True)

    area = fields.Float(
        required=True, digits=(12, 4),
        help="Declaration column 4. Hectares for agricultural land, square metres otherwise.")
    exemption_basis_id = fields.Many2one(
        'rs.form15.exemption.basis', string='Exemption Basis', ondelete='restrict',
        help="Declaration column 6. Leave empty for the portal's "
             "“შეღავათით "
             "არ ვსარგებლობ”.")
    taxable_area = fields.Float(
        digits=(12, 4),
        help="Declaration column 5. The portal fills it only when an exemption applies; "
             "leave it at 0 and the whole area is taxed.")

    # Documents backing the exemption or the land quality, per Order 996 art. 88 paragraph 5.
    supporting_document = fields.Char()
    note = fields.Char()

    # Optional link to the land as booked in Fixed Assets. The plot stays the tax record
    # (area, type, zone); the asset is the accounting record and supplies the dates.
    asset_id = fields.Many2one(
        'account.asset', string='Asset', index=True, ondelete='set null', check_company=True,
        help="The land as booked in Fixed Assets. Its dates are used, and it is kept out of "
             "part III, which taxes property by value; land is taxed here by area.")
    date_acquired = fields.Date(
        string='Acquired On', compute='_compute_dates', store=True, readonly=False, precompute=True,
        help="Part IV declares the plot only if it was owned on the declaration's “Land as at” "
             "date. Empty means owned since before any declaration.")
    date_sold = fields.Date(
        string='Sold On', compute='_compute_dates', store=True, readonly=False, precompute=True,
        help="From this date the plot is no longer declared. Empty means still owned.")

    _asset_uniq = models.Constraint(
        'UNIQUE(asset_id)', 'An asset can be linked to one land plot only.')

    @api.depends('asset_id.acquisition_date', 'asset_id.main_variant_id.state',
                 'asset_id.main_variant_id.depreciation_move_ids.state',
                 'asset_id.main_variant_id.depreciation_move_ids.date')
    def _compute_dates(self):
        """A linked asset is the source of truth; an unlinked plot keeps what was typed."""
        for plot in self:
            if plot.asset_id:
                plot.date_acquired = plot.asset_id.acquisition_date
                plot.date_sold = plot.asset_id._rs_form15_disposal_date(plot.asset_id.main_variant_id)
            else:
                plot.date_acquired = plot.date_acquired
                plot.date_sold = plot.date_sold

    def _is_owned_on(self, day):
        """Owned on `day` itself counts: bought on 1 April is declared, sold on 1 April is not.
        An archived plot without a sale date was removed the old way, before Sold On existed."""
        self.ensure_one()
        if not self.active and not self.date_sold:
            return False
        return ((not self.date_acquired or self.date_acquired <= day)
                and (not self.date_sold or self.date_sold > day))

    @api.model_create_multi
    def create(self, vals_list):
        plots = super().create(vals_list)
        plots._rs_form15_exclude_assets()
        return plots

    def write(self, vals):
        previous = self.asset_id if 'asset_id' in vals else self.env['account.asset']
        result = super().write(vals)
        if 'asset_id' in vals:
            self._rs_form15_exclude_assets()
            self._rs_form15_release_assets(previous - self.asset_id)
        return result

    def unlink(self):
        assets = self.asset_id
        result = super().unlink()
        self.browse()._rs_form15_release_assets(assets)
        return result

    def _rs_form15_release_assets(self, assets):
        """An asset no plot points to any more goes back to part III: a wrong pick must
        not stay hidden. An asset another plot still links stays excluded."""
        still_linked = self.with_context(active_test=False).search([('asset_id', 'in', assets.ids)]).asset_id
        released = assets - still_linked
        if released:
            released.rs_form15_excluded = False

    def _rs_form15_exclude_assets(self):
        """Land is declared in part IV by area; the same land in part III would be taxed
        again by value."""
        assets = self.asset_id.filtered(lambda asset: not asset.rs_form15_excluded)
        if assets:
            assets.rs_form15_excluded = True

    @api.constrains('asset_id')
    def _check_asset_not_depreciated(self):
        """Attaching a depreciating asset is refused like changing an attached one."""
        self.asset_id._check_rs_form15_land_not_depreciated()

    @api.constrains('date_acquired', 'date_sold')
    def _check_dates(self):
        for plot in self:
            if plot.date_acquired and plot.date_sold and plot.date_sold < plot.date_acquired:
                raise ValidationError(self.env._(
                    "%s cannot be sold before it was acquired.", plot.name))

    @api.constrains('area', 'taxable_area', 'exemption_basis_id')
    def _check_area(self):
        for plot in self:
            if plot.area <= 0:
                raise ValidationError(self.env._("The area of %s must be positive.", plot.name))
            if plot.taxable_area < 0 or plot.taxable_area > plot.area:
                raise ValidationError(self.env._(
                    "The taxable area of %s cannot be negative or larger than the area.",
                    plot.name))
            if plot.taxable_area and not plot.exemption_basis_id:
                raise ValidationError(self.env._(
                    "%s has a taxable area but no exemption basis. The portal fills column 5 "
                    "only when an exemption applies.", plot.name))

    def action_rs_form15_create_asset(self):
        """Open a new land asset in a dialog; saving it links it to this plot
        (account.asset.create reads rs_form15_land_plot_id)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Land Asset"),
            'res_model': 'account.asset',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'rs_form15_land_plot_id': self.id},
        }

    def _declared_area(self):
        """Column 5 when an exemption reduced it, otherwise the whole area."""
        self.ensure_one()
        return self.taxable_area if self.exemption_basis_id and self.taxable_area else self.area
