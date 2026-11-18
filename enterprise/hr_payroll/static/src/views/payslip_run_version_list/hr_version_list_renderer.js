import { PayrollAvatarCard } from "@hr_payroll/core/web/avatar_card/payroll_avatar_card";
import { usePopover } from "@web/core/popover/popover_hook";
import { ListRenderer } from "@web/views/list/list_renderer";

export class VersionPayrunListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.avatarCard = usePopover(PayrollAvatarCard);
    }

    /**
     * Opening the employee form would leave the pay run creation flow: the avatar and the name
     * of the employee open his avatar card, the other cells select him.
     *
     * @override
     */
    async onCellClicked(record, column, ev, newWindow) {
        if (ev.target.closest(".o_m2o_avatar")) {
            // the avatar of a many2one (e.g. the manager) opens its own card
            return super.onCellClicked(record, column, ev, newWindow);
        }
        if (!this.uiService.isSmall && ["avatar_128", "name"].includes(column.name)) {
            const target = ev.target.closest(".o_data_cell");
            if (this.avatarCard.isOpen && this.avatarCardTarget === target) {
                this.avatarCard.close();
            } else {
                this.avatarCardTarget = target;
                this.avatarCard.open(target, {
                    id: record.resId,
                    model: record.resModel,
                });
            }
            return;
        }
        this.toggleRecordSelection(record);
        ev.preventDefault();
        ev.stopPropagation();
    }
}
