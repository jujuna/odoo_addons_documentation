// Part of bpmn_process_management. License LGPL-3.
import { repairConnection, withoutRedundantPoints } from 'diagram-js/lib/layout/ManhattanLayout';
import { getMid, getOrientation } from 'diagram-js/lib/layout/LayoutUtil';
import { setSnapped } from 'diagram-js/lib/features/snapping/SnapUtil';
import RuleProvider from 'diagram-js/lib/features/rules/RuleProvider';
import { getExternalLabelMid, getWaypointsMid } from 'bpmn-js/lib/util/LabelUtil';

function isType(element, type) {
  var bo = element && (element.businessObject || element);
  return !!(bo && bo.$instanceOf && bo.$instanceOf(type));
}

function isAnyType(element, types) {
  return types.some(function(t) { return isType(element, t); });
}

function ConnectHighlighter(eventBus, elementRegistry, canvas, bpmnRules) {
  var marked = [];
  var MARK = 'o-connect-candidate';
  var SOURCE = 'o-connect-source';

  function clear() {
    marked.forEach(function(el) {
      canvas.removeMarker(el, MARK);
      canvas.removeMarker(el, SOURCE);
    });
    marked = [];
  }

  function isShape(el) {
    return el && !el.waypoints && !el.labelTarget && el.type !== 'label' && el.parent &&
      el.type !== 'bpmn:Process' && el.type !== 'bpmn:Collaboration';
  }

  function mark(source, test) {
    clear();
    if (source) {
      canvas.addMarker(source, SOURCE);
      marked.push(source);
    }
    elementRegistry.forEach(function(el) {
      if (!isShape(el) || el === source) {
        return;
      }
      var ok = false;
      try {
        ok = test(el);
      } catch (e) {
        ok = false;
      }
      if (ok) {
        canvas.addMarker(el, MARK);
        marked.push(el);
      }
    });
  }

  eventBus.on('connect.start', function(event) {
    var context = event.context || {};
    var source = context.start || context.source;
    if (!source) {
      return;
    }
    mark(source, function(target) {
      return !!bpmnRules.canConnect(source, target);
    });
  });
  eventBus.on('connect.cleanup', clear);

  eventBus.on('bendpoint.move.start', function(event) {
    var context = event.context || {};
    var connection = context.connection;
    // 'reconnectStart' | 'reconnectEnd' | 'updateWaypoints'
    if (!connection || (context.type !== 'reconnectStart' && context.type !== 'reconnectEnd')) {
      return;
    }
    var moveStart = context.type === 'reconnectStart';
    mark(null, function(target) {
      return moveStart
        ? !!bpmnRules.canConnect(target, connection.target, connection)
        : !!bpmnRules.canConnect(connection.source, target, connection);
    });
  });
  eventBus.on(['bendpoint.move.cleanup', 'bendpoint.move.end', 'bendpoint.move.cancel'], clear);

  eventBus.on('create.start', function(event) {
    var shape = event.context && event.context.shape;
    if (!shape || shape.waypoints) {
      return;
    }
    var containers = ['bpmn:Participant', 'bpmn:Lane', 'bpmn:SubProcess', 'bpmn:Transaction',
      'bpmn:AdHocSubProcess'];
    mark(null, function(target) {
      return containers.indexOf(target.type) !== -1 && !!bpmnRules.canCreate(shape, target);
    });
  });
  eventBus.on(['create.cleanup'], clear);
}
ConnectHighlighter.$inject = ['eventBus', 'elementRegistry', 'canvas', 'bpmnRules'];

function OdooPaletteProvider(palette, create, elementFactory, translate) {
  this._create = create;
  this._elementFactory = elementFactory;
  this._translate = translate;
  palette.registerProvider(500, this);
}
OdooPaletteProvider.$inject = ['palette', 'create', 'elementFactory', 'translate'];

OdooPaletteProvider.prototype.getPaletteEntries = function() {
  var create = this._create, elementFactory = this._elementFactory, translate = this._translate;
  function entry(group, className, title, attrs) {
    function start(event) {
      create.start(event, elementFactory.createShape(Object.assign({}, attrs)));
    }
    return { group: group, className: className, title: translate(title),
      action: { dragstart: start, click: start } };
  }
  return {
    'odoo.start-message': entry('event', 'bpmn-icon-start-event-message', 'Create message start event',
      { type: 'bpmn:StartEvent', eventDefinitionType: 'bpmn:MessageEventDefinition' }),
    'odoo.start-timer': entry('event', 'bpmn-icon-start-event-timer', 'Create timer start event',
      { type: 'bpmn:StartEvent', eventDefinitionType: 'bpmn:TimerEventDefinition' }),
    'odoo.gateway-parallel': entry('gateway', 'bpmn-icon-gateway-parallel', 'Create parallel gateway',
      { type: 'bpmn:ParallelGateway' }),
    'odoo.user-task': entry('activity', 'bpmn-icon-user-task', 'Create user task', { type: 'bpmn:UserTask' }),
    'odoo.service-task': entry('activity', 'bpmn-icon-service-task', 'Create service task', { type: 'bpmn:ServiceTask' }),
    'odoo.call-activity': entry('activity', 'bpmn-icon-call-activity', 'Create call activity', { type: 'bpmn:CallActivity' }),
    'odoo.text-annotation': entry('data-store', 'bpmn-icon-text-annotation', 'Create text annotation',
      { type: 'bpmn:TextAnnotation' }),
  };
};

// Extra keyboard shortcuts (the canvas needs the focus); the web client provides the callbacks.
function OdooKeyboardBindings(keyboard, eventBus) {
  keyboard.addListener(900, function(context) {
    var e = context.keyEvent;
    var cmd = keyboard.isCmd(e);
    var key = (e.key || '').toLowerCase();
    if (cmd && key === 's') {
      eventBus.fire('odoo.save');
      return true;
    }
    if (cmd && !e.altKey && !e.shiftKey && (key === 'b' || key === 'i' || key === 'u')) {
      eventBus.fire('odoo.text', { toggle: { b: 'fontWeight', i: 'fontStyle', u: 'textDecoration' }[key] });
      return true;
    }
    if (cmd && e.shiftKey && (e.key === '>' || e.key === '<' || e.code === 'Period' || e.code === 'Comma')) {
      eventBus.fire('odoo.text', { size: (e.key === '>' || e.code === 'Period') ? 1 : -1 });
      return true;
    }
    if (!cmd && !e.altKey && (e.key === '?' || (e.shiftKey && key === '/'))) {
      eventBus.fire('odoo.shortcuts');
      return true;
    }
    if (!cmd && !e.altKey && !e.shiftKey && key === 'f') {
      eventBus.fire('odoo.fullscreen');
      return true;
    }
    if (!cmd && !e.altKey && !e.shiftKey && key === 'm') {
      eventBus.fire('odoo.minimap');
      return true;
    }
    if (!cmd && !e.altKey && !e.shiftKey && key === 'g') {
      eventBus.fire('odoo.grid');
      return true;
    }
    if (!cmd && !e.altKey && !e.shiftKey && key === '0') {
      eventBus.fire('odoo.fit');
      return true;
    }
    if (!cmd && !e.altKey && !e.shiftKey && key === 'p') {
      eventBus.fire('odoo.panel');
      return true;
    }
  });
}
OdooKeyboardBindings.$inject = ['keyboard', 'eventBus'];

// External labels: bpmn-js sizes the box to the rounded text width, which can split a long word
// ("Inspectio" / "n"). Give the box a few pixels of slack.
function LabelBoundsFix(textRenderer) {
  var original = textRenderer.getExternalLabelBounds.bind(textRenderer);
  textRenderer.getExternalLabelBounds = function(bounds, text) {
    var r = original(bounds, text);
    if (!r || !text) {
      return r;
    }
    return { x: Math.round(r.x - 3), y: r.y, width: Math.ceil(r.width) + 6, height: r.height };
  };
}
LabelBoundsFix.$inject = ['textRenderer'];


var SVG_NS = 'http://www.w3.org/2000/svg';
var PORT_SNAP_PX = 18;
var SIMPLE_PORT_TYPES = ['bpmn:Event', 'bpmn:Gateway', 'bpmn:DataObjectReference',
  'bpmn:DataStoreReference'];

export function getPorts(el) {
  var x = el.x, y = el.y, w = el.width, h = el.height, out = [];
  if (isAnyType(el, SIMPLE_PORT_TYPES)) {
    return [
      { x: x + w / 2, y: y, side: 't' }, { x: x + w, y: y + h / 2, side: 'r' },
      { x: x + w / 2, y: y + h, side: 'b' }, { x: x, y: y + h / 2, side: 'l' }
    ].map(roundPoint);
  }
  function count(len) {
    return len < 50 ? 1 : len <= 180 ? 3 : 5;
  }
  var nx = count(w), ny = count(h), i;
  for (i = 1; i <= nx; i++) {
    out.push({ x: x + w * i / (nx + 1), y: y, side: 't' });
    out.push({ x: x + w * i / (nx + 1), y: y + h, side: 'b' });
  }
  for (i = 1; i <= ny; i++) {
    out.push({ x: x, y: y + h * i / (ny + 1), side: 'l' });
    out.push({ x: x + w, y: y + h * i / (ny + 1), side: 'r' });
  }
  return out.map(roundPoint);
}

function roundPoint(p) {
  return { x: Math.round(p.x), y: Math.round(p.y), side: p.side };
}

function hasPorts(el) {
  return !!el && !el.waypoints && !el.labelTarget && el.type !== 'label' &&
    isAnyType(el, ['bpmn:FlowNode', 'bpmn:DataObjectReference', 'bpmn:DataStoreReference',
      'bpmn:Participant']) && !isType(el, 'bpmn:Lane');
}

// The docked side is stored on the flow (<odoo:dock source="b" target="l"/>), so routing survives a reopen.
function DockStore(eventBus, injector) {
  var self = this;
  this.pending = null;

  this.read = function(connection) {
    var bo = connection && connection.businessObject;
    var ext = bo && bo.extensionElements;
    var v = ext && (ext.values || []).filter(function(x) { return isType(x, 'odoo:Dock'); })[0];
    return v ? { source: v.source || null, target: v.target || null } : {};
  };

  this.effective = function(connection) {
    var dock = self.read(connection);
    if (self.pending) {
      Object.keys(self.pending).forEach(function(k) {
        if (k === 'source' || k === 'target') {
          dock[k] = self.pending[k];
        }
      });
    }
    return dock;
  };

  function write(connection, dock) {
    var modeling = injector.get('modeling'), moddle = injector.get('moddle');
    var bo = connection.businessObject;
    var ext = bo.extensionElements;
    var has = dock.source || dock.target;
    if (!ext) {
      if (!has) {
        return;
      }
      ext = moddle.create('bpmn:ExtensionElements', { values: [] });
      modeling.updateModdleProperties(connection, bo, { extensionElements: ext });
    }
    var others = (ext.values || []).filter(function(x) { return !isType(x, 'odoo:Dock'); });
    var attrs = {};
    if (dock.source) {
      attrs.source = dock.source;
    }
    if (dock.target) {
      attrs.target = dock.target;
    }
    modeling.updateModdleProperties(connection, ext, {
      values: others.concat(has ? [moddle.create('odoo:Dock', attrs)] : [])
    });
  }

  eventBus.on(['commandStack.connection.create.postExecuted',
    'commandStack.connection.reconnect.postExecuted'], function(event) {
    var connection = event.context && event.context.connection;
    var pending = self.pending;
    self.pending = null;
    if (!connection || !pending) {
      return;
    }
    var dock = self.read(connection);
    if (pending.source !== undefined) {
      dock.source = pending.source;
    }
    if (pending.target !== undefined) {
      dock.target = pending.target;
    }
    var before = self.read(connection);
    if (before.source !== dock.source || before.target !== dock.target) {
      write(connection, dock);
    }
  });
  eventBus.on(['connect.cleanup', 'bendpoint.move.cleanup'], function() {
    // let the command (fired from *.end) consume it first
    setTimeout(function() {
      self.pending = null;
    }, 0);
  });
}
DockStore.$inject = ['eventBus', 'injector'];

function Ports(eventBus, canvas, connect, dragging, elementRegistry, odooDock) {
  var layer = canvas.getLayer('odoo-ports', 1000);
  layer.setAttribute('class', (layer.getAttribute('class') || '') + ' o-ports-layer');
  var shown = null, mode = null, hideTimer = null, overPort = false;

  function zoom() {
    return canvas.zoom() || 1;
  }

  function clear() {
    while (layer.firstChild) {
      layer.removeChild(layer.firstChild);
    }
    shown = null;
    mode = null;
  }

  function show(el, how) {
    if (shown === el && mode === how) {
      return;
    }
    clear();
    shown = el;
    mode = how;
    var r = 4.5 / zoom(), sw = 1.5 / zoom();
    getPorts(el).forEach(function(p) {
      var c = document.createElementNS(SVG_NS, 'circle');
      c.setAttribute('cx', p.x);
      c.setAttribute('cy', p.y);
      c.setAttribute('r', r);
      c.setAttribute('stroke-width', sw);
      c.setAttribute('class', 'o-port o-port-' + how);
      c.__port = p;
      if (how === 'hover') {
        c.addEventListener('mouseenter', function() {
          overPort = true;
          cancelHide();
          c.classList.add('o-port-active');
        });
        c.addEventListener('mouseleave', function() {
          overPort = false;
          c.classList.remove('o-port-active');
          scheduleHide();
        });
        c.addEventListener('mousedown', function(ev) {
          if (ev.button !== 0) {
            return;
          }
          ev.preventDefault();
          ev.stopPropagation();
          var source = shown;
          clear();
          overPort = false;
          connect.start(ev, source, { x: p.x, y: p.y });
          var ctx = dragging.context();
          if (ctx && ctx.data && ctx.data.context) {
            ctx.data.context.odooStartPort = { x: p.x, y: p.y };
          }
        });
      }
      layer.appendChild(c);
    });
  }

  function activate(point) {
    Array.prototype.forEach.call(layer.childNodes, function(c) {
      var p = c.__port;
      c.classList.toggle('o-port-active', !!point && p.x === point.x && p.y === point.y);
    });
  }

  function cancelHide() {
    if (hideTimer) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function scheduleHide() {
    cancelHide();
    hideTimer = setTimeout(function() {
      hideTimer = null;
      if (!overPort && mode === 'hover') {
        clear();
      }
    }, 350);
  }

  function isDragging() {
    return !!dragging.context();
  }

  eventBus.on('element.hover', function(e) {
    if (isDragging()) {
      return;
    }
    if (hasPorts(e.element) && !isType(e.element, 'bpmn:Participant')) {
      cancelHide();
      show(e.element, 'hover');
    } else if (mode === 'hover') {
      scheduleHide();
    }
  });
  eventBus.on('element.out', function() {
    if (mode === 'hover') {
      scheduleHide();
    }
  });
  eventBus.on(['drag.init', 'shape.move.start', 'canvas.viewbox.changing', 'diagram.clear'], function() {
    if (mode === 'hover') {
      clear();
    }
  });
  eventBus.on('canvas.viewbox.changed', function() {
    if (shown) {
      var el = shown, how = mode;
      clear();
      show(el, how);
    }
  });

  function nearest(el, pos) {
    var best = null, bestD = PORT_SNAP_PX / zoom();
    getPorts(el).forEach(function(p) {
      var d = Math.sqrt(Math.pow(p.x - pos.x, 2) + Math.pow(p.y - pos.y, 2));
      if (d < bestD) {
        best = p;
        bestD = d;
      }
    });
    return best;
  }

  // remember where the pointer really is, before bpmn-js snaps it to the center
  eventBus.on(['connect.hover', 'connect.move', 'connect.end', 'bendpoint.move.hover',
    'bendpoint.move.move', 'bendpoint.move.end'], 1300, function(event) {
    if (event.context) {
      event.context.odooRaw = { x: event.x, y: event.y };
    }
  });

  function snap(event, hover, allowed) {
    if (!hover || !allowed || !hasPorts(hover)) {
      activate(null);
      return null;
    }
    var p = nearest(hover, event.context.odooRaw || event);
    if (p) {
      setSnapped(event, 'x', p.x);
      setSnapped(event, 'y', p.y);
    }
    activate(p);
    return p;
  }

  eventBus.on('connect.hover', 900, function(event) {
    var ctx = event.context;
    if (ctx.canExecute && hasPorts(ctx.hover)) {
      show(ctx.hover, 'target');
    }
  });
  eventBus.on(['connect.move', 'connect.end'], 1100, function(event) {
    var ctx = event.context;
    if (ctx.odooStartPort) {
      ctx.connectionStart = ctx.odooStartPort; // undo the "snap start to center" of bpmn-js
    }
    var free = event.originalEvent && (event.originalEvent.ctrlKey || event.originalEvent.metaKey);
    var p = free ? null : snap(event, ctx.hover, ctx.canExecute);
    if (event.type === 'connect.end') {
      var startSide = ctx.odooStartPort ? sideOf(ctx.odooStartPort, ctx.start) : null;
      var endSide = p ? p.side : null;
      var reverse = ctx.source && ctx.start && ctx.source !== ctx.start;
      odooDock.pending = (startSide || endSide)
        ? (reverse ? { source: endSide, target: startSide } : { source: startSide, target: endSide })
        : null;
    }
  });
  eventBus.on(['connect.out', 'connect.cleanup'], function() {
    clear();
  });

  function isReconnect(ctx) {
    return ctx && (ctx.type === 'reconnectStart' || ctx.type === 'reconnectEnd');
  }
  eventBus.on('bendpoint.move.hover', 900, function(event) {
    var ctx = event.context;
    if (isReconnect(ctx) && ctx.allowed && hasPorts(ctx.hover)) {
      show(ctx.hover, 'target');
    }
  });
  eventBus.on(['bendpoint.move.move', 'bendpoint.move.end'], 1100, function(event) {
    var ctx = event.context;
    if (!isReconnect(ctx)) {
      return;
    }
    var free = event.originalEvent && (event.originalEvent.ctrlKey || event.originalEvent.metaKey);
    var p = free ? null : snap(event, ctx.hover, ctx.allowed);
    if (event.type === 'bendpoint.move.end') {
      odooDock.pending = ctx.type === 'reconnectStart' ? { source: p ? p.side : null }
        : { target: p ? p.side : null };
    }
  });
  eventBus.on(['bendpoint.move.out', 'bendpoint.move.cleanup'], function() {
    clear();
  });

  this.getPorts = getPorts;
  this.clear = clear;
}
Ports.$inject = ['eventBus', 'canvas', 'connect', 'dragging', 'elementRegistry', 'odooDock'];

var SIDE_TOLERANCE = 3;

function sideOf(point, shape) {
  if (!point || !shape) {
    return null;
  }
  var t = SIDE_TOLERANCE;
  var inX = point.x >= shape.x - t && point.x <= shape.x + shape.width + t;
  var inY = point.y >= shape.y - t && point.y <= shape.y + shape.height + t;
  if (inX && Math.abs(point.y - shape.y) <= t) {
    return 't';
  }
  if (inX && Math.abs(point.y - (shape.y + shape.height)) <= t) {
    return 'b';
  }
  if (inY && Math.abs(point.x - shape.x) <= t) {
    return 'l';
  }
  if (inY && Math.abs(point.x - (shape.x + shape.width)) <= t) {
    return 'r';
  }
  return null;
}

function facingSide(shape, other, otherSide) {
  var o = getOrientation(other, shape, -10);
  var vertical = /top|bottom/.test(o), horizontal = /left|right/.test(o);
  var v = /top/.test(o) ? 't' : 'b', h = /left/.test(o) ? 'l' : 'r';
  if (o === 'intersect') {
    return otherSide === 'l' ? 'r' : otherSide === 'r' ? 'l' : otherSide === 't' ? 'b' : 't';
  }
  if (vertical && !horizontal) {
    return v;
  }
  if (horizontal && !vertical) {
    return h;
  }
  return otherSide === 'l' || otherSide === 'r' ? v : h;
}

function sidePoint(shape, side) {
  var m = getMid(shape);
  return {
    t: { x: m.x, y: shape.y }, b: { x: m.x, y: shape.y + shape.height },
    l: { x: shape.x, y: m.y }, r: { x: shape.x + shape.width, y: m.y }
  }[side];
}

function docking(point) {
  return point && (point.original || point);
}

function PortLayouter(layouter, odooDock) {
  var original = layouter.layoutConnection.bind(layouter);
  layouter.layoutConnection = function(connection, hints) {
    hints = hints || {};
    var source = hints.source || connection.source,
        target = hints.target || connection.target;
    if (!source || !target || source === target ||
        !isAnyType(connection, ['bpmn:SequenceFlow', 'bpmn:MessageFlow']) ||
        isType(source, 'bpmn:BoundaryEvent') || isType(target, 'bpmn:BoundaryEvent') ||
        source.waypoints || target.waypoints) {
      return original(connection, hints);
    }
    // only arrows explicitly docked on a connection point get side routing;
    // all others keep the standard bpmn-js layout
    var dock = odooDock.effective(connection);
    var sSide = dock.source, eSide = dock.target;
    if (!sSide && !eSide) {
      return original(connection, hints);
    }
    var waypoints = hints.waypoints || connection.waypoints;
    var start = hints.connectionStart || docking(waypoints && waypoints[0]);
    var end = hints.connectionEnd || docking(waypoints && waypoints[waypoints.length - 1]);
    if (sSide && sideOf(start, source) !== sSide) {
      start = sidePoint(source, sSide);
    }
    if (eSide && sideOf(end, target) !== eSide) {
      end = sidePoint(target, eSide);
    }
    if (!sSide) {
      sSide = facingSide(source, target, eSide);
      start = sidePoint(source, sSide);
    }
    if (!eSide) {
      eSide = facingSide(target, source, sSide);
      end = sidePoint(target, eSide);
    }
    try {
      return withoutRedundantPoints(repairConnection(source, target, start, end, waypoints,
        Object.assign({}, hints, { preferredLayouts: [sSide + ':' + eSide] })));
    } catch (e) {
      return original(connection, hints);
    }
  };
}
PortLayouter.$inject = ['layouter', 'odooDock'];

// Line jumps: a horizontal segment hops (small arc) over a crossing vertical one. Visual only; exports include it.
var JUMP_R = 5, JUMP_MARGIN = 9;

function LineJumps(eventBus, elementRegistry, canvas) {
  var timer = null;

  function segments(conn) {
    var out = [], wp = conn.waypoints || [];
    for (var i = 1; i < wp.length; i++) {
      out.push({ a: wp[i - 1], b: wp[i], conn: conn, index: i - 1 });
    }
    return out;
  }

  function isH(s) {
    return Math.abs(s.a.y - s.b.y) < 0.5 && Math.abs(s.a.x - s.b.x) > 0.5;
  }

  function isV(s) {
    return Math.abs(s.a.x - s.b.x) < 0.5 && Math.abs(s.a.y - s.b.y) > 0.5;
  }

  function between(v, p, q, margin) {
    var lo = Math.min(p, q) + margin, hi = Math.max(p, q) - margin;
    return v > lo && v < hi;
  }

  function vec(a, b, len) {
    var dx = b.x - a.x, dy = b.y - a.y, l = Math.sqrt(dx * dx + dy * dy) || 1;
    return { x: a.x + dx / l * len, y: a.y + dy / l * len };
  }

  function dist(a, b) {
    return Math.sqrt(Math.pow(b.x - a.x, 2) + Math.pow(b.y - a.y, 2));
  }

  // same corner rounding as diagram-js createLine, plus arcs at jumps
  function buildPath(wp, jumps, radius) {
    var d = ['M', wp[0].x, wp[0].y];
    function lineWithJumps(from, to, segIndex) {
      var list = (jumps[segIndex] || []).filter(function(x) {
        return between(x, from.x, to.x, JUMP_R + 1);
      });
      var dir = to.x >= from.x ? 1 : -1;
      list.sort(function(p, q) { return (p - q) * dir; });
      list.forEach(function(x) {
        d.push('L', x - dir * JUMP_R, from.y);
        d.push('A', JUMP_R, JUMP_R, 0, 0, dir > 0 ? 1 : 0, x + dir * JUMP_R, from.y);
      });
      d.push('L', to.x, to.y);
    }
    var cursor = wp[0];
    for (var i = 1; i < wp.length; i++) {
      var before = wp[i - 1], point = wp[i], after = wp[i + 1];
      var r = after && radius ? Math.min(radius, dist(before, point), dist(point, after)) : 0;
      var lineEnd = r ? vec(point, before, r) : point;
      lineWithJumps(cursor, lineEnd, i - 1);
      if (r) {
        var b2 = vec(point, before, r * 0.5), a2 = vec(point, after, r * 0.5), a1 = vec(point, after, r);
        d.push('C', b2.x, b2.y, a2.x, a2.y, a1.x, a1.y);
        cursor = a1;
      } else {
        cursor = point;
      }
    }
    return d.join(' ');
  }

  var roots = new Map();
  function rootOf(el) {
    if (!roots.has(el)) {
      var r = null;
      try {
        r = canvas.findRoot(el);
      } catch (e) {
        r = null;
      }
      roots.set(el, r);
    }
    return roots.get(el);
  }

  function run() {
    timer = null;
    roots = new Map();
    var conns = elementRegistry.filter(function(e) {
      return e.waypoints && e.waypoints.length > 1 &&
        isAnyType(e, ['bpmn:SequenceFlow', 'bpmn:MessageFlow', 'bpmn:Association',
          'bpmn:DataInputAssociation', 'bpmn:DataOutputAssociation']);
    });
    var verticals = [];
    conns.forEach(function(c) {
      segments(c).forEach(function(s) {
        if (isV(s)) {
          verticals.push(s);
        }
      });
    });
    conns.forEach(function(c) {
      var gfx = elementRegistry.getGraphics(c);
      var path = gfx && gfx.querySelector('.djs-visual > path');
      if (!path) {
        return;
      }
      var jumps = {}, any = false;
      segments(c).forEach(function(s) {
        if (!isH(s)) {
          return;
        }
        verticals.forEach(function(v) {
          if (v.conn === c || rootOf(v.conn) !== rootOf(c)) {
            return;
          }
          if (between(v.a.x, s.a.x, s.b.x, JUMP_MARGIN) && between(s.a.y, v.a.y, v.b.y, JUMP_MARGIN)) {
            (jumps[s.index] = jumps[s.index] || []).push(v.a.x);
            any = true;
          }
        });
      });
      var radius = parseInt(path.dataset && path.dataset.cornerRadius, 10) || 0;
      if (any) {
        path.setAttribute('d', buildPath(c.waypoints, jumps, radius));
        path.dataset.odooJumps = '1';
      } else if (path.dataset.odooJumps) {
        delete path.dataset.odooJumps;
        path.setAttribute('d', buildPath(c.waypoints, {}, radius));
      }
    });
  }

  function schedule() {
    if (!timer) {
      timer = setTimeout(run, 0);
    }
  }

  eventBus.on(['import.done', 'elements.changed', 'commandStack.changed'], schedule);
  eventBus.on('diagram.destroy', function() {
    if (timer) {
      clearTimeout(timer);
    }
  });
  this.update = run;
}
LineJumps.$inject = ['eventBus', 'elementRegistry', 'canvas'];


var MAGNET_PX = 16;

function PoolMagnet(eventBus, elementRegistry, canvas) {
  eventBus.on(['create.move', 'create.end', 'shape.move.move', 'shape.move.end'], 1300, function(event) {
    var ctx = event.context, shape = ctx.shape, snap = ctx.snapContext;
    if (!shape || !snap || !isType(shape, 'bpmn:Participant') ||
        (event.originalEvent && (event.originalEvent.ctrlKey || event.originalEvent.metaKey))) {
      return;
    }
    var tlO = snap.getSnapOrigin('top-left'), brO = snap.getSnapOrigin('bottom-right');
    if (!tlO || !brO) {
      return;
    }
    var moving = ctx.shapes || [shape];
    var tl = { x: event.x + tlO.x, y: event.y + tlO.y }, br = { x: event.x + brO.x, y: event.y + brO.y };
    var t = MAGNET_PX / (canvas.zoom() || 1);
    var others = elementRegistry.filter(function(e) {
      return isType(e, 'bpmn:Participant') && !e.labelTarget && moving.indexOf(e) === -1 && e !== shape;
    });
    for (var i = 0; i < others.length; i++) {
      var p = others[i];
      if (!(tl.x < p.x + p.width && br.x > p.x)) {
        continue;
      }
      var snappedY = null;
      if (Math.abs(tl.y - (p.y + p.height)) <= t) {
        snappedY = p.y + p.height - tlO.y;
      } else if (Math.abs(br.y - p.y) <= t) {
        snappedY = p.y - brO.y;
      }
      if (snappedY !== null) {
        setSnapped(event, 'y', snappedY);
        if (Math.abs(tl.x - p.x) <= t * 2) {
          setSnapped(event, 'x', p.x - tlO.x);
        }
        return;
      }
    }
  });
}
PoolMagnet.$inject = ['eventBus', 'elementRegistry', 'canvas'];


// Per-element text format and diagram-wide text size, stored as odoo:* attributes on the DI; other tools ignore them.
// bpmn-js has no per-element text style: the renderer is wrapped to apply the element's style to its texts.
var BASE_FONT = 12;

export function getTextStyle(element) {
  var target = element && (element.labelTarget || element);
  var di = target && target.di;
  if (!di || !di.get) {
    return {};
  }
  return {
    fontSize: di.get('odoostyle:fontSize') || null,
    fontWeight: di.get('odoostyle:fontWeight') || null,
    fontStyle: di.get('odoostyle:fontStyle') || null,
    textDecoration: di.get('odoostyle:textDecoration') || null,
    textAlign: di.get('odoostyle:textAlign') || null
  };
}

function TextStyles(eventBus, bpmnRenderer, textRenderer, elementRegistry, canvas) {
  var current = null;
  var lastBase = null;

  function baseFont() {
    var root = canvas.getRootElement();
    var plane = root && root.di;
    var v = plane && plane.get && plane.get('odoostyle:baseFontSize');
    return v ? Number(v) : null;
  }

  function wrap(name) {
    var original = bpmnRenderer[name].bind(bpmnRenderer);
    bpmnRenderer[name] = function(parentGfx, element, attrs) {
      var previous = current;
      current = element;
      try {
        return original(parentGfx, element, attrs);
      } finally {
        current = previous;
      }
    };
  }
  wrap('drawShape');
  wrap('drawConnection');

  var createText = textRenderer.createText.bind(textRenderer);

  function halo(textGfx) {
    if (current && current.labelTarget && textGfx && textGfx.setAttribute) {
      textGfx.setAttribute('paint-order', 'stroke');
      textGfx.setAttribute('stroke', '#ffffff');
      textGfx.setAttribute('stroke-width', '4');
      textGfx.setAttribute('stroke-linejoin', 'round');
      textGfx.setAttribute('stroke-opacity', '0.92');
    }
    return textGfx;
  }

  textRenderer.createText = function(text, options) {
    if (!current) {
      return createText(text, options);
    }
    var st = getTextStyle(current);
    var base = baseFont();
    if (!base && !st.fontSize && !st.fontWeight && !st.fontStyle && !st.textDecoration && !st.textAlign) {
      return halo(createText(text, options));
    }
    options = Object.assign({}, options);
    var style = Object.assign({}, options.style || {});
    var defaultSize = parseFloat(style.fontSize) || BASE_FONT;
    if (st.fontSize) {
      style.fontSize = Number(st.fontSize);
    } else if (base) {
      style.fontSize = Math.round(defaultSize * base / BASE_FONT * 10) / 10;
    }
    if (st.fontWeight) {
      style.fontWeight = st.fontWeight;
    }
    if (st.fontStyle) {
      style.fontStyle = st.fontStyle;
    }
    options.style = style;
    var target = current.labelTarget || current;
    if (st.textAlign && !current.labelTarget && !current.waypoints && options.align &&
        !isAnyType(target, ['bpmn:Participant', 'bpmn:Lane'])) {
      options.align = st.textAlign + '-' + (String(options.align).split('-')[1] || 'middle');
    }
    // an external label keeps the width stored in the file: widen it with the font
    // (centered on the same point) so larger text does not break word by word
    var grow = 0;
    var scale = (parseFloat(style.fontSize) || defaultSize) / defaultSize;
    if (current.labelTarget && scale > 1 && options.box && options.box.width) {
      grow = options.box.width * (scale - 1);
      options.box = Object.assign({}, options.box, { width: options.box.width + grow });
    }
    var textGfx = createText(text, options);
    if (grow) {
      textGfx.setAttribute('transform', 'translate(' + (-grow / 2) + ', 0)');
    }
    if (st.textDecoration) {
      textGfx.setAttribute('text-decoration', st.textDecoration);
    }
    return halo(textGfx);
  };

  // an external label is a separate shape: redraw it with its element;
  // a new diagram-wide size redraws everything
  eventBus.on('elements.changed', 1500, function(event) {
    var elements = event.elements;
    var seen = new Set(elements);
    elements.slice().forEach(function(el) {
      if (el.label && !seen.has(el.label)) {
        elements.push(el.label);
        seen.add(el.label);
      }
    });
    var base = baseFont();
    if (base !== lastBase) {
      lastBase = base;
      elementRegistry.getAll().forEach(function(el) {
        if (!seen.has(el)) {
          elements.push(el);
          seen.add(el);
        }
      });
    }
  });
  eventBus.on('import.done', function() {
    lastBase = baseFont();
  });
}
TextStyles.$inject = ['eventBus', 'bpmnRenderer', 'textRenderer', 'elementRegistry', 'canvas'];

var TEXT_KEYS = ['fontSize', 'fontWeight', 'fontStyle', 'textDecoration', 'textAlign'];

/** Default center of an external label; arrows: beside the middle segment, not bpmn-js's 15px offset. */
export function defaultLabelMid(el, label) {
  if (!el.waypoints) {
    return getExternalLabelMid(el);
  }
  var wp = el.waypoints;
  var a = wp[Math.max(0, Math.floor(wp.length / 2 - 1))];
  var b = wp[Math.ceil(wp.length / 2 - 1 + 0.01)] || wp[wp.length - 1];
  var m = getWaypointsMid(wp);
  return Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)
    ? { x: m.x, y: m.y - label.height / 2 - 6 }
    : { x: m.x + label.width / 2 + 6, y: m.y };
}

/** Undoable commands, one undo step per selection: odoo.text.update {elements, style: {fontSize, fontWeight, ...}},
 * odoo.text.base {size: 14 | null} (diagram-wide text size) */
function TextStyleCommands(commandStack, elementRegistry, canvas, modeling, eventBus) {
  function UpdateText() {}
  UpdateText.prototype.execute = function(ctx) {
    ctx.old = ctx.elements.map(function(el) {
      var di = el.di;
      var old = {};
      TEXT_KEYS.forEach(function(k) {
        old[k] = di.get('odoostyle:' + k);
        if (k in ctx.style) {
          di.set('odoostyle:' + k, ctx.style[k] === null ? undefined : ctx.style[k]);
        }
      });
      return old;
    });
    return changed(ctx.elements);
  };
  UpdateText.prototype.revert = function(ctx) {
    ctx.elements.forEach(function(el, i) {
      TEXT_KEYS.forEach(function(k) {
        el.di.set('odoostyle:' + k, ctx.old[i][k]);
      });
    });
    return changed(ctx.elements);
  };

  function definitions() {
    return canvas.getRootElement().di;  // the BPMNPlane holds the diagram-wide text size
  }
  function UpdateBase() {}
  UpdateBase.prototype.execute = function(ctx) {
    var defs = definitions();
    ctx.old = defs.get('odoostyle:baseFontSize');
    defs.set('odoostyle:baseFontSize', ctx.size || undefined);
    return elementRegistry.getAll();
  };
  UpdateBase.prototype.revert = function(ctx) {
    definitions().set('odoostyle:baseFontSize', ctx.old);
    return elementRegistry.getAll();
  };

  function changed(elements) {
    var out = elements.slice();
    elements.forEach(function(el) {
      if (el.label) {
        out.push(el.label);
      }
    });
    return out;
  }

  function SameSize() {}
  SameSize.prototype.preExecute = function(ctx) {
    var ref = ctx.reference;
    ctx.elements.forEach(function(el) {
      if (el === ref) {
        return;
      }
      modeling.resizeShape(el, {
        x: Math.round(el.x + (el.width - ref.width) / 2),
        y: Math.round(el.y + (el.height - ref.height) / 2),
        width: ref.width,
        height: ref.height
      });
    });
  };
  SameSize.prototype.execute = function() {
    return [];
  };
  SameSize.prototype.revert = function() {
    return [];
  };

  // generic odoostyle:* attributes (group, locked...): {elements, attrs: {key: value | null}}
  function UpdateDi() {}
  UpdateDi.prototype.execute = function(ctx) {
    var keys = Object.keys(ctx.attrs);
    ctx.old = ctx.elements.map(function(el) {
      var old = {};
      keys.forEach(function(k) {
        old[k] = el.di.get('odoostyle:' + k);
        el.di.set('odoostyle:' + k, ctx.attrs[k] === null ? undefined : ctx.attrs[k]);
      });
      return old;
    });
    return changed(ctx.elements);
  };
  UpdateDi.prototype.revert = function(ctx) {
    ctx.elements.forEach(function(el, i) {
      Object.keys(ctx.old[i]).forEach(function(k) {
        el.di.set('odoostyle:' + k, ctx.old[i][k]);
      });
    });
    return changed(ctx.elements);
  };

  function Relayout() {}
  Relayout.prototype.preExecute = function(ctx) {
    ctx.connections.forEach(function(c) {
      if (!c.source || !c.target || !c.waypoints) {
        return;
      }
      var wp = c.waypoints;
      var docked = c.businessObject && (c.businessObject.extensionElements || {}).values &&
        c.businessObject.extensionElements.values.some(function(v) { return v.$type === 'odoo:Dock'; });
      var ends = docked ? [wp[0], wp[wp.length - 1]] : [getMid(c.source), getMid(c.target)];
      modeling.layoutConnection(c, { waypoints: ends,
        connectionStart: docked ? wp[0] : undefined, connectionEnd: docked ? wp[wp.length - 1] : undefined });
    });
  };
  Relayout.prototype.execute = function() {
    return [];
  };
  Relayout.prototype.revert = function() {
    return [];
  };

  function ResetLabels() {}
  ResetLabels.prototype.preExecute = function(ctx) {
    ctx.elements.forEach(placeLabel);
  };
  ResetLabels.prototype.execute = function() {
    return [];
  };
  ResetLabels.prototype.revert = function() {
    return [];
  };

  function placeLabel(el) {
    var label = el && el.label;
    if (!label || (el.waypoints && el.waypoints.length < 2)) {
      return;
    }
    var mid = defaultLabelMid(el, label);
    var delta = { x: Math.round(mid.x - (label.x + label.width / 2)), y: Math.round(mid.y - (label.y + label.height / 2)) };
    if (delta.x || delta.y) {
      modeling.moveShape(label, delta);
    }
  }

  eventBus.on('commandStack.element.updateLabel.postExecuted', function(event) {
    var ctx = event.context;
    var el = ctx.element;
    if (el && el.waypoints && el.label && !ctx.oldLabel && ctx.newLabel) {
      placeLabel(el);
    }
  });

  commandStack.registerHandler('odoo.labels.reset', ResetLabels);
  commandStack.registerHandler('odoo.di.update', UpdateDi);
  commandStack.registerHandler('odoo.connections.relayout', Relayout);
  commandStack.registerHandler('odoo.shapes.sameSize', SameSize);
  commandStack.registerHandler('odoo.text.update', UpdateText);
  commandStack.registerHandler('odoo.text.base', UpdateBase);
}
TextStyleCommands.$inject = ['commandStack', 'elementRegistry', 'canvas', 'modeling', 'eventBus'];


// Groups (selected and moved together) and locked elements (no move, resize or delete),
// stored as odoostyle:group / odoostyle:locked on the DI.
function groupOf(el) {
  var t = el && (el.labelTarget || el);
  return t && t.di && t.di.get ? t.di.get('odoostyle:group') : null;
}

function isLocked(el) {
  var t = el && (el.labelTarget || el);
  return !!(t && t.di && t.di.get && t.di.get('odoostyle:locked'));
}

export function groupMembers(elementRegistry, group) {
  return group ? elementRegistry.filter(function(e) {
    return !e.labelTarget && e.di && e.di.get && e.di.get('odoostyle:group') === group;
  }) : [];
}

function GroupSelect(eventBus, selection, elementRegistry) {
  function expand(el, add) {
    var g = groupOf(el);
    if (!g) {
      return false;
    }
    var members = groupMembers(elementRegistry, g);
    var current = add ? selection.get() : [];
    selection.select(current.concat(members.filter(function(m) { return current.indexOf(m) === -1; })));
    return true;
  }
  eventBus.on('element.click', 1600, function(event) {
    var e = event.originalEvent || {};
    if (e.altKey || !groupOf(event.element)) {
      return;
    }
    expand(event.element, e.shiftKey || e.ctrlKey || e.metaKey);
    return false;
  });
  eventBus.on('shape.move.start', 2000, function(event) {
    var shape = event.shape || (event.context && event.context.shape);
    var g = groupOf(shape);
    var oe = event.originalEvent || {};
    if (!g || oe.altKey) {
      return;
    }
    var sel = selection.get();
    var members = groupMembers(elementRegistry, g);
    if (members.some(function(m) { return sel.indexOf(m) === -1; })) {
      selection.select(sel.indexOf(shape) === -1 ? members : sel.concat(members.filter(function(m) {
        return sel.indexOf(m) === -1;
      })));
    }
  });
}
GroupSelect.$inject = ['eventBus', 'selection', 'elementRegistry'];

function LockRules(eventBus) {
  RuleProvider.call(this, eventBus);
}
LockRules.prototype = Object.create(RuleProvider.prototype);
LockRules.prototype.init = function() {
  function anyLocked(list) {
    return (list || []).some(isLocked);
  }
  this.addRule('elements.move', 3000, function(ctx) {
    return anyLocked(ctx.shapes) ? false : undefined;
  });
  this.addRule('shape.resize', 3000, function(ctx) {
    return isLocked(ctx.shape) ? false : undefined;
  });
  this.addRule('elements.delete', 3000, function(ctx) {
    return anyLocked(ctx.elements) ? false : undefined;
  });
  // tasks and call activities may be resized (bpmn-js keeps them at 100 x 80)
  this.addRule('shape.resize', 1500, function(ctx) {
    var shape = ctx.shape;
    if (!isAnyType(shape, ['bpmn:Task', 'bpmn:CallActivity']) &&
        !(isType(shape, 'bpmn:SubProcess') && shape.collapsed)) {
      return undefined;
    }
    var b = ctx.newBounds;
    return !b || (b.width >= 50 && b.height >= 40);
  });
};
LockRules.$inject = ['eventBus'];

// deleting from the context pad / keyboard goes through modeling: filter locked ones
function LockGuard(eventBus) {
  eventBus.on('commandStack.elements.delete.preExecute', 3000, function(event) {
    var ctx = event.context;
    ctx.elements = (ctx.elements || []).filter(function(el) { return !isLocked(el); });
  });
}
LockGuard.$inject = ['eventBus'];

var LOCK_ICON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" ' +
  'stroke-width="2.2" stroke-linecap="round"><rect x="5" y="11" width="14" height="10" rx="2"/>' +
  '<path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';

function LockBadges(eventBus, overlays, elementRegistry) {
  var ids = {};
  function refresh(elements) {
    (elements || elementRegistry.getAll()).forEach(function(el) {
      if (el.labelTarget || !el.di) {
        return;
      }
      var locked = isLocked(el);
      if (locked && !ids[el.id]) {
        var html = document.createElement('div');
        html.className = 'odoo-lock-badge';
        html.innerHTML = LOCK_ICON;
        ids[el.id] = overlays.add(el, 'odoo-lock', { position: { top: -9, left: -9 }, html: html });
      } else if (!locked && ids[el.id]) {
        overlays.remove(ids[el.id]);
        delete ids[el.id];
      }
    });
  }
  eventBus.on('import.done', function() {
    ids = {};
    refresh();
  });
  eventBus.on('elements.changed', function(e) {
    refresh(e.elements);
  });
}
LockBadges.$inject = ['eventBus', 'overlays', 'elementRegistry'];

export var OdooModelerUxModule = {
  __init__: ['odooLabelBoundsFix', 'odooConnectHighlighter', 'odooPaletteProvider', 'odooKeyboardBindings',
    'odooPorts', 'odooPortLayouter', 'odooLineJumps', 'odooPoolMagnet', 'odooTextStyles',
    'odooTextStyleCommands', 'odooGroupSelect', 'odooLockRules', 'odooLockGuard', 'odooLockBadges'],
  odooGroupSelect: ['type', GroupSelect],
  odooLockRules: ['type', LockRules],
  odooLockGuard: ['type', LockGuard],
  odooLockBadges: ['type', LockBadges],
  odooTextStyles: ['type', TextStyles],
  odooTextStyleCommands: ['type', TextStyleCommands],
  odooPoolMagnet: ['type', PoolMagnet],
  odooDock: ['type', DockStore],
  odooLabelBoundsFix: ['type', LabelBoundsFix],
  odooPorts: ['type', Ports],
  odooPortLayouter: ['type', PortLayouter],
  odooLineJumps: ['type', LineJumps],
  odooConnectHighlighter: ['type', ConnectHighlighter],
  odooPaletteProvider: ['type', OdooPaletteProvider],
  odooKeyboardBindings: ['type', OdooKeyboardBindings],
};

export var OdooViewerUxModule = {
  __init__: ['odooLabelBoundsFix', 'odooKeyboardBindings', 'odooLineJumps', 'odooTextStyles'],
  odooTextStyles: ['type', TextStyles],
  odooLabelBoundsFix: ['type', LabelBoundsFix],
  odooLineJumps: ['type', LineJumps],
  odooKeyboardBindings: ['type', OdooKeyboardBindings],
};
