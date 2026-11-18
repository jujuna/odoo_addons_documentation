import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    async onClickBookWoltCourier(order) {
        const quote = await this._callWoltDrive(order, "wolt_drive_quote");
        if (!quote) {
            return;
        }
        const body = quote.eta_minutes
            ? _t("Book the courier for %(price)s, at the customer in about %(eta)s minutes?", {
                  price: this.pos.formatCurrency(quote.price),
                  eta: quote.eta_minutes,
              })
            : _t("Book the courier for %(price)s?", {
                  price: this.pos.formatCurrency(quote.price),
              });
        if (!(await ask(this.dialog, { title: _t("Wolt Courier"), body }))) {
            return;
        }
        const args = [quote.promise_id, quote.dropoff_location];
        const booked = await this._callWoltDrive(order, "wolt_drive_book", args);
        if (booked) {
            this.pos.notification.add(_t("Wolt courier booked."), { type: "success" });
        } else if (booked === false) {
            this.pos.notification.add(
                _t(
                    "Wolt has not confirmed the courier yet. The order shows Waiting for Wolt: press Wolt Courier again to check."
                ),
                { type: "warning" }
            );
        }
    },
    async onClickCancelWoltCourier(order) {
        const body = _t("Cancel the Wolt courier?");
        if (!(await ask(this.dialog, { title: _t("Wolt Courier"), body }))) {
            return;
        }
        await this._callWoltDrive(order, "wolt_drive_cancel");
    },
    async _callWoltDrive(order, method, args = []) {
        this.ui.block();
        try {
            const result = await this.pos.data.call("pos.order", method, [order.id, ...args]);
            if (method !== "wolt_drive_quote") {
                await this.pos.data.loadServerOrders([["id", "=", order.id]]);
            }
            return result;
        } catch (error) {
            this.pos.notification.add(error?.data?.message || _t("Wolt Drive request failed."), {
                type: "danger",
            });
            return null;
        } finally {
            this.ui.unblock();
        }
    },
});
