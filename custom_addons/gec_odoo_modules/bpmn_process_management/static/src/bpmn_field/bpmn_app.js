/** Part of bpmn_process_management. License LGPL-3.
 * Framework-free diagram app (viewer, modeler, inspector): touches only its host; bpmn_field.js wraps it in OWL. */
import { _t } from "@web/core/l10n/translation";
import { loadCSS, loadJS } from "@web/core/assets";
import { getBpmnTerms, getReviewReasons, getTypeLabels } from "./bpmn_terms";
import { MAX_SHEETS, PAPERS, buildPrintHtml, pageLayout, printHtml } from "./bpmn_print";

const LIB = "/bpmn_process_management/static/lib/bpmn-js";
const GUIDE_URL = "/bpmn_process_management/guide";
// bump with every rebuild of the bundle: browsers cache static files
const LIB_V = "?v=1.6.4";
const TEXT_KEYS = ["fontSize", "fontWeight", "fontStyle", "textDecoration", "textAlign"];
const TEXT_SIZES = [9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32];
const TEXT_BASE = 12;
const TEXT_ALIGN_TYPES = ["Task", "bpmn:SubProcess", "bpmn:Transaction", "bpmn:CallActivity", "bpmn:TextAnnotation"];
let libPromise = null;

export function loadBpmnLib() {
    if (!libPromise) {
        libPromise = Promise.all([
            loadCSS(LIB + "/assets/diagram-js.css" + LIB_V),
            loadCSS(LIB + "/assets/bpmn-js.css" + LIB_V),
            loadCSS(LIB + "/assets/bpmn-font/css/bpmn.css" + LIB_V),
            loadCSS(LIB + "/assets/diagram-js-minimap.css" + LIB_V),
            loadCSS(LIB + "/assets/color-picker.css" + LIB_V),
            loadJS(LIB + "/odoo-bpmn.min.js" + LIB_V),
        ]).then(() => window.OdooBpmn);
        libPromise.catch(() => (libPromise = null));
    }
    return libPromise;
}

const LINKABLE = [
    "bpmn:Task", "bpmn:UserTask", "bpmn:ManualTask", "bpmn:ServiceTask", "bpmn:ScriptTask",
    "bpmn:SendTask", "bpmn:ReceiveTask", "bpmn:BusinessRuleTask", "bpmn:SubProcess",
    "bpmn:Transaction", "bpmn:AdHocSubProcess", "bpmn:CallActivity", "bpmn:StartEvent", "bpmn:EndEvent",
    "bpmn:IntermediateThrowEvent", "bpmn:IntermediateCatchEvent", "bpmn:BoundaryEvent",
    "bpmn:ExclusiveGateway", "bpmn:InclusiveGateway", "bpmn:ParallelGateway",
    "bpmn:ComplexGateway", "bpmn:EventBasedGateway", "bpmn:DataObjectReference",
    "bpmn:DataStoreReference", "bpmn:Participant", "bpmn:Lane",
];
const RESPONSIBLE_TYPES = ["bpmn:Lane", "bpmn:Participant"];
const NO_LANE_INFO = ["bpmn:TextAnnotation", "bpmn:DataObjectReference", "bpmn:DataStoreReference",
    "bpmn:Group"];
const CONTAINERS = ["bpmn:Process", "bpmn:Collaboration", "label"];
// Regexes are built from strings because the Odoo term extractor mis-parses some regex literals.
const SAFE_URL = new RegExp("^(https?:\\/\\/[^\\/\\\\\\s]|mailto:|\\/(?![\\/\\\\]))", "i");
const URL_BAD_CHARS = new RegExp("[\\\\\\u0000-\\u0020\\u007f]");
const UNSAFE_FILENAME_CHARS = new RegExp("[\\\\/:*?\"<>|]+", "g");
const PLACEHOLDER = new RegExp("{([^}]+)}", "g");
const HAS_DI = new RegExp("BPMNShape|BPMNEdge");
const HAS_PROCESS = new RegExp("<(\\w+:)?process[\\s>]");
const BULLET = new RegExp("^[-*\\u2022]\\s+(.*)$");
const NUMBERED = new RegExp("^\\d{1,3}[.)]\\s+(.*)$");
const WORDS = new RegExp("\\s+");
const SECTION_COUNT = new RegExp("\\s*\\(\\d+\\)\\s*$");
const PANEL_MIN = 260;
const PANEL_MAX = 620;
const PANEL_DEFAULT = 320;
const MAC = new RegExp("Mac|iPhone|iPad");

const FONT = "\"Segoe UI\", Roboto, \"Noto Sans Georgian\", \"Noto Sans\", \"Helvetica Neue\", Arial, sans-serif";
const DEFAULT_STROKE = "#153749";
const DEFAULT_FILL = "#FFFFFF";
const COLOR_PRESETS = [
    { key: "default", label: "Default", fill: undefined, stroke: undefined },
    { key: "teal", label: "Teal", fill: "#D5F0E9", stroke: "#226263" },
    { key: "navy", label: "Navy", fill: "#DCE7EE", stroke: "#153749" },
    { key: "orange", label: "Orange", fill: "#FDE2D8", stroke: "#B83A12" },
    { key: "yellow", label: "Yellow", fill: "#FDF1C9", stroke: "#8A6500" },
    { key: "green", label: "Green", fill: "#DDF2D1", stroke: "#2E6B1F" },
    { key: "purple", label: "Purple", fill: "#EADCF5", stroke: "#5B2A86" },
    { key: "red", label: "Red", fill: "#FAD4D4", stroke: "#A11F1F" },
    { key: "gray", label: "Gray", fill: "#ECEEF0", stroke: "#4A5560" },
];

const EVENT_DEFS = {
    "bpmn:MessageEventDefinition": "message", "bpmn:TimerEventDefinition": "timer",
    "bpmn:ConditionalEventDefinition": "condition", "bpmn:SignalEventDefinition": "signal",
    "bpmn:ErrorEventDefinition": "error", "bpmn:EscalationEventDefinition": "escalation",
    "bpmn:CompensateEventDefinition": "compensation", "bpmn:CancelEventDefinition": "cancel",
    "bpmn:LinkEventDefinition": "link", "bpmn:TerminateEventDefinition": "terminate",
};
const SIMPLE_ICONS = {
    "bpmn:Task": "task", "bpmn:UserTask": "user-task", "bpmn:ManualTask": "manual-task",
    "bpmn:ServiceTask": "service-task", "bpmn:ScriptTask": "script-task", "bpmn:SendTask": "send-task",
    "bpmn:ReceiveTask": "receive-task", "bpmn:BusinessRuleTask": "business-rule-task",
    "bpmn:CallActivity": "call-activity", "bpmn:Transaction": "transaction",
    "bpmn:AdHocSubProcess": "ad-hoc-subprocess", "bpmn:ExclusiveGateway": "gateway-xor",
    "bpmn:InclusiveGateway": "gateway-or", "bpmn:ParallelGateway": "gateway-parallel",
    "bpmn:ComplexGateway": "gateway-complex", "bpmn:EventBasedGateway": "gateway-eventbased",
    "bpmn:DataObjectReference": "data-object", "bpmn:DataStoreReference": "data-store",
    "bpmn:DataInput": "data-input", "bpmn:DataOutput": "data-output", "bpmn:Participant": "participant",
    "bpmn:Lane": "lane", "bpmn:TextAnnotation": "text-annotation", "bpmn:Group": "group",
    "bpmn:MessageFlow": "connection", "bpmn:Association": "connection",
    "bpmn:DataInputAssociation": "connection", "bpmn:DataOutputAssociation": "connection",
};

/** Tiny DOM builder: h("div", {"class": "x", onclick: fn}, "text", child) */
function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v === undefined || v === null || v === false) {
            continue;
        }
        if (k.startsWith("on") && typeof v === "function") {
            el.addEventListener(k.slice(2), v);
        } else if (k === "class") {
            el.className = v;
        } else if (k === "value") {
            el.value = v;
        } else {
            el.setAttribute(k, v === true ? "" : v);
        }
    }
    for (const c of children.flat(Infinity)) {
        if (c === null || c === undefined || c === false) {
            continue;
        }
        el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
}

const ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
    undo: '<path d="M9 13L4 8l5-5"/><path d="M4 8h10a6 6 0 0 1 0 12h-3"/>',
    redo: '<path d="M15 13l5-5-5-5"/><path d="M20 8H10a6 6 0 0 0 0 12h3"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    print: '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    compress: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
    broken: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/><path d="M4 4l16 16"/>',
    warning: '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17v.5"/>',
    check: '<path d="M5 12l5 5 9-10"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    users: '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14a5 5 0 0 1 5 6"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
    record: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    map: '<rect x="3" y="4" width="18" height="16" rx="2"/><rect x="12" y="11" width="6" height="6" rx="1"/>',
    grid: '<path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
    keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    sidebar: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.9-.7-1.2-.7-2 0-.8.7-1.5 1.5-1.5H17a4 4 0 0 0 4-4c0-5-4-9-9-9z"/><circle cx="7.5" cy="11" r=".8"/><circle cx="10" cy="7" r=".8"/><circle cx="15" cy="7.5" r=".8"/>',
    once: '<path d="M5 12h14"/><path d="M15 8l4 4-4 4"/>',
    loopMark: '<path d="M18 13a6 6 0 1 1-2-6.5"/><path d="M17 3v4h-4"/>',
    miPar: '<path d="M8 6v12M12 6v12M16 6v12"/>',
    miSeq: '<path d="M6 8h12M6 12h12M6 16h12"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    group: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/><path d="M3 15v6h6M21 9V3h-6" stroke-dasharray="2 2"/>',
    route: '<path d="M5 19h4a3 3 0 0 0 3-3V8a3 3 0 0 1 3-3h4"/><circle cx="5" cy="19" r="1.5"/><path d="M17 3l2 2-2 2"/>',
    move: '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    sameSize: '<rect x="3" y="7" width="8" height="10" rx="1.5"/><rect x="13" y="7" width="8" height="10" rx="1.5"/><path d="M3 4h18M3 20h18"/>',
    bold: '<path d="M7 5h6a3.5 3.5 0 0 1 0 7H7zM7 12h7a3.5 3.5 0 0 1 0 7H7z"/>',
    italic: '<path d="M10 5h8M6 19h8M14 5l-4 14"/>',
    underline: '<path d="M7 4v7a5 5 0 0 0 10 0V4M5 20h14"/>',
    alignLeftText: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    alignCenterText: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    alignRightText: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    textSize: '<path d="M4 18L9 6l5 12M5.8 14h6.4M15 18l3-7 3 7M15.9 16h4.2"/>',
    copyStyle: '<rect x="8" y="3" width="12" height="7" rx="2"/><path d="M4 7v5h10v3M12 15h4v6h-4z"/>',
    swap: '<path d="M7 7h13l-3-3M17 17H4l3 3"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    right: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    left: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    note: '<path d="M4 5h16v11H9l-5 4z"/>',
    text: '<path d="M5 6h14M12 6v13M8 19h8"/>',
    reset: '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v4h4"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/>',
    flow: '<circle cx="5" cy="12" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><path d="M7 12h4l6-6M11 12l6 6"/>',
    alignLeft: '<path d="M4 3v18M8 7h10M8 12h6M8 17h12"/>',
    alignCenter: '<path d="M12 3v18M6 7h12M8 12h8M5 17h14"/>',
    alignRight: '<path d="M20 3v18M6 7h10M10 12h6M4 17h12"/>',
    alignTop: '<path d="M3 4h18M7 8v10M12 8v6M17 8v12"/>',
    alignMiddle: '<path d="M3 12h18M7 6v12M12 8v8M17 5v14"/>',
    alignBottom: '<path d="M3 20h18M7 6v10M12 10v6M17 4v12"/>',
    distH: '<path d="M4 3v18M20 3v18"/><rect x="9" y="8" width="6" height="8" rx="1"/>',
    distV: '<path d="M3 4h18M3 20h18"/><rect x="8" y="9" width="8" height="6" rx="1"/>',
    chevron: '<path d="M6 9l6 6 6-6"/>',
    save: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17v.5"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>',
};

const LINE_PREVIEWS = {
    sequence: '<path d="M4 12h46" stroke-width="2"/><path d="M50 7l10 5-10 5z" fill="currentColor" stroke="none"/>',
    default: '<path d="M4 12h46" stroke-width="2"/><path d="M10 7l6 10" stroke-width="2"/><path d="M50 7l10 5-10 5z" fill="currentColor" stroke="none"/>',
    conditional: '<path d="M4 12l7-5 7 5-7 5z" fill="#fff" stroke-width="1.6"/><path d="M18 12h32" stroke-width="2"/><path d="M50 7l10 5-10 5z" fill="currentColor" stroke="none"/>',
    message: '<circle cx="7" cy="12" r="3.5" fill="#fff" stroke-width="1.6"/><path d="M11 12h39" stroke-width="1.6" stroke-dasharray="6 4"/><path d="M50 7l10 5-10 5z" fill="#fff" stroke-width="1.6"/>',
    association: '<path d="M4 12h56" stroke-width="1.6" stroke-dasharray="1.5 4" stroke-linecap="round"/>',
    data: '<path d="M4 12h50" stroke-width="1.6" stroke-dasharray="1.5 4" stroke-linecap="round"/><path d="M52 7l8 5-8 5" stroke-width="1.6"/>',
};

function isActivity(el) {
    return /(Task|SubProcess|CallActivity|Transaction)$/.test(el.type || "");
}

function linePreview(kind) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 64 24");
    svg.setAttribute("width", "64");
    svg.setAttribute("height", "24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "o_bpmn_line_preview");
    svg.innerHTML = LINE_PREVIEWS[kind] || "";
    return svg;
}

function icon(name, size = 16) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "o_bpmn_icon");
    svg.innerHTML = ICONS[name] || "";
    return svg;
}

function debounce(fn, delay) {
    let timer;
    const wrapped = (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
    wrapped.cancel = () => clearTimeout(timer);
    return wrapped;
}

function downloadBlob(content, filename, type) {
    const blob = content instanceof Blob ? content : new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function utf8ToBase64(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
}

function safeFileName(name) {
    return (name || "process").replace(UNSAFE_FILENAME_CHARS, "_").slice(0, 80);
}

/** Label, icon, short hint and "can be created from here" for each kind of target. */
function kindMeta(kind) {
    const model = kind.includes(":") ? kind.split(":")[1] : kind;
    const map = {
        "hr.department": { label: _t("Department"), icon: "users" },
        "hr.job": { label: _t("Job position"), icon: "user" },
        "res.groups": { label: _t("User group"), icon: "users" },
        "res.users": { label: _t("User"), icon: "user" },
        menu: { label: _t("Odoo screen"), icon: "menu",
            hint: _t("The menu people open to do this step, e.g. Sales / Orders.") },
        "knowledge.article": { label: _t("Knowledge article"), icon: "book", create: true,
            hint: _t("A detailed instruction in Knowledge. Type a title: pick an existing article or create it.") },
        "documents.document": { label: _t("Document"), icon: "folder",
            hint: _t("A form, template or policy stored in Documents.") },
        "business.process": { label: _t("Other process"), icon: "flow", create: true,
            hint: _t("The process that continues here, or a sub-process. Type a name to find or create it.") },
        "ir.attachment": { label: _t("Attached file"), icon: "record",
            hint: _t("A file attached to this process (paperclip in the chatter).") },
        action: { label: _t("Window action (technical)"), icon: "bolt" },
        url: { label: _t("Web address"), icon: "external",
            hint: _t("A web page or an Odoo address starting with /.") },
    };
    return map[model] || { label: model, icon: "record" };
}

function initials(name) {
    const parts = (name || "").trim().split(WORDS).filter(Boolean);
    return parts.slice(0, 2).map((p) => p.charAt(0).toUpperCase()).join("") || "?";
}

function readPref(key, fallback) {
    try {
        const v = window.localStorage.getItem("o_bpmn_" + key);
        return v === null ? fallback : v === "1";
    } catch {
        return fallback;
    }
}

function writePref(key, value) {
    try {
        window.localStorage.setItem("o_bpmn_" + key, value ? "1" : "0");
    } catch {
    }
}

function readJson(key, fallback) {
    try {
        const v = JSON.parse(window.localStorage.getItem("o_bpmn_" + key));
        return v === null || v === undefined ? fallback : v;
    } catch {
        return fallback;
    }
}

function writeJson(key, value) {
    try {
        window.localStorage.setItem("o_bpmn_" + key, JSON.stringify(value));
    } catch {
    }
}

function isMac() {
    return MAC.test(navigator.platform || navigator.userAgent || "");
}

/** Work instruction → paragraphs and lists ("- item", "1. item"); text only, no HTML. */
function renderInstruction(text) {
    const out = [];
    let para = [];
    let list = null;
    let listTag = null;
    const flushPara = () => {
        if (para.length) {
            out.push(h("p", {}, para.join("\n")));
            para = [];
        }
    };
    const flushList = () => {
        if (list) {
            out.push(list);
            list = null;
            listTag = null;
        }
    };
    for (const raw of text.split("\n")) {
        const line = raw.trim();
        if (!line) {
            flushPara();
            flushList();
            continue;
        }
        const bullet = BULLET.exec(line);
        const num = bullet ? null : NUMBERED.exec(line);
        if (bullet || num) {
            flushPara();
            const tag = bullet ? "ul" : "ol";
            if (listTag !== tag) {
                flushList();
                list = h(tag, {});
                listTag = tag;
            }
            list.append(h("li", {}, (bullet || num)[1]));
        } else {
            flushList();
            para.push(line);
        }
    }
    flushPara();
    flushList();
    return h("div", { "class": "o_bpmn_doc" }, out);
}

export class BpmnApp {
    /**
     * @param {HTMLElement} host
     * @param {{orm, action, notification}} services
     * @param {(values: Object) => Promise} onChange
     * @param {{save?: () => Promise<boolean>}} hooks
     */
    constructor(host, services, onChange, hooks = {}) {
        this.host = host;
        this.orm = services.orm;
        this.action = services.action;
        this.notification = services.notification;
        this.onChange = onChange;
        this.hooks = hooks;
        this.snapshot = null;
        this.instance = null;
        this.mode = null;
        this.lastXml = null;
        this.selected = null;
        this.selection = [];
        this.resolved = {};
        this.options = { record_models: [], responsible_models: [], is_manager: false };
        this.pendingSave = null;
        this.openPickers = new Set();
        this.changedSinceSave = false;
        this.emitted = [];
        this.destroyed = false;
        this.panelOpen = readPref("panel", true);
        this.panelTab = readJson("panel_tab", "content");
        this.collapsed = new Set(readJson("collapsed", []));
        this.panelWidth = Number(readJson("panel_width", PANEL_DEFAULT)) || PANEL_DEFAULT;
        this.minimapOpen = readPref("minimap", false);
        this.gridOn = readPref("grid", true);
        this.typeLabels = getTypeLabels();
        this.reviewReasons = getReviewReasons();
        this.scheduleSave = debounce(() => this.flush(), 400);
        this.scheduleOverlays = debounce(() => this.refreshOverlays(), 150);
        this.buildLayout();
        if (odoo.debug) {
            window.__bpmnApp = this; // handy for support / automated UI checks
        }
    }

    buildLayout() {
        this.canvasEl = h("div", { "class": "o_bpmn_canvas" });
        this.zoomEl = h("div", { "class": "o_bpmn_zoom", role: "group", "aria-label": _t("Zoom") });
        this.helpEl = h("div", { "class": "o_bpmn_help d-none", role: "dialog", "aria-modal": "true" });
        this.stageEl = h("div", { "class": "o_bpmn_stage" }, this.canvasEl, this.zoomEl, this.helpEl);
        this.panelEl = h("aside", { "class": "o_bpmn_panel", "aria-label": _t("Details") });
        this.toolbarEl = h("div", { "class": "o_bpmn_toolbar", role: "toolbar" });
        this.messageEl = h("div", { "class": "o_bpmn_message d-none" });
        this.conflictEl = h("div", { "class": "o_bpmn_conflict d-none", role: "alert" });
        this.root = h("div", { "class": "o_bpmn_app" + (this.panelOpen ? "" : " o_bpmn_panel_closed") },
            this.toolbarEl,
            this.messageEl,
            this.conflictEl,
            h("div", { "class": "o_bpmn_body" }, this.stageEl, this.buildResizer(), this.panelEl),
        );
        this.setPanelWidth(this.panelWidth, false);
        this.host.replaceChildren(this.root);
        this.onKeydown = (ev) => {
            if (ev.key === "Escape") {
                if (!this.helpEl.classList.contains("d-none")) {
                    this.toggleHelp(false);
                } else if (this.root.classList.contains("o_bpmn_fullscreen") &&
                        !document.querySelector(".djs-popup")) {
                    this.toggleFullscreen();
                }
            }
        };
        document.addEventListener("keydown", this.onKeydown);
        this.onPageHide = () => {
            if (this.presenceId) {
                try {
                    fetch("/web/dataset/call_kw/business.process/bpmn_editing_ping", {
                        method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: {
                            model: "business.process", method: "bpmn_editing_ping", args: [this.presenceId, true], kwargs: {} } }),
                    }).catch(() => {});
                } catch {
                }
            }
        };
        window.addEventListener("pagehide", this.onPageHide);
        // The field renders before its tab has its final size: re-fit on resize until the user moves the view.
        if (window.ResizeObserver) {
            this.resizeObserver = new ResizeObserver(() => {
                if (!this.instance || !this.canvasEl.clientWidth) {
                    return;
                }
                this.instance.get("canvas").resized();
                if (!this.viewTouched) {
                    this.fit();
                }
            });
            this.resizeObserver.observe(this.stageEl);
        }
        this.stageEl.addEventListener("wheel", () => (this.viewTouched = true), { passive: true });
        this.stageEl.addEventListener("pointerdown", () => (this.viewTouched = true));
        this.root.addEventListener("keydown", (ev) => {
            if (ev.defaultPrevented) {
                return;
            }
            if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key || "").toLowerCase() === "s") {
                ev.preventDefault();
                ev.stopPropagation();
                const target = ev.target;
                if (target && target.dispatchEvent && ["INPUT", "TEXTAREA"].includes(target.tagName)) {
                    target.dispatchEvent(new Event("change", { bubbles: true }));
                }
                this.saveRecord();
            } else if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && (ev.key || "").toLowerCase() === "p") {
                ev.preventDefault();
                ev.stopPropagation();
                this.openPrint();
            }
        });
    }

    /** Drag handle on the left edge of the side panel (double-click: default width). */
    buildResizer() {
        const handle = h("div", { "class": "o_bpmn_resizer", role: "separator", tabindex: "0",
            "aria-orientation": "vertical", "aria-label": _t("Panel width"),
            title: _t("Drag to change the panel width. Double-click: default width.") });
        handle.addEventListener("pointerdown", (ev) => {
            if (ev.button !== 0) {
                return;
            }
            ev.preventDefault();
            handle.setPointerCapture(ev.pointerId);
            this.root.classList.add("o_bpmn_resizing");
            const right = this.root.querySelector(".o_bpmn_body").getBoundingClientRect().right;
            const move = (e) => this.setPanelWidth(right - e.clientX, false);
            const up = () => {
                handle.removeEventListener("pointermove", move);
                handle.removeEventListener("pointerup", up);
                handle.removeEventListener("pointercancel", up);
                this.root.classList.remove("o_bpmn_resizing");
                this.setPanelWidth(this.panelWidth, true);
            };
            handle.addEventListener("pointermove", move);
            handle.addEventListener("pointerup", up);
            handle.addEventListener("pointercancel", up);
        });
        handle.addEventListener("dblclick", () => this.setPanelWidth(PANEL_DEFAULT, true));
        handle.addEventListener("keydown", (ev) => {
            if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
                ev.preventDefault();
                this.setPanelWidth(this.panelWidth + (ev.key === "ArrowLeft" ? 20 : -20), true);
            }
        });
        return handle;
    }

    setPanelWidth(width, save) {
        const body = this.root && this.root.querySelector(".o_bpmn_body");
        const room = body && body.clientWidth ? Math.round(body.clientWidth * 0.6) : PANEL_MAX;
        this.panelWidth = Math.round(Math.max(PANEL_MIN, Math.min(width, PANEL_MAX, Math.max(PANEL_MIN, room))));
        this.root.style.setProperty("--bpmn-panel-width", this.panelWidth + "px");
        if (save) {
            writeJson("panel_width", this.panelWidth);
        }
    }

    tbButton(title, iconName, onclick, extra = {}) {
        const { label, cls, shortcut, keepFocus, ...attrs } = extra;
        const tip = shortcut ? title + " (" + shortcut + ")" : title;
        return h("button", { type: "button", "class": "o_bpmn_tb_btn" + (cls ? " " + cls : ""),
            title: tip, "aria-label": title, ...attrs,
            onclick: (ev) => {
                onclick(ev);
                if (!keepFocus) {
                    this.focusCanvas();
                }
            } },
        icon(iconName, 18), label ? h("span", { "class": "o_bpmn_tb_label" }, label) : null);
    }

    renderToolbar() {
        const modeler = this.mode === "modeler";
        const cmd = isMac() ? "⌘" : "Ctrl";
        this.statusEl = h("span", { "class": "o_bpmn_status" });
        this.presenceEl = h("span", { "class": "o_bpmn_presence d-none", role: "status" });
        this.editBtn = h("button", { type: "button", "class": "o_bpmn_edit_btn d-none",
            onclick: () => this.startEditing() });
        this.editHelp = this.helpLink("edit");
        this.editHelp.classList.add("d-none");
        const left = [this.statusEl, this.editBtn, this.editHelp, this.presenceEl];
        if (modeler) {
            left.push(h("span", { "class": "o_bpmn_tb_sep" }));
            left.push(this.tbButton(_t("Undo"), "undo", () => this.instance.get("commandStack").undo(),
                { shortcut: cmd + "+Z" }));
            left.push(this.tbButton(_t("Redo"), "redo", () => this.instance.get("commandStack").redo(),
                { shortcut: cmd + "+Y" }));
        }
        left.push(h("span", { "class": "o_bpmn_tb_sep" }));
        left.push(this.tbButton(_t("Find an element"), "search", () => this.openSearch(),
            { shortcut: modeler ? cmd + "+F" : null, keepFocus: !modeler }));
        this.reviewBtn = h("button", { type: "button", "class": "o_bpmn_review_btn d-none",
            title: _t("Go to the next item to review"), onclick: () => this.selectNextReview() });
        left.push(this.reviewBtn);

        const dl = (label, hint, fmt) => h("button", { type: "button", "class": "o_bpmn_menu_item",
            onclick: () => this.download(fmt) }, h("span", {}, label), h("small", {}, hint));
        const menu = h("div", { "class": "o_bpmn_menu" },
            dl(_t("BPMN 2.0"), ".bpmn", "bpmn"),
            dl(_t("draw.io (last saved version)"), ".drawio", "drawio"),
            dl(_t("Image"), ".svg", "svg"),
            dl(_t("Image"), ".png", "png"),
            h("div", { "class": "o_bpmn_menu_sep" }),
            h("button", { type: "button", "class": "o_bpmn_menu_item", onclick: () => this.openPrint() },
                h("span", {}, _t("Print / PDF...")), h("small", {}, isMac() ? "⌘P" : "Ctrl+P")),
        );
        const dlBtn = this.tbButton(_t("Download"), "download", () => menu.classList.toggle("show"),
            { keepFocus: true });
        this.onDocClick = this.onDocClick || ((ev) => {
            if (!ev.target.closest || !ev.target.closest(".o_bpmn_dropdown")) {
                this.root.querySelectorAll(".o_bpmn_menu.show").forEach((m) => m.classList.remove("show"));
            }
        });
        document.removeEventListener("click", this.onDocClick, true);
        document.addEventListener("click", this.onDocClick, true);

        this.minimapBtn = this.tbButton(_t("Minimap"), "map", () => this.toggleMinimap(), { shortcut: "M" });
        const right = [h("div", { "class": "o_bpmn_dropdown" }, dlBtn, menu),
            h("span", { "class": "o_bpmn_tb_sep" }), this.minimapBtn];
        if (modeler) {
            this.gridBtn = this.tbButton(_t("Grid"), "grid", () => this.toggleGrid(), { shortcut: "G" });
            right.push(this.gridBtn);
        } else {
            this.gridBtn = null;
        }
        right.push(this.tbButton(_t("Keyboard shortcuts"), "keyboard", () => this.toggleHelp(),
            { shortcut: "?", keepFocus: true }));
        right.push(this.tbButton(_t("User guide"), "help", () => this.openGuide(), { keepFocus: true }));
        this.panelBtn = this.tbButton(_t("Side panel"), "sidebar", () => this.togglePanel(), { shortcut: "P" });
        right.push(this.panelBtn);
        this.fullBtn = this.tbButton(_t("Full screen"), "expand", () => this.toggleFullscreen(), { shortcut: "F" });
        right.push(this.fullBtn);
        this.toolbarEl.replaceChildren(
            h("div", { "class": "o_bpmn_tb_group" }, left),
            h("span", { "class": "flex-grow-1" }),
            h("div", { "class": "o_bpmn_tb_group" }, right),
        );
        this.renderStatus();
        this.renderPresence();
        this.renderZoom();
        this.syncToggles();
    }

    renderStatus() {
        if (!this.statusEl) {
            return;
        }
        const snap = this.snapshot || {};
        const editing = this.mode === "modeler";
        let hint = "";
        if (!editing && snap.isManager && snap.state && snap.state !== "draft") {
            hint = snap.state === "review" ? _t("Send it back to draft to edit.")
                : _t("Create a new version to edit.");
        }
        this.statusEl.className = "o_bpmn_status " + (editing ? "o_bpmn_status_edit" : "o_bpmn_status_view");
        this.statusEl.title = hint;
        this.statusEl.replaceChildren(h("i", {}), editing ? _t("Editing") : _t("Read only"));
        const how = this.editHow();
        if (this.editBtn) {
            this.editBtn.classList.toggle("d-none", !how);
            this.editHelp.classList.toggle("d-none", !how);
            this.editBtn.title = how ? how.help : "";
            this.editBtn.replaceChildren(...(how ? [icon(how.icon, 14), how.label] : []));
        }
    }

    /** How a manager gets from this read-only version to an editable one (null: nothing to offer). */
    editHow() {
        const snap = this.snapshot || {};
        if (this.mode === "modeler" || !snap.isManager || !snap.resId || !snap.state || snap.state === "draft") {
            return null;
        }
        if (snap.state === "review") {
            return { method: "action_back_to_draft", icon: "undo", label: _t("Back to draft to edit"),
                help: _t("The version in review becomes an editable draft again.") };
        }
        if (snap.isLatest) {
            return { method: "action_new_version", icon: "plus", label: _t("New version to edit"),
                help: _t("Creates an editable draft copy. This version stays valid until the new one is published.") };
        }
        if (snap.otherVersion) {
            return { method: "action_open_other_version", icon: "right",
                label: snap.otherVersionLabel ? _t("Open %s", snap.otherVersionLabel) : _t("Open the current version"),
                help: _t("Changes are made in another version of this process.") };
        }
        return null;
    }

    async startEditing() {
        const how = this.editHow();
        if (!how) {
            return;
        }
        this.editBtn.disabled = true;
        try {
            if (this.hooks.save) {
                await this.hooks.save(); // other fields of the form may have changes
            }
            const result = await this.orm.call("business.process", how.method, [[this.snapshot.resId]]);
            if (result && typeof result === "object") {
                if (this.root.classList.contains("o_bpmn_fullscreen")) {
                    this.toggleFullscreen();
                }
                await this.action.doAction(result);
            } else if (this.hooks.load) {
                await this.hooks.load();
            }
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            this.notification.add(msg, { type: "danger" });
        } finally {
            if (this.editBtn) {
                this.editBtn.disabled = false;
            }
        }
    }

    renderZoom() {
        const zoomBy = (f) => {
            const c = this.instance && this.instance.get("canvas");
            if (c) {
                c.zoom(Math.min(4, Math.max(0.2, c.zoom() * f)));
            }
        };
        this.zoomLabel = h("button", { type: "button", "class": "o_bpmn_zoom_label", title: _t("Reset zoom to 100%"),
            onclick: () => {
                if (this.instance) {
                    this.instance.get("canvas").zoom(1, "auto");
                }
            } }, "100%");
        this.zoomEl.replaceChildren(
            this.tbButton(_t("Zoom out"), "minus", () => zoomBy(1 / 1.2), { shortcut: (isMac() ? "⌘" : "Ctrl") + " -" }),
            this.zoomLabel,
            this.tbButton(_t("Zoom in"), "plus", () => zoomBy(1.2), { shortcut: (isMac() ? "⌘" : "Ctrl") + " +" }),
            h("span", { "class": "o_bpmn_tb_sep" }),
            this.tbButton(_t("Fit to screen"), "fit", () => this.fit(), { shortcut: "0" }),
        );
    }

    updateZoomLabel() {
        if (this.zoomLabel && this.instance) {
            this.zoomLabel.textContent = Math.round(this.instance.get("canvas").zoom() * 100) + "%";
        }
    }

    syncToggles() {
        const set = (btn, on) => btn && btn.classList.toggle("active", !!on);
        set(this.minimapBtn, this.minimapOpen);
        set(this.gridBtn, this.gridOn);
        set(this.panelBtn, this.panelOpen);
        const full = this.root.classList.contains("o_bpmn_fullscreen");
        if (this.fullBtn) {
            this.fullBtn.replaceChildren(icon(full ? "compress" : "expand", 18));
        }
    }

    focusCanvas() {
        try {
            if (this.instance) {
                this.instance.get("canvas").focus();
            }
        } catch {
        }
    }

    toggleFullscreen() {
        this.root.classList.toggle("o_bpmn_fullscreen");
        this.syncToggles();
        if (this.instance) {
            this.instance.get("canvas").resized();
            this.fit();
        }
    }

    togglePanel(open) {
        this.panelOpen = open === undefined ? !this.panelOpen : !!open;
        writePref("panel", this.panelOpen);
        this.root.classList.toggle("o_bpmn_panel_closed", !this.panelOpen);
        this.syncToggles();
        if (this.instance) {
            this.instance.get("canvas").resized();
        }
    }

    toggleMinimap() {
        const minimap = this.instance && this.instance.get("minimap", false);
        if (!minimap) {
            return;
        }
        minimap.toggle();
        this.minimapOpen = minimap.isOpen();
        writePref("minimap", this.minimapOpen);
        this.syncToggles();
    }

    toggleGrid() {
        const grid = this.instance && this.instance.get("grid", false);
        if (!grid) {
            return;
        }
        this.gridOn = !grid.isVisible();
        grid.toggle(this.gridOn);
        writePref("grid", this.gridOn);
        this.syncToggles();
    }

    openSearch() {
        const pad = this.mode === "modeler" && this.instance && this.instance.get("searchPad", false);
        if (pad) {
            pad.toggle();
            return;
        }
        if (this.instance) {
            const sel = this.instance.get("selection", false);
            if (sel) {
                sel.select(null);
            }
        }
        this.selected = null;
        this.togglePanel(true);
        this.renderPanel();
        const input = this.panelEl.querySelector(".o_bpmn_find input");
        if (input) {
            input.focus();
        }
    }

    async saveRecord() {
        if (this.mode !== "modeler" || !this.hooks.save) {
            return;
        }
        if (this.importFailed) {
            this.notification.add(_t("The stored diagram could not be opened, so changes on this canvas are not saved. Import the diagram again or restore a previous version."), { type: "warning" });
            return;
        }
        try {
            await this.flush();
            const ok = await this.hooks.save();
            if (ok !== false) {
                this.notification.add(_t("Saved"), { type: "success" });
            } else {
                this.pingPresence();
            }
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            this.notification.add(msg, { type: "danger" });
            this.pingPresence();
        }
    }

    /** User guide in the user's language, at a section when given (e.g. "print"). */
    openGuide(section) {
        window.open(GUIDE_URL + (section ? "#" + section : ""), "_blank", "noopener");
    }

    toggleHelp(show) {
        const visible = show === undefined ? this.helpEl.classList.contains("d-none") : !!show;
        if (!visible) {
            this.helpEl.classList.add("d-none");
            this.focusCanvas();
            return;
        }
        const cmd = isMac() ? "⌘" : "Ctrl";
        const row = (keys, text) => h("div", { "class": "o_bpmn_kbd_row" },
            h("span", { "class": "o_bpmn_kbd_keys" }, keys.map((k, i) => [i ? h("span", { "class": "o_bpmn_kbd_plus" }, "+") : null,
                h("kbd", {}, k)])),
            h("span", {}, text));
        const group = (title, rows) => h("div", { "class": "o_bpmn_kbd_group" }, h("h6", {}, title), rows);
        const general = group(_t("View"), [
            row(["?"], _t("Show this help")),
            row(["F"], _t("Full screen")),
            row(["P"], _t("Show or hide the side panel")),
            row(["M"], _t("Minimap")),
            row(["0"], _t("Fit diagram to screen")),
            row([cmd, "P"], _t("Print or save as PDF")),
            row([cmd, "+ / -"], _t("Zoom in / out (or mouse wheel with Ctrl)")),
            row([_t("Drag")], _t("Move the canvas (drag the empty background)")),
            row(["Esc"], _t("Close menus, leave full screen")),
        ]);
        const groups = [general];
        if (this.mode === "modeler") {
            groups.push(group(_t("Edit"), [
                row([cmd, "S"], _t("Save")),
                row([cmd, "Z"], _t("Undo")),
                row([cmd, "Y"], _t("Redo")),
                row([cmd, "C"], _t("Copy")),
                row([cmd, "V"], _t("Paste")),
                row([cmd, "A"], _t("Select all")),
                row([cmd, "F"], _t("Find an element")),
                row(["Del"], _t("Delete the selection")),
                row(["← ↑ → ↓"], _t("Move the selection (Shift: faster)")),
            ]));
            groups.push(group(_t("Draw"), [
                row(["A"], _t("Append an element after the selected one")),
                row(["N"], _t("Create an element (with search)")),
                row(["E"], _t("Edit the text (or double-click)")),
                row([cmd, "B / I / U"], _t("Bold / italic / underline text")),
                row([cmd, "Shift", "> <"], _t("Larger / smaller text")),
                row(["R"], _t("Change the type of the selected element")),
                row(["C"], _t("Connect tool")),
                row(["H"], _t("Hand tool")),
                row(["L"], _t("Lasso tool: select several elements")),
                row(["S"], _t("Space tool: make or remove room")),
                row(["G"], _t("Show or hide the grid")),
            ]));
        }
        const close = h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Close"),
            "aria-label": _t("Close"), onclick: () => this.toggleHelp(false) }, icon("close"));
        const card = h("div", { "class": "o_bpmn_help_card" },
            h("div", { "class": "o_bpmn_help_head" }, icon("keyboard", 20), h("h5", {}, _t("Keyboard shortcuts")),
                this.helpLink("keys"), close),
            h("p", { "class": "o_bpmn_muted" }, _t("Shortcuts work when the diagram has the focus: click on the canvas first.")),
            h("div", { "class": "o_bpmn_kbd_grid" }, groups),
            h("div", { "class": "o_bpmn_help_foot" },
                h("button", { type: "button", "class": "o_bpmn_btn_sm", onclick: () => this.openGuide("keys") },
                    icon("book", 14), _t("Open the user guide"))),
        );
        this.helpEl.replaceChildren(card);
        this.helpEl.onclick = (ev) => {
            if (ev.target === this.helpEl) {
                this.toggleHelp(false);
            }
        };
        this.helpEl.classList.remove("d-none");
        close.focus();
    }

    fit() {
        if (!this.instance) {
            return;
        }
        const canvas = this.instance.get("canvas");
        canvas.zoom("fit-viewport", "auto");
        if (canvas.zoom() > 1.2) {
            canvas.zoom(1.0, "auto");
        }
        this.updateZoomLabel();
    }

    showMessage(text, type = "danger") {
        this.messageEl.className = "o_bpmn_message alert alert-" + type + " m-2";
        this.messageEl.textContent = text;
    }

    clearMessage() {
        this.messageEl.className = "o_bpmn_message d-none";
        this.messageEl.textContent = "";
    }

    async start(snapshot) {
        this.canvasEl.append(h("div", { "class": "o_bpmn_loading" }, h("span", { "class": "o_bpmn_spinner" }),
            _t("Loading diagram...")));
        try {
            const [lib, options] = await Promise.all([
                loadBpmnLib(),
                this.orm.call("business.process", "bpmn_get_options", []),
            ]);
            this.lib = lib;
            this.options = options;
        } catch (e) {
            this.showMessage(_t("The diagram library could not be loaded."));
            throw e;
        }
        if (this.destroyed) {
            return;
        }
        // snapshots received while the library was loading are newer than the mount one
        const latest = this.snapshot || snapshot;
        if (latest) {
            await this.update(latest);
        }
    }

    /** Snapshots are applied one after the other; only the newest pending one counts. */
    update(snapshot) {
        this.nextSnapshot = snapshot;
        this.updateChain = (this.updateChain || Promise.resolve()).then(() => {
            const snap = this.nextSnapshot;
            this.nextSnapshot = null;
            return snap ? this._update(snap) : undefined;
        }).catch((e) => console.error(e));
        return this.updateChain;
    }

    async _update(snapshot) {
        const sameRecord = !this.snapshot || this.snapshot.resId === snapshot.resId;
        if (!sameRecord) {
            this.emitted = [];
            this.importedXml = null;
                    }
        if (snapshot.focusElement) {
            this.pendingFocus = snapshot.focusElement;
        }
        this.snapshot = snapshot;
        if (!this.lib || this.destroyed) {
            return;
        }
        const mode = snapshot.editable ? "modeler" : "viewer";
        const value = snapshot.value || "";
        if (value === this.lastXml || !sameRecord) {
            // the server holds what we have: later saves are based on its revision
            this.baseRevision = snapshot.revision;
        }
        this.updatePresence(mode === "modeler" ? snapshot.resId : null);
        if (mode !== this.mode) {
            await this.createInstance(mode);
            await this.importXml(value);
        } else if (value !== this.lastXml) {
            const discarded = this.forceImport || (!snapshot.dirty && value === this.importedXml);
            if (sameRecord && !discarded && this.mode === "modeler" && (this.pendingSave || this.changedSinceSave)) {
                // a save of ours is on its way and the record may show the previous value: the canvas is newer
                this.renderStatus();
                return;
            }
            if (!this.forceImport && snapshot.dirty && this.emitted.length &&
                    (this.emitted.includes(value) || value === this.importedXml)) {
                // stale echo of our own earlier edit or of the starting value
                // (the record updates after an onchange): keep the canvas
                this.renderStatus();
                return;
            }
            this.emitted = [];
            this.forceImport = false;
            await this.importXml(value);
        }
        this.renderStatus();
    }

    async createInstance(mode) {
        if (this.instance) {
            this.instance.destroy();
            this.instance = null;
        }
        this.canvasEl.replaceChildren();
        this.mode = mode;
        this.root.classList.toggle("o_bpmn_is_viewer", mode !== "modeler");
        const terms = getBpmnTerms();
        const translateModule = {
            translate: ["value", (template, replacements) => {
                const tpl = terms[template] || template;
                return tpl.replace(PLACEHOLDER, (_, key) =>
                    replacements && key in replacements ? replacements[key] : "{" + key + "}");
            }],
        };
        const modeler = mode === "modeler";
        const Ctor = modeler ? this.lib.Modeler : this.lib.NavigatedViewer;
        const extra = (modeler ? this.lib.modelerModules : this.lib.viewerModules) || [];
        this.instance = new Ctor({
            container: this.canvasEl,
            moddleExtensions: { odoo: this.lib.odooModdle, odoostyle: this.lib.odooStyleModdle },
            additionalModules: [translateModule, ...extra],
            bpmnRenderer: { defaultFillColor: DEFAULT_FILL, defaultStrokeColor: DEFAULT_STROKE },
            textRenderer: {
                defaultStyle: { fontFamily: FONT, fontSize: 12, fontWeight: "normal", lineHeight: 1.2 },
                externalStyle: { fontSize: 11 },
            },
            colorPicker: { colors: COLOR_PRESETS.map((c) => ({ label: c.label, fill: c.fill, stroke: c.stroke })) },
            minimap: { open: this.minimapOpen },
        });
        const bus = this.instance.get("eventBus");
        bus.on("selection.changed", ({ newSelection }) => {
            // clicking the text of an arrow or event selects its label: show the element itself
            const seen = new Set();
            this.selection = [];
            for (const e of newSelection || []) {
                const target = e.labelTarget || e;
                if (!seen.has(target)) {
                    seen.add(target);
                    this.selection.push(target);
                }
            }
            this.selected = this.selection.length === 1 ? this.selection[0] : null;
            this.renderPanel();
        });
        bus.on("canvas.viewbox.changed", () => this.updateZoomLabel());
        bus.on("odoo.save", () => this.saveRecord());
        bus.on("odoo.shortcuts", () => this.toggleHelp());
        bus.on("odoo.fullscreen", () => this.toggleFullscreen());
        bus.on("odoo.minimap", () => this.toggleMinimap());
        bus.on("odoo.grid", () => this.toggleGrid());
        bus.on("odoo.fit", () => this.fit());
        bus.on("odoo.panel", () => this.togglePanel());
        bus.on("odoo.text", (ev) => this.textShortcut(ev));
        bus.on("minimap.toggle", ({ open }) => {
            this.minimapOpen = !!open;
            this.syncToggles();
        });
        if (!modeler) {
            bus.on("element.click", ({ element }) => {
                this.selected = element && !CONTAINERS.includes(element.type) ? element : null;
                this.selection = this.selected ? [this.selected] : [];
                this.renderPanel();
            });
        } else {
            bus.on("commandStack.changed", () => {
                this.changedSinceSave = true;
                this.scheduleSave();
                this.scheduleOverlays();
                const reg = this.instance.get("elementRegistry");
                this.selection = this.selection.map((e) => reg.get(e.id)).filter(Boolean);
                if (this.selected) {
                    this.selected = reg.get(this.selected.id) || null;
                }
                this.renderPanelSoon();
            });
        }
        this.renderToolbar();
    }

    async importXml(xml) {
        this.clearMessage();
        let toImport = xml;
        let laidOut = false;
        if (xml && !HAS_DI.test(xml) && HAS_PROCESS.test(xml)) {
            try {
                toImport = await this.lib.layoutProcess(xml);
                laidOut = true;
            } catch {
                // keep the original: bpmn-js will show an empty canvas + warning
            }
        }
        try {
            const result = await this.instance.importXML(toImport);
            if (result.warnings && result.warnings.length && this.snapshot && this.snapshot.isManager) {
                console.warn("BPMN import warnings", result.warnings);
            }
        } catch (e) {
            this.lastXml = xml;
            this.importFailed = true; // never autosave an empty canvas over the stored diagram
            this.root.classList.add("o_bpmn_import_failed");
            this.showMessage(_t("The diagram could not be displayed: %s", e.message || e));
            return;
        }
        this.importFailed = false;
        this.root.classList.remove("o_bpmn_import_failed");
        this.baseRevision = this.snapshot ? this.snapshot.revision : 0;
        if (this.conflict) {
            this.renderConflict(null);
        }
        this.lastXml = xml;
        this.importedXml = xml;
        this.viewTouched = false;
        this.changedSinceSave = false;
        this.selected = null;
        this.selection = [];
        const grid = this.instance.get("grid", false);
        if (grid) {
            grid.toggle(this.gridOn);
        }
        this.fit();
        await this.resolveReferences();
        this.refreshOverlays();
        this.renderPanel();
        if (laidOut && this.mode === "modeler") {
            this.changedSinceSave = true;
            this.notification.add(_t("The diagram had no layout and was arranged automatically."),
                { type: "info" });
            this.scheduleSave();
        }
        const focus = this.pendingFocus;
        if (focus) {
            this.pendingFocus = null;
            this.focusElement(focus);
        }
    }

    focusElement(id) {
        const reg = this.instance.get("elementRegistry");
        const el = reg.get(id);
        if (!el) {
            return;
        }
        const sel = this.instance.get("selection", false);
        if (sel) {
            sel.select(el);
        }
        this.selected = el;
        this.selection = [el];
        this.renderPanel();
        try {
            this.instance.get("canvas").scrollToElement(el, { top: 120, bottom: 120, left: 200, right: 200 });
        } catch {
        }
    }

    async flush() {
        this.scheduleSave.cancel();
        if (!this.instance || this.mode !== "modeler" || this.destroyed) {
            return;
        }
        // Loop: edits made while a save is running must be pushed too.
        while (this.pendingSave || this.changedSinceSave) {
            if (!this.pendingSave) {
                this.changedSinceSave = false;
                this.pendingSave = this._save().finally(() => (this.pendingSave = null));
            }
            await this.pendingSave;
        }
    }

    /** Push the canvas to the record (the thumbnail is drawn by the server on save). */
    async _save() {
        const inst = this.instance;
        if (this.importFailed || !inst || this.destroyed) {
            return;
        }
        const definitions = inst.getDefinitions();
        for (const el of (definitions && definitions.rootElements) || []) {
            if (el.$type === "bpmn:Process") {
                el.isExecutable = false;
            }
        }
        const { xml } = await inst.saveXML({ format: true });
        if (xml === this.lastXml || inst !== this.instance) {
            return;
        }
        this.lastXml = xml;
        this.emitted.push(xml);
        if (this.emitted.length > 20) {
            this.emitted.shift();
        }
        await this.onChange({ bpmn_xml: xml, bpmn_save_base: this.saveBase() });
    }

    /** "<revision>:<token>" sent with each change; the server refuses it if someone else saved after that revision. */
    saveBase() {
        if (!this.editorToken) {
            this.editorToken = Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
        }
        return (this.baseRevision || 0) + ":" + this.editorToken;
    }

    /** Synchronous save for page unload (WILL_SAVE_URGENTLY):
     *  Odoo reads the changes right after the event, so async flush() is too late. */
    flushUrgent() {
        this.scheduleSave.cancel();
        if (this.mode !== "modeler" || this.importFailed || this.destroyed || !this.instance || !this.changedSinceSave) {
            return;
        }
        let xml;
        try {
            xml = this.lib.toXMLSync(this.instance.getDefinitions());
        } catch {
            return;
        }
        if (!xml || xml === this.lastXml) {
            return;
        }
        this.lastXml = xml;
        this.emitted.push(xml);
        this.changedSinceSave = false;
        this.onChange({ bpmn_xml: xml, bpmn_save_base: this.saveBase() });
    }

    /** Start / stop the heartbeat for the draft being edited (null: none). */
    updatePresence(resId) {
        if (resId === this.presenceId) {
            return;
        }
        if (this.presenceId) {
            this.orm.call("business.process", "bpmn_editing_ping", [this.presenceId, true]).catch(() => {});
        }
        clearInterval(this.presenceTimer);
        this.presenceId = resId || null;
        this.otherEditors = [];
        this.renderPresence();
        if (!this.presenceId) {
            return;
        }
        const ping = () => this.pingPresence();
        ping();
        this.presenceTimer = setInterval(ping, 60000);
    }

    /** Heartbeat: who else is editing, and did someone save after we read the diagram? */
    async pingPresence() {
        const id = this.presenceId;
        if (!id) {
            return;
        }
        try {
            const res = await this.orm.call("business.process", "bpmn_editing_ping", [id, false, this.saveBase()]);
            if (id === this.presenceId && !this.destroyed && res) {
                this.otherEditors = res.others || [];
                this.renderPresence();
                this.renderConflict(res.conflict);
            }
        } catch {
        }
    }

    /** Banner when the stored diagram is newer than the one on the canvas. */
    renderConflict(conflict) {
        this.conflict = conflict || null;
        if (!conflict) {
            this.conflictEl.classList.add("d-none");
            this.conflictEl.replaceChildren();
            return;
        }
        this.conflictEl.classList.remove("d-none");
        this.conflictEl.replaceChildren(
            icon("warning", 18),
            h("div", { "class": "o_bpmn_conflict_text" },
                h("b", {}, _t("%(user)s saved a newer version at %(time)s.", conflict)),
                h("span", {}, this.changedSinceSave || (this.snapshot && this.snapshot.dirty)
                    ? _t("Your changes on this canvas cannot be saved over it. Keep a copy of your version, then load theirs and redo your changes (or import your copy).")
                    : _t("Load it before you continue, otherwise your next change cannot be saved."))),
            this.helpLink("concurrent"),
            h("button", { type: "button", "class": "o_bpmn_btn_sm", onclick: () => this.download("bpmn") },
                icon("download", 14), _t("Download my version")),
            h("button", { type: "button", "class": "o_bpmn_primary", onclick: () => this.reloadSaved() },
                icon("reset", 14), _t("Load the saved version")));
    }

    /** Drop the local changes and show what is stored now. */
    async reloadSaved() {
        if (!this.hooks.reload) {
            return;
        }
        this.scheduleSave.cancel();
        this.changedSinceSave = false;
        this.forceImport = true; // the next snapshot replaces the canvas, whatever it holds
        try {
            await this.hooks.reload();
        } catch (e) {
            this.forceImport = false;
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            this.notification.add(msg, { type: "danger" });
            return;
        }
        this.renderConflict(null);
    }

    renderPresence() {
        if (!this.presenceEl) {
            return;
        }
        const others = this.otherEditors || [];
        this.presenceEl.classList.toggle("d-none", !others.length);
        this.presenceEl.replaceChildren(...(others.length ? [icon("users", 14),
            h("span", {}, _t("Also editing: %s", others.map((o) => o.name).join(", ")))] : []));
        this.presenceEl.onclick = () => this.openGuide("concurrent");
        this.presenceEl.title = others.length
            ? _t("Another manager has this diagram open. The first one to save wins; the other one is warned and keeps a copy.")
            : "";
    }

    /** One panel refresh per frame, however many commands ran (large diagrams). */
    renderPanelSoon() {
        if (this._panelFrame) {
            return;
        }
        this._panelFrame = requestAnimationFrame(() => {
            this._panelFrame = null;
            if (!this.destroyed && this.instance) {
                this.renderPanel();
            }
        });
    }

    destroy() {
        this.destroyed = true;
        this.updatePresence(null);
        if (this._panelFrame) {
            cancelAnimationFrame(this._panelFrame);
        }
        if (window.__bpmnApp === this) {
            delete window.__bpmnApp;
        }
        this.scheduleSave.cancel();
        this.scheduleOverlays.cancel();
        document.removeEventListener("keydown", this.onKeydown);
        window.removeEventListener("pagehide", this.onPageHide);
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        if (this.onDocClick) {
            document.removeEventListener("click", this.onDocClick, true);
        }
        if (this.instance) {
            this.instance.destroy();
            this.instance = null;
        }
    }

    extValues(bo, type) {
        const ext = bo && bo.extensionElements;
        return ((ext && ext.values) || []).filter((v) => v.$instanceOf && v.$instanceOf(type));
    }

    links(bo) {
        return this.extValues(bo, "odoo:Link");
    }

    responsible(bo) {
        return this.extValues(bo, "odoo:Responsible")[0] || null;
    }

    review(bo) {
        const r = this.extValues(bo, "odoo:Review")[0];
        return r && (r.status || "pending") === "pending" ? r : null;
    }

    documentation(bo) {
        return ((bo && bo.documentation) || []).map((d) => d.text || "").join("\n").trim();
    }

    setExtValues(element, type, newValues) {
        const modeling = this.instance.get("modeling");
        const moddle = this.instance.get("moddle");
        const bo = element.businessObject;
        let ext = bo.extensionElements;
        if (!ext) {
            ext = moddle.create("bpmn:ExtensionElements", { values: [] });
            modeling.updateModdleProperties(element, bo, { extensionElements: ext });
        }
        const others = (ext.values || []).filter((v) => !(v.$instanceOf && v.$instanceOf(type)));
        modeling.updateModdleProperties(element, ext, { values: [...others, ...newValues] });
    }

    createExt(type, attrs) {
        const moddle = this.instance.get("moddle");
        const clean = {};
        for (const [k, v] of Object.entries(attrs)) {
            if (v !== undefined && v !== null && v !== false && v !== "") {
                clean[k] = v;
            }
        }
        return moddle.create(type, clean);
    }

    async resolveReferences() {
        const refs = [];
        const reg = this.instance.get("elementRegistry");
        for (const el of reg.getAll()) {
            const bo = el.businessObject;
            if (!bo || el.labelTarget) {
                continue;
            }
            this.links(bo).forEach((lk, idx) => refs.push({
                key: el.id + ":link:" + idx, linkType: lk.linkType, model: lk.model,
                resId: lk.resId, xmlid: lk.xmlid, url: lk.url,
            }));
            const resp = this.responsible(bo);
            if (resp) {
                refs.push({ key: el.id + ":resp", linkType: "record", model: resp.model,
                    resId: resp.resId, xmlid: resp.xmlid });
            }
        }
        this.resolved = {};
        if (!refs.length) {
            return;
        }
        try {
            this.resolved = await this.orm.call("business.process", "bpmn_resolve", [refs]);
        } catch {
            this.resolved = {};
        }
    }

    reviewItems() {
        const reg = this.instance ? this.instance.get("elementRegistry") : null;
        if (!reg) {
            return [];
        }
        const out = [];
        for (const el of reg.getAll()) {
            if (el.labelTarget || !el.businessObject) {
                continue;
            }
            const bo = el.businessObject;
            const rv = this.review(bo);
            let broken = false;
            this.links(bo).forEach((_lk, idx) => {
                const r = this.resolved[el.id + ":link:" + idx];
                if (r && !r.ok) {
                    broken = true;
                }
            });
            const resp = this.resolved[el.id + ":resp"];
            if (resp && !resp.ok) {
                broken = true;
            }
            if (rv || broken) {
                out.push({ element: el, reason: rv ? rv.reason : "link_broken", broken });
            }
        }
        return out;
    }

    refreshOverlays() {
        if (!this.instance) {
            return;
        }
        const overlays = this.instance.get("overlays");
        overlays.remove({ type: "odoo-review" });
        overlays.remove({ type: "odoo-link" });
        const isManager = this.snapshot && this.snapshot.isManager;
        const reg = this.instance.get("elementRegistry");
        for (const el of reg.getAll()) {
            if (el.labelTarget || !el.businessObject || el.waypoints) {
                continue;
            }
            const n = this.links(el.businessObject).length;
            if (n && el.type !== "bpmn:Lane" && el.type !== "bpmn:Participant") {
                overlays.add(el.id, "odoo-link", {
                    position: { bottom: 8, left: -8 },
                    html: h("div", { "class": "o_bpmn_badge o_bpmn_badge_link", title: _t("%s link(s)", n) },
                        icon("link", 12)),
                });
            }
        }
        const items = isManager ? this.reviewItems() : [];
        for (const item of items) {
            const el = item.element;
            const pos = el.type === "bpmn:Lane" || el.type === "bpmn:Participant"
                ? { top: 4, left: 34 } : { top: -10, right: 10 };
            overlays.add(el.id, "odoo-review", {
                position: pos,
                html: h("div", { "class": "o_bpmn_badge o_bpmn_badge_review",
                    title: this.reviewReasons[item.reason] || this.reviewReasons.imported }, "!"),
            });
        }
        if (this.reviewBtn) {
            this.reviewBtn.classList.toggle("d-none", !items.length);
            this.reviewBtn.replaceChildren(icon("warning", 16), " ", _t("%s to review", items.length));
        }
        this._reviewCount = items.length;
    }

    selectNextReview() {
        const items = this.reviewItems();
        if (!items.length) {
            return;
        }
        const idx = this.selected ? items.findIndex((i) => i.element.id === this.selected.id) : -1;
        const next = items[(idx + 1) % items.length].element;
        this.togglePanel(true);
        this.focusElement(next.id);
    }

    typeLabel(el) {
        return this.typeLabels[el.type] || el.type.replace("bpmn:", "");
    }

    elementName(el) {
        const bo = el.businessObject || {};
        if (el.type === "bpmn:Group") {
            return (bo.categoryValueRef && bo.categoryValueRef.value) || "";
        }
        return bo.name || bo.text || "";
    }

    displayName(el) {
        return this.elementName(el) || this.typeLabel(el);
    }

    iconClass(el) {
        const bo = el.businessObject || {};
        const t = el.type;
        const defs = bo.eventDefinitions || [];
        let def = "none";
        if (defs.length > 1) {
            def = bo.parallelMultiple ? "parallel-multiple" : "multiple";
        } else if (defs.length) {
            def = EVENT_DEFS[defs[0].$type] || "none";
        }
        let name;
        if (t === "bpmn:StartEvent") {
            name = "start-event-" + (bo.isInterrupting === false && def !== "none" ? "non-interrupting-" : "") + def;
        } else if (t === "bpmn:EndEvent") {
            name = "end-event-" + def;
        } else if (t === "bpmn:IntermediateCatchEvent" || t === "bpmn:IntermediateThrowEvent") {
            name = def === "none" ? "intermediate-event-none"
                : "intermediate-event-" + (t === "bpmn:IntermediateCatchEvent" ? "catch-" : "throw-") + def;
        } else if (t === "bpmn:BoundaryEvent") {
            name = "intermediate-event-catch-" + (bo.cancelActivity === false ? "non-interrupting-" : "") + def;
        } else if (t === "bpmn:SubProcess") {
            const expanded = el.di ? el.di.isExpanded !== false : true;
            name = bo.triggeredByEvent ? "event-subprocess-expanded"
                : expanded ? "subprocess-expanded" : "subprocess-collapsed";
        } else if (t === "bpmn:SequenceFlow") {
            const src = bo.sourceRef;
            name = src && src.default === bo ? "default-flow" : bo.conditionExpression ? "conditional-flow" : "connection";
        } else {
            name = SIMPLE_ICONS[t] || "task-none";
        }
        return "bpmn-icon-" + name;
    }

    category(el) {
        const t = el.type;
        if (t === "bpmn:StartEvent") {
            return "start";
        }
        if (t === "bpmn:EndEvent") {
            return "end";
        }
        if (t.endsWith("Event")) {
            return "event";
        }
        if (t.endsWith("Gateway")) {
            return "gateway";
        }
        if (t.startsWith("bpmn:Data")) {
            return "data";
        }
        if (t === "bpmn:Participant" || t === "bpmn:Lane") {
            return "pool";
        }
        if (el.waypoints) {
            return "flow";
        }
        if (t === "bpmn:TextAnnotation" || t === "bpmn:Group") {
            return "other";
        }
        return "task";
    }

    typeTile(el, small = false) {
        return h("span", { "class": "o_bpmn_tile o_bpmn_cat_" + this.category(el) + (small ? " o_bpmn_tile_sm" : ""),
            "aria-hidden": "true" }, h("i", { "class": this.iconClass(el) }));
    }

    laneOf(el) {
        const reg = this.instance.get("elementRegistry");
        const bo = el.businessObject;
        let best = null;
        for (const lane of reg.filter((e) => e.type === "bpmn:Lane")) {
            const refs = lane.businessObject.flowNodeRef || [];
            if (refs.includes(bo)) {
                // nested lanes: the innermost (smallest) one wins
                if (!best || lane.width * lane.height < best.width * best.height) {
                    best = lane;
                }
            }
        }
        if (best) {
            return best;
        }
        let p = el.parent;
        while (p) {
            if (p.type === "bpmn:Participant") {
                return p;
            }
            p = p.parent;
        }
        return null;
    }

    responsibleName(el) {
        const resp = this.responsible(el.businessObject);
        if (!resp) {
            return null;
        }
        const r = this.resolved[el.id + ":resp"];
        return (r && r.ok && r.name) || resp.name || "";
    }

    responsibleModelLabel(model) {
        return model ? kindMeta(model).label : "";
    }

    flowNeighbours(el) {
        const prev = [];
        const next = [];
        const isFlow = (c) => c.type === "bpmn:SequenceFlow" || c.type === "bpmn:MessageFlow";
        for (const c of el.incoming || []) {
            if (isFlow(c) && c.source) {
                prev.push({ el: c.source, label: c.businessObject.name, message: c.type === "bpmn:MessageFlow" });
            }
        }
        for (const c of el.outgoing || []) {
            if (isFlow(c) && c.target) {
                const isDefault = el.businessObject && el.businessObject.default === c.businessObject;
                next.push({ el: c.target, label: c.businessObject.name || (isDefault ? _t("otherwise") : ""),
                    message: c.type === "bpmn:MessageFlow" });
            }
        }
        for (const b of el.attachers || []) {
            next.push({ el: b, label: _t("exception"), exception: true });
        }
        if (el.host) {
            prev.push({ el: el.host, label: _t("attached to") });
        }
        return { prev, next };
    }

    renderPanel() {
        if (!this.instance) {
            return;
        }
        const scroll = this.panelEl.scrollTop;
        const sameTarget = this._panelFor === (this.selected ? this.selected.id : this.selection.length ? "multi" : "overview");
        const el = this.selected;
        const valid = el && el.businessObject && !el.labelTarget && !CONTAINERS.includes(el.type);
        let content;
        if (this.mode === "modeler" && this.selection.length > 1) {
            content = this.renderMultiPanel(this.selection);
            this._panelFor = "multi";
        } else if (valid) {
            if (this._panelFor !== el.id) {
                this.openPickers.clear();
            }
            content = this.renderElementPanel(el);
            this._panelFor = el.id;
        } else {
            content = this.renderOverview();
            this._panelFor = "overview";
        }
        this.panelEl.replaceChildren(...content);
        this.panelEl.scrollTop = sameTarget ? scroll : 0;
        this.markFlow(valid && this.mode !== "modeler" ? el : null);
    }

    /** Viewer: outline the selected step and softly its next steps. */
    markFlow(el) {
        const canvas = this.instance.get("canvas");
        for (const id of this._flowMarks || []) {
            const reg = this.instance.get("elementRegistry");
            const e = reg.get(id.el);
            if (e) {
                canvas.removeMarker(e, id.marker);
            }
        }
        this._flowMarks = [];
        if (!el || el.waypoints || RESPONSIBLE_TYPES.includes(el.type)) {
            return;
        }
        canvas.addMarker(el, "o-flow-current");
        this._flowMarks.push({ el: el.id, marker: "o-flow-current" });
        for (const n of this.flowNeighbours(el).next) {
            if (!RESPONSIBLE_TYPES.includes(n.el.type)) {
                canvas.addMarker(n.el, "o-flow-next");
                this._flowMarks.push({ el: n.el.id, marker: "o-flow-next" });
            }
        }
    }

    /** Panel section; a titled one folds on a click on its title (remembered per title). */
    section(title, iconName, ...body) {
        if (!title) {
            return h("section", { "class": "o_bpmn_sec" }, body);
        }
        let help = null;
        if (iconName && typeof iconName === "object") {
            help = iconName.help;
            iconName = iconName.icon;
        }
        const key = String(title).replace(SECTION_COUNT, "");
        const folded = this.collapsed.has(key);
        const content = h("div", { "class": "o_bpmn_sec_body" }, body);
        const head = h("button", { type: "button", "class": "o_bpmn_sec_title o_bpmn_sec_toggle",
            "aria-expanded": folded ? "false" : "true", title: _t("Show or hide") },
        iconName ? icon(iconName, 14) : null, h("span", { "class": "flex-grow-1" }, title),
        h("span", { "class": "o_bpmn_sec_chevron" }, icon("chevron", 14)));
        // the guide sections behind these links explain editing: managers only
        const helpLink = help && this.mode === "modeler" ? this.helpLink(help) : null;
        const sec = h("section", { "class": "o_bpmn_sec" + (folded ? " o_bpmn_sec_folded" : "") },
            helpLink ? h("div", { "class": "o_bpmn_sec_head" }, head, helpLink) : head, content);
        head.addEventListener("click", () => {
            const nowFolded = !sec.classList.contains("o_bpmn_sec_folded");
            sec.classList.toggle("o_bpmn_sec_folded", nowFolded);
            head.setAttribute("aria-expanded", nowFolded ? "false" : "true");
            if (nowFolded) {
                this.collapsed.add(key);
            } else {
                this.collapsed.delete(key);
            }
            writeJson("collapsed", [...this.collapsed]);
        });
        return sec;
    }

    /** Small "?" that opens the user guide at a section. */
    helpLink(section) {
        return h("a", { "class": "o_bpmn_help_link", href: GUIDE_URL + "#" + section, target: "_blank",
            rel: "noopener", title: _t("Explain this (user guide)"), "aria-label": _t("Explain this (user guide)"),
            onclick: (ev) => ev.stopPropagation() }, "?");
    }

    /** Tabs under the element header: Content and Appearance (none in the viewer, which has no appearance parts). */
    tabbed(content, look) {
        const parts = (list) => list.filter(Boolean);
        content = parts(content);
        look = parts(look);
        if (!look.length) {
            return content;
        }
        const tab = look.length && this.panelTab === "look" ? "look" : "content";
        const button = (key, label, iconName) => h("button", { type: "button", role: "tab",
            "class": "o_bpmn_tab" + (tab === key ? " active" : ""), "aria-selected": tab === key ? "true" : "false",
            onclick: () => {
                if (this.panelTab !== key) {
                    this.panelTab = key;
                    writeJson("panel_tab", key);
                    this.renderPanel();
                    this.panelEl.scrollTop = 0;
                }
            } }, icon(iconName, 14), label);
        return [h("div", { "class": "o_bpmn_tabs", role: "tablist" },
            button("content", _t("Content"), "record"), button("look", _t("Appearance"), "palette")),
        ...(tab === "look" ? look : content)];
    }

    renderOverview() {
        const reg = this.instance.get("elementRegistry");
        const all = reg.getAll().filter((e) => !e.labelTarget && e.businessObject && !CONTAINERS.includes(e.type));
        const editing = this.mode === "modeler";
        const steps = all.filter((e) => ["task", "gateway"].includes(this.category(e)) && !e.waypoints);
        const lanes = all.filter((e) => e.type === "bpmn:Lane" ||
            // a collapsed pool (no process behind it) is an outside party, not a role
            (e.type === "bpmn:Participant" && e.businessObject.processRef &&
                !(e.businessObject.processRef.laneSets && e.businessObject.processRef.laneSets.length)));
        let linkCount = 0;
        for (const e of all) {
            linkCount += this.links(e.businessObject).length;
        }
        const isManager = this.snapshot && this.snapshot.isManager;
        const reviewItems = isManager ? this.reviewItems() : [];
        const out = [];

        out.push(h("header", { "class": "o_bpmn_head" },
            h("span", { "class": "o_bpmn_tile o_bpmn_cat_process", "aria-hidden": "true" }, icon("flow", 22)),
            h("div", { "class": "o_bpmn_head_text" },
                h("div", { "class": "o_bpmn_eyebrow" }, _t("Process overview")),
                h("div", { "class": "o_bpmn_title" }, (this.snapshot && this.snapshot.name) || _t("Process")))));

        const stat = (n, label, warn) => h("div", { "class": "o_bpmn_stat" + (warn && n ? " o_bpmn_stat_warn" : "") },
            h("b", {}, String(n)), h("span", {}, label));
        out.push(h("div", { "class": "o_bpmn_stats" },
            stat(steps.length, _t("Steps")),
            stat(lanes.length, _t("Roles")),
            stat(linkCount, _t("Links")),
            isManager ? stat(reviewItems.length, _t("To review"), true) : null));

        const starts = all.filter((e) => e.type === "bpmn:StartEvent" &&
            !(e.parent && e.parent.type === "bpmn:SubProcess")).sort((a, b) => a.x - b.x || a.y - b.y);
        if (starts.length) {
            out.push(h("div", { "class": "o_bpmn_sec o_bpmn_sec_tight" },
                h("button", { type: "button", "class": "o_bpmn_primary w-100",
                    onclick: () => this.focusElement(starts[0].id) },
                icon("play", 16), editing ? _t("Go to the start") : _t("Walk through the process"))));
        }

        const results = h("div", { "class": "o_bpmn_find_results" });
        const named = all.filter((e) => !e.waypoints && this.elementName(e));
        const find = h("input", { type: "search", "class": "o_bpmn_input", placeholder: _t("Find a step, role or document..."),
            "aria-label": _t("Find a step") });
        const doFind = () => {
            const q = find.value.trim().toLowerCase();
            if (!q) {
                results.replaceChildren();
                return;
            }
            const hits = named.filter((e) => this.elementName(e).toLowerCase().includes(q)).slice(0, 25);
            results.replaceChildren(...(hits.length ? hits.map((e) => this.stepButton({ el: e }))
                : [h("div", { "class": "o_bpmn_muted small px-1" }, _t("No result."))]));
        };
        find.addEventListener("input", doFind);
        find.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                const first = results.querySelector("button");
                if (first) {
                    first.click();
                }
            }
        });
        out.push(this.section(null, null, h("div", { "class": "o_bpmn_find" }, icon("search", 16), find), results));

        if (lanes.length) {
            out.push(this.section(_t("Who does what"), "users", h("div", { "class": "o_bpmn_lane_list" },
                lanes.map((lane) => {
                    const resp = this.responsibleName(lane);
                    const r = this.resolved[lane.id + ":resp"];
                    const broken = r && !r.ok;
                    return h("button", { type: "button", "class": "o_bpmn_lane_row",
                        onclick: () => this.focusElement(lane.id) },
                    h("span", { "class": "o_bpmn_lane_name" }, lane.businessObject.name || _t("(unnamed lane)")),
                    resp ? h("span", { "class": "o_bpmn_chip" + (broken ? " o_bpmn_chip_danger" : "") },
                        icon(broken ? "broken" : "user", 12), resp)
                        : h("span", { "class": "o_bpmn_chip o_bpmn_chip_warn" }, _t("not assigned")));
                }))));
        }

        if (reviewItems.length) {
            out.push(this.section(_t("To review (%s)", reviewItems.length), { icon: "warning", help: "review" },
                h("div", { "class": "o_bpmn_review_list" }, reviewItems.slice(0, 60).map((it) =>
                    h("button", { type: "button", "class": "o_bpmn_review_row",
                        onclick: () => this.focusElement(it.element.id) },
                    this.typeTile(it.element, true),
                    h("span", {}, h("b", {}, this.displayName(it.element)),
                        h("small", {}, this.reviewReasons[it.reason] || "")))))));
        }

        if (editing) {
            out.push(this.renderDiagramText());
            const tip = (text) => h("li", {}, text);
            out.push(this.section(_t("Drawing tips"), { icon: "info", help: "create" }, h("ul", { "class": "o_bpmn_tips" },
                tip(_t("Drag a shape from the palette on the left, or press N to search one.")),
                tip(_t("Hover a shape and use its arrow to connect: the shapes you may connect to light up.")),
                tip(_t("Press A on a selected shape to append the next step right after it.")),
                tip(_t("Double-click a shape to edit its text; use the side panel for colors and details.")),
                tip(_t("Press ? to see all keyboard shortcuts.")))));
        } else {
            out.push(this.section(null, null, h("p", { "class": "o_bpmn_muted small mb-0" },
                _t("Click a step to read what has to be done, who does it and open the related Odoo screen."))));
        }
        return out;
    }

    stepButton(n) {
        return h("button", { type: "button", "class": "o_bpmn_step", onclick: () => this.focusElement(n.el.id),
            title: this.typeLabel(n.el) },
        this.typeTile(n.el, true),
        h("span", { "class": "o_bpmn_step_name" }, this.displayName(n.el)),
        n.label ? h("span", { "class": "o_bpmn_flowlabel" + (n.exception ? " o_bpmn_flowlabel_exc" : "") }, n.label) : null,
        n.message ? h("span", { "class": "o_bpmn_flowlabel" }, _t("message")) : null);
    }

    renderElementPanel(el) {
        const bo = el.businessObject;
        const editing = this.mode === "modeler";
        const isManager = this.snapshot && this.snapshot.isManager;
        const out = [];

        const headText = h("div", { "class": "o_bpmn_head_text" });
        const typeRow = h("div", { "class": "o_bpmn_eyebrow" }, this.typeLabel(el));
        headText.append(typeRow);
        if (editing) {
            const current = this.elementName(el);
            const annotation = el.type === "bpmn:TextAnnotation";
            const multiline = !el.waypoints;
            const input = h(multiline ? "textarea" : "input", { "class": "o_bpmn_name_input",
                placeholder: el.waypoints ? _t("Label (e.g. Yes / No)") : _t("Name"), "aria-label": _t("Name"),
                title: multiline && !annotation ? _t("Shift+Enter: new line") : null,
                rows: annotation ? "3" : (multiline ? "1" : null) });
            input.value = current;
            if (multiline && !annotation) {
                const fit = () => {
                    input.style.height = "auto";
                    input.style.height = Math.min(input.scrollHeight + 2, 96) + "px";
                };
                input.addEventListener("input", fit);
                requestAnimationFrame(fit);
            }
            input.addEventListener("change", () => {
                if (input.value !== this.elementName(el)) {
                    this.instance.get("modeling").updateLabel(el, input.value);
                }
            });
            if (!annotation) {
                input.addEventListener("keydown", (ev) => {
                    if (ev.key === "Enter" && !ev.shiftKey) {
                        ev.preventDefault();
                        input.blur();
                    }
                });
            }
            headText.append(input);
        } else {
            headText.append(h("div", { "class": "o_bpmn_title" }, this.elementName(el) || _t("(no name)")));
        }
        const headButtons = [];
        if (editing && this.canReplace(el)) {
            headButtons.push(h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Change type") + " (R)",
                "aria-label": _t("Change type"), onclick: (ev) => this.openReplace(el, ev.currentTarget) }, icon("swap")));
        }
        out.push(h("header", { "class": "o_bpmn_head" }, this.typeTile(el), headText, headButtons));

        const rv = this.review(bo);
        if (rv && isManager) {
            out.push(h("div", { "class": "o_bpmn_alert" },
                icon("warning", 18),
                h("div", { "class": "flex-grow-1" },
                    h("div", {}, this.reviewReasons[rv.reason] || this.reviewReasons.imported),
                    rv.note ? h("div", { "class": "o_bpmn_alert_note" }, rv.note) : null,
                    editing ? h("button", { type: "button", "class": "o_bpmn_btn_sm",
                        onclick: () => this.setExtValues(el, "odoo:Review", []) },
                    icon("check", 14), _t("Mark as reviewed")) : null)));
        }

        if (el.waypoints) {
            const conn = this.renderConnection(el);
            out.push(...this.tabbed(conn.content, conn.look));
            return out;
        }

        const content = [];
        if (RESPONSIBLE_TYPES.includes(el.type)) {
            content.push(this.renderResponsible(el, editing));
        } else if (!NO_LANE_INFO.includes(el.type)) {
            const lane = this.laneOf(el);
            if (lane) {
                content.push(this.section(_t("Who"), { icon: "user", help: "responsible" }, this.personCard(lane, true)));
            }
        }

        const docText = this.documentation(bo);
        if (editing) {
            const ta = h("textarea", { "class": "o_bpmn_input", rows: "6",
                placeholder: _t("What has to be done, rules, controls, documents...\n- start a line with - for a bullet list"),
                "aria-label": _t("Work instruction") });
            ta.value = docText;
            ta.addEventListener("change", () => {
                const moddle = this.instance.get("moddle");
                const docs = ta.value.trim() ? [moddle.create("bpmn:Documentation", { text: ta.value })] : [];
                this.instance.get("modeling").updateProperties(el, { documentation: docs });
            });
            content.push(this.section(_t("Work instruction"), { icon: "record", help: "instruction" }, ta));
        } else if (docText) {
            content.push(this.section(_t("What to do"), "record", renderInstruction(docText)));
        } else if (el.type !== "bpmn:Participant" && el.type !== "bpmn:Lane") {
            content.push(this.section(_t("What to do"), "record",
                h("div", { "class": "o_bpmn_muted small" }, _t("No instruction yet."))));
        }

        if (LINKABLE.includes(el.type)) {
            content.push(this.renderLinks(el, editing));
        }

        if (!RESPONSIBLE_TYPES.includes(el.type) && !NO_LANE_INFO.includes(el.type)) {
            const { prev, next } = this.flowNeighbours(el);
            if (prev.length || next.length) {
                content.push(this.section(_t("Flow"), "flow",
                    prev.length ? h("div", { "class": "o_bpmn_flow_group" },
                        h("div", { "class": "o_bpmn_flow_caption" }, icon("left", 12), _t("Before")),
                        prev.map((n) => this.stepButton(n))) : null,
                    next.length ? h("div", { "class": "o_bpmn_flow_group" },
                        h("div", { "class": "o_bpmn_flow_caption" }, _t("Next"), icon("right", 12)),
                        next.map((n) => this.stepButton(n))) : null));
            }
        }
        if (editing && isActivity(el)) {
            content.push(this.renderRepeat(el));
        }

        const look = [];
        if (editing) {
            look.push(this.renderStyle([el]));
            look.push(this.renderGeometry(el));
            if (el.label) {
                look.push(this.section(_t("Label"), { icon: "text", help: "arrowtext" },
                    h("button", { type: "button", "class": "o_bpmn_btn_sm",
                        title: _t("Put the text back under the element"),
                        onclick: () => this.instance.get("commandStack").execute("odoo.labels.reset", { elements: [el] }) },
                    icon("reset", 14), _t("Put the text back in place"))));
            }
            content.push(h("div", { "class": "o_bpmn_footer_id" }, "ID: ", bo.id));
        }
        out.push(...this.tabbed(content, look));
        return out;
    }

    isLocked(el) {
        return !!(el && el.di && el.di.get && el.di.get("odoostyle:locked"));
    }

    groupOf(el) {
        return (el && el.di && el.di.get && el.di.get("odoostyle:group")) || null;
    }

    groupMembers(group) {
        return group ? this.instance.get("elementRegistry").filter((e) => !e.labelTarget && this.groupOf(e) === group) : [];
    }

    setDi(elements, attrs) {
        const els = elements.filter((e) => e.di && !e.labelTarget);
        if (els.length) {
            this.instance.get("commandStack").execute("odoo.di.update", { elements: els, attrs });
            this.renderPanel();
        }
    }

    /** Exact X / Y / width / height (in diagram pixels), lock and group of one shape. */
    renderGeometry(el) {
        const modeling = this.instance.get("modeling");
        const rules = this.instance.get("rules");
        const locked = this.isLocked(el);
        const isLane = el.type === "bpmn:Lane";
        const canResize = !locked && rules.allowed("shape.resize", { shape: el,
            newBounds: { x: el.x, y: el.y, width: el.width, height: el.height } });
        const field = (label, value, disabled, onchange) => {
            const input = h("input", { type: "number", "class": "o_bpmn_input o_bpmn_num", value: String(Math.round(value)),
                step: "1", disabled: disabled ? true : null, "aria-label": label });
            input.addEventListener("change", () => {
                const v = Math.round(Number(input.value));
                if (Number.isFinite(v)) {
                    onchange(v);
                }
            });
            input.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    input.blur();
                }
            });
            return h("label", { "class": "o_bpmn_geo_field" }, h("span", {}, label), input);
        };
        const move = (dx, dy) => (dx || dy) && modeling.moveElements([el], { x: dx, y: dy });
        const resize = (w, hgt) => {
            const bounds = { x: el.x, y: el.y, width: Math.max(10, w), height: Math.max(10, hgt) };
            if (rules.allowed("shape.resize", { shape: el, newBounds: bounds }) !== false) {
                modeling.resizeShape(el, bounds);
            } else {
                this.notification.add(_t("This element cannot have that size."), { type: "warning" });
                this.renderPanel();
            }
        };
        const grid = h("div", { "class": "o_bpmn_geo" },
            field("X", el.x, locked || isLane, (v) => move(v - el.x, 0)),
            field("Y", el.y, locked || isLane, (v) => move(0, v - el.y)),
            field(_t("W"), el.width, !canResize, (v) => resize(v, el.height)),
            field(_t("H"), el.height, !canResize, (v) => resize(el.width, v)));
        const group = this.groupOf(el);
        const members = group ? this.groupMembers(group) : [];
        const tools = h("div", { "class": "o_bpmn_btn_row o_bpmn_style_tools" },
            h("button", { type: "button", "class": "o_bpmn_btn_sm" + (locked ? " active" : ""),
                title: locked ? _t("Unlock: allow moving, resizing and deleting") : _t("Lock: prevent moving, resizing and deleting"),
                onclick: () => this.setDi([el], { locked: locked ? null : true }) },
            icon("lock", 14), locked ? _t("Unlock") : _t("Lock")),
            members.length > 1 ? h("button", { type: "button", "class": "o_bpmn_btn_sm",
                title: _t("Select the whole group"),
                onclick: () => this.instance.get("selection").select(members) },
            icon("group", 14), _t("Group of %s", members.length)) : null,
            members.length > 1 ? h("button", { type: "button", "class": "o_bpmn_btn_link",
                onclick: () => this.setDi(members, { group: null }) }, _t("Ungroup")) : null);
        return this.section(_t("Position and size"), { icon: "move", help: "geometry" }, grid, tools,
            locked ? h("p", { "class": "o_bpmn_hint o_bpmn_hint_sm" },
                _t("Locked: the element cannot be moved, resized or deleted. Its text and details can still be edited.")) : null);
    }

    /** Panel parts of an arrow: {content, look}. */
    renderConnection(el) {
        const editing = this.mode === "modeler";
        const parts = [];
        if (editing && el.type === "bpmn:SequenceFlow" && el.source && el.source.type.endsWith("Gateway")) {
            const name = el.businessObject.name || "";
            const chip = (text) => h("button", { type: "button", "class": "o_bpmn_chip_btn" + (name === text ? " active" : ""),
                onclick: () => this.instance.get("modeling").updateLabel(el, name === text ? "" : text) }, text);
            parts.push(h("div", { "class": "o_bpmn_label_chips" },
                h("span", { "class": "o_bpmn_muted small" }, _t("Quick label:")),
                chip(_t("Yes")), chip(_t("No"))));
        }
        if (el.source && el.target) {
            parts.push(h("div", { "class": "o_bpmn_flow_group" },
                h("div", { "class": "o_bpmn_flow_caption" }, _t("From")), this.stepButton({ el: el.source })));
            parts.push(h("div", { "class": "o_bpmn_flow_group" },
                h("div", { "class": "o_bpmn_flow_caption" }, _t("To")), this.stepButton({ el: el.target })));
        }
        const content = [this.section(_t("Connection"), { icon: "flow", help: "arrowtext" }, parts), this.renderLineType(el)];
        const look = [];
        if (editing) {
            look.push(this.renderStyle([el]));
            const routeTools = [];
            if (el.source && el.target) {
                routeTools.push(h("button", { type: "button", "class": "o_bpmn_btn_sm",
                    title: _t("Draw this arrow again along the shortest tidy path"),
                    onclick: () => this.instance.get("commandStack").execute("odoo.connections.relayout", { connections: [el] }) },
                icon("route", 14), _t("Tidy the route")));
            }
            if (el.label) {
                routeTools.push(h("button", { type: "button", "class": "o_bpmn_btn_sm",
                    title: _t("Put the text right beside the middle of the arrow"),
                    onclick: () => this.instance.get("commandStack").execute("odoo.labels.reset", { elements: [el] }) },
                icon("reset", 14), _t("Put the text back in place")));
            }
            if (routeTools.length) {
                look.push(this.section(_t("Route and text"), { icon: "route", help: "arrowtext" }, h("div", { "class": "o_bpmn_btn_row" }, routeTools),
                    h("div", { "class": "o_bpmn_muted small mt-2" },
                        _t("Tip: drag the text to move it; double-click the arrow or its text to edit the text."))));
            }
        }
        return { content, look };
    }

    repeatKind(el) {
        const lc = el.businessObject.loopCharacteristics;
        if (!lc) {
            return "once";
        }
        if (lc.$type === "bpmn:StandardLoopCharacteristics") {
            return "loop";
        }
        return lc.isSequential ? "sequential" : "parallel";
    }

    /** Loop / multi-instance markers: normally hidden in the "change type" menu. */
    renderRepeat(el) {
        const current = this.repeatKind(el);
        const opts = [
            ["once", "once", _t("Once"), _t("The step is done one time.")],
            ["loop", "loopMark", _t("Repeated"), _t("Repeated until a condition is met, e.g. until the check passes.")],
            ["parallel", "miPar", _t("For each, at the same time"), _t("Done for every item in parallel, e.g. each approver at once.")],
            ["sequential", "miSeq", _t("For each, one after another"), _t("Done for every item in turn, e.g. each order line.")],
        ];
        const hint = h("p", { "class": "o_bpmn_hint o_bpmn_hint_sm" }, opts.find((o) => o[0] === current)[3]);
        const chips = h("div", { "class": "o_bpmn_kinds" }, opts.map(([kind, ic, label, tip]) => h("button", {
            type: "button", title: tip, "aria-pressed": kind === current ? "true" : "false",
            "class": "o_bpmn_kind" + (kind === current ? " active" : ""),
            onclick: () => {
                if (kind === current) {
                    return;
                }
                const moddle = this.instance.get("moddle");
                let lc;
                if (kind === "loop") {
                    lc = moddle.create("bpmn:StandardLoopCharacteristics");
                } else if (kind !== "once") {
                    lc = moddle.create("bpmn:MultiInstanceLoopCharacteristics", { isSequential: kind === "sequential" });
                }
                this.instance.get("modeling").updateProperties(el, { loopCharacteristics: lc });
                this.renderPanel();
            } }, icon(ic, 14), label)));
        return this.section(_t("Repeat"), { icon: "loopMark", help: "repeat" }, chips, hint);
    }

    connectionKind(el) {
        const bo = el.businessObject;
        if (el.type === "bpmn:MessageFlow") {
            return "message";
        }
        if (el.type === "bpmn:Association") {
            return "association";
        }
        if (el.type === "bpmn:DataInputAssociation" || el.type === "bpmn:DataOutputAssociation") {
            return "data";
        }
        const src = el.source && el.source.businessObject;
        if (src && src.default === bo) {
            return "default";
        }
        if (bo.conditionExpression && el.source && isActivity(el.source)) {
            return "conditional";
        }
        return "sequence";
    }

    /** Line style is meaning in BPMN (solid sequence, dashed message, dotted association):
     *  offer the valid connection kinds, not a free "dash". */
    renderLineType(el) {
        const editing = this.mode === "modeler";
        const current = this.connectionKind(el);
        const meta = {
            sequence: [_t("Sequence flow"), _t("Solid line: the next step in the same pool.")],
            default: [_t("Default flow"), _t("Slash at the start: taken when no other condition is met.")],
            conditional: [_t("Conditional flow"), _t("Diamond at the start: taken only if its condition is true (write it as the label).")],
            message: [_t("Message flow"), _t("Dashed line: a message between two pools. Drawn automatically when you connect different pools.")],
            association: [_t("Association"), _t("Dotted line: attaches a note (text annotation) to an element.")],
            data: [_t("Data association"), _t("Dotted arrow: a document or data store is read or written by the step.")],
        };
        let options = [current];
        if (["sequence", "default", "conditional"].includes(current) && el.source) {
            const src = el.source;
            options = ["sequence"];
            const gw = ["bpmn:ExclusiveGateway", "bpmn:InclusiveGateway", "bpmn:ComplexGateway"].includes(src.type);
            if (gw || isActivity(src)) {
                options.push("default");
            }
            if (isActivity(src)) {
                options.push("conditional");
            }
        }
        const cards = options.map((kind) => {
            const [label, hint] = meta[kind];
            const active = kind === current;
            return h("button", { type: "button", "class": "o_bpmn_linetype" + (active ? " active" : ""),
                "aria-pressed": active ? "true" : "false", disabled: !editing && !active ? true : null,
                onclick: () => editing && !active && this.setConnectionKind(el, kind) },
            linePreview(kind), h("span", { "class": "o_bpmn_linetype_text" }, h("b", {}, label), h("small", {}, hint)));
        });
        const body = [h("div", { "class": "o_bpmn_linetypes" }, editing ? cards : cards.filter((c) => c.classList.contains("active")))];
        if (editing) {
            body.push(h("p", { "class": "o_bpmn_hint o_bpmn_hint_sm" },
                _t("In BPMN the line style has a meaning, so it follows the kind of connection. The color can be changed below.")));
        }
        return this.section(_t("Line type"), { icon: "flow", help: "linetype" }, body);
    }

    setConnectionKind(el, kind) {
        const modeling = this.instance.get("modeling");
        const moddle = this.instance.get("moddle");
        const bo = el.businessObject;
        const src = el.source;
        const cmd = this.instance.get("commandStack");
        const run = () => {
            if (kind === "default") {
                if (bo.conditionExpression) {
                    modeling.updateProperties(el, { conditionExpression: undefined });
                }
                modeling.updateProperties(src, { "default": bo });
            } else {
                if (src.businessObject.default === bo) {
                    modeling.updateProperties(src, { "default": undefined });
                }
                if (kind === "conditional") {
                    modeling.updateProperties(el, {
                        conditionExpression: moddle.create("bpmn:FormalExpression", { body: this.elementName(el) || "" }),
                    });
                } else if (bo.conditionExpression) {
                    modeling.updateProperties(el, { conditionExpression: undefined });
                }
            }
        };
        run();
        this.renderPanel();
    }

    renderMultiPanel(elements) {
        const out = [];
        out.push(h("header", { "class": "o_bpmn_head" },
            h("span", { "class": "o_bpmn_tile o_bpmn_cat_process", "aria-hidden": "true" }, icon("grid", 22)),
            h("div", { "class": "o_bpmn_head_text" },
                h("div", { "class": "o_bpmn_eyebrow" }, _t("Selection")),
                h("div", { "class": "o_bpmn_title" }, _t("%s elements selected", elements.length)))));
        const shapes = elements.filter((e) => !e.waypoints);
        if (shapes.length > 1) {
            const align = this.instance.get("alignElements", false);
            const distribute = this.instance.get("distributeElements", false);
            const btn = (title, ic, fn) => h("button", { type: "button", "class": "o_bpmn_icon_btn", title,
                "aria-label": title, onclick: fn }, icon(ic, 18));
            const row = [];
            if (align) {
                for (const [dir, ic, title] of [["left", "alignLeft", _t("Align left")],
                    ["center", "alignCenter", _t("Align centers")], ["right", "alignRight", _t("Align right")],
                    ["top", "alignTop", _t("Align top")], ["middle", "alignMiddle", _t("Align middles")],
                    ["bottom", "alignBottom", _t("Align bottom")]]) {
                    row.push(btn(title, ic, () => align.trigger(shapes, dir)));
                }
            }
            if (distribute && shapes.length > 2) {
                row.push(btn(_t("Distribute horizontally"), "distH", () => distribute.trigger(shapes, "horizontal")));
                row.push(btn(_t("Distribute vertically"), "distV", () => distribute.trigger(shapes, "vertical")));
            }
            const boxes = shapes.filter((e) => /(Task|SubProcess|CallActivity|Transaction|TextAnnotation)$/.test(e.type));
            if (boxes.length > 1) {
                row.push(btn(_t("Same size as the first selected"), "sameSize", () =>
                    this.instance.get("commandStack").execute("odoo.shapes.sameSize",
                        { elements: boxes, reference: boxes[0] })));
            }
            if (row.length) {
                out.push(this.section(_t("Arrange"), { icon: "alignLeft", help: "layout" }, h("div", { "class": "o_bpmn_btn_row" }, row)));
            }
        }
        if (this.mode === "modeler") {
            const shapesOnly = elements.filter((e) => !e.waypoints && !e.labelTarget && e.type !== "bpmn:Lane");
            const groups = new Set(shapesOnly.map((e) => this.groupOf(e)));
            const oneGroup = groups.size === 1 && !groups.has(null) && shapesOnly.length > 1;
            const allLocked = shapesOnly.length && shapesOnly.every((e) => this.isLocked(e));
            const reg = this.instance.get("elementRegistry");
            const inside = new Set(shapesOnly);
            const arrows = elements.filter((e) => e.waypoints).concat(
                reg.filter((c) => c.waypoints && inside.has(c.source) && inside.has(c.target)));
            const tools = h("div", { "class": "o_bpmn_btn_row o_bpmn_style_tools" },
                shapesOnly.length > 1 ? (oneGroup
                    ? h("button", { type: "button", "class": "o_bpmn_btn_sm", onclick: () => this.setDi(shapesOnly, { group: null }) },
                        icon("group", 14), _t("Ungroup"))
                    : h("button", { type: "button", "class": "o_bpmn_btn_sm",
                        title: _t("Move and select these elements together (Alt+click selects one)"),
                        onclick: () => this.setDi(shapesOnly, { group: "g" + Date.now().toString(36) }) },
                    icon("group", 14), _t("Group"))) : null,
                shapesOnly.length ? h("button", { type: "button", "class": "o_bpmn_btn_sm",
                    onclick: () => this.setDi(shapesOnly, { locked: allLocked ? null : true }) },
                icon("lock", 14), allLocked ? _t("Unlock") : _t("Lock")) : null,
                arrows.length ? h("button", { type: "button", "class": "o_bpmn_btn_sm",
                    title: _t("Draw the selected arrows again along tidy paths"),
                    onclick: () => this.instance.get("commandStack").execute("odoo.connections.relayout",
                        { connections: [...new Set(arrows)] }) },
                icon("route", 14), _t("Tidy %s arrows", new Set(arrows).size)) : null);
            const labelled = elements.filter((e) => e.label);
            if (labelled.length) {
                tools.append(h("button", { type: "button", "class": "o_bpmn_btn_sm",
                    title: _t("Put the texts of the selected elements and arrows back in place"),
                    onclick: () => this.instance.get("commandStack").execute("odoo.labels.reset", { elements: labelled }) },
                icon("reset", 14), _t("Put %s texts back in place", labelled.length)));
            }
            out.push(this.section(_t("Group and lock"), { icon: "group", help: "group" }, tools));
        }
        out.push(this.renderStyle(elements));
        return out;
    }

    canReplace(el) {
        try {
            const popup = this.instance.get("popupMenu", false);
            return !!popup && !popup.isEmpty(el, "bpmn-replace");
        } catch {
            return false;
        }
    }

    openReplace(el, anchor) {
        const popup = this.instance.get("popupMenu");
        const rect = anchor.getBoundingClientRect();
        const width = 300;
        const x = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
        popup.open(el, "bpmn-replace", { x, y: rect.bottom + 6, cursor: { x: rect.left, y: rect.bottom } },
            { title: this.instance.get("translate")("Change element"), width, search: true });
    }

    currentColors(el) {
        const di = el.di;
        const get = (keys) => {
            for (const k of keys) {
                try {
                    const v = di && di.get(k);
                    if (v) {
                        return v;
                    }
                } catch {
                    // attribute not known by moddle
                }
            }
            return undefined;
        };
        return {
            fill: get(["color:background-color", "bioc:fill"]),
            stroke: get(["color:border-color", "bioc:stroke"]),
        };
    }

    renderStyle(elements) {
        const modeling = this.instance.get("modeling");
        const targets = elements.filter((e) => !e.labelTarget);
        const first = this.currentColors(targets[0]);
        const connectionsOnly = targets.every((e) => e.waypoints);
        const labels = {
            default: _t("Default"), teal: _t("Teal"), navy: _t("Navy"), orange: _t("Orange"),
            yellow: _t("Yellow"), green: _t("Green"), purple: _t("Purple"), red: _t("Red"), gray: _t("Gray"),
        };
        const norm = (c) => (c || "").toUpperCase();
        const apply = (colors) => {
            modeling.setColor(targets, colors);
            const withLabels = targets.map((e) => e.label).filter(Boolean);
            if ("stroke" in colors && withLabels.length) {
                modeling.setColor(withLabels, { stroke: colors.stroke });
            }
        };
        const swatches = COLOR_PRESETS.map((c) => {
            const active = norm(c.fill) === norm(first.fill) && norm(c.stroke) === norm(first.stroke);
            return h("button", { type: "button", "class": "o_bpmn_swatch" + (active ? " active" : ""),
                title: labels[c.key], "aria-label": labels[c.key],
                style: "--sw-fill:" + (connectionsOnly ? "#fff" : (c.fill || DEFAULT_FILL)) + ";--sw-stroke:" + (c.stroke || DEFAULT_STROKE),
                onclick: () => apply({ fill: c.fill, stroke: c.stroke }) },
            connectionsOnly ? h("i", { "class": "o_bpmn_swatch_line" }) : null);
        });
        const picker = (label, key, value) => {
            const input = h("input", { type: "color", value: value || (key === "fill" ? DEFAULT_FILL : DEFAULT_STROKE),
                "aria-label": label });
            input.addEventListener("change", () => apply({ [key]: input.value }));
            return h("label", { "class": "o_bpmn_color_input" }, input, h("span", {}, label));
        };
        const custom = h("div", { "class": "o_bpmn_color_row" },
            connectionsOnly ? null : picker(_t("Fill"), "fill", first.fill),
            picker(connectionsOnly ? _t("Line") : _t("Line and text"), "stroke", first.stroke),
            h("button", { type: "button", "class": "o_bpmn_icon_btn ms-auto", title: _t("Reset colors"),
                "aria-label": _t("Reset colors"), onclick: () => apply({ fill: undefined, stroke: undefined }) },
            icon("reset")));
        const clip = this.styleClipboard;
        const styleTools = h("div", { "class": "o_bpmn_btn_row o_bpmn_style_tools" },
            h("button", { type: "button", "class": "o_bpmn_btn_sm", title: _t("Copy colors and text format of this element"),
                onclick: () => {
                    const src = targets[0];
                    this.styleClipboard = { colors: this.currentColors(src), text: this.textStyle(src) };
                    this.notification.add(_t("Style copied. Select other elements and click \"Paste style\"."),
                        { type: "info" });
                    this.renderPanel();
                } }, icon("copyStyle", 14), _t("Copy style")),
            clip ? h("button", { type: "button", "class": "o_bpmn_btn_sm",
                title: _t("Apply the copied colors and text format to the selection"),
                onclick: () => {
                    apply({ fill: clip.colors.fill || undefined, stroke: clip.colors.stroke || undefined });
                    this.applyTextStyle(targets, Object.fromEntries(TEXT_KEYS.map((k) => [k, clip.text[k] || null])));
                } }, icon("check", 14), _t("Paste style")) : null);
        return h("div", {},
            this.section(_t("Style"), { icon: "palette", help: "colors" }, h("div", { "class": "o_bpmn_swatches" }, swatches), custom, styleTools),
            this.renderTextFormat(targets));
    }

    textStyle(el) {
        const di = el && el.di;
        const out = {};
        for (const k of TEXT_KEYS) {
            out[k] = (di && di.get && di.get("odoostyle:" + k)) || null;
        }
        return out;
    }

    /** One undo step for the whole selection (command registered in odoo_ux.js). */
    applyTextStyle(elements, style) {
        const els = elements.filter((e) => e.di && !e.labelTarget);
        if (!els.length) {
            return;
        }
        this.instance.get("commandStack").execute("odoo.text.update", { elements: els, style });
        this.renderPanel();
    }

    baseFontSize() {
        const root = this.instance.get("canvas").getRootElement();
        const plane = root && root.di;
        return (plane && plane.get && Number(plane.get("odoostyle:baseFontSize"))) || null;
    }

    renderTextFormat(targets) {
        const hasText = targets.some((e) => (e.businessObject && (e.businessObject.name || e.businessObject.text)));
        const first = this.textStyle(targets[0]);
        const base = this.baseFontSize() || TEXT_BASE;
        const size = first.fontSize ? Number(first.fontSize) : null;
        const shown = size || base;
        const step = (dir) => {
            let next = dir > 0 ? TEXT_SIZES.find((v) => v > shown) : [...TEXT_SIZES].reverse().find((v) => v < shown);
            if (next === undefined) {
                next = TEXT_SIZES[dir > 0 ? TEXT_SIZES.length - 1 : 0];
            }
            this.applyTextStyle(targets, { fontSize: next === base ? null : next });
        };
        const toggle = (key, on, value, ic, title) => h("button", { type: "button",
            "class": "o_bpmn_icon_btn o_bpmn_toggle" + (on ? " active" : ""), title, "aria-label": title,
            "aria-pressed": on ? "true" : "false",
            onclick: () => this.applyTextStyle(targets, { [key]: on ? null : value }) }, icon(ic, 16));
        const sizeRow = h("div", { "class": "o_bpmn_text_row" },
            h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Smaller text"),
                "aria-label": _t("Smaller text"), onclick: () => step(-1) }, "A−"),
            h("span", { "class": "o_bpmn_text_size" + (size ? "" : " o_bpmn_muted"),
                title: size ? _t("Text size of this element") : _t("Diagram text size (not changed here)") }, String(shown)),
            h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Larger text"),
                "aria-label": _t("Larger text"), onclick: () => step(1) }, "A+"),
            h("span", { "class": "o_bpmn_text_sep" }),
            toggle("fontWeight", first.fontWeight === "bold", "bold", "bold", _t("Bold")),
            toggle("fontStyle", first.fontStyle === "italic", "italic", "italic", _t("Italic")),
            toggle("textDecoration", first.textDecoration === "underline", "underline", "underline", _t("Underline")));
        const boxed = targets.filter((e) => !e.waypoints && TEXT_ALIGN_TYPES.some((t) => e.type === t || e.type.endsWith(t)));
        let alignRow = null;
        if (boxed.length) {
            const cur = first.textAlign || "center";
            const btn = (value, ic, title) => h("button", { type: "button",
                "class": "o_bpmn_icon_btn o_bpmn_toggle" + (cur === value ? " active" : ""), title, "aria-label": title,
                onclick: () => this.applyTextStyle(boxed, { textAlign: value === "center" ? null : value }) }, icon(ic, 16));
            alignRow = h("div", { "class": "o_bpmn_text_row" },
                btn("left", "alignLeftText", _t("Align text left")),
                btn("center", "alignCenterText", _t("Center text")),
                btn("right", "alignRightText", _t("Align text right")));
        }
        const any = targets.some((e) => TEXT_KEYS.some((k) => this.textStyle(e)[k]));
        return this.section(_t("Text"), { icon: "textSize", help: "text" },
            hasText ? null : h("p", { "class": "o_bpmn_hint o_bpmn_hint_sm" },
                _t("Type a name first; the format applies to it.")),
            sizeRow, alignRow,
            any ? h("button", { type: "button", "class": "o_bpmn_btn_link",
                onclick: () => this.applyTextStyle(targets, Object.fromEntries(TEXT_KEYS.map((k) => [k, null]))) },
            icon("reset", 14), _t("Clear text format")) : null);
    }

    /** Keyboard: Ctrl+B / I / U and Ctrl+Shift+> / < on the selected elements. */
    textShortcut({ toggle, size }) {
        const targets = (this.selection || []).filter((e) => !e.labelTarget);
        if (this.mode !== "modeler" || !targets.length) {
            return;
        }
        const first = this.textStyle(targets[0]);
        if (toggle) {
            const on = { fontWeight: "bold", fontStyle: "italic", textDecoration: "underline" }[toggle];
            this.applyTextStyle(targets, { [toggle]: first[toggle] === on ? null : on });
            return;
        }
        const base = this.baseFontSize() || TEXT_BASE;
        const shown = first.fontSize ? Number(first.fontSize) : base;
        const next = size > 0 ? TEXT_SIZES.find((v) => v > shown) : [...TEXT_SIZES].reverse().find((v) => v < shown);
        if (next !== undefined) {
            this.applyTextStyle(targets, { fontSize: next === base ? null : next });
        }
    }

    /** Overview (nothing selected): one text size for the whole diagram. */
    renderDiagramText() {
        const current = this.baseFontSize() || TEXT_BASE;
        const opts = [[11, _t("Small")], [12, _t("Normal")], [14, _t("Large")], [16, _t("Extra large")]];
        return this.section(_t("Diagram text size"), { icon: "textSize", help: "text" },
            h("div", { "class": "o_bpmn_kinds" }, opts.map(([v, label]) => h("button", { type: "button",
                "class": "o_bpmn_kind" + (v === current ? " active" : ""), "aria-pressed": v === current ? "true" : "false",
                onclick: () => {
                    this.instance.get("commandStack").execute("odoo.text.base", { size: v === TEXT_BASE ? null : v });
                    this.renderPanel();
                } }, label))),
            h("p", { "class": "o_bpmn_hint o_bpmn_hint_sm" },
                _t("Applies to every element that has no size of its own (set one in the Text section of an element).")));
    }

    /** Card "who": for a lane itself, or (inherited=true) for a step inside a lane. */
    personCard(lane, inherited) {
        const resp = this.responsible(lane.businessObject);
        const laneName = lane.businessObject.name || "";
        const r = this.resolved[lane.id + ":resp"];
        const broken = resp && r && !r.ok;
        const name = resp ? this.responsibleName(lane) : "";
        const kind = resp ? this.responsibleModelLabel(resp.model) : "";
        const title = name || laneName || _t("not assigned");
        const subtitle = [];
        if (inherited && resp && laneName && laneName !== name) {
            subtitle.push((lane.type === "bpmn:Lane" ? _t("Lane") : _t("Pool")) + ": " + laneName);
        }
        if (kind) {
            subtitle.push(kind);
        }
        if (!resp) {
            subtitle.push(_t("no Odoo responsible assigned"));
        }
        return h("div", { "class": "o_bpmn_person" + (broken ? " o_bpmn_person_broken" : "") + (resp ? "" : " o_bpmn_person_none") },
            h("span", { "class": "o_bpmn_avatar" }, broken ? icon("broken", 16) : initials(title)),
            h("div", { "class": "o_bpmn_person_text" },
                h("div", { "class": "o_bpmn_person_name" }, title),
                subtitle.length ? h("div", { "class": "o_bpmn_person_sub" }, subtitle.join(" · ")) : null,
                resp && resp.note ? h("div", { "class": "o_bpmn_person_note" }, resp.note) : null,
                broken ? h("div", { "class": "o_bpmn_person_sub text-danger" },
                    _t("The linked record no longer exists or is not accessible.")) : null),
            inherited ? h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Show the lane"),
                "aria-label": _t("Show the lane"), onclick: () => this.focusElement(lane.id) }, icon("right")) : null);
    }

    assignResponsible(el, model, item) {
        const bo = el.businessObject;
        const modeling = this.instance.get("modeling");
        const prev = this.responsible(bo);
        const prevName = prev ? (this.responsibleName(el) || "").trim() : "";
        const laneName = (bo.name || "").trim();
        // The lane name follows the responsible if it was empty, equal to the previous responsible,
        // or syncName is set; else only suggested.
        const sync = !laneName || laneName === item.name || (prev && (prev.syncName || laneName === prevName));
        this.setExtValues(el, "odoo:Responsible", [this.createExt("odoo:Responsible", {
            model, resId: item.resId, xmlid: item.xmlid, name: item.name,
            note: prev ? prev.note : undefined, syncName: sync,
        })]);
        if (sync && laneName !== item.name) {
            modeling.updateLabel(el, item.name);
        }
        const rv = this.review(bo);
        if (rv && ["responsible_missing", "responsible_auto"].includes(rv.reason)) {
            this.setExtValues(el, "odoo:Review", []);
        }
    }

    updateResponsible(el, changes) {
        const resp = this.responsible(el.businessObject);
        if (!resp) {
            return;
        }
        const attrs = { model: resp.model, resId: resp.resId, xmlid: resp.xmlid, name: resp.name,
            note: resp.note, syncName: resp.syncName, ...changes };
        this.setExtValues(el, "odoo:Responsible", [this.createExt("odoo:Responsible", attrs)]);
    }

    renderResponsible(el, editing) {
        const bo = el.businessObject;
        const resp = this.responsible(bo);
        const body = [this.personCard(el, false)];
        if (editing) {
            const modeling = this.instance.get("modeling");
            if (resp) {
                const name = this.responsibleName(el) || "";
                const laneName = (bo.name || "").trim();
                const tools = h("div", { "class": "o_bpmn_resp_tools" });
                if (name && laneName !== name) {
                    tools.append(h("button", { type: "button", "class": "o_bpmn_btn_sm",
                        onclick: () => {
                            modeling.updateLabel(el, name);
                            this.updateResponsible(el, { syncName: true });
                        } }, icon("text", 14), _t("Use \"%s\" as lane name", name)));
                }
                const sync = h("input", { type: "checkbox", "class": "form-check-input" });
                sync.checked = !!resp.syncName;
                sync.addEventListener("change", () => {
                    this.updateResponsible(el, { syncName: sync.checked });
                    if (sync.checked && name && laneName !== name) {
                        modeling.updateLabel(el, name);
                    }
                });
                tools.append(h("label", { "class": "o_bpmn_check" }, sync, _t("Lane name follows the responsible")));
                const note = h("input", { "class": "o_bpmn_input", value: resp.note || "",
                    placeholder: _t("Role or comment, e.g. \"the shift manager approves\""),
                    "aria-label": _t("Comment") });
                note.addEventListener("change", () => this.updateResponsible(el, { note: note.value.trim() }));
                tools.append(note);
                tools.append(h("button", { type: "button", "class": "o_bpmn_btn_link",
                    onclick: () => this.setExtValues(el, "odoo:Responsible", []) }, icon("close", 14), _t("Remove the responsible")));
                body.push(tools);
            }
            if (!resp) {
                body.push(h("p", { "class": "o_bpmn_hint" },
                    _t("Who performs the steps of this lane? Pick the department, job position, group or person in Odoo.")));
            }
            if (this.options.responsible_models.length) {
                const rpicker = this.renderPicker(
                    this.options.responsible_models.map((m) => ({ value: "responsible:" + m.model })),
                    async (kind, item) => {
                        this.openPickers.delete("responsible");
                        const current = this.instance && this.instance.get("elementRegistry").get(el.id);
                        if (!current) {
                            return;
                        }
                        this.assignResponsible(current, kind.split(":")[1], item);
                        await this.resolveReferences();
                        this.refreshOverlays();
                        this.renderPanel();
                    },
                    resp ? _t("Replace: search a department, job position or group...")
                        : _t("Search a department, job position or group..."),
                    { id: "responsible" },
                );
                const ropen = !resp || this.openPickers.has("responsible");
                if (resp) {
                    const change = h("button", { type: "button", "class": "o_bpmn_btn_sm" + (ropen ? " d-none" : ""),
                        onclick: () => {
                            this.openPickers.add("responsible");
                            change.classList.add("d-none");
                            rpicker.classList.remove("d-none");
                            const inp = rpicker.querySelector("input[type=search]");
                            if (inp) {
                                inp.focus();
                            }
                        } }, icon("swap", 14), _t("Change the responsible"));
                    body.push(change);
                }
                rpicker.classList.toggle("d-none", !ropen);
                body.push(rpicker);
            }
        }
        return this.section(_t("Responsible"), { icon: "users", help: "responsible" }, body);
    }

    linkKindLabel(lk) {
        if (lk.linkType === "menu") {
            return kindMeta("menu").label;
        }
        if (lk.linkType === "action") {
            return _t("Window action (technical)");
        }
        if (lk.linkType === "url") {
            return _t("Web address (URL)");
        }
        return lk.model ? kindMeta(lk.model).label : _t("Record");
    }

    renderLinks(el, editing) {
        const bo = el.businessObject;
        const links = this.links(bo);
        if (!links.length && !editing) {
            return null;
        }
        const list = h("div", { "class": "o_bpmn_links" });
        links.forEach((lk, idx) => {
            const r = this.resolved[el.id + ":link:" + idx];
            const broken = r && !r.ok;
            const label = lk.label || (r && r.name) || lk.url || lk.xmlid || _t("Link");
            const kindIcon = kindMeta(lk.linkType === "record" ? lk.model : lk.linkType).icon;
            const tile = h("button", { type: "button", "class": "o_bpmn_linktile" + (broken ? " o_bpmn_linktile_broken" : ""),
                disabled: broken && !editing ? true : null,
                title: broken ? _t("This link is broken or not accessible.") : label,
                onclick: () => this.openLink(lk) },
            h("span", { "class": "o_bpmn_linktile_icon" }, icon(broken ? "broken" : kindIcon, 18)),
            h("span", { "class": "o_bpmn_linktile_text" }, h("b", {}, label), h("small", {}, this.linkKindLabel(lk))),
            icon("right", 16));
            list.append(h("div", { "class": "o_bpmn_link_row" }, tile,
                editing ? h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Remove"),
                    "aria-label": _t("Remove"), onclick: () => {
                        const rest = links.filter((_x, i) => i !== idx);
                        this.setExtValues(el, "odoo:Link", rest);
                        this.resolveReferences().then(() => this.refreshOverlays());
                    } }, icon("close", 14)) : null));
        });
        const body = [list];
        if (editing) {
            const kinds = [{ value: "menu" }];
            for (const m of this.options.record_models) {
                kinds.push({ value: "record:" + m.model });
            }
            if (odoo.debug) {
                kinds.push({ value: "action" });
            }
            kinds.push({ value: "url" });
            const addLink = async (link) => {
                // re-read: the element may have changed (or be gone) during an RPC
                const current = this.instance && this.instance.get("elementRegistry").get(el.id);
                if (!current) {
                    return;
                }
                const now = this.links(current.businessObject);
                this.setExtValues(current, "odoo:Link", [...now, this.createExt("odoo:Link", link)]);
                this.openPickers.delete("links");
                await this.resolveReferences();
                this.refreshOverlays();
                this.renderPanel();
            };
            const picker = this.renderPicker(kinds, (kind, item) => {
                let link;
                if (kind === "url") {
                    link = { linkType: "url", url: item.url, label: item.label || item.url };
                } else if (kind.startsWith("record:")) {
                    link = { linkType: "record", model: kind.split(":")[1], resId: item.resId,
                        xmlid: item.xmlid, label: item.name };
                } else {
                    link = { linkType: kind, resId: item.resId, xmlid: item.xmlid, label: item.name,
                        model: kind === "menu" ? "ir.ui.menu" : "ir.actions.act_window" };
                }
                return addLink(link);
            }, _t("Search..."), { id: "links" });
            if (!links.length) {
                body.push(h("p", { "class": "o_bpmn_hint" },
                    _t("Link the Odoo screen, instruction article or document people need for this step. They open it with one click.")));
            }
            const open = !links.length || this.openPickers.has("links");
            const toggle = h("button", { type: "button", "class": "o_bpmn_btn_sm" + (open ? " d-none" : ""),
                onclick: () => {
                    this.openPickers.add("links");
                    toggle.classList.add("d-none");
                    picker.classList.remove("d-none");
                    const inp = picker.querySelector("input[type=search]");
                    if (inp) {
                        inp.focus();
                    }
                } }, icon("plus", 14), _t("Add a link"));
            picker.classList.toggle("d-none", !open);
            body.push(toggle, picker);
        }
        return this.section(editing ? _t("Links") : _t("Open in Odoo"), { icon: "link", help: "links" }, body);
    }

    /** Kind chips + search box + results (+ "create" for kinds that allow it).
     * onPick(kind, item) with item = {resId, xmlid, name} or {url, label}. */
    renderPicker(kinds, onPick, placeholder, opts = {}) {
        const id = opts.id || "picker";
        this.pickerKind = this.pickerKind || {};
        let kind = kinds.some((k) => k.value === this.pickerKind[id]) ? this.pickerKind[id] : kinds[0].value;
        const chips = h("div", { "class": "o_bpmn_kinds", role: "tablist", "aria-label": _t("Type") });
        const hint = h("div", { "class": "o_bpmn_hint o_bpmn_hint_sm" });
        const input = h("input", { type: "search", "class": "o_bpmn_input", placeholder, "aria-label": placeholder });
        const labelInput = h("input", { "class": "o_bpmn_input d-none",
            placeholder: _t("Label shown to people (optional)"), "aria-label": _t("Label") });
        const results = h("div", { "class": "o_bpmn_results", role: "listbox" });
        const addUrl = h("button", { type: "button", "class": "o_bpmn_btn_sm d-none" }, icon("plus", 14), _t("Add link"));
        const isUrl = () => kind === "url";
        const modelOf = (k) => (k.includes(":") ? k.split(":")[1] : null);
        const renderChips = () => {
            chips.replaceChildren(...kinds.map((k) => {
                const meta = kindMeta(k.value);
                return h("button", { type: "button", role: "tab", "aria-selected": k.value === kind ? "true" : "false",
                    "class": "o_bpmn_kind" + (k.value === kind ? " active" : ""),
                    onclick: () => {
                        kind = k.value;
                        this.pickerKind[id] = kind;
                        renderChips();
                        refreshKind();
                        search();
                        input.focus();
                    } }, icon(meta.icon, 14), meta.label);
            }));
        };
        const refreshKind = () => {
            const url = isUrl();
            const meta = kindMeta(kind);
            labelInput.classList.toggle("d-none", !url);
            addUrl.classList.toggle("d-none", !url);
            input.placeholder = url ? "https://..." : (meta.create ? _t("Search or type a new title...") : placeholder);
            hint.textContent = meta.hint || "";
            hint.classList.toggle("d-none", !meta.hint);
            results.replaceChildren();
        };
        let searchSeq = 0;
        const createRow = (term, k) => {
            const model = modelOf(k);
            const meta = kindMeta(k);
            const allowed = (this.options.can_create || []).includes(model);
            if (!meta.create || !term || !model || !allowed) {
                return null;
            }
            return h("button", { type: "button", "class": "o_bpmn_result o_bpmn_result_create",
                onclick: async (ev) => {
                    const btn = ev.currentTarget;
                    if (btn.disabled) {
                        return;
                    }
                    btn.disabled = true;
                    try {
                        const item = await this.orm.call("business.process", "bpmn_create_target", [model, term]);
                        await onPick(k, item);
                        this.notification.add(_t("\"%s\" was created and linked. Open it from the link to complete it.", term),
                            { type: "success" });
                    } catch (e) {
                        btn.disabled = false;
                        const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
                        this.notification.add(msg, { type: "danger" });
                    }
                } }, icon("plus", 14), h("span", {}, _t("Create \"%s\"", term)));
        };
        const search = debounce(async () => {
            if (isUrl()) {
                return;
            }
            let rpcKind = kind;
            const model = modelOf(kind);
            if (kind.startsWith("record:")) {
                rpcKind = "record";
            } else if (kind.startsWith("responsible:")) {
                rpcKind = "responsible";
            }
            const term = input.value.trim();
            const k = kind;
            const seq = (searchSeq += 1);
            let items = [];
            try {
                items = await this.orm.call("business.process", "bpmn_search_targets",
                    [rpcKind, term, model, 8, this.snapshot && this.snapshot.resId]);
            } catch {
                items = [];
            }
            if (seq !== searchSeq || k !== kind) {
                return; // an older answer, or the kind changed meanwhile
            }
            const low = term.toLowerCase();
            // display names may carry a suffix, e.g. "Returns (v1.0)"
            const exact = items.some((it) => {
                const n = (it.name || "").toLowerCase();
                return n === low || n.startsWith(low + " (");
            });
            results.replaceChildren(...[
                ...items.map((it) => h("button", { type: "button", "class": "o_bpmn_result", role: "option",
                    onclick: () => onPick(k, it) }, icon(kindMeta(k).icon, 14), h("span", {}, it.name))),
                exact ? null : createRow(term, k),
                !items.length && !(kindMeta(k).create && term)
                    ? h("div", { "class": "o_bpmn_muted small p-1" }, _t("No result.")) : null,
            ].filter(Boolean));
        }, 250);
        input.addEventListener("input", search);
        input.addEventListener("focus", () => !results.children.length && search());
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                ev.preventDefault();
                if (isUrl()) {
                    addUrl.click();
                } else {
                    const first = results.querySelector("button");
                    if (first) {
                        first.click();
                    }
                }
            }
        });
        addUrl.addEventListener("click", () => {
            const url = input.value.trim();
            if (!SAFE_URL.test(url) || URL_BAD_CHARS.test(url)) {
                this.notification.add(_t("Use an address starting with https://, http://, mailto: or /"),
                    { type: "warning" });
                return;
            }
            onPick("url", { url, label: labelInput.value.trim() });
        });
        renderChips();
        refreshKind();
        return h("div", { "class": "o_bpmn_picker" },
            kinds.length > 1 ? chips : null, hint, h("div", { "class": "o_bpmn_find" }, icon("search", 16), input),
            labelInput, addUrl, results);
    }

    async openLink(link) {
        try {
            const res = await this.orm.call("business.process", "bpmn_open_link", [{
                linkType: link.linkType, model: link.model, resId: link.resId, xmlid: link.xmlid,
                url: link.url,
            }]);
            if (this.root.classList.contains("o_bpmn_fullscreen")) {
                this.toggleFullscreen();
            }
            if (res.action_id) {
                await this.action.doAction(res.action_id);
            } else {
                await this.action.doAction(res);
            }
        } catch (e) {
            const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
            this.notification.add(msg, { type: "danger" });
        }
    }

    /** Steps in reading order: along the sequence flows from the start events, then the rest. */
    printSteps() {
        const reg = this.instance.get("elementRegistry");
        const wanted = (e) => !e.labelTarget && !e.waypoints && e.businessObject && e.parent &&
            !CONTAINERS.includes(e.type) && ["task", "gateway", "start", "end", "event"].includes(this.category(e));
        const all = reg.filter(wanted);
        const byPos = (a, b) => a.x - b.x || a.y - b.y;
        const seen = new Set();
        const order = [];
        const visit = (start) => {
            const queue = [start];
            while (queue.length) {
                const el = queue.shift();
                if (seen.has(el) || !wanted(el)) {
                    continue;
                }
                seen.add(el);
                order.push(el);
                const next = [];
                for (const c of el.outgoing || []) {
                    if (c.type === "bpmn:SequenceFlow" && c.target) {
                        next.push(c.target);
                    }
                }
                for (const b of el.attachers || []) {
                    next.push(b);
                }
                for (const child of (el.children || []).filter((c) => c.type === "bpmn:StartEvent").sort(byPos)) {
                    next.unshift(child);
                }
                queue.push(...next.sort(byPos));
            }
        };
        for (const start of all.filter((e) => e.type === "bpmn:StartEvent").sort(byPos)) {
            visit(start);
        }
        for (const rest of all.sort(byPos)) {
            visit(rest);
        }
        return order.map((el, i) => {
            const bo = el.businessObject;
            const lane = this.laneOf(el);
            const who = [lane && lane.businessObject.name, lane && this.responsibleName(lane)]
                .filter(Boolean).join(" · ");
            const links = this.links(bo).map((lk, idx) => {
                const r = this.resolved[el.id + ":link:" + idx];
                return { label: lk.label || (r && r.name) || lk.url || lk.xmlid || _t("Link"),
                    kind: this.linkKindLabel(lk), url: lk.linkType === "url" && SAFE_URL.test(lk.url || "") ? lk.url : "" };
            });
            return { n: i + 1, name: this.displayName(el), type: this.typeLabel(el), who,
                doc: this.documentation(bo), links, x: el.x, y: el.y };
        });
    }

    printPrefs() {
        let prefs = {};
        try {
            prefs = JSON.parse(window.localStorage.getItem("o_bpmn_print") || "{}") || {};
        } catch {
            prefs = {};
        }
        return Object.assign({ paper: "A4", orientation: "auto", mode: "fit", scale: 1, details: true,
            stepList: true, numbers: true }, prefs);
    }

    async openPrint() {
        this.root.querySelectorAll(".o_bpmn_menu.show").forEach((m) => m.classList.remove("show"));
        if (!this.instance) {
            return;
        }
        let svg;
        try {
            ({ svg } = await this.instance.saveSVG());
        } catch (e) {
            this.notification.add(_t("Export failed: %s", e.message || e), { type: "danger" });
            return;
        }
        const vbAttr = (new DOMParser().parseFromString(svg, "image/svg+xml").documentElement
            .getAttribute("viewBox") || "0 0 100 100").split(" ").map(Number);
        const vb = { x: vbAttr[0], y: vbAttr[1], width: vbAttr[2], height: vbAttr[3] };
        const opts = this.printPrefs();
        const preview = h("div", { "class": "o_bpmn_print_preview", "aria-hidden": "true" });
        const summary = h("div", { "class": "o_bpmn_print_summary", role: "status" });
        const imgUrl = "data:image/svg+xml;base64," + utf8ToBase64(svg);
        const printBtn = h("button", { type: "button", "class": "o_bpmn_primary" }, icon("print", 16), _t("Print"));

        const seg = (key, choices) => h("div", { "class": "o_bpmn_seg", role: "radiogroup" }, choices.map(([value, label]) =>
            h("button", { type: "button", role: "radio", "class": "o_bpmn_btn_sm" + (opts[key] === value ? " active" : ""),
                "aria-checked": opts[key] === value ? "true" : "false", "data-key": key, "data-value": String(value),
                onclick: () => {
                    opts[key] = value;
                    refresh();
                } }, label)));
        const check = (key, label) => h("label", { "class": "o_bpmn_check" },
            h("input", { type: "checkbox", checked: opts[key] ? true : null, onchange: (ev) => {
                opts[key] = ev.target.checked;
                refresh();
            } }), h("span", {}, label));
        const scaleRow = h("div", { "class": "o_bpmn_print_row" }, h("label", {}, _t("Size")),
            seg("scale", [[1, "100 %"], [0.75, "75 %"], [0.5, "50 %"]]));
        const numbersCheck = check("numbers", _t("Number the steps on the diagram"));

        const refresh = () => {
            for (const b of card.querySelectorAll(".o_bpmn_seg button")) {
                const on = String(opts[b.dataset.key]) === b.dataset.value;
                b.classList.toggle("active", on);
                b.setAttribute("aria-checked", on ? "true" : "false");
            }
            scaleRow.classList.toggle("d-none", opts.mode !== "pages");
            numbersCheck.classList.toggle("d-none", !opts.stepList);
            const lay = pageLayout(vb, opts);
            const paper = lay.paper + " " + (lay.landscape ? _t("landscape") : _t("portrait"));
            const tooMany = lay.sheets > MAX_SHEETS;
            summary.textContent = opts.mode === "pages"
                ? _t("%(paper)s: %(n)s sheets (%(cols)s × %(rows)s). Glue them along the overlapping edges.",
                    { paper, n: lay.sheets, cols: lay.cols, rows: lay.rows })
                : _t("%(paper)s: one page, printed at %(zoom)s of the screen size.",
                    { paper, zoom: Math.round(lay.zoom * 100) + " %" });
            if (opts.mode === "fit" && lay.zoom < 0.45) {
                summary.textContent += " " + _t("The text will be small: consider splitting into pages or A3.");
            }
            if (tooMany) {
                summary.textContent = _t("Too many sheets (%s): choose a smaller size or A3.", lay.sheets);
            }
            summary.classList.toggle("o_bpmn_print_warn", tooMany || (opts.mode === "fit" && lay.zoom < 0.45));
            printBtn.disabled = tooMany;
            const box = 300;
            const unit = (25.4 / 96) * lay.scale;
            const dW = vb.width * unit;
            const dH = vb.height * unit;
            const overlap = 6;
            const totalW = lay.cols === 1 ? lay.areaW : lay.cols * (lay.areaW - overlap) + overlap;
            const totalH = lay.rows === 1 ? lay.areaH : lay.rows * (lay.areaH - overlap) + overlap;
            const k = Math.min(box / totalW, 190 / totalH);
            const offX = opts.mode === "fit" ? (lay.areaW - dW) / 2 : 0;
            const offY = opts.mode === "fit" ? (lay.areaH - dH) / 2 : 0;
            preview.style.width = Math.round(totalW * k) + "px";
            preview.style.height = Math.round(totalH * k) + "px";
            const pages = [];
            for (let r = 0; r < Math.min(lay.rows, 12); r++) {
                for (let c = 0; c < Math.min(lay.cols, 12); c++) {
                    pages.push(h("i", { style: "left:" + Math.round(c * (lay.areaW - overlap) * k) + "px;top:" +
                        Math.round(r * (lay.areaH - overlap) * k) + "px;width:" + Math.round(lay.areaW * k) +
                        "px;height:" + Math.round(lay.areaH * k) + "px" }));
                }
            }
            preview.replaceChildren(h("img", { src: imgUrl, alt: "", style: "left:" + Math.round(offX * k) + "px;top:" +
                Math.round(offY * k) + "px;width:" + Math.round(dW * k) + "px;height:" + Math.round(dH * k) + "px" }), ...pages);
            try {
                window.localStorage.setItem("o_bpmn_print", JSON.stringify(opts));
            } catch {
            }
        };

        printBtn.onclick = async () => {
            printBtn.disabled = true;
            try {
                const id = this.snapshot && this.snapshot.resId;
                const info = await this.orm.call("business.process", "bpmn_print_info", [id || false]);
                if (!info.name) {
                    info.name = this.snapshot && this.snapshot.name;
                }
                const steps = opts.stepList || opts.numbers ? this.printSteps() : [];
                const html = buildPrintHtml({ svg, info, steps,
                    opts: Object.assign({}, opts, { numbers: opts.stepList && opts.numbers }) });
                this.toggleHelp(false);
                await printHtml(html);
            } catch (e) {
                const msg = (e && e.data && e.data.message) || (e && e.message) || String(e);
                this.notification.add(_t("Printing failed: %s", msg), { type: "danger" });
                printBtn.disabled = false;
            }
        };

        const close = h("button", { type: "button", "class": "o_bpmn_icon_btn", title: _t("Close"),
            "aria-label": _t("Close"), onclick: () => this.toggleHelp(false) }, icon("close"));
        const card = h("div", { "class": "o_bpmn_help_card o_bpmn_print_card" },
            h("div", { "class": "o_bpmn_help_head" }, icon("print", 20), h("h5", {}, _t("Print / PDF")),
                this.helpLink("print"), close),
            h("div", { "class": "o_bpmn_print_body" },
                h("div", { "class": "o_bpmn_print_form" },
                    h("div", { "class": "o_bpmn_print_row" }, h("label", {}, _t("Paper")),
                        seg("paper", Object.keys(PAPERS).map((p) => [p, p]))),
                    h("div", { "class": "o_bpmn_print_row" }, h("label", {}, _t("Orientation")),
                        seg("orientation", [["auto", _t("Automatic")], ["landscape", _t("Landscape")],
                            ["portrait", _t("Portrait")]])),
                    h("div", { "class": "o_bpmn_print_row" }, h("label", {}, _t("Layout")),
                        seg("mode", [["fit", _t("Fit on one page")], ["pages", _t("Split into pages")]])),
                    scaleRow,
                    h("div", { "class": "o_bpmn_print_row o_bpmn_print_checks" }, h("label", {}, _t("Add")),
                        h("div", {},
                            check("details", _t("Process details (owner, purpose, inputs and outputs)")),
                            check("stepList", _t("Step list with instructions, roles and links")),
                            numbersCheck)),
                ),
                h("div", { "class": "o_bpmn_print_side" }, preview, summary)),
            h("p", { "class": "o_bpmn_muted small mb-0" },
                _t("To get a PDF, choose \"Save as PDF\" as the printer in the next window. Unsaved changes are printed too.")),
            h("div", { "class": "o_bpmn_help_foot" }, printBtn),
        );
        this.helpEl.replaceChildren(card);
        this.helpEl.onclick = (ev) => {
            if (ev.target === this.helpEl) {
                this.toggleHelp(false);
            }
        };
        this.helpEl.classList.remove("d-none");
        refresh();
        printBtn.focus({ preventScroll: true });
    }

    async download(fmt) {
        this.root.querySelectorAll(".o_bpmn_menu.show").forEach((m) => m.classList.remove("show"));
        const name = safeFileName(this.snapshot && this.snapshot.name);
        try {
            if (fmt === "bpmn") {
                const { xml } = await this.instance.saveXML({ format: true });
                downloadBlob(xml, name + ".bpmn", "application/xml");
            } else if (fmt === "svg") {
                const { svg } = await this.instance.saveSVG();
                downloadBlob(svg, name + ".svg", "image/svg+xml");
            } else if (fmt === "png") {
                const { svg } = await this.instance.saveSVG();
                downloadBlob(await this.svgToPng(svg), name + ".png", "image/png");
            } else if (fmt === "drawio") {
                const id = this.snapshot && this.snapshot.resId;
                if (!id) {
                    this.notification.add(_t("Save the process first."), { type: "warning" });
                    return;
                }
                window.location.href = "/bpmn_process_management/export/" + id + "/drawio";
            }
        } catch (e) {
            this.notification.add(_t("Export failed: %s", e.message || e), { type: "danger" });
        }
    }

    svgToPng(svg) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const scale = 2;
                const canvas = document.createElement("canvas");
                canvas.width = Math.max(1, img.width * scale);
                canvas.height = Math.max(1, img.height * scale);
                const ctx = canvas.getContext("2d");
                ctx.fillStyle = "#ffffff";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG"))), "image/png");
            };
            img.onerror = reject;
            img.src = "data:image/svg+xml;base64," + utf8ToBase64(svg);
        });
    }
}
