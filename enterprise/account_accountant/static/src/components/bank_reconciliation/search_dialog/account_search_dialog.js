import {
    SelectCreateDialog,
    selectCreateDialogProps,
} from "@web/views/view_dialogs/select_create_dialog";
import { useService } from "@web/core/utils/hooks";
import { useProps, t } from "@odoo/owl";

const { DateTime } = luxon;

export class BankRecAccountSelectCreateDialog extends SelectCreateDialog {
    props = useProps({
        ...selectCreateDialogProps,
        journalCurrencyId: t.number(),
        suspenseAccountLine: t.object(),
        reference: t.string(),
        date: t.instanceOf(DateTime),
    });

    setup() {
        super.setup();
        this.orm = useService("orm");
        // we want the remaining amount to be positive no matter the statement line amount
        // in case the statement line is negative we will invert the sign of the added lines
        // Also, this.state is coming from the super class SelectCreateDialog
        this.state.remainingAmount = this.absoluteStatementLineAmount;
        this.state.statementLineSign = Math.sign(-this.suspenseAccountLine.amount_currency);

        // Since we cannot compute the rates directly, we hide the balance when the currency
        // is not the one from the journal
        if (this.suspenseAccountLine.currency_id.id !== this.props.journalCurrencyId) {
            this.state.hideRemainingAmount = true;
        }
        this.baseViewProps.onSelectionChanged = (resIds, selectedLines) => {
            this.state.resIds = resIds;
            this.state.selectedLines = selectedLines;

            this.changeInSelectedMoveLine(
                selectedLines.map((record) => ({
                    id: record.resId,
                    amount: record.data.amount,
                }))
            );
        };

        this.baseViewProps.bankRecInfo = {
            date: this.formattedStatementLineDate,
            reference: this.props.reference,
            state: this.state,
            currencyId: this.suspenseAccountLine.currency_id.id,
        };
    }

    async select(resIds) {
        // If we have selectedLines (might not be the case if we click directly on a line)
        // We want to save them to be sure the amount is the one entered by the user
        for (const line of this.state.selectedLines) {
            await line.save();
        }
        super.select(resIds);
    }

    get viewProps() {
        const props = super.viewProps;
        // Small hack to make sure the SelectCreateDialog can be editable
        props.readonly = false;
        return props;
    }

    async changeInSelectedMoveLine(selectedLines) {
        // This function may cause difference between the Python and JS but is needed to
        // compute the remaining amount on top of the view
        if (!selectedLines?.length) {
            this.state.remainingAmount = this.absoluteStatementLineAmount;
            return;
        }
        const selectedLinesSum = selectedLines.reduce((sum, line) => sum - line.amount, 0);
        this.state.remainingAmount = this.absoluteStatementLineAmount + selectedLinesSum;
    }

    get absoluteStatementLineAmount() {
        return Math.abs(this.suspenseAccountLine.amount_currency);
    }

    get suspenseAccountLine() {
        return this.props?.suspenseAccountLine;
    }

    get formattedStatementLineDate() {
        return this.props.date?.toLocaleString({
            month: "short",
            day: "2-digit",
        });
    }
}
