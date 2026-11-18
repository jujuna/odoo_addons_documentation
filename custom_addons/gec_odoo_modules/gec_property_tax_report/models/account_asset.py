from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Order 996 art. 88 paragraph 4 sub-point d.b: the leasing company's rate cap.
LEASING_RATE_CAP = 0.6

# Tax Code art. 202(2): no revaluation coefficient for up to four years after an audited IFRS revaluation.
REVALUATION_EXCEPTION_YEARS = 4

# Types held only until the asset is put into use: 2 uninstalled equipment, 3 construction in progress.
PRE_USE_TYPE_CODES = ('17', '18')

# Fields copied on activation. The exemption amount is left out: it would be claimed twice.
ACTIVATION_INHERITED_FIELDS = (
    'rs_form15_territory_id',
    'rs_form15_excluded',
    'rs_form15_exemption_basis_id',
    'rs_form15_international_company_months',
    'rs_form15_leased_out',
    'rs_form15_leased_out_base_value',
    'rs_form15_revaluation_model_applied',
    'rs_form15_last_audit_date',
)


class AccountDepreciationModel(models.Model):
    _inherit = 'account.depreciation.model'

    rs_form15_property_type_id = fields.Many2one(
        'rs.form15.property.type', string='Property Tax Type', ondelete='restrict',
        help="Default property tax type for new assets on this model, for example "
             "3 construction in progress on a no-depreciation model. Set on the asset "
             "when it is created; an asset that already has a type keeps it.")


class AccountAsset(models.Model):
    _inherit = 'account.asset'

    rs_form15_property_type_id = fields.Many2one(
        'rs.form15.property.type', string='Property Tax Type', index=True, ondelete='restrict',
        help="Declaration column 3. The portal offers this as a dropdown, so an untagged "
             "asset cannot be declared.")
    rs_form15_territory_id = fields.Many2one(
        'rs.form15.territory', string='Property Tax Territorial Unit', index=True,
        ondelete='restrict',
        help="Declaration column 4. The local self-government unit the object is "
             "registered in; it drives the rate.")
    rs_form15_excluded = fields.Boolean(
        string='Exempt from Property Tax', tracking=True,
        help="Keep the asset out of the declaration altogether, for example land, which "
             "belongs in part IV.")

    rs_form15_exemption_basis_id = fields.Many2one(
        'rs.form15.exemption.basis', string='Exemption Basis', ondelete='restrict',
        help="Declaration column 9.")
    rs_form15_exemption_amount = fields.Monetary(
        string='Exemption Amount', currency_field='currency_id',
        help="Declaration column 8. Leave at 0 and let the international-company months "
             "derive it, or type the amount directly.")
    rs_form15_international_company_months = fields.Integer(
        string='International Company Months',
        help="Order 996 art. 88: for an international company the exemption is the average "
             "annual value pro-rated over the months the status was held. Status granted on "
             "5 May counts from 1 May, so that year has 8 months.")

    rs_form15_leased_out = fields.Boolean(
        string='Leased Out',
        help="Order 996 art. 88. For an ordinary company Odoo already carries the value the "
             "asset would have had if not leased out, so nothing changes; for a leasing "
             "company the value freezes at the first lease-out and the rate is capped.")
    rs_form15_leased_out_base_value = fields.Monetary(
        string='Value at Lease-Out', currency_field='currency_id',
        help="The book value at the moment the asset was first leased out. A leasing company "
             "declares it instead of the average annual value, for the part of the year the "
             "asset existed.")

    rs_form15_revaluation_model_applied = fields.Boolean(
        string='IFRS Revaluation Model',
        help="Tax Code art. 202(2): with audited statements the revaluation coefficient of "
             "art. 202(1) does not apply, for at most four calendar years after the audit.")
    rs_form15_last_audit_date = fields.Date(string='Last Audit Date')

    rs_form15_is_land = fields.Boolean(
        string='Land Plot', compute='_compute_rs_form15_is_land', store=True, readonly=False,
        help="This asset is land. Its plot (zone, type, area) is filled on the Land Plot page, "
             "declared in part IV by area and kept out of part III.")
    rs_form15_land_plot_ids = fields.One2many(
        'rs.form15.land.plot', 'asset_id', string='Land Plots')

    @api.depends('rs_form15_land_plot_ids')
    def _compute_rs_form15_is_land(self):
        """An asset a plot points to is land, also when it was linked from the plot side."""
        for asset in self:
            asset.rs_form15_is_land = asset.rs_form15_is_land or bool(asset.rs_form15_land_plot_ids)

    @api.model
    def _rs_form15_no_depreciation_model(self, company, account=None):
        """The model a land asset uses: the account's own one when it does not depreciate,
        otherwise the first 'No depreciation' model available to the company."""
        if account and account.depreciation_model_id.method == 'no_depreciation':
            return account.depreciation_model_id
        return self.env['account.depreciation.model'].search(
            [('method', '=', 'no_depreciation'), ('company_id', 'in', [False, company.id])], limit=1)

    @api.model
    def _rs_form15_context_plot(self):
        """The plot the asset dialog was opened for, while it has no asset yet. Buttons in that
        dialog carry the same context, so a plot already linked is never linked again."""
        plot = self.env['rs.form15.land.plot'].browse(self.env.context.get('rs_form15_land_plot_id')).exists()
        return plot if plot and not plot.asset_id else self.env['rs.form15.land.plot']

    @api.model
    def default_get(self, fields):
        """Opened from a land plot: prefill a non-depreciating land asset from that plot."""
        defaults = super().default_get(fields)
        plot = self._rs_form15_context_plot()
        if plot:
            plot_defaults = {
                'name': plot.name,
                'company_id': plot.company_id.id,
                'rs_form15_is_land': True,
                'acquisition_date': plot.date_acquired,
                'model_id': self._rs_form15_no_depreciation_model(plot.company_id).id,
            }
            defaults.update({key: value for key, value in plot_defaults.items() if key in fields and value})
        return defaults

    @api.onchange('account_asset_id')
    def _onchange_account_asset_id(self):
        """Land is not depreciated: an account whose model depreciates must not replace the
        'No depreciation' model of a land asset. Core's model onchange then refills the
        computation type and journal, which super() cleared along with the model."""
        super()._onchange_account_asset_id()
        for asset in self.filtered(lambda a: a.rs_form15_is_land and a.model_id.method != 'no_depreciation'):
            asset.model_id = asset._rs_form15_no_depreciation_model(asset.company_id, asset.account_asset_id)
            asset._onchange_model_id()

    def _rs_form15_default_property_type(self):
        """The type proposed by the asset's depreciation model, or the account's model."""
        self.ensure_one()
        model = self.model_id or self.account_asset_id.depreciation_model_id
        return model.rs_form15_property_type_id

    @api.model_create_multi
    def create(self, vals_list):
        """Propose the model's property tax type, and link the land plot the dialog was
        opened for (Land Plots → save a new plot → asset dialog)."""
        assets = super().create(vals_list)
        for asset in assets.filtered(lambda a: not a.rs_form15_property_type_id):
            default_type = asset._rs_form15_default_property_type()
            if default_type:
                asset.rs_form15_property_type_id = default_type
        plot = self._rs_form15_context_plot()
        if plot and len(assets) == 1:
            plot.asset_id = assets
        return assets

    @api.onchange('model_id', 'account_asset_id')
    def _onchange_rs_form15_default_property_type(self):
        for asset in self:
            if not asset.rs_form15_property_type_id:
                asset.rs_form15_property_type_id = asset._rs_form15_default_property_type()

    def _rs_form15_inherit_from(self, origin):
        """Copy the property tax fields from the asset this one replaced on activation.
        The type is kept from the origin unless it was a pre-use type."""
        self.ensure_one()
        vals = {
            field: origin[field].id if origin._fields[field].type == 'many2one' else origin[field]
            for field in ACTIVATION_INHERITED_FIELDS
        }
        if origin.asset_group_id and not self.asset_group_id:
            vals['asset_group_id'] = origin.asset_group_id.id
        if not self.rs_form15_property_type_id and origin.rs_form15_property_type_id.code not in PRE_USE_TYPE_CODES:
            vals['rs_form15_property_type_id'] = origin.rs_form15_property_type_id.id
        self.write(vals)
        if not self.rs_form15_property_type_id:
            self.message_post(body=self.env._(
                "Property tax: %(origin)s was %(type)s, which ends when depreciation starts. "
                "Set this asset's property tax type, or give its depreciation model a default.",
                origin=origin.display_name, type=origin.rs_form15_property_type_id.name))

    @api.onchange('rs_form15_exemption_basis_id')
    def _onchange_rs_form15_exemption_basis_id(self):
        """No basis means no exemption: clear the column 8 inputs."""
        for asset in self:
            if not asset.rs_form15_exemption_basis_id:
                asset.rs_form15_exemption_amount = 0.0
                asset.rs_form15_international_company_months = 0

    @api.constrains('model_id', 'account_asset_id', 'rs_form15_land_plot_ids')
    def _check_rs_form15_land_not_depreciated(self):
        """An asset a land plot is attached to keeps a 'No depreciation' model. Changing the
        account counts too: core recomputes a draft variant's model from it."""
        for asset in self.filtered('rs_form15_land_plot_ids'):
            model = asset.main_variant_id.model_id
            if model and model.method != 'no_depreciation':
                raise ValidationError(self.env._(
                    "%(asset)s is attached to the land plot %(plot)s. Land is not depreciated, so this "
                    "asset must keep a \"No depreciation\" model.\n\nTo depreciate it, create a new asset, "
                    "or first detach this asset from the land plot (Accounting > Configuration > "
                    "Land Plots, clear its Asset).",
                    asset=asset.display_name, plot=asset.rs_form15_land_plot_ids[:1].display_name))

    @api.constrains('rs_form15_international_company_months')
    def _check_rs_form15_months(self):
        for asset in self:
            if not 0 <= asset.rs_form15_international_company_months <= 12:
                raise ValidationError(self.env._(
                    "International company months must be between 0 and 12."))

    def _rs_form15_book_value(self, date):
        """Net book value at a date, read from the main variant (the accounting ledger)."""
        self.ensure_one()
        return self._rs_form15_variant_book_value(self.main_variant_id, date)

    def _rs_form15_average(self, year):
        """Column 6 for one asset: (value at 1 January + value at 31 December) / 2.

        A leasing company declares leased-out property at its value when first leased out
        (Order 996 art. 88 d.a / d.b), but only for the part of the year the asset existed:
        each of the two dates on which it was not yet acquired or already disposed of takes
        its half away. Existence is read from the dates, not the value: a fully depreciated
        asset is still owned and still leased out."""
        self.ensure_one()
        days = (date(year, 1, 1), date(year, 12, 31))
        if self._rs_form15_lease_frozen():
            present = sum(1 for day in days if self._rs_form15_exists_on(day))
            return self.rs_form15_leased_out_base_value * present / 2.0
        return sum(self._rs_form15_book_value(day) for day in days) / 2.0

    def _rs_form15_lease_frozen(self):
        """True when column 6 is the value at lease-out rather than the book value."""
        self.ensure_one()
        return bool(self.company_id.rs_form15_is_leasing_company and self.rs_form15_leased_out
                    and self.rs_form15_leased_out_base_value)

    def _rs_form15_exists_on(self, day):
        """Acquired on or before `day` and not yet disposed of, the same bounds the book value uses."""
        self.ensure_one()
        variant = self.main_variant_id
        disposal_date = self._rs_form15_disposal_date(variant)
        acquired = variant.acquisition_date if variant else self.acquisition_date
        return bool(variant) and not (acquired and acquired > day) and not (disposal_date and disposal_date <= day)

    @api.model
    def _rs_form15_variant_book_value(self, variant, date):
        """Mirrors the variant's _compute_value_residual; reversals net out as negative moves."""
        if not variant:
            return 0.0
        if variant.acquisition_date and variant.acquisition_date > date:
            return 0.0
        disposal_date = self._rs_form15_disposal_date(variant)
        if disposal_date and disposal_date <= date:
            return 0.0
        depreciated = sum(
            move.depreciation_value
            for move in variant.depreciation_move_ids
            if move.state == 'posted' and move.date and move.date <= date
        )
        value = variant.original_value - variant.already_depreciated_amount_import - depreciated
        # Gross increases are separate assets, added as core does.
        return value + sum(
            self._rs_form15_variant_book_value(child, date) for child in variant.children_ids)

    @api.model
    def _rs_form15_disposal_date(self, variant):
        """Core's disposal_date is the last date of all the variant's entries. A back-dated
        sale leaves later entries behind: cancelled under a restrictive audit trail, reversed
        in a hashed journal. Neither those entries nor their reversals date the sale."""
        if variant.state != 'close':
            return False
        moves = variant.depreciation_move_ids
        reversed_moves = moves.filtered(lambda move: move.reversal_move_ids.filtered(lambda r: r.state == 'posted'))
        dates = (moves - reversed_moves).filtered(
            lambda move: move.state != 'cancel' and move.date and not move.reversed_entry_id).mapped('date')
        return max(dates) if dates else variant.disposal_date

    def _rs_form15_acquisition_year(self):
        self.ensure_one()
        return self.acquisition_date.year if self.acquisition_date else 0

    def _rs_form15_coefficient_exempt(self, tax_year):
        """True while the art. 202(2) audited-revaluation exception still runs."""
        self.ensure_one()
        if not self.rs_form15_revaluation_model_applied or not self.rs_form15_last_audit_date:
            return False
        return tax_year - self.rs_form15_last_audit_date.year <= REVALUATION_EXCEPTION_YEARS

    def _rs_form15_exemption(self, average_value):
        """Column 8: the explicit amount, else the average value pro-rated over the
        international-company months (Order 996 art. 88: 120 000 / 12 x 8 = 80 000)."""
        self.ensure_one()
        if self.rs_form15_exemption_amount:
            # Capped at the asset's own value: the row sums exemptions over its assets.
            return min(self.rs_form15_exemption_amount, max(average_value, 0.0))
        months = self.rs_form15_international_company_months
        return average_value / 12.0 * months if months else 0.0


class AccountAssetVariant(models.Model):
    _inherit = 'account.asset.variant'

    @api.constrains('model_id')
    def _check_rs_form15_land_not_depreciated(self):
        """The model can also be changed on the variant form: same rule as on the asset."""
        self.filtered(lambda v: v == v.asset_id.main_variant_id).asset_id._check_rs_form15_land_not_depreciated()
