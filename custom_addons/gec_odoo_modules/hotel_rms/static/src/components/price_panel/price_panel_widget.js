import { Component, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { DONE_MESSAGES, UNDOABLE, recordCurrency } from "../../utils/pricing_utils";
import { PricePanel } from "./price_panel";

const TOAST_DELAY = 5000;

export class PricePanelWidget extends Component {
    static template = "hotel_rms.PricePanelWidget";
    static components = { PricePanel };
    props = useProps(standardWidgetProps);

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({ busy: false, version: 0 });
    }

    get currency() {
        return recordCurrency(this.props.record);
    }

    noop() {}

    async act(method, args = []) {
        const { record } = this.props;
        this.state.busy = method;
        try {
            if (record.dirty) {
                await record.save();
            }
            await this.orm.call("hotel.rms.price", method, [[record.resId], ...args]);
            await record.load();
            this.state.version++;
            this.notification.add(DONE_MESSAGES[method][0], {
                type: "success",
                autocloseDelay: TOAST_DELAY,
                buttons: UNDOABLE.includes(method)
                    ? [{ name: _t("Undo"), onClick: () => this.act("action_undo") }]
                    : [],
            });
        } finally {
            this.state.busy = false;
        }
    }
}

export const pricePanelWidget = { component: PricePanelWidget };

registry.category("view_widgets").add("rms_price_panel", pricePanelWidget);
