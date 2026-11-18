import { Component, onWillStart, proxy, t, useOnChange, useProps } from "@odoo/owl";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const RIGHTS = [
    ["perm_read", _t("Read")],
    ["perm_create", _t("Create")],
    ["perm_write", _t("Edit")],
    ["perm_unlink", _t("Delete")],
];
const FIELD_MODES = [
    ["keep", _t("Visible")],
    ["readonly", _t("Read-only")],
    ["hide", _t("Hidden")],
    ["required", _t("Required")],
];
const BUTTON_MODES = [["visible", _t("Visible")], ["hide", _t("Hidden")], ["hide_block", _t("Blocked")]];
const LEVELS = [
    ["full", _t("No extra limit")],
    ["user", _t("No settings menus")],
    ["readonly", _t("Read only")],
    ["none", _t("Blocked")],
];
const RESULT_OPS = [["read", _t("Read")], ["create", _t("Create")], ["write", _t("Edit")], ["unlink", _t("Delete")]];
const NO_EXTRA_FILTER = _t("No extra filter");
const MODEL = "gec.access.profile";
const RESULT_SHOWN = 6;

/** The Records choices with the "all" key shown as what it is: no filter added by the profile. */
function withNoExtraFilter(choices) {
    return choices.map(([key, label]) => [key, key === "all" ? NO_EXTRA_FILTER : label]);
}
const EXPOSURE_CHIPS = {
    unused: ["primary", _t("Unused")],
    shared: ["info", _t("Shared")],
    linked: ["info", _t("Linked")],
    core: ["secondary", _t("Core")],
    blocked: ["success", _t("Blocked")],
};
const ELEMENT_SECTIONS = [
    ["pages", "page", _t("Pages"), _t("This menu's form has no tabs.")],
    ["filters", "filter", _t("Filters"), _t("This menu's search has no filters.")],
    ["views", "view", _t("Views"), _t("This menu has only one view.")],
];

/** Every change is written at once by the server. */
export class MenuPanel extends Component {
    static template = "gec_access_manager.MenuPanel";
    static components = { CheckBox };
    props = useProps({
        panel: t.object(),
        readonly: t.boolean().optional(),
        apply: t.function(),
        openRule: t.function(),
        openGrants: t.function(),
        openRow: t.function(),
        resultUser: t.number(),
        setResultUser: t.function(),
        profileId: t.number(),
        callProfile: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.resultRequest = 0;
        this.state = proxy({
            open: { rights: true }, fieldSearch: "", choices: {}, exposure: null,
            advanced: false, showAll: false, memberResult: null, memberLoading: false,
        });
        this.RIGHTS = RIGHTS;
        this.FIELD_MODES = FIELD_MODES;
        this.BUTTON_MODES = BUTTON_MODES;
        this.LEVELS = LEVELS;
        this.RESULT_OPS = RESULT_OPS;
        onWillStart(() => this.loadChoices());
        onWillStart(() => this.loadExposure());
        onWillStart(() => this.loadMemberResult());
        useOnChange(
            () => [this.props.panel],
            () => {
                this.loadExposure();
            },
            { initialRun: false }
        );
        useOnChange(
            () => [this.props.panel, this.props.resultUser],
            () => {
                this.loadMemberResult();
            },
            { initialRun: false }
        );
    }

    get panel() {
        return this.props.panel;
    }

    get isData() {
        return Boolean(this.panel.model);
    }

    get isBranch() {
        return this.panel.menu.has_children;
    }

    /** The values of "everything below": this menu's own rule, else the inherited one, else full access. */
    get branchValues() {
        return this.panel.rule || this.panel.inherited || {
            perm_read: true, perm_create: true, perm_write: true, perm_unlink: true,
            records: "all", edit_draft_only: false, include_shared: false,
        };
    }

    get branchSource() {
        if (this.panel.rule) {
            return _t("Set on this menu.");
        }
        if (this.panel.inherited) {
            return _t("Copied from %s. Change any box to set this menu separately.", this.panel.inherited.menu);
        }
        return _t("No limits yet. Change any box to limit every screen of this menu.");
    }

    get dataSource() {
        const panel = this.panel;
        if (panel.source === "data") {
            return _t("Set on this data.");
        }
        if (panel.source === "menu") {
            return _t("Copied from the menu settings. Change any box to set these records separately.");
        }
        return _t("No extra limit.");
    }

    get recordChoices() {
        const choices = withNoExtraFilter(this.panel.record_choices);
        const current = this.panel.rights.records;
        if (current === "custom") {
            choices.push(["custom", _t("Custom filter")]);
        } else if (current === "filter") {
            choices.push(["filter", _t("From the menu settings")]);
        }
        return choices;
    }

    get branchRecordChoices() {
        return withNoExtraFilter(Object.entries(this.panel.record_labels));
    }

    get members() {
        return this.panel.members || [];
    }

    get selectedMember() {
        return this.members.find((member) => member.id === this.props.resultUser);
    }

    /** The result for the picked member, else for this profile. Null while it loads the first time (the block stays,
     * with its select); the previous result is kept while a reload is under way. */
    get result() {
        const member = this.selectedMember;
        if (!member) {
            return this.panel.result;
        }
        const loaded = this.state.memberResult;
        return loaded && loaded.userId === member.id && loaded.menuId === this.panel.menu.id ? loaded.result : null;
    }

    /** Fetch the result of the picked member. A slow older reply never replaces a newer one; a refusal puts
     * the block back on this profile's groups, with a notification. */
    async loadMemberResult() {
        const member = this.selectedMember;
        if (!member || !this.panel.result) {
            return;
        }
        const menuId = this.panel.menu.id;
        const request = ++this.resultRequest;
        this.state.memberLoading = true;
        try {
            const result = await this.orm.call(MODEL, "gec_panel_result", [[this.props.profileId], menuId, member.id]);
            if (request === this.resultRequest) {
                this.state.memberResult = { menuId, userId: member.id, result };
            }
        } catch {
            if (request === this.resultRequest) {
                this.notification.add(
                    _t("Could not show the result for %s. Showing this profile's groups instead.", member.name),
                    { type: "warning" }
                );
                this.props.setResultUser(0);
            }
        } finally {
            if (request === this.resultRequest) {
                this.state.memberLoading = false;
            }
        }
    }

    onResultUser(ev) {
        this.props.setResultUser(parseInt(ev.target.value) || 0);
    }

    get resultTitle() {
        const member = this.selectedMember;
        return member ? _t("What %s can do here", member.name) : _t("What this profile's groups allow here");
    }

    get exemptNote() {
        return _t("Not limited: %s is an administrator.", this.selectedMember.name);
    }

    get notAppliedNote() {
        return _t("This profile does not limit %(name)s: %(reason)s.", {
            name: this.selectedMember.name, reason: this.result.not_applied,
        });
    }

    get branchModels() {
        return this.result?.models || [];
    }

    get dataModels() {
        return this.branchModels.filter((item) => item.model === this.panel.model);
    }

    /** The first RESULT_SHOWN models of the result and the rest; models the groups refuse in full come last. */
    get resultRows() {
        const refused = (item) => RESULT_OPS.every(([operation]) => item.ops[operation].source === "group");
        const given = this.branchModels.filter((item) => !refused(item));
        return {
            first: given.slice(0, RESULT_SHOWN),
            rest: [...given.slice(RESULT_SHOWN), ...this.branchModels.filter(refused)],
        };
    }

    get shownModels() {
        const { first, rest } = this.resultRows;
        return this.state.showAll ? [...first, ...rest] : first;
    }

    get moreModelsLabel() {
        return this.state.showAll ? _t("Show fewer") : _t("Show %s more", this.resultRows.rest.length);
    }

    toggleResultRows() {
        this.state.showAll = !this.state.showAll;
    }

    groupGives(models, right) {
        const operation = right.replace("perm_", "");
        return !models.length || models.some((item) => item.ops[operation].source !== "group");
    }

    groupLimits(models) {
        return Boolean(models[0]?.ops.read.filtered);
    }

    resultCell(item, operation) {
        const info = item.ops[operation];
        if (info.allowed) {
            return { icon: "check", color: "text-success", title: "", label: _t("Yes") };
        }
        const titles = {
            group: _t("The groups do not allow this"),
            readonly: _t("Read Only Everywhere is on"),
            row: _t("Limited on the Models tab"),
            menu: _t("Limited by the menu: %s", item.limited_by.join(", ")),
            other: _t("Limited by another profile"),
        };
        const title = titles[info.source] || "";
        return {
            icon: "close",
            color: info.source === "group" ? "text-muted" : "text-danger",
            title,
            label: title ? _t("No: %s", title) : _t("No"),
        };
    }

    takenAway(item) {
        const sources = new Set(Object.values(item.ops).map((info) => info.source));
        const reasons = [];
        if (sources.has("menu")) {
            reasons.push(item.limited_by.join(", "));
        }
        if (sources.has("row")) {
            reasons.push(_t("the Models tab"));
        }
        if (sources.has("readonly")) {
            reasons.push(_t("Read Only Everywhere"));
        }
        if (sources.has("other")) {
            reasons.push(_t("another profile"));
        }
        return reasons.length ? _t("Taken away by: %s", reasons.filter(Boolean).join(", ")) : "";
    }

    recordsLabel(item) {
        const read = item.ops.read;
        const member = Boolean(this.selectedMember);
        if (read.filtered && read.profile_filtered) {
            return member ? _t("Limited by the group and their profiles") : _t("Limited by the group and this profile");
        }
        if (read.filtered) {
            return _t("Limited by the group");
        }
        if (read.profile_filtered) {
            return member ? _t("Limited by their profiles") : _t("Limited by this profile");
        }
        return _t("All records");
    }

    get moreLabel() {
        return _t("and %s more", this.result.more);
    }

    /** The models whose own Models row cancels the limit of the menus above them. */
    get rowNotes() {
        return this.branchModels.filter((item) => item.row_id && item.limited_by.length);
    }

    rowNote(item) {
        return _t("%(name)s has its own settings on the Models tab. Those are used, not the menu settings (%(menus)s).", {
            name: item.name, menus: item.limited_by.join(", "),
        });
    }

    /** Shared models a menu limit stops at: only a menu with children can tick "Also shared data" to reach them. */
    get sharedNotes() {
        const rule = this.panel.rule || this.panel.inherited;
        if (!this.isBranch || !rule || rule.include_shared) {
            return [];
        }
        return this.branchModels.filter((item) => item.shared && !item.limited_by.length);
    }

    sharedNote(item) {
        return _t(
            "Other apps also use %s. Your limits do not affect it unless you tick 'Also shared data'.",
            item.name
        );
    }

    get shownFields() {
        const search = this.state.fieldSearch.trim().toLowerCase();
        const fields = this.panel.fields || [];
        return search ? fields.filter((field) => field.label.toLowerCase().includes(search)) : fields;
    }

    get reports() {
        return (this.panel.print || []).filter((entry) => entry.type === "ir.actions.report");
    }

    get actions() {
        return (this.panel.print || []).filter((entry) => entry.type !== "ir.actions.report");
    }

    get switchItems() {
        return Object.entries(this.panel.switch_labels);
    }

    onFieldSearch(ev) {
        this.state.fieldSearch = ev.target.value;
    }

    count(list, predicate) {
        return (list || []).filter(predicate).length;
    }

    countLabel(count, label) {
        return count ? _t("%(label)s (%(count)s)", { label, count }) : label;
    }

    get sections() {
        const panel = this.panel;
        const switches = Object.keys(panel.switch_labels).filter((flag) => panel.rights[flag]).length;
        return [
            { key: "fields", label: this.countLabel(
                this.count(panel.fields, (field) => field.mode !== "keep"), _t("Fields")) },
            { key: "buttons", label: this.countLabel(
                this.count(panel.buttons, (button) => button.mode !== "visible"), _t("Buttons")) },
            ...ELEMENT_SECTIONS.map(([key, type, label, empty]) => ({
                key, elementType: type, empty,
                label: this.countLabel(
                    this.count(this.elementsOf(type), (element) => element.hidden), label),
            })),
            { key: "print", entries: this.reports, empty: _t("No report for this data."),
              label: this.countLabel(this.count(this.reports, (entry) => entry.hidden), _t("Print")) },
            { key: "actions", entries: this.actions, empty: _t("The Action menu is empty here."),
              label: this.countLabel(this.count(this.actions, (entry) => entry.hidden), _t("Action Menu")) },
            { key: "switches", label: this.countLabel(switches, _t("Switches")) },
        ];
    }

    elementsOf(type) {
        return (this.panel.elements || []).filter((element) => element.element_type === type);
    }

    toggleSection(key) {
        this.state.open[key] = !this.state.open[key];
    }

    toggleAdvanced() {
        this.state.advanced = !this.state.advanced;
    }

    async loadChoices() {
        for (const kind of this.panel.allowed || []) {
            if (!this.state.choices[kind.model]) {
                this.state.choices[kind.model] = await this.orm.searchRead(
                    kind.model, [], ["display_name"], { limit: 500 }
                );
            }
        }
    }

    /** The panel is replaced after every change made here (rights, level), which can change what is exposed. */
    async loadExposure() {
        if (this.panel.hidden) {
            this.state.exposure = await this.orm.call(
                "gec.access.profile", "gec_hidden_exposure", [[this.props.profileId], this.panel.menu.id]
            );
        }
    }

    get exposureModels() {
        return this.state.exposure?.entries[0]?.models || [];
    }

    get exposureUnknown() {
        return (this.state.exposure?.entries[0]?.unknown || []).join(", ");
    }

    get stillReadableBy() {
        return [...new Set(
            this.exposureModels
                .filter((item) => item.status !== "blocked")
                .flatMap((item) => item.still_readable_by)
        )].join(", ");
    }

    get runsAs() {
        return (this.state.exposure?.runs_as || [])
            .map((entry) => `${entry.user} (${entry.jobs.join(", ")})`)
            .join("; ");
    }

    exposureChip(item) {
        const [type, label] = EXPOSURE_CHIPS[item.status];
        return { type, label };
    }

    exposureLines(item) {
        if (item.status === "core") {
            return [_t("Core data: kept open")];
        }
        if (item.status === "blocked") {
            const lines = [
                item.by === "line"
                    ? _t("Blocked")
                    : _t("Blocked by the settings of: %s", item.by_menus.join(", ")),
            ];
            if (item.still_readable_by.length) {
                lines.push(_t("Still readable by: %s", item.still_readable_by.join(", ")));
            }
            return lines;
        }
        const lines = [];
        if (item.also.length) {
            lines.push(_t("Also opened by: %s", item.also.join(", ")));
        }
        if (item.links.length) {
            lines.push(_t("Shown inside: %s", item.links.join(", ")));
        }
        if (item.inherits.length) {
            lines.push(_t("Also blocks: %s", item.inherits.join(", ")));
        }
        return lines.length ? lines : [_t("Not found elsewhere")];
    }

    exposureButton(item) {
        if (item.status === "unused") {
            return _t("Block");
        }
        if (item.status === "shared" || item.status === "linked") {
            return _t("Block anyway");
        }
        return item.status === "blocked" && item.by === "line" ? _t("Unblock") : false;
    }

    confirmExposure(item) {
        const unblock = item.status === "blocked";
        const body = unblock
            ? [_t("Viewing is allowed again. Edit, Create and Delete stay off. Turn them on in 'Limit further'.")]
            : [
                _t("Users of this profile will see an access error wherever these records appear."),
                ...(item.status === "unused" ? [] : this.exposureLines(item)),
                ...(item.lines.length ? [_t("Also blocks: %s", item.lines.join(", "))] : []),
            ];
        this.dialog.add(ConfirmationDialog, {
            title: unblock ? _t("Unblock %s", item.label) : _t("Block %s", item.label),
            size: "md",
            body: body.join("\n"),
            confirmLabel: unblock ? _t("Unblock") : _t("Block"),
            confirmClass: unblock ? "btn-primary" : "btn-danger",
            confirm: () => this.changeExposure(item, unblock),
            cancel: () => {},
            cancelLabel: _t("Cancel"),
        });
    }

    async changeExposure(item, unblock) {
        const exposure = await this.props.callProfile(
            unblock ? "gec_unblock_data" : "gec_block_data", [this.panel.menu.id, [item.model]]
        );
        if (exposure) {
            this.state.exposure = exposure;
        }
    }

    setDataRight(name, value) {
        return this.props.apply({ kind: "data_rights", [name]: value });
    }

    setBranchRight(name, value) {
        return this.props.apply({ kind: "menu_rights", [name]: value });
    }

    onDataRecords(ev) {
        if (["custom", "filter"].includes(ev.target.value)) {
            return;
        }
        return this.props.apply({ kind: "data_rights", records: ev.target.value });
    }

    onBranchRecords(ev) {
        return this.props.apply({ kind: "menu_rights", records: ev.target.value });
    }

    setField(field, mode, condition = field.condition) {
        return this.props.apply({ kind: "field", field: field.name, mode, condition });
    }

    noExportTitle(field) {
        return field.no_export
            ? _t("Left out of exports. Click to include it.")
            : _t("Included in exports. Click to leave it out.");
    }

    setNoExport(field, value) {
        return this.props.apply({
            kind: "field", field: field.name, mode: field.mode, condition: field.condition, no_export: value,
        });
    }

    onFieldCondition(field, ev) {
        if (ev.target.value !== field.condition) {
            return this.setField(field, field.mode, ev.target.value);
        }
    }

    buttonMode(button) {
        return button.mode === "block" ? "hide_block" : button.mode;
    }

    setButton(button, mode) {
        return this.props.apply({
            kind: "button",
            button_type: button.button_type,
            button_name: button.button_name,
            label: button.label,
            mode,
            condition: button.condition,
        });
    }

    setElement(element, shown) {
        return this.props.apply({
            kind: "element",
            element_type: element.element_type,
            element_name: element.element_name,
            label: element.label,
            hidden: !shown,
        });
    }

    setPrint(entry, shown) {
        return this.props.apply({ kind: "print", type: entry.type, id: entry.id, hidden: !shown });
    }

    grantedGroups(grant) {
        return grant.groups.filter((group) => grant.granted_ids.includes(group.id));
    }

    grantedNames(grant) {
        const names = this.grantedGroups(grant).map((group) => group.name);
        return names.length ? names.join(", ") : _t("Nothing extra");
    }

    /** The level a ladder privilege gives here: the highest one granted, the lower ones come with it. */
    ladderLevel(grant) {
        const granted = grant.levels.filter((level) => grant.granted_ids.includes(level.id));
        return granted.length ? granted[granted.length - 1].id : null;
    }

    get lockedTitle() {
        return _t("Locked: you do not have this level, so you cannot give it");
    }

    setGrant(grant, level) {
        if (this.props.readonly || level?.locked || (level?.id ?? null) === this.ladderLevel(grant)) {
            return;
        }
        return this.props.apply({ kind: "grant", privilege_id: grant.privilege_id, group_id: level?.id || false });
    }

    /** A level of a privilege whose levels stand alone (Accounting, Payroll): the others stay. */
    toggleGrant(grant, level, on) {
        if (this.props.readonly || level.locked) {
            return;
        }
        const ids = new Set(grant.granted_ids);
        if (on) {
            ids.add(level.id);
        } else {
            ids.delete(level.id);
        }
        return this.props.apply({ kind: "grant", privilege_id: grant.privilege_id, group_ids: [...ids] });
    }

    setLevel(level) {
        return this.props.apply({ kind: "level", level });
    }

    showMenu() {
        return this.props.apply({ kind: "hide_menu", hidden: false });
    }

    onAddAllowed(kind, ev) {
        const id = parseInt(ev.target.value);
        ev.target.value = "";
        if (id) {
            return this.props.apply({ kind: "allowed", allowed_kind: kind.kind, add: id });
        }
    }

    removeAllowed(kind, record) {
        return this.props.apply({ kind: "allowed", allowed_kind: kind.kind, remove: record.line_id });
    }

    setPerUser(kind, value) {
        return this.props.apply({ kind: "allowed", allowed_kind: kind.kind, per_user: value });
    }

    allowedChoices(kind) {
        const taken = new Set(kind.records.map((record) => record.id));
        return (this.state.choices[kind.model] || []).filter((record) => !taken.has(record.id));
    }
}
