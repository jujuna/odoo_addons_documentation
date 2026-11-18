import base64
import io
from datetime import date
from unittest.mock import patch

import openpyxl

from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import DAY, HotelRmsCommon

RESERVATION_HEADER = "reference,booked_on,arrival,departure,room_type,rooms,revenue,status,cancelled_on,channel"
PROPERTY_MODEL_LOGGER = 'odoo.addons.hotel_rms.models.hotel_rms_property'


class ImportCommon(HotelRmsCommon):

    def _day(self, offset):
        return fields.Date.to_string(self.today + offset * DAY)

    def _import(self, content, kind='reservations', filename=None, hotel=None):
        raw = content.encode() if isinstance(content, str) else content
        filename = filename or ('data.xlsx' if raw[:2] == b'PK' else 'data.csv')
        return self.env['hotel.rms.import'].create({
            'property_id': (hotel or self.hotel).id, 'kind': kind, 'filename': filename,
            'file': {'filename': filename, 'content': base64.b64encode(raw).decode()},
        })

    def _reservation_file(self, *rows, header=RESERVATION_HEADER):
        return "\n".join([header, *rows])

    def _rates_file(self, *rows, header="date,room_type,price"):
        return "\n".join([header, *rows])

    def _xlsx(self, rows):
        workbook = openpyxl.Workbook()
        for row in rows:
            workbook.active.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _reservations(self):
        return self.env['hotel.rms.reservation'].search([('property_id', '=', self.hotel.id)])

    def _runs(self):
        return self.env['hotel.rms.run'].search([('property_id', '=', self.hotel.id)])


@tagged('post_install', '-at_install')
class TestImportReservations(ImportCommon):

    def test_csv_creates_the_reservations_and_runs_the_engine(self):
        self.hotel.last_data_at = fields.Datetime.now() - DAY
        old = self.hotel.last_data_at
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,2,300.50,confirmed,,Direct"))
        imp.action_import()
        reservation = self._reservations()
        self.assertEqual((imp.state, imp.created, imp.updated, imp.error_count), ('done', 1, 0, 0))
        self.assertEqual((reservation.source_ref, reservation.nights, reservation.rooms, reservation.revenue),
                         ('R1', 2, 2, 300.5))
        self.assertEqual((reservation.status, reservation.channel, reservation.room_type_id),
                         ('confirmed', 'Direct', self.double))
        self.assertEqual(reservation.booking_date, self.today - 2 * DAY)
        self.assertGreater(self.hotel.last_data_at, old)
        self.assertEqual(self._runs().state, 'done')
        self.assertEqual(len(self._prices()), 20)

    def test_a_revenue_manager_can_import(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,"))
        imp.with_user(self.manager).action_import()
        self.assertEqual(imp.state, 'done')
        self.assertEqual(self._runs().state, 'done')

    def test_semicolon_csv_reads_comma_decimals(self):
        header = RESERVATION_HEADER.replace(',', ';')
        imp = self._import(self._reservation_file(
            f'R1;{self._day(-2)};{self._day(3)};{self._day(5)};DBL;1;"1.200,50";confirmed;;',
            f"R2;{self._day(-2)};{self._day(3)};{self._day(5)};DBL;1;300,5;confirmed;;",
            header=header))
        imp.action_import()
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual(sorted(self._reservations().mapped('revenue')), [300.5, 1200.5])

    def test_thousands_comma_is_rejected_in_a_comma_csv(self):
        imp = self._import(self._reservation_file(
            f'R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,"1,200",confirmed,,'))
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("Use a dot for decimals", imp.errors)
        self.assertFalse(self._reservations())

    def test_optional_columns_may_be_missing(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL",
            header="reference,booked_on,arrival,departure,room_type"))
        imp.action_import()
        reservation = self._reservations()
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual((reservation.rooms, reservation.revenue, reservation.status, reservation.channel),
                         (1, 0, 'confirmed', False))

    def test_a_missing_required_column_fails_the_file(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(5)},DBL", header="reference,booked_on,departure,room_type"))
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("Missing column: arrival", imp.errors)

    def test_a_file_of_the_wrong_type_gives_one_error(self):
        imp = self._import(b'%PDF-1.4\n' + bytes(64) + b'\n%%EOF\n', filename='report.pdf')
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("CSV or XLSX", imp.errors)
        self.assertFalse(self._runs())

    def test_one_bad_row_writes_nothing(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,",
            f"R2,{self._day(-2)},{self._day(3)},{self._day(5)},Penthouse,1,100,confirmed,,"))
        imp.action_import()
        self.assertEqual((imp.state, imp.created, imp.error_count), ('failed', 0, 1))
        self.assertIn("Row 3", imp.errors)
        self.assertFalse(self._reservations())
        self.assertFalse(self._runs())

    def test_every_bad_row_is_listed(self):
        imp = self._import(self._reservation_file(
            f"R1,not a date,{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,",
            f"R2,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,maybe,,",
            f",{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,"))
        imp.action_import()
        self.assertEqual(imp.error_count, 3)
        self.assertIn("Row 2: booked_on is not a date", imp.errors)
        self.assertIn("Row 3: status maybe is unknown", imp.errors)
        self.assertIn("Row 4: reference is required", imp.errors)

    def test_departure_must_be_after_arrival(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(3)},DBL,1,100,confirmed,,",
            f"R2,{self._day(-2)},{self._day(3)},{self._day(2)},DBL,1,100,confirmed,,"))
        imp.action_import()
        self.assertEqual(imp.error_count, 2)
        self.assertIn("departure must be after arrival", imp.errors)

    def test_reimporting_the_same_file_changes_nothing(self):
        content = self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,2,300.5,confirmed,,Direct")
        self._import(content).action_import()
        again = self._import(content)
        again.action_import()
        self.assertEqual((again.state, again.created, again.updated), ('done', 0, 0))
        self.assertEqual(len(self._reservations()), 1)

    def test_a_changed_row_updates_its_reservation(self):
        self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,2,300.5,confirmed,,")).action_import()
        again = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(6)},DBL,2,450,cancelled,{self._day(-1)},"))
        again.action_import()
        reservation = self._reservations()
        self.assertEqual((again.created, again.updated), (0, 1))
        self.assertEqual((reservation.nights, reservation.revenue, reservation.status), (3, 450, 'cancelled'))
        self.assertEqual(reservation.cancel_date, self.today - DAY)

    def test_status_spellings(self):
        header = RESERVATION_HEADER
        dates = f"{self._day(-2)},{self._day(3)},{self._day(5)}"
        imp = self._import(self._reservation_file(
            f"R1,{dates},DBL,1,100,canceled,{self._day(-1)},",
            f"R2,{dates},DBL,1,100,no-show,,",
            f"R3,{dates},DBL,1,100,NO_SHOW,,",
            f"R4,{dates},DBL,1,100,,,", header=header))
        imp.action_import()
        statuses = {res.source_ref: res.status for res in self._reservations()}
        self.assertEqual(statuses, {'R1': 'cancelled', 'R2': 'no_show', 'R3': 'no_show', 'R4': 'confirmed'})

    def test_dates_in_dotted_and_slashed_formats(self):
        imp = self._import(self._reservation_file("R1,01.12.2030,25.12.2030,27/12/2030,DBL,1,100,confirmed,,"))
        imp.action_import()
        reservation = self._reservations()
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual((reservation.booking_date, reservation.arrival, reservation.departure),
                         (date(2030, 12, 1), date(2030, 12, 25), date(2030, 12, 27)))

    def test_a_slashed_date_that_reads_two_ways_is_refused(self):
        imp = self._import(self._reservation_file("R1,01.12.2030,7/11/2030,27.12.2030,DBL,1,100,confirmed,,"))
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("can be read as two dates", imp.errors)
        self.assertFalse(self._reservations())

    def test_a_date_with_a_time_of_midnight_is_read(self):
        imp = self._import(self._reservation_file("R1,2030-12-01 00:00:00,2030-12-25 00:00:00,2030-12-27 00:00:00,DBL,1,100,confirmed,,"))
        imp.action_import()
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual(self._reservations().arrival, date(2030, 12, 25))

    def test_a_csv_that_is_not_utf8_asks_for_utf8(self):
        content = self._reservation_file(f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,")
        imp = self._import(content.encode('utf-16'), filename='data.csv')
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("Save the file as UTF-8 CSV.", imp.errors)
        self.assertFalse(self._reservations())

    def test_room_types_match_by_code_then_name_and_archived_ones_still_match(self):
        self.suite.active = False
        dates = f"{self._day(-2)},{self._day(3)},{self._day(5)}"
        imp = self._import(self._reservation_file(f"R1,{dates},Double,1,100,,,", f"R2,{dates},STE,1,100,,,"))
        imp.action_import()
        by_ref = {res.source_ref: res.room_type_id for res in self._reservations()}
        self.assertEqual(by_ref, {'R1': self.double, 'R2': self.suite})

    def test_a_utf8_file_with_a_byte_order_mark_is_read(self):
        content = self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,Direct")
        imp = self._import(b'\xef\xbb\xbf' + content.encode())
        imp.action_import()
        self.assertEqual((imp.state, imp.created), ('done', 1))

    def test_xlsx_file_with_date_cells(self):
        rows = [
            RESERVATION_HEADER.split(','),
            ['X1', self.today - 2 * DAY, self.today + 3 * DAY, self.today + 5 * DAY, 'DBL', 2, 410.5,
             'confirmed', None, 'Booking.com'],
            ['X2', self._day(-2), self._day(4), self._day(5), 'STE', 1, 90, None, None, None],
        ]
        imp = self._import(self._xlsx(rows))
        imp.action_import()
        by_ref = {res.source_ref: res for res in self._reservations()}
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual((by_ref['X1'].arrival, by_ref['X1'].rooms, by_ref['X1'].revenue, by_ref['X1'].channel),
                         (self.today + 3 * DAY, 2, 410.5, 'Booking.com'))
        self.assertEqual((by_ref['X2'].room_type_id, by_ref['X2'].status), (self.suite, 'confirmed'))

    def test_check_shows_a_preview_and_writes_nothing(self):
        old = self.hotel.last_data_at
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,"))
        imp.action_check()
        self.assertIn("R1", imp.preview_html)
        self.assertEqual((imp.state, imp.error_count), ('draft', 0))
        self.assertFalse(self._reservations())
        self.assertFalse(self._runs())
        self.assertEqual(self.hotel.last_data_at, old)

    def test_check_lists_the_errors_and_writes_nothing(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},Penthouse,1,100,confirmed,,"))
        imp.action_check()
        self.assertEqual((imp.state, imp.error_count), ('draft', 1))
        self.assertIn("Row 2", imp.errors)
        self.assertFalse(self._reservations())

    def test_an_engine_error_never_rolls_back_the_import(self):
        imp = self._import(self._reservation_file(
            f"R1,{self._day(-2)},{self._day(3)},{self._day(5)},DBL,1,100,confirmed,,"))
        with (patch.object(type(self.hotel), '_compute_actuals', side_effect=RuntimeError("boom")),
              mute_logger(PROPERTY_MODEL_LOGGER)):
            imp.action_import()
        self.assertEqual(imp.state, 'done')
        self.assertEqual(len(self._reservations()), 1)
        self.assertEqual(self._runs().state, 'failed')


@tagged('post_install', '-at_install')
class TestImportRates(ImportCommon):

    def setUp(self):
        super().setUp()
        self.old_data_date = fields.Datetime.now() - DAY
        self.hotel.last_data_at = self.old_data_date

    def test_rates_become_the_live_and_exported_prices(self):
        imp = self._import(self._rates_file(f"{self._day(2)},DBL,175", f"{self._day(2)},STE,225.5"), kind='rates')
        imp.action_import()
        double, suite = self._price(2), self._price(2, self.suite)
        self.assertEqual((imp.state, imp.created, imp.updated, imp.kept), ('done', 2, 0, 0))
        self.assertEqual((double.published_rate, double.exported_rate, double.to_export), (175, 175, False))
        self.assertEqual((suite.published_rate, suite.exported_rate), (225.5, 225.5))

    def test_a_rates_import_writes_an_import_audit_row_for_a_new_price(self):
        self._import(self._rates_file(f"{self._day(2)},DBL,175"), kind='rates').action_import()
        audit = self._price(2).audit_ids
        self.assertEqual((audit.action, audit.new_rate, audit.user_id), ('import', 175, self.env.user))

    def test_a_rates_import_audit_row_of_a_changed_price_holds_the_old_price(self):
        self._run()
        self._import(self._rates_file(f"{self._day(2)},DBL,175"), kind='rates').action_import()
        audit = self._price(2).audit_ids
        self.assertEqual((audit.action, audit.old_rate, audit.new_rate), ('import', 0, 175))

    def test_rates_do_not_touch_the_booking_data_date(self):
        self._import(self._rates_file(f"{self._day(2)},DBL,175"), kind='rates').action_import()
        self.assertEqual(self.hotel.last_data_at, self.old_data_date)

    def test_rates_run_the_engine(self):
        self._import(self._rates_file(f"{self._day(2)},DBL,175"), kind='rates').action_import()
        self.assertEqual(self._runs().state, 'done')
        self.assertTrue(self._price(2).recommended_rate)

    def test_rates_waiting_to_be_published_are_kept(self):
        self._run()
        waiting = self._price(2)
        waiting.action_accept()
        accepted = waiting.published_rate
        imp = self._import(self._rates_file(f"{self._day(2)},DBL,175", f"{self._day(3)},DBL,190"), kind='rates')
        imp.action_import()
        self.assertEqual((imp.created, imp.updated, imp.kept), (0, 1, 1))
        self.assertEqual(waiting.published_rate, accepted)
        self.assertTrue(waiting.to_export)
        self.assertEqual(self._price(3).published_rate, 190)

    def test_reimporting_the_same_rates_changes_nothing(self):
        content = self._rates_file(f"{self._day(2)},DBL,175")
        self._import(content, kind='rates').action_import()
        again = self._import(content, kind='rates')
        again.action_import()
        self.assertEqual((again.created, again.updated, again.kept), (0, 0, 0))
        self.assertEqual(len(self._price(2).audit_ids), 1)

    def test_semicolon_rates_read_comma_decimals(self):
        imp = self._import(self._rates_file(f'{self._day(2)};DBL;"1.175,5"', header="date;room_type;price"),
                           kind='rates')
        imp.action_import()
        self.assertEqual(self._price(2).published_rate, 1175.5)

    def test_thousands_comma_is_rejected_in_a_comma_rates_file(self):
        imp = self._import(self._rates_file(f'{self._day(2)},DBL,"1,175"'), kind='rates')
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertFalse(self._prices())

    def test_archived_room_types_are_not_accepted_in_a_rates_file(self):
        self.suite.active = False
        imp = self._import(self._rates_file(f"{self._day(2)},STE,225"), kind='rates')
        imp.action_import()
        self.assertEqual(imp.state, 'failed')
        self.assertIn("room_type STE is unknown", imp.errors)

    def test_rates_xlsx(self):
        rows = [['date', 'room_type', 'price'], [self.today + 2 * DAY, 'DBL', 180], [self._day(3), 'Suite', 230.5]]
        imp = self._import(self._xlsx(rows), kind='rates')
        imp.action_import()
        self.assertEqual(imp.state, 'done', imp.errors)
        self.assertEqual(self._price(2).published_rate, 180)
        self.assertEqual(self._price(3, self.suite).published_rate, 230.5)

    def test_check_writes_no_prices(self):
        imp = self._import(self._rates_file(f"{self._day(2)},DBL,175"), kind='rates')
        imp.action_check()
        self.assertIn("175", imp.preview_html)
        self.assertFalse(self._prices())
        self.assertFalse(self._runs())

    def test_one_bad_rate_row_writes_nothing(self):
        imp = self._import(self._rates_file(f"{self._day(2)},DBL,175", f"{self._day(3)},DBL,cheap"), kind='rates')
        imp.action_import()
        self.assertEqual((imp.state, imp.error_count), ('failed', 1))
        self.assertIn("price is not a number", imp.errors)
        self.assertFalse(self._prices())

