# Part of bpmn_process_management. License LGPL-3.
"""Read Odoo metadata out of a BPMN document (for the searchable element index)
and apply automatic responsibility matching after an import."""
from .bpmn_common import (
    FLOW_NODE_TAGS, element_name, get_documentation, local, odoo_items, parse_bpmn, q,
    remove_odoo_item, set_odoo_item, to_string,
)

INDEXED_TAGS = FLOW_NODE_TAGS | {"lane", "participant", "dataObjectReference",
                                 "dataStoreReference"}


def _link_dict(el):
    return {k: el.get(k) for k in ("linkType", "label", "xmlid", "model", "resId", "url")
            if el.get(k)}


def extract_elements(xml):
    root = parse_bpmn(xml)
    lane_of, pool_of = {}, {}
    participants = {p.get("processRef"): p for p in root.iter(q("bpmn", "participant"))}
    for lane in root.iter(q("bpmn", "lane")):
        for ref in lane.findall(q("bpmn", "flowNodeRef")):
            if ref.text:
                lane_of[ref.text.strip()] = lane
    for proc in root.iter(q("bpmn", "process")):
        part = participants.get(proc.get("id"))
        if part is None:
            continue
        for el in proc.iter():
            if isinstance(el.tag, str) and el.get("id"):
                pool_of[el.get("id")] = part
    out = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = local(el.tag)
        if tag not in INDEXED_TAGS or not el.get("id"):
            continue
        eid = el.get("id")
        resp = odoo_items(el, "responsible")
        review = odoo_items(el, "review")
        lane = lane_of.get(eid)
        pool = pool_of.get(eid)
        responsible = None
        if resp:
            r = resp[0]
            responsible = {"model": r.get("model"), "resId": _int(r.get("resId")),
                           "xmlid": r.get("xmlid"), "name": r.get("name")}
        elif lane is not None and odoo_items(lane, "responsible"):
            r = odoo_items(lane, "responsible")[0]
            responsible = {"model": r.get("model"), "resId": _int(r.get("resId")),
                           "xmlid": r.get("xmlid"), "name": r.get("name"), "inherited": True}
        elif lane is None and pool is not None and pool is not el and odoo_items(pool, "responsible"):
            # pool without lanes: its responsible performs every step
            r = odoo_items(pool, "responsible")[0]
            responsible = {"model": r.get("model"), "resId": _int(r.get("resId")),
                           "xmlid": r.get("xmlid"), "name": r.get("name"), "inherited": True}
        rv = None
        if review and review[0].get("status", "pending") == "pending":
            rv = {"reason": review[0].get("reason") or "imported",
                  "note": review[0].get("note") or "", "source": review[0].get("source") or ""}
        out.append({
            "element_id": eid,
            "element_type": tag,
            "name": element_name(el),
            "lane_name": element_name(lane) if lane is not None else "",
            "pool_name": element_name(pool) if pool is not None else "",
            "documentation": get_documentation(el),
            "links": [_link_dict(lk) for lk in odoo_items(el, "link")],
            "responsible": responsible,
            "review": rv,
        })
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def apply_responsible_matching(xml, matcher):
    """Ask ``matcher(name)`` for the responsible of each lane (or lane-less participant) that has none.
    ``matcher`` returns ``{'model', 'resId', 'xmlid', 'name'}`` or ``None``; a match gets flag ``responsible_auto``
    (to confirm), none ``responsible_missing``. Returns ``(xml, matched, missing)``."""
    root = parse_bpmn(xml)
    matched = missing = 0
    targets = list(root.iter(q("bpmn", "lane")))
    procs_with_lanes = {p.get("id") for p in root.iter(q("bpmn", "process"))
                        if p.find(".//" + q("bpmn", "lane")) is not None}
    for part in root.iter(q("bpmn", "participant")):
        # a collapsed pool (no processRef) is an outside party, not a role to assign
        if part.get("processRef") and part.get("processRef") not in procs_with_lanes:
            targets.append(part)
    for el in targets:
        if odoo_items(el, "responsible"):
            continue
        reviews = odoo_items(el, "review")
        source = reviews[0].get("source") if reviews else "import"
        name = element_name(el)
        match = matcher(name) if name else None
        if match:
            set_odoo_item(el, "responsible", {
                "model": match.get("model"), "resId": match.get("resId"),
                "xmlid": match.get("xmlid"), "name": match.get("name")})
            set_odoo_item(el, "review", {"status": "pending", "reason": "responsible_auto",
                                         "source": source})
            matched += 1
        else:
            set_odoo_item(el, "review", {"status": "pending", "reason": "responsible_missing",
                                         "source": source})
            missing += 1
    return to_string(root), matched, missing


def clear_review(xml, element_id):
    root = parse_bpmn(xml)
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("id") == element_id:
            remove_odoo_item(el, "review")
    return to_string(root)
