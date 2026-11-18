import { computed, proxy } from "@odoo/owl";
import { usePopover } from "@web/core/popover/popover_hook";
import { registry } from "@web/core/registry";
import { DurationPopover } from "@web/views/fields/float_time/float_time_field";
import { formatFloatTime } from "@web/views/fields/formatters";
import { DurationParseError, InvalidNumberError, parseFloatTime } from "@web/views/fields/parsers";
import { GridCell } from "./grid_cell";

export class FloatTimeGridCell extends GridCell {
    static template = "web_grid.FloatTimeGridCell";

    inputMode = "text";
    formattedValue = computed(() => formatFloatTime(this.value()));

    setup() {
        super.setup();
        this.durationState = proxy({ formattedResult: "" });
        this.resultPopover = usePopover(DurationPopover, { position: "bottom" });
    }

    parse(value) {
        return parseFloatTime(value);
    }

    onValueChange(ev) {
        const parsedValue = this.parseOrClosePopover(ev.target.value);
        if (parsedValue || parsedValue === 0) {
            this.durationState.formattedResult = formatFloatTime(parsedValue);
            if (!this.resultPopover.isOpen) {
                this.resultPopover.open(this.inputRef(), { state: this.durationState });
            }
        }
    }

    openPopover() {
        const duration = this.parseOrClosePopover(this.inputRef().value);
        if (duration || duration === 0) {
            this.durationState.formattedResult = formatFloatTime(duration);
            this.resultPopover.open(this.inputRef(), { state: this.durationState });
        }
    }

    closePopover() {
        this.resultPopover.close();
    }

    parseOrClosePopover(value) {
        try {
            return this.parse(value);
        } catch (error) {
            if (
                [EvalError, InvalidNumberError, DurationParseError].every(
                    (e) => !(error instanceof e)
                )
            ) {
                throw error;
            }
            this.closePopover();
        }
    }
}

export const floatTimeGridCell = {
    component: FloatTimeGridCell,
    formatter: formatFloatTime,
};

registry.category("grid_components").add("float_time", floatTimeGridCell);
