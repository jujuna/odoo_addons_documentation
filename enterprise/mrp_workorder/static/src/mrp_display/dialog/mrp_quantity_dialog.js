import { useProps, t } from "@odoo/owl";
import {
    ConfirmationDialog,
    confirmationDialogProps,
} from "@web/core/confirmation_dialog/confirmation_dialog";
import { FloatField } from "@web/views/fields/float/float_field";

export class MrpQuantityDialog extends ConfirmationDialog {
    static template = "mrp_workorder.MrpQuantityDialog";
    props = useProps({
        ...confirmationDialogProps,
        record: t.object(),
    });
    static components = {
        ...ConfirmationDialog.components,
        FloatField,
    };

    async apply() {
        const { resModel, model, resId } = this.props.record;
        await this.props.record.save({ reload: false });
        if (resModel === "stock.move") {
            await model.orm.call(resModel, "action_pass", [[resId]]);
        } else if (resModel === "stock.move.line") {
            await model.orm.call(resModel, "action_apply_from_shop_floor", [[resId]]);
        }
        return this._confirm();
    }

    async remove() {
        const { resModel, model, resId } = this.props.record;
        await model.orm.call(resModel, "action_remove_from_shop_floor", [[resId]]);
        return this._confirm();
    }

    _dismiss() {
        this.props.record.discard();
    }
}
