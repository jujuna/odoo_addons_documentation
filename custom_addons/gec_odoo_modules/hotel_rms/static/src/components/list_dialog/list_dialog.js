import { Component, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";

export class ListDialog extends Component {
    static template = "hotel_rms.ListDialog";
    static components = { Dialog, View };
    props = useProps({
        title: t.string(),
        resModel: t.string(),
        domain: t.array().optional([]),
        close: t.function(),
    });

    setup() {
        this.action = useService("action");
    }

    get viewProps() {
        return {
            type: "list",
            resModel: this.props.resModel,
            domain: this.props.domain,
            loadIrFilters: true,
            searchViewId: false,
            readonly: true,
            allowSelectors: false,
            allowOpenAction: false,
            noBreadcrumbs: true,
            display: { searchPanel: false, controlPanel: { buttons: false } },
            selectRecord: (resId) => this.openFullPage({ res_id: resId, views: [[false, "form"]] }),
        };
    }

    /** Full page, so the breadcrumb leads back to the page under this pop-up. */
    openFullList() {
        return this.openFullPage({ views: [[false, "list"], [false, "form"]] });
    }

    async openFullPage(values) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: this.props.title,
            res_model: this.props.resModel,
            domain: this.props.domain,
            ...values,
        });
        this.props.close();
    }
}
