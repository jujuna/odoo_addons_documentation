/** @odoo-module **/

// Drift highlight for the read-only RS snapshot popups (Live RS View and the adjustment snapshot): after each render,
// tints the fields listed in the record's `drift_field_names` (CSV), scoped to the open dialog.

import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

class LiveRsFormController extends FormController {
    setup() {
        super.setup();
        this._highlightFrame = null;
        onMounted(() => this._scheduleHighlight());
        onPatched(() => this._scheduleHighlight());
        onWillUnmount(() => {
            if (this._highlightFrame !== null) {
                cancelAnimationFrame(this._highlightFrame);
                this._highlightFrame = null;
            }
        });
    }

    // Wait a frame so the read-only widgets are painted. One frame in flight only: onPatched can fire repeatedly and
    // the same DOM walk would run several times per render.
    _scheduleHighlight() {
        if (this._highlightFrame !== null) {
            cancelAnimationFrame(this._highlightFrame);
        }
        this._highlightFrame = requestAnimationFrame(() => {
            this._highlightFrame = null;
            this._applyDriftHighlight();
        });
    }

    _applyDriftHighlight() {
        // Scope to THIS form's own root (rootRef), never the form behind the popup.
        const root = this.rootRef();
        if (!root) {
            return;
        }
        const names = (this.model.root.data.drift_field_names || "")
            .split(",").map((s) => s.trim()).filter(Boolean);
        root.querySelectorAll(".o_rs_drift")
            .forEach((el) => el.classList.remove("o_rs_drift"));
        for (const name of names) {
            root.querySelectorAll(`.o_field_widget[name="${name}"]`).forEach((el) => {
                (el.closest(".rsw-field") || el).classList.add("o_rs_drift");
            });
        }
    }
}

registry.category("views").add("rs_waybill_live_form", {
    ...formView,
    Controller: LiveRsFormController,
});
