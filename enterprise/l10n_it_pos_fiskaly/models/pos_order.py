import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_repr, float_round

from odoo.addons.l10n_it_pos_fiskaly.models.fiskaly_client import fiskaly_client
from odoo.addons.l10n_it_pos_fiskaly.models.pos_config import VAT_RATES

_logger = logging.getLogger(__name__)

EXEMPTION_NOT_SUBJECT = 'NOT_SUBJECT'

PAYMENT_TYPES = {
    'cash': {'type': 'CASH'},
    'bank': {'type': 'CARD', 'kind': 'DEBIT', 'number': '****'},
    'online': {'type': 'ONLINE'},
    'pay_later': {'type': 'OUTSTANDING'},
    'meal_voucher': {'type': 'CARD', 'kind': 'TICKET', 'number': '****'},
}


class PosOrder(models.Model):
    _inherit = 'pos.order'

    l10n_it_fiskaly_intention_id = fields.Char(string="Fiskaly Intention")
    l10n_it_fiskaly_record_id = fields.Char(string="Fiskaly Record")
    l10n_it_fiskaly_compliance_number = fields.Char(string="Fiskaly compliance number")

    def _l10n_it_fiskaly_requires_manual_document(self):
        self.ensure_one()
        original = self.lines.refunded_orderline_id.order_id
        return bool(original) and not original.l10n_it_fiskaly_record_id

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('paid', 'done'):
            for order in self.filtered(lambda order: order.config_id._l10n_it_fiskaly_is_active()
                    and not order.l10n_it_fiskaly_record_id
                    and order._l10n_it_fiskaly_lines().filtered(lambda line: line._l10n_it_fiskaly_is_declared())):
                if order._l10n_it_fiskaly_requires_manual_document():
                    continue
                try:
                    order._l10n_it_fiskaly_create_transaction()
                except Exception:
                    _logger.exception("fiskaly could not record %s", order.display_name)
        return res

    def order_receipt_generate_data(self, basic_receipt=False):
        data = super().order_receipt_generate_data(basic_receipt)
        data['extra_data']['l10n_it_fiskaly_refunded_compliance_number'] = (
            self.refunded_order_id.l10n_it_fiskaly_compliance_number
        )
        return data

    def _l10n_it_fiskaly_ensure_intention(self, client):
        self.ensure_one()
        if not self.l10n_it_fiskaly_intention_id:
            self.l10n_it_fiskaly_intention_id = self._l10n_it_fiskaly_create_intention(client)
        return self.l10n_it_fiskaly_intention_id

    def _l10n_it_fiskaly_create_intention(self, client):
        self.ensure_one()
        config = self.config_id
        if not config.l10n_it_fiskaly_system_id:
            raise UserError(_("Please register %s with fiskaly first.", config.display_name))
        if config.l10n_it_fiskaly_system_state != 'COMMISSIONED':
            raise UserError(_(
                "The fiskaly system of %(register)s is %(state)s: it must be commissioned before "
                "it can record transactions.",
                register=config.display_name,
                state=config.l10n_it_fiskaly_system_state or _("not registered"),
            ))
        response = client.create_record({
            'type': 'INTENTION',
            'system': {
                'id': config.l10n_it_fiskaly_system_id,
            },
            'operation': {
                'type': 'TRANSACTION',
            },
        })
        record_id = response.get('id')
        if not record_id:
            raise UserError(_("Fiskaly did not return a record identifier."))
        return record_id

    def l10n_it_fiskaly_get_record(self):
        self.ensure_one()
        if not self.l10n_it_fiskaly_record_id:
            raise UserError(_("%s has no fiskaly record.", self.display_name))
        with fiskaly_client(self.company_id, subject=True) as client:
            return client.get_record(self.l10n_it_fiskaly_record_id)

    def _l10n_it_fiskaly_amount(self, amount):
        return float_repr(self.currency_id.round(amount), self.currency_id.decimal_places)

    def _l10n_it_fiskaly_precise_amount(self, amount):
        return float_repr(float_round(amount, precision_digits=8), 8)

    def _l10n_it_fiskaly_vat_rate(self, tax):
        self.ensure_one()
        rate = next((
            rate for rate in VAT_RATES
            if float_compare(float(rate['percentage']), tax.amount, 2) == 0
        ), None) if tax else None
        if not rate:
            raise UserError(_(
                "%(tax)s is not mapped to a fiskaly VAT rate, %(order)s cannot be fiscalized.",
                tax=tax.display_name if tax else _("No tax"),
                order=self.display_name,
            ))
        return rate

    def _l10n_it_fiskaly_vat_exemption(self, code):
        exemptions = self.env['pos.order.line']._fields['l10n_it_fiskaly_vat_exemption'].get_values(self.env)
        if code not in exemptions:
            raise UserError(_(
                "%(code)s is not a fiskaly VAT exemption of %(register)s.",
                code=code,
                register=self.config_id.display_name,
            ))
        return {
            'type': 'VAT_EXEMPTION',
            'code': code,
        }

    def _l10n_it_fiskaly_vat(self, code, exclusive, amount):
        rate = next((rate for rate in VAT_RATES if rate['code'] == code), None)
        if not rate:
            return self._l10n_it_fiskaly_vat_exemption(code)
        percentage = rate['percentage']
        return {
            'type': 'VAT_RATE',
            'code': code,
            'percentage': percentage,
            'exclusive': self._l10n_it_fiskaly_precise_amount(exclusive),
            'inclusive': self._l10n_it_fiskaly_amount(exclusive + amount),
            'amount': self._l10n_it_fiskaly_precise_amount(amount),
        }

    def _l10n_it_fiskaly_returned_order(self):
        self.ensure_one()
        if not self.is_refund:
            return self.env['pos.order']
        original = self.lines.refunded_orderline_id.order_id
        if not original.l10n_it_fiskaly_record_id:
            raise UserError(_(
                "%(original)s has no fiskaly record: the return %(order)s cannot be recorded.",
                original=original.display_name,
                order=self.display_name,
            ))
        return original

    def _l10n_it_fiskaly_sign(self):
        self.ensure_one()
        return -1 if self._l10n_it_fiskaly_returned_order() else 1

    def _l10n_it_fiskaly_tax_details(self, base_lines):
        self.ensure_one()
        AccountTax = self.env['account.tax']
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return base_lines

    def _l10n_it_fiskaly_total(self):
        self.ensure_one()
        return self._l10n_it_fiskaly_sign() * self.amount_total

    def _l10n_it_fiskaly_lines(self):
        self.ensure_one()
        return self.lines.filtered(lambda line: not line.combo_line_ids)

    def _l10n_it_fiskaly_base_lines(self):
        self.ensure_one()
        sign = self._l10n_it_fiskaly_sign()
        return self._l10n_it_fiskaly_tax_details([
            line._l10n_it_fiskaly_base_line(sign * line.qty)
            for line in self._l10n_it_fiskaly_lines()
        ])

    def _l10n_it_fiskaly_sold_lines(self, lines):
        self.ensure_one()
        sign = self._l10n_it_fiskaly_sign()
        AccountTax = self.env['account.tax']
        base_lines = self._l10n_it_fiskaly_tax_details([
            line._l10n_it_fiskaly_base_line(sign * line.qty)
            for line in lines
        ])
        return AccountTax._dispatch_global_discount_lines(base_lines, self.company_id)

    def _l10n_it_fiskaly_entry_base_lines(self):
        self.ensure_one()
        sign = self._l10n_it_fiskaly_sign()
        lines = self._l10n_it_fiskaly_lines().filtered(lambda line: line._l10n_it_fiskaly_is_declared())
        free = lines.filtered(lambda line: line._l10n_it_fiskaly_is_free())
        gifts = self._l10n_it_fiskaly_tax_details([
            line._l10n_it_fiskaly_base_line(sign * line.qty, price_unit=line._l10n_it_fiskaly_list_price_unit())
            for line in free
        ])
        return [(base_line, False) for base_line in self._l10n_it_fiskaly_sold_lines(lines - free)] + [
            (base_line, True) for base_line in gifts
        ]

    def _l10n_it_fiskaly_vat_amounts(self, base_lines):
        self.ensure_one()
        AccountTax = self.env['account.tax']

        def grouping_function(base_line, tax_data):
            return base_line['record']._l10n_it_fiskaly_vat_code(
                tax_data['tax'] if tax_data else None)

        aggregated_values = AccountTax._aggregate_base_lines_tax_details(base_lines, grouping_function)
        return {
            code: {
                'exclusive': values['raw_base_amount_currency'],
                'amount': values['raw_tax_amount_currency'],
            }
            for code, values in AccountTax._aggregate_base_lines_aggregated_values(aggregated_values).items()
        }

    def _l10n_it_fiskaly_breakdown(self, vat_amounts):
        breakdown = []
        for code, amounts in vat_amounts.items():
            vat = self._l10n_it_fiskaly_vat(code, amounts['exclusive'], amounts['amount'])
            if vat['type'] == 'VAT_EXEMPTION':
                vat['exclusive'] = self._l10n_it_fiskaly_precise_amount(amounts['exclusive'])
            breakdown.append(vat)
        return breakdown

    def _l10n_it_fiskaly_outstanding_concept(self):
        self.ensure_one()
        if all(line.product_id.type == 'service' for line in self.lines):
            return 'SERVICE'
        return 'GOOD'

    def _l10n_it_fiskaly_payment(self, payment, sign):
        self.ensure_one()
        method = payment.payment_method_id
        content = {
            **PAYMENT_TYPES.get(method.type, {'type': 'OTHER'}),
            'details': {
                'amount': self._l10n_it_fiskaly_amount(sign * payment.amount),
            },
        }
        if content['type'] == 'OUTSTANDING':
            content['concept'] = self._l10n_it_fiskaly_outstanding_concept()
        if content['type'] in ('ONLINE', 'OTHER'):
            content['name'] = method.name
        return content

    def _l10n_it_fiskaly_payments(self, inclusive):
        self.ensure_one()
        sign = self._l10n_it_fiskaly_sign()
        payments = [
            self._l10n_it_fiskaly_payment(payment, sign)
            for payment in self.payment_ids
        ]
        collected = sum(float(payment['details']['amount']) for payment in payments)
        rounding = self.currency_id.round(inclusive - collected)
        if not payments:
            payments.append({
                'type': 'CASH',
                'details': {'amount': self._l10n_it_fiskaly_amount(0)},
            })
        discounted = next(
            (payment for payment in payments if payment['type'] == 'CASH'), None)
        if not discounted and payments:
            discounted = payments[0]
        if discounted and rounding > 0:
            discounted['details']['discount'] = self._l10n_it_fiskaly_amount(rounding)
        return payments

    def _l10n_it_fiskaly_entries(self, vat_amounts=None):
        self.ensure_one()
        entries = []
        shortfall = 0.0
        gifted = 0.0
        for base_line, gift in self._l10n_it_fiskaly_entry_base_lines():
            line = base_line['record']
            gift = gift or line._l10n_it_fiskaly_is_gift()
            entries.append(line._l10n_it_fiskaly_entry(base_line, gift=gift))
            if vat_amounts is None:
                continue
            amounts = line._l10n_it_fiskaly_amounts(base_line)
            code = line._l10n_it_fiskaly_vat_code(line.tax_ids_after_fiscal_position[:1])
            if gift:
                # fiskaly declares gifts at their full price in the breakdown and totals
                values = vat_amounts.setdefault(code, {'exclusive': 0.0, 'amount': 0.0})
                values['exclusive'] += amounts['base']
                values['amount'] += amounts['base_inclusive'] - amounts['base']
                gifted += amounts['base_inclusive']
                continue
            if not amounts['shortfall']:
                continue
            exclusive = amounts['shortfall'] / (1 + amounts['percentage'] / 100)
            values = vat_amounts.setdefault(code, {'exclusive': 0.0, 'amount': 0.0})
            values['exclusive'] += exclusive
            values['amount'] += amounts['shortfall'] - exclusive
            shortfall += amounts['shortfall']
        return entries, shortfall, gifted

    def _l10n_it_fiskaly_document(self):
        self.ensure_one()
        base_lines = self._l10n_it_fiskaly_base_lines()
        vat_amounts = self._l10n_it_fiskaly_vat_amounts(base_lines)
        entries, shortfall, gifted = self._l10n_it_fiskaly_entries(vat_amounts)
        exclusive = sum(amounts['exclusive'] for amounts in vat_amounts.values())
        amount = sum(amounts['amount'] for amounts in vat_amounts.values())
        collectable = self.currency_id.round(self._l10n_it_fiskaly_total() + shortfall)
        inclusive = self.currency_id.round(collectable + gifted)
        return {
            'document': {
                'number': str(self.sequence_number),
            },
            'breakdown': self._l10n_it_fiskaly_breakdown(vat_amounts),
            'totals': {
                'vat': {
                    'amount': self._l10n_it_fiskaly_precise_amount(amount),
                    'exclusive': self._l10n_it_fiskaly_precise_amount(exclusive),
                    'inclusive': self._l10n_it_fiskaly_amount(inclusive),
                },
            },
            'entries': entries,
            'payments': self._l10n_it_fiskaly_payments(collectable),
        }

    def _l10n_it_fiskaly_operation(self):
        self.ensure_one()
        original = self._l10n_it_fiskaly_returned_order()
        if not original:
            return {
                'type': 'RECEIPT',
                **self._l10n_it_fiskaly_document(),
            }
        return {
            'type': 'CORRECTION',
            'record': {
                'id': original.l10n_it_fiskaly_record_id,
            },
            'data': {
                'type': 'RECEIPT',
                **self._l10n_it_fiskaly_document(),
            },
        }

    def _l10n_it_fiskaly_log_failure(self, error, idempotency_key, attempts):
        self.ensure_one()
        try:
            breakdown = self._l10n_it_fiskaly_breakdown(
                self._l10n_it_fiskaly_vat_amounts(self._l10n_it_fiskaly_base_lines()))
        except UserError:
            breakdown = _("not available")
        _logger.error(
            "fiskaly SIGN IT could not record %(order)s\n"
            "  date: %(date)s\n"
            "  total: %(total)s\n"
            "  breakdown: %(breakdown)s\n"
            "  idempotency key: %(key)s\n"
            "  attempts: %(attempts)s (%(retried)s)\n"
            "  error: %(error)r",
            {
                'order': self.display_name,
                'date': self.date_order,
                'total': self.amount_total,
                'breakdown': breakdown,
                'key': idempotency_key,
                'attempts': attempts,
                'retried': _("retried, still failing") if attempts > 1 else _("no retry"),
                'error': error,
            },
        )

    def _l10n_it_fiskaly_check_response(self, response):
        self.ensure_one()
        record_id = response.get('id')
        if not record_id:
            raise UserError(_("Fiskaly did not return a record identifier."))
        state = response.get('state')
        if state != "COMPLETED":
            raise UserError(_(
                "Fiskaly returned the state %(state)s: %(logs)s",
                state=state,
                logs=response.get('logs'),
            ))
        if not response.get('compliance', {}).get('data'):
            raise UserError(_("Fiskaly did not return a record compliance number"))
        return record_id

    def _l10n_it_fiskaly_create_transaction(self):
        self.ensure_one()
        with fiskaly_client(self.company_id, subject=True) as client:
            self._l10n_it_fiskaly_ensure_intention(client)
            idempotency_key = self.uuid
            try:
                response = client.create_record(
                    {
                        'type': 'TRANSACTION',
                        'record': {
                            'id': self.l10n_it_fiskaly_intention_id,
                        },
                        'operation': self._l10n_it_fiskaly_operation(),
                    },
                    idempotency_key=idempotency_key,
                )
                record_id = self._l10n_it_fiskaly_check_response(response)
                self.l10n_it_fiskaly_record_id = record_id
                compliance_number = response.get('compliance', {}).get('data')
            except Exception as error:
                self._l10n_it_fiskaly_log_failure(error, idempotency_key, client.attempts)
                raise
        self.l10n_it_fiskaly_compliance_number = compliance_number
        return record_id
