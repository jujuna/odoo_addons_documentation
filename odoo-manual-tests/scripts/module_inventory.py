#!/usr/bin/env python3
"""List what a tester can see and trigger in an Odoo module, with exact labels.

Usage:
    python3 module_inventory.py MODULE_DIR [--db DBNAME] [--port 5433] [--full]

Prints Markdown: size, menus, window actions, buttons (label, confirm popup,
visibility rule), tabs, coloured boxes, ribbons, search filters, scheduled
jobs, state/status selections, and every UserError / ValidationError message
with file:line. With --db it also reads the live menu paths of the module.
Everything printed comes from the source, so the checklist never has to
guess a label. Ends with a suggested number of test cases.
"""
import argparse
import ast
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from lxml import etree

ERROR_CLASSES = {"UserError", "ValidationError", "AccessError", "RedirectWarning", "MissingError"}
GENERIC_BUTTONS = {"cancel", "close", "discard", "ok", "save", "confirm", "apply", "done", "back"}


def short(text, n=110):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ------------------------------------------------------------------------ XML
def element_text(el):
    return short(" ".join(t for t in el.itertext() if t.strip()), 160)


def button_label(btn):
    """Visible label of a button: string attr, else stat-button field string, else text."""
    if btn.get("string"):
        return btn.get("string")
    field = btn.find(".//field[@string]")
    if field is not None:
        return field.get("string")
    span = btn.find(".//span[@class='o_stat_text']")
    if span is not None and (span.text or "").strip():
        return span.text.strip()
    return element_text(btn) or btn.get("name", "?")


def scan_xml(path, out):
    try:
        tree = etree.parse(str(path), etree.XMLParser(remove_comments=True, recover=True))
    except etree.XMLSyntaxError:
        return
    root = tree.getroot()
    if root is None:
        return
    rel = path.name
    for menu in root.iter("menuitem"):
        out["menus"].append((menu.get("name") or "(from action)", menu.get("id"), menu.get("parent") or "(top)",
                             menu.get("action") or "", rel))
    for rec in root.iter("record"):
        model = rec.get("model")
        fields = {f.get("name"): f for f in rec.findall("field")}
        if model == "ir.actions.act_window":
            out["actions"].append((
                (fields.get("name").text if fields.get("name") is not None else rec.get("id")),
                rec.get("id"),
                fields.get("res_model").text if fields.get("res_model") is not None else "",
                fields.get("target").text if fields.get("target") is not None else "current",
                rel,
            ))
        elif model == "ir.cron":
            def val(key):
                f = fields.get(key)
                if f is None:
                    return ""
                return f.get("eval") or (f.text or "")
            out["crons"].append((val("name"), val("code"), f"{val('interval_number')} {val('interval_type')}",
                                 val("active") or "True", rel))
        elif model == "ir.ui.view" and fields.get("arch") is not None:
            view_model = fields.get("model").text if fields.get("model") is not None else "?"
            arch = fields["arch"]
            where = f"{rel} [{rec.get('id')}] ({view_model})"
            for form in arch.iter("form"):
                if form.get("string"):
                    out["forms"].append((form.get("string"), where))
            for btn in arch.iter("button"):
                out["buttons"].append({
                    "label": button_label(btn),
                    "method": btn.get("name") or "",
                    "confirm": btn.get("confirm") or "",
                    "invisible": btn.get("invisible") or "",
                    "stat": "oe_stat_button" in (btn.get("class") or ""),
                    "where": where,
                })
            for page in arch.iter("page"):
                if page.get("string"):
                    out["pages"].append((page.get("string"), page.get("invisible") or "", where))
            for div in arch.iter("div"):
                cls = div.get("class") or ""
                if "alert" in cls.split() or any(c.startswith("alert-") for c in cls.split()):
                    strong = div.find(".//strong")
                    head = element_text(strong) if strong is not None else element_text(div)
                    colour = next((c.replace("alert-", "") for c in cls.split() if c.startswith("alert-")), "")
                    out["boxes"].append((head, colour, div.get("invisible") or "", where))
            for widget in arch.iter("widget"):
                if widget.get("name") == "web_ribbon":
                    out["ribbons"].append((widget.get("title") or "", widget.get("invisible") or "", where))
            for flt in arch.iter("filter"):
                if flt.get("string"):
                    out["filters"].append((flt.get("string"), where))


# --------------------------------------------------------------------- Python
def literal_text(node, constants):
    """Best-effort readable text of a message expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
        if name == "_" and node.args:
            return literal_text(node.args[0], constants)
    if isinstance(node, ast.BinOp):
        return literal_text(node.left, constants)
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def selection_labels(node, list_constants):
    if isinstance(node, ast.Name):
        return list_constants.get(node.id)
    if isinstance(node, ast.List):
        labels = []
        for elt in node.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) == 2 and isinstance(elt.elts[1], ast.Constant):
                key = elt.elts[0].value if isinstance(elt.elts[0], ast.Constant) else "?"
                labels.append(f"{key}={elt.elts[1].value}")
        return labels or None
    return None


def scan_py(path, out, root_dir):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    rel = str(path.relative_to(root_dir))
    constants, list_constants = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                constants[name] = node.value.value
            labels = selection_labels(node.value, {})
            if labels:
                list_constants[name] = labels
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            attrs = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    attrs[stmt.targets[0].id] = stmt.value
            bases = [ast.unparse(b) for b in node.bases]
            name = attrs.get("_name")
            inherit = attrs.get("_inherit")
            kind = "wizard" if any("TransientModel" in b for b in bases) else "model"
            if isinstance(name, ast.Constant):
                out["models"].append((name.value, kind, rel))
            elif inherit is not None:
                out["inherits"].append((ast.unparse(inherit), rel))
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                        and ast.unparse(stmt.value.func).endswith("fields.Selection")
                        and isinstance(stmt.targets[0], ast.Name)
                        and re.search(r"state|status", stmt.targets[0].id)):
                    arg = stmt.value.args[0] if stmt.value.args else next(
                        (k.value for k in stmt.value.keywords if k.arg == "selection"), None)
                    labels = selection_labels(arg, list_constants) if arg is not None else None
                    out["selections"].append((stmt.targets[0].id, ", ".join(labels or ["(computed)"]), rel))
                if (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                        and ast.unparse(stmt.value.func).endswith("models.Constraint")
                        and len(stmt.value.args) >= 2):
                    out["errors"].append(("DB constraint", literal_text(stmt.value.args[1], constants),
                                          f"{rel}:{stmt.lineno}"))
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            cls = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
            if cls in ERROR_CLASSES and node.exc.args:
                out["errors"].append((cls, literal_text(node.exc.args[0], constants), f"{rel}:{node.lineno}"))
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                if isinstance(deco, ast.Call) and ast.unparse(deco.func).endswith("api.constrains"):
                    out["constrains"].append((node.name, f"{rel}:{node.lineno}"))


# ------------------------------------------------------------------------- DB
def live_menus(module, db, port):
    sql = (
        "WITH RECURSIVE m AS (SELECT id, parent_id, (name->>'en_US')::text AS path FROM ir_ui_menu "
        "WHERE parent_id IS NULL AND active UNION ALL SELECT c.id, c.parent_id, m.path || ' > ' || (c.name->>'en_US') "
        "FROM ir_ui_menu c JOIN m ON c.parent_id = m.id WHERE c.active) "
        "SELECT m.path FROM m JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = m.id "
        f"WHERE d.module = '{module}' ORDER BY 1;"
    )
    state_sql = f"SELECT state FROM ir_module_module WHERE name = '{module}';"
    try:
        state = subprocess.run(["psql", "-p", str(port), "-d", db, "-At", "-c", state_sql],
                               capture_output=True, text=True, timeout=30)
        menus = subprocess.run(["psql", "-p", str(port), "-d", db, "-At", "-c", sql],
                               capture_output=True, text=True, timeout=30)
    except Exception as e:  # psql missing or blocked
        return None, f"psql failed: {e}\nRun yourself:\n{state_sql}\n{sql}"
    if state.returncode or menus.returncode:
        return None, f"psql failed: {state.stderr or menus.stderr}\nRun yourself:\n{state_sql}\n{sql}"
    return state.stdout.strip() or "not in this DB", menus.stdout.strip().splitlines()


# --------------------------------------------------------------------- output
def suggest(n_actions, n_errors):
    """Suggested test-case range: about 1.1 cases per user-facing action (rs_einvoice:
    32 actions -> 35 cases, the size the user asked for), 10-50 overall, a quarter of
    them safety cases."""
    target = min(50, max(10, round(n_actions * 1.1)))
    safety = min(max(3, round(target * 0.25)), max(3, n_errors))
    return max(10, target - 3), min(50, target + 3), safety


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("module_dir")
    parser.add_argument("--db")
    parser.add_argument("--port", default="5433")
    parser.add_argument("--full", action="store_true", help="print every error message (default: first 60)")
    args = parser.parse_args()
    root = Path(args.module_dir).resolve()
    if not (root / "__manifest__.py").exists():
        sys.exit(f"{root} has no __manifest__.py")
    out = {k: [] for k in ("menus", "actions", "crons", "forms", "buttons", "pages", "boxes", "ribbons",
                           "filters", "models", "inherits", "selections", "errors", "constrains")}
    lines = Counter()
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or "/tests/" in str(path) or not path.is_file():
            continue
        if path.suffix in (".py", ".xml", ".js", ".scss"):
            lines[path.suffix] += sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        if path.suffix == ".xml":
            scan_xml(path, out)
        elif path.suffix == ".py":
            scan_py(path, out, root)

    module = root.name
    print(f"# Inventory of `{module}`\n")
    print("## Size")
    print(f"- Python {lines['.py']} lines · XML {lines['.xml']} · JS {lines['.js']} · SCSS {lines['.scss']}")
    print(f"- New models: {len([m for m in out['models'] if m[1] == 'model'])} · wizards: "
          f"{len([m for m in out['models'] if m[1] == 'wizard'])} · inherited: {len(out['inherits'])}")

    def table(title, header, rows):
        if not rows:
            return
        print(f"\n## {title}\n")
        print("| " + " | ".join(header) + " |")
        print("|" + "---|" * len(header))
        for row in rows:
            print("| " + " | ".join(short(str(c), 120).replace("|", "/") for c in row) + " |")

    table("Menus (XML)", ["Menu", "id", "Parent", "Action", "File"], out["menus"])
    table("Window actions", ["Name", "id", "Model", "Target", "File"], out["actions"])
    grouped = OrderedDict()
    for b in out["buttons"]:
        grouped.setdefault(b["where"], []).append(b)
    if grouped:
        print("\n## Buttons (label = what the tester sees)")
        for where, buttons in grouped.items():
            print(f"\n**{where}**\n")
            print("| Label | Method | Confirm popup | Visible unless | Smart box |")
            print("|---|---|---|---|---|")
            for b in buttons:
                print(f"| {short(b['label'], 60)} | {b['method']} | {short(b['confirm'], 90)} | "
                      f"{short(b['invisible'], 90).replace('|', '/')} | {'yes' if b['stat'] else ''} |")
    table("Form titles (pop-up windows)", ["Title", "View"], out["forms"])
    table("Tabs", ["Tab", "Hidden when", "View"], out["pages"])
    table("Coloured boxes (starts with)", ["Text", "Colour", "Hidden when", "View"], out["boxes"])
    table("Corner ribbons", ["Title", "Hidden when", "View"], out["ribbons"])
    table("Search filters", ["Filter", "View"], out["filters"])
    table("Scheduled jobs", ["Name", "Code", "Every", "Active", "File"], out["crons"])
    table("Models", ["Model", "Kind", "File"], out["models"])
    table("Status / state selections", ["Field", "Values", "File"], out["selections"])
    errors = out["errors"] if args.full else out["errors"][:60]
    table(f"Error messages ({len(out['errors'])} total{'' if args.full else ', first 60; --full for all'})",
          ["Type", "Message starts with", "Where"], errors)
    table("@api.constrains checks", ["Method", "Where"], out["constrains"])

    if args.db:
        state, menus = live_menus(module, args.db, args.port)
        print(f"\n## Live menus in `{args.db}`\n")
        if state is None:
            print(menus)
        else:
            print(f"- module state: {state}")
            for m in menus:
                print(f"- {m}")

    labels = {b["label"].strip().lower() for b in out["buttons"] if b["label"]} - GENERIC_BUTTONS
    n_actions = len(labels) + len(out["menus"]) + len([m for m in out["models"] if m[1] == "wizard"])
    low, high, safety = suggest(n_actions, len(out["errors"]))
    print("\n## Suggested size")
    print(f"- User-facing actions: {len(labels)} distinct buttons + {len(out['menus'])} menus + "
          f"{len([m for m in out['models'] if m[1] == 'wizard'])} wizards = {n_actions}")
    print(f"- Test cases: **{low}-{high}**, of which about **{safety}** safety cases (Odoo must refuse).")


if __name__ == "__main__":
    main()
