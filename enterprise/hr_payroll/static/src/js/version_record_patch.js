/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { EmployeeFormController } from "@hr/views/form_view";
import { VersionUpdateDialog } from "./version_update_dialog";

    
const PERSONAL_INFORMATION = [
    "country_id", "identification_id", "passport_id", "disabled", "sex",
    "private_street", "private_street2", "private_city", "private_city_id", "private_state_id", "private_zip", "private_country_id", "distance_home_work",
    "other_dependents", "disabled_children_number", "l10n_be_dependent_children_attachment", "other_juniors_dependent", "other_senior_dependent", "other_disabled_juniors_dependent", // Sub field for dependent people
    "marital", "spouse_fiscal_status",  "disabled_spouse_bool", "spouse_complete_name", "spouse_birthdate", "children" // Sub field for Married and Legal Cohabitan
];

const EXCLUDED_FIELDS = ["contract_date_end", "resource_calendar_id", ...PERSONAL_INFORMATION];


patch(EmployeeFormController.prototype, {
    setup() {
        super.setup();
        this.versionChoice = null;
    },
    _isVersionedField(record, fieldName) {
        const isVersioned = Boolean(record.fields[fieldName]?.related?.startsWith("version_id."));
        return (!EXCLUDED_FIELDS.includes(fieldName) && isVersioned);
    },

    async onRecordChanged(record, changes) {
        await super.onRecordChanged(...arguments);

        const modifiedFieldNames = Object.keys(changes || {});
        const hasVersionedChanges = modifiedFieldNames.some((fieldName) => this._isVersionedField(record, fieldName));

        const versionId = record.data.version_id?.id
        if (!record.resId || this.versionChoice || !hasVersionedChanges || !versionId) {
            return;
        }

        const status = await this.orm.call(
            "hr.version",
            "action_check_version_status",
            [[versionId]]
        );

        if (!status.is_last_version || !status.valid_payslips_count) {
            return;
        }

        const choice = await new Promise((resolve) => {
            this.dialogService.add(VersionUpdateDialog, {
                payslipsCount: status.valid_payslips_count,
                nextPeriodStart: status.next_period_start,
                currentVersionStart: status.date_start,
                confirm: (selection) => resolve(selection),
                cancel: () => resolve(null),
                close: () => resolve(null),
            });
        });

        if (!choice) {
            record._discard();  // Cancel -> discard the chnages
            return;
        }
        if (choice.mode === "create_new_version") {  // create new version directly without wait to save()

            const filteredChanges = Object.fromEntries(
                Object.entries(changes).filter(([key]) => this._isVersionedField(record, key))
            );

            await this.orm.call(
                "hr.version",
                "action_create_version_from_update",
                [[versionId], choice.dateStart, filteredChanges]
            );

            this.versionChoice = null;

            record.discard();  // Reset the changes on current version
            this.model.load(); // Reload model to point to the newly created version

        } else if (choice.mode === "correct_current_version") {  // save the choice locally and wait to save()
            this.versionChoice = choice;
        }
    },

    async save() {
        const saved = await super.save();
        if (saved) {
            this.versionChoice = null;
        }
        return saved;
    },

    discard() {
        this.versionChoice = null;
        return super.discard(...arguments);
    }
});
