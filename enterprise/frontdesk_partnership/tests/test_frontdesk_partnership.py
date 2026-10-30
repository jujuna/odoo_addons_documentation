# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from odoo.tests.common import HttpCase, JsonRpcException
from odoo.tools.misc import mute_logger


class TestFrontdeskPartnership(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.grade_gold = cls.env.ref('partnership.res_partner_grade_data_gold')
        cls.grade_silver = cls.env.ref('partnership.res_partner_grade_data_silver')
        cls.partner_no_grade = cls.env['res.partner'].create({
            'name': 'Partner No Grade',
            'email': 'no_grade@example.com',
        })
        cls.partner_gold = cls.env['res.partner'].create({
            'name': 'Partner Gold',
            'email': 'gold@example.com',
            'grade_id': cls.grade_gold.id,
        })
        cls.partner_silver = cls.env['res.partner'].create({
            'name': 'Partner Silver',
            'email': 'silver@example.com',
            'grade_id': cls.grade_silver.id,
        })
        cls.station = cls.env['frontdesk.frontdesk'].create({
            'name': 'Test Partnership Station',
            'frontdesk_type': 'members',
            'required_grade_ids': [(4, cls.grade_gold.id)],
            'passback_timeout': 10.0,
        })

    def get_visitor_data(self, frontdesk, barcode):
        return self.make_jsonrpc_request(
            f'/frontdesk/{frontdesk.id}/{frontdesk.access_token}/get_visitor_data',
            {'barcode': barcode},
        )

    def prepare_visitor_data(self, station, visitor_data):
        return self.make_jsonrpc_request(
            f'/frontdesk/{station.id}/{station.access_token}/prepare_visitor_data',
            {
                'name': visitor_data.get('name'),
                'phone': visitor_data.get('phone'),
                'email': visitor_data.get('email'),
                'company': visitor_data.get('company'),
                'host_ids': visitor_data.get('host_ids', []),
            },
        )

    def test_barcode_generated_on_partner_level_assignment(self):
        """Ensure assigning a grade to an existing partner generates a barcode."""
        self.partner_no_grade.grade_id = self.grade_gold.id
        self.assertTrue(
            self.partner_no_grade.barcode,
            "A barcode should be auto-generated when a grade is assigned to a partner."
        )

    def test_barcode_generated_on_create_with_grade(self):
        """Ensure creating a partner with a grade automatically generates a barcode."""
        partner = self.env['res.partner'].create({
            'name': 'New Graded Partner',
            'grade_id': self.grade_gold.id,
        })
        self.assertTrue(
            partner.barcode,
            "Barcode should be auto-generated at creation time when grade_id is provided."
        )

    def test_authorized_entry_with_correct_grade(self):
        """Ensure a partner with the required grade is authorized to enter the frontdesk."""
        result = self.get_visitor_data(self.station, self.partner_gold.barcode)
        self.assertEqual(result['email'], self.partner_gold.email,
            "The partner with the required grade should be authorized to enter the frontdesk.",
        )

    def test_unauthorized_entry_with_wrong_grade(self):
        """Ensure a partner with an unauthorized grade is denied frontdesk access."""
        with self.assertRaises(JsonRpcException), mute_logger("odoo.http"):
            self.get_visitor_data(self.station, self.partner_silver.barcode)

    def test_unauthorized_entry_with_no_grade(self):
        """
        Ensure a partner without a grade is denied frontdesk access.
        A partner without any grade should be rejected with an error.
        """
        partner = self.env['res.partner'].create({
            'name': 'No Grade Barcode Partner',
            'barcode': '042000000001',
        })
        with self.assertRaises(JsonRpcException), mute_logger("odoo.http"):
            self.get_visitor_data(self.station, partner.barcode)

    def test_unauthorized_entry_unknown_barcode(self):
        """A barcode that doesn't correspond to any partner should raise an error."""
        with self.assertRaises(JsonRpcException), mute_logger("odoo.http"):
            self.get_visitor_data(self.station, 'BARCODE_UNKNOWN_9999')

    def test_passback_timeout_prevents_quick_rescan(self):
        """
        After a partner scans their barcode, they should not be able to scan
        again until the passback_timeout (in minutes) has elapsed.
        """
        self.station.passback_timeout = 30.0

        self.get_visitor_data(self.station, self.partner_gold.barcode)
        self.assertTrue(self.partner_gold.last_barcode_scan, "last_barcode_scan should be set after the first scan.")

        # Second immediate scan — should fail due to passback timeout
        with self.assertRaises(JsonRpcException), mute_logger("odoo.http"):
            self.get_visitor_data(self.station, self.partner_gold.barcode)

    def test_passback_timeout_allows_rescan_after_expiry(self):
        """
        After the passback timeout period has elapsed, the partner should be
        able to scan again without an error.
        """
        self.partner_gold.last_barcode_scan = datetime.now() - timedelta(minutes=11)
        result = self.get_visitor_data(self.station, self.partner_gold.barcode)
        self.assertEqual(result['email'], self.partner_gold.email,
            "The partner should be able to scan again successfully after the passback timeout expires.",
        )

    def test_passback_timeout_disabled(self):
        """
        When passback_timeout is 0 (disabled), a partner can scan multiple times
        in quick succession without any error.
        """
        self.station.passback_timeout = 0.0

        # Two consecutive scans should succeed when timeout is disabled
        result_1 = self.get_visitor_data(self.station, self.partner_gold.barcode)
        result_2 = self.get_visitor_data(self.station, self.partner_gold.barcode)
        self.assertEqual(result_1['name'], self.partner_gold.name)
        self.assertEqual(result_2['name'], self.partner_gold.name,
            "Both scans should run successfully when the passback timeout is disabled.",
        )

    def test_visitor_registration_after_check_in(self):
        """
        When a valid barcode is scanned at a members station, a visitor record
        should be created with the correct state and linked station.
        """
        station_members = self.env['frontdesk.frontdesk'].create({
            'name': 'Members Station',
            'frontdesk_type': 'members',
            'required_grade_ids': [(4, self.grade_gold.id)],
        })
        partner = self.env['res.partner'].create({
            'name': 'Registered Visitor',
            'email': 'visitor@example.com',
            'grade_id': self.grade_gold.id,
        })
        visitor_data = self.get_visitor_data(
            station_members,
            partner.barcode,
        )
        self.prepare_visitor_data(
            station_members,
            visitor_data,
        )
        created_visitor = self.env['frontdesk.visitor'].search([
            ('name', '=', partner.name),
            ('email', '=', partner.email),
            ('station_id', '=', station_members.id),
        ])
        self.assertTrue(
            created_visitor,
            "Visitor record should exist in visitor model after check-in."
        )
