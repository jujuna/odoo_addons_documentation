import { DebugWidget } from "@point_of_sale/app/utils/debug/debug_widget";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { patch } from "@web/core/utils/patch";

patch(DebugWidget.prototype, {
    get isItalianFiskalyCommissioned() {
        return this.pos.config.l10n_it_fiskaly_system_state === "COMMISSIONED";
    },

    async l10nItFiskalyPaidOrders() {
        return await this.pos.data.searchRead("pos.order", [["state", "=", "paid"]], [], {
            limit: 50,
            order: "id desc",
        });
    },

    l10nItFiskalyAlert(title, body) {
        this.dialog.add(AlertDialog, { title, body });
    },

    async l10nItFiskalyShowRecord(order) {
        if (!order.l10n_it_fiskaly_record_id) {
            this.l10nItFiskalyAlert("fiskaly", `${order.pos_reference} has no fiskaly record.`);
            return;
        }

        const record = await this.pos.data.call("pos.order", "l10n_it_fiskaly_get_record", [
            [order.id],
        ]);
        this.l10nItFiskalyAlert(
            `fiskaly record ${order.l10n_it_fiskaly_record_id}`,
            JSON.stringify(record, null, 2)
        );
    },

    async l10nItFiskalySelectOrder() {
        const orders = await this.l10nItFiskalyPaidOrders();
        if (!orders.length) {
            this.l10nItFiskalyAlert("fiskaly", "No paid order was found.");
            return;
        }

        const list = orders.map((order) => ({
            id: order.id,
            label: `${order.pos_reference} / ${order.getName()}`,
            description: order.l10n_it_fiskaly_record_id
                ? `record ${order.l10n_it_fiskaly_record_id}`
                : "no fiskaly record",
            item: order,
        }));

        const order = await makeAwaitable(this.dialog, SelectionPopup, {
            title: "Paid orders",
            list,
        });
        if (order) {
            await this.l10nItFiskalyShowRecord(order);
        }
    },
});
