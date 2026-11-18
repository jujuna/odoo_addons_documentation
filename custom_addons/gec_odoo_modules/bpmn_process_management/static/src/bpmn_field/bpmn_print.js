/** Part of bpmn_process_management. License LGPL-3.
 * Print / PDF of a diagram: page layout, printable HTML, printing through a hidden iframe (print dialog or PDF). */
import { _t } from "@web/core/l10n/translation";

/** Paper sizes in mm, portrait. */
export const PAPERS = { A4: [210, 297], A3: [297, 420] };
const MARGIN = 10;
const HEADER = 13;
const FOOTER = 7;
const OVERLAP = 6;
const PX_MM = 25.4 / 96;
const MAX_SHEETS = 60;
const AMP = new RegExp("&", "g");
const LT = new RegExp("<", "g");
const GT = new RegExp(">", "g");
const QUOT = new RegExp("\"", "g");
const LIST_ITEM = new RegExp("^([-*\\u2022]|\\d{1,3}[.)])\\s+(.*)$");
const SPACES = new RegExp("[\\s,]+");

function esc(text) {
    return String(text === undefined || text === null ? "" : text)
        .replace(AMP, "&amp;").replace(LT, "&lt;").replace(GT, "&gt;").replace(QUOT, "&quot;");
}

function num(v) {
    return Math.round(v * 100) / 100;
}

/**
 * @param {{x, y, width, height}} vb diagram box in CSS px
 * @param {{paper, orientation: auto|landscape|portrait, mode: fit|pages, scale: 1|0.75|0.5}} opts
 * @returns {{paper, landscape, pageW, pageH, areaW, areaH, cols, rows, sheets, scale, zoom}} zoom: print vs screen
 */
export function pageLayout(vb, opts) {
    const [pw, ph] = PAPERS[opts.paper] || PAPERS.A4;
    const one = (landscape) => {
        const pageW = landscape ? ph : pw;
        const pageH = landscape ? pw : ph;
        const areaW = pageW - 2 * MARGIN;
        const areaH = pageH - 2 * MARGIN - HEADER - FOOTER;
        const wMm = Math.max(1, vb.width) * PX_MM;
        const hMm = Math.max(1, vb.height) * PX_MM;
        if (opts.mode === "pages") {
            const k = opts.scale || 1;
            const count = (size, area) => (size * k <= area ? 1 : Math.ceil((size * k - OVERLAP) / (area - OVERLAP)));
            const cols = count(wMm, areaW);
            const rows = count(hMm, areaH);
            return { paper: opts.paper, landscape, pageW, pageH, areaW, areaH, cols, rows,
                sheets: cols * rows, scale: k, zoom: k };
        }
        const zoom = Math.min(areaW / wMm, areaH / hMm);
        return { paper: opts.paper, landscape, pageW, pageH, areaW, areaH, cols: 1, rows: 1, sheets: 1,
            scale: zoom, zoom };
    };
    if (opts.orientation === "landscape" || opts.orientation === "portrait") {
        return one(opts.orientation === "landscape");
    }
    const land = one(true);
    const port = one(false);
    if (opts.mode === "pages") {
        return port.sheets < land.sheets ? port : land;
    }
    return port.zoom > land.zoom * 1.05 ? port : land;
}

/** Sheet name as on a map: columns A, B, C..., rows 1, 2, 3... */
function sheetName(row, col) {
    let name = "";
    let c = col;
    do {
        name = String.fromCharCode(65 + (c % 26)) + name;
        c = Math.floor(c / 26) - 1;
    } while (c >= 0);
    return name + (row + 1);
}

function instructionHtml(text) {
    if (!text) {
        return "";
    }
    const out = [];
    let list = null;
    for (const raw of text.split("\n")) {
        const line = raw.trim();
        const item = /^([-*•]|\d{1,3}[.)])\s+(.*)$/.exec(line);
        if (item) {
            list = list || [];
            list.push("<li>" + esc(item[2]) + "</li>");
            continue;
        }
        if (list) {
            out.push("<ul>" + list.join("") + "</ul>");
            list = null;
        }
        if (line) {
            out.push("<p>" + esc(line) + "</p>");
        }
    }
    if (list) {
        out.push("<ul>" + list.join("") + "</ul>");
    }
    return out.join("");
}

/** Printable HTML from {svg: saveSVG(), info: business.process.bpmn_print_info, opts: pageLayout options + details,
 * stepList, numbers, steps: [{n, name, type, who, doc, links: [{label, kind, url}], x, y}]}. */
export function buildPrintHtml({ svg, info, steps, opts }) {
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    const root = doc.documentElement;
    const vbAttr = (root.getAttribute("viewBox") || "0 0 100 100").split(SPACES).map(Number);
    const vb = { x: vbAttr[0], y: vbAttr[1], width: vbAttr[2], height: vbAttr[3] };
    const layout = pageLayout(vb, opts);
    const inner = Array.from(root.childNodes).map((n) => new XMLSerializer().serializeToString(n)).join("");
    let badges = "";
    if (opts.numbers) {
        for (const s of steps) {
            badges += '<g class="n"><circle cx="' + num(s.x) + '" cy="' + num(s.y) + '" r="10"/>' +
                '<text x="' + num(s.x) + '" y="' + num(s.y + 4) + '">' + s.n + "</text></g>";
        }
    }
    const title = esc(info.name || _t("Process"));
    const sub = [info.code, info.version ? _t("version %s", info.version) : ""].filter(Boolean).map(esc).join(" · ");
    const draft = info.state_key && info.state_key !== "published";
    const header = '<header><div><b>' + title + "</b>" + (sub ? "<span>" + sub + "</span>" : "") + "</div>" +
        (info.state ? '<em class="' + (draft ? "draft" : "ok") + '">' + esc(info.state) +
            (draft ? " · " + esc(_t("not approved")) : "") + "</em>" : "") + "</header>";
    const printed = esc(_t("Printed on %(date)s by %(user)s", { date: info.printed_at || "", user: info.printed_by || "" }));
    const footer = (right) => "<footer><span>" + printed + "</span><span>" + right + "</span></footer>";

    const pages = [];
    const { areaW, areaH } = layout;
    if (opts.mode === "pages") {
        const unit = PX_MM * layout.scale;
        const stepW = (areaW - OVERLAP) / unit;
        const stepH = (areaH - OVERLAP) / unit;
        const total = layout.sheets;
        let i = 0;
        for (let r = 0; r < layout.rows; r++) {
            for (let c = 0; c < layout.cols; c++) {
                i++;
                const box = [vb.x + c * stepW, vb.y + r * stepH, areaW / unit, areaH / unit].map(num).join(" ");
                const where = esc(_t("Sheet %(name)s (%(n)s of %(total)s)",
                    { name: sheetName(r, c), n: i, total }));
                pages.push('<section class="sheet">' + header +
                    '<div class="area"><svg viewBox="' + box + '" preserveAspectRatio="xMinYMin meet">' +
                    '<use href="#d"/></svg><i class="tag">' + esc(sheetName(r, c)) + "</i></div>" +
                    footer(where) + "</section>");
            }
        }
    } else {
        pages.push('<section class="sheet">' + header + '<div class="area"><svg viewBox="' +
            [vb.x, vb.y, vb.width, vb.height].map(num).join(" ") +
            '" preserveAspectRatio="xMidYMid meet"><use href="#d"/></svg></div>' +
            footer(esc(_t("Scale: %s", Math.round(layout.zoom * 100) + " %"))) + "</section>");
    }

    let text = "";
    if (opts.details && info.name) {
        const row = (label, value) => (value ? "<tr><th>" + esc(label) + "</th><td>" + esc(value) + "</td></tr>" : "");
        text += "<h1>" + title + "</h1>" + (sub ? '<p class="sub">' + sub + "</p>" : "") +
            '<table class="meta">' +
            row(_t("Status"), info.state) + row(_t("Process type"), info.category) + row(_t("Level"), info.level) +
            row(_t("Process owner"), info.owner) + row(_t("Company"), info.company) +
            row(_t("Published"), [info.published, info.published_by].filter(Boolean).join(" · ")) +
            row(_t("Diagram last saved"), info.saved_at) + "</table>";
        if (info.description) {
            text += "<h2>" + esc(_t("Purpose")) + "</h2>" + instructionHtml(info.description);
        }
        if (info.sipoc && info.sipoc.length) {
            text += '<table class="meta">' + info.sipoc.map(([l, v]) => row(l, v)).join("") + "</table>";
        }
    }
    if (opts.stepList && steps.length) {
        text += "<h2>" + esc(_t("Steps")) + '</h2><table class="steps"><thead><tr><th>#</th><th>' +
            esc(_t("Step")) + "</th><th>" + esc(_t("Who")) + "</th><th>" + esc(_t("What to do")) + "</th><th>" +
            esc(_t("Links")) + "</th></tr></thead><tbody>" +
            steps.map((s) => "<tr><td class=\"n\">" + s.n + "</td><td><b>" + esc(s.name) + "</b><small>" +
                esc(s.type) + "</small></td><td>" + esc(s.who || "") + "</td><td>" + instructionHtml(s.doc) +
                "</td><td>" + s.links.map((l) => "<div>" + (l.url ? '<a href="' + esc(l.url) + '">' + esc(l.label) +
                    "</a>" : esc(l.label)) + "<small>" + esc(l.kind) + "</small></div>").join("") + "</td></tr>").join("") +
            "</tbody></table>";
    }
    if (text) {
        pages.push('<section class="text">' + text + '<p class="foot">' + printed + "</p></section>");
    }

    const size = layout.paper + " " + (layout.landscape ? "landscape" : "portrait");
    const css = `
@page { size: ${size}; margin: ${MARGIN}mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; color: #153749;
  font-family: "Segoe UI", Roboto, "Noto Sans Georgian", "Noto Sans", Arial, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.src { position: absolute; width: 0; height: 0; overflow: hidden; }
.sheet { width: ${num(layout.pageW - 2 * MARGIN)}mm; height: ${num(layout.pageH - 2 * MARGIN)}mm;
  display: flex; flex-direction: column; overflow: hidden; break-after: page; page-break-after: always; }
.sheet:last-child { break-after: auto; page-break-after: auto; }
header { height: ${HEADER}mm; display: flex; align-items: flex-start; justify-content: space-between; gap: 6mm;
  border-bottom: 0.4mm solid #153749; padding-bottom: 2mm; }
header b { display: block; font-size: 12pt; line-height: 1.2; }
header span { font-size: 8pt; color: #5b6b77; }
header em { font-style: normal; font-size: 8pt; font-weight: 700; padding: 1mm 3mm; border-radius: 3mm;
  white-space: nowrap; }
header em.ok { background: #E1F3EE; color: #226263; }
header em.draft { background: #FFF3EC; color: #B83A12; }
.area { position: relative; height: ${num(areaH)}mm; width: ${num(areaW)}mm; }
.area svg { width: ${num(areaW)}mm; height: ${num(areaH)}mm; display: block; }
.tag { position: absolute; right: 0; top: 1mm; font-style: normal; font-size: 7pt; color: #8a99a6; }
footer { height: ${FOOTER}mm; display: flex; justify-content: space-between; align-items: flex-end;
  font-size: 7pt; color: #5b6b77; border-top: 0.2mm solid #d7dee3; }
.n circle { fill: #F05324; stroke: #fff; stroke-width: 2; }
.n text { fill: #fff; font: 700 11px sans-serif; text-anchor: middle; }
.text { font-size: 9.5pt; line-height: 1.4; }
h1 { font-size: 18pt; margin: 0 0 1mm; }
h2 { font-size: 12pt; margin: 6mm 0 2mm; color: #226263; }
.sub { margin: 0 0 4mm; color: #5b6b77; }
p { margin: 0 0 1.5mm; }
ul { margin: 0 0 1.5mm; padding-left: 5mm; }
table { border-collapse: collapse; width: 100%; }
.meta th { text-align: left; width: 45mm; color: #5b6b77; font-weight: 600; vertical-align: top; padding: 1mm 3mm 1mm 0; }
.meta td { padding: 1mm 0; white-space: pre-line; }
.steps th { text-align: left; font-size: 8pt; color: #fff; background: #153749; padding: 1.5mm 2mm; }
.steps td { vertical-align: top; padding: 1.8mm 2mm; border-bottom: 0.2mm solid #d7dee3; }
.steps tr { break-inside: avoid; page-break-inside: avoid; }
.steps thead { display: table-header-group; }
.steps td.n { width: 8mm; font-weight: 700; color: #F05324; }
.steps small { display: block; color: #8a99a6; font-size: 7.5pt; }
.steps a { color: #226263; }
.foot { margin-top: 6mm; font-size: 7pt; color: #8a99a6; }
`;
    return "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>" + title + "</title><style>" + css +
        "</style></head><body>" +
        '<svg class="src" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><g id="d">' + inner + badges +
        "</g></svg>" + pages.join("") + "</body></html>";
}

/** Print an HTML document through a hidden iframe (the page itself stays as it is). */
export function printHtml(html) {
    return new Promise((resolve) => {
        const frame = document.createElement("iframe");
        frame.setAttribute("aria-hidden", "true");
        frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
        let done = false;
        const cleanup = () => {
            if (!done) {
                done = true;
                setTimeout(() => frame.remove(), 500);
                resolve();
            }
        };
        frame.onload = () => {
            const win = frame.contentWindow;
            win.addEventListener("afterprint", cleanup);
            // let the SVG lay out before the print preview is taken
            setTimeout(() => {
                win.focus();
                win.print();
                setTimeout(cleanup, 120000);
            }, 150);
        };
        frame.srcdoc = html;
        document.body.append(frame);
    });
}

export { MAX_SHEETS };
