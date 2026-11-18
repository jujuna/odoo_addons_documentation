from datetime import date
from lxml import etree
from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import BinaryBytes, float_compare, float_is_zero

SS_NS = 'urn:schemas-microsoft-com:office:spreadsheet'
SS = '{%s}' % SS_NS
NSMAP = {
    None: SS_NS,
    'o': 'urn:schemas-microsoft-com:office:office',
    'x': 'urn:schemas-microsoft-com:office:excel',
    'ss': SS_NS,
    'html': 'http://www.w3.org/TR/REC-html40',
}

# Column order of temp_15_2.xml, read by the portal by position; keep in step with _export_values.
PART4_HEADERS = [
    'ტერიტორიული ერთეულის დასახელება მიწის ნაკვეთის მდებარეობა ID',
    'ტერიტორიული ერთეულის დასახელება მიწის ნაკვეთის მდებარეობა',
    'სახეობა და აღწერილობა ID',
    'სახეობა და აღწერილობა',
    'ფართობი (ჰა, კვ. მ.) ',
    'დაბეგვრის ობიექტის ფართობი საგადასახადო შეღავათის გათვალიწინებით',
    'საგადასახადო შეღავათის საფუძველი',
    'გადასახადის განიკვეთი',
    'ქონების გადასახადი',
]

# Style IDs of temp_15_2.xml: s65 default, s64 header, s63 data cells.
PART4_STYLES = {
    's63': {'border': True},
    's64': {'border': True, 'fill': '#EEECE1'},
    's65': {},
}


# Column order of temp_15_1_2.xml, read by the portal by position.
PART3_HEADERS = [
    'ქონების დასახელება ID',
    'ქონების დასახელება',
    'ტერიტორიული ერთე-ული ID',
    'ტერიტორიული ერთე-ული',
    'ქონების მიღების წელი (ივსება უძრავ ქონებაზე)',
    'ქონების საშუალო წლიური საბალანსო ნარჩენი ღირებულება  ',
    'უძრავი ქონების აფასების კოეფიცი-ენტი',
    'საგადასახდო შეღავათის თანხა',
    'საგადასახდო შეღავათის შეღა-ვათის საფუძ-ველი',
    'გადასა-ხადის განაკვე-თი ',
    'გადასა-ხადის თანხა ',
    'საანგა-რიშო პერიო-დის მიხედ-ვით დარიც-ხული მიმდი-ნარე გადასა-ხდელი',
    'ექვემდე-ბარება დამატე-ბით დარიც-ხვას (+); შემცი-რებას (-)',
    'საწარმოს/ორგანიზაციის არსებობის პერიოდი',
    'გადასახადის თანხა არსებობის პერიოდის გათვალისწინებით',
]

# temp_15_1_2.xml swaps the roles of s63 and s64.
PART3_STYLES = {
    's62': {},
    's63': {'border': True, 'fill': '#EEECE1'},
    's64': {'border': True},
}

# Order 996 art. 88 para. 4 l: column 13 is "column 11, or column 15 where one exists" minus column 12.
# The portal and rs.ge's sample row use column 11; the instruction wins until a portal upload settles it.
DIFFERENCE_USES_PRORATED = True

# Order 996 art. 88 paragraph 4 sub-point d.b.
LEASING_RATE_CAP = 0.6


def _number(value, digits=2):
    """Decimal with a dot and no trailing zeros: 250, 250.5, 0."""
    return ('%.*f' % (digits, value or 0.0)).rstrip('0').rstrip('.') or '0'


class RsForm15Declaration(models.Model):
    """Annual enterprise property tax declaration, rs.ge annex V-01."""
    _name = 'rs.form15.declaration'
    _description = 'rs.ge Form 15 Annual Property Tax Declaration'
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict',
                                 default=lambda self: self.env.company)

    currency_id = fields.Many2one(related='company_id.currency_id')

    date_from = fields.Date(string='Period', required=True,
                            default=lambda self: date(fields.Date.context_today(self).year - 1, 1, 1),
                            help="First day of the reporting year. Part III reports the year that ended.")

    date_to = fields.Date(compute='_compute_period', store=True)

    tax_year = fields.Integer(compute='_compute_period', store=True,
                              help="YYYY, used for classifier validity and for the part III columns.")

    land_reference_date = fields.Date(string='Land as at', required=True,
                                      default=lambda self: date(fields.Date.context_today(self).year, 4, 1),
                                      help="Tax Code art. 205(2): the declaration reports property for the past year "
                                           "and land for the current (filing) year, as at 1 April (art. 203). So it "
                                           "defaults to 1 April of the year after the period. Its year drives the "
                                           "part IV rate lookup.")

    land_year = fields.Integer(compute='_compute_period', store=True)

    kind = fields.Selection([('primary', 'პირველადი'), ('corrected', 'შესწორებული')],required=True, default='primary',
                            help="Part I of the form. A correction is this same record, re-generated and re-flagged.")

    months_of_existence = fields.Integer(help="Declaration column 14. Filled only when the company existed an incomplete "
                                              "calendar year. A month counts in full when registration falls on or before "
                                              "the 15th, or deregistration after the 15th (Order 996 art. 88).")

    state = fields.Selection([('draft', 'Draft'), ('exported', 'Exported')], required=True, default='draft', copy=False)

    part3_line_ids = fields.One2many('rs.form15.part3.line', 'declaration_id', copy=False)
    part3_count = fields.Integer(compute='_compute_totals', store=True)

    part3_total = fields.Monetary(string='Property Tax', compute='_compute_totals', store=True,
                                  currency_field='currency_id')

    part4_line_ids = fields.One2many('rs.form15.part4.line', 'declaration_id', copy=False)
    part4_count = fields.Integer(compute='_compute_totals', store=True)
    part4_total = fields.Monetary(string='Land Tax', compute='_compute_totals', store=True, currency_field='currency_id')
    warning_count = fields.Integer(compute='_compute_totals', store=True)
    next_advance_amount = fields.Monetary(string='Next Year Advance', compute='_compute_next_advance',
                                          currency_field='currency_id',
                                          help="Tax Code art. 205(3): next year's current payment is this year's full "
                                               "annual property tax (column 11, even for an incomplete year, art. 205(9)), "
                                               "paid once by 15 June. It may be reduced if the tax is expected to fall by "
                                               "at least 50% and the tax office is told by 1 June (art. 205(4)).")
    next_advance_date = fields.Date(string='Advance Due', compute='_compute_next_advance')
    export_file_3 = fields.Binary(string='Part III File', readonly=True, copy=False)
    export_filename_3 = fields.Char(readonly=True, copy=False)
    export_file_4 = fields.Binary(string='Part IV File', readonly=True, copy=False)
    export_filename_4 = fields.Char(readonly=True, copy=False)

    _company_period_uniq = models.Constraint(
        'UNIQUE(company_id, date_from)', 'One declaration per company and year.')

    @api.depends('company_id.name', 'date_from')
    def _compute_name(self):
        for declaration in self:
            year = declaration.date_from.year if declaration.date_from else ''
            declaration.name = (
                f"Property Tax {year} {declaration.company_id.name or ''}").strip()

    @api.depends('date_from', 'land_reference_date')
    def _compute_period(self):
        for declaration in self:
            start = declaration.date_from
            declaration.date_to = date(start.year, 12, 31) if start else False
            declaration.tax_year = start.year if start else 0
            declaration.land_year = (
                declaration.land_reference_date.year
                if declaration.land_reference_date else declaration.tax_year)

    @api.depends('part4_line_ids.tax_amount', 'part4_line_ids.warning',
                 'part3_line_ids.tax_amount', 'part3_line_ids.warning')
    def _compute_totals(self):
        for declaration in self:
            part3 = declaration.part3_line_ids
            part4 = declaration.part4_line_ids
            declaration.part3_count = len(part3)
            declaration.part3_total = sum(part3.mapped('tax_amount'))
            declaration.part4_count = len(part4)
            declaration.part4_total = sum(part4.mapped('tax_amount'))
            declaration.warning_count = len(part3.filtered('warning')) + len(part4.filtered('warning'))

    @api.depends('part3_total', 'tax_year')
    def _compute_next_advance(self):
        for declaration in self:
            declaration.next_advance_amount = declaration.part3_total
            declaration.next_advance_date = (
                date(declaration.tax_year + 1, 6, 15) if declaration.tax_year else False)

    @api.onchange('date_from')
    def _onchange_date_from(self):
        """Land is reported as at 1 April of the filing year, the year after the period (art. 205(2))."""
        for declaration in self:
            if declaration.date_from:
                declaration.land_reference_date = date(declaration.date_from.year + 1, 4, 1)

    @api.constrains('date_from', 'months_of_existence')
    def _check_period(self):
        for declaration in self:
            start = declaration.date_from
            if start and (start.day, start.month) != (1, 1):
                raise ValidationError(self.env._("The reporting period must start on 1 January: the declaration is "
                                                 "annual and the form carries a single year."))
            if not 0 <= declaration.months_of_existence <= 11:
                raise ValidationError(self.env._("Column 14 is filled only for an incomplete year: 1 to 11 months, "
                                                 "or 0 for a full year."))
        self.part4_line_ids._check_matrix()
        self.part3_line_ids._check_rate()

    def write(self, vals):
        if 'company_id' in vals and any(declaration.company_id.id != vals['company_id']
                                        and (declaration.part4_line_ids or declaration.part3_line_ids)
                                        for declaration in self):
            raise UserError(self.env._("You cannot change the company of a declaration that has lines."))
        if 'months_of_existence' in vals and any(declaration.state == 'exported'
                                                 and declaration.months_of_existence != vals['months_of_existence']
                                                 for declaration in self):
            raise UserError(self.env._("Reset the declaration to draft before changing the months of existence: "
                                       "the exported file would no longer match the rows."))
        return super().write(vals)

    def action_draft(self):
        """Back to draft; the exported files no longer match once rows change, so drop them."""
        self.write(dict(self._empty_export_files(), state='draft'))

    def _empty_export_files(self, parts=('3', '4')):
        return {name % part: False for part in parts for name in ('export_file_%s', 'export_filename_%s')}

    def _export_filename(self, part, year):
        company = self.company_id
        return 'form15_part%s_%s_%s.xml' % (part, company.vat or company.id, year)

    def action_generate(self):
        """Rebuild both parts."""
        self.action_generate_part3()
        self.action_generate_part4()
        return True

    def action_generate_part3(self):
        """Rebuild the property rows from Fixed Assets; manual rows are kept."""
        for declaration in self:
            if declaration.state != 'draft':
                raise UserError(self.env._("Reset the declaration to draft before regenerating it."))
            generated = declaration.part3_line_ids.filtered(lambda line: line.source != 'manual')
            typed_advances = {}
            for line in generated.filtered('advance_amount'):
                key = (line.property_type_id.id, line.territory_id.id, line._object_key())
                typed_advances[key] = typed_advances.get(key, 0.0) + line.advance_amount
            generated.unlink()
            declaration.write(dict(declaration._empty_export_files(), part3_line_ids=[
                Command.create(vals) for vals in declaration._part3_line_vals(typed_advances)]))
        return True

    def _part3_assets(self):
        """Assets with a value in the reporting year; gross increases count in their parent.
        Archived (closed) assets are read too; plot-linked land is declared in part IV."""
        self.ensure_one()
        land = self.env['rs.form15.land.plot'].with_context(active_test=False).search(
            [('company_id', '=', self.company_id.id), ('asset_id', '!=', False)]).asset_id
        return self.env['account.asset'].with_context(active_test=False).search([
            ('company_id', '=', self.company_id.id),
            ('main_variant_id.state', 'in', ('open', 'paused', 'close')),
            ('main_variant_id.parent_id', '=', False),
            ('rs_form15_excluded', '=', False),
            ('id', 'not in', land.ids),
            '|', '|', ('main_variant_id.state', '!=', 'close'),
            ('main_variant_id.disposal_date', '=', False),
            ('main_variant_id.disposal_date', '>=', date(self.tax_year, 1, 1)),
        ])

    def _part3_line_vals(self, typed_advances=None):
        """One row per (property type, territorial unit, acquisition year). A named type
        (pipeline, building) gets one row per object: the asset's group, else the asset."""
        self.ensure_one()
        year = self.tax_year
        untagged = []
        groups = {}

        for asset in self._part3_assets():
            average = asset._rs_form15_average(year)
            if float_is_zero(average, precision_rounding=self.currency_id.rounding):
                continue
            if not asset.rs_form15_property_type_id or not asset.rs_form15_territory_id:
                untagged.append(asset.display_name)
                continue

            property_type = asset.rs_form15_property_type_id
            exempt_from_coefficient = asset._rs_form15_coefficient_exempt(year)
            acquisition_year = asset._rs_form15_acquisition_year() if property_type.is_immovable else 0
            if property_type.has_name:
                # One object, one row: its year is the earliest of its assets, below.
                declared_object = asset.asset_group_id or asset
                key = (property_type.id, asset.rs_form15_territory_id.id, 0,
                       declared_object._name, declared_object.id)
            else:
                declared_object = None
                key = (property_type.id, asset.rs_form15_territory_id.id, acquisition_year, False, False)
            group = groups.setdefault(key, {
                'object': declared_object,
                'property_type': property_type,
                'territory': asset.rs_form15_territory_id,
                'acquisition_year': acquisition_year,
                'average': 0.0,
                'exemption': 0.0,
                'exemption_basis': asset.rs_form15_exemption_basis_id,
                'assets': self.env['account.asset'],
                'exempt_flags': [],
            })
            if acquisition_year:
                group['acquisition_year'] = min(group['acquisition_year'] or acquisition_year, acquisition_year)
            group['average'] += average
            group['exemption'] += asset._rs_form15_exemption(average)
            group['assets'] |= asset
            # Art. 202(2) belongs to the declared object, not to each of its bills.
            group['exempt_flags'].append(exempt_from_coefficient)
            if asset.rs_form15_exemption_basis_id:
                group['exemption_basis'] = asset.rs_form15_exemption_basis_id

        if untagged:
            raise UserError(self.env._("These assets have no property tax type or territorial unit, and the "
                                       "portal offers both only as dropdowns:\n%s", '\n'.join(untagged[:40])))

        coefficients = self.env['rs.form15.revaluation.coefficient']
        years = self.env['rs.form15.year']
        building_rates = self.env['rs.form15.building.rate']
        advances = self._part3_previous_advances(typed_advances)
        missing_years = []
        vals_list = []
        for (type_id, territory_id, _year, _model, _object_id), group in groups.items():
            property_type = group['property_type']
            territory = group['territory']
            acquisition_year = group['acquisition_year']
            declared_object = group['object']
            exempt = all(group['exempt_flags'])
            warnings = []
            if property_type.is_immovable and not exempt and any(group['exempt_flags']):
                warnings.append(self.env._("IFRS revaluation is set on only some assets of this object; "
                                           "the revaluation coefficient was applied."))
            # The portal asks every immovable row for a coefficient and does not check it
            # against the year, so an art. 202(2) exemption is declared as the 1.0 option.
            if not property_type.is_immovable:
                band = coefficients.browse()
            elif exempt:
                band = coefficients.search([('coefficient', '=', 1.0)], limit=1)
            else:
                band = coefficients._band_for(acquisition_year)
            coefficient = band.coefficient if band else 1.0
            year_option = years._for_year(acquisition_year) if acquisition_year else years
            if acquisition_year and not year_option:
                year_option = years._for_year(acquisition_year, create=True)
                if year_option:
                    warnings.append(self.env._("The acquisition year option %s was added automatically; "
                                               "check that the portal offers it.", acquisition_year))
            if acquisition_year and not year_option:
                missing_years.extend(group['assets'].mapped('display_name'))

            rate, from_table = building_rates._rate_for(territory, year)
            if not from_table:
                warnings.append(self.env._("No building tax rate is configured for this territorial unit; "
                                           "the 1% cap of Tax Code art. 202(1) was used."))
            if property_type.is_leasing and self.company_id.rs_form15_is_leasing_company:
                rate = min(rate, LEASING_RATE_CAP)

            if declared_object is None:
                object_key, name = ('name', ''), ''
            elif declared_object._name == 'account.asset.group':
                object_key, name = ('group', declared_object.id), declared_object.name or ''
            else:
                object_key = ('asset', declared_object.id)
                name = declared_object.with_context(lang=self._rs_form15_lang()).name or ''

            base = group['average'] * coefficient - group['exemption']
            tax_amount = self.currency_id.round(max(base, 0.0) * rate / 100.0)
            vals_list.append({
                'source': 'asset',
                'asset_id': object_key[1] if object_key[0] == 'asset' else False,
                'asset_group_id': object_key[1] if object_key[0] == 'group' else False,
                'property_type_id': type_id,
                'territory_id': territory_id,
                'acquisition_year_id': year_option.id,
                'average_value': self.currency_id.round(group['average']),
                'revaluation_coefficient_id': band.id,
                'exemption_amount': self.currency_id.round(group['exemption']),
                'exemption_basis_id': group['exemption_basis'].id,
                'tax_rate': rate,
                'tax_amount': tax_amount,
                'advance_amount': self._part3_take_advance(advances, type_id, territory_id, object_key, name),
                'asset_ids': [Command.set(group['assets'].ids)],
                'warning': ' '.join(warnings),
            })
        if missing_years:
            raise UserError(self.env._("The acquisition year of these assets is missing from Acquisition Years, "
                                       "and the portal offers the year only as a dropdown:\n%s",
                                       '\n'.join(missing_years[:40])))
        return vals_list

    def _rs_form15_lang(self):
        """Names go to rs.ge in the company's language, whoever presses Generate."""
        return self.company_id.partner_id.lang or self.env.lang

    def _part3_previous_advances(self, typed_advances=None):
        """Column 12 is last year's column 11, the full-year figure, never column 15
        (Order 996 art. 88). Keyed by type, unit and declared object; without last
        year's declaration, the typed column 12 is kept."""
        self.ensure_one()
        previous = self.search([('company_id', '=', self.company_id.id), ('tax_year', '=', self.tax_year - 1),], limit=1)
        if not previous.part3_line_ids:
            return dict(typed_advances or {})
        advances = {}
        for line in previous.part3_line_ids:
            key = (line.property_type_id.id, line.territory_id.id, line._object_key())
            advances[key] = advances.get(key, 0.0) + line.tax_amount
        return advances

    @api.model
    def _part3_take_advance(self, advances, type_id, territory_id, object_key, name):
        """Hand out each advance once; a named row falls back to last year's row name."""
        key = (type_id, territory_id, object_key)
        if key in advances:
            return advances.pop(key)
        if object_key[0] != 'name' and name:
            return advances.pop((type_id, territory_id, ('name', name)), 0.0)
        return 0.0

    def action_generate_part4(self):
        """Rebuild the land rows from the plot register; manual rows are kept."""
        for declaration in self:
            if declaration.state != 'draft':
                raise UserError(self.env._("Reset the declaration to draft before regenerating it."))
            declaration.part4_line_ids.filtered(lambda line: line.source != 'manual').unlink()
            declaration.write(dict(declaration._empty_export_files(),
                                   part4_line_ids=[Command.create(vals) for vals in declaration._part4_line_vals()]))
        return True

    def _part4_line_vals(self):
        """One row per plot owned on the "Land as at" date, valued with the rs.ge rate
        matrix of that year."""
        self.ensure_one()
        plots = self.env['rs.form15.land.plot'].with_context(active_test=False).search(
            [('company_id', '=', self.company_id.id)]).filtered(
            lambda plot: plot._is_owned_on(self.land_reference_date))
        rates = self.env['rs.form15.land.rate']._rates_for(self.land_year)
        vals_list = []
        for plot in plots:
            table_rate = rates.get((plot.land_territory_id.id, plot.land_type_id.id))
            warning = ''
            if table_rate is None:
                warning = self.env._("No rs.ge rate covers this territorial unit and land type.")
                table_rate = 0.0
            elif float_is_zero(table_rate, precision_digits=4):
                warning = self.env._("The rs.ge rate for this territorial unit and land type is zero.")
            declared_area = plot._declared_area()
            unit_rate = plot.land_type_id._unit_rate(table_rate)
            vals_list.append({
                'plot_id': plot.id,
                'source': 'plot',
                'land_territory_id': plot.land_territory_id.id,
                'land_type_id': plot.land_type_id.id,
                'area': plot.area,
                'taxable_area': plot.taxable_area,
                'exemption_basis_id': plot.exemption_basis_id.id,
                'rate': table_rate,
                'tax_amount': self.currency_id.round(declared_area * unit_rate),
                'warning': warning,
            })
        return vals_list

    def action_export(self):
        """Validate, then write the part IV import file into a Binary field."""
        for declaration in self:
            if not (declaration.part3_line_ids or declaration.part4_line_ids):
                raise UserError(self.env._("There is nothing to export."))
            values = dict(declaration._empty_export_files(), state='exported')
            if declaration.part3_line_ids:
                declaration.part3_line_ids._check_lines()
                values['export_file_3'] = BinaryBytes(declaration._build_xml(declaration.part3_line_ids))
                values['export_filename_3'] = declaration._export_filename(3, declaration.tax_year)
            if declaration.part4_line_ids:
                declaration.part4_line_ids._check_lines()
                values['export_file_4'] = BinaryBytes(declaration._build_xml(declaration.part4_line_ids))
                values['export_filename_4'] = declaration._export_filename(4, declaration.land_year)
            declaration.write(values)
        return True

    def _build_xml(self, lines):
        """Excel 2003 SpreadsheetML, as the rs.ge template of temp_15_2.xml spells it."""
        self.ensure_one()
        root = etree.Element(SS + 'Workbook', nsmap=NSMAP)
        style_block = etree.SubElement(root, SS + 'Styles')
        for style_id, spec in sorted(lines._rs_form15_styles().items()):
            style = etree.SubElement(style_block, SS + 'Style', {SS + 'ID': style_id})
            if spec.get('border'):
                borders = etree.SubElement(style, SS + 'Borders')
                for position in ('Bottom', 'Left', 'Right', 'Top'):
                    etree.SubElement(borders, SS + 'Border', {
                        SS + 'Position': position,
                        SS + 'LineStyle': 'Continuous',
                        SS + 'Weight': '1',
                    })
            if spec.get('fill'):
                etree.SubElement(style, SS + 'Interior', {
                    SS + 'Color': spec['fill'], SS + 'Pattern': 'Solid'})
            etree.SubElement(style, SS + 'NumberFormat', {SS + 'Format': '@'})

        worksheet = etree.SubElement(root, SS + 'Worksheet', {SS + 'Name': 'data'})
        table = etree.SubElement(worksheet, SS + 'Table', {SS + 'StyleID': lines._rs_form15_table_style()})

        def add_row(values, style_id):
            row = etree.SubElement(table, SS + 'Row', {SS + 'AutoFitHeight': '0'})
            for value in values:
                cell = etree.SubElement(row, SS + 'Cell', {SS + 'StyleID': style_id})
                data = etree.SubElement(cell, SS + 'Data', {SS + 'Type': 'String'})
                # The portal's own export writes a space, never an empty <Data/>.
                data.text = value if value else ' '

        add_row(lines._rs_form15_headers(), lines._rs_form15_header_style())
        for line in lines:
            add_row(line._export_values(), lines._rs_form15_cell_style())

        document = etree.ElementTree(root)
        root.addprevious(etree.ProcessingInstruction('mso-application', 'progid="Excel.Sheet"'))
        return etree.tostring(document, xml_declaration=True, encoding='UTF-8', standalone=None)


class RsForm15Part4Line(models.Model):
    """One land row of part IV. Classifier links are snapshots, not related fields:
    a filed row must stay as filed when the plot register changes."""
    _name = 'rs.form15.part4.line'
    _description = 'rs.ge Form 15 Part IV Line (Land)'
    _order = 'land_territory_id, id'
    _check_company_auto = True

    declaration_id = fields.Many2one('rs.form15.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    # Part IV reports land at 1 April; rates, classifier validity and export follow that year.
    land_year = fields.Integer(related='declaration_id.land_year', store=True)
    source = fields.Selection([('plot', 'Plot Register'), ('manual', 'Manual')], required=True, default='manual')
    plot_id = fields.Many2one('rs.form15.land.plot', ondelete='set null', index=True)

    land_territory_id = fields.Many2one('rs.form15.land.territory', string='Territorial Unit (2)',
                                        required=True, ondelete='restrict')

    land_type_id = fields.Many2one('rs.form15.land.type', string='Type (3)', required=True, ondelete='restrict')
    area = fields.Float(string='Area (4)', digits=(12, 4))
    taxable_area = fields.Float(string='Taxable Area (5)', digits=(12, 4))
    exemption_basis_id = fields.Many2one('rs.form15.exemption.basis', string='Exemption Basis (6)', ondelete='restrict')

    rate = fields.Float(string='Rate (7)', digits=(8, 4),
                        help="The rs.ge table value. For non-agricultural land it is a municipal "
                             "coefficient on the statutory base rate, not an amount per square metre.")
    base_rate = fields.Float(compute='_compute_base_rate', digits=(6, 4))

    tax_amount = fields.Monetary(string='Tax (8)', currency_field='currency_id')
    warning = fields.Char(readonly=True)

    @api.depends('land_type_id.uses_base_rate', 'land_type_id.base_rate')
    def _compute_base_rate(self):
        """The statutory base the rate multiplies (0.24 GEL/m² for non-agricultural land); 0 otherwise."""
        for line in self:
            line.base_rate = line.land_type_id.base_rate if line.land_type_id.uses_base_rate else 0.0

    @api.onchange('land_territory_id', 'land_type_id', 'area', 'taxable_area', 'exemption_basis_id')
    def _onchange_rate(self):
        """Fill the rate from the rs.ge table and the tax from the area, as the portal does."""
        if not (self.land_territory_id and self.land_type_id):
            return
        rate = self.env['rs.form15.land.rate']._rates_for(self.land_year).get(
            (self.land_territory_id.id, self.land_type_id.id))
        self.rate = rate or 0.0
        declared = self.taxable_area if (self.exemption_basis_id and self.taxable_area) else self.area
        self.tax_amount = self.currency_id.round(declared * self.land_type_id._unit_rate(self.rate))

    @api.model
    def _rs_form15_headers(self):
        return PART4_HEADERS

    @api.model
    def _rs_form15_styles(self):
        return PART4_STYLES

    @api.model
    def _rs_form15_table_style(self):
        return 's65'

    @api.model
    def _rs_form15_header_style(self):
        return 's64'

    @api.model
    def _rs_form15_cell_style(self):
        return 's63'

    def _export_values(self):
        self.ensure_one()
        return [
            self.land_territory_id.code or '',
            self.land_territory_id.name or '',
            self.land_type_id.code or '',
            self.land_type_id.name or '',
            _number(self.area, 4),
            _number(self.taxable_area, 4) if self.taxable_area else '',
            self.exemption_basis_id.code or '',
            _number(self.rate, 4),
            _number(self.tax_amount),
        ]

    @api.constrains('land_territory_id', 'land_type_id', 'rate', 'land_year')
    def _check_matrix(self):
        problems = self._matrix_problems()
        if problems:
            raise ValidationError(self.env._("These land rows do not match the rs.ge rate table:\n%s", '\n'.join(problems)))

    @api.constrains('area', 'taxable_area')
    def _check_taxable_area(self):
        """The portal refuses a taxable area larger than the area as soon as it is typed."""
        for line in self:
            if line.taxable_area < 0 or line.taxable_area > line.area:
                raise ValidationError(self.env._(
                    "%s: the taxable area after exemption cannot be negative or more than the area.",
                    line._label()))

    def _label(self):
        """Row label for messages and the explanation."""
        self.ensure_one()
        return ' / '.join(filter(None, [self.land_territory_id.name or '?', self.land_type_id.name or '?',
                                        self.plot_id.name]))

    def _matrix_problems(self):
        """Rows the rs.ge classifiers and rate table do not allow, as printable labels."""
        problems = []
        by_year = {}
        for line in self:
            year = line.land_year
            if year not in by_year:
                by_year[year] = self.env['rs.form15.land.rate']._rates_for(year)
            rates = by_year[year]
            label = line._label()
            for classifier in (line.land_territory_id, line.land_type_id,
                               line.exemption_basis_id):
                if classifier and not classifier._is_valid(year):
                    problems.append(self.env._("%(label)s: %(name)s is not valid in %(year)s",
                                               label=label, name=classifier.name, year=year))
            expected = rates.get((line.land_territory_id.id, line.land_type_id.id))
            if expected is None:
                problems.append(self.env._("%s: no rs.ge rate for this territorial unit and land type", label))
            elif float_compare(line.rate, expected, precision_digits=4) != 0:
                problems.append(self.env._("%(label)s: rate %(got)s does not match the rs.ge table value %(want)s",
                                           label=label, got=line.rate, want=expected))
        return problems

    def _explain(self):
        """How this row was built, as ordered steps; the wizard and the workbook render this."""
        self.ensure_one()
        currency = self.currency_id
        land_type = self.land_type_id
        declared = self.taxable_area if (self.exemption_basis_id and self.taxable_area) \
            else self.area
        expected = self.env['rs.form15.land.rate']._rates_for(self.land_year).get((self.land_territory_id.id, self.land_type_id.id))
        unit_rate = land_type._unit_rate(self.rate)

        steps = [{
            'code': '2',
            'label': self.env._("Territorial unit"),
            'value': self.land_territory_id.name or '',
            'detail': self.env._("rs.ge ID %s", self.land_territory_id.code or '?'),
        }, {
            'code': '3',
            'label': self.env._("Kind and description"),
            'value': land_type.name or '',
            'detail': self.env._("rs.ge ID %(code)s, declared in %(unit)s", code=land_type.code or '?',
                                 unit=dict(land_type._fields['unit'].selection).get(land_type.unit, '')),
        }, {
            'code': '4',
            'label': self.env._("Area"),
            'value': _number(self.area, 4),
            'detail': self.plot_id.display_name or self.env._("typed by hand"),
        }, {
            'code': '5',
            'label': self.env._("Taxable area"),
            'value': _number(self.taxable_area, 4) if self.taxable_area else '',
            'detail': self.env._("An exemption applies, so column 5 carries the reduced area.")
            if self.exemption_basis_id
            else self.env._("No exemption, so the portal leaves column 5 empty and taxes the whole area."),
        }]
        if self.exemption_basis_id:
            steps.append({
                'code': '6',
                'label': self.env._("Exemption basis"),
                'value': self.exemption_basis_id.code or '',
                'detail': self.exemption_basis_id.name or '',
            })
        steps.append({
            'code': '7',
            'label': self.env._("Rate"),
            'value': _number(self.rate, 4),
            'detail': (
                self.env._("rs.ge table value for this territorial unit and land type (%s).", _number(expected, 4))
                if expected is not None
                else self.env._("No rs.ge rate covers this pair.")),
        })
        if land_type.uses_base_rate:
            steps.append({
                'code': '',
                'label': self.env._("Amount per square metre"),
                'value': _number(unit_rate, 4),
                'detail': self.env._("Column 7 is a municipal coefficient, not an amount: "
                                     "%(base)s GEL/m² x %(coefficient)s = %(unit)s GEL/m².",
                                     base=_number(land_type.base_rate, 4),
                                     coefficient=_number(self.rate, 4), unit=_number(unit_rate, 4)),
            })
        steps.append({
            'code': '8',
            'label': self.env._("Property tax"),
            'value': _number(self.tax_amount),
            'detail': self.env._("%(area)s x %(unit)s = %(tax)s",
                                 area=_number(declared, 4), unit=_number(unit_rate, 4),
                                 tax=_number(currency.round(declared * unit_rate))), 'total': True,
        })
        return {
            'title': self._label(),
            'formula': self.env._("column 8 = (column 5, or column 4 when there is no "
                                  "exemption) x column 7, and for non-agricultural land "
                                  "column 7 is multiplied by the statutory 0.24 GEL/m²"),
            'steps': steps,
            'sources': [{
                'name': self.plot_id.display_name,
                'model': 'rs.form15.land.plot',
                'res_id': self.plot_id.id,
            }] if self.plot_id else [],
            'warning': self.warning or '',
        }

    def _check_lines(self):
        """Completeness, run at export only: an unfinished manual row must stay saveable."""
        errors = []
        for line in self:
            label = line._label()
            if not line.land_territory_id:
                errors.append(self.env._("%s: missing territorial unit", label))
            if not line.land_type_id:
                errors.append(self.env._("%s: missing land type", label))
            if line.area <= 0:
                errors.append(self.env._("%s: the area must be positive", label))
            if line.taxable_area and not line.exemption_basis_id:
                errors.append(self.env._("%s: column 5 is filled but no exemption basis is set", label))
        errors += self._matrix_problems()
        if errors:
            raise UserError(self.env._("The part IV rows are not ready to export:\n%s", '\n'.join(errors[:40])))


class RsForm15Part3Line(models.Model):
    """Part III property row: aggregates a type per territorial unit; named types (1.13, 2, 3, 4, 5.1, 5.2) get
    one row per asset. Classifier links are snapshots, so filed rows stay as filed."""
    _name = 'rs.form15.part3.line'
    _description = 'rs.ge Form 15 Part III Line (Property other than Land)'
    _order = 'territory_id, property_type_id, id'
    _check_company_auto = True

    declaration_id = fields.Many2one('rs.form15.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    tax_year = fields.Integer(related='declaration_id.tax_year', store=True)
    months_of_existence = fields.Integer(related='declaration_id.months_of_existence')
    source = fields.Selection([('asset', 'Fixed Assets'), ('manual', 'Manual')], required=True, default='manual')

    asset_ids = fields.Many2many('account.asset', string='Assets',
                                 help="The assets summed into this row, for tracing column 6 back to the ledger.")

    property_type_id = fields.Many2one('rs.form15.property.type', string='Property (3)', required=True,
                                       ondelete='restrict')
    is_immovable = fields.Boolean(related='property_type_id.is_immovable')
    has_name = fields.Boolean(related='property_type_id.has_name')

    # A named row declares one object: an asset, or an asset group when it was booked as several assets.
    asset_id = fields.Many2one('account.asset', string='Asset', ondelete='restrict', index='btree_not_null',
                               check_company=True,
                               help="Named types only: the asset this row declares.")
    asset_group_id = fields.Many2one('account.asset.group', string='Asset Group', ondelete='restrict',
                                     index='btree_not_null',
                                     help="Named types only: the asset group this row declares, when the object "
                                          "was booked as several assets.")
    name = fields.Char(string='Name', compute='_compute_name', store=True, readonly=True,
                       help="Column 2: the object's own name, asked by the portal for named types only. "
                            "Copied from the asset or asset group when the row is built and kept as filed, "
                            "so renaming the asset later does not change a submitted declaration.")

    territory_id = fields.Many2one('rs.form15.territory', string='Territorial Unit (4)', required=True,
                                   ondelete='restrict')

    acquisition_year_id = fields.Many2one('rs.form15.year', string='Acquisition Year (5)', ondelete='restrict',
                                          help="Filled for immovable property only; the portal hides the column otherwise.")

    average_value = fields.Monetary(string='Average Annual NBV (6)', currency_field='currency_id',
                                    help="(value at 1 January + value at 31 December) / 2, from the posted depreciation entries.")

    revaluation_coefficient_id = fields.Many2one('rs.form15.revaluation.coefficient', string='Coefficient (7)',
                                                 ondelete='restrict')

    exemption_amount = fields.Monetary(string='Exemption (8)', currency_field='currency_id')
    exemption_basis_id = fields.Many2one('rs.form15.exemption.basis', string='Exemption Basis (9)', ondelete='restrict')

    tax_rate = fields.Float(string='Rate (10)', digits=(5, 3),
                            help="Percent. Capped at 1% by Tax Code art. 202(1), or 0.6% for a leasing "
                                 "company's leased-out property.")

    tax_amount = fields.Monetary(string='Tax (11)', currency_field='currency_id', compute='_compute_amounts',
                                 store=True, readonly=True)

    advance_amount = fields.Monetary(string='Current Payment (12)', currency_field='currency_id',
                                     help="Last year's column 11. Order 996 art. 88: the next year's current payment "
                                          "is always the full-year figure, never column 15.")

    prorated_amount = fields.Monetary(string='Tax for the Period (15)', currency_field='currency_id',
                                      compute='_compute_amounts', store=True, readonly=True)

    difference = fields.Monetary(string='Difference (13)', currency_field='currency_id', compute='_compute_amounts',
                                 store=True, readonly=True)
    warning = fields.Char(readonly=True)

    @api.depends('asset_id', 'asset_group_id')
    def _compute_name(self):
        """A snapshot: re-picking the object changes it, a later rename does not."""
        for line in self:
            asset = line.asset_id.with_context(lang=line.declaration_id._rs_form15_lang())
            line.name = line.asset_group_id.name or asset.name or line.name

    def _object_key(self):
        """What a named row declares, stable across years and across renames."""
        self.ensure_one()
        if self.asset_group_id:
            return ('group', self.asset_group_id.id)
        if self.asset_id:
            return ('asset', self.asset_id.id)
        return ('name', self.name or '')

    @api.onchange('property_type_id')
    def _onchange_property_type_id(self):
        """The object belongs to the type: a new type needs a new pick."""
        for line in self:
            if not line.has_name or (line.asset_id and line.asset_id.rs_form15_property_type_id
                                     != line.property_type_id):
                line.asset_id = False
            if not line.has_name:
                line.asset_group_id = False

    @api.constrains('property_type_id', 'territory_id', 'asset_id', 'asset_group_id')
    def _check_declared_object(self):
        """A named type needs exactly one object on the row; any other type none."""
        for line in self:
            if line.has_name and bool(line.asset_id) == bool(line.asset_group_id):
                raise ValidationError(self.env._(
                    "%s: pick either the asset or the asset group this row declares (column 2).",
                    line._label()))
            if not line.has_name and (line.asset_id or line.asset_group_id):
                raise ValidationError(self.env._(
                    "%s is not a named type: it is declared per territorial unit, without an asset.",
                    line.property_type_id.name))
            if line.has_name:
                duplicates = line.declaration_id.part3_line_ids.filtered(
                    lambda other: other != line
                    and other.property_type_id == line.property_type_id
                    and other.territory_id == line.territory_id
                    and other._object_key() == line._object_key())
                if duplicates:
                    raise ValidationError(self.env._(
                        "%s is declared twice in this declaration.", line._label()))

    @api.onchange('exemption_basis_id')
    def _onchange_exemption_basis_id(self):
        """No basis means no exemption: the portal locks column 8 and keeps it at zero."""
        for line in self:
            if not line.exemption_basis_id:
                line.exemption_amount = 0.0

    @api.depends('average_value', 'revaluation_coefficient_id.coefficient',
                 'exemption_amount', 'tax_rate', 'advance_amount',
                 'declaration_id.months_of_existence')
    def _compute_amounts(self):
        for line in self:
            currency = line.currency_id or line.company_id.currency_id
            coefficient = line.revaluation_coefficient_id.coefficient or 1.0
            base = line.average_value * coefficient - line.exemption_amount
            line.tax_amount = currency.round(max(base, 0.0) * line.tax_rate / 100.0)
            months = line.months_of_existence
            line.prorated_amount = (currency.round(line.tax_amount / 12.0 * months) if months else 0.0)
            chargeable = (line.prorated_amount if (DIFFERENCE_USES_PRORATED and months) else line.tax_amount)
            line.difference = currency.round(chargeable - line.advance_amount)

    @api.model
    def _rs_form15_headers(self):
        return PART3_HEADERS

    @api.model
    def _rs_form15_styles(self):
        return PART3_STYLES

    @api.model
    def _rs_form15_table_style(self):
        return 's62'

    @api.model
    def _rs_form15_header_style(self):
        return 's63'

    @api.model
    def _rs_form15_cell_style(self):
        return 's64'

    def _export_values(self):
        self.ensure_one()
        return [
            self.property_type_id.code or '',
            (self.name or '') if self.has_name else (self.property_type_id.name or ''),
            self.territory_id.code or '',
            self.territory_id.name or '',
            self.acquisition_year_id.code or '',
            _number(self.average_value),
            self.revaluation_coefficient_id.code or '',
            _number(self.exemption_amount),
            self.exemption_basis_id.code or '',
            _number(self.tax_rate, 3),
            _number(self.tax_amount),
            _number(self.advance_amount),
            _number(self.difference),
            str(self.months_of_existence) if self.months_of_existence else '',
            _number(self.prorated_amount),
        ]

    @api.constrains('tax_rate', 'property_type_id')
    def _check_rate(self):
        for line in self:
            cap = (LEASING_RATE_CAP
                   if line.property_type_id.is_leasing
                   and line.company_id.rs_form15_is_leasing_company else 1.0)
            if not 0 <= line.tax_rate <= cap:
                raise ValidationError(self.env._("%(name)s: the rate must be between 0 and %(cap)s percent.",
                                                 name=line.property_type_id.name or '?', cap=cap))

    def _label(self):
        """Row label for messages and the explanation: type, the object's name, territory."""
        self.ensure_one()
        return ' / '.join(filter(None, [self.property_type_id.name or '?', self.name,
                                        self.territory_id.name or '?']))

    @api.constrains('property_type_id', 'average_value', 'acquisition_year_id', 'revaluation_coefficient_id')
    def _check_required_columns(self):
        """Columns the portal requires: the value, plus year and coefficient for immovable property."""
        for line in self:
            label = line._label()
            if float_is_zero(line.average_value, precision_digits=2):
                raise ValidationError(self.env._("%s: the average annual value (column 6) is required.", label))
            if line.property_type_id.is_immovable and not line.acquisition_year_id:
                raise ValidationError(self.env._("%s: immovable property needs an acquisition year (column 5).",
                                                 label))
            if line.property_type_id.is_immovable and not line.revaluation_coefficient_id:
                raise ValidationError(self.env._("%s: immovable property needs a revaluation coefficient "
                                                 "(column 7).", label))

    @api.constrains('property_type_id', 'acquisition_year_id', 'revaluation_coefficient_id')
    def _check_immovable_columns(self):
        """The portal hides columns 5 and 7 for movable property, so they must stay empty."""
        for line in self:
            if line.property_type_id and not line.property_type_id.is_immovable \
                    and (line.acquisition_year_id or line.revaluation_coefficient_id):
                raise ValidationError(self.env._("%s is movable property: the acquisition year and the revaluation "
                                                 "coefficient must stay empty (columns 5 and 7).",
                                                 line.property_type_id.name))

    def _explain(self):
        """How this row was built, as ordered steps, plus the assets behind column 6."""
        self.ensure_one()
        currency = self.currency_id
        opening = date(self.tax_year, 1, 1)
        closing = date(self.tax_year, 12, 31)
        coefficient = self.revaluation_coefficient_id.coefficient or 1.0

        sources = []
        assets = self.with_context(active_test=False).asset_ids
        frozen = assets.filtered(lambda asset: asset._rs_form15_lease_frozen())
        for asset in assets:
            start = asset._rs_form15_book_value(opening)
            end = asset._rs_form15_book_value(closing)
            average = asset._rs_form15_average(self.tax_year) if asset in frozen else (start + end) / 2.0
            sources.append({
                'name': asset.display_name,
                'model': 'account.asset',
                'res_id': asset.id,
                'opening': currency.round(start),
                'closing': currency.round(end),
                'average': currency.round(average),
                'exemption': currency.round(asset._rs_form15_exemption(average)),
            })

        steps = [{
            'code': '3',
            'label': self.env._("Property"),
            'value': self.property_type_id.name or '',
            'detail': self.env._("rs.ge ID %s", self.property_type_id.code or '?'),
        }, {
            'code': '4',
            'label': self.env._("Territorial unit"),
            'value': self.territory_id.name or '',
            'detail': self.env._("rs.ge ID %s", self.territory_id.code or '?'),
        }]
        if self.property_type_id.is_immovable:
            steps.append({
                'code': '5',
                'label': self.env._("Year acquired"),
                'value': self.acquisition_year_id.code or '',
                'detail': self.env._("Immovable property only; it selects column 7."),
            })
        steps.append({
            'code': '6',
            'label': self.env._("Average annual net book value"),
            'value': _number(self.average_value),
            'detail': (self.env._("Value at lease-out for %(frozen)s of %(count)s asset(s), for the part of the "
                                  "year each existed (leasing company, Order 996 art. 88); any other asset at "
                                  "(value at 1 January + value at 31 December) / 2.",
                                  frozen=len(frozen), count=len(assets))
                       if frozen else
                       self.env._("(value at 1 January + value at 31 December) / 2, summed over %s asset(s) "
                                  "from the posted depreciation entries.", len(assets))),
        })
        if self.property_type_id.is_immovable:
            steps.append({
                'code': '7',
                'label': self.env._("Revaluation coefficient"),
                'value': self.revaluation_coefficient_id.code or '',
                'detail': self.revaluation_coefficient_id.name
                or self.env._("No coefficient: art. 202(2) audited revaluation model."),
            })
        if self.exemption_amount or self.exemption_basis_id:
            steps.append({
                'code': '8',
                'label': self.env._("Exemption"),
                'value': _number(self.exemption_amount),
                'detail': self.exemption_basis_id.name or '',
            })
        steps.append({
            'code': '10',
            'label': self.env._("Rate"),
            'value': _number(self.tax_rate, 3),
            'detail': self.warning or self.env._("From the building tax rate table for %(unit)s in %(year)s.",
                                                 unit=self.territory_id.name or '?', year=self.tax_year),
        })
        steps.append({
            'code': '11',
            'label': self.env._("Tax"),
            'value': _number(self.tax_amount),
            'detail': self.env._("(%(average)s x %(coefficient)s - %(exemption)s) x %(rate)s%% = %(tax)s",
                                 average=_number(self.average_value), coefficient=_number(coefficient, 2),
                                 exemption=_number(self.exemption_amount), rate=_number(self.tax_rate, 3),
                                 tax=_number(self.tax_amount)),
        })
        steps.append({
            'code': '12',
            'label': self.env._("Current payment"),
            'value': _number(self.advance_amount),
            'detail': self.env._("Last year's column 11 for the same property type and territorial unit. "
                                 "Order 996 art. 88: the advance is always the full-year figure."),
        })
        if self.months_of_existence:
            steps.append({
                'code': '14',
                'label': self.env._("Months the company existed"),
                'value': str(self.months_of_existence),
                'detail': self.env._("Filled only for an incomplete calendar year. A month counts in full "
                                     "when registration falls on or before the 15th."),})
            steps.append({
                'code': '15',
                'label': self.env._("Tax for the period"),
                'value': _number(self.prorated_amount),
                'detail': self.env._("%(tax)s / 12 x %(months)s = %(prorated)s", tax=_number(self.tax_amount),
                                     months=self.months_of_existence, prorated=_number(self.prorated_amount)),
            })
        chargeable = (self.prorated_amount if (DIFFERENCE_USES_PRORATED and self.months_of_existence)
                      else self.tax_amount)
        steps.append({
            'code': '13',
            'label': self.env._("To add (+) / reduce (-)"),
            'value': _number(self.difference),
            'detail': self.env._("%(chargeable)s - %(advance)s = %(difference)s", chargeable=_number(chargeable),
                                 advance=_number(self.advance_amount), difference=_number(self.difference)),
            'total': True,
        })
        return {
            'title': self._label(),
            'formula': self.env._("column 11 = (column 6 x column 7 - column 8) x column 10, and "
                                  "column 13 = %s - column 12",
                                  self.env._("column 15 when the year is incomplete, otherwise column 11")
                                  if DIFFERENCE_USES_PRORATED else self.env._("column 11")),
            'steps': steps,
            'sources': sources,
            'warning': self.warning or '',
        }

    def _check_lines(self):
        """Completeness, run at export only."""
        errors = []
        for line in self:
            label = line._label()
            if not line.property_type_id:
                errors.append(self.env._("%s: missing property type", label))
            if not line.territory_id:
                errors.append(self.env._("%s: missing territorial unit", label))
            for classifier in (line.property_type_id, line.territory_id,
                               line.exemption_basis_id):
                if classifier and not classifier._is_valid(line.tax_year):
                    errors.append(self.env._("%(label)s: %(name)s is not valid in %(year)s",
                                             label=label, name=classifier.name, year=line.tax_year))
            if line.exemption_amount and not line.exemption_basis_id:
                errors.append(self.env._("%s: an exemption amount needs an exemption basis (column 9)", label))
            if line.has_name and not (line.name or '').strip():
                errors.append(self.env._("%s: a named type needs the object's name (column 2)", label))
        if errors:
            raise UserError(self.env._("The part III rows are not ready to export:\n%s", '\n'.join(errors[:40])))
