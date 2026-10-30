import { proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { KeepLast } from "@web/core/utils/concurrency";
import { omit } from "@web/core/utils/objects";
import { FrequencyViewerLocalConfig } from "./frequency_viewer/frequency_viewer_local_config";
import { roundTimeSpent } from "@timesheet_grid/utils/timer";
import { purgeOldCacheKeys } from "@timesheet_grid/utils/timesheets_assistant";

const { DateTime, Duration } = luxon;
export const MINIMUM_DURATION_FOR_EVENT = 60;
export const MINIMUM_DURATION_FOR_CONTEXT_SWITCH = 2;
export const MINIMUM_AFK_FILLING = 60 * 3;

/**
 * Owns fetching, matching and aggregating ActivityWatch/Odoo activity into timesheet
 * suggestions, and the mutations (take/delete/create/update) that keep that data in sync.
 * Instantiated once by TimesheetsAssistant. The instance itself is a plain object — only
 * `this.data` is a `proxy()`, since that's the only part templates/components ever read
 * reactively. `this.data`'s identity never changes after construction (see `fetchData()`),
 * so its properties can be mutated in place without any outer object needing to be reactive.
 */
export class TimesheetAssistantModel {
    constructor({ orm, notification, fakeEvents }, initialDate, { onBeforeLoad } = {}) {
        this.orm = orm;
        this.notification = notification;
        this.fakeEvents = fakeEvents;
        this.onBeforeLoad = onBeforeLoad;
        this.timesheetModel = "account.analytic.line";

        this.data = proxy({
            ...this.defaultDataValues,
            currentDate: initialDate,
            awServerStatus: "disconnected",
            hasWebWatcher: true,
            activeProjectName: "",
            activeProjectSince: "",
        });

        this.consumedEventsKey = "aw_taken_deleted_events";
        this.consumedEvents = JSON.parse(localStorage.getItem(this.consumedEventsKey) || "{}");
        this.migrateConsumedEvents(); // can be removed in the future
        this.cleanOldConsumedEvents();
        this.cleanOldBlockouts();
        this.assistantTimesheetIdsKey = "aw_assistant_timesheet_ids";
        this.assistantTimesheetIds = JSON.parse(
            localStorage.getItem(this.assistantTimesheetIdsKey) || "{}"
        );
        this.frequencyViewerLocalConfig = new FrequencyViewerLocalConfig();
        this.scores = this.frequencyViewerLocalConfig.scores;
        this.roundingValues = { minimum: 15, rounding: 15 };
        this.odooModelsData = {};
        this.projectById = {};
        this.taskById = {};
        this.metaData = {};
        this.keepLast = new KeepLast();
    }

    get defaultDataValues() {
        return {
            recordsByStart: {},
            grouped: {},
            totalDuration: 0,
            workingHours: 0,
            timesheets: [],
            totalTime: 0,
        };
    }

    get isToday() {
        return (
            this.data.currentDate.toFormat("yyyy-MMMM-dd") ===
            luxon.DateTime.now().toFormat("yyyy-MMMM-dd")
        );
    }

    async loadAssistantData() {
        const data = await this.orm.call(this.timesheetModel, "get_assistant_data");
        this.roundingValues = data.rounding_values;
        this.odooModelsData = data.odoo_models_data;
        return data;
    }

    get unmatchedProjectTaskKey() {
        return '{"project_id":false,"task_id":false}';
    }

    get blacklistEmails() {
        // List of email which should not have a project or task associated with them
        return new Set(["online@odoo.com"]);
    }

    getTimesheets(data = this.data) {
        return data.timesheets;
    }

    projectTaskKey(project_id, task_id) {
        return JSON.stringify({
            project_id: project_id || false,
            task_id: task_id || false,
        });
    }

    titleAndDayKey(title, extra = {}) {
        const key = { title, day: this.data.currentDate.toISO().split("T")[0] };
        if (extra.res_model && extra.id) {
            key.res_model = extra.res_model;
            key.id = extra.id;
        }
        return JSON.stringify(key);
    }

    projectName(id) {
        return this.projectById[id]?.name;
    }

    isProjectAllowsTimesheets(id) {
        if (!id) {
            return false;
        }
        return this.projectById[id]?.allowTimesheets ?? true;
    }

    taskName(id) {
        return this.taskById[id];
    }

    groupByTitle(ids) {
        const project = this.projectName(ids.project_id);
        const task = this.taskName(ids.task_id);

        let title = _t("Unmatched");
        if (project) {
            if (task) {
                title = `${project} / ${task}`;
            } else {
                title = project;
            }
        }

        return title;
    }

    hasVisibleActivities(groupKey) {
        return Object.values(this.data.grouped[groupKey].suggestions).some(
            (activity) => activity.type !== "afk" && this.isVisible(activity)
        );
    }

    getGroupTotalDuration(groupKey) {
        return this.data.grouped?.[groupKey]?.groupDuration;
    }

    async getWatchers(baseUrl) {
        // get all available buckets
        const buckets = await fetch(`${baseUrl}/api/0/buckets/`).then((response) =>
            response.json()
        );
        return Object.values(buckets).filter((bucket) =>
            ["afkstatus", "currentwindow", "web.tab.current", "app.editor.activity"].includes(
                bucket.type
            )
        );
    }

    _getParsedSampleData() {
        const { fakeEvents, partnerEmails: gmailEmails } = this.fakeEvents.get(
            this.data.currentDate.toISO().split("T")[0]
        );
        const keyEvents = {};
        const otherEvents = {};
        const composingEvents = [];

        for (const watcherType of ["web.tab.current", "currentwindow"]) {
            const events = fakeEvents[watcherType] || [];
            for (const event of events) {
                let eventType = watcherType;
                if (!this.parseWatcherActivity(event, gmailEmails, composingEvents)) {
                    continue;
                }
                if (event.always_active) {
                    eventType = "always_active";
                }
                const target = event.keyEvent ? keyEvents : otherEvents;
                if (!target[eventType]) {
                    target[eventType] = [];
                }
                target[eventType].push(event);
            }
        }
        return { keyEvents, otherEvents, gmailEmails, composingEvents };
    }

    /**
     * Identifies the specific email session or thread to group related activities together.
     * For new emails, Gmail uses a "compose" parameter in the URL.
     * When replying or forwarding, the URL remains the same as the "reading" URL,
     * so we extract the thread/message ID from the end of the path instead.
     */
    getGmailComposeId(url) {
        const composeMatch = url?.match(/compose=([^&?#]+)/);
        if (composeMatch) {
            return composeMatch[1];
        }
        return url?.split("/")?.pop()?.split("?")[0];
    }

    parseWatcherActivity(event, gmailEmails, composingEvents) {
        // Filter out window events that have no app and no title (e.g. system startup without open apps)
        if (!event.data?.app?.trim() && !event.data?.title?.trim()) {
            return false;
        }
        if (event.data.gmail_activity) {
            event.keyEvent = true;
            event.type = "gmail_activity";
            const recipients = [
                ...(event.data?.to || []),
                ...(event.data?.cc || []),
                ...(event.data?.bcc || []),
                ...(event.data?.from ? [event.data?.from] : []),
            ];
            for (const recipient of recipients) {
                if (recipient) {
                    const match = recipient.match(/\((.*)\)/);
                    gmailEmails.add(match ? match[1] : recipient);
                }
            }
            if (event.data.gmail_activity === "composing_email") {
                event.composeId = this.getGmailComposeId(event.data.url);
                composingEvents.push(event);
            }
        } else {
            this.extractWatcherActivity(event);
        }
        return true;
    }

    extractWatcherActivity(event) {
        let data = event.data.title;
        if (event.data.url) {
            data += "|" + event.data.url;
        }
        if (event.data.app) {
            data += "|" + event.data.app;
        }

        for (const rule of this.awRules) {
            const regex = new RegExp(rule.regex);
            const match = data.match(regex);
            if (match) {
                if (rule.project_id) {
                    event.project_id = rule.project_id[0];
                    event._res_model = "project.project";
                    event._res_id = rule.project_id[0];
                }

                if (rule.task_id) {
                    event.task_id = rule.task_id[0];
                    event._res_model = "project.task";
                    event._res_id = rule.task_id[0];
                }

                if (!event.task_id && match.groups?.task_id) {
                    const taskId = parseInt(match.groups.task_id, 10);
                    if (!isNaN(taskId)) {
                        event.task_id = taskId;
                        event._res_model = "project.task";
                        event._res_id = taskId;
                    }
                }

                if (rule.template != null || rule.description != null) {
                    event.template = rule.template;
                    event.description = rule.description;
                    event.matches = Array.from(match);

                    let key = rule.template;
                    let name = rule.description || rule.template;
                    for (let i = 1; i < match.length; i++) {
                        name = name.replace(`$${i}`, match[i] ?? "");
                        key = key.replace(`$${i}`, match[i] ?? "");
                    }
                    event.name = name;
                    event.key = key;
                } else {
                    event.name = rule.type;
                }
                event.threshold = rule.threshold;
                event.always_active = rule.always_active;
                event.side_activity = rule.side_activity;
                event.type = rule.type;
                event.keyEvent = true;
                return;
            }
        }

        if (!event.data.url) {
            return;
        }

        // in the config, we should have a sequence field, because order is important
        // like the example of overlap in calendar and planning apps
        // project and task in odoo url
        const url = event.data.url;

        for (const resolver of this.odooModelsData) {
            const match = url.match(new RegExp(resolver.url_regex));
            if (match) {
                event.matches = ["", resolver.label];
                event.template = resolver.template;
                let name = resolver.template;
                for (let i = 1; i < event.matches.length; i++) {
                    name = name.replace(`$${i}`, event.matches[i] ?? "");
                }
                event.name = name;
                event._res_model = resolver.model;
                event.type = resolver.type;
                event._res_id = Number(match[1]);
                event.keyEvent = true;
                event.isOdooModelEvent = true;
                return;
            }
        }

        return false;
    }

    async _processFallbackOdooUrls(events) {
        const odooOrigin = window.location.origin;
        const unmatchedOdooUrls = new Set();
        for (const event of events) {
            if (event.data?.url) {
                let urlObj;
                try {
                    urlObj = new URL(event.data.url);
                } catch {
                    continue;
                }
                if (urlObj.origin === odooOrigin) {
                    unmatchedOdooUrls.add(event.data.url);
                }
            }
        }

        if (unmatchedOdooUrls.size === 0) {
            return;
        }

        const resolvedUrls = await this.orm.call(this.timesheetModel, "get_aw_app_from_urls", [
            Array.from(unmatchedOdooUrls),
        ]);

        for (const event of events) {
            if (event.data?.url && resolvedUrls[event.data.url]) {
                const resolvedData = resolvedUrls[event.data.url];
                const name = resolvedData.record_name || resolvedData.app_name;
                event.name = _t("Working on %(target)s", {
                    target: name,
                });
                event.keyEvent = true;
                event.type = "odoo";
                event.matches = [name, name];
                event.template = _t("Working on $1");
            }
        }
    }

    async loadAwEvents(data, baseUrl, start, end) {
        // We call this unconditionally to guarantee a safe fallback structure for the catch block.
        // When there is no fake data for the current date, the 'events' array inside this method is empty,
        // meaning the parsing loops naturally skip execution when no data exists.
        const fakeData = this._getParsedSampleData();

        try {
            const watchers = await this.getWatchers(baseUrl);
            data.awServerStatus = "connected";
            data.hasWebWatcher = true;

            const requests = [];
            for (const watcher of watchers) {
                requests.push(
                    fetch(
                        `${baseUrl}/api/0/buckets/${
                            watcher["id"]
                        }/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
                    )
                );
            }

            const responses = await Promise.all(requests);
            const failed = [];
            const keyEvents = {};
            const otherEvents = {};
            const gmailEmails = new Set();
            const composingEvents = [];
            let webWatcherLastStop = null;

            for (let index = 0; index < requests.length; index++) {
                if (responses[index].ok) {
                    const events = await Promise.resolve(responses[index].json());
                    if (
                        watchers[index].type === "web.tab.current" &&
                        this.isToday &&
                        events.length > 0
                    ) {
                        const latest = events[0];
                        const stop = DateTime.fromISO(latest.timestamp).plus(
                            Duration.fromObject({ seconds: latest.duration })
                        );
                        if (!webWatcherLastStop || stop > webWatcherLastStop) {
                            webWatcherLastStop = stop;
                        }
                    }
                    for (const event of events.sort((a, b) => a.start - b.start)) {
                        event.start = DateTime.fromISO(event.timestamp);
                        event.stop = event.start.plus(
                            Duration.fromObject({ seconds: event.duration })
                        );
                        let eventType = watchers[index].type;
                        if (eventType === "app.editor.activity") {
                            event.type = "development";
                            if (watchers[index].client === "aw-watcher-vscode") {
                                // includes vscode, vscodium, antigravity ...
                                event.name =
                                    event.data.project === "unknown"
                                        ? _t("Development")
                                        : _t("VS Code - %(folder)s", {
                                              folder: event.data.project,
                                          });
                                event.keyEvent = true;
                            } else if (watchers[index].client === "aw-watcher-pycharm") {
                                // can be refactored with the previous
                                event.name =
                                    event.data.project === "unknown"
                                        ? _t("Development")
                                        : _t("Pycharm - %(folder)s - %(branch)s", {
                                              folder: event.data.project,
                                              branch: event.data.branch,
                                          });
                                event.keyEvent = true;
                            } else {
                                event.name = _t("Development");
                            }
                        } else if (["currentwindow", "web.tab.current"].includes(eventType)) {
                            if (!this.parseWatcherActivity(event, gmailEmails, composingEvents)) {
                                continue;
                            }
                            if (event.always_active) {
                                eventType = "always_active";
                            }
                        } else if (eventType === "afkstatus") {
                            if (event?.data?.status === "not-afk") {
                                continue;
                            }
                        }
                        if (event.keyEvent) {
                            if (!keyEvents[eventType]) {
                                keyEvents[eventType] = [];
                            }
                            keyEvents[eventType].push(event);
                        } else {
                            if (!otherEvents[eventType]) {
                                otherEvents[eventType] = [];
                            }
                            otherEvents[eventType].push(event);
                        }
                    }
                } else {
                    failed.push(responses[index]);
                }
            }

            if (this.isToday) {
                const webWatcherFound = watchers.some((w) => w.type === "web.tab.current");
                if (!webWatcherFound || !webWatcherLastStop) {
                    data.hasWebWatcher = false;
                } else {
                    const diff = DateTime.now().diff(webWatcherLastStop, "minutes").minutes;
                    if (diff > 5) {
                        data.hasWebWatcher = false;
                    }
                }
            }

            // Fallback for Odoo browser events only: try to match them to an app name
            const candidateEvents = otherEvents["web.tab.current"] || [];
            if (candidateEvents.length > 0) {
                await this._processFallbackOdooUrls(candidateEvents);
                const remainingOther = [];
                for (const event of candidateEvents) {
                    if (event.keyEvent) {
                        if (!keyEvents["web.tab.current"]) {
                            keyEvents["web.tab.current"] = [];
                        }
                        keyEvents["web.tab.current"].push(event);
                    } else {
                        remainingOther.push(event);
                    }
                }
                otherEvents["web.tab.current"] = remainingOther;
            }

            // Inject sample ActivityWatch events into the loaded ActivityWatch data.
            // Relies on fakeData returning empty arrays/objects if no data exists for the date.
            for (const [type, events] of Object.entries(fakeData.keyEvents)) {
                if (!keyEvents[type]) {
                    keyEvents[type] = [];
                }
                keyEvents[type].push(...events);
            }
            for (const [type, events] of Object.entries(fakeData.otherEvents)) {
                if (!otherEvents[type]) {
                    otherEvents[type] = [];
                }
                otherEvents[type].push(...events);
            }
            composingEvents.push(...fakeData.composingEvents);
            fakeData.gmailEmails.forEach((email) => gmailEmails.add(email));
            return { keyEvents, otherEvents, gmailEmails, composingEvents };
        } catch {
            await this._updateAwStatus(baseUrl, data);
            return fakeData;
        }
    }

    validateProjectTask(target) {
        if (!target) {
            return;
        }
        if (target.project_id && !this.projectById[target.project_id]) {
            target.project_id = false;
            target.task_id = false;
        }
        if (target.task_id && !this.taskById[target.task_id]) {
            target.task_id = false;
        }
    }

    _resolveProjectTaskFromResModel(range) {
        if (!(range._res_model && range._res_id)) {
            return null;
        }
        const rangeProjectTaskData = this.projectAndTaskData?.[range._res_model]?.[range._res_id];
        if (rangeProjectTaskData?.project_id) {
            range.project_id = rangeProjectTaskData.project_id;
        }
        if (rangeProjectTaskData?.task_id) {
            if (!range.project_id) {
                range.keyEvent = false;
            }
            range.task_id = rangeProjectTaskData.task_id;
        }
        return rangeProjectTaskData;
    }

    computeKeyEventGroups(ranges) {
        const getDuration = (range) => range.duration ?? (range.stop - range.start) / 1000;
        const isAfk = (range) => range.data?.status === "afk" || range.type === "afk";
        const isSameActivity = (a, b) =>
            ["name", "type", "project_id", "task_id", "_res_model", "_res_id"].every(
                (field) => a[field] === b[field]
            );

        let group = null;
        const closeGroup = () => {
            for (const range of group?.keyEvents || []) {
                range.groupDuration = group.duration;
            }
            group = null;
        };

        for (const range of ranges) {
            delete range.groupDuration;
            delete range.isInKeyEventGroup;
            const duration = getDuration(range);
            if (
                range.isConsumed ||
                (isAfk(range) &&
                    duration >= MINIMUM_DURATION_FOR_EVENT &&
                    !group?.keyEvents[0].always_active)
            ) {
                closeGroup();
                continue;
            }
            if (range.keyEvent && duration >= MINIMUM_DURATION_FOR_CONTEXT_SWITCH) {
                if (!group || !isSameActivity(group.keyEvents[0], range)) {
                    closeGroup();
                    group = { keyEvents: [], duration: 0 };
                }
                group.keyEvents.push(range);
            }
            if (group) {
                group.duration += duration;
                if (isAfk(range)) {
                    range.isInKeyEventGroup = true;
                }
            }
        }
        closeGroup();
    }

    /**
     * Normalize a list of events by removing overlaps.
     *
     * When two events overlap, the event that starts later takes priority.
     * The earlier event is clipped so that no overlap remains, or discarded
     * entirely if it is fully covered by the later one.
     *
     * The input array is expected to be ordered by increasing `start` time.
     */
    normalizeEvents(events) {
        if (!events || events.length === 0) {
            return [];
        }
        const res = [{ ...events[0] }];
        for (let i = 1; i < events.length; i++) {
            const event = events[i];
            const prev = res[res.length - 1];

            if (event.start >= prev.stop) {
                res.push({ ...event });
                continue;
            }

            if (event.stop >= prev.stop) {
                event.start = prev.stop;
                res.push({ ...event });
            }
        }
        return res;
    }

    addResId(idsByModel, res_model, res_id) {
        if (!idsByModel[res_model]) {
            idsByModel[res_model] = new Set();
        }
        idsByModel[res_model].add(res_id);
    }

    /**
     * Merge an array of events into the `range` array paramater. Events from `ranges` have
     * priority, so if events from `intervalsToInclude` overlap them, they are clipped so that no
     * overlap remains, or discarded entirely if they are fully covered by events from `ranges`.
     *
     * This method modifies `ranges` in place.
     * Events in both array parameters are assumed to be sorted by increasing start.
     */
    merge(ranges, intervalsToInclude) {
        if (!intervalsToInclude || intervalsToInclude.length === 0) {
            return;
        }
        if (ranges.length === 0) {
            ranges.push(...intervalsToInclude);
            return;
        }

        let j = 0;
        const res = [];
        for (let i = 0; i <= ranges.length; i++) {
            const gapStart = i === 0 ? -Infinity : ranges[i - 1].stop;
            const gapEnd = i === ranges.length ? Infinity : ranges[i].start;
            if (gapEnd <= gapStart) {
                continue;
            }
            while (j < intervalsToInclude.length && intervalsToInclude[j].stop <= gapStart) {
                j++;
            }
            while (j < intervalsToInclude.length && intervalsToInclude[j].start < gapEnd) {
                const current = intervalsToInclude[j];
                const clampedStart = current.start > gapStart ? current.start : gapStart;
                const clampedStop = current.stop < gapEnd ? current.stop : gapEnd;
                if (clampedStart < clampedStop) {
                    const interval = {
                        ...current,
                        start: clampedStart,
                        stop: clampedStop,
                    };
                    if ("duration" in interval) {
                        interval.duration = (clampedStop - clampedStart) / 1000;
                    }
                    res.push(interval);
                }
                if (intervalsToInclude[j].stop > gapEnd) {
                    break;
                }
                j++;
            }
        }
        ranges.push(...res);
        ranges.sort((a, b) => a.start - b.start);
    }

    /**
     * Fetches the `aw.rule` records once and hands off to `fetchData()` for the
     * per-day/per-view data. Rules don't depend on the selected date or the
     * timeline/by-project grouping, so this must only run on the initial load —
     * navigating dates, switching view, reconnecting, or regenerating sample data
     * should all go through `fetchData()` instead, not re-fetch the rules.
     */
    async load() {
        this.awRules = await this.orm.call("aw.rule", "get_applicable_rules", [
            [
                "regex",
                "type",
                "template",
                "description",
                "project_id",
                "task_id",
                "threshold",
                "always_active",
                "side_activity",
                "sequence",
            ],
        ]);
        await this.fetchData();
    }

    async fetchData() {
        this.onBeforeLoad?.();

        // If the user navigates again (e.g. clicking the previous-day arrow several
        // times) before this call's RPCs settle, `this.keepLast` makes this `await`
        // never resolve for the superseded call, so its result is never committed
        // below: the view never flickers through the in-between days it never asked
        // to actually see, and only ends up showing the last-requested date.
        const { data, metaData } = await this.keepLast.add(this._fetchData());

        Object.assign(this.data, data);
        this.metaData = metaData;
    }

    async _fetchData() {
        // Built up in isolation from `this.data` and only returned for `fetchData()`
        // to commit in one go, so that the reactive proxy sees exactly one change
        // instead of re-rendering TimesheetsAssistant on every intermediate mutation
        // made while this method (and everything it awaits) is still running.
        // `this.data` keeps its identity (never reassigned) so it can stay the one
        // reactive object owned by this model.
        const data = {
            ...this.defaultDataValues,
            currentDate: this.data.currentDate,
            awServerStatus: this.data.awServerStatus,
            hasWebWatcher: this.data.hasWebWatcher,
            activeProjectName: "",
            activeProjectSince: "",
        };

        const baseUrl = "http://localhost:5600";
        const todayStart = data.currentDate.toISO();
        const todayEnd = data.currentDate.endOf("day").toISO();
        const [awEvents, odooEvents] = await Promise.all([
            this.loadAwEvents(data, baseUrl, todayStart, todayEnd),
            this.orm.call(this.timesheetModel, "get_assistant_events", [
                [],
                data.currentDate.toISO().split("T")[0],
            ]),
        ]);
        const { keyEvents, otherEvents, gmailEmails, composingEvents } = awEvents;
        let gmailPartners = {};
        if (gmailEmails && gmailEmails.size > 0) {
            gmailPartners = await this.orm.call(this.timesheetModel, "resolve_gmail_partners", [
                [...gmailEmails.difference(this.blacklistEmails)],
            ]);
        }

        const resolveEmail = (emailStr) => {
            const match = emailStr?.match(/^(.*)\s+\((.*)\)$/);
            const name = match ? match[1].trim() : emailStr;
            const email = match ? match[2].trim() : emailStr;
            const partner = gmailPartners[email];
            return {
                label: partner ? partner.partner_name : name,
                isPartner: !!partner,
                data: partner || {},
            };
        };

        const allAwEvents = [...Object.values(keyEvents), ...Object.values(otherEvents)].flat();

        composingEvents.sort((a, b) => a.start - b.start);

        const draftDataById = {};
        let lastSeenComposeId = null;
        for (let i = composingEvents.length - 1; i >= 0; i--) {
            const event = composingEvents[i];
            let composeId = event.composeId;
            if (composeId === "new") {
                if (lastSeenComposeId) {
                    composeId = lastSeenComposeId;
                    event.data = { ...draftDataById[composeId] };
                }
            } else if (composeId) {
                if (!draftDataById[composeId]) {
                    draftDataById[composeId] = event.data;
                }
                event.data = { ...draftDataById[composeId] };
                lastSeenComposeId = composeId;
            }
        }

        for (const range of allAwEvents.filter((e) => e.type === "gmail_activity")) {
            if (range.data.gmail_activity === "reading_inbox") {
                range.name = _t("Reading Inbox");
                continue;
            }
            const emails =
                range.data.gmail_activity === "reading_email"
                    ? [
                          ...(range.data?.from ? [range.data?.from] : []),
                          ...(range.data?.to || []),
                          ...(range.data?.cc || []),
                          ...(range.data?.bcc || []),
                      ]
                    : [
                          ...(range.data?.to || []),
                          ...(range.data?.cc || []),
                          ...(range.data?.bcc || []),
                      ];

            const resolvedEmails = emails.map(resolveEmail);

            const getScore = (r) => {
                if (!r.isPartner) {
                    return 0;
                }
                if (r.data.project_id && r.data.task_id) {
                    return 3;
                }
                if (r.data.project_id) {
                    return 2;
                }
                return 1;
            };

            const bestPartner = resolvedEmails.reduce(
                (best, current) => (getScore(current) > getScore(best) ? current : best),
                resolvedEmails[0]
            );

            if (bestPartner && bestPartner.isPartner) {
                if (bestPartner.data.task_id) {
                    range._res_model = "project.task";
                    range._res_id = bestPartner.data.task_id;
                } else if (bestPartner.data.project_id) {
                    range._res_model = "project.project";
                    range._res_id = bestPartner.data.project_id;
                }
            }

            let peopleStr;
            if (range.data.gmail_activity === "reading_email") {
                peopleStr = range.data.from ? resolveEmail(range.data.from).label : "";
            } else {
                const displayLabels = resolvedEmails.slice(0, 2).map((r) => r.label);
                peopleStr =
                    resolvedEmails.length <= 2
                        ? displayLabels.join(", ")
                        : _t("%(person1)s, %(person2)s, and %(count)s more", {
                              person1: displayLabels[0],
                              person2: displayLabels[1],
                              count: resolvedEmails.length - 2,
                          });
            }

            if (peopleStr) {
                if (range.data.subject) {
                    const isReading = range.data.gmail_activity === "reading_email";
                    range.template = isReading ? _t("Reading email $1") : _t("Composing email $1");
                    range.matches = [
                        `${peopleStr}|${range.data.subject}`,
                        isReading
                            ? _t('from %(person)s: "%(subject)s"', {
                                  person: peopleStr,
                                  subject: range.data.subject,
                              })
                            : _t('to %(person)s: "%(subject)s"', {
                                  person: peopleStr,
                                  subject: range.data.subject,
                              }),
                    ];
                } else {
                    range.template =
                        range.data.gmail_activity === "reading_email"
                            ? _t("Reading email from $1")
                            : _t("Composing email to $1");
                    range.matches = [peopleStr, peopleStr];
                }
                peopleStr =
                    range.data.gmail_activity === "reading_email"
                        ? _t(" from %(people)s", { people: peopleStr })
                        : _t(" to %(people)s", { people: peopleStr });
            }

            const subjectStr = range.data.subject ? `: "${range.data.subject}"` : "";
            range.name =
                range.data.gmail_activity === "reading_email"
                    ? _t("Reading email%(people)s%(subject)s", {
                          people: peopleStr,
                          subject: subjectStr,
                      })
                    : _t("Composing email%(people)s%(subject)s", {
                          people: peopleStr,
                          subject: subjectStr,
                      });
        }

        const rawOdooEvents = (odooEvents || []).map((event) => ({
            ...event,
            start: deserializeDateTime(event.start),
            stop: deserializeDateTime(event.stop),
            duration: event.duration !== undefined ? event.duration * 3600 : undefined,
            keyEvent: true,
        }));

        const allSuggestedAwEvents = [];
        for (const events of [keyEvents?.always_active, otherEvents?.afkstatus]) {
            if (events) {
                events.sort((a, b) => a.start - b.start);
                this.merge(allSuggestedAwEvents, this.normalizeEvents(events));
            }
        }

        for (const events of [keyEvents, otherEvents]) {
            for (const eventType of ["app.editor.activity", "web.tab.current", "currentwindow"]) {
                if (events?.[eventType]) {
                    events[eventType].sort((a, b) => a.start - b.start);
                    this.merge(allSuggestedAwEvents, this.normalizeEvents(events[eventType]));
                }
            }
        }
        if (allSuggestedAwEvents.length > 0) {
            const afk_fillers = [
                {
                    data: {
                        status: "afk",
                    },
                    duration:
                        allSuggestedAwEvents[allSuggestedAwEvents.length - 1].stop -
                        allSuggestedAwEvents[0].start,
                    start: allSuggestedAwEvents[0].start,
                    stop: allSuggestedAwEvents[allSuggestedAwEvents.length - 1].stop,
                },
            ];
            this.merge(allSuggestedAwEvents, afk_fillers);
        }

        let idsByModel = {};
        for (const { _res_model, _res_id } of [...rawOdooEvents, ...allSuggestedAwEvents]) {
            if (_res_model && _res_id) {
                this.addResId(idsByModel, _res_model, _res_id);
            }
        }

        for (const combos of Object.values(this.frequencyViewerLocalConfig.scores)) {
            for (const jsonKey of Object.keys(combos)) {
                const { project_id, task_id } = JSON.parse(jsonKey);
                if (project_id) {
                    this.addResId(idsByModel, "project.project", project_id);
                }
                if (task_id) {
                    this.addResId(idsByModel, "project.task", task_id);
                }
            }
        }
        idsByModel = Object.fromEntries(
            Object.entries(idsByModel).map(([model, idsSet]) => [model, [...idsSet]])
        );

        this.projectAndTaskData = await this.orm.call(
            this.timesheetModel,
            "resolve_assistant_models_targets",
            [idsByModel]
        );
        this.projectById = {};
        this.taskById = {};

        for (const idsVals of Object.values(this.projectAndTaskData)) {
            for (const {
                project_id,
                project_name,
                task_id,
                task_name,
                allow_timesheets,
            } of Object.values(idsVals)) {
                if (project_id && project_name) {
                    if (!this.projectById[project_id]) {
                        this.projectById[project_id] = {
                            name: project_name,
                            allowTimesheets: allow_timesheets,
                        };
                    }
                    if (task_id && task_name && !this.taskById[task_id]) {
                        this.taskById[task_id] = task_name;
                    }
                }
            }
        }

        const metaData = { rawOdooEvents, allSuggestedAwEvents };

        // the manual timesheets are deducted from the suggestions, so they must be loaded first
        await this.loadTimesheets(data);
        await this.computeSuggestions(data, metaData);

        return { data, metaData };
    }

    async computeSuggestions(data = this.data, metaData = this.metaData) {
        Object.assign(data, {
            grouped: {},
            recordsByStart: {},
        });

        const ranges = [];
        this.merge(ranges, this.getTimerBlockouts(data));
        for (const range of metaData.rawOdooEvents) {
            const keyWithDay = this.titleAndDayKey(range.name, range);
            const consumed = this.consumedEvents[keyWithDay];
            if (consumed) {
                if (consumed.isConsumed) {
                    // if taken, we keep the range to mask any ActivityWatch events underneath,
                    // but we mark it to avoid displaying it in the suggestions.
                    range.isConsumed = true;
                } else {
                    // if deleted/ignored, we completely remove the range so that background
                    // activity can surface as new suggestions.
                    continue;
                }
            }
            ranges.push({ ...range });
        }

        this.merge(ranges, metaData.allSuggestedAwEvents);
        // resolving the project/task can make a range a non key event (e.g. a task without
        // project), so it must be done before grouping the key events.
        for (const range of ranges) {
            if (range.type !== "gmail_activity") {
                this._resolveProjectTaskFromResModel(range);
            }
        }
        this.computeKeyEventGroups(ranges);

        let currentTimelineBlock = null;

        const processTimelineBlock = (
            range,
            projectTask,
            name,
            duration,
            matchKey = name,
            type = range.type
        ) => {
            if (
                !currentTimelineBlock ||
                currentTimelineBlock.groupKey !== projectTask ||
                currentTimelineBlock.name !== name
            ) {
                if (currentTimelineBlock) {
                    this._pushTimelineBlock(data, currentTimelineBlock);
                }
                const { project_id, task_id } = JSON.parse(projectTask);
                currentTimelineBlock = {
                    ...omit(range, ["start", "stop", "data", "duration", "timestamp"]),
                    start: range.start.toISO(),
                    data: [range.data],
                    formattedStart: range.start.toLocaleString(DateTime.TIME_SIMPLE),
                    duration: 0.0,
                    threshold: range.threshold ?? 1,
                    type,
                    title: name,
                    name,
                    key: range.key || null,
                    groupKey: projectTask,
                    matchKey,
                    allow_timesheets: this.isProjectAllowsTimesheets(project_id),
                    source_model: range._res_model,
                    source_id: range._res_id,
                };
                if (project_id) {
                    currentTimelineBlock.project = this.projectName(project_id);
                }
                if (task_id) {
                    currentTimelineBlock.task = this.taskName(task_id);
                }
            }
            currentTimelineBlock.data.push(range.data);
            currentTimelineBlock.duration += duration;
        };

        const activeKeyEvent = {
            name: null,
            type: "other",
            projectId: false,
            taskId: false,
            start: null,
            alwaysActive: false,
        };
        for (const range of ranges) {
            if (range.isConsumed) {
                // hide consumed events from the suggestions list without allowing
                // underlying AW activity to reappear (hiding without replacing)
                continue;
            }

            if (
                (range.data?.status === "afk" || range.type === "afk") &&
                !activeKeyEvent.alwaysActive &&
                !range.isInKeyEventGroup
            ) {
                range.type = "afk";
                const away = _t("Away");
                processTimelineBlock(
                    range,
                    this.unmatchedProjectTaskKey,
                    away,
                    (range.stop - range.start) / 1000
                );
                continue;
            }

            const frequencyKey =
                range.type === "gmail_activity" && range.data?.subject
                    ? range.data.subject
                    : range.name;

            const historicalAssignment =
                this.frequencyViewerLocalConfig.getDominantSuggestion(frequencyKey);

            if (range.type !== "gmail_activity") {
                if (range.isOdooModelEvent) {
                    const rangeProjectTaskData =
                        this.projectAndTaskData?.[range._res_model]?.[range._res_id];
                    const recordName =
                        range._res_model === "project.task"
                            ? rangeProjectTaskData?.task_name
                            : rangeProjectTaskData?.source_record_name
                            ? _t("Working on %s", rangeProjectTaskData.source_record_name)
                            : rangeProjectTaskData?.project_name;
                    if (recordName) {
                        range.name = recordName;
                        range.template = "$1";
                        range.matches = [recordName, recordName];
                    }
                }
            } else {
                if (historicalAssignment) {
                    this.validateProjectTask(historicalAssignment);
                    if (historicalAssignment.project_id) {
                        range.project_id = historicalAssignment.project_id;
                    }
                    if (historicalAssignment.task_id) {
                        range.task_id = historicalAssignment.task_id;
                    }
                } else {
                    this._resolveProjectTaskFromResModel(range);
                }
            }

            if (range?._isTimerBlockout) {
                continue;
            }

            // if the range is a gmail activity and has no project or task, it should be grouped under unmatched without impacting the next events
            const hasProjectOrTask = range.project_id || range.task_id;
            const isUnmatchedGmailActivity =
                range.type === "gmail_activity" && !historicalAssignment && !hasProjectOrTask;

            let groupKey;
            let name;
            let type;

            if (isUnmatchedGmailActivity) {
                // If the event is a gmail activity and has no project or task, group under unmatched
                // without impacting the next events.
                groupKey = this.unmatchedProjectTaskKey;
                name = range.name;
                type = range.type;
            } else {
                let targetProjectId = activeKeyEvent.projectId;
                let targetTaskId = activeKeyEvent.taskId;
                let foundNewContext = false;

                if (range.keyEvent && hasProjectOrTask) {
                    targetProjectId = range.project_id;
                    targetTaskId = range.task_id;
                    foundNewContext = true;
                } else if (historicalAssignment) {
                    this.validateProjectTask(historicalAssignment);
                    if (historicalAssignment.project_id || historicalAssignment.task_id) {
                        targetProjectId = historicalAssignment.project_id;
                        targetTaskId = historicalAssignment.task_id || false;
                        foundNewContext = true;
                    }
                } else if (range.keyEvent && this._isSideActivityEvent(range)) {
                    targetProjectId = false;
                    targetTaskId = false;
                }

                if (
                    range.keyEvent &&
                    (range.groupDuration ?? range.duration) >= MINIMUM_DURATION_FOR_EVENT
                ) {
                    if (this._isSideActivityEvent(range)) {
                        name = range.name;
                        type = range.type;
                    } else {
                        activeKeyEvent.name = range.name;
                        activeKeyEvent.type = range.type;
                        activeKeyEvent.alwaysActive = range.always_active ?? false;
                        if (foundNewContext) {
                            activeKeyEvent.projectId = targetProjectId;
                            activeKeyEvent.taskId = targetTaskId;
                            activeKeyEvent.start = range.start;
                        }
                        name = activeKeyEvent.name;
                        type = activeKeyEvent.type;
                    }
                } else {
                    name = activeKeyEvent.name;
                    type = activeKeyEvent.type;
                }
                groupKey = this.projectTaskKey(targetProjectId, targetTaskId);
            }
            name = name || range.data?.title || _t("Unknown Activity");
            let duration = range.duration ?? (range.stop - range.start) / 1000;
            if (range.max_hours && duration / 3600 > range.max_hours) {
                duration = range.max_hours * 3600;
            }
            processTimelineBlock(range, groupKey, name, duration, frequencyKey, type);
        }

        if (currentTimelineBlock) {
            this._pushTimelineBlock(data, currentTimelineBlock);
        }

        const project = this.projectName(activeKeyEvent.projectId);
        if (project) {
            data.activeProjectName = project;
            if (activeKeyEvent.start) {
                data.activeProjectSince = activeKeyEvent.start.toLocaleString(DateTime.TIME_SIMPLE);
            }
        }

        // legacy: the time taken or deleted from the project view was only stored as a duration
        // (`duration` minus the `timelineDuration` taken or deleted from the chronological view)
        const legacyConsumedByKey = {};
        for (const record of Object.values(data.recordsByStart)) {
            const key = this.titleAndDayKey(record.title, record);
            const consumedEvent = this.consumedEvents[key];
            let trackedDuration = record.duration;
            if (consumedEvent?.timelineStartTimes?.includes(record.start)) {
                // a taken or deleted record stays hidden, so that the manual timesheets are
                // deducted from the same records, in the same order, as before the reload
                record.consumedDuration =
                    consumedEvent.timelineDurations?.[record.start] ?? trackedDuration;
            } else if (consumedEvent?.duration) {
                // removed from the records of the same title, from the first one
                legacyConsumedByKey[key] ??= Math.max(
                    0,
                    consumedEvent.duration - (consumedEvent.timelineDuration || 0)
                );
                const legacyConsumed = Math.min(legacyConsumedByKey[key], trackedDuration);
                legacyConsumedByKey[key] -= legacyConsumed;
                trackedDuration -= legacyConsumed;
            }
            record.trackedDuration = trackedDuration;
            record.remaining = trackedDuration;
            record.duration = this._getDisplayedDuration(record);
        }

        // the project view is built from the chronological records, so that both views
        // always show the same time for the same project/task.
        data.grouped = {};
        data.totalDuration = 0;
        for (const record of Object.values(data.recordsByStart)) {
            this._addRecordToGrouped(data, record);
        }

        const today = data.currentDate.toISO().split("T")[0];
        const assistantIdsForDay = new Set(this.assistantTimesheetIds[today] || []);
        for (const ts of this.getTimesheets(data)) {
            if (!assistantIdsForDay.has(ts.id)) {
                const groupKey = this.projectTaskKey(ts.project_id.id, ts.task_id.id);
                this.refreshSuggestions(groupKey, ts.unit_amount * 3600, data);
            }
        }
    }

    getTimerBlockouts(data) {
        const cacheStr = localStorage.getItem("timesheet_assistant_blockouts");
        if (!cacheStr) {
            return [];
        }
        const cache = JSON.parse(cacheStr);
        const todayStr = data.currentDate.toISODate();
        const dayData = cache[todayStr];
        if (!dayData) {
            return [];
        }
        const blockoutRanges = [];
        for (const tsId in dayData) {
            for (const [startStr, stopStr] of dayData[tsId]) {
                blockoutRanges.push({
                    start: DateTime.fromISO(startStr),
                    stop: DateTime.fromISO(stopStr),
                    _isTimerBlockout: true,
                    keyEvent: true,
                });
            }
        }
        blockoutRanges.sort((a, b) => a.start - b.start);
        return this.normalizeEvents(blockoutRanges);
    }

    /**
     * Displayed duration of a record: rounded to the minute, so that both views sum up the
     * exact same displayed minutes, or 0 if it is too short to be displayed.
     */
    _roundDuration(seconds, minimum = MINIMUM_DURATION_FOR_EVENT) {
        return seconds >= minimum ? Math.round(seconds / 60) * 60 : 0;
    }

    _getDisplayedDuration(record) {
        if (record.consumedDuration != null) {
            return 0;
        }
        // a record shorter than the threshold of its rule (in minutes) is hidden
        const minimum =
            record.threshold != null ? record.threshold * 60 : MINIMUM_DURATION_FOR_EVENT;
        return this._roundDuration(record.remaining, minimum);
    }

    /**
     * Update the displayed duration of a record, and its share of its project suggestion.
     */
    _refreshRecordDuration(record, data = this.data) {
        const diff = this._getDisplayedDuration(record) - record.duration;
        record.duration += diff;
        const suggestion = this._getRecordSuggestion(record, data);
        if (suggestion) {
            suggestion.duration += diff;
            data.grouped[record.groupKey].groupDuration += diff;
            data.totalDuration += diff;
        }
    }

    isVisible(item) {
        return item.duration >= MINIMUM_DURATION_FOR_EVENT;
    }

    _getRecordSuggestion(record, data = this.data) {
        if (record.type === "afk") {
            return null;
        }
        return data.grouped[record.groupKey]?.suggestions[record.title] || null;
    }

    _addRecordToGrouped(data, record) {
        if (record.type === "afk") {
            return;
        }
        const { groupKey, title } = record;
        if (!(groupKey in data.grouped)) {
            data.grouped[groupKey] = {
                groupDuration: 0,
                starts: new Set(), // chronological, including the hidden records
                overflow: 0, // manual timesheeted time that exceeded the tracked time of the group
                suggestions: {},
            };
        }
        const group = data.grouped[groupKey];
        if (!group.suggestions[title]) {
            group.suggestions[title] = {
                duration: 0,
                starts: new Set(),
                type: record.type,
                id: record.id,
                res_model: record.res_model,
                start: record.start,
                template: record.template,
                description: record.description,
                matches: record.matches,
                title,
                key: record.key,
                matchKey: record.matchKey,
                source_model: record.source_model,
                source_id: record.source_id,
            };
        }
        group.starts.add(record.start);
        group.suggestions[title].starts.add(record.start);
        group.suggestions[title].duration += record.duration;
        group.groupDuration += record.duration;
        data.totalDuration += record.duration;
    }

    /**
     * Deduct a manual timesheeted duration from the records of a project/task, from the first
     * one to the last one, or give it back from the last one to the first one when negative.
     * A record left with less than MINIMUM_DURATION_FOR_EVENT is hidden, not removed, so that
     * it shows up again when its time is given back. A taken or deleted record stays hidden,
     * but its time that was not taken or deleted can still be deducted and given back.
     */
    refreshSuggestions(groupKey, deltaSeconds, data = this.data) {
        const group = data.grouped[groupKey];
        if (!group) {
            return;
        }
        let rem = deltaSeconds;
        if (rem < 0) {
            const fromOverflow = Math.min(group.overflow, -rem);
            group.overflow -= fromOverflow;
            rem += fromOverflow;
        }
        const starts = rem > 0 ? [...group.starts] : [...group.starts].reverse();
        for (const start of starts) {
            if (rem === 0) {
                break;
            }
            const record = data.recordsByStart[start];
            const change =
                rem > 0
                    ? Math.min(record.remaining - (record.consumedDuration ?? 0), rem)
                    : Math.max(record.remaining - record.trackedDuration, rem);
            rem -= change;
            record.remaining -= change;
            this._refreshRecordDuration(record, data);
        }
        if (rem > 0) {
            group.overflow += rem;
        }
    }

    _pushTimelineBlock(data, block) {
        if (!block) {
            return;
        }
        const threshold = "threshold" in block ? block.threshold * 60 : MINIMUM_DURATION_FOR_EVENT;
        const starts = Object.keys(data.recordsByStart);
        const lastPushed = starts.length ? data.recordsByStart[starts[starts.length - 1]] : null;

        if (block.duration < threshold && (!lastPushed || lastPushed.type != "afk")) {
            if (lastPushed) {
                lastPushed.duration += block.duration;
            }
            return;
        }

        if (lastPushed && lastPushed.duration < MINIMUM_DURATION_FOR_EVENT) {
            if (block.type == "afk") {
                data.recordsByStart[starts[starts.length - 2]].duration +=
                    block.duration + lastPushed.duration;
                delete data.recordsByStart[starts[starts.length - 1]];
                return;
            }
            block.duration += lastPushed.duration;
            block.start = lastPushed.start;
            block.formattedStart = lastPushed.formattedStart;
            delete data.recordsByStart[starts[starts.length - 1]];
            data.recordsByStart[lastPushed.start] = block;
            return;
        }

        if (
            lastPushed &&
            lastPushed.groupKey === block.groupKey &&
            lastPushed.name === block.name
        ) {
            lastPushed.duration += block.duration;
        } else {
            data.recordsByStart[block.start] = block;
        }
    }

    _isSideActivityEvent(range) {
        return range.side_activity;
    }

    async loadTimesheets(data = this.data) {
        const today = data.currentDate.toISO().split("T")[0];
        data.totalTime = 0;

        const { specification, timesheets, working_hours } = await this.orm.call(
            this.timesheetModel,
            "get_aw_timesheet_data",
            [today]
        );
        this.specification = specification;
        data.workingHours = working_hours;
        data.timesheets = [];
        const validIds = [];
        if (timesheets.length) {
            timesheets.records.forEach((timesheet) => {
                this.addTimesheet(timesheet, true, data);
                validIds.push(timesheet.id);
            });
        }
        this.invalidateAwBlockoutsCache(validIds);
    }

    invalidateAwBlockoutsCache(validTsIds) {
        const cacheStr = localStorage.getItem("timesheet_assistant_blockouts");
        if (!cacheStr) {
            return;
        }
        const cache = JSON.parse(cacheStr);
        const todayStr = this.data.currentDate.toISODate();
        if (!cache[todayStr]) {
            return;
        }
        let hasGhosts = false;
        const validIdsSet = new Set(validTsIds);
        for (const tsId in cache[todayStr]) {
            if (!validIdsSet.has(Number(tsId))) {
                delete cache[todayStr][tsId];
                hasGhosts = true;
            }
        }
        if (hasGhosts) {
            if (Object.keys(cache[todayStr]).length === 0) {
                delete cache[todayStr];
            }
            localStorage.setItem("timesheet_assistant_blockouts", JSON.stringify(cache));
        }
    }

    refreshTimesheetsOnAdd(timesheet, data = this.data) {
        data.timesheets.push(timesheet);
        data.totalTime += timesheet.unit_amount;
    }

    addTimesheet(timesheet, isAssistant = false, data = this.data) {
        this.refreshTimesheetsOnAdd(timesheet, data);
        if (!isAssistant) {
            const groupKey = this.projectTaskKey(timesheet.project_id.id, timesheet.task_id.id);
            this.refreshSuggestions(groupKey, timesheet.unit_amount * 3600, data);
        }
    }

    refreshTimesheetsOnRemove(timesheetId) {
        const index = this.data.timesheets.findIndex((t) => t.id === timesheetId);
        if (index >= 0) {
            const timesheetToRemove = this.data.timesheets[index];
            this.data.totalTime -= timesheetToRemove.unit_amount;
            this.data.timesheets.splice(index, 1);
            return timesheetToRemove;
        }
        return null;
    }

    removeTimesheet(timesheetId) {
        const timesheetToRemove = this.refreshTimesheetsOnRemove(timesheetId);
        if (!timesheetToRemove) {
            return;
        }
        const today = this.data.currentDate.toISO().split("T")[0];
        const isAssistant = (this.assistantTimesheetIds[today] || []).includes(timesheetId);
        if (!isAssistant) {
            const groupKey = this.projectTaskKey(
                timesheetToRemove.project_id.id,
                timesheetToRemove.task_id.id
            );
            this.refreshSuggestions(groupKey, -timesheetToRemove.unit_amount * 3600);
        }
    }

    refreshTimesheetsOnUpdate(timesheet) {
        const index = this.data.timesheets.findIndex((t) => t.id === timesheet.id);
        if (index >= 0) {
            const oldTimesheet = this.data.timesheets[index];
            this.data.totalTime += timesheet.unit_amount - oldTimesheet.unit_amount;
            this.data.timesheets[index] = timesheet;
            return oldTimesheet;
        }

        return null;
    }

    updateTimesheet(timesheet) {
        const oldTimesheet = this.refreshTimesheetsOnUpdate(timesheet);
        if (!oldTimesheet) {
            return;
        }
        const today = this.data.currentDate.toISO().split("T")[0];
        const isAssistant = (this.assistantTimesheetIds[today] || []).includes(timesheet.id);
        if (!isAssistant) {
            const oldGroupKey = this.projectTaskKey(
                oldTimesheet.project_id.id,
                oldTimesheet.task_id.id
            );
            const newGroupKey = this.projectTaskKey(timesheet.project_id.id, timesheet.task_id.id);
            if (oldGroupKey !== newGroupKey) {
                this.refreshSuggestions(oldGroupKey, -oldTimesheet.unit_amount * 3600);
                this.refreshSuggestions(newGroupKey, timesheet.unit_amount * 3600);
            } else {
                this.refreshSuggestions(
                    oldGroupKey,
                    (timesheet.unit_amount - oldTimesheet.unit_amount) * 3600
                );
            }
        }
    }

    getSuggestionParams(groupKey, title, start = false, groupBy) {
        let duration = 0.0;

        if (groupBy === "timeline") {
            const record = this.data.recordsByStart[start];
            if (!record) {
                return false;
            }
            duration = record.duration;
        } else {
            if (this.data.grouped[groupKey]?.suggestions?.[title] == null) {
                return false;
            }
            duration = this.data.grouped[groupKey]?.suggestions?.[title].duration;
        }
        const { project_id, task_id } = JSON.parse(groupKey);
        const res = {
            name: title,
            unit_amount: duration / 60,
        };
        const timesheetsAllowed = this.isProjectAllowsTimesheets(project_id);

        if (project_id && timesheetsAllowed) {
            res.project_id = project_id;
        }
        if (task_id && timesheetsAllowed) {
            res.task_id = task_id;
        }

        return res;
    }

    getMatchKey(groupKey, title, start = false, groupBy) {
        if (groupBy === "timeline") {
            return this.data.recordsByStart[start]?.matchKey ?? title;
        }
        return this.data.grouped[groupKey]?.suggestions?.[title]?.matchKey ?? title;
    }

    _getResId(params) {
        if (params) {
            if (typeof params === "object") {
                return params.id ?? false;
            }
            return params;
        }
        return false;
    }

    getLocalConfigValsOnTake(params) {
        const res = {};
        if (params.project_id) {
            res.project_id = this._getResId(params.project_id);
        }
        if (params.task_id) {
            res.task_id = this._getResId(params.task_id);
        }
        return res;
    }

    async onTake(groupKey, title, start = false, groupBy) {
        // duplicated in fetchData
        const todayStart = this.data.currentDate.toISO();
        const date = todayStart.split("T")[0];
        const params = this.getSuggestionParams(groupKey, title, start, groupBy);
        if (params === false) {
            return;
        }
        const matchKey = this.getMatchKey(groupKey, title, start, groupBy);

        const vals = {
            date,
            user_id: user.userId,
            ...params,
            unit_amount:
                roundTimeSpent({ minutesSpent: params.unit_amount, ...this.roundingValues }) / 60,
        };

        const [timesheetId] = await this.orm.create(this.timesheetModel, [vals]);
        this.recordAssistantTimesheet(timesheetId);
        this.onDelete(groupKey, title, false, true, start, groupBy);
        this.frequencyViewerLocalConfig.addMatching(
            matchKey,
            this.getLocalConfigValsOnTake(params)
        );

        const [timesheet] = await this.orm.webRead(this.timesheetModel, [timesheetId], {
            specification: this.specification,
        });
        this.addTimesheet(timesheet, true);
    }

    recordAssistantTimesheet(id) {
        const day = this.data.currentDate.toISO().split("T")[0];
        if (!this.assistantTimesheetIds[day]) {
            this.assistantTimesheetIds[day] = [];
        }
        this.assistantTimesheetIds[day].push(id);
        localStorage.setItem(
            this.assistantTimesheetIdsKey,
            JSON.stringify(this.assistantTimesheetIds)
        );
    }

    onDelete(groupKey, title, refresh = true, isConsumed = false, start = false, groupBy) {
        // both views show the same chronological records: a row of the project view is made
        // of all the records sharing its project/task and title.
        const starts =
            groupBy === "timeline"
                ? [start]
                : [...(this.data.grouped[groupKey]?.suggestions?.[title]?.starts || [])];
        let hasMeeting = false;
        for (const recordStart of starts) {
            const record = this.data.recordsByStart[recordStart];
            // a hidden record stays, so that it shows up again if its time is given back
            if (!record || !this.isVisible(record)) {
                continue;
            }
            hasMeeting ||= record.type === "meeting";
            const keyWithDay = this.titleAndDayKey(record.title, record);
            if (!this.consumedEvents[keyWithDay]) {
                this.consumedEvents[keyWithDay] = {
                    isConsumed: false,
                    timelineStartTimes: [],
                };
            }
            const consumedEvent = this.consumedEvents[keyWithDay];
            consumedEvent.timelineStartTimes = [
                ...(consumedEvent.timelineStartTimes || []),
                recordStart,
            ];
            // the rest of the tracked time was deducted by manual timesheets, it can still be
            // given back to them or deducted by others
            consumedEvent.timelineDurations = {
                ...consumedEvent.timelineDurations,
                [recordStart]: record.remaining,
            };
            if (isConsumed) {
                consumedEvent.isConsumed = true;
            }
            record.consumedDuration = record.remaining;
            this._refreshRecordDuration(record);
        }

        localStorage.setItem(this.consumedEventsKey, JSON.stringify(this.consumedEvents));

        if (hasMeeting && refresh) {
            this.computeSuggestions();
        }
    }

    async generateSampleData() {
        await this.fakeEvents.generate(this.data.currentDate.toISO().split("T")[0]);
        await this.fetchData();
    }

    async testAwConnection() {
        const baseUrl = "http://localhost:5600";
        try {
            const response = await fetch(`${baseUrl}/api/0/info`);
            if (response.ok) {
                this.notification.add(
                    _t("Connection successful! The assistant is tracking your activity."),
                    { type: "success" }
                );
                if (this.data.awServerStatus !== "connected") {
                    this.data.awServerStatus = "connected";
                    this.fetchData();
                }
                return;
            }
        } catch {
            await this._updateAwStatus(baseUrl);
            if (this.data.awServerStatus === "unauthorized") {
                this.notification.add(
                    _t(
                        "Your browser can’t connect to the tracker. Please configure the CORS settings."
                    ),
                    { type: "danger" }
                );
                return;
            }
        }
        this.notification.add(
            _t(
                "Connected failed. Make sure ActivityWatch is running, and enable “Apps on Device” in your browser settings"
            ),
            { type: "danger" }
        );
    }

    async _updateAwStatus(baseUrl, data = this.data) {
        try {
            await fetch(`${baseUrl}/api/0/info`, { mode: "no-cors" });
            data.awServerStatus = "unauthorized";
        } catch {
            data.awServerStatus = "disconnected";
        }
    }

    migrateConsumedEvents() {
        // `some` will short circuit, we could also just test the first value but this feels cleaner
        if (Object.values(this.consumedEvents).some((value) => typeof value !== "number")) {
            return;
        }
        for (const [key, value] of Object.entries(this.consumedEvents)) {
            this.consumedEvents[key] = { duration: value, isConsumed: true };
        }
        localStorage.setItem(this.consumedEventsKey, JSON.stringify(this.consumedEvents));
    }

    cleanOldConsumedEvents() {
        const hasChanges = purgeOldCacheKeys(this.consumedEvents, (key) => JSON.parse(key).day, 30);
        if (hasChanges) {
            localStorage.setItem(this.consumedEventsKey, JSON.stringify(this.consumedEvents));
        }
    }

    cleanOldBlockouts() {
        const ASSISTANT_BLOCKOUTS_KEY = "timesheet_assistant_blockouts";
        const cacheStr = localStorage.getItem(ASSISTANT_BLOCKOUTS_KEY);
        if (!cacheStr) {
            return;
        }
        try {
            const cache = JSON.parse(cacheStr);
            const hasChanges = purgeOldCacheKeys(cache, (key) => key, 15);

            if (hasChanges) {
                localStorage.setItem(ASSISTANT_BLOCKOUTS_KEY, JSON.stringify(cache));
            }
        } catch {
            localStorage.removeItem(ASSISTANT_BLOCKOUTS_KEY);
        }
    }
}
