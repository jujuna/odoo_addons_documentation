import { AccountReportController } from "@account_reports/components/account_report/controller";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { _t } from "@web/core/l10n/translation";

/** Adds the section selector and two toggles to the filter bar.
 * The toggles extend filterExtraOptionsData; the selector needs its own markup (inherited template). */
export class GecMarginStatementFilters extends AccountReportFilters {
    static template = "gec_analytic_margin.MarginStatementFilters";

    get filterExtraOptionsData() {
        return {
            ...super.filterExtraOptionsData,
            gec_before_allocation: {
                name: _t("Before Allocation"),
            },
            gec_ladder_first: {
                name: _t("Ladder First"),
            },
        };
    }

    get gecSectionChoices() {
        return this.controller.cachedFilterOptions().gec_section_choices || [];
    }

    get gecSectionName() {
        const chosen = this.gecSectionChoices.find(
            (choice) => choice.id === this.controller.cachedFilterOptions().gec_section_by
        );
        return chosen ? chosen.name : _t("Report");
    }

    async gecSelectSection(sectionId) {
        await this.controller.updateOption("gec_section_by", sectionId);
        await this.applyFilters("gec_section_by");
    }

    get gecSectionRecords() {
        return this.controller.cachedFilterOptions().gec_section_records || [];
    }

    get gecSectionFilter() {
        return this.controller.cachedFilterOptions().gec_section_filter || [];
    }

    gecIsPicked(recordId) {
        return this.gecSectionFilter.includes(recordId);
    }

    get gecPickerName() {
        const picked = this.gecSectionFilter;
        if (!picked.length) {
            return _t("All");
        }
        if (picked.length === 1) {
            const one = this.gecSectionRecords.find((r) => r.id === picked[0]);
            return one ? one.name : _t("1 selected");
        }
        return _t("%s selected", picked.length);
    }

    async gecTogglePick(recordId) {
        const picked = this.gecSectionFilter.filter((id) => id !== recordId);
        if (picked.length === this.gecSectionFilter.length) {
            picked.push(recordId);
        }
        await this.controller.updateOption("gec_section_filter", picked);
        await this.applyFilters("gec_section_filter");
    }

    async gecClearPick() {
        await this.controller.updateOption("gec_section_filter", []);
        await this.applyFilters("gec_section_filter");
    }
}

AccountReportController.registerCustomComponent(GecMarginStatementFilters);
