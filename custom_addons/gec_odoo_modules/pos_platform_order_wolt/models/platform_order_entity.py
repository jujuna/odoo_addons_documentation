import base64
import datetime
import json
import logging
import secrets
from urllib.parse import urlencode

from requests.exceptions import HTTPError, RequestException

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools.misc import hmac as hmac_tool
from odoo.tools.urls import urljoin

from odoo.addons.pos_platform_order import utils
from odoo.addons.pos_platform_order_wolt.utils import const, preorder_status, wolt_option_lines
from odoo.addons.pos_platform_order_wolt.utils.wolt_request import WoltClient

_logger = logging.getLogger(__name__)

class PlatformOrderEntity(models.Model):
    _inherit = 'platform.order.entity'
    _check_company_auto = True

    wolt_oauth_state = fields.Char(copy=False, readonly=True, groups='base.group_system')
    wolt_connected = fields.Boolean(string="Connected to Wolt", compute='_compute_wolt_token_info')
    wolt_token_expiry = fields.Datetime(string="Access Token Valid Until", compute='_compute_wolt_token_info')
    wolt_fallback_product_id = fields.Many2one('product.product', string="Product for Unknown Wolt Items", check_company=True, ondelete='restrict',
        domain="[('available_in_pos', '=', True)]",
        help="Used for Wolt items that were not created by Odoo's menu sync, "
        "with Wolt's name and price. Without it such an order cannot be imported.")
    wolt_pending_order_refs = fields.Json(copy=False, readonly=True, help="Wolt orders received while the POS was closed or whose import failed.")
    wolt_pending_product_tmpl_ids = fields.Many2many('product.template', 'platform_order_entity_wolt_pending_product_rel',
        string="Wolt Items to Push", copy=False, readonly=True, help="Products whose price or availability changed since the last push to Wolt.")
    wolt_items_pushed_at = fields.Datetime(string="Wolt Items Pushed On", readonly=True, copy=False)
    wolt_venue_online = fields.Boolean(string="Online on Wolt", readonly=True, copy=False)
    wolt_venue_open = fields.Boolean(string="Open on Wolt", readonly=True, copy=False)
    wolt_venue_status_date = fields.Datetime(string="Wolt Status Checked On", readonly=True, copy=False)

    def _compute_wolt_token_info(self):
        # sudo: the connection state is shown to POS managers, the tokens stay admin-only
        tokens = self.env['platform.order.wolt.token'].sudo().search([('store_id', 'in', self.ids)])
        expiry_by_store = {token.store_id.id: token.expiry for token in tokens}
        for store in self:
            store.wolt_token_expiry = expiry_by_store.get(store.id)
            store.wolt_connected = store.id in expiry_by_store

    def action_wolt_connect(self):
        """Start Wolt self-service onboarding (SSIO) for this venue."""
        self.ensure_one()
        self.check_access('write')
        provider = self.provider_id
        if provider.state == 'disabled':
            raise UserError(self.env._("Enable the Wolt provider (test or production) first."))
        state = secrets.token_urlsafe(24)
        # sudo: the state field is admin-only; write access on the store was checked above
        self.sudo().wolt_oauth_state = state
        params = {'client_id': provider.wolt_client_id, 'redirect_url': provider.wolt_redirect_url, 'state': state, 'venue_name': self.name}
        return {'type': 'ir.actions.act_url', 'url': f"{const.INTEGRATE_URLS[provider.state]}?{urlencode(params)}", 'target': 'self'}

    def _wolt_handle_oauth_callback(self, code):
        """Exchange the one-time SSIO code and link the Wolt venue from the token claims."""
        self.ensure_one()
        provider = self.provider_id
        response = WoltClient.request_token(provider, {'grant_type': 'authorization_code', 'redirect_uri': provider.wolt_redirect_url, 'code': code})
        venue_id = self._wolt_decode_jwt(response['access_token']).get('integration', {}).get('venue_id')
        if not venue_id:
            raise UserError(self.env._("Wolt did not return a venue in the access token."))
        if venue_id != self.external_id:
            other = self.search([('id', '!=', self.id), ('provider_id', '=', self.provider_id.id), ('external_id', '=', venue_id)])
            if other:
                raise UserError(self.env._("Wolt venue %s is already linked to %s.", venue_id, other.display_name))
        Token = self.env['platform.order.wolt.token']
        token_values = Token._prepare_values(response)
        if token := Token.search([('store_id', '=', self.id)]):
            token.write(token_values)
        else:
            Token.create({**token_values, 'store_id': self.id})
        self.write({'external_id': venue_id, 'wolt_oauth_state': False})
        return venue_id

    @api.model
    def _wolt_decode_jwt(self, token):
        """Read the JWT payload. No signature check: the token comes straight from Wolt over TLS."""
        payload = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))

    def _wolt_get_access_token(self):
        self.ensure_one()
        # sudo: tokens are admin-only; the Wolt client and the cron read them, never the user
        token = self.env['platform.order.wolt.token'].sudo().search([('store_id', '=', self.id)])
        if not token:
            raise UserError(self.env._("Use 'Connect to Wolt' on store %s first.", self.display_name))
        return token._get_access_token()

    @api.model
    def _find_store_from_data(self, provider_code, order_data):
        if provider_code != const.PROVIDER_CODE:
            return super()._find_store_from_data(provider_code, order_data)
        venue_id = (order_data.get('order') or {}).get('venue_id') or order_data.get('venue_id')
        if not venue_id:
            raise ValidationError(self.env._("Wolt: notification without venue ID."))
        return self.search([('provider_code', '=', const.PROVIDER_CODE), ('provider_id.state', '!=', 'disabled'), ('external_id', '=', venue_id)])

    def _wolt_handle_notification(self, data):
        """Apply a verified Wolt notification; returns True when the order import failed and was queued."""
        self.ensure_one()
        order_ref = (data.get('order') or {}).get('id')
        if not order_ref:
            _logger.info("Wolt: venue event %s for store %s", data.get('event_type'), self.id)
            return
        order = self.env['pos.order']._find_order_from_data(const.PROVIDER_CODE, data, raise_if_not_found=False)
        if order and order.platform_order_store_id != self:
            _logger.warning("Wolt: order %s is not of store %s, notification ignored", order_ref, self.id)
            return
        if order:
            order._update_order_status_from_data(data)
        elif data.get('type') == 'order.notification' and data['order'].get('status') not in ('CANCELED', 'DELIVERED'):
            try:
                with self.env.cr.savepoint():
                    self._create_order_from_data(WoltClient(self).get_order(order_ref))
            except (RequestException, UserError) as error:
                _logger.warning("Wolt: import of order %s for store %s failed, queued: %s", order_ref, self.id, error)
                self._wolt_queue_order(order_ref)
                return True

    def _prepare_order_values_from_data(self, data):
        self.ensure_one()
        if self.provider_code != const.PROVIDER_CODE:
            return super()._prepare_order_values_from_data(data)

        delivery = data.get('delivery') or {}
        pre_order = data.get('pre_order') or {}
        preorder_state = preorder_status(data)
        acceptance = (data.get('order_handling') or {}).get('acceptance_status')
        accepted = preorder_state == 'confirmed' or (acceptance in const.ACCEPTED_ON_ARRIVAL_STATUSES and preorder_state != 'waiting')
        location = delivery.get('location') or {}
        notes = [data.get('consumer_comment')]
        if delivery.get('self_delivery'):
            notes.append(location.get('formatted_address'))
        values = {
            'name': data['id'],
            'floating_order_name': f"Wolt #{data['order_number']}",
            'platform_order_ref': data['id'],
            'platform_order_status': 'accepted' if accepted else 'new',
            'platform_order_pin': data['order_number'],
            'general_customer_note': '\n'.join(filter(None, notes)),
            'order_type': const.DELIVERY_TYPE_MAPPING.get(delivery.get('type'), 'delivery'),
            'wolt_order_type': 'preorder' if data.get('type') == 'preorder' else 'instant',
            'wolt_self_delivery': bool(delivery.get('self_delivery')),
            'wolt_food_ready': data.get('order_status') == 'ready',
            'wolt_customer': {'name': data.get('consumer_name'), 'phone': data.get('consumer_phone_number'), 'location': location},
        }
        if pre_order.get('preorder_time'):
            preorder_time = datetime.datetime.fromisoformat(pre_order['preorder_time'])
            values['preset_time'] = preorder_time.astimezone(datetime.UTC).replace(tzinfo=None)
        return values

    def _convert_to_order_values(self, **kwargs):
        values = super()._convert_to_order_values(**kwargs)
        if self.provider_code == const.PROVIDER_CODE:
            values.update({
                'wolt_order_type': kwargs['wolt_order_type'],
                'wolt_self_delivery': kwargs['wolt_self_delivery'],
                'platform_order_food_ready': kwargs['wolt_food_ready'],
            })
        return values

    def _find_or_create_partners_from_data(self, order_data):
        self.ensure_one()
        if self.provider_code != const.PROVIDER_CODE:
            return super()._find_or_create_partners_from_data(order_data)
        Partner = self.env['res.partner']
        company = self.config_id.company_id
        customer = order_data.get('wolt_customer') or {}
        # Wolt shares a phone number only when the venue delivers itself; without it a contact is just noise.
        if not order_data.get('wolt_self_delivery') or not customer.get('phone'):
            return Partner
        location = customer['location']
        address = {
            'street': location.get('street_address'),
            'street2': location.get('apartment'),
            'city': location.get('city'),
            'zip': location.get('zip_code'),
        }
        partner = Partner.search([('phone', '=', customer['phone']), *Partner._check_company_domain(company)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': customer.get('name') or customer['phone'],
                'phone': customer['phone'],
                'company_id': company.id,
                **address,
            })
        elif any(partner[field] != (value or False) for field, value in address.items()):
            partner.write(address)
        return partner

    def _prepare_order_lines_values_from_data(self, data):
        self.ensure_one()
        if self.provider_code != const.PROVIDER_CODE:
            return super()._prepare_order_lines_values_from_data(data)

        currency = self.config_id.currency_id
        minor_unit = 10 ** currency.decimal_places
        lines = []
        Value = self.env['product.template.attribute.value']
        for item in data.get('items') or []:
            options = item.get('options') or []
            template = self.env['product.template'].browse(self._wolt_parse_ids([item.get('pos_id')])).exists()
            if template:
                values = Value
                unmapped = []
                for option in options:
                    value_ids = self._wolt_parse_ids([option.get('value_pos_id')])
                    option_values = Value.browse(value_ids).exists().filtered(lambda v: v.product_tmpl_id == template)
                    values |= option_values
                    if not option_values:
                        unmapped.append(option)
                # the menu sends no option for a line with one value, so a Wolt order never carries it
                for line in template.attribute_line_ids - wolt_option_lines(template):
                    values |= line.product_template_value_ids._only_active()
                product = template._create_product_variant(values) or template.product_variant_id
                name = product.display_name
            elif self.wolt_fallback_product_id:
                values = Value
                unmapped = options
                product = self.wolt_fallback_product_id
                name = item.get('name') or product.display_name
            else:
                raise ValidationError(self.env._("Wolt item %(name)s (POS ID %(pos_id)s) has no product: sync the menu from Odoo or set a Product "
                    "for Unknown Wolt Items on the store.", name=item.get('name'), pos_id=item.get('pos_id')))
            taxes = product.taxes_id.filtered_domain(self.env['account.tax']._check_company_domain(self.config_id.company_id))

            # Wolt amounts are tax included, in minor units, after merchant discounts.
            count = item['count']
            item_price = item['item_price']
            total = item_price['total']['amount'] / minor_unit
            breakdown = item_price.get('price_breakdown') or {}
            before = (breakdown.get('total_before_discounts') or item_price['total'])['amount'] / minor_unit
            discount = (before - total) / before * 100 if before > total else 0.0
            price_unit = self._wolt_price_unit_from_included(before / count, taxes, product)
            computed = taxes.compute_all(price_unit * (1 - discount / 100), currency, count, product=product)
            line = {
                'product_id': product.id,
                'full_product_name': name,
                'attribute_value_ids': [Command.set(values.ids)],
                'qty': count,
                'price_unit': price_unit,
                'discount': discount,
                'price_subtotal': computed['total_excluded'],
                'price_subtotal_incl': computed['total_included'],
                'tax_ids': [Command.set(taxes.ids)],
            }
            if unmapped:
                notes = [(option.get('value') or option.get('name'), option.get('count') or 1) for option in unmapped]
                line['customer_note'] = ', '.join(f'{count} x {name}' if count > 1 else name for name, count in notes)
            lines.append(line)
        return lines

    @api.model
    def _wolt_parse_ids(self, external_ids):
        """IDs from our `external_data` strings; values Odoo did not send are ignored."""
        res_ids = []
        for external_id in filter(None, external_ids):
            try:
                res_ids += utils._parse_external_ids(self.env, external_id)
            except ValueError:
                _logger.info("Wolt: ignoring unknown POS ID %s", external_id)
        return res_ids

    @api.model
    def _wolt_price_unit_from_included(self, price_included, taxes, product):
        """Turn a tax-included unit price into the line price_unit expected by the taxes' setting."""
        if not taxes or all(taxes.flatten_taxes_hierarchy().mapped('price_include')):
            return price_included
        return taxes._get_tax_details(price_included, 1.0, rounding_method='round_globally', product=product,
            special_mode='total_included')['total_excluded']

    def _cancel_order_from_data(self, data, reason):
        self.ensure_one()
        if self.provider_code != const.PROVIDER_CODE:
            return super()._cancel_order_from_data(data, reason)
        acceptance = (data.get('order_handling') or {}).get('acceptance_status')
        # Wolt allows rejecting only before acceptance: accepted orders and preorders (a waiting one is confirmed now)
        # wait for the POS to open (see _wolt_import_pending_orders).
        if data.get('type') == 'preorder' or acceptance != 'to_be_accepted_by_venue':
            if preorder_status(data) == 'waiting':
                WoltClient(self).confirm_preorder(data['id'])
            _logger.warning("Wolt: order %s arrived while the POS of store %s is closed, queued.", data['id'], self.id)
            self._wolt_queue_order(data['id'])
            return None
        try:
            WoltClient(self).reject_order(data['id'], reason, 'GENERIC')
        except (RequestException, UserError) as error:
            _logger.error("Wolt: failed to reject order %s: %s", data['id'], error)
        return None

    def _wolt_queue_order(self, order_ref):
        self.wolt_pending_order_refs = list(dict.fromkeys([*(self.wolt_pending_order_refs or []), order_ref]))

    def _sync_menu(self):
        wolt_stores = self.filtered(lambda s: s.provider_code == const.PROVIDER_CODE)
        super(PlatformOrderEntity, self - wolt_stores)._sync_menu()
        wolt_stores.check_access('write')
        for store in wolt_stores:
            try:
                WoltClient(store).create_menu(store._wolt_prepare_menu())
                store._set_menu_sync_state_done()
                store.wolt_pending_product_tmpl_ids = [Command.clear()]
            except (RequestException, UserError) as error:
                _logger.warning("Wolt: menu sync failed for store %s: %s", store.id, error)
                if isinstance(error, HTTPError) and error.response.status_code == 429:
                    notification = {'type': 'warning', 'message': self.env._("Wolt accepts one menu sync every 15 minutes; try again later.")}
                else:
                    store.menu_sync_state = 'failed'
                    notification = {
                        'type': 'danger',
                        'message': self.env._("Wolt menu sync failed for %(store)s: %(error)s", store=store.display_name, error=error),
                    }
                self.env.user._bus_send('simple_notification', notification)

    def _wolt_prepare_menu(self):
        """Full Wolt menu; it replaces the venue's menu on Wolt. Wolt does not document whether POST menu prices
        are major or minor units (not verified): we send major units (EUR 10.00 -> 10), like Wolt's own example."""
        self.ensure_one()
        store = self.with_company(self.company_id)
        langs = store._wolt_languages()
        categories = {}
        products = store._get_menu_products()
        prices = store._wolt_pricelist()._get_products_price(products, 1.0)
        for template in products:
            template_categories = template.pos_categ_ids
            if store.available_categ_ids:
                template_categories = template_categories.filtered_domain([('id', 'child_of', store.available_categ_ids.ids)])
            if template_categories:
                categories.setdefault(template_categories.sorted()[:1], []).append(template)
        return {
            'currency': store.currency_id.name,
            'primary_language': langs[0][0],
            'categories': [{
                'name': store._wolt_text(category, 'name', langs),
                'items': [store._wolt_prepare_menu_item(template, langs, prices) for template in templates],
            } for category, templates in sorted(categories.items(), key=lambda c: (c[0].sequence, c[0].id))],
        }

    def _wolt_prepare_menu_item(self, template, langs, prices):
        taxes = self._wolt_product_taxes(template)
        item = {
            'name': self._wolt_text(template, 'name', langs),
            'price': self._wolt_price_included(prices[template.id], taxes, template),
            'enabled': template.platform_order_available,
            'delivery_methods': ['homedelivery', 'takeaway'],
            'external_data': utils._get_external_id(template),
            'options': [self._wolt_prepare_option(line, taxes, template, langs) for line in wolt_option_lines(template)],
        }
        description = self._wolt_text(template, 'description_sale', langs)
        if description:
            item['description'] = description
        vat = self._wolt_vat_percentage(taxes)
        if vat is not None:
            item['sales_tax_percentage'] = vat
        if template.image_128:
            item['image_url'] = self._wolt_image_url(template)
        return item

    def _wolt_prepare_option(self, line, taxes, template, langs):
        multi = line.attribute_id.display_type == 'multi'
        values = line.product_template_value_ids._only_active()
        option = {
            'name': self._wolt_text(line.attribute_id, 'name', langs),
            'type': 'MultiChoice' if multi else 'SingleChoice',
            'external_data': utils._get_external_id(line),
            'values': [],
        }
        for index, value in enumerate(values):
            option_value = {
                'name': self._wolt_text(value.product_attribute_value_id, 'name', langs),
                'price': self._wolt_price_included(value.price_extra, taxes, template),
                'enabled': True,
                'default': not multi and index == 0,
                'external_data': utils._get_external_id(value),
            }
            if multi:
                option_value['selection_range'] = {'min': 0, 'max': 1}
            option['values'].append(option_value)
        if multi:
            option['selection_range'] = {'min': 0, 'max': len(values)}
        return option

    def _wolt_languages(self):
        """(Wolt code, Odoo code) of the installed languages, the company language first."""
        self.ensure_one()
        primary = self.company_id.partner_id.lang or self.env.lang
        codes = sorted((code for code, _name in self.env['res.lang'].get_installed()), key=lambda code: code != primary)
        langs = {}
        for code in codes:
            langs.setdefault(code.split('_')[0], code)
        return list(langs.items())

    @api.model
    def _wolt_text(self, record, field_name, langs):
        texts = [{'lang': wolt_lang, 'value': record.with_context(lang=lang)[field_name]} for wolt_lang, lang in langs]
        return [text for text in texts if text['value']]

    def _wolt_pricelist(self):
        return self.pricelist_line_ids[:1].pricelist_id or self.provider_id.default_pricelist_id

    def _wolt_product_taxes(self, template):
        return template.taxes_id.filtered_domain(self.env['account.tax']._check_company_domain(self.config_id.company_id))

    def _wolt_price_included(self, price, taxes, template):
        return self.currency_id.round(taxes.compute_all(price, self.currency_id, 1, product=template)['total_included'])

    @api.model
    def _wolt_vat_percentage(self, taxes):
        taxes = taxes.flatten_taxes_hierarchy()
        if not taxes or any(tax.amount_type != 'percent' for tax in taxes):
            return None
        return sum(taxes.mapped('amount'))

    def _wolt_image_url(self, template):
        # sudo: hmac() reads the database secret, a system parameter
        token = hmac_tool(self.env(su=True), 'wolt-menu-image', str(template.id))
        return urljoin(self.get_base_url(), f"{const.MENU_IMAGE_ROUTE}/{template.id}/{token}.jpg")

    def _update_platform_order_menu(self, products):
        self.ensure_one()
        if self.provider_code != const.PROVIDER_CODE:
            return super()._update_platform_order_menu(products)
        # Wolt allows one item update per venue every 15 minutes: queue it for the cron.
        self.wolt_pending_product_tmpl_ids = [Command.link(product.id) for product in products]
        return None

    def _get_menu_products(self):
        products = super()._get_menu_products()
        if self.provider_code != const.PROVIDER_CODE:
            return products
        # core searches as sudo or in all active companies: keep what this POS's company can sell
        return products.filtered_domain(products._check_company_domain(self.config_id.company_id))

    def _wolt_push_pending_items(self):
        """Send queued price and availability changes (PATCH items, minor units)."""
        self.ensure_one()
        products = self.wolt_pending_product_tmpl_ids
        if not products:
            return
        minor_unit = 10 ** self.currency_id.decimal_places
        items = []
        prices = self._wolt_pricelist()._get_products_price(products, 1.0)
        for template in products:
            taxes = self._wolt_product_taxes(template)
            item = {
                'external_id': utils._get_external_id(template),
                'price': round(self._wolt_price_included(prices[template.id], taxes, template) * minor_unit),
                'enabled': template.platform_order_available,
            }
            vat = self._wolt_vat_percentage(taxes)
            if vat is not None:
                item['vat_percentage'] = vat
            items.append(item)
        WoltClient(self).update_items(items)
        self.write({
            'wolt_pending_product_tmpl_ids': [Command.unlink(product.id) for product in products],
            'wolt_items_pushed_at': fields.Datetime.now(),
        })

    def _wolt_import_pending_orders(self):
        """Core detaches future preorders at a session close; they and the queued imports join the open session.
        Collected or delivered orders left unpaid (POS closed, failed payment) are paid on every run.
        While the POS is closed, a queued preorder that is still waiting is confirmed so Wolt keeps it."""
        self.ensure_one()
        session = self.config_id.current_session_id
        Order = self.env['pos.order']
        if session:
            store_drafts = Domain('platform_order_store_id', '=', self.id) & Domain('state', '=', 'draft')
            Order.search(store_drafts & Domain('session_id', '=', False)).session_id = session
            unpaid = store_drafts & Domain('session_id', '=', session.id) & Domain('payment_ids', '=', False)
            for order in Order.search(unpaid & Domain('platform_order_status', 'in', ('collected', 'delivered'))):
                try:
                    with self.env.cr.savepoint():
                        order.write(order._get_payment_method_values())
                        self.config_id.notify_platform_order_synchronisation(order)
                except Exception:
                    _logger.exception("Wolt: payment of order %s for store %s failed", order.platform_order_ref, self.id)
        if not self.wolt_pending_order_refs:
            return
        client = WoltClient(self)
        kept = []
        for order_ref in self.wolt_pending_order_refs:
            if Order._find_order_from_data(const.PROVIDER_CODE, {'order': {'id': order_ref}}, raise_if_not_found=False):
                continue
            try:
                with self.env.cr.savepoint():
                    data = client.get_order(order_ref)
                    if data.get('order_status') == 'rejected':
                        _logger.info("Wolt: queued order %s for store %s was rejected, dropped", order_ref, self.id)
                    elif session:
                        order = self._create_order_from_data(data)
                        if data.get('order_status') == 'delivered':
                            order._update_order_status_from_data({'type': 'order.notification', 'order': {'status': 'DELIVERED'}})
                    else:
                        if preorder_status(data) == 'waiting':
                            client.confirm_preorder(order_ref)
                        kept.append(order_ref)
            except Exception as error:
                if isinstance(error, HTTPError) and error.response.status_code == 404:
                    _logger.warning("Wolt: queued order %s for store %s no longer exists at Wolt, dropped", order_ref, self.id)
                else:
                    _logger.exception("Wolt: import of queued order %s for store %s failed", order_ref, self.id)
                    kept.append(order_ref)
        self.wolt_pending_order_refs = kept or False

    @api.model
    def _cron_wolt_sync(self):
        """Import queued orders, push queued item changes and keep idle venues' refresh tokens alive (30 days)."""
        # sudo: one run serves the stores of every company, whatever user the cron runs as
        stores = self.sudo().search([('provider_code', '=', const.PROVIDER_CODE), ('provider_id.state', '!=', 'disabled')])
        now = fields.Datetime.now()
        # Wolt accepts one item update per venue every 15 minutes.
        push_before = now - datetime.timedelta(minutes=15)
        for store in stores.filtered('wolt_connected'):
            store = store.with_company(store.company_id)
            try:
                with self.env.cr.savepoint():
                    store._wolt_import_pending_orders()
            except Exception:
                _logger.exception("Wolt: import failed for store %s", store.id)
            try:
                with self.env.cr.savepoint():
                    if (store.wolt_pending_product_tmpl_ids and (not store.wolt_items_pushed_at or store.wolt_items_pushed_at <= push_before)):
                        store._wolt_push_pending_items()
                    elif store.wolt_token_expiry < now - datetime.timedelta(days=1):
                        store._wolt_get_access_token()
            except Exception:
                _logger.exception("Wolt: sync failed for store %s", store.id)
            if not self.env['ir.cron']._commit_progress(1):
                break
            # a webhook may have queued an order on a later store since the prefetch
            self.env.invalidate_all()

    def action_wolt_go_online(self):
        return self._wolt_set_online(True)

    def action_wolt_go_offline(self):
        return self._wolt_set_online(False)

    def _wolt_set_online(self, online):
        for store in self:
            store._wolt_call(lambda client: client.set_online(online))
        return self.action_wolt_refresh_status()

    def action_wolt_push_opening_hours(self):
        self.check_access('write')
        # sudo: Service Hours are readable by admins only (pos_platform_order), POS managers push them
        for store in self.sudo():
            if not store.service_hours_id:
                raise UserError(self.env._("Set the Service Hours of store %s first.", store.display_name))
            store._wolt_call(lambda client: client.set_opening_times(store._wolt_prepare_opening_times()))

    def _wolt_prepare_opening_times(self):
        """Weekly windows from the Service Hours calendar, in the venue's local time."""
        def hhmm(hours):
            hour, minute = divmod(round(hours * 60), 60)
            return f"{hour:02d}:{minute:02d}"

        attendances = self.service_hours_id.attendance_ids.filtered(lambda a: not a.date and not a.duration_based)
        if not attendances:
            # An empty list would close the venue on Wolt for the whole week.
            raise UserError(self.env._("The Service Hours of %s have no weekly opening hours.", self.display_name))
        availability = []
        for attendance in attendances.sorted(lambda a: (a.dayofweek, a.hour_from)):
            day = const.WEEKDAYS[int(attendance.dayofweek)]
            availability.append({
                'opening_day': day,
                'opening_time': hhmm(attendance.hour_from),
                'closing_day': day,
                'closing_time': hhmm(attendance.hour_to),
            })
        return availability

    def action_wolt_refresh_status(self):
        for store in self:
            status = store._wolt_call(lambda client: client.get_venue_status())['status']
            store.write({
                'wolt_venue_online': status.get('is_online'),
                'wolt_venue_open': status.get('is_open'),
                'wolt_venue_status_date': fields.Datetime.now(),
            })

    def _wolt_call(self, call):
        """Venue actions are for POS managers: check before anything is sent to Wolt."""
        self.ensure_one()
        self.check_access('write')
        try:
            return call(WoltClient(self))
        except RequestException as error:
            raise UserError(self.env._("Wolt request failed for %s: %s", self.display_name, error)) from error
