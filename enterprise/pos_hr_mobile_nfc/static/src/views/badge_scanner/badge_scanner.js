import { Component, onWillStart, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { BarcodeScanner } from "@barcodes/components/barcode_scanner";
import { useNfcReader } from "@pos_mobile/app/hooks/nfc_reader";

export class BadgeScanner extends Component {
    static template = "pos_hr_mobile_nfc.BadgeScanner";
    static components = { BarcodeScanner };

    props = useProps(standardActionServiceProps);
    setup() {
        this.employeeId = this.props.action.context.active_id;
        this.notification = useService("notification");
        this.orm = useService("orm");
        onWillStart(async () => {
            [this.employee] = await this.orm.read("hr.employee", [this.employeeId], ["name"]);
        });
        useNfcReader((uid) => this.onBadgeScanned(uid));
    }

    async onBadgeScanned(badge) {
        try {
            await this.orm.write("hr.employee", [this.employeeId], { barcode: badge });
        } catch (error) {
            this.notification.add(_t("Failed to update badge: %s", error?.data?.message), {
                type: "danger",
            });
            return;
        }
        this.notification.add(_t("Badge updated: %s", badge), { type: "success" });
        this.goBack();
    }

    goBack() {
        this.env.config.historyBack();
    }
}

registry.category("actions").add("pos_hr_mobile_nfc.badge_scanner", BadgeScanner);
