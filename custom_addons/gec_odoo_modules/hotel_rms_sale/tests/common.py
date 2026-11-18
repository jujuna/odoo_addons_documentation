import base64
from contextlib import ExitStack, contextmanager
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from odoo import Command
from odoo.tests import TransactionCase

DAY = timedelta(days=1)
HOTEL_TZ = ZoneInfo('Asia/Tbilisi')
UTC = ZoneInfo('UTC')
LIST_PRICE = 150


def local_to_utc(day, at):
    """Expected value worked out with zoneinfo here, not by the module."""
    return datetime.combine(day, at, tzinfo=HOTEL_TZ).astimezone(UTC).replace(tzinfo=None)


class HotelRmsSaleCommon(TransactionCase):
    """A hotel in Tbilisi that sells one rental room product from a pricelist."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': "Hotel pricelist", 'currency_id': cls.currency.id, 'company_id': cls.company.id})
        cls.room_product = cls._create_room_product("Standard room")
        cls.hotel = cls.env['hotel.rms.property'].create({
            'name': "Bridge Hotel", 'company_id': cls.company.id, 'tz': 'Asia/Tbilisi', 'horizon_days': 6,
            'pricelist_id': cls.pricelist.id})
        cls.today = cls.hotel._get_local_today()
        cls.room = cls.env['hotel.rms.room.type'].create({
            'property_id': cls.hotel.id, 'name': "Standard", 'code': 'STD', 'rooms': 5,
            'product_tmpl_id': cls.room_product.id})
        cls.env['hotel.rms.season'].create({
            'property_id': cls.hotel.id, 'name': "All year", 'date_from': cls.today - 30 * DAY,
            'date_to': cls.today + 365 * DAY, 'base_rate': 150, 'min_rate': 100, 'max_rate': 300,
            'expected_occ_pct': 50})
        cls.partner = cls.env['res.partner'].create({'name': "Guest"})
        cls.manager = cls._create_user('rms_sale_manager', ['hotel_rms.group_hotel_rms_revenue_manager'])
        cls.pricelist_manager = cls._create_user(
            'rms_sale_pricelist_manager',
            ['hotel_rms.group_hotel_rms_revenue_manager', 'product.group_product_manager'])

    @classmethod
    def _create_room_product(cls, name):
        return cls.env['product.template'].create({
            'name': name, 'type': 'consu', 'list_price': LIST_PRICE, 'rent_periodicity': 'nights',
            'pickup_time': 15, 'return_time': 11, 'company_id': False})

    @classmethod
    def _create_user(cls, login, group_xmlids):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': f'{login}@example.com', 'tz': 'Asia/Tbilisi',
            'group_ids': [Command.set([cls.env.ref(xmlid).id for xmlid in group_xmlids])],
        })

    def _order(self, arrival_offset=3, nights=3, rooms=1, total=300.0, confirm=True, product=None,
               pickup=time(18), checkout=time(11), company=None):
        """Offsets are hotel-local days; pickup and checkout are hotel-local times."""
        arrival = self.today + arrival_offset * DAY
        order = self.env['sale.order'].with_company(company or self.company).create({
            'partner_id': self.partner.id, 'company_id': (company or self.company).id,
            'rental_start_date': local_to_utc(arrival, pickup),
            'rental_return_date': local_to_utc(arrival + nights * DAY, checkout),
            'order_line': [Command.create({
                'product_id': (product or self.room_product).product_variant_id.id, 'product_uom_qty': rooms,
                'price_unit': total / rooms, 'tax_ids': [Command.clear()]})],
        })
        if confirm:
            order.action_confirm()
        return order

    def _sync(self):
        self.hotel._sync_sources()

    def _reservations(self):
        return self.env['hotel.rms.reservation'].search([('property_id', '=', self.hotel.id)])

    def _prices(self):
        return self.env['hotel.rms.price'].search([('property_id', '=', self.hotel.id)])

    def _price(self, offset):
        return self._prices().filtered(lambda p: p.stay_date == self.today + offset * DAY)

    def _set_night_price(self, offset, fixed_price):
        day = self.today + offset * DAY
        return self.env['product.pricelist.item'].create({
            'pricelist_id': self.pricelist.id, 'product_tmpl_id': self.room_product.id,
            'applied_on': '1_product', 'compute_price': 'fixed', 'fixed_price': fixed_price,
            'date_start': local_to_utc(day, time.min), 'date_end': local_to_utc(day, time(23, 59, 59))})

    def _price_on(self, offset, user=None):
        """Default user is in the hotel zone (Asia/Tbilisi)."""
        pricelist = self.pricelist.with_user(user or self.pricelist_manager)
        return pricelist._get_product_price(self.room_product, 1.0, date=self.today + offset * DAY)

    def _rates_import(self):
        content = f"date,room_type,price\n{self.today + 2 * DAY},STD,99"
        return self.env['hotel.rms.import'].create({
            'property_id': self.hotel.id, 'kind': 'rates', 'filename': 'rates.csv',
            'file': {'filename': 'rates.csv', 'content': base64.b64encode(content.encode()).decode()},
        })

    @contextmanager
    def _count_calls(self, *targets):
        """Records only the writes and creates that carry something."""
        calls = []
        with ExitStack() as stack:
            for model_name, method in targets:
                model_class = type(self.env[model_name])

                def wrapper(record, *args, _original=getattr(model_class, method), _tag=(model_name, method), **kwargs):
                    if args[0] if _tag[1] == 'create' else record:
                        calls.append(_tag)
                    return _original(record, *args, **kwargs)

                stack.enter_context(patch.object(model_class, method, wrapper))
            yield calls
