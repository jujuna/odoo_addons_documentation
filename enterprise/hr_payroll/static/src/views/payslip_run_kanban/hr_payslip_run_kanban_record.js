import { PayRunButtonBox } from "../../components/payrun_card/button_box/payrun_button_box";
import { usePlugin } from "@odoo/owl";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { PayRunChatterService } from "@hr_payroll/js/payrun_chatter_service";

export class PayrunKanbanRecord extends KanbanRecord {
    static template = "hr_payroll.PayrunKanbanRecord";
    static menuTemplate = "hr_payroll.PayrunKanbanRecordMenu";
    static components = {
        ...KanbanRecord.components,
        PayRunButtonBox,
    };

    setup() {
        super.setup();
        this.payRunChatter = usePlugin(PayRunChatterService);
    }

    get isChatterOpen() {
        return this.payRunChatter.visible();
    }

    get isSelected() {
        return this.payRunChatter.payslipRunId === this.props.record.resId;
    }

    get renderingContext() {
        return {
            ...super.renderingContext,
            isChatterOpen: this.isChatterOpen,
            isSelected: this.isSelected,
            toggleChatter: this.toggleChatter.bind(this),
        };
    }

    onGlobalClick(ev) {
        if (ev.target.closest('.o_payrun_chatter_icon')) {
            this.toggleChatter(ev);
            return;
        }
        super.onGlobalClick(ev);
    }

    toggleChatter(ev) {
        ev?.stopPropagation();
        if (this.isChatterOpen) {
            if (this.isSelected) {
                this.payRunChatter.toggleChatter();
            } else {
                this.payRunChatter.selectPayslipRun(this.props.record);
            }
            return;
        }
        this.payRunChatter.selectPayslipRun(this.props.record);
        this.payRunChatter.toggleChatter();
    }

    getCardClasses() {
        return `${super.getCardClasses()} o_payrun_card_root opacity-trigger-hover d-flex flex-row align-items-center`;
    }
}

// this component is mainly used when we only want to show the menu of the
// kanban card (to then compile it into the PayRunButtonBox)
export class PayrunKanbanMenu extends PayrunKanbanRecord {
    static template = "hr_payroll.PayrunKanbanRecordMenu";
}
