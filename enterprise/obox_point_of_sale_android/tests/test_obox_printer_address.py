from odoo.tests import TransactionCase


class TestOboxPrinterAddress(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.obox = cls.env["obox.obox"].create({
            "name": "Phone Obox",
            "serial_number": "ODO-PHONE",
            "state": "02_paired",
            "token": "dummy",
            "platform": "android",
            "local_ip": "192.168.1.10",
            "local_port": 4545,
        })
        cls.device = cls.env["obox.device"].create({
            "name": "Kitchen",
            "identifier": "usb_kitchen",
            "type": "printer",
            "obox_id": cls.obox.id,
        })
        cls.printer = cls.env["pos.printer"].create({
            "name": "Kitchen printer",
            "printer_type": "obox",
            "obox_device_id": cls.device.id,
            "printer_ip": "192.168.1.10:4545/usb/v1/printer/usb_kitchen",
        })

    def test_the_address_carries_the_port(self):
        self.assertEqual(self.printer.printer_ip, "192.168.1.10:4545/usb/v1/printer/usb_kitchen")

    def test_a_new_ip_moves_the_printer(self):
        self.obox.local_ip = "192.168.1.20"

        self.assertEqual(self.printer.printer_ip, "192.168.1.20:4545/usb/v1/printer/usb_kitchen")

    def test_a_new_port_moves_the_printer(self):
        self.obox.local_port = 4546

        self.assertEqual(self.printer.printer_ip, "192.168.1.10:4546/usb/v1/printer/usb_kitchen")

    def test_a_synced_ip_moves_the_printer(self):
        self.obox._sync_device_state({"ip": "192.168.1.30", "local_port": 4547})

        self.assertEqual(self.printer.printer_ip, "192.168.1.30:4547/usb/v1/printer/usb_kitchen")

    def test_an_unusable_ip_leaves_the_printer_alone(self):
        for ip in ("0.0.0.0", "not-an-ip"):
            with self.subTest(ip=ip):
                self.obox.local_ip = ip

                self.assertEqual(self.printer.printer_ip, "192.168.1.10:4545/usb/v1/printer/usb_kitchen")

    def test_the_same_address_leaves_the_printer_alone(self):
        self.printer.printer_ip = "192.168.1.10:4545/usb/v1/printer/custom"

        self.obox.write({"local_ip": "192.168.1.10", "local_port": 4545})

        self.assertEqual(self.printer.printer_ip, "192.168.1.10:4545/usb/v1/printer/custom")

    def test_a_usable_ip_after_an_outage_moves_the_printer(self):
        self.obox.local_ip = "0.0.0.0"
        self.obox.local_ip = "192.168.1.40"

        self.assertEqual(self.printer.printer_ip, "192.168.1.40:4545/usb/v1/printer/usb_kitchen")

    def test_other_printers_are_left_alone(self):
        other_box = self.env["obox.obox"].create({
            "name": "Other Obox",
            "serial_number": "ODO-OTHER",
            "state": "02_paired",
            "token": "dummy-other",
            "platform": "android",
            "local_ip": "192.168.1.50",
        })
        other_device = self.env["obox.device"].create({
            "name": "Bar",
            "identifier": "usb_bar",
            "type": "printer",
            "obox_id": other_box.id,
        })
        other_printer = self.env["pos.printer"].create({
            "name": "Bar printer",
            "printer_type": "obox",
            "obox_device_id": other_device.id,
            "printer_ip": "192.168.1.50/usb/v1/printer/usb_bar",
        })
        epson = self.env["pos.printer"].create({
            "name": "Epson",
            "printer_type": "epson_epos",
            "printer_ip": "192.168.1.60",
        })

        self.obox.local_ip = "192.168.1.20"

        self.assertEqual(other_printer.printer_ip, "192.168.1.50/usb/v1/printer/usb_bar")
        self.assertEqual(epson.printer_ip, "192.168.1.60")

    def test_a_raspberry_pi_box_is_left_alone(self):
        self.obox.platform = "rpi"

        self.obox.local_ip = "192.168.1.20"

        self.assertEqual(self.printer.printer_ip, "192.168.1.10:4545/usb/v1/printer/usb_kitchen")
