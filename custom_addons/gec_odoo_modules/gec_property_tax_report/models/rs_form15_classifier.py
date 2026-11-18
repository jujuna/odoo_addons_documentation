from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Tax Code art. 204(2)(a): GEL 0.24 per m2 a year; the municipal coefficient is at most 1.5 (art. 204(2)(b)).
BASE_NON_AGRI_RATE = 0.24

# Tax Code art. 202(1) caps the building rate at 1%. Units without a rate fall back to the cap:
# it can only overstate the tax, never understate it, and the line gets a warning.
DEFAULT_BUILDING_RATE = 1.0


def check_year_bounds(records):
    for record in records:
        for year in (record.valid_from, record.valid_to):
            if year and not 1900 <= year <= 2999:
                raise ValidationError(record.env._(
                    "Validity must be a YYYY year, or empty for an open boundary."))
        if record.valid_from and record.valid_to and record.valid_from > record.valid_to:
            raise ValidationError(record.env._("Valid To must be on or after Valid From."))


class RsForm15ClassifierMixin(models.AbstractModel):
    """Year-versioned rs.ge classifier entry; ``code`` is the ID written in the import file."""
    _name = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Classifier'
    _order = 'sequence, id'

    code = fields.Char(required=True, help="The rs.ge ID written into the import file.")
    name = fields.Char(
        required=True,
        help="The label exactly as rs.ge spells it; the import file carries it next to the code.")
    sequence = fields.Integer(default=10)
    valid_from = fields.Integer(string='Valid From (Year)')
    valid_to = fields.Integer(string='Valid To (Year)')
    active = fields.Boolean(default=True)

    @api.constrains('valid_from', 'valid_to')
    def _check_validity(self):
        check_year_bounds(self)

    def _is_valid(self, year):
        self.ensure_one()
        return (not self.valid_from or year >= self.valid_from) \
            and (not self.valid_to or year <= self.valid_to)


class RsForm15PropertyType(models.Model):
    """Part III column 2/3: the kind of taxable object, as the portal's dropdown offers it."""
    _name = 'rs.form15.property.type'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Property Type'

    display_code = fields.Char(string='RS Number', help="Number shown on the portal, e.g. 1.1")
    is_immovable = fields.Boolean(
        help="Immovable property: column 5 (acquisition year) is filled and the "
             "art. 202(1) revaluation coefficient applies. The portal hides both "
             "columns for movable types.")
    has_name = fields.Boolean(
        string='Named Object',
        help="The portal asks for the object's own name in column 2 (a pipeline, a "
             "building), so each asset is declared on its own row. Other types are "
             "declared per type, territorial unit and acquisition year.")
    is_leasing = fields.Boolean(
        string='Leased-Out Property',
        help="Group 5 of the rs.ge list. A leasing company declaring these rows is "
             "capped at 0.6% instead of 1% (Order 996 art. 88). ASSUMPTION of "
             "2026-09-21, inferred from the group 1 label, not verified on the portal.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Property type code must be unique.')


class RsForm15Territory(models.Model):
    """Part III column 4: the local self-government unit the object is registered in."""
    _name = 'rs.form15.territory'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Territorial Unit'

    _code_uniq = models.Constraint('UNIQUE(code)', 'Territorial unit code must be unique.')


class RsForm15YearAcquire(models.Model):
    """Part III column 5: the year the property was acquired, as the portal's dropdown offers it."""
    _name = 'rs.form15.year'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Year Acquired'

    _code_uniq = models.Constraint('UNIQUE(code)', 'Acquisition year must be unique.')

    @api.model
    def _for_year(self, year, create=False):
        """The portal's option for an acquisition year; one option covers everything before 2000.
        rs.ge adds one option per year with the year as its ID, so `create` adds a missing one
        instead of stopping the declaration on data rs.ge has not shipped yet."""
        code = '1999' if year < 2000 else str(year)
        option = self.search([('code', '=', code)], limit=1)
        if not option and create and year >= 2000:
            # An archived option still holds the unique code: reuse it rather than fail.
            option = self.with_context(active_test=False).search([('code', '=', code)], limit=1)
        if not option and create and year >= 2000:
            option = self.sudo().create({'code': code, 'name': code, 'sequence': (year - 1998) * 10})
            # Registered under the xmlid a later data file will use, as noupdate, so that
            # file finds this row instead of inserting the same code again.
            self.env['ir.model.data'].sudo()._update_xmlids([{
                'xml_id': 'gec_property_tax_report.year_%s' % code, 'record': option, 'noupdate': True}])
        return option


class RsForm15ExemptionBasis(models.Model):
    """Part III column 9 and part IV column 6: the legal ground, from the rs.ge list."""
    _name = 'rs.form15.exemption.basis'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Exemption Basis'

    note = fields.Char(help="The validity remark as rs.ge publishes it.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Exemption basis code must be unique.')


class RsForm15BuildingRate(models.Model):
    """Part III column 10. rs.ge publishes no table for this, so it is maintained here."""
    _name = 'rs.form15.building.rate'
    _description = 'rs.ge Form 15 Building Tax Rate'
    _order = 'tax_year desc, territory_id'

    territory_id = fields.Many2one(
        'rs.form15.territory', required=True, ondelete='cascade', index=True)
    tax_year = fields.Integer(required=True)
    rate = fields.Float(
        required=True, default=DEFAULT_BUILDING_RATE, digits=(5, 3),
        help="Percent, as written into column 10. Tax Code art. 202(1) caps it at 1%.")
    note = fields.Char()

    _territory_year_uniq = models.Constraint(
        'UNIQUE(territory_id, tax_year)', 'One building tax rate per territorial unit and year.')

    @api.constrains('rate', 'tax_year')
    def _check_rate(self):
        for record in self:
            if not 0 <= record.rate <= 1:
                raise ValidationError(self.env._(
                    "The building tax rate must be between 0 and 1 percent "
                    "(Tax Code art. 202(1))."))
            if not 1900 <= record.tax_year <= 2999:
                raise ValidationError(self.env._("The tax year must be a YYYY year."))

    @api.model
    def _rate_for(self, territory, year):
        """(rate in percent, True when it came from the table)."""
        record = self.search(
            [('territory_id', '=', territory.id), ('tax_year', '=', year)], limit=1)
        return (record.rate, True) if record else (DEFAULT_BUILDING_RATE, False)

    @api.model
    def _seed_year(self, year):
        """Create a capped row for every territorial unit that has none for that year."""
        covered = self.search([('tax_year', '=', year)]).territory_id.ids
        territories = self.env['rs.form15.territory'].search([('id', 'not in', covered)])
        return self.create([
            {'territory_id': territory.id, 'tax_year': year, 'rate': DEFAULT_BUILDING_RATE}
            for territory in territories
        ])


class RsForm15LandTerritory(models.Model):
    """Part IV column 2: region / municipality / zone, as deep as rs.ge splits it."""
    _name = 'rs.form15.land.territory'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Land Territorial Unit'

    region = fields.Char(index=True)
    municipality = fields.Char(index=True)

    _code_uniq = models.Constraint('UNIQUE(code)', 'Land territorial unit code must be unique.')


class RsForm15LandType(models.Model):
    """Part IV column 3: land kind. The rate column means different things per kind."""
    _name = 'rs.form15.land.type'
    _inherit = 'rs.form15.classifier.mixin'
    _description = 'rs.ge Form 15 Land Type'

    unit = fields.Selection(
        [('ha', 'Hectare'), ('sqm', 'Square Metre')], required=True, default='ha',
        help="Agricultural land is declared in hectares, non-agricultural in square metres.")
    uses_base_rate = fields.Boolean(
        string='Rate is a Coefficient',
        help="When set, the rate table holds a municipal coefficient applied to the "
             "statutory base rate, not an absolute amount per unit of area.")
    base_rate = fields.Float(
        digits=(6, 4), default=0.0,
        help="Statutory base rate per unit of area, used only when the rate is a coefficient.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Land type code must be unique.')

    def _unit_rate(self, table_rate):
        """The amount per hectare or square metre behind one rate-table value."""
        self.ensure_one()
        return self.base_rate * table_rate if self.uses_base_rate else table_rate


class RsForm15LandRate(models.Model):
    """One (land territory, land type) cell of the rs.ge land rate matrix."""
    _name = 'rs.form15.land.rate'
    _description = 'rs.ge Form 15 Land Rate'
    _order = 'land_territory_id, land_type_id, id'

    land_territory_id = fields.Many2one(
        'rs.form15.land.territory', required=True, ondelete='cascade', index=True)
    land_type_id = fields.Many2one(
        'rs.form15.land.type', required=True, ondelete='cascade', index=True)
    rate = fields.Float(required=True, digits=(8, 4))
    valid_from = fields.Integer(string='Valid From (Year)')
    valid_to = fields.Integer(string='Valid To (Year)')
    note = fields.Char()

    _pair_uniq = models.Constraint(
        'UNIQUE(land_territory_id, land_type_id, valid_from)',
        'One rate per land territorial unit, land type and validity start.')

    @api.constrains('valid_from', 'valid_to', 'rate')
    def _check_validity(self):
        check_year_bounds(self)
        for record in self:
            if record.rate < 0:
                raise ValidationError(self.env._("The land rate cannot be negative."))

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('install_mode'):
            # Keep manager edits through a classifier reload; only our own XML IDs.
            self.env['ir.model.data'].sudo().search([
                ('module', '=', 'gec_property_tax_report'),
                ('model', '=', self._name), ('res_id', 'in', self.ids),
            ]).write({'noupdate': True})
        return result

    @api.model
    def _rates_for(self, year):
        """{(land_territory_id, land_type_id): rate} for the whole matrix in that year."""
        rates = {}
        for rule in self.search([]):
            if (not rule.valid_from or year >= rule.valid_from) \
                    and (not rule.valid_to or year <= rule.valid_to):
                rates[(rule.land_territory_id.id, rule.land_type_id.id)] = rule.rate
        return rates


class RsForm15RevaluationCoefficient(models.Model):
    """Part III column 7: the art. 202(1) multiplier, as the portal's dropdown offers it:
    before 2000 x3, 2000-2003 x2, 2004 x1.5, unknown date x3; from 2005 none."""
    _name = 'rs.form15.revaluation.coefficient'
    _description = 'rs.ge Form 15 Revaluation Coefficient'
    _order = 'year_from'

    code = fields.Char(required=True, help="Written into column 7 verbatim, including '-'.")
    name = fields.Char(required=True)
    year_from = fields.Integer(help="0 means no lower bound.")
    year_to = fields.Integer(help="0 means open.")
    coefficient = fields.Float(required=True, digits=(3, 2), default=1.0)

    _code_uniq = models.Constraint('UNIQUE(code)', 'Coefficient code must be unique.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for band in self:
            band.display_name = f"{band.code} - {band.name}"

    @api.model
    def _band_for(self, acquisition_year):
        """The band record, so the line stores the portal's own option, not a number.
        An unknown acquisition year takes the highest band, as the rs.ge table states."""
        bands = self.search([])
        if not acquisition_year:
            return max(bands, key=lambda band: band.coefficient, default=bands.browse())
        for band in bands:
            if (not band.year_from or acquisition_year >= band.year_from) \
                    and (not band.year_to or acquisition_year <= band.year_to):
                return band
        return bands.browse()
