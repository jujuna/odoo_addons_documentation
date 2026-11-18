import { patch } from "@web/core/utils/patch";
import { PosStore, posService } from "@point_of_sale/app/services/pos_store";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { uuidv4, getColorScheme } from "@point_of_sale/utils";

patch(posService, {
    dependencies: [...posService.dependencies, "iot_http"],
});

patch(PosStore.prototype, {
    async setup(env, { iot_http }) {
        this.iotHttp = iot_http;
        await super.setup(...arguments);
    },
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        this.iotHttp.cacheIotBoxRecords(this.models["iot.box"].getAll());
        this.barcodeReader?.setupListeners(this.config.iot_scanner_ids);
    },
    showScreen(name, props, newOrder = false) {
        if (
            this.router.currentScreen() === "PaymentScreen" &&
            this.getOrder()?.payment_ids.some(
                (pl) =>
                    pl.payment_method_id.payment_provider === "worldline" &&
                    ["waiting", "waitingCard", "waitingCancel"].includes(pl.payment_status)
            )
        ) {
            this.dialog.add(AlertDialog, {
                title: _t("Transaction in progress"),
                body: _t("Please process or cancel the current transaction."),
            });
        } else {
            return super.showScreen(...arguments);
        }
    },
    openIotCustomerDisplay() {
        if (!localStorage.getItem("device_uuid")) {
            localStorage.setItem("device_uuid", uuidv4());
        }
        const deviceUuid = localStorage.getItem("device_uuid");
        this.data.call("pos.config", "open_iot_customer_display", [
            this.config.id,
            deviceUuid,
            getColorScheme(),
        ]);
    },
    closeIotCustomerDisplay() {
        this.data.call("pos.config", "close_iot_customer_display", [this.config.id]);
    },
});
