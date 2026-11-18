"""Asia/Tbilisi <-> UTC conversion, both directions. RS.GE uses Georgian local time (UTC+4, no DST); Odoo stores UTC.
Every datetime crossing the boundary is converted exactly once."""

from datetime import datetime
from unittest.mock import Mock

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestTimezoneIngest(RsWaybillCommon):
    """RS local string → UTC string (rs_local_to_utc, used by sync and snapshots)."""

    def test_local_to_utc_subtracts_four_hours(self):
        self.assertEqual(
            self.service.rs_local_to_utc('2026-08-12T10:00:00'),
            '2026-08-12 06:00:00')

    def test_local_to_utc_crosses_midnight_backwards(self):
        """01:00 Tbilisi is 21:00 UTC the previous day."""
        self.assertEqual(
            self.service.rs_local_to_utc('2026-08-12T01:00:00'),
            '2026-08-11 21:00:00')

    def test_no_dst_in_georgia(self):
        """Georgia has no DST: a January and a July timestamp both shift by exactly 4h."""
        self.assertEqual(self.service.rs_local_to_utc('2026-01-15T12:00:00'),
                         '2026-01-15 08:00:00')
        self.assertEqual(self.service.rs_local_to_utc('2026-07-15T12:00:00'),
                         '2026-07-15 08:00:00')

    def test_fractional_seconds_are_stripped(self):
        self.assertEqual(
            self.service.rs_local_to_utc('2026-08-12T10:00:00.4830000'),
            '2026-08-12 06:00:00')

    def test_empty_input_returns_none(self):
        self.assertIsNone(self.service.rs_local_to_utc(''))
        self.assertIsNone(self.service.rs_local_to_utc(None))

    def test_unparseable_input_degrades_instead_of_raising(self):
        """A surprise RS format must not abort the whole sync row."""
        self.assertEqual(self.service.rs_local_to_utc('not a date'), 'not a date')

    def test_close_date_maps_to_close_date_not_cancel_date(self):
        """RS also sets CLOSE_DATE on a normal close; it must not land in cancel_date."""
        waybill = self.make_waybill()
        vals = waybill._map_rs_waybill_vals({
            'STATUS': '2',
            'CLOSE_DATE': '2026-08-12T18:00:00',
        })
        self.assertEqual(vals.get('close_date'), '2026-08-12 14:00:00')
        self.assertNotIn('cancel_date', vals)

    def test_ingest_datetimes_are_converted(self):
        waybill = self.make_waybill()
        vals = waybill._map_rs_waybill_vals({
            'STATUS': '1',
            'ACTIVATE_DATE': '2026-08-12T09:00:00',
            'BEGIN_DATE': '2026-08-12T10:00:00',
            'DELIVERY_DATE': '2026-08-12T15:30:00',
        })
        self.assertEqual(vals['activation_date'], '2026-08-12 05:00:00')
        self.assertEqual(vals['transport_start_date'], '2026-08-12 06:00:00')
        self.assertEqual(vals['delivery_date'], '2026-08-12 11:30:00')


@tagged('post_install', '-at_install')
class TestTimezoneSend(RsWaybillCommon):
    """Odoo UTC → RS local, on the outbound XML and the dated action calls."""

    def _build_xml(self, waybill):
        double = Mock()
        with self.mocked_client(double):
            client, su, sp, history = self.service._get_client()
            return self.service._build_waybill_xml(waybill, client, su, sp)

    def test_begin_date_is_sent_in_georgian_local_time(self):
        waybill = self.make_waybill(transport_start_date='2026-08-12 06:00:00')
        self.add_line(waybill)
        root = self._build_xml(waybill)
        self.assertEqual(root.findtext('BEGIN_DATE'), '2026-08-12T10:00:00')

    def test_delivery_date_is_sent_in_georgian_local_time(self):
        waybill = self.make_waybill(delivery_date='2026-08-12 11:30:00')
        self.add_line(waybill)
        root = self._build_xml(waybill)
        self.assertEqual(root.findtext('DELIVERY_DATE'), '2026-08-12T15:30:00')

    def test_missing_delivery_date_sends_empty_not_epoch(self):
        waybill = self.make_waybill(delivery_date=False)
        self.add_line(waybill)
        root = self._build_xml(waybill)
        self.assertEqual(root.findtext('DELIVERY_DATE'), '')

    def test_round_trip_is_stable(self):
        """UTC -> RS local -> UTC returns the original instant (no double or reversed conversion)."""
        waybill = self.make_waybill(transport_start_date='2026-08-12 06:00:00')
        self.add_line(waybill)
        sent = self._build_xml(waybill).findtext('BEGIN_DATE')
        self.assertEqual(self.service.rs_local_to_utc(sent), '2026-08-12 06:00:00')

    def test_transporter_activate_converts_begin_date(self):
        double = Mock()
        double.send_waybill_transporter.return_value = Mock(
            send_waybill_transporterResult=1, waybill_number='AB-9')
        with self.mocked_client(double):
            self.service.send_transporter_waybill(123, datetime(2026, 8, 12, 6, 0, 0))
        sent = double.send_waybill_transporter.call_args.kwargs['begin_date']
        self.assertEqual(sent.strftime('%Y-%m-%d %H:%M:%S'), '2026-08-12 10:00:00')
        self.assertIsNone(sent.tzinfo, "RS expects a naive local wall-clock value")

    def test_transporter_close_converts_delivery_date(self):
        double = Mock()
        double.close_waybill_transporter.return_value = 1
        with self.mocked_client(double):
            self.service.close_transporter_waybill(123, datetime(2026, 8, 12, 11, 30, 0))
        sent = double.close_waybill_transporter.call_args.kwargs['delivery_date']
        self.assertEqual(sent.strftime('%Y-%m-%d %H:%M:%S'), '2026-08-12 15:30:00')


@tagged('post_install', '-at_install')
class TestTbilisiCutoffDates(RsWaybillCommon):
    """The integration cutoffs are Georgian business dates, compared against UTC-stored datetimes."""

    def _set_cutoff(self, field_name, value):
        self.env.company.write({field_name: value or False})

    def test_tbilisi_date_helper_rolls_over_at_20_utc(self):
        Waybill = self.env['rs.waybill']
        self.assertEqual(
            Waybill._tbilisi_date(datetime(2026, 8, 11, 19, 59, 0)).isoformat(),
            '2026-08-11')
        self.assertEqual(
            Waybill._tbilisi_date(datetime(2026, 8, 11, 20, 0, 0)).isoformat(),
            '2026-08-12')

    def test_mapping_cutoff_uses_georgian_date(self):
        """21:00 UTC on the 11th is the 12th in Tbilisi, so it is in scope of a cutoff on the 12th."""
        self._set_cutoff('rs_mapping_cutoff_date', '2026-08-12')
        waybill = self.make_waybill()
        self.force_create_date(waybill, '2026-08-11 21:00:00')
        self.assertTrue(waybill._mapping_enabled())

    def test_mapping_cutoff_excludes_genuinely_earlier_record(self):
        self._set_cutoff('rs_mapping_cutoff_date', '2026-08-12')
        waybill = self.make_waybill()
        self.force_create_date(waybill, '2026-08-11 12:00:00')
        self.assertFalse(waybill._mapping_enabled())

    def test_no_cutoff_configured_means_disabled(self):
        self._set_cutoff('rs_mapping_cutoff_date', '')
        self.assertFalse(self.make_waybill()._mapping_enabled())

    def test_integration_scope_prefers_activation_date(self):
        self.env.company.rs_enable_stock = True
        self._set_cutoff('rs_stock_integration_date', '2026-08-12')
        waybill = self.make_waybill(activation_date='2026-08-11 21:00:00')
        self.force_create_date(waybill, '2026-01-01 12:00:00')
        self.assertTrue(waybill._in_integration_scope())
