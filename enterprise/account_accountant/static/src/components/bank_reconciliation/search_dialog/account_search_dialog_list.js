import { useProps, proxy, t } from "@odoo/owl";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer, listRendererProps } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { standardViewProps } from "@web/views/standard_view_props";

export class BankRecAccountDialogListController extends ListController {
    static template = "account_accountant.BankRecAccountDialogListController";

    props = useProps({
        ...standardViewProps,
        allowSelectors: t.boolean().optional(true),
        onSelectionChanged: t.function().optional(),
        readonly: t.boolean().optional(),
        allowOpenAction: t.boolean().optional(true),
        Model: t.function(),
        Renderer: t.function(),
        buttonTemplate: t.string(),
        archInfo: t.object(),
        createRecord: t.function().optional(() => () => {}),
        selectRecord: t.function().optional(() => () => {}),
        bankRecInfo: t.object().optional(),
    });

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.useService = useService("ui");
        this.selectedLines = [];
        this.resIds = [];
    }

    async onSelectionChanged() {
        this.resIds = await this.model.root.getResIds(true);
        if (!this.resIds.length) {
            this.props.onSelectionChanged(this.resIds, []);
        }

        // When being in the list view with more element than the limit and doing a select all, the user has the
        // possibility to select more element than the limit. In this case the isDomainSelected is True
        if (this.isDomainSelected) {
            const { resModel, context } = this.model.root._config;
            this.selectedLines = await this.orm.read(resModel, this.resIds, ["id", "amount"], {
                context,
            });
        } else {
            this.selectedLines = Object.values(this.model.root.records).filter((record) =>
                this.resIds.includes(record._config.resId)
            );
        }
        this.props.onSelectionChanged(this.resIds, this.selectedLines);
    }

    async onRecordSaved(record) {
        if (!record.selected) {
            record.selected = true;
            await this.onSelectionChanged();
        }
        // When saving the record, there is an inconsistency between selectedLines and the real lines,
        // So this will update manually and redo a onSelectionChanged to trigger the update
        const selectedLine = this.selectedLines.find((line) => line.resId === record.resId);
        selectedLine.amount = record.data.amount;
        this.props.onSelectionChanged(this.resIds, this.selectedLines);
        return true;
    }
}

export class BankRecAccountDialogListRenderer extends ListRenderer {
    static template = "account_accountant.BankRecAccountDialogListRenderer";
    props = useProps({
        ...listRendererProps,
        bankRecInfo: t.any().optional(),
    });

    setup() {
        super.setup();
        if (this.props.bankRecInfo?.state) {
            this.bankRecState = proxy(this.props.bankRecInfo.state);
        }
    }

    isRecordReadonly(record) {
        if (record?.selected) {
            return false;
        }
        return super.isRecordReadonly(record);
    }

    isFieldReadonly(column, record) {
        if (record?.selected) {
            return false;
        }
        return super.isFieldReadonly(column, record);
    }

    async onCellClicked(record, column, ev, newWindow) {
        if (!this.props.list.selection.length) {
            this.props.openRecord(record, { newWindow });
        }

        if (!record.selected) {
            return;
        }

        // This comes from the list_renderer.js
        const clickedSubFieldName = ev.target.closest("[data-field-name]")?.dataset.fieldName;
        await this.props.list.enterEditMode(record);
        this.cellToFocus = { column, record, subFieldName: clickedSubFieldName };
    }

    onGlobalClick(ev) {
        // In case we click on another column and that we have an edited record we want to save it
        // it will work with a click or a tab
        if (this.editedRecord()) {
            this.editedRecord().save();
            this.props.list.leaveEditMode();
        }
        super.onGlobalClick(ev);
    }

    get remainingAmountFormatted() {
        const { currencyId } = this.props.bankRecInfo;
        return formatMonetary(this.bankRecState.remainingAmount, { currencyId });
    }
}

export const bankRecAccountDialogListRenderer = {
    ...listView,
    Renderer: BankRecAccountDialogListRenderer,
    Controller: BankRecAccountDialogListController,
    props: (genericProps, view) => {
        const baseProps = listView.props(genericProps, view);
        return {
            ...baseProps,
            bankRecInfo: genericProps.bankRecInfo,
        };
    },
};

registry.category("views").add("bank_rec_account_dialog_list", bankRecAccountDialogListRenderer);
