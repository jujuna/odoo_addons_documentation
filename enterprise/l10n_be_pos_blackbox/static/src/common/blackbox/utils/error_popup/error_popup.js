import { Dialog } from "@web/core/dialog/dialog";
import { Component, useProps, t } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

export class L10nBeBlackboxErrorPopup extends Component {
    static components = { Dialog };
    static template = "l10n_be_pos_blackbox.L10nBeBlackboxErrorPopup";
    props = useProps({
        errors: t.array().optional([]),
        data: t.object().optional({}),
        mutationName: t.string().optional(""),
        close: t.function(),
    });

    setup() {
        this.pos = usePos();
    }

    get order() {
        return this.props.data.order;
    }

    retry() {
        this.props.close();
        this.pos.syncAllOrders({ orders: [this.order] });
    }

    get showViewOrderButton() {
        const order = this.order;
        return order && order.state !== "paid";
    }

    viewOrder(order) {
        this.props.close();
        this.pos.setOrder(order);
        this.pos.navigate("ProductScreen", { orderUuid: this.pos.selectedOrderUuid });
    }
}
