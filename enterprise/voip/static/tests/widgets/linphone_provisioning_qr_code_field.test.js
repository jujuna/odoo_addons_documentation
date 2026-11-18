import { mailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { mockUserAgent } from "@odoo/hoot-mock";
import { defineModels, fields, models, mountView } from "@web/../tests/web_test_helpers";

const PROVISIONING_URL = "https://odoo.example.com/voip/linphone_provisioning/token";

class Provisioning extends models.Model {
    _name = "provisioning";

    linphone_provisioning_qr_code = fields.Char();
    linphone_provisioning_url = fields.Char();

    _records = [
        {
            id: 1,
            linphone_provisioning_qr_code: "data:image/png;base64,",
            linphone_provisioning_url: PROVISIONING_URL,
        },
    ];
}

defineModels({ ...mailModels, Provisioning });

const arch = `
    <form>
        <field name="linphone_provisioning_qr_code"
               widget="voip_linphone_provisioning_qr_code"
               options="{'url_field': 'linphone_provisioning_url'}"/>
    </form>`;

test.tags("mobile");
test("on a mobile, the QR code links to its URL through the Linphone scheme", async () => {
    // The mobile preset only sets the screen: isMobileOS reads the user agent.
    mockUserAgent("android");
    await mountView({ type: "form", resModel: "provisioning", resId: 1, arch });
    expect(".o-voip-LinphoneProvisioningQrCodeField").toHaveCount(1);
    expect("a:has(.o-voip-LinphoneProvisioningQrCodeField)").toHaveAttribute(
        "href",
        `linphone-config:${PROVISIONING_URL}`
    );
});

test.tags("desktop");
test("on a desktop, the QR code is not a link", async () => {
    await mountView({ type: "form", resModel: "provisioning", resId: 1, arch });
    expect(".o-voip-LinphoneProvisioningQrCodeField").toHaveCount(1);
    expect("a:has(.o-voip-LinphoneProvisioningQrCodeField)").not.toHaveAttribute("href");
});
