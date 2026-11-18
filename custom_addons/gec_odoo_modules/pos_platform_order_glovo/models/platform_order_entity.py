import logging

from odoo import Command, _, api, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_repr

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE

_logger = logging.getLogger(__name__)


def _glovo_unit_price_cents(item):
    """Unit price in cents of a Glovo product or combo sub-product, attributes and sub-products included."""
    return (
        item['price']
        + sum(attribute['price'] * attribute['quantity'] for attribute in item.get('attributes') or [])
        + sum(
            sub['quantity'] * _glovo_unit_price_cents(sub) - sub.get('discount', 0)
            for sub in item.get('sub_products') or []
        )
    )


def _glovo_item_note(item):
    """Readable list of the attributes and sub-products of a Glovo product, for the order line note."""
    parts = [f"{attribute['quantity']} x {attribute['name']}" for attribute in item.get('attributes') or []]
    for sub in item.get('sub_products') or []:
        sub_note = _glovo_item_note(sub)
        parts.append(f"{sub['quantity']} x {sub['name']}" + (f" ({sub_note})" if sub_note else ""))
    return ", ".join(parts)


class PlatformOrderEntity(models.Model):
    _inherit = 'platform.order.entity'

    def _sync_menu(self):
        if self.filtered(lambda store: store.provider_code == PROVIDER_CODE):
            raise UserError(_("Glovo: menu synchronisation is not implemented yet."))
        return super()._sync_menu()

    def _update_platform_order_menu(self, products):
        self.ensure_one()
        if self.provider_code != PROVIDER_CODE:
            return super()._update_platform_order_menu(products)
        return None

    def _prepare_order_values_from_data(self, data):
        self.ensure_one()
        if self.provider_code != PROVIDER_CODE:
            return super()._prepare_order_values_from_data(data)

        notes = []
        if data.get('allergy_info'):
            notes.append(_("Allergies: %s", data['allergy_info']))
        if data.get('special_requirements'):
            notes.append(_("Special requirements: %s", data['special_requirements']))
        if data.get('cutlery_requested'):
            notes.append(_("Cutlery requested"))

        return {
            'name': data['order_code'],
            'floating_order_name': f"#{data['order_code']}",
            'platform_order_ref': str(data['order_id']),
            'platform_order_status': 'accepted',
            'platform_order_pin': data.get('pick_up_code'),
            'platform_order_rider_name': (data.get('courier') or {}).get('name'),
            'glovo_payment_method': data.get('payment_method'),
            'general_customer_note': "\n".join(notes),
            'order_type': 'pickup' if data.get('is_picked_up_by_customer') else 'delivery',
        }

    def _convert_to_order_values(self, **kwargs):
        values = super()._convert_to_order_values(**kwargs)
        if self.provider_code == PROVIDER_CODE:
            values['platform_order_rider_name'] = kwargs.get('platform_order_rider_name')
            values['glovo_payment_method'] = kwargs.get('glovo_payment_method')
        return values

    def _find_or_create_partners_from_data(self, order_data):
        """Glovo orders carry no customer: courier orders only send anonymised initials."""
        self.ensure_one()
        if self.provider_code != PROVIDER_CODE:
            return super()._find_or_create_partners_from_data(order_data)
        return self.env['res.partner']

    def _prepare_order_lines_values_from_data(self, order_data):
        """Map each Glovo product to the Odoo product whose Internal Reference is the Glovo product ID.

        Prices are tax-included cents; attributes and sub-products add to the line price, the discount is subtracted.
        """
        self.ensure_one()
        if self.provider_code != PROVIDER_CODE:
            return super()._prepare_order_lines_values_from_data(order_data)

        company = self.config_id.company_id
        Product = self.env['product.product']
        codes = [line_data['id'] for line_data in order_data['products']]
        products = Product.search(Domain('default_code', 'in', codes) & Domain(Product._check_company_domain(company)))
        by_code = {}
        for product in products:
            by_code.setdefault(product.default_code, product)
        order_lines_values = []
        for line_data in order_data['products']:
            product = by_code.get(line_data['id'])
            if not product:
                raise ValidationError(_("Glovo: no product with Internal Reference %s.", line_data['id']))

            qty = line_data['quantity']
            line_total_incl = (qty * _glovo_unit_price_cents(line_data) - line_data.get('discount', 0)) / 100
            taxes = product.taxes_id._filter_taxes_by_company(company)
            price_info = taxes.with_context(force_price_include=True, round_base=False).compute_all(line_total_incl / qty, self.currency_id, qty)
            # pos.order._compute_prices recomputes the order total from price_unit with the taxes' own include setting
            line_price = line_total_incl if all(taxes.mapped('price_include')) else price_info['total_excluded']

            order_lines_values.append({
                'customer_note': _glovo_item_note(line_data),
                'full_product_name': product.name,
                'product_id': product.id,
                'qty': qty,
                'price_unit': line_price / qty,
                'price_subtotal': self.currency_id.round(price_info['total_excluded']),
                'price_subtotal_incl': self.currency_id.round(price_info['total_included']),
                'tax_ids': [Command.set(taxes.ids)],
            })
        return order_lines_values

    def _create_order_from_data(self, order_data):
        order = super()._create_order_from_data(order_data)
        if self.provider_code != PROVIDER_CODE or not order:
            return order

        expected = order_data['partner_discounted_products_total'] / 100
        if order.currency_id.compare_amounts(order.amount_total, expected):
            digits = order.currency_id.decimal_places
            message = _("POS order total %(total)s differs from Glovo total after product discounts %(expected)s (difference %(difference)s "
                "%(currency)s).", total=float_repr(order.amount_total, digits), expected=float_repr(expected, digits),
                difference=float_repr(order.amount_total - expected, digits), currency=order.currency_id.name)
            _logger.warning("Glovo: order %s: %s", order_data['order_id'], message)
            self.env['glovo.event'].search([('glovo_order_id', '=', str(order_data['order_id'])), ('event_type', '=', 'dispatched')]).error = message
        return order

    @api.model
    def _find_store_from_data(self, provider_code, notification_data):
        if provider_code != PROVIDER_CODE:
            return super()._find_store_from_data(provider_code, notification_data)

        external_id = notification_data.get('store_id')
        if not external_id:
            raise ValidationError(_("Glovo: received data without a store ID."))

        stores = self.search([('provider_code', '=', PROVIDER_CODE), ('external_id', '=', external_id)])
        if not stores:
            raise ValidationError(_("Glovo: no store found matching ID %s.", external_id))
        return stores

    def _cancel_order_from_data(self, order_data, reason):
        """Glovo has no refuse API: record the dispatched event as failed so the store handles it in the Glovo Webapp."""
        self.ensure_one()
        if self.provider_code != PROVIDER_CODE:
            return super()._cancel_order_from_data(order_data, reason)

        glovo_order_id = str(order_data['order_id'])
        _logger.warning("Glovo: order %s not created for store %s: no open POS session.", glovo_order_id, self.name)
        self.env['glovo.event'].search([
            ('glovo_order_id', '=', glovo_order_id),
            ('event_type', '=', 'dispatched'),
        ]).write({'state': 'failed', 'error': _("No open POS session.")})
