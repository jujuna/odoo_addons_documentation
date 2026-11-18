import { Component, computed, onMounted, onWillStart, proxy, signal, useProps } from "@odoo/owl";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

const MODEL = "gec.access.profile";
const DEFAULT_ICON = "/web/static/img/default_icon_app.png";

/**
 * Edits a draft of the granted groups and saves only the difference, so what the page does not show,
 * or was saved elsewhere meanwhile, stays. Nothing is saved on leaving: a dirty page asks first.
 */
export class GecAccessGrants extends Component {
    static template = "gec_access_manager.Grants";
    static components = { Layout, CheckBox, SelectMenu };
    static displayName = _t("What they get");
    props = useProps(standardActionServiceProps);
    rootRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.menuService = useService("menu");
        const context = this.props.action.context || {};
        this.profileId = context.active_id || this.props.action.params?.active_id;
        this.focusId = Number(context.gec_focus_privilege_id) || false;
        this.users = [];
        this.exposure = [];
        this.hiddenNobody = false;
        this.data = signal(null);
        this.draft = signal(new Set());
        this.state = proxy({
            search: "",
            extraSearch: "",
            filter: "all",
            open: { other: false, extra: false },
            skipped: [],
            saving: false,
        });

        this.index = computed(() => {
            const index = new Map();
            const data = this.data();
            for (const row of data?.rows || []) {
                for (const level of row.levels) {
                    index.set(level.id, { level, row });
                }
            }
            for (const extra of data?.extras || []) {
                index.set(extra.id, { level: extra, row: null });
            }
            return index;
        });
        this.givenBy = computed(() => {
            const given = new Map();
            for (const id of this.draft()) {
                const level = this.index().get(id)?.level;
                for (const implied of level?.implies || []) {
                    given.set(implied, [...(given.get(implied) || []), this.levelLabel(id)]);
                }
            }
            return given;
        });
        this.changes = computed(() => {
            const granted = new Set(this.data()?.granted_ids);
            const draft = this.draft();
            return {
                add: [...draft].filter((id) => !granted.has(id)),
                remove: [...granted].filter((id) => !draft.has(id)),
            };
        });
        this.dirtyCount = computed(() => this.changes().add.length + this.changes().remove.length);
        this.chips = computed(() => this.computeChips());
        this.view = computed(() => this.computeView());

        onWillStart(async () => {
            this.setData(this.profileId
                ? await this.orm.call(MODEL, "gec_grants_data", [[this.profileId]])
                : { missing: true });
            if (this.missing) {
                return;
            }
            const exposure = await this.orm.call(MODEL, "gec_hidden_exposure", [[this.profileId]]);
            this.exposure = exposure.entries;
            this.hiddenNobody = Boolean(exposure.hidden && !exposure.members);
            if (this.editable) {
                this.users = await this.orm.searchRead("res.users", [["share", "=", false]], ["display_name"], {
                    limit: 500,
                });
            }
            const focused = this.data().rows.find((row) => row.privilege_id === this.focusId);
            if (focused && focused.section !== "seen") {
                this.state.open.other = true;
            }
        });
        onMounted(() => {
            if (this.focusId) {
                this.rootRef()
                    ?.querySelector(`[data-privilege="${this.focusId}"]`)
                    ?.scrollIntoView({ block: "center" });
            }
        });
        useSetupAction({
            beforeLeave: (options) => this.beforeLeave(options),
            beforeUnload: (ev) => this.beforeUnload(ev),
        });
    }

    /**
     * While a save runs, leaving waits for it and goes on only if no unsaved edits remain.
     * Never throws, so navigation cannot get stuck here.
     */
    beforeLeave({ forceLeave } = {}) {
        if (forceLeave) {
            return true;
        }
        if (this.state.saving) {
            return this.savePromise;
        }
        if (!this.dirtyCount()) {
            return true;
        }
        return new Promise((resolve) => {
            try {
                this.dialog.add(
                    ConfirmationDialog,
                    {
                        title: _t("Leave without saving?"),
                        body: _t("You have unsaved changes on this page."),
                        confirmLabel: _t("Discard changes"),
                        confirm: () => resolve(true),
                        cancelLabel: _t("Stay"),
                        cancel: () => resolve(false),
                    },
                    { onClose: () => resolve(false) }
                );
            } catch {
                resolve(true);
            }
        });
    }

    beforeUnload(ev) {
        if (this.dirtyCount()) {
            ev.preventDefault();
            ev.returnValue = "Unsaved changes";
        }
    }

    setData(data) {
        this.data.set(data);
        this.draft.set(new Set(data.granted_ids || []));
        this.state.skipped = [];
    }

    get missing() {
        return Boolean(this.data()?.missing);
    }

    get profile() {
        return this.data()?.profile;
    }

    get editable() {
        return Boolean(this.profile?.editable);
    }

    get n() {
        return this.profile?.n || 0;
    }

    get title() {
        return _t("What %s users get", this.profile.name);
    }

    get membersText() {
        return this.n === 1 ? _t("1 user gets these") : _t("%s users get these", this.n);
    }

    get holdersText() {
        const { direct } = this.profile;
        const names = direct.map((user) => user.name).join(", ");
        return this.n > direct.length ? `${names} (+${this.n - direct.length})` : names;
    }

    get viaGroupsText() {
        return _t(
            "%s more users get this profile through an Odoo group. The limits apply to them, the levels chosen here do not.",
            this.profile.via_groups
        );
    }

    /** One line per hidden menu: how much of its data is still open and how much is blocked. */
    get hiddenEntries() {
        return this.exposure.map((entry) => {
            const count = (status) => entry.models.filter((item) => item.status === status).length;
            const [unused, shared, linked, core, blocked] = ["unused", "shared", "linked", "core", "blocked"].map(count);
            const details = [
                [unused, _t("%s unused", unused)],
                [shared, _t("%s shared", shared)],
                [linked, _t("%s linked", linked)],
                [core, _t("%s core", core)],
            ].filter(([n]) => n).map(([, text]) => text);
            const open = details.length
                ? _t("%(count)s open: %(details)s", {
                    count: unused + shared + linked + core,
                    details: details.join(", "),
                })
                : _t("0 open");
            return { menu: entry.menu, text: `${open} · ${_t("%s blocked", blocked)}` };
        });
    }

    openProfile() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: this.profileId,
            views: [[false, "form"]],
        });
    }

    get userChoices() {
        return this.users.map((user) => ({ value: user.id, label: user.display_name }));
    }

    get userPlaceholder() {
        return _t("Start from a user...");
    }

    get skippedText() {
        return _t("Not copied, because you do not have these yourself: %s.", this.state.skipped.join(", "));
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }

    onExtraSearch(ev) {
        this.state.extraSearch = ev.target.value;
    }

    /** Copies a user's access into the draft as clicks; saves nothing. The server skips what the editor cannot give. */
    async pickUser(userId) {
        const result = await this.orm.call(MODEL, "gec_grants_from_user", [[this.profileId], userId]);
        this.setDraft((draft) => {
            for (const id of result.add) {
                const row = this.index().get(id)?.row;
                for (const level of row?.ladder ? row.levels : []) {
                    draft.delete(level.id);
                }
                draft.add(id);
            }
        });
        this.state.skipped = result.skipped;
    }

    setDraft(mutate) {
        const draft = new Set(this.draft());
        mutate(draft);
        this.draft.set(draft);
    }

    selectedLevel(row) {
        const draft = this.draft();
        let selected = null;
        for (const level of row.levels) {
            if (draft.has(level.id)) {
                selected = level.id;
            }
        }
        return selected;
    }

    chooseLevel(row, level) {
        if (!this.editable || level?.locked) {
            return;
        }
        this.setDraft((draft) => {
            for (const other of row.levels) {
                draft.delete(other.id);
            }
            if (level) {
                draft.add(level.id);
            }
        });
    }

    toggle(row, level, on) {
        if (row?.ladder) {
            return this.chooseLevel(row, on ? level : null);
        }
        if (!this.editable || level.locked) {
            return;
        }
        this.setDraft((draft) => (on ? draft.add(level.id) : draft.delete(level.id)));
    }

    /** Take a granted group the page does not offer out of the draft: saved as a removal. */
    removeOther(id) {
        if (this.editable) {
            this.setDraft((draft) => draft.delete(id));
        }
    }

    discard() {
        this.draft.set(new Set(this.data().granted_ids));
        this.state.skipped = [];
    }

    /**
     * A refused save leaves the draft as it is: the error dialog shows.
     * ``savePromise`` tells beforeLeave whether the save left no unsaved edits.
     */
    async save() {
        if (this.state.saving || !this.dirtyCount()) {
            return;
        }
        this.state.saving = true;
        const { promise, resolve } = Promise.withResolvers();
        this.savePromise = promise;
        let saved = false;
        try {
            const submittedDraft = new Set(this.draft());
            const { add, remove } = this.changes();
            const data = await this.orm.call(MODEL, "gec_grants_save", [[this.profileId], add, remove]);
            // Keep edits made during the request on top of the server's grants, including changes saved elsewhere.
            const added = [...this.draft()].filter((id) => !submittedDraft.has(id));
            const removed = [...submittedDraft].filter((id) => !this.draft().has(id));
            this.setData(data);
            this.setDraft((draft) => {
                for (const id of added) {
                    draft.add(id);
                }
                for (const id of removed) {
                    draft.delete(id);
                }
            });
            this.notification.add(
                this.dirtyCount() ? _t("Saved. Your newer changes are still unsaved.") : _t("Saved"),
                { type: "success" }
            );
            saved = true;
        } finally {
            this.state.saving = false;
            resolve(saved && !this.dirtyCount());
        }
    }

    levelLabel(id) {
        const entry = this.index().get(id);
        if (!entry) {
            return this.data().others.find((group) => group.id === id)?.name || "";
        }
        return entry.row
            ? _t("%(privilege)s: %(levels)s", { privilege: entry.row.name, levels: entry.level.name })
            : entry.level.name;
    }

    get changeLines() {
        const { add, remove } = this.changes();
        const before = new Set(this.data().granted_ids);
        for (const id of this.data().granted_ids) {
            for (const implied of this.index().get(id)?.level.implies || []) {
                before.add(implied);
            }
        }
        const draft = this.draft();
        const included = new Set();
        for (const id of add) {
            const row = this.index().get(id)?.row;
            for (const implied of this.index().get(id)?.level.implies || []) {
                const sameLadder = row?.ladder && this.index().get(implied)?.row === row;
                if (!before.has(implied) && !draft.has(implied) && !sameLadder) {
                    included.add(implied);
                }
            }
        }
        const names = (ids) => [...ids].map((id) => this.levelLabel(id)).join(", ");
        return [
            add.length && _t("New: %s", names(add)),
            remove.length && _t("Removed: %s", names(remove)),
            included.size && _t("Also included: %s", names(included)),
        ].filter(Boolean);
    }

    get dirtyText() {
        const count = this.dirtyCount();
        return count === 1 ? _t("1 unsaved change") : _t("%s unsaved changes", count);
    }

    levelState(row, level) {
        const selected = row?.ladder ? this.selectedLevel(row) === level.id : this.draft().has(level.id);
        const given = selected ? [] : this.givenBy().get(level.id) || [];
        const own = this.n > 0 && level.own_count === this.n;
        const parts = [level.comment];
        if (level.locked) {
            parts.unshift(_t("Locked: you do not have this level, so you cannot give it"));
        }
        if (given.length) {
            parts.push(_t("Given by %s", given.join(", ")));
        }
        if (own) {
            parts.push(_t("All users already have it on their user form"));
        }
        return { selected, given, own, title: parts.filter(Boolean).join("\n") };
    }

    selectedNames(row) {
        const draft = this.draft();
        const selected = row.ladder ? this.selectedLevel(row) : null;
        return row.levels
            .filter((level) => (row.ladder ? level.id === selected : draft.has(level.id)))
            .map((level) => level.name);
    }

    detailLines(row) {
        const draft = this.draft();
        const selected = row.ladder ? this.selectedLevel(row) : null;
        return row.levels
            .filter((level) => (row.ladder ? level.id === selected : draft.has(level.id)))
            .map((level) => {
                const text = this.detailText(level);
                return row.ladder ? text : _t("%(level)s: %(text)s", { level: level.name, text });
            });
    }

    detailText(level) {
        if (level.adds.length) {
            const menus = level.adds.join(", ");
            return level.adds_more
                ? _t("Adds: %(menus)s and %(count)s more", { menus, count: level.adds_more })
                : _t("Adds: %s", menus);
        }
        return level.comment || _t("Changes what users can do in the app's screens");
    }

    opensApp(row) {
        const opening = new Set(row.levels.filter((level) => level.opens_app).map((level) => level.id));
        for (const id of this.draft()) {
            const level = this.index().get(id)?.level;
            if (opening.has(id) || level?.implies.some((other) => opening.has(other))) {
                return true;
            }
        }
        return false;
    }

    /** The badge of a row that opens its app; null for a row only attached to an app. */
    badgeOf(row) {
        if (!row.app?.is_gate || !this.n) {
            return null;
        }
        if (this.opensApp(row)) {
            return { type: "success", text: _t("Opens the app") };
        }
        if (row.open_without >= this.n) {
            return { type: "secondary", text: _t("They already have it") };
        }
        const missing = this.n - (row.open_without || 0);
        return {
            type: "warning",
            text: _t("Not given"),
            title: missing === 1
                ? _t("1 user of this profile cannot open this app")
                : _t("%s users of this profile cannot open this app", missing),
        };
    }

    iconOf(app) {
        if (!app) {
            return null;
        }
        const menu = this.menuService.getMenu(app.menu_id);
        if (menu?.webIconData) {
            return { src: menu.webIconData };
        }
        if (menu?.webIcon) {
            const [name, color] = menu.webIcon.split(",");
            return { name, style: color ? `color: ${color}` : "" };
        }
        return { src: DEFAULT_ICON };
    }

    warningText(row) {
        return _t("%(app)s: users get %(levels)s, but the app is hidden on the Menus & Apps tab", {
            app: row.app.name,
            levels: this.selectedNames(row).join(", "),
        });
    }

    computeChips() {
        const draft = this.draft();
        const data = this.data();
        const chips = [];
        for (const row of data?.rows || []) {
            const names = this.selectedNames(row);
            if (names.length) {
                chips.push(_t("%(privilege)s: %(levels)s", { privilege: row.name, levels: names.join(", ") }));
            }
        }
        for (const extra of data?.extras || []) {
            if (draft.has(extra.id)) {
                chips.push(extra.name);
            }
        }
        for (const other of data?.others || []) {
            if (draft.has(other.id)) {
                chips.push(other.name);
            }
        }
        return chips;
    }

    matches(search, ...texts) {
        return !search || texts.some((text) => (text || "").toLowerCase().includes(search));
    }

    /** The page body: rows granted in a hidden app (the warning block), then the sections to show. */
    computeView() {
        const data = this.data();
        if (!data?.rows) {
            return { warned: [], sections: [], others: [] };
        }
        const draft = this.draft();
        const search = this.state.search.trim().toLowerCase();
        const extraSearch = this.state.extraSearch.trim().toLowerCase();
        const granted = (row) => row.levels.some((level) => draft.has(level.id));
        const filter = this.state.filter;
        const given = this.givenBy();
        const gets = (level) => draft.has(level.id) || given.has(level.id);
        const keep = (row) =>
            filter === "all"
            || (filter === "given" && row.levels.some(gets))
            || (filter === "closed" && this.badgeOf(row)?.type === "warning");
        const rows = data.rows.filter((row) =>
            keep(row) && this.matches(search, row.app?.name, row.name, ...row.levels.map((level) => level.name))
        );
        const seen = rows.filter((row) => row.section === "seen");
        const warned = rows.filter((row) => row.section === "other" && granted(row));
        const other = rows.filter((row) => row.section === "more" || (row.section === "other" && !granted(row)));
        const extras = data.extras.filter(
            (extra) =>
                (filter === "all" || (filter === "given" && gets(extra)))
                && this.matches(search, extra.name)
                && this.matches(extraSearch, extra.name)
        );
        const sections = [];
        if (seen.length) {
            sections.push({
                key: "seen", rows: seen, groups: this.byCategory(seen), collapsible: false,
                title: _t("Apps they see in the menu (%s)", seen.length),
            });
        }
        if (other.length) {
            sections.push({
                key: "other", rows: other, groups: this.byCategory(other), collapsible: true,
                title: _t("Other apps (%s)", other.length),
            });
        }
        if (extras.length || (extraSearch && filter === "all")) {
            sections.push({ key: "extra", extras, collapsible: true, title: _t("Extra rights (%s)", extras.length) });
        }
        return {
            warned,
            sections,
            others: data.others.filter((group) => draft.has(group.id)),
            empty: !seen.length && !warned.length && !other.length && !extras.length,
        };
    }

    /** Consecutive rows of one category, as the user form shows them: the server sends rows in that order. */
    byCategory(rows) {
        const groups = [];
        for (const row of rows) {
            if (groups.at(-1)?.id !== row.category.id) {
                groups.push({ id: row.category.id, name: row.category.name, rows: [] });
            }
            groups.at(-1).rows.push(row);
        }
        return groups;
    }

    get closedCount() {
        return (this.data()?.rows || []).filter((row) => this.badgeOf(row)?.type === "warning").length;
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    isOpen(section) {
        return (
            !section.collapsible
            || this.state.filter !== "all"
            || this.state.open[section.key]
            || Boolean(this.state.search.trim())
            || (section.key === "extra" && Boolean(this.state.extraSearch.trim()))
        );
    }

    toggleSection(key) {
        this.state.open[key] = !this.state.open[key];
    }
}

registry.category("actions").add("gec_access_manager.grants", GecAccessGrants);
