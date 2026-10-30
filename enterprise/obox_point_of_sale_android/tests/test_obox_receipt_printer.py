from odoo.tests import HttpCase, tagged

from odoo.addons.obox.tests.common import CommonOboxTest


@tagged("post_install", "-at_install")
class TestOboxReceiptPrinter(HttpCase, CommonOboxTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.obox.write({"platform": "android", "local_ip": "192.168.1.10", "local_port": 4545})
        cls.pos_config = cls.env["pos.config"].create({"name": "Obox Shop"})

    def _add(self, **extra):
        return self.make_jsonrpc_request("/obox/pos/add_receipt_printer", {
            "serial_number": "TEST",
            "token": "test_obox_token",
            "config_id": self.pos_config.id,
            "identifier": "test_obox_printer",
            **extra,
        })

    def test_the_detail_lists_the_box_printers_a_config_uses(self):
        def linked_printers():
            detail = self.obox._get_obox_feature_details("point_of_sale")
            return next(pos for pos in detail["point_of_sale"] if pos["id"] == self.pos_config.id)["linked_printers"]

        self.assertEqual(linked_printers(), [])
        self.obox._add_obox_receipt_printer(self.pos_config.id, "test_obox_printer")
        self.assertEqual(linked_printers(), ["test_obox_printer"])

    def test_the_detail_lists_a_box_printer_a_config_uses_for_preparation(self):
        self.pos_config.preparation_printer_ids = self.env["pos.printer"].create({
            "name": "Kitchen",
            "printer_type": "obox",
            "use_type": "preparation",
            "obox_device_id": self.obox_printer.id,
        })

        detail = self.obox._get_obox_feature_details("point_of_sale")

        pos = next(pos for pos in detail["point_of_sale"] if pos["id"] == self.pos_config.id)
        self.assertEqual(pos["linked_printers"], ["test_obox_printer"])

    def test_the_box_adds_its_printer_as_receipt_printer(self):
        self.assertTrue(self._add())

        printer = self.pos_config.receipt_printer_ids
        self.assertTrue(self.pos_config.other_devices)
        self.assertEqual(len(printer), 1)
        self.assertEqual(printer.obox_device_id, self.obox_printer)
        self.assertEqual(printer.printer_type, "obox")
        self.assertEqual(printer.use_type, "receipt")
        self.assertTrue(printer.use_lna)
        self.assertEqual(printer.printer_ip, "192.168.1.10:4545/usb/v1/printer/test_obox_printer")

    def test_the_receipt_printer_takes_the_paper_size_the_box_announces(self):
        self.assertTrue(self._add(paper_size="58"))

        self.assertEqual(self.pos_config.receipt_printer_ids.paper_size, "58")

    def test_the_receipt_printer_keeps_the_standard_paper_otherwise(self):
        self.assertTrue(self._add(paper_size="A4"))

        self.assertEqual(self.pos_config.receipt_printer_ids.paper_size, "80")

    def test_a_second_call_adds_nothing(self):
        self._add()

        self.assertTrue(self._add())
        self.assertEqual(len(self.pos_config.receipt_printer_ids), 1)

    def test_the_box_printer_is_added_next_to_another_receipt_printer(self):
        epson = self.env["pos.printer"].create({
            "name": "Epson",
            "use_type": "receipt",
            "printer_ip": "192.168.1.60",
        })
        self.pos_config.receipt_printer_ids = epson

        self.assertTrue(self._add())

        printers = self.pos_config.receipt_printer_ids
        self.assertEqual(len(printers), 2)
        self.assertEqual((printers - epson).obox_device_id, self.obox_printer)

    def test_an_existing_printer_of_the_device_is_reused(self):
        self._add()
        other_config = self.env["pos.config"].create({"name": "Other Shop"})

        self.assertTrue(self._add(config_id=other_config.id))
        self.assertEqual(other_config.receipt_printer_ids, self.pos_config.receipt_printer_ids)

    def test_only_a_printer_of_the_box_is_added(self):
        other_box = self.env["obox.obox"].create({
            "name": "Other Obox",
            "serial_number": "OTHER",
            "state": "02_paired",
            "token": "other_token",
        })
        self.env["obox.device"].create({
            "name": "Other printer",
            "identifier": "other_printer",
            "type": "printer",
            "obox_id": other_box.id,
        })

        self.assertFalse(self._add(identifier="other_printer"))
        self.assertFalse(self._add(identifier="test_obox_scale"))
        self.assertFalse(self.pos_config.receipt_printer_ids)

    def test_a_wrong_token_is_rejected(self):
        with self.assertRaises(Exception):
            self._add(token="wrong")
        self.assertFalse(self.pos_config.receipt_printer_ids)

    def test_the_box_adds_a_printer_it_has_not_synced_yet(self):
        self.assertFalse(self._add(identifier="usb_new"))

        self.assertTrue(self._add(identifier="usb_new", name="New printer"))

        device = self.pos_config.receipt_printer_ids.obox_device_id
        self.assertEqual(device.identifier, "usb_new")
        self.assertEqual(device.name, "New printer")
        self.assertEqual(device.obox_id, self.obox)
