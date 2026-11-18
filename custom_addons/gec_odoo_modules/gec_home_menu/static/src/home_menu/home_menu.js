import { computed, onMounted, onPatched, proxy, useListener } from "@odoo/owl";
import { HomeMenu } from "@web_enterprise/webclient/home_menu/home_menu";
import { hasTouch } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { SIZES } from "@web/core/ui/ui_utils";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { fuzzyLookup } from "@web/core/utils/search";
import { useSortable } from "@web/core/utils/sortable_owl";
import { computeAppsAndMenuItems } from "@web/webclient/menus/menu_helpers";

const TEMPLATE = "gec_home_menu.HomeMenu";
const MAX_RESULTS = 100;
const GROUP_CARDS = ".o_gec_hm_group_card:not(.o_gec_hm_placeholder)";
const TODO_APP_XMLID = "project_todo.menu_todo_todos";

patch(HomeMenu, { template: TEMPLATE });

patch(HomeMenu.prototype, {
    /** Builds the layout state from the saved config before core registers its hotkeys; NULL config reads as false.
     * Customize mode is session-only and starts off; on touch, scrolls to the top, undoing core's 46px scroll. */
    setup() {
        if (this.gecActive) {
            const config = user.settings?.gec_home_menu_config || {};
            this.gecState = proxy({
                query: "",
                customizing: false,
                pinned: Array.isArray(config.pinned) ? [...config.pinned] : [],
                view: config.view === "all" ? "all" : "groups",
                groupOrder: Array.isArray(config.group_order) ? [...config.group_order] : [],
                groupLayout: this.gecCopyLayout(config.group_layout),
            });
        }
        super.setup(...arguments);
        if (this.gecActive) {
            this.store = useService("mail.store");
            this.gecActivityByApp = computed(() => this.gecComputeActivityByApp());
            useSortable({
                enable: () =>
                    this.gecState.customizing &&
                    this.gecState.view === "groups" &&
                    !this.gecState.query.trim(),
                ref: this.rootRef,
                groups: ".o_gec_hm_masonry_col",
                connectGroups: true,
                elements: ".o_gec_hm_group_card",
                handle: ".o_gec_hm_title",
                cursor: "grabbing",
                tolerance: 10,
                touchDelay: 500,
                placeholderClasses: ["o_gec_hm_placeholder"],
                onDragStart: () => (this.gecDragRects = this.gecCardRects()),
                onElementEnter: () => (this.gecDragRects = this.gecAnimateFrom(this.gecDragRects)),
                onGroupEnter: () => (this.gecDragRects = this.gecAnimateFrom(this.gecDragRects)),
                onDrop: (params) => this.gecOnGroupDrop(params),
                onDragEnd: () => (this.gecDragRects = null),
            });
            onPatched(() => {
                if (this.gecPendingRects) {
                    this.gecAnimateFrom(this.gecPendingRects);
                    this.gecPendingRects = null;
                }
            });
            onMounted(() => {
                if (hasTouch()) {
                    this.rootRef().scrollTo(0, 0);
                }
                this.store.fetchStoreData("systray_get_activities");
            });
        }
    },

    /** True when this component renders our template; Studio's StudioHomeMenu has its own: overrides defer to core. */
    get gecActive() {
        return this.constructor.template === TEMPLATE;
    },

    gecAppKey(app) {
        return app.xmlid || String(app.id);
    },

    gecIsPinned(app) {
        return this.gecState.pinned.includes(this.gecAppKey(app));
    },

    get gecSearchPlaceholder() {
        return _t("Search apps and menus...");
    },

    get gecViewToggleTitle() {
        return this.gecState.view === "all" ? _t("Group apps") : _t("Show all apps");
    },

    get gecCustomizeTitle() {
        return this.gecState.customizing ? _t("Done") : _t("Customize");
    },

    get gecDragTitle() {
        return this.gecState.customizing ? _t("Drag to change the order") : false;
    },

    gecPinTitle(app) {
        return this.gecIsPinned(app) ? _t("Unpin") : _t("Pin");
    },

    gecParents(item) {
        return item.parents ? item.parents.split(" / ") : [];
    },

    gecCategoryOf(app) {
        return this.menus.getMenu(app.id)?.gecCategory || null;
    },

    gecAppOf(item) {
        return this.props.apps.find((app) => app.id === item.appID);
    },

    /** Activity counts per app menu id: today and overdue, from groups tagged with `gec_app_id`.
     * `is_todo` groups count on the To-Do app when the user sees it; untagged groups belong to no app. */
    gecComputeActivityByApp() {
        const todoApp = this.props.apps.find((app) => app.xmlid === TODO_APP_XMLID);
        const counts = new Map();
        for (const group of this.store.activityGroups) {
            const appId = (group.is_todo && todoApp?.id) || group.gec_app_id;
            if (!appId) {
                continue;
            }
            const count = counts.get(appId) || { today: 0, overdue: 0 };
            count.today += group.today_count;
            count.overdue += group.overdue_count;
            counts.set(appId, count);
        }
        return counts;
    },

    /** Badge of one app tile: activities due today or overdue and a tooltip, or null when none. */
    gecAppBadge(app) {
        const count = this.gecActivityByApp().get(app.id);
        if (!count || !(count.today + count.overdue)) {
            return null;
        }
        return {
            total: count.today + count.overdue,
            overdue: count.overdue,
            title: _t("%(today)s due today, %(overdue)s overdue", {
                today: count.today,
                overdue: count.overdue,
            }),
        };
    },

    /** English breadcrumb of every menu id ("App / Menu / Sub menu", root left out), from `gecNameEn`. */
    gecEnglishBreadcrumbs() {
        const breadcrumbs = new Map();
        const walk = (menu, names) => {
            const path = [...names, menu.gecNameEn || menu.name];
            breadcrumbs.set(menu.id, path.join(" / "));
            menu.childrenTree.forEach((child) => walk(child, path));
        };
        this.menus.getMenuAsTree("root").childrenTree.forEach((app) => walk(app, []));
        return breadcrumbs;
    },

    /** Turns Customize mode on or off; card rects are kept first so onPatched slides the cards. */
    gecToggleCustomize() {
        this.gecPendingRects = this.gecCardRects();
        this.gecState.customizing = !this.gecState.customizing;
    },

    /** Splits groups into masonry columns (3 from XL, 2 from MD, else 1): the saved layout for that count first,
     * others to the shortest column (ties: leftmost). Tab follows the DOM; arrows follow the reading order. */
    gecMasonryColumns(groups) {
        const count = this.ui.size >= SIZES.XL ? 3 : this.ui.size >= SIZES.MD ? 2 : 1;
        const columns = Array.from({ length: count }, () => []);
        const heights = new Array(count).fill(0);
        const unplaced = new Map(groups.map((group) => [group.key, group]));
        const place = (index, group) => {
            columns[index].push(group);
            heights[index] += 1.2 + Math.ceil(group.apps.length / 3);
            unplaced.delete(group.key);
        };
        const saved = this.gecState.groupLayout[count] || [];
        for (let index = 0; index < count; index++) {
            for (const key of saved[index] || []) {
                if (unplaced.has(key)) {
                    place(index, unplaced.get(key));
                }
            }
        }
        for (const group of [...unplaced.values()]) {
            place(heights.indexOf(Math.min(...heights)), group);
        }
        return columns;
    },

    /** Flattens columns into masonry reading order: row by row across the columns. */
    gecReadingOrder(columns) {
        const rows = Math.max(...columns.map((column) => column.length));
        return Array.from({ length: rows }, (_, row) => columns.map((column) => column[row]))
            .flat()
            .filter(Boolean);
    },

    /** Fresh copy of a saved `group_layout` ({column count: [[group keys] per column]}); other shapes read as none. */
    gecCopyLayout(layout) {
        if (!layout || typeof layout !== "object" || Array.isArray(layout)) {
            return {};
        }
        return Object.fromEntries(
            Object.entries(layout).map(([count, columns]) => [
                count,
                Array.isArray(columns)
                    ? columns.map((column) => (Array.isArray(column) ? [...column] : []))
                    : [],
            ])
        );
    },

    /** Template sections, rebuilt each render. Query: matching apps, then matching menus by app (English names too);
     * no query: pinned apps, then category cards (in `groupOrder`) or the all-apps grid; items get a focus `index`. */
    get gecSections() {
        let index = 0;
        const toItems = (records, kind) =>
            records.map((record) => ({ index: index++, kind, record }));
        const query = this.gecState.query.trim();
        if (query) {
            const apps = fuzzyLookup(query, this.props.apps, (app) => [
                app.label,
                this.menus.getMenu(app.id)?.gecNameEn || app.label,
            ]).slice(0, MAX_RESULTS);
            const { menuItems } = computeAppsAndMenuItems(this.menus.getMenuAsTree("root"));
            const englishBreadcrumbs = this.gecEnglishBreadcrumbs();
            const menus = fuzzyLookup(query, menuItems, (menu) => {
                const breadcrumb = `${menu.parents} / ${menu.label}`;
                const strings = [breadcrumb, breadcrumb.split("/").reverse().join("/")];
                const english = englishBreadcrumbs.get(menu.id);
                if (english && english !== breadcrumb) {
                    strings.push(english, english.split("/").reverse().join("/"));
                }
                return strings;
            }).slice(0, MAX_RESULTS - apps.length);
            const appItems = toItems(apps, "app");
            const menusByApp = new Map();
            for (const menu of menus) {
                if (!menusByApp.has(menu.appID)) {
                    menusByApp.set(menu.appID, []);
                }
                menusByApp.get(menu.appID).push(menu);
            }
            const groups = [...menusByApp].map(([key, records]) => {
                const items = toItems(records, "menu");
                return { key, app: this.gecAppOf(items[0].record), items };
            });
            return [
                { key: "result_apps", kind: "result_apps", items: appItems },
                {
                    key: "result_menus",
                    kind: "result_menus",
                    items: groups.flatMap((group) => group.items),
                    groups,
                },
            ].filter((section) => section.items.length);
        }
        const sections = [];
        const pinned = this.props.apps.filter((app) => this.gecIsPinned(app));
        if (pinned.length) {
            sections.push({
                key: "pinned",
                kind: "pinned",
                title: _t("Pinned apps"),
                items: toItems(pinned, "app"),
            });
        }
        if (this.gecState.view === "all") {
            sections.push({
                key: "all",
                kind: "all",
                title: _t("All apps"),
                items: toItems(this.props.apps, "app"),
            });
        } else {
            const groups = new Map();
            for (const app of this.props.apps) {
                const category = this.gecCategoryOf(app);
                const key = category ? `category_${category.id}` : "other";
                if (!groups.has(key)) {
                    groups.set(key, {
                        key,
                        title: category ? category.name : _t("Other"),
                        sequence: category?.sequence ?? null,
                        apps: [],
                    });
                }
                groups.get(key).apps.push(app);
            }
            const byOrder = (a, b) => {
                if (a.key === "other" || b.key === "other") {
                    return (a.key === "other") - (b.key === "other");
                }
                if ((a.sequence === null) !== (b.sequence === null)) {
                    return a.sequence === null ? 1 : -1;
                }
                return (
                    (a.sequence ?? 0) - (b.sequence ?? 0) ||
                    String(a.title).localeCompare(String(b.title))
                );
            };
            const defaultOrder = [...groups.values()].sort(byOrder);
            const saved = this.gecState.groupOrder;
            const userOrder = defaultOrder
                .filter((group) => saved.includes(group.key))
                .sort((a, b) => saved.indexOf(a.key) - saved.indexOf(b.key));
            const ordered = defaultOrder.map((group) =>
                saved.includes(group.key) ? userOrder.shift() : group
            );
            const columns = this.gecMasonryColumns(ordered);
            const byKey = new Map(
                this.gecReadingOrder(columns).map(({ key, title, apps }) => [
                    key,
                    { key, kind: "group", title, items: toItems(apps, "app") },
                ])
            );
            sections.push({
                key: "groups",
                kind: "groups",
                columns: columns.map((column) => column.map((group) => byKey.get(group.key))),
                items: [...byKey.values()].flatMap((section) => section.items),
            });
        }
        return sections;
    },

    /** Records in the order of their index in gecSections, for our Enter and arrow keys. */
    get displayedApps() {
        if (!this.gecActive) {
            return super.displayedApps;
        }
        return this.gecSections.flatMap((section) => section.items.map((entry) => entry.record));
    },

    /** Registers our keys instead of core's. Arrows move focus only from the search box or body (RTL: right = back).
     * Enter opens the focused entry unless a button or link has focus; Escape clears the query or closes. */
    _registerHotkeys() {
        if (!this.gecActive) {
            return super._registerHotkeys(...arguments);
        }
        const isInputOrBody = (target) => target === this.inputRef() || target === document.body;
        const isCaretFree = (target) =>
            isInputOrBody(target) && (target !== this.inputRef() || !this.inputRef().value);
        const isRtl = () => localization.direction === "rtl";
        const hotkeys = [
            ["ArrowDown", () => this.gecMoveFocus("down"), { isAvailable: isInputOrBody }],
            ["ArrowUp", () => this.gecMoveFocus("up"), { isAvailable: isInputOrBody }],
            [
                "ArrowRight",
                () => this.gecMoveFocus(isRtl() ? "previous" : "next"),
                { isAvailable: isCaretFree },
            ],
            [
                "ArrowLeft",
                () => this.gecMoveFocus(isRtl() ? "next" : "previous"),
                { isAvailable: isCaretFree },
            ],
            ["Enter", () => this.gecOpenFocused(), { isAvailable: isInputOrBody }],
            ["Escape", () => this.gecOnEscape()],
        ];
        for (const [hotkey, callback, options] of hotkeys) {
            useHotkey(hotkey, callback, { allowRepeat: true, ...options });
        }
        useListener(window, "keydown", this._onKeydownFocusInput.bind(this));
    },

    /** Only printable keys reach core, which otherwise steals Tab, Space and Enter from buttons and links. */
    _onKeydownFocusInput(ev) {
        if (this.gecActive) {
            const isPrintable = ev.key?.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey;
            if (!isPrintable || (ev.key === " " && ev.target.closest?.("button, a"))) {
                return;
            }
        }
        return super._onKeydownFocusInput(...arguments);
    },

    /** Moves the focused entry. "next"/"previous" wrap around; "up"/"down" pick the nearest entry above or below. */
    gecMoveFocus(direction) {
        const total = this.displayedApps.length;
        const current = this.state.focusedIndex;
        if (!total) {
            return;
        }
        if (current === null) {
            this.state.focusedIndex = 0;
            return;
        }
        if (direction === "next" || direction === "previous") {
            this.state.focusedIndex = (current + (direction === "next" ? 1 : -1) + total) % total;
            return;
        }
        const elements = [...this.rootRef().querySelectorAll("[data-gec-index]")];
        const fromElement = elements.find((el) => Number(el.dataset.gecIndex) === current);
        if (!fromElement) {
            return;
        }
        const from = fromElement.getBoundingClientRect();
        const fromX = from.left + from.width / 2;
        let best = null;
        let bestScore = Infinity;
        for (const el of elements) {
            const rect = el.getBoundingClientRect();
            const dy = direction === "down" ? rect.top - from.bottom : from.top - rect.bottom;
            if (el === fromElement || dy < -1) {
                continue;
            }
            const score = Math.max(dy, 0) + 2 * Math.abs(rect.left + rect.width / 2 - fromX);
            if (score < bestScore) {
                best = el;
                bestScore = score;
            }
        }
        if (best) {
            this.state.focusedIndex = Number(best.dataset.gecIndex);
        }
    },

    /** Opens the focused entry; with a query and nothing focused, the first result. */
    gecOpenFocused() {
        const index = this.state.focusedIndex ?? (this.gecState.query.trim() ? 0 : null);
        const record = index === null ? null : this.displayedApps[index];
        if (record && this._isAvailable(record)) {
            this._openMenu(record);
        }
    },

    /** Escape clears the search, then leaves Customize mode, then closes the home menu (no-op without an action). */
    gecOnEscape() {
        if (this.gecState.query) {
            this.gecSetQuery("");
        } else if (this.gecState.customizing) {
            this.gecToggleCustomize();
        } else {
            this.homeMenuService.toggle(false);
        }
    },

    gecSetQuery(query) {
        this.gecState.query = query;
        this.state.focusedIndex = null;
        const input = this.inputRef();
        if (input && input.value !== query) {
            input.value = query;
        }
    },

    gecOnInput(ev) {
        this.gecState.query = ev.target.value;
        this.state.focusedIndex = null;
    },

    /** On small screens core registers no hotkeys, so Enter in the search box opens the focused entry here. */
    gecOnInputKeydown(ev) {
        if (this.ui.isSmall && ev.key === "Enter") {
            this.gecOpenFocused();
            ev.preventDefault();
        }
    },

    /** Pins or unpins an app and saves the list, dropping keys of apps the user no longer sees. */
    gecTogglePin(app) {
        const key = this.gecAppKey(app);
        const wasPinned = this.gecIsPinned(app);
        const visibleKeys = new Set(this.props.apps.map((a) => this.gecAppKey(a)));
        const pinned = this.gecState.pinned.filter((k) => visibleKeys.has(k) && k !== key);
        if (!wasPinned) {
            pinned.push(key);
        }
        this.gecState.pinned = pinned;
        this.state.focusedIndex = null;
        this.gecSaveConfig();
    },

    gecToggleView() {
        this.gecState.view = this.gecState.view === "all" ? "groups" : "all";
        this.state.focusedIndex = null;
        this.gecSaveConfig();
    },

    /** Rects of the category cards by group key, without the drag placeholder (a clone with the same key). */
    gecCardRects() {
        const rects = new Map();
        for (const card of this.rootRef().querySelectorAll(GROUP_CARDS)) {
            rects.set(card.dataset.gecGroup, card.getBoundingClientRect());
        }
        return rects;
    },

    /** Slides every card from its old place to its new rect (FLIP), skipping the dragged card and under reduced motion.
     * Returns the new rects for the next `oldRects`. */
    gecAnimateFrom(oldRects) {
        const cards = [...this.rootRef().querySelectorAll(GROUP_CARDS)];
        const offsets = new Map();
        for (const card of cards) {
            const transform = getComputedStyle(card).transform;
            const matrix =
                transform && transform !== "none" ? new DOMMatrixReadOnly(transform) : null;
            offsets.set(card, [matrix?.m41 || 0, matrix?.m42 || 0]);
            card.getAnimations()
                .filter((animation) => !(animation instanceof CSSTransition))
                .forEach((animation) => animation.cancel());
        }
        const rects = this.gecCardRects();
        const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        for (const card of cards) {
            const old = oldRects?.get(card.dataset.gecGroup);
            const rect = rects.get(card.dataset.gecGroup);
            const [offsetX, offsetY] = offsets.get(card);
            const dx = old ? old.left + offsetX - rect.left : 0;
            const dy = old ? old.top + offsetY - rect.top : 0;
            if (reduceMotion || card.classList.contains("o_dragged") || (!dx && !dy)) {
                this.gecRestorePointer(card);
            } else {
                this.gecSlide(card, dx, dy);
            }
        }
        return rects;
    },

    /** Slides one card from an offset back to its place, ignoring the pointer meanwhile so the drop spot stays put.
     * Restores the inline value core set for the drag when it ends. */
    gecSlide(card, dx, dy) {
        if (!("gecPointerEvents" in card.dataset)) {
            card.dataset.gecPointerEvents = card.style.pointerEvents;
        }
        card.style.pointerEvents = "none";
        const animation = card.animate(
            [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
            { duration: 200, easing: "cubic-bezier(.2, .8, .2, 1)" }
        );
        animation.onfinish = () => this.gecRestorePointer(card);
    },

    gecRestorePointer(card) {
        if ("gecPointerEvents" in card.dataset) {
            card.style.pointerEvents = card.dataset.gecPointerEvents;
            delete card.dataset.gecPointerEvents;
        }
    },

    /** After a card drop, saves the arrangement as the layout for the current column count;
     * group_order gets its reading-order flattening for other counts. Rects are kept first so onPatched can slide. */
    gecOnGroupDrop({ element, previous, parent }) {
        if (!parent) {
            return;
        }
        this.gecPendingRects = this.gecCardRects();
        const key = element.dataset.gecGroup;
        const { columns } = this.gecSections.find((section) => section.kind === "groups");
        const layout = columns.map((column) =>
            column.map((section) => section.key).filter((groupKey) => groupKey !== key)
        );
        const target = layout[Number(parent.dataset.gecCol)];
        target.splice(target.indexOf(previous?.dataset.gecGroup) + 1, 0, key);
        this.gecState.groupLayout = { ...this.gecState.groupLayout, [layout.length]: layout };
        this.gecState.groupOrder = this.gecReadingOrder(layout);
        this.state.focusedIndex = null;
        this.gecSaveConfig();
    },

    /** Saves pinned apps, view, card order and layout in one write, with fresh objects so user.settings is not mutated.
     * Last write wins across tabs. */
    gecSaveConfig() {
        return user.setUserSettings("gec_home_menu_config", {
            pinned: [...this.gecState.pinned],
            view: this.gecState.view,
            group_order: [...this.gecState.groupOrder],
            group_layout: this.gecCopyLayout(this.gecState.groupLayout),
        });
    },
});
