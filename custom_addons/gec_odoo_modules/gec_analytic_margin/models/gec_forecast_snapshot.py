from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class GecForecastSnapshot(models.Model):
    """Expected revenue of a month, frozen on its first day (budget, else the prior three months' run rate).
    Past months are rebuilt from earlier data, possibly since corrected: marked reconstructed."""
    _name = 'gec.forecast.snapshot'
    _description = 'Monthly Revenue Forecast'
    _order = 'month desc, company_id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company,
                                 index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    month = fields.Date(required=True, help="First day of the month the forecast is for.")
    forecast_revenue = fields.Monetary(string='Forecast Revenue', required=True)
    basis = fields.Selection([
        ('budget', 'Budget'),
        ('run_rate', 'Run rate'),
    ], required=True,
        help="Budget: the month's revenue budget, prorated by day. "
             "Run rate: the average revenue of the three full months before.")
    recorded_on = fields.Date(string='Recorded On', required=True, default=fields.Date.context_today)
    reconstructed = fields.Boolean(
        help="Filled in after the fact for a month before forecasts were recorded. "
             "It uses only data dated before the month, but that data may have changed since.")
    actual_revenue = fields.Monetary(string='Actual Revenue', compute='_compute_actual')
    error_pct = fields.Float(
        string='Error', compute='_compute_actual',
        help="(Actual − forecast) ÷ actual. Empty until the month has closed.")

    _month_uniq = models.Constraint('unique (company_id, month)', 'A month has one forecast per company.')

    @api.model
    def _gec_revenue(self, company, date_from, date_to, line_type='actual'):
        domain = [('company_id', '=', company.id), ('is_primary_plan', '=', True)]
        if line_type == 'actual':
            domain += [('line_type', '=', 'actual'), ('date', '>=', date_from), ('date', '<=', date_to)]
            [(revenue,)] = self.env['gec.margin.report']._read_group(domain, [], ['revenue_amount:sum'])
            return revenue or 0.0
        total = 0.0
        for line, revenue in self.env['gec.margin.report']._read_group(
                domain + [('line_type', '=', 'budget'), ('budget_line_id.date_from', '<=', date_to),
                          ('budget_line_id.date_to', '>=', date_from)],
                ['budget_line_id'], ['revenue_amount:sum']):
            span = (line.date_to - line.date_from).days + 1
            shared = (min(line.date_to, date_to) - max(line.date_from, date_from)).days + 1
            if span > 0 and shared > 0:
                total += (revenue or 0.0) * shared / span
        return total

    @api.model
    def _gec_forecast_for(self, company, month):
        """(amount, basis) as it could have been known on the month's first day."""
        end = month + relativedelta(months=1) - timedelta(days=1)
        budget = self._gec_revenue(company, month, end, line_type='budget')
        if budget:
            return budget, 'budget'
        start = month - relativedelta(months=3)
        return self._gec_revenue(company, start, month - timedelta(days=1)) / 3, 'run_rate'

    @api.depends('month', 'company_id', 'forecast_revenue')
    def _compute_actual(self):
        today = fields.Date.context_today(self)
        for snapshot in self:
            end = snapshot.month + relativedelta(months=1) - timedelta(days=1) if snapshot.month else False
            if not end or end >= today:
                snapshot.actual_revenue = 0.0
                snapshot.error_pct = 0.0
                continue
            actual = self._gec_revenue(snapshot.company_id, snapshot.month, end)
            snapshot.actual_revenue = actual
            snapshot.error_pct = (actual - snapshot.forecast_revenue) / actual if actual else 0.0

    @api.model
    def _gec_record(self, companies, months, reconstructed=False):
        existing = {(s.company_id.id, s.month) for s in self.search(
            [('company_id', 'in', companies.ids), ('month', 'in', months)])}
        vals = []
        for company in companies:
            for month in months:
                if (company.id, month) in existing:
                    continue
                amount, basis = self.with_company(company)._gec_forecast_for(company, month)
                if amount:
                    vals.append({'company_id': company.id, 'month': month, 'forecast_revenue': amount,
                                 'basis': basis, 'reconstructed': reconstructed})
        return self.create(vals)

    @api.model
    def _cron_record_month(self):
        """On the first of the month: freeze this month's forecast."""
        month = fields.Date.context_today(self).replace(day=1)
        return self.sudo()._gec_record(self.env['res.company'].search([]), [month])

    @api.model
    def _gec_backfill(self, months=12):
        """Reconstruct the forecasts of past months that were never recorded."""
        this_month = fields.Date.context_today(self).replace(day=1)
        past = [this_month - relativedelta(months=i) for i in range(1, months + 1)]
        records = self.sudo()._gec_record(self.env['res.company'].search([]), past, reconstructed=True)
        return records | self._cron_record_month()
