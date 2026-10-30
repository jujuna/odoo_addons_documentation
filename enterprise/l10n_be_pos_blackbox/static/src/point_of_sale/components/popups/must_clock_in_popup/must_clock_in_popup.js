import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Component, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

class CustomDialog extends Dialog {
    onEscape() {}
}

export class MustClockInPopup extends Component {
    static template = "l10n_be_pos_blackbox.MustClockInPopup";
    static components = { Dialog: CustomDialog };
    props = useProps({
        close: t.function(),
    });

    setup() {
        this.pos = usePos();
    }
    async clockIn() {
        await this.pos.handleClockInOut(this.pos.accessRight.loggedCashier, "in");
        this.props.close();
    }
}
