import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RS_CUSTOMS_DECLARATIONS_PATH = "/CustomsDeclarations/GetAsycudaDeclarations"


def _parse_rs_date(value):
    """RS returns dates as 'DD.MM.YYYY'. Be lenient about missing/empty values."""
    if not value:
        return False
    if isinstance(value, (datetime,)):
        return value.date()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except (TypeError, ValueError):
            continue
    _logger.warning("Customs declarations: could not parse date %r", value)
    return False


class GecCustomsDeclarationLine(models.Model):
    _name = 'gec.customs.declaration.line'
    _description = 'RS Customs Declaration Line (Asycuda)'
    _order = 'assessment_date desc, assessment_number desc, item_number'
    _rec_name = 'display_name'

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_currency_id', store=True,
    )

    # ---- Customs office ----
    customs_code = fields.Char(string='Customs Code', index=True)
    customs_name = fields.Char(string='Customs Office')

    # ---- Declaration header (repeated on every line of the same declaration) ----
    regime = fields.Char(string='Regime', index=True)
    registration_number = fields.Char(string='Registration Number', index=True)
    registration_date = fields.Date(string='Registration Date')
    assessment_number = fields.Char(string='Assessment Number', required=True, index=True)
    assessment_date = fields.Date(string='Assessment Date', required=True, index=True)

    # ---- Parties (raw tax IDs + resolved partner links) ----
    exporter_code = fields.Char(string='Exporter Tax ID', index=True)
    exporter_id = fields.Many2one(
        'res.partner', string='Exporter',
        compute='_compute_partner_links', store=True,
    )
    importer_code = fields.Char(string='Importer Tax ID', index=True)
    importer_id = fields.Many2one(
        'res.partner', string='Importer',
        compute='_compute_partner_links', store=True,
    )

    # ---- Geography (raw country codes + resolved res.country links) ----
    sender_country_code = fields.Char(string='Sender Country Code')
    sender_country_id = fields.Many2one(
        'res.country', string='Sender Country',
        compute='_compute_country_links', store=True,
    )
    destination_country_code = fields.Char(string='Destination Country Code')
    destination_country_id = fields.Many2one(
        'res.country', string='Destination Country',
        compute='_compute_country_links', store=True,
    )
    origin_country_code = fields.Char(string='Origin Country Code')
    origin_country_id = fields.Many2one(
        'res.country', string='Country of Origin',
        compute='_compute_country_links', store=True,
    )

    # ---- Goods line ----
    item_number = fields.Integer(string='Item #', required=True)
    hs_code = fields.Char(string='HS Code', index=True)
    customs_procedure = fields.Char(string='Customs Procedure')
    goods_description = fields.Text(string='Goods Description')

    # ---- Quantities & value ----
    brutto_weight = fields.Float(string='Brutto Weight (kg)', digits=(16, 3))
    netto_weight = fields.Float(string='Netto Weight (kg)', digits=(16, 3))
    supplementary_quantity = fields.Float(string='Supplementary Qty', digits=(16, 3))
    supplementary_unit = fields.Char(string='Supplementary Unit')
    value_gel = fields.Monetary(string='Value (GEL)', currency_field='currency_id')

    # ---- Computed direction / display ----
    direction = fields.Selection(
        [('import', 'Import'), ('export', 'Export'), ('unknown', 'Unknown')],
        compute='_compute_direction', store=True, index=True,
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)

    # ---- Audit ----
    fetched_by_user_id = fields.Many2one('res.users', string='Fetched By', readonly=True)
    fetched_on = fields.Datetime(string='Fetched On', readonly=True)

    _uniq_assessment_item_company = models.Constraint(
        'UNIQUE(assessment_number, item_number, company_id)',
        'A customs declaration line with the same assessment number and item number '
        'already exists for this company.',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('company_id')
    def _compute_currency_id(self):
        gel = self.env['res.currency'].search([('name', '=', 'GEL')], limit=1)
        for rec in self:
            rec.currency_id = gel or rec.company_id.currency_id

    @api.depends('exporter_code', 'importer_code')
    def _compute_partner_links(self):
        Partner = self.env['res.partner']
        for rec in self:
            rec.exporter_id = self._match_partner_by_vat(Partner, rec.exporter_code)
            rec.importer_id = self._match_partner_by_vat(Partner, rec.importer_code)

    @staticmethod
    def _match_partner_by_vat(Partner, tax_id):
        if not tax_id:
            return False
        # rs.ge stores plain tax IDs; many Odoo partners prefix the VAT with the
        # country code (e.g. "GE211336240"). Try both shapes.
        candidates = [tax_id]
        if not tax_id.upper().startswith('GE'):
            candidates.append('GE' + tax_id)
        for value in candidates:
            partner = Partner.search([('vat', '=', value)], limit=1)
            if partner:
                return partner.id
        return False

    @api.depends('sender_country_code', 'destination_country_code', 'origin_country_code')
    def _compute_country_links(self):
        Country = self.env['res.country']
        for rec in self:
            rec.sender_country_id = self._match_country(Country, rec.sender_country_code)
            rec.destination_country_id = self._match_country(Country, rec.destination_country_code)
            rec.origin_country_id = self._match_country(Country, rec.origin_country_code)

    @staticmethod
    def _match_country(Country, code):
        if not code:
            return False
        c = Country.search([('code', '=', code.upper())], limit=1)
        return c.id if c else False

    @api.depends('importer_code', 'exporter_code', 'company_id.vat')
    def _compute_direction(self):
        for rec in self:
            company_vat = (rec.company_id.vat or '').lstrip('Gg').lstrip('Ee')
            imp = (rec.importer_code or '').strip()
            exp = (rec.exporter_code or '').strip()
            if company_vat and imp and imp.endswith(company_vat):
                rec.direction = 'import'
            elif company_vat and exp and exp.endswith(company_vat):
                rec.direction = 'export'
            else:
                rec.direction = 'unknown'

    @api.depends('assessment_number', 'item_number', 'hs_code')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.assessment_number or _('(no assessment #)')]
            if rec.item_number:
                parts.append('#%s' % rec.item_number)
            if rec.hs_code:
                parts.append(rec.hs_code)
            rec.display_name = ' / '.join(parts)

    # ------------------------------------------------------------------
    # REST fetch
    # ------------------------------------------------------------------

    @api.model
    def _rs_row_to_vals(self, row):
        """Convert one API row (dict) into create vals."""
        return {
            'customs_code': row.get('CustomsCode'),
            'customs_name': row.get('CustomsName'),
            'regime': row.get('Regime'),
            'registration_number': row.get('RegistrationNumber'),
            'registration_date': _parse_rs_date(row.get('RegistrationDate')),
            'assessment_number': row.get('AssessmentNumber'),
            'assessment_date': _parse_rs_date(row.get('AssessmentDate')),
            'exporter_code': row.get('ExporterCode'),
            'importer_code': row.get('ImporterCode'),
            'sender_country_code': row.get('SenderCountryCode'),
            'destination_country_code': row.get('DestinationCountryCode'),
            'origin_country_code': row.get('OriginCountryCode'),
            'item_number': int(row.get('ItemNumber') or 0),
            'hs_code': row.get('HSCode'),
            'customs_procedure': row.get('CustomsProcedure'),
            'goods_description': row.get('GoodsDescription'),
            'brutto_weight': float(row.get('BruttoWeight') or 0.0),
            'netto_weight': float(row.get('NettoWeight') or 0.0),
            'value_gel': float(row.get('ValueInGEL') or 0.0),
            'supplementary_quantity': float(row.get('SupplementaryQuantity') or 0.0),
            'supplementary_unit': row.get('SupplementaryUnit'),
        }

    @api.model
    def fetch_from_rs(self, start_date, end_date, user=None):
        """Call RS, upsert lines, return (created, skipped) counts.

        `start_date` / `end_date` are date or datetime; `user` is a res.users
        record (defaults to self.env.user). RS accepts max 20 days per call.
        """
        user = user or self.env.user
        if not start_date or not end_date:
            raise UserError(_("Provide both a start and an end date."))
        if end_date < start_date:
            raise UserError(_("End date must be on or after the start date."))
        if (end_date - start_date).days > 20:
            raise UserError(_(
                "RS allows at most 20 days per call. You requested %s days.",
                (end_date - start_date).days,
            ))

        def _to_rs_dt(d):
            if isinstance(d, datetime):
                return d.replace(microsecond=0).isoformat()
            return datetime(d.year, d.month, d.day).isoformat()

        payload = {
            'START_DATE': _to_rs_dt(start_date),
            'END_DATE': _to_rs_dt(end_date),
        }
        _logger.info(
            "Customs declarations: fetching %s..%s as user %s",
            payload['START_DATE'], payload['END_DATE'], user.login,
        )
        data = user._rs_rest_authenticated_call(
            RS_CUSTOMS_DECLARATIONS_PATH, payload, method='GET',
        )
        rows = data if isinstance(data, list) else (data.get('DATA') if isinstance(data, dict) else None) or []
        if not isinstance(rows, list):
            raise UserError(_("Unexpected response shape from RS: DATA is not a list."))

        company = self.env.company
        now = fields.Datetime.now()
        created, skipped = 0, 0
        for row in rows:
            vals = self._rs_row_to_vals(row)
            if not vals.get('assessment_number') or not vals.get('assessment_date'):
                _logger.warning("Customs declarations: skipping row with no assessment: %s", row)
                skipped += 1
                continue
            existing = self.search([
                ('assessment_number', '=', vals['assessment_number']),
                ('item_number', '=', vals['item_number']),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing:
                # Refresh values (RS may correct a declaration before the line stays final).
                existing.write({**vals, 'fetched_by_user_id': user.id, 'fetched_on': now})
                skipped += 1
            else:
                self.create({
                    **vals,
                    'company_id': company.id,
                    'fetched_by_user_id': user.id,
                    'fetched_on': now,
                })
                created += 1
        _logger.info(
            "Customs declarations: imported %s new, refreshed %s existing.",
            created, skipped,
        )
        return created, skipped
