import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormRenderer } from "@web/views/form/form_renderer";
import { ExtractMixinFormRenderer } from "@iap_extract/components/manual_correction/form_renderer";

export class HrExpenseFormRenderer extends ExtractMixinFormRenderer(FormRenderer) {
    setup() {
        super.setup();

        this.recordModel = "hr.expense";
    }
}

export const HrExpenseFormRendererFormViewExtract = {
    ...formView,
    Renderer: HrExpenseFormRenderer,
};

registry.category("views").add("hr_expense_form", HrExpenseFormRendererFormViewExtract);
