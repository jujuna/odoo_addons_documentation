from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.date_utils import to_timezone

SOURCE_PREFIX = 'sale.order.line,'
PRICE_READ_TIME = time(12)
DAY_END = time(23, 59, 59)


def _differs(record, vals):
    """True when a value of vals is not what the record holds; money compares by the currency rounding."""
    for fname, value in vals.items():
        field = record._fields[fname]
        current = record[fname]
        if field.type == 'monetary':
            different = record.currency_id.compare_amounts(current, value)
        elif field.type == 'many2one':
            different = current.id != value
        else:
            different = (current or False) != value
        if different:
            return True
    return False


class HotelRmsProperty(models.Model):
    _inherit = 'hotel.rms.property'
    _check_company_auto = True

    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist", check_company=True, ondelete='set null',
        domain="[('currency_id', '=', currency_id)]",
        help="Current prices are read from this pricelist, and approved prices are written back to it as one fixed price per night and room product. "
        "Empty: prices come from a CSV import and are exported to CSV.")

    def _local_to_utc(self, day, at):
        """Naive UTC datetime of a time of day in the hotel time zone."""
        self.ensure_one()
        return to_timezone(None)(datetime.combine(day, at, tzinfo=ZoneInfo(self.tz or 'UTC')))

    def _sync_sources(self):
        super()._sync_sources()
        for prop in self:
            room_types = prop.with_context(active_test=False).room_type_ids.filtered('product_tmpl_id')
            if not room_types:
                continue
            today = prop._get_local_today()
            prop._sync_reservations(today, room_types)
            if prop.pricelist_id:
                prop._sync_prices(today, room_types)
            prop.last_data_at = fields.Datetime.now()

    def _sync_reservations(self, today, room_types):
        """Create, update and cancel the reservations of this hotel from its rental order lines."""
        self.ensure_one()
        Reservation = self.env['hotel.rms.reservation']
        by_template = {room.product_tmpl_id.id: room for room in room_types}
        existing = {res.source_ref: res for res in Reservation.search([
            ('property_id', '=', self.id),
            ('source_ref', '=like', SOURCE_PREFIX + '%'),
        ]) if res.source_ref.removeprefix(SOURCE_PREFIX).isdecimal()}
        domain = (
            Domain('is_rental', '=', True)
            & Domain('product_template_id', 'in', list(by_template))
            & Domain('company_id', '=', self.company_id.id)
            & (Domain('state', 'in', ('sale', 'cancel'))
               | Domain('id', 'in', [int(ref.removeprefix(SOURCE_PREFIX)) for ref in existing]))
        )
        # sudo: a Revenue Manager may lack Sales rights and a salesman sees own lines only; company filtered here
        lines = self.env['sale.order.line'].sudo().search(domain)
        to_create = []
        updates = defaultdict(list)
        for line in lines:
            order = line.order_id
            ref = f"{SOURCE_PREFIX}{line.id}"
            res = existing.pop(ref, Reservation)
            arrival = self._get_local_today(order.rental_start_date)
            cancelled = order.state != 'sale'
            cancel_date = False
            if cancelled and res:
                cancel_date = res.cancel_date if res.status == 'cancelled' else today
            vals = {
                'booking_date': min(self._get_local_today(order.create_date), arrival),
                'arrival': arrival,
                'departure': self._get_local_today(order.rental_return_date),
                'room_type_id': by_template[line.product_template_id.id].id,
                'rooms': int(line.product_uom_qty),
                'revenue': line.currency_id._convert(line.price_subtotal, self.currency_id, self.company_id, order.date_order.date()),
                'status': 'cancelled' if cancelled else 'confirmed',
                'cancel_date': cancel_date,
            }
            if not res:
                to_create.append(dict(vals, property_id=self.id, source_ref=ref))
            elif _differs(res, vals):
                updates[frozenset(vals.items())].append(res.id)
        for vals, ids in updates.items():
            Reservation.browse(ids).write(dict(vals))
        Reservation.create(to_create)
        Reservation.concat(*existing.values()).filtered(lambda r: r.status != 'cancelled').write({'status': 'cancelled', 'cancel_date': today})

    def _sync_prices(self, today, room_types):
        """A pricelist price of 0 means not for sale; a price waiting to be applied keeps its rate."""
        self.ensure_one()
        Price = self.env['hotel.rms.price']
        rooms = room_types.filtered('active')
        horizon_end = today + timedelta(days=self.horizon_days)
        prices = {(price.stay_date, price.room_type_id.id): price for price in Price.search([
            ('property_id', '=', self.id),
            ('room_type_id', 'in', rooms.ids),
            ('stay_date', '>=', today),
            ('stay_date', '<', horizon_end),
        ])}
        to_create = []
        updates = defaultdict(list)
        for lead in range(self.horizon_days):
            night = today + timedelta(days=lead)
            current = self.pricelist_id._get_products_price(rooms.product_tmpl_id, 1.0, date=self._local_to_utc(night, PRICE_READ_TIME))
            for room in rooms:
                rate = current[room.product_tmpl_id.id]
                row = prices.get((night, room.id))
                if self.currency_id.is_zero(rate):
                    vals = {'not_for_sale': True, 'recommended_rate': 0, 'raw_target_rate': 0, 'action': False, 'state': 'hold', 'reason_json': False}
                else:
                    vals = {'not_for_sale': False}
                    if not (row and row.to_export):
                        vals.update({'published_rate': rate, 'exported_rate': rate})
                if not row:
                    to_create.append(dict(vals, property_id=self.id, stay_date=night, room_type_id=room.id, state='hold'))
                elif _differs(row, vals):
                    updates[frozenset(vals.items())].append(row.id)
        for vals, ids in updates.items():
            Price.browse(ids).write(dict(vals))
        Price.create(to_create)

    def _get_apply_domain(self):
        """The prices the apply writes; the calendar's publish count uses the same set."""
        self.ensure_one()
        return (
            Domain('property_id', '=', self.id)
            & Domain('to_export', '=', True)
            & Domain('not_for_sale', '=', False)
            & Domain('room_type_id.product_tmpl_id', '!=', False)
            & Domain('stay_date', '>=', self._get_local_today())
        )

    def action_publish_approved(self):
        """Apply the approved prices to the pricelist, one fixed-price item per night and room product."""
        self.ensure_one()
        if not self.pricelist_id:
            return super().action_publish_approved()
        Item = self.env['product.pricelist.item']
        if not Item.has_access('create'):
            raise UserError(self.env._("Applying prices to the pricelist needs the access right Sales: Administrator or Product: Manager."))
        prices = self.env['hotel.rms.price'].search(self._get_apply_domain(), order='stay_date, room_type_id')
        items = {item.hotel_rms_price_id.id: item for item in Item.search([('hotel_rms_price_id', 'in', prices.ids)])}
        to_create = []
        for price in prices:
            vals = {
                'pricelist_id': self.pricelist_id.id,
                'product_tmpl_id': price.room_type_id.product_tmpl_id.id,
                'compute_price': 'fixed',
                'fixed_price': price.published_rate,
                'min_quantity': 0,
                'date_start': self._local_to_utc(price.stay_date, time.min),
                'date_end': self._local_to_utc(price.stay_date, DAY_END),
            }
            if price.id in items:
                items[price.id].write(vals)
            else:
                to_create.append(dict(vals, hotel_rms_price_id=price.id))
        Item.create(to_create)
        prices._mark_exported('apply')
        return False

    def get_calendar(self, date_from=None, days=14):
        """With a pricelist, the publish count is what the apply writes."""
        calendar = super().get_calendar(date_from, days)
        if self.pricelist_id:
            calendar['to_export_count'] = self.env['hotel.rms.price'].search_count(self._get_apply_domain())
            calendar['publish'].update(label=self.env._("Apply to pricelist"), done=self.env._("%s prices applied to the pricelist"))
        return calendar
