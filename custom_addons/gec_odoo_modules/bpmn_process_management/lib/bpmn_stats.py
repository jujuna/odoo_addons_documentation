# Part of bpmn_process_management. License LGPL-3.
"""Structural figures of one BPMN diagram for the dashboard (pure Python, no Odoo).
A *role* is who performs a step: lane (or pool) responsible, else its name;
a *handoff* is a sequence or message flow between two different roles."""
from .bpmn_common import (
    ACTIVITY_TAGS, FLOW_NODE_TAGS, element_name, get_documentation, local, odoo_items,
    parse_bpmn, q,
)

GATEWAY_DECISIONS = {"exclusiveGateway", "inclusiveGateway", "complexGateway", "eventBasedGateway"}


def _responsible(el):
    items = odoo_items(el, "responsible") if el is not None else []
    if not items:
        return None
    r = items[0]
    try:
        res_id = int(r.get("resId"))
    except (TypeError, ValueError):
        res_id = None
    return {"model": r.get("model") or "", "resId": res_id, "name": r.get("name") or ""}


def role_of(container):
    """(key, label, responsible) of a lane or pool element, or (None, '', None)."""
    if container is None:
        return None, "", None
    resp = _responsible(container)
    name = element_name(container)
    if resp and resp["model"] and resp["resId"]:
        return "res:%s:%s" % (resp["model"], resp["resId"]), resp["name"] or name, resp
    if name:
        return "name:" + " ".join(name.lower().split()), name, None
    return None, "", None


def process_stats(xml):
    root = parse_bpmn(xml)
    lane_of, pool_of = {}, {}
    all_participants = list(root.iter(q("bpmn", "participant")))
    # collapsed pools have no processRef: keep them all
    participants = {p.get("processRef"): p for p in all_participants if p.get("processRef")}
    lanes = list(root.iter(q("bpmn", "lane")))
    for lane in lanes:  # document order: nested (inner) lanes win
        for ref in lane.findall(q("bpmn", "flowNodeRef")):
            if ref.text:
                lane_of[ref.text.strip()] = lane
    procs_with_lanes = set()
    for proc in root.iter(q("bpmn", "process")):
        if proc.find(".//" + q("bpmn", "lane")) is not None:
            procs_with_lanes.add(proc.get("id"))
        part = participants.get(proc.get("id"))
        if part is None:
            continue
        for el in proc.iter():
            if isinstance(el.tag, str) and el.get("id"):
                pool_of[el.get("id")] = part

    # lanes that are leaves (no child lanes) + pools without lanes = the roles drawn
    leaf_lanes = [ln for ln in lanes if ln.find(".//" + q("bpmn", "lane")) is None]
    # a collapsed pool (no processRef) is an outside party: not a role to assign
    containers = leaf_lanes + [p for p in all_participants
                               if p.get("processRef") and p.get("processRef") not in procs_with_lanes]
    assigned = sum(1 for c in containers if _responsible(c))

    roles = {}
    node_role = {}

    def role_entry(key, label, resp, external=False):
        if key not in roles:
            roles[key] = {"key": key, "label": label, "responsible": resp, "steps": 0,
                          "decisions": 0, "documented": 0, "linked": 0, "events": 0,
                          "external": external}
        return roles[key]

    for c in containers:
        key, label, resp = role_of(c)
        if key:
            role_entry(key, label, resp)

    steps = documented = linked = decisions = events = 0
    for el in root.iter():
        if not isinstance(el.tag, str) or not el.get("id"):
            continue
        tag = local(el.tag)
        if tag not in FLOW_NODE_TAGS:
            continue
        eid = el.get("id")
        container = lane_of.get(eid)
        if container is None:
            container = pool_of.get(eid)
        key, label, resp = role_of(container)
        node_role[eid] = key
        entry = role_entry(key, label, resp) if key else None
        if tag in ACTIVITY_TAGS:
            steps += 1
            has_doc = bool(get_documentation(el))
            has_link = bool(odoo_items(el, "link"))
            documented += has_doc
            linked += has_link
            if entry:
                entry["steps"] += 1
                entry["documented"] += has_doc
                entry["linked"] += has_link
        elif tag in GATEWAY_DECISIONS:
            decisions += 1
            if entry:
                entry["decisions"] += 1
        elif tag.endswith("Event"):
            events += 1
            if entry:
                entry["events"] += 1

    # pools themselves are a role for message flows that end on the pool
    pool_roles = {}
    for part in all_participants:
        key, label, resp = role_of(part)
        node_role.setdefault(part.get("id"), key)
        if key:
            # a collapsed pool (no processRef) is an outside party: customer, supplier...
            pool_roles[key] = (label, resp, not part.get("processRef"))

    handoffs = []
    flows = 0
    for tag in ("sequenceFlow", "messageFlow"):
        for fl in root.iter(q("bpmn", tag)):
            flows += 1
            a = node_role.get(fl.get("sourceRef"))
            b = node_role.get(fl.get("targetRef"))
            if a and b and a != b:
                handoffs.append((a, b))
                for k in (a, b):
                    if k not in roles and k in pool_roles:
                        role_entry(k, *pool_roles[k])

    return {
        "steps": steps,
        "documented": documented,
        "linked": linked,
        "decisions": decisions,
        "events": events,
        "flows": flows,
        "lanes": len(containers),
        "lanes_assigned": assigned,
        "roles": roles,
        "handoffs": handoffs,
    }
