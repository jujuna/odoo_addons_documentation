import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { CustomSelectCreateDialog } from "@point_of_sale/app/components/custom_select_create_dialog/custom_select_create_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(ControlButtons.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.report = useService("report");
    },
    async clickPrintBill() {
        if (!this.pos.blackbox.isActive || !this.pos.getOrder().getOrderlines().length) {
            return await super.clickPrintBill();
        }
        const order = this.pos.getOrder();
        try {
            const identifier = this.pos.l10nBeSigningInsz;
            // We must await the signOrder must sent before 'signPreBill'
            await this.pos.blackbox.signOrder.sign(order, identifier);
            // We must await the signPreBill because we need blackbox response to display it on the receipt
            const result = await this.pos.blackbox.signPreBill.sign(
                order,
                identifier,
                this.pos.ticketPrinter.hasReceiptPrinters
            );
            if (!result) {
                return false;
            }
            await super.clickPrintBill();
        } finally {
            order.l10n_be_pre_bill_event_data = {};
        }
    },
    openSplitPage() {
        if (!this.pos.blackbox.isActive) {
            return super.openSplitPage(...arguments);
        }
        const identifier = this.pos.l10nBeSigningInsz;
        // Before splitting an order, we push the potential changes to the order to the blackbox
        this.pos.blackbox.signOrder.sign(this.pos.getOrder(), identifier);
        return super.openSplitPage(...arguments);
    },

    async applyDiscount(value, type) {
        if (this.pos.blackbox.isActive && type === "fixed") {
            const order = this.pos.getOrder();
            const orderTotal = order.lines
                .filter((line) => !line.isGlobalDiscountLine())
                .reduce((sum, line) => sum + line.priceIncl, 0);
            if (parseFloat(value) > orderTotal) {
                this.dialog.add(AlertDialog, {
                    title: _t("Incorrect discount"),
                    body: _t(
                        "The discounted amount cannot be higher than the amount of the order. Please enter a valid discount."
                    ),
                });
                return;
            }
        }
        return super.applyDiscount(value, type);
    },
    onClickSalesReports() {
        this.pos.openSalesReportsList(this.report);
    },
    onClickUserReports() {
        const domain = [
            ["config_id", "=", this.pos.config.id],
            ["pos_clock_in_out_ids", "!=", false],
        ];
        this.dialog.add(CustomSelectCreateDialog, {
            resModel: "pos.session",
            title: _t("Select a session to print the user report"),
            listViewId: this.pos.models["ir.ui.view"].find(
                (v) => v.name == "pos_session_reports_list_view"
            )?.id,
            noCreate: true,
            multiSelect: false,
            domain,
            context: {},
            onSelected: async (resIds) => {
                const sessionId = resIds[0];
                const res = await this.report.doAction(
                    "l10n_be_pos_blackbox.action_report_pos_user",
                    [sessionId]
                );
                if (res?.success) {
                    const [session] = await this.pos.data.read(
                        "pos.session",
                        [sessionId],
                        ["state"]
                    );
                    this.pos.signUserReport(
                        sessionId,
                        session.state === "closed" ? "closed" : "opened"
                    );
                }
            },
        });
    },
});
