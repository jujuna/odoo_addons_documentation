from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_repr

from .account_tax import VAT_EXEMPTIONS


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    l10n_it_fiskaly_vat_exemption = fields.Selection(
        selection=VAT_EXEMPTIONS,
        string="Fiskaly VAT Exemption",
        copy=False,
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'l10n_it_fiskaly_vat_exemption']

    def _l10n_it_fiskaly_vat_code(self, tax):
        self.ensure_one()
        if tax and tax.amount:
            return self.order_id._l10n_it_fiskaly_vat_rate(tax)['code']
        return self.l10n_it_fiskaly_vat_exemption or tax and tax.l10n_it_fiskaly_vat_exemption or 'NOT_SUBJECT'

    def _l10n_it_fiskaly_entry_number(self):
        self.ensure_one()
        original = self.refunded_orderline_id
        entry_lines = [base_line['record'] for base_line, _gift in original.order_id._l10n_it_fiskaly_entry_base_lines()]
        return str(entry_lines.index(original) + 1)

    def _l10n_it_fiskaly_entry_text(self):
        self.ensure_one()
        line = self.refunded_orderline_id or self
        return (line.full_product_name or line.product_id.display_name)[:256]

    def _l10n_it_fiskaly_is_gift(self):
        self.ensure_one()
        return float_compare(self.discount, 100, 2) == 0

    def _l10n_it_fiskaly_is_free(self):
        self.ensure_one()
        return self.order_id.currency_id.is_zero(self.price_unit) and not self._l10n_it_fiskaly_is_global_discount()

    def _l10n_it_fiskaly_list_price_unit(self):
        self.ensure_one()
        order = self.order_id
        if order.pricelist_id:
            return order.pricelist_id._get_product_price(
                self.product_id, abs(self.qty), currency=order.currency_id)
        return self.product_id.lst_price

    def _l10n_it_fiskaly_is_declared(self):
        self.ensure_one()
        if not self.qty:
            return False
        return not self._l10n_it_fiskaly_is_free() or not self.order_id.currency_id.is_zero(
            self._l10n_it_fiskaly_list_price_unit())

    def _l10n_it_fiskaly_is_global_discount(self):
        self.ensure_one()
        config = self.order_id.config_id
        return 'discount_product_id' in config._fields and config.discount_product_id == self.product_id

    def _l10n_it_fiskaly_base_line(self, quantity, price_unit=None):
        self.ensure_one()
        order = self.order_id
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            currency_id=order.currency_id,
            rate=order.currency_rate,
            tax_ids=self.tax_ids_after_fiscal_position,
            price_unit=self.price_unit if price_unit is None else price_unit,
            quantity=quantity,
            discount=self.discount,
            special_type='global_discount' if self._l10n_it_fiskaly_is_global_discount() else False,
        )

    def _l10n_it_fiskaly_gross(self, base_line):
        self.ensure_one()
        order = self.order_id
        AccountTax = self.env['account.tax']
        gross_line = AccountTax._prepare_base_line_for_taxes_computation(
            self,
            currency_id=order.currency_id,
            rate=order.currency_rate,
            tax_ids=self.tax_ids_after_fiscal_position,
            price_unit=base_line['price_unit'],
            quantity=base_line['quantity'],
            discount=0.0,
        )
        AccountTax._add_tax_details_in_base_lines([gross_line], order.company_id)
        details = gross_line['tax_details']
        return details['raw_total_excluded_currency'], details['raw_total_included_currency']

    def _l10n_it_fiskaly_amounts(self, base_line):
        self.ensure_one()
        details = base_line['tax_details']
        discounts = [line['tax_details'] for line in base_line.get('discount_base_lines', [])]
        exclusive = details['raw_total_excluded_currency'] + sum(
            discount['raw_total_excluded_currency'] for discount in discounts)
        inclusive = details['raw_total_included_currency'] + sum(
            discount['raw_total_included_currency'] for discount in discounts)
        tax = self.tax_ids_after_fiscal_position[:1]
        percentage = float(
            self.order_id._l10n_it_fiskaly_vat_rate(tax)['percentage']) if tax and tax.amount else 0.0
        base, base_inclusive = self._l10n_it_fiskaly_gross(base_line)
        if self._l10n_it_fiskaly_is_gift():
            exclusive = base
            inclusive = base_inclusive
        currency = self.order_id.currency_id
        minimum = currency.rounding
        shortfall = 0.0
        if (currency.compare_amounts(base_inclusive, minimum) > 0
                and currency.compare_amounts(inclusive, minimum) < 0):
            shortfall = minimum - inclusive
            inclusive = minimum
            exclusive = minimum / (1 + percentage / 100)
        return {
            'quantity': base_line['quantity'],
            'inclusive': inclusive,
            'exclusive': exclusive,
            'base': base,
            'base_inclusive': base_inclusive,
            'percentage': percentage,
            'shortfall': shortfall,
        }

    def _l10n_it_fiskaly_quantity(self, quantity):
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        return float_repr(quantity, digits)

    def _l10n_it_fiskaly_unit(self, quantity, inclusive, exclusive):
        order = self.order_id
        return {
            'quantity': self._l10n_it_fiskaly_quantity(quantity),
            'price': {
                'inclusive': order._l10n_it_fiskaly_precise_amount(inclusive / quantity if quantity else inclusive),
                'exclusive': order._l10n_it_fiskaly_precise_amount(exclusive / quantity if quantity else exclusive),
            },
        }

    def _l10n_it_fiskaly_item(self, base_line, gift=False):
        self.ensure_one()
        order = self.order_id
        amounts = self._l10n_it_fiskaly_amounts(base_line)
        base = amounts['base']
        base_inclusive = amounts['base_inclusive']
        exclusive = base if gift else amounts['exclusive']
        inclusive = base_inclusive if gift else amounts['inclusive']
        return {
            'text': self._l10n_it_fiskaly_entry_text(),
            'unit': self._l10n_it_fiskaly_unit(amounts['quantity'], base_inclusive, base),
            'value': {
                'base': order._l10n_it_fiskaly_precise_amount(base),
                'discount': order._l10n_it_fiskaly_precise_amount(base_inclusive - inclusive),
            },
            'vat': order._l10n_it_fiskaly_vat(
                self._l10n_it_fiskaly_vat_code(self.tax_ids_after_fiscal_position[:1]),
                exclusive,
                inclusive - exclusive,
            ),
        }

    def _l10n_it_fiskaly_item_data(self, base_line, gift=False):
        return {
            'type': 'ITEM',
            **self._l10n_it_fiskaly_item(base_line, gift=gift),
        }

    def _l10n_it_fiskaly_entry(self, base_line, gift=False):
        self.ensure_one()
        gift = gift or self._l10n_it_fiskaly_is_gift()
        return {
            'type': 'RETURN' if self.refunded_orderline_id else 'SALE',
            'details': {
                'concept': 'SERVICE' if self.product_id.type == 'service' else 'GOOD',
                **({'purpose': 'GIFT'} if gift else {}),
                **({'number': self._l10n_it_fiskaly_entry_number()} if self.refunded_orderline_id else {}),
            },
            'data': self._l10n_it_fiskaly_item_data(base_line, gift=gift),
        }
