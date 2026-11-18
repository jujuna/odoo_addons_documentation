import {
    Component,
    computed,
    markup,
    onWillStart,
    onMounted,
    onWillUnmount,
    onPatched,
    proxy,
    signal,
    t,
    usePlugin,
    useProps,
} from "@odoo/owl";
import { useDebounced } from "@web/core/utils/timing";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { Dialog } from "@web/core/dialog/dialog";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatList } from "@web/core/l10n/utils";
import { pyToJsLocale } from "@web/core/l10n/utils/locales";
import { KeepLast, Mutex } from "@web/core/utils/concurrency";
import { TimesheetInlineForm } from "@timesheet_grid/components/timesheet_inline_form/timesheet_inline_form";
import { user } from "@web/core/user";
import { searchHighlight } from "@mail/core/common/message_search_hook";
import { formatDurationTimesheet, roundTimeSpent } from "@timesheet_grid/utils/timer";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { DocumentationLink } from "@web/views/widgets/documentation_link/documentation_link";
import { DebugModePlugin } from "@web/core/debug_mode_plugin";
import { FakeEventsPlugin } from "./fake_events_plugin";
import { useSuggestionsDraggable } from "@timesheet_grid/hooks/use_aw_suggestions_draggable";
import { TimesheetAssistantModel } from "./aw_timesheet_model";
import { TimesheetsAssistantTimeline } from "./timeline/timeline";
import { TimesheetsAssistantByProject } from "./by_project/by_project";

const { DateTime } = luxon;

export class TimesheetsAssistant extends Component {
    static components = {
        TimesheetInlineForm,
        Dropdown,
        DropdownItem,
        Dialog,
        DocumentationLink,
        TimesheetsAssistantTimeline,
        TimesheetsAssistantByProject,
    };
    static template = "timesheet_grid.TimesheetsAssistant";

    props = useProps(standardActionServiceProps);

    formatDuration = formatDurationTimesheet;
    suggestionsContentRef = signal.ref();
    timesheetsSectionRef = signal.ref();

    debugMode = usePlugin(DebugModePlugin);
    fakeEvents = usePlugin(FakeEventsPlugin);
    searchInput = signal.ref();

    setup() {
        this.keepLast = new KeepLast();
        this.updateMutex = new Mutex();
        const orm = useService("orm");
        const notification = useService("notification");
        this.notification = notification;
        this.dialog = useService("dialog");
        this.uiService = useService("ui");
        this.model = new TimesheetAssistantModel(
            { orm, notification, fakeEvents: this.fakeEvents },
            DateTime.now().startOf("day"),
            { onBeforeLoad: () => this.resetSelectionState() }
        );
        this.state = proxy({
            groupBy: localStorage.getItem("aw_suggestion_pref") || "timeline",
            showCreateForm: false,
            showAwayTime: localStorage.getItem("show_away_time") !== "false",
            connectionWarningDismissed:
                localStorage.getItem("aw_connection_warning_dismissed") === "true",
            webWatcherWarningDismissed:
                localStorage.getItem("aw_web_watcher_warning_dismissed") === "true",
            selectedRows: new Set(),
            isMouseButtonPressed: false,
            isSelectedRowDirty: false,
            isSelecting: false,
            focusedIndex: -1, // the currently highlighted row
            lastSelectedIndex: -1, // the anchor point for MAJ (Shift) selection
            searchQuery: "",
            dragOverTimesheetId: null,
            isDraggingSuggestions: false,
            pendingUnselect: null,
        });
        this.selectedTimesheet = null;
        this.pendingScrollToTimesheetId = null;

        useSuggestionsDraggable({
            ref: this.suggestionsContentRef,
            elements: ".o_suggestions_suggestion.o_isSelected",
            component: this,
        });

        this._debouncedSearch = useDebounced((val) => this.setSearchQuery(val), 200);
        onWillStart(async () => {
            await this.model.loadAssistantData();
            await this.keepLast.add(this.model.load());
        });

        this._onMouseUp = this.onMouseUp.bind(this);
        this._onMouseDownAll = this.onMouseDownAll.bind(this);
        this._onClickOutsideBound = this.onClickOutside.bind(this);
        this._onKeyDown = this.onKeyDown.bind(this);
        onMounted(() => {
            window.addEventListener("pointerup", this._onMouseUp);
            window.addEventListener("pointercancel", this._onMouseUp);
            window.addEventListener("keydown", this._onKeyDown, { capture: true });
            window.addEventListener("pointerdown", this._onMouseDownAll);
            window.addEventListener("click", this._onClickOutsideBound);
            const savedStep = localStorage.getItem("aw_install_wizard_step");
            if (savedStep === "2") {
                this.openInstallDialog(2);
            }
        });
        onWillUnmount(() => {
            window.removeEventListener("pointerup", this._onMouseUp);
            window.removeEventListener("pointercancel", this._onMouseUp);
            window.removeEventListener("keydown", this._onKeyDown);
            window.removeEventListener("pointerdown", this._onMouseDownAll);
            window.removeEventListener("click", this._onClickOutsideBound);
        });
        onPatched(() => {
            if (this.pendingScrollToTimesheetId !== null) {
                this.scrollToTimesheetForm(this.pendingScrollToTimesheetId);
            }
        });
        this.onTakeDebounced = useDebounced(this.onTake, 200);
    }

    get defaultSelectionState() {
        return {
            selectedRows: new Set(),
            isMouseButtonPressed: false,
            isSelectedRowDirty: false,
            isSelecting: false,
            focusedIndex: -1, // the currently highlighted row
            lastSelectedIndex: -1, // the anchor point for MAJ (Shift) selection
            dragOverTimesheetId: null,
            isDraggingSuggestions: false,
            pendingUnselect: null,
        };
    }

    /**
     * Reloading the model's data (day navigation, reconnect, sample-data generation) always
     * discards any in-progress selection/keyboard-nav state and closes the create form, since
     * the underlying suggestions it points to are about to be rebuilt from scratch. Wired as
     * the model's `onBeforeLoad` hook so it fires regardless of which path triggers a reload.
     */
    resetSelectionState() {
        Object.assign(this.state, this.defaultSelectionState, { showCreateForm: false });
    }

    get selectedRowCount() {
        return this.state.selectedRows.size;
    }

    get suggestionsTotal() {
        return this.model.data.totalDuration;
    }

    onClickOutside(ev) {
        if (ev.target.closest(".modal, .o-overlay-container")) {
            return;
        }
        // the creation form reads the selected rows, so it must not clear them
        if (!ev.target.closest(".o_activitywatch_sync")) {
            this.initSelectedRows();
        }
    }

    setSearchQuery(query) {
        this.state.searchQuery = query;
        // indexes point into the visible records, which the query has just changed
        this.state.focusedIndex = -1;
        this.state.lastSelectedIndex = -1;
    }

    clearSearch() {
        this._debouncedSearch.cancel();
        this.setSearchQuery("");
        this.searchInput()?.focus();
    }

    highlight(text) {
        return searchHighlight(this.state.searchQuery, text);
    }

    get searchFields() {
        return ["title", "project", "task", "description"];
    }

    get activitySearchFields() {
        return ["description"];
    }

    filteredRecords = computed(() => {
        const q = this.state.searchQuery.trim().toLowerCase();
        if (!q) {
            return this.records;
        }
        const fields = this.searchFields;
        return this.records.filter((r) =>
            fields.some((f) => (r[f] || "").toLowerCase().includes(q))
        );
    });

    filteredGrouped = computed(() => {
        const q = this.state.searchQuery.trim().toLowerCase();
        if (!q) {
            return this.model.data.grouped;
        }

        const activityFields = this.activitySearchFields;
        const result = {};

        for (const [groupKey, groupData] of Object.entries(this.model.data.grouped)) {
            const { project_id, task_id } = JSON.parse(groupKey);
            const projectName = (this.model.projectName(project_id) || "").toLowerCase();
            const taskName = (this.model.taskName(task_id) || "").toLowerCase();
            if (projectName.includes(q) || taskName.includes(q)) {
                result[groupKey] = groupData;
                continue;
            }

            for (const [title, activity] of Object.entries(groupData.suggestions)) {
                const activityMatch =
                    title.toLowerCase().includes(q) ||
                    activityFields.some((f) => (activity[f] || "").toLowerCase().includes(q));
                if (activityMatch) {
                    result[groupKey] ??= { ...groupData, suggestions: {} };
                    result[groupKey].suggestions[title] = activity;
                }
            }
        }
        return result;
    });

    onDateChange(ev) {
        this.model.data.currentDate = DateTime.fromISO(ev.target.value);
        this.model.fetchData();
    }

    navigateToDay(diff) {
        this.model.data.currentDate = this.model.data.currentDate.plus({ days: diff });
        this.model.fetchData();
    }

    navigateToToday() {
        this.model.data.currentDate = DateTime.now().startOf("day");
        this.model.fetchData();
    }

    get dayHeader() {
        const locale = pyToJsLocale(document.documentElement.getAttribute("lang")) || "en-US";
        const options = {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
        };
        return new Intl.DateTimeFormat(locale, options).format(this.model.data.currentDate);
    }

    get noSuggestionsText() {
        if (this.model.isToday) {
            return _t("No suggestions for %(boldStart)sToday%(boldEnd)s.", {
                boldStart: markup`<b>`,
                boldEnd: markup`</b>`,
            });
        } else {
            return _t("No suggestions for %(boldStart)s%(day)s%(boldEnd)s.", {
                boldStart: markup`<b>`,
                boldEnd: markup`</b>`,
                day: this.dayHeader,
            });
        }
    }

    keyFor(groupKey, title, start = false) {
        let key = null;
        if (this.state.groupBy === "timeline") {
            key = this.model.data.recordsByStart?.[start]?.key || null;
        } else {
            key = this.model.data.grouped[groupKey]?.suggestions?.[title]?.key || null;
        }
        const res = {
            groupKey,
            title,
            key,
        };
        if (this.state.groupBy === "timeline") {
            res.start = start;
        }
        return JSON.stringify(res);
    }

    disableTextSelection() {
        document.body.style.userSelect = "none";
    }

    enableTextSelection() {
        document.body.style.userSelect = "";
    }

    isSelected(groupKey, title, start = false) {
        return this.state.selectedRows.has(this.keyFor(groupKey, title, start));
    }

    isSameRecord(record, groupKey, title, start = false) {
        if (this.state.groupBy === "timeline") {
            return record.start === start;
        }
        return record.groupKey === groupKey && record.title === title;
    }

    get records() {
        return Object.values(this.model.data.recordsByStart).filter((record) =>
            this.model.isVisible(record)
        );
    }

    visualRecords = computed(() => {
        if (this.state.groupBy === "project") {
            const grouped = this.filteredGrouped();
            return Object.keys(grouped)
                .sort()
                .flatMap((groupKey) =>
                    Object.values(grouped[groupKey].suggestions).map((item) => ({
                        ...item,
                        groupKey: groupKey,
                    }))
                )
                .filter((a) => a.type !== "afk" && this.model.isVisible(a));
        }
        return this.filteredRecords();
    });

    /**
     * @param {KeyboardEvent} ev
     */
    onKeyDown(ev) {
        if (ev.key === "Escape") {
            this.dismissAllForms();
            if (document.activeElement) {
                document.activeElement.blur();
            }
            return;
        }
        if (
            ev.target.closest(".o_timesheet_inline_form,.o_dialog,.modal") ||
            ["INPUT", "TEXTAREA"].includes(ev.target.tagName) ||
            ev.target.isContentEditable ||
            !this.visualRecords().length
        ) {
            return;
        }
        // Arrows: move focus | Space: toggle selection (sets anchor)
        // Shift + Arrows: select continuous range from anchor to focus
        // Esc: discard all selections and close form
        const records = this.visualRecords();

        if (ev.key === " " || ev.key === "Enter") {
            if (ev.target.classList.contains("o_suggestions_suggestion")) {
                ev.preventDefault();
            }
            if (ev.key === "Enter") {
                if (this.state.selectedRows.size > 0 && !this.state.showCreateForm) {
                    this.state.showCreateForm = true;
                }
                return;
            }
            if (this.state.focusedIndex !== -1) {
                const record = records[this.state.focusedIndex];
                this.state.lastSelectedIndex = this.state.focusedIndex;
                this.toggleSelect(record.groupKey, record.title, false, record.start);
            }
            return;
        } else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
            ev.preventDefault();
            let newIndex = this.state.focusedIndex;

            if (ev.key === "ArrowDown") {
                newIndex = Math.min(records.length - 1, newIndex + 1);
            } else if (ev.key === "ArrowUp") {
                newIndex = Math.max(0, newIndex === -1 ? records.length - 1 : newIndex - 1);
            }
            if (newIndex !== this.state.focusedIndex) {
                if (!ev.shiftKey) {
                    this.state.focusedIndex = newIndex;
                    this.state.lastSelectedIndex = newIndex;
                } else {
                    const fallbackAnchor =
                        this.state.focusedIndex !== -1 ? this.state.focusedIndex : 0;
                    const anchor =
                        this.state.lastSelectedIndex === -1
                            ? fallbackAnchor
                            : this.state.lastSelectedIndex;

                    this.state.focusedIndex = newIndex;
                    this.selectRange(anchor, newIndex, false);
                }
                const container = this.suggestionsContentRef();
                if (!container) {
                    return;
                }
                const elements = container.querySelectorAll(".o_suggestions_suggestion");
                const element = elements[newIndex];
                if (!element) {
                    return;
                }
                element.focus({ preventScroll: true });
                element.scrollIntoView({ block: "nearest", behavior: "auto" });
            }
        }
    }

    selectRange(startIndex, endIndex, autoOpenForm = true) {
        this.clearSelectedTimesheet();
        const records = this.visualRecords();
        const start = Math.min(startIndex, endIndex);
        const end = Math.max(startIndex, endIndex);
        for (let i = start; i <= end; i++) {
            const record = records[i];
            const key = this.keyFor(record.groupKey, record.title, record.start);
            this.state.selectedRows.add(key);
        }
        if (this.state.selectedRows.size > 0) {
            if (autoOpenForm) {
                this.state.showCreateForm = true;
            }
            if (this.currentRecord) {
                this.updateRecordInForm();
            }
        } else {
            this.state.showCreateForm = false;
        }
    }

    getSelectionClass(groupKey, title, previousWasSelected, start = false) {
        let cssClasses = "";
        const isSelected = this.isSelected(groupKey, title, start);
        if (isSelected) {
            cssClasses = previousWasSelected
                ? "o_isSelected border-top-0 border border-info z-1"
                : "o_isSelected border border-info z-1";
        } else {
            cssClasses = "bg-view";
        }
        const records = this.visualRecords();
        if (this.state.focusedIndex !== -1 && records[this.state.focusedIndex]) {
            const focusedRecord = records[this.state.focusedIndex];
            if (this.isSameRecord(focusedRecord, groupKey, title, start)) {
                if (!isSelected) {
                    cssClasses = cssClasses.replace("bg-view", "o_keyboard_focused");
                } else {
                    cssClasses += " o_keyboard_focused";
                }
            }
        }
        return cssClasses;
    }

    onMouseDown(groupKey, title, ev, start = false) {
        this.state.isMouseButtonPressed = true;

        if (ev && ev.button !== 0) {
            return;
        }

        if (ev?.target.closest(".btn")) {
            return; // click on Take/Delete btns
        }
        this.disableTextSelection();
        this.state.isSelecting = true;
        const key = this.keyFor(groupKey, title, start);
        if (this.state.selectedRows.has(key)) {
            this.state.pendingUnselect = { groupKey, title, start };
            return;
        }

        const records = this.visualRecords();
        const clickedIndex = records.findIndex((r) => this.isSameRecord(r, groupKey, title, start));
        if (ev?.shiftKey && this.state.lastSelectedIndex !== -1) {
            this.selectRange(this.state.lastSelectedIndex, clickedIndex);
            this.state.focusedIndex = clickedIndex;
        } else {
            this.state.focusedIndex = clickedIndex;
            this.state.lastSelectedIndex = clickedIndex;
            this.toggleSelect(groupKey, title, true, start);
        }
    }

    onMouseEnter(groupKey, title, start = false) {
        if (this.state.isDraggingSuggestions) {
            return;
        }
        /*
        When hovering over suggestion with the mouse button pressed, the new suggestions are not added to the form
        directly. Their data is first stored inside the state.selectRow, then once the user release the mouse button
        the update is done. This way only one update is triggered for the view form with the batch suggestion. This
        avoids overloading the server since we have only one update per batch selection instead of one update per hover.
        */
        if (this.state.isMouseButtonPressed) {
            if (this.state.selectedRows.size === 0) {
                this.onMouseDown(groupKey, title, undefined, start);
            } else {
                this.clearSelectedTimesheet();
                const key = this.keyFor(groupKey, title, start);
                if (this.state.selectedRows.has(key)) {
                    this.state.selectedRows.delete(key);
                    if (this.state.selectedRows.size === 0) {
                        this.dismissAllForms();
                        this.state.isSelectedRowDirty = false;
                    }
                } else {
                    this.state.selectedRows.add(key);
                    this.state.isSelectedRowDirty = true;
                }
            }
            return;
        }
        if (!(this.state.isSelecting && this.state.selectedTimesheet)) {
            return;
        }
        this.clearSelectedTimesheet();
        const key = this.keyFor(groupKey, title, start);
        if (!this.state.selectedRows.has(key)) {
            this.state.selectedRows.add(key);
        }
    }

    onMouseDownAll() {
        this.state.isMouseButtonPressed = true;
    }

    onMouseUp() {
        if (this.state.pendingUnselect && !this.state.isDraggingSuggestions) {
            const { groupKey, title, start } = this.state.pendingUnselect;
            this.toggleSelect(groupKey, title, true, start);
        }
        this.state.pendingUnselect = null;

        if (this.state.isSelectedRowDirty) {
            this.state.isSelectedRowDirty = false;
            this.updateRecordInForm();
        }
        this.state.isMouseButtonPressed = false;
        this.state.isSelecting = false;
        this.enableTextSelection();
    }

    toggleSelect(groupKey, title, autoOpenForm = true, start = false) {
        if (!this.selectedTimesheet) {
            this.clearSelectedTimesheet();
        }

        const key = this.keyFor(groupKey, title, start);
        if (this.state.selectedRows.has(key)) {
            this.state.selectedRows.delete(key);
            if (this.state.selectedRows.size === 0 && !this.selectedTimesheet) {
                this.state.showCreateForm = false;
            } else {
                this.updateRecordInForm();
            }
        } else {
            this.state.selectedRows.add(key);
            if (autoOpenForm && !this.state.showCreateForm && !this.selectedTimesheet) {
                this.state.showCreateForm = true;
            } else if (this.currentRecord) {
                this.updateRecordInForm();
            }
        }
    }

    async updateEditedTimesheetDuration(record, addedMinutes) {
        if (record !== this.currentRecord || !this.selectedTimesheet) {
            return;
        }

        const currentAmount = record.data.unit_amount || 0;
        let formState = this.suggestionFormState;

        if (!formState || formState.record !== record) {
            formState = this.suggestionFormState = {
                record,
                baseAmount: currentAmount,
                lastAmount: currentAmount,
            };
        }

        const baseAmount = formState.baseAmount + currentAmount - formState.lastAmount;

        const unitAmount =
            addedMinutes > 0
                ? roundTimeSpent({
                      minutesSpent: baseAmount * 60 + addedMinutes,
                      ...this.model.roundingValues,
                  }) / 60
                : baseAmount;

        await record.update({ unit_amount: unitAmount });

        formState.baseAmount = baseAmount;
        formState.lastAmount = record.data.unit_amount;
    }

    updateRecordInForm() {
        const record = this.currentRecord;
        if (!record) {
            return;
        }

        if (this.selectedTimesheet) {
            const addedMinutes = this.model.getSelectedSuggestionsDuration(
                this.state.selectedRows,
                this.state.groupBy
            );
            return this.updateMutex.exec(() =>
                this.updateEditedTimesheetDuration(record, addedMinutes)
            );
        }

        const selectedData = this.selectedData;
        const vals = {
            name: selectedData.name,
            unit_amount: selectedData.unit_amount,
        };
        if (selectedData.project_id && this.model.projectById[this.selectedData.project_id]) {
            vals.project_id = {
                id: selectedData.project_id,
                display_name: this.model.projectById[this.selectedData.project_id]?.name,
            };
        }
        if (selectedData.task_id && this.model.taskById[this.selectedData.task_id]) {
            vals.task_id = {
                id: selectedData.task_id,
                display_name: this.model.taskById[this.selectedData.task_id],
            };
        }
        record.update(vals);
    }

    onDragSuggestion() {
        this.state.isDraggingSuggestions = true;
        this.clearSelectedTimesheet();
    }

    async onDropSuggestions(dragOverTimesheetId) {
        if (!dragOverTimesheetId || this.state.selectedRows.size === 0) {
            return;
        }

        const timesheet = this.model.getTimesheets().find((t) => t.id === dragOverTimesheetId);
        if (timesheet) {
            await this._mergeSuggestionsIntoTimesheet(timesheet);
        }
    }

    async _mergeSuggestionsIntoTimesheet(timesheet) {
        const undoData = await this.model.mergeSuggestionsIntoTimesheet(
            timesheet,
            new Set(this.state.selectedRows),
            this.state.groupBy
        );
        if (!undoData) {
            return;
        }

        this.dismissAllForms();

        const closeNotification = this.notification.add(_t("Time added"), {
            type: "success",
            buttons: [
                {
                    name: _t("Undo"),
                    onClick: () => {
                        closeNotification();
                        return this.undoAddedTime(undoData);
                    },
                },
            ],
            autocloseDelay: 5000,
        });
    }

    async undoAddedTime(undoData) {
        if (!(await this.model.undoAddedTime(undoData))) {
            return;
        }
        this.initSelectedRows();
        this.notification.add(_t("Time removed"), { type: "success" });
    }

    initSelectedRows() {
        this.state.selectedRows = new Set();
        this.state.focusedIndex = -1;
        this.state.lastSelectedIndex = -1;
    }

    getGroupedNames(selectedRows) {
        if (!selectedRows.length) {
            return "";
        }
        const selectedRecords = this.getSelectedRecords(selectedRows);
        const groupedRecords = Map.groupBy(
            selectedRecords,
            ({ template, description, title }) => description || template || title
        );
        const groupNames = [];
        for (const [pattern, records] of groupedRecords) {
            const recordsWithMatches = records.filter(({ matches }) => matches);
            let groupName = pattern;
            for (let i = 1; i < (recordsWithMatches[0]?.matches.length ?? 0); i++) {
                const values = [
                    ...new Set(recordsWithMatches.map(({ matches }) => matches[i])),
                ].filter(Boolean);
                groupName = groupName.replace(`$${i}`, formatList(values));
            }
            groupNames.push(groupName);
        }
        return groupNames.join("; ");
    }

    getSelectedRecords(selectedRows) {
        return selectedRows
            .map((row) => {
                const { groupKey, title, start } = JSON.parse(row);
                if (this.state.groupBy === "timeline") {
                    return this.model.data.recordsByStart[start];
                }
                return this.model.data.grouped[groupKey]?.suggestions?.[title];
            })
            .filter(Boolean);
    }

    get selectedData() {
        if (this.selectedTimesheet) {
            return this.selectedTimesheet;
        }

        let project_id = this.model._getResId(this.currentRecord?.data?.project_id);
        let task_id = this.model._getResId(this.currentRecord?.data?.task_id);
        let totalAmount = 0.0;

        for (const row of this.state.selectedRows) {
            const { groupKey, title, start } = JSON.parse(row);
            const params = this.model.getSuggestionParams(
                groupKey,
                title,
                start,
                this.state.groupBy
            );

            if (!project_id && params.project_id) {
                project_id = params.project_id;
            }
            if (!task_id && params.task_id && params.project_id === project_id) {
                task_id = params.task_id;
            }

            totalAmount += params.unit_amount;
        }

        const name = this.getGroupedNames(Array.from(this.state.selectedRows));
        const roundedAmount =
            roundTimeSpent({
                minutesSpent: totalAmount,
                ...this.model.roundingValues,
            }) / 60;

        return {
            project_id,
            task_id,
            name,
            unit_amount: roundedAmount,
            date: this.model.data.currentDate.toISO().split("T")[0],
            user_id: user.userId,
        };
    }

    get context() {
        const context = {};
        if (!this.selectedTimesheet && this.selectedData) {
            for (const [key, value] of Object.entries(this.selectedData)) {
                context[`default_${key}`] = value;
            }
        }
        return context;
    }

    onShowCreateForm() {
        this.dismissAllForms();
        this.state.showCreateForm = true;
    }

    async onTake(groupKey, title, start = false) {
        return this.model.onTake(groupKey, title, start, this.state.groupBy);
    }

    onDelete(
        groupKey,
        title,
        refresh = true,
        isConsumed = false,
        start = false,
        timesheetId = false
    ) {
        return this.model.onDelete(
            groupKey,
            title,
            refresh,
            isConsumed,
            start,
            this.state.groupBy,
            timesheetId
        );
    }

    onDeleteSelected() {
        this.state.selectedRows.forEach((row) => {
            const { groupKey, title, start } = JSON.parse(row);
            this.onDelete(groupKey, title, true, false, start);
        });
        this.dismissAllForms();
        this.initSelectedRows();
    }

    onSaveTimesheetForm(timesheet) {
        const localConfigVals = this.model.getLocalConfigValsOnTake(timesheet.data);
        for (const row of this.state.selectedRows) {
            const { groupKey, title, start } = JSON.parse(row);
            const matchKey = this.model.getMatchKey(groupKey, title, start, this.state.groupBy);
            this.onDelete(groupKey, title, false, true, start, timesheet.data.id);

            this.model.frequencyViewerLocalConfig.addMatching(matchKey, localConfigVals);
        }

        this.model.addTimesheet(timesheet.data);
        this.dismissAllForms();
    }

    onDeleteTimesheet(timesheetId) {
        this.model.removeTimesheet(timesheetId);
        this.dismissAllForms();
    }

    onClickExistingTimesheet(timesheet) {
        // If suggestions are selected, clicking instantly merges them
        if (this.state.selectedRows.size > 0) {
            this._mergeSuggestionsIntoTimesheet(timesheet);
            return;
        }

        // Check if there's a currently selected timesheet with unsaved changes
        if (this.selectedTimesheet && this.currentRecord && this.currentRecord.dirty) {
            this.dialog.add(ConfirmationDialog, {
                body: _t("Do you want to save your changes?"),
                confirmLabel: _t("Save"),
                confirm: async () => {
                    if (await this.currentRecord.save()) {
                        this.onWriteTimesheet(this.currentRecord);
                        this.switchToTimesheet(timesheet);
                    }
                },
                cancel: () => {},
                close: () => {
                    this.switchToTimesheet(timesheet);
                },
            });
            return;
        }

        this.switchToTimesheet(timesheet);
    }

    switchToTimesheet(timesheet) {
        this.dismissAllForms();
        this.selectedTimesheet = timesheet;
        timesheet.showEditForm = true;

        // Mark that we need to scroll to this form when onPatched
        this.pendingScrollToTimesheetId = timesheet.id;
        this.initSelectedRows();
    }

    scrollToTimesheetForm(id) {
        const formEl = document.querySelector(`[data-timesheet-form="${id}"]`);
        if (formEl) {
            formEl.scrollIntoView({
                behavior: "smooth",
                block: "center",
                container: "nearest",
            });
            this.pendingScrollToTimesheetId = null;
        }
    }

    clearSelectedTimesheet() {
        if (this.selectedTimesheet) {
            this.selectedTimesheet.showEditForm = false;
            this.selectedTimesheet = null;
            this.state.isSelecting = false;
        }
        if (!this.state.showCreateForm) {
            this.currentRecord = null;
        }
        this.suggestionFormState = null;
    }

    dismissAllForms() {
        this.state.showCreateForm = false;
        this.state.isSelecting = false;
        this.clearSelectedTimesheet();
        this.initSelectedRows();
    }

    onWriteTimesheet(timesheet) {
        if (this.state.selectedRows.size > 0) {
            // the selected rows are now taken by this timesheet: recompute the suggestions, so
            // that their time is not deducted a second time as manual time of the timesheet, and
            // learn its project/task for them, like when taking them
            const localConfigVals = this.model.getLocalConfigValsOnTake(timesheet.data);
            for (const row of this.state.selectedRows) {
                const { groupKey, title, start } = JSON.parse(row);
                const matchKey = this.model.getMatchKey(groupKey, title, start, this.state.groupBy);
                this.onDelete(groupKey, title, false, true, start, timesheet.data.id);
                this.model.frequencyViewerLocalConfig.addMatching(matchKey, localConfigVals);
            }
            this.model.refreshTimesheetsOnUpdate(timesheet.data);
            this.model.computeSuggestions();
        } else {
            this.model.updateTimesheet(timesheet.data);
        }
        this.dismissAllForms();
    }

    async generateSampleData() {
        return this.model.generateSampleData();
    }

    async onLinkedRecordSaved() {
        const editedTimesheetId = this.selectedTimesheet?.id;
        await this.keepLast.add(this.model.loadTimesheets());
        this.model.computeSuggestions();
        const timesheet = this.model.data.timesheets.find((ts) => ts.id === editedTimesheetId);
        if (timesheet) {
            this.switchToTimesheet(timesheet);
        } else {
            this.clearSelectedTimesheet();
        }
    }

    openInstallDialog(initialStep) {
        const savedStep = localStorage.getItem("aw_install_wizard_step");
        const step = initialStep || (savedStep ? parseInt(savedStep, 10) : 1);
        this.dialog.add(InstallTimesheetAssistantDialog, {
            onInstall: (os) => this.onInstallTimesheetAssistant(os),
            onTestConnection: () => this.testAwConnection(),
            initialStep: step,
        });
    }

    async onInstallTimesheetAssistant(os) {
        let url;
        if (os === "linux_jammy") {
            url = "https://nightly.odoo.com/aw/ubuntu/jammy/activitywatch-odoo-jammy.deb";
        } else if (os === "linux_noble") {
            url = "https://nightly.odoo.com/aw/ubuntu/noble/activitywatch-odoo-noble.deb";
        } else {
            url = "https://nightly.odoo.com/aw/windows/activitywatch-odoo_patched-latest-setup.exe";
        }

        const a = document.createElement("a");
        a.href = url;
        a.download = "";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    openTestConnectionDialog() {
        this.dialog.add(TestConnectionDialog, {
            awServerStatus: this.model.data.awServerStatus,
            onInstall: (os) => this.onInstallTimesheetAssistant(os),
            onTestConnection: () => this.testAwConnection(),
            openAppsOnDeviceDialog: () => this.openAppsOnDeviceDialog(),
            activeProjectName: this.model.data.activeProjectName,
            activeProjectSince: this.model.data.activeProjectSince,
        });
    }

    toggleShowAwayTime() {
        const currentShowAwayTime = this.state.showAwayTime;
        this.state.showAwayTime = !currentShowAwayTime;
        localStorage.setItem("show_away_time", (!currentShowAwayTime).toString());
    }

    onDismissConnectionWarning() {
        this.state.connectionWarningDismissed = true;
        localStorage.setItem("aw_connection_warning_dismissed", "true");
    }

    onDismissWebWatcherWarning() {
        this.state.webWatcherWarningDismissed = true;
        localStorage.setItem("aw_web_watcher_warning_dismissed", "true");
    }

    onGroupByChange(state) {
        this.initSelectedRows();
        this.dismissAllForms();
        this.state.groupBy = state;
        localStorage.setItem("aw_suggestion_pref", state);
    }

    openAppsOnDeviceDialog() {
        this.dialog.add(AppsOnDevicePermissionDialog);
    }

    async testAwConnection() {
        return this.model.testAwConnection();
    }
}

// Dialog Component
class InstallTimesheetAssistantDialog extends Component {
    static template = "timesheet_grid.InstallTimesheetAssistantDialog";
    static components = { CopyButton, Dialog };

    props = useProps({
        close: t.function(),
        onInstall: t.function(),
        onTestConnection: t.function(),
        initialStep: t.number().optional(),
    });

    setup() {
        this.state = proxy({
            showDevList: false,
            step: this.props.initialStep || 1,
        });
    }

    get os() {
        const userAgent = navigator.userAgent || "";
        let platform = navigator.platform || "";

        if (navigator.userAgentData && navigator.userAgentData.platform) {
            platform = navigator.userAgentData.platform;
        }

        platform = platform.toLowerCase();
        if (platform.includes("win") || /windows/i.test(userAgent)) {
            return "windows";
        } else if (
            (platform.includes("linux") || /linux/i.test(userAgent)) &&
            !/android/i.test(userAgent)
        ) {
            return "linux";
        } else if (platform.includes("mac") || /mac/i.test(userAgent)) {
            return "mac";
        } else {
            return "unknown";
        }
    }

    onDevToggle() {
        this.state.showDevList = !this.state.showDevList;
    }

    onInstall(os) {
        this.props.onInstall(os);
    }

    onNext() {
        if (this.state.step < 6) {
            if (this.state.step === 1 && this.os === "windows") {
                this.state.step += 2;
            } else {
                this.state.step++;
            }
            this.saveStep();
        }
    }

    onPrev() {
        if (this.state.step > 1) {
            if (this.state.step === 3 && this.os === "windows") {
                this.state.step -= 2;
            } else {
                this.state.step--;
            }
            this.saveStep();
        }
    }

    saveStep() {
        localStorage.setItem("aw_install_wizard_step", this.state.step.toString());
    }

    onConfigureNow() {
        window.open("http://localhost:5600/#/settings", "_blank");
    }

    onDiscard() {
        if (this.state.step === 6) {
            localStorage.removeItem("aw_install_wizard_step");
        }
        this.props.close();
    }
}

class TestConnectionDialog extends Component {
    static template = "timesheet_grid.TestConnectionDialog";
    static components = { CopyButton, Dialog, DocumentationLink };

    props = useProps({
        close: t.function(),
        awServerStatus: t.string(),
        onInstall: t.function(),
        onTestConnection: t.function(),
        openAppsOnDeviceDialog: t.function(),
        activeProjectName: t.string().optional(),
        activeProjectSince: t.string().optional(),
    });

    get originUrl() {
        return window.location.origin;
    }

    get os() {
        const userAgent = navigator.userAgent || "";
        let platform = navigator.platform || "";

        if (navigator.userAgentData && navigator.userAgentData.platform) {
            platform = navigator.userAgentData.platform;
        }

        platform = platform.toLowerCase();
        if (platform.includes("win") || /windows/i.test(userAgent)) {
            return "windows";
        } else if (
            (platform.includes("linux") || /linux/i.test(userAgent)) &&
            !/android/i.test(userAgent)
        ) {
            return "linux";
        } else if (platform.includes("mac") || /mac/i.test(userAgent)) {
            return "mac";
        } else {
            return "unknown";
        }
    }

    onInstall(os) {
        this.props.onInstall(os);
    }

    onConfigureCORS() {
        window.open("http://localhost:5600/#/settings", "_blank");
    }

    onHelp() {}
}

export class AppsOnDevicePermissionDialog extends Component {
    static template = "timesheet_grid.AppsOnDevicePermissionDialog";
    static components = { Dialog };

    props = useProps({
        close: t.function(),
    });

    setup() {
        this.ui = useService("ui");
    }
}

registry.category("actions").add("hr_timesheet_activitywatch_action", TimesheetsAssistant);
