/** @odoo-module **/

import { status } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";

/**
 * A new land plot row saved without an asset opens the land asset dialog at once. Saving the
 * asset links it to the plot; either way the list reloads when the dialog closes, and a plot
 * still without an asset keeps its "Create Asset" button.
 *
 * A save made while leaving the list (breadcrumb, menu) opens no dialog: the next screen
 * would close it at once. That plot shows as "Without Asset".
 */
export class RsForm15LandPlotListController extends listView.Controller {
    setup() {
        super.setup();
        this.rsForm15NewRecordIds = new Set();
    }

    async beforeLeave() {
        this.rsForm15Leaving = true;
        try {
            return await super.beforeLeave(...arguments);
        } finally {
            this.rsForm15Leaving = false;
        }
    }

    async onWillSaveRecord(record) {
        if (record.isNew) {
            this.rsForm15NewRecordIds.add(record.id);
        }
        return super.onWillSaveRecord(...arguments);
    }

    async onRecordSaved(record) {
        await super.onRecordSaved(...arguments);
        const savedNew = this.rsForm15NewRecordIds.delete(record.id);
        if (!savedNew || this.rsForm15Leaving || record.data.asset_id) {
            return;
        }
        const action = await this.orm.call(
            "rs.form15.land.plot", "action_rs_form15_create_asset", [[record.resId]]
        );
        await this.actionService.doAction(action, {
            onClose: async () => {
                if (status(this) !== "destroyed") {
                    await this.model.root.load();
                }
            },
        });
    }
}

registry.category("views").add("rs_form15_land_plot_list", {
    ...listView,
    Controller: RsForm15LandPlotListController,
});
