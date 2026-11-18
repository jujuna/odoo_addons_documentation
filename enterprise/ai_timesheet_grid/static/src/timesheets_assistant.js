import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { useDebounced } from "@web/core/utils/timing";
import { TimesheetsAssistant } from "@timesheet_grid/components/aw_timesheet/aw_timesheet";

patch(TimesheetsAssistant.prototype, {
    setup() {
        super.setup();
        this.debouncedUpdateDescription = useDebounced(
            this._updateDescriptionWithAI.bind(this),
            800
        );
    },

    /**
     * One line per selected activity, prefixed with its category (the rule/event
     * type also used for the icon), so the AI knows e.g. that a title is a
     * presentation and not a piece of development work.
     */
    _getActivitiesForAI() {
        return this.getSelectedRecords(Array.from(this.state.selectedRows))
            .map(({ type, title }) => {
                const category = type === "gmail_activity" ? "email" : type || "other";
                return `- [${category}] ${title}`;
            })
            .join("\n");
    },

    async _updateDescriptionWithAI(name) {
        let description = name;
        try {
            const summary = await rpc("/ai/get_direct_response", {
                interface_key: "timesheet_assistant_ai",
                prompt:
                    "Summarize the following timesheet activities into one short description. " +
                    "Each activity is prefixed with its category in brackets " +
                    "(e.g. development, presentation, messaging, meeting, email, odoo). " +
                    "Use the categories to understand what kind of work each activity was, " +
                    "and do not attribute an activity to a different category. " +
                    "Return only the summary.\n\n" +
                    this._getActivitiesForAI(),
            });
            description = summary?.trim() || name;
            this.currentRecord.update({ name: description });
        } catch {}
    },

    /** @override */
    async updateRecordInForm() {
        await super.updateRecordInForm();
        if (!this.model.isAgentAvailable || this.state.selectedRows.size < 2 || !this.currentRecord) {
            return;
        }
        this.debouncedUpdateDescription(this.selectedData.name);
    },
});
