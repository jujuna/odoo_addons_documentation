from odoo import _, fields, models


class AccountReport(models.Model):
    _inherit = 'account.report'

    filter_multi_currency_dps = fields.Boolean(
        string="Multi-Currency Presentation",
        compute=lambda self: self._compute_report_option_filter('filter_multi_currency_dps', False),
        precompute=True,
        readonly=False,
        store=True,
        depends=['root_report_id', 'section_main_report_ids'],
        help="Show a currency dropdown that re-expresses the report's amounts "
             "in the selected presentation currency at each column's period-end rate.",
    )

    def _dps_browse_currency_option(self, currency_id=None, currency_name=None):
        """Resolve a currency from report options; stale or malformed session data gives an empty recordset."""
        Currency = self.env['res.currency']
        company_currency = self.env.company.currency_id

        if currency_id not in (None, False, ''):
            try:
                currency = Currency.browse(int(currency_id)).exists()
            except (TypeError, ValueError):
                currency = Currency
            if currency:
                return currency

        if currency_name and currency_name != company_currency.name:
            return Currency.search(
                [('name', '=', currency_name), ('active', '=', True)], limit=1,
            )

        return Currency

    def _dps_resolve_selected_currency(self, options, previous_options=None):
        """Return the currency picked in the filter; empty if the company currency or nothing is selected."""
        company_currency = self.env.company.currency_id
        empty = self.env['res.currency']

        data = previous_options if previous_options is not None else options or {}
        currency = self._dps_browse_currency_option(
            currency_id=data.get('selected_currencies_id'),
            currency_name=data.get('selected_currencies'),
        )
        return currency if currency and currency != company_currency else empty

    def _dps_get_conversion_date(self, options, col_data=None):
        """Return the FX date: the column group's own period end, else the report's date_to."""
        date_to = None
        if col_data:
            col_group_key = col_data.get('column_group_key')
            column_groups = (options or {}).get('column_groups') or {}
            forced = column_groups.get(col_group_key, {}).get('forced_options') or {}
            date_to = (forced.get('date') or {}).get('date_to')
        if not date_to:
            date_to = (options or {}).get('date', {}).get('date_to')
        if not date_to:
            return fields.Date.context_today(self)
        if isinstance(date_to, str):
            return fields.Date.from_string(date_to)
        return date_to

    def _get_options_initializers_forced_sequence_map(self):
        sequence_map = super()._get_options_initializers_forced_sequence_map()
        default_sequence = sequence_map.get('default', 200)
        sequence_map[self._init_options_currencies] = default_sequence
        sequence_map[self._init_options_rounding_unit] = default_sequence + 1
        return sequence_map

    def _init_options_currencies(self, options, previous_options):
        """Add the currency dropdown data only on reports with ``filter_multi_currency_dps`` set."""
        if not self.filter_multi_currency_dps:
            return

        company_currency = self.env.company.currency_id
        previous_options = previous_options or {}
        selected_currency = self._dps_browse_currency_option(
            currency_id=previous_options.get('selected_currencies_id'),
            currency_name=previous_options.get('selected_currencies'),
        ) or company_currency

        currencies = self.env['res.currency'].search(
            [('active', '=', True)], order='name',
        )
        options['currencies'] = [
            {'id': c.id, 'name': c.name, 'selected': c.id == selected_currency.id}
            for c in currencies
        ]
        options['selected_currencies'] = selected_currency.name
        options['selected_currencies_id'] = selected_currency.id

    def _init_options_rounding_unit(self, options, previous_options):
        """Swap the company currency symbol in ``rounding_unit_names`` for the selected one."""
        super()._init_options_rounding_unit(options, previous_options)

        to_currency = self._dps_resolve_selected_currency(options)
        if not to_currency:
            return

        company_symbol = self.env.company.currency_id.symbol or ''
        selected_symbol = to_currency.symbol or company_symbol
        if not company_symbol or selected_symbol == company_symbol:
            return

        rewritten = {}
        for key, value in options.get('rounding_unit_names', {}).items():
            if isinstance(value, (tuple, list)) and len(value) == 2:
                label, description = value
                if isinstance(label, str) and company_symbol in label:
                    label = label.replace(company_symbol, selected_symbol)
                rewritten[key] = (label, description)
            else:
                rewritten[key] = value
        options['rounding_unit_names'] = rewritten

    def _build_column_dict(self, col_value, col_data,
                           options=None, currency=False, digits=1,
                           column_expression=None, has_sublines=False,
                           report_line_id=None):
        """Convert monetary company-currency values to the selected currency at the column's period date."""
        if col_value is None and col_data is None:
            return super()._build_column_dict(
                col_value, col_data, options=options, currency=currency, digits=digits,
                column_expression=column_expression, has_sublines=has_sublines,
                report_line_id=report_line_id,
            )

        options = options or {}
        col_data = col_data or {}
        expression = column_expression or self.env['account.report.expression']
        figure_type = expression.figure_type or col_data.get('figure_type', 'string')

        to_currency = self._dps_resolve_selected_currency(options)
        company_currency = self.env.company.currency_id
        caller_currency = currency or self.env['res.currency']

        converted_value = col_value
        effective_currency = currency

        should_convert = (
            to_currency
            and figure_type == 'monetary'
            and isinstance(col_value, (int, float))
            and not isinstance(col_value, bool)
        )
        if should_convert:
            source_currency = caller_currency or company_currency
            # Cells already in a non-company currency (e.g. 'amount_currency') stay as they are.
            if source_currency == company_currency and source_currency != to_currency:
                convert_date = self._dps_get_conversion_date(options, col_data)
                converted_value = source_currency._convert(
                    col_value, to_currency, self.env.company, convert_date, round=False,
                )
                effective_currency = to_currency

        return super()._build_column_dict(
            converted_value, col_data, options=options, currency=effective_currency, digits=digits,
            column_expression=column_expression, has_sublines=has_sublines,
            report_line_id=report_line_id,
        )

    # Value formatting: covers callers that bypass _build_column_dict (journal-audit tax summary, journal exports)
    def _format_value(self, options, value, figure_type, format_params=None):
        converted_params = format_params
        if (
            options
            and figure_type == 'monetary'
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            to_currency = self._dps_resolve_selected_currency(options)
            if to_currency:
                company_currency = self.env.company.currency_id
                # Skip values already converted by _build_column_dict or given in a non-company currency.
                source_currency_id = (format_params or {}).get('currency_id', company_currency.id)
                if source_currency_id == company_currency.id and company_currency != to_currency:
                    convert_date = self._dps_get_conversion_date(options)
                    value = company_currency._convert(
                        value, to_currency, self.env.company, convert_date, round=False,
                    )
                    converted_params = {**(format_params or {}), 'currency_id': to_currency.id}
        return super()._format_value(
            options=options, value=value, figure_type=figure_type, format_params=converted_params,
        )

    def _inject_report_options_into_xlsx_sheet(self, options, sheet, y_offset, options_to_print=None):
        y_offset = super()._inject_report_options_into_xlsx_sheet(
            options, sheet, y_offset, options_to_print=options_to_print,
        )
        if not options_to_print or 'selected_currencies' in options_to_print:
            to_currency = self._dps_resolve_selected_currency(options)
            if to_currency:
                sheet.write(y_offset, 0, _("Reporting Currency"))
                sheet.write(y_offset, 1, to_currency.name)
                y_offset += 1
        return y_offset
