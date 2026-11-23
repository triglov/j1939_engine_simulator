#!/usr/bin/env python3
"""Generates ../flow.json from engine.js (single source of truth for the encoder/model)."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
core = open(os.path.join(D, 'engine.js')).read()

INIT = core + r"""
// ===== Node-RED glue (On Start) =====
// Engine hours are kept in flow context. Store 'file' = persistent (see README), falls back to memory.
const STORE = (env.get('VP_STORE') || 'file');
const s = defaultState();
let saved;
try { saved = flow.get('vp_engine', STORE); } catch (e) { saved = undefined; }
if (saved && typeof saved.hours === 'number') { s.hours = saved.hours; s.revs = saved.revs || s.revs; }
else { const h0 = Number(env.get('VP_START_HOURS') || 1234.5); if (!isNaN(h0) && h0 >= 0) s.hours = h0; }
context.set('s', s);
const save = () => { try { flow.set('vp_engine', { hours: s.hours, revs: s.revs }, STORE); } catch (e) { flow.set('vp_engine', { hours: s.hours, revs: s.revs }); } };
context.set('save', save);

const UI_KEYS = ['rpm','load','pedal','coolant','fuelTemp','oilTemp','oilPress','coolPress','coolLevel','boost','imt','egt','fuelRate','battV','baro','airIn'];
const NOUT = 4;
const out = (i, m) => { const a = new Array(NOUT).fill(null); a[i] = m; node.send(a); };
// push current settings to the dashboard widgets once at start (sliders/switches show the real state)
const pushInputs = () => {
  const msgs = [];
  for (const k of UI_KEYS) msgs.push({ topic: k, payload: s.in[k] });
  for (const k of ['tx','engineOn','sweep','realistic','fault']) msgs.push({ topic: k, payload: s[k] });
  msgs.push({ topic: 'setHours', payload: +s.hours.toFixed(2) });
  const a = new Array(NOUT).fill(null); a[3] = msgs; node.send(a);
};
setTimeout(pushInputs, 1500);
context.set('pushInputs', pushInputs);

const now0 = Date.now();
PGNS.forEach((p, i) => { p.next = now0 + 5 * i; });     // small stagger
let last = now0, nextUi = now0, nextSave = now0 + 10000, sent = 0;
const timer = setInterval(() => {
  const now = Date.now();
  step(s, Math.min((now - last) / 1000, 1)); last = now;
  if (s.tx) {
    for (const p of PGNS) {
      if (now >= p.next) {
        out(0, { topic: p.name, payload: frame(p, s) }); sent++;
        p.next += p.period; if (p.next <= now) p.next = now + p.period;   // no burst after a stall
      }
    }
  }
  if (now >= nextUi) {
    nextUi = now + 500;
    const r = (v, d) => +v.toFixed(d);
    const rows = [
      ['EEC1', 61444, 190, 'Obroty', r(s.rpm, 0), 'rpm'],
      ['EEC1', 61444, 512, 'Moment zadany', r(s.demandTq, 0), '%'],
      ['EEC1', 61444, 513, 'Moment rzeczywisty', r(s.actualTq, 0), '%'],
      ['EEC2', 61443, 91, 'Pedał / manetka', r(s.pedal, 1), '%'],
      ['EEC2', 61443, 92, 'Obciążenie', r(s.load, 0), '%'],
      ['ET1', 65262, 110, 'Temp. płynu chł.', r(s.coolant, 0), '°C'],
      ['ET1', 65262, 174, 'Temp. paliwa', r(s.fuelTemp, 0), '°C'],
      ['ET1', 65262, 175, 'Temp. oleju', r(s.oilTemp, 1), '°C'],
      ['EFL/P1', 65263, 100, 'Ciśn. oleju', r(s.oilPress, 0), 'kPa'],
      ['EFL/P1', 65263, 109, 'Ciśn. płynu chł.', r(s.coolPress, 0), 'kPa'],
      ['EFL/P1', 65263, 111, 'Poziom płynu chł.', r(s.coolLevel, 0), '%'],
      ['IC1', 65270, 102, 'Doładowanie', r(s.boost, 0), 'kPa'],
      ['IC1', 65270, 105, 'Temp. kolektora dol.', r(s.imt, 0), '°C'],
      ['IC1', 65270, 173, 'Temp. spalin', r(s.egt, 0), '°C'],
      ['LFE', 65266, 183, 'Zużycie paliwa', r(s.fuelRate, 2), 'l/h'],
      ['VEP1', 65271, 168, 'Napięcie akumulatora', r(s.battV, 2), 'V'],
      ['AMB', 65269, 108, 'Ciśn. barometryczne', r(s.baro, 1), 'kPa'],
      ['AMB', 65269, 172, 'Temp. powietrza dolot.', r(s.airIn, 0), '°C'],
      ['HOURS', 65253, 247, 'Motogodziny', r(s.hours, 2), 'h'],
      ['DM1', 65226, 100, 'Aktywny błąd', s.fault ? 'SPN 100 FMI 1' : 'brak', ''],
    ];
    const a = new Array(NOUT).fill(null);
    a[1] = { payload: rows, topic: 'table' };
    a[2] = [{ topic: 'rpm', payload: Math.round(s.rpm) }, { topic: 'coolant', payload: Math.round(s.coolant) },
            { topic: 'oilPress', payload: Math.round(s.oilPress) }, { topic: 'hours', payload: s.hours.toFixed(2) + ' h' }];
    node.send(a);
    node.status({ fill: s.tx ? (s.rpm > 0 ? 'green' : 'yellow') : 'grey', shape: 'dot',
      text: (s.tx ? 'TX ' : 'TX off ') + Math.round(s.rpm) + ' rpm, ' + s.hours.toFixed(2) + ' h, ramek: ' + sent });
  }
  if (now >= nextSave) { nextSave = now + 10000; save(); }
}, 10);
context.set('timer', timer);
"""

MAIN = r"""// Inputs from the dashboard: msg.topic = parameter name, msg.payload = value
const s = context.get('s');
if (!s) return null;
const t = msg.topic, v = msg.payload;
if (['tx', 'engineOn', 'sweep', 'realistic', 'fault'].includes(t)) s[t] = (v === true || v === 'true' || v === 1);
else if (t === 'setHours') { const h = Number(v); if (!isNaN(h) && h >= 0) { s.hours = h; context.get('save')(); } }
else if (t in s.in) { const x = Number(v); if (!isNaN(x)) s.in[t] = x; }
else if (t === 'refresh') context.get('pushInputs')();
return null;
"""

FINAL = r"""clearInterval(context.get('timer'));
const save = context.get('save'); if (save) save();
"""

TABLE_TPL = """<template>
  <table class="vp-tab" v-if="Array.isArray(msg.payload)">
    <tr><th>PGN</th><th>SPN</th><th>Parametr</th><th>Wartość</th><th></th></tr>
    <tr v-for="r in msg.payload" :key="String(r[1]) + '-' + r[2]">
      <td>{{ r[0] }} ({{ r[1] }})</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td class="v"><b>{{ r[4] }}</b></td><td>{{ r[5] }}</td>
    </tr>
  </table>
  <div v-else>czekam na dane…</div>
</template>
<style>
.vp-tab { width: 100%; border-collapse: collapse; font-size: 14px; }
.vp-tab th, .vp-tab td { padding: 3px 6px; border-bottom: 1px solid #ddd; text-align: left; }
.vp-tab td.v { text-align: right; }
</style>"""

nodes = []
def add(n): nodes.append(n); return n
TAB = 'f0a1000000000001'
uid = iter(range(1, 10000))
def nid(): return 'f0a1%012x' % (0x100 + next(uid))

add({"id": TAB, "type": "tab", "label": "Volvo Penta J1939 sim", "disabled": False,
     "info": "Symulator silnika J1939 (EEC1/EEC2/ET1/EFL-P1/IC1/LFE/VEP1/AMB/HOURS/DM1) na SocketCAN.",
     "env": [{"name": "VP_CAN_IF", "value": "$env(\"CAN_IF\") ? $env(\"CAN_IF\") : \"can0\"", "type": "jsonata"}]})
CANCFG = add({"id": nid(), "type": "socketcan-config", "z": TAB, "interface": "${VP_CAN_IF}"})
UIBASE = add({"id": nid(), "type": "ui-base", "name": "Symulator J1939", "path": "/dashboard", "appIcon": "",
     "includeClientData": True, "acceptsClientConfig": ["ui-notification", "ui-control"], "showPathInSidebar": False,
     "headerContent": "page", "navigationStyle": "default", "titleBarStyle": "default",
     "showReconnectNotification": True, "notificationDisplayTime": 1, "showDisconnectNotification": True, "allowInstall": False})
THEME = add({"id": nid(), "type": "ui-theme", "name": "Default",
     "colors": {"surface": "#0b3d5c", "primary": "#0d74ce", "bgPage": "#eef2f6", "groupBg": "#ffffff", "groupOutline": "#cccccc"},
     "sizes": {"density": "default", "pagePadding": "12px", "groupGap": "12px", "groupBorderRadius": "4px", "widgetGap": "12px"}})
PAGE = add({"id": nid(), "type": "ui-page", "name": "Silnik", "ui": UIBASE["id"], "path": "/engine", "icon": "engine",
     "layout": "grid", "theme": THEME["id"], "breakpoints": [{"name": "Default", "px": 0, "cols": 3}, {"name": "Tablet", "px": 576, "cols": 6},
     {"name": "Small Desktop", "px": 768, "cols": 9}, {"name": "Desktop", "px": 1024, "cols": 12}], "order": 1,
     "className": "", "visible": "true", "disabled": "false"})
def group(name, order, width=3):
    return add({"id": nid(), "type": "ui-group", "name": name, "page": PAGE["id"], "width": str(width), "height": "1",
                "order": order, "showTitle": True, "className": "", "visible": "true", "disabled": "false", "groupType": "default"})
G_CTRL = group("Sterowanie", 1, 4)
G_LIVE = group("Podgląd", 2)
G_TAB = group("Wysyłane wartości", 3, 6)
G_MAN = group("Ręczne wartości (tryb ręczny)", 4, 6)

SIM = nid()
widgets = []   # (node, topic) — topic used to route init values back
def switch(label, topic, order, g=G_CTRL):
    n = add({"id": nid(), "type": "ui-switch", "z": TAB, "name": label, "label": label, "group": g["id"], "order": order,
             "width": 0, "height": 0, "passthru": False, "decouple": "false", "topic": topic, "topicType": "str", "style": "",
             "className": "", "layout": "row-spread", "clickableArea": "switch", "onvalue": "true", "onvalueType": "bool",
             "onicon": "", "oncolor": "", "offvalue": "false", "offvalueType": "bool", "officon": "", "offcolor": "",
             "x": 0, "y": 0, "wires": [[SIM]]})
    widgets.append((n, topic)); return n
def slider(label, topic, mn, mx, step, order, g=G_MAN):
    n = add({"id": nid(), "type": "ui-slider", "z": TAB, "group": g["id"], "name": label, "label": label, "tooltip": "",
             "order": order, "width": 0, "height": 0, "passthru": False, "outs": "end", "topic": topic, "topicType": "str",
             "thumbLabel": "always", "showTicks": "false", "min": mn, "max": mx, "step": step, "className": "",
             "iconPrepend": "", "iconAppend": "", "color": "", "colorTrack": "", "colorThumb": "", "showTextField": True,
             "x": 0, "y": 0, "wires": [[SIM]]})
    widgets.append((n, topic)); return n

switch("Nadawanie na CAN (zapłon)", "tx", 1)
switch("Silnik pracuje", "engineOn", 2)
switch("Tryb realistyczny (z RPM/obciążenia)", "realistic", 3)
switch("Auto sweep RPM (700↔3800, 60 s)", "sweep", 4)
switch("Wstrzyknij błąd DM1: SPN 100 FMI 1", "fault", 5)
slider("Obroty [rpm]", "rpm", 0, 4000, 10, 6, G_CTRL)
n = add({"id": nid(), "type": "ui-number-input", "z": TAB, "group": G_CTRL["id"], "name": "Ustaw motogodziny",
         "label": "Ustaw motogodziny [h]", "order": 7, "width": 0, "height": 0, "topic": "setHours", "topicType": "str",
         "min": 0, "max": 100000, "step": 0.1, "tooltip": "", "passthru": False, "sendOnDelay": False, "sendOnBlur": True,
         "sendOnEnter": True, "className": "", "clearable": False, "icon": "", "iconPosition": "left",
         "iconInnerPosition": "inside", "spinner": "default", "x": 0, "y": 0, "wires": [[SIM]]})
widgets.append((n, "setHours"))
man = [("Obciążenie [%] (SPN 92/513)", "load", 0, 125, 1), ("Pedał/manetka [%] (SPN 91)", "pedal", 0, 100, 1),
       ("Temp. płynu chł. [°C] (SPN 110)", "coolant", -40, 130, 1), ("Temp. paliwa [°C] (SPN 174)", "fuelTemp", -40, 100, 1),
       ("Temp. oleju [°C] (SPN 175)", "oilTemp", -40, 150, 1), ("Ciśn. oleju [kPa] (SPN 100)", "oilPress", 0, 1000, 4),
       ("Ciśn. płynu chł. [kPa] (SPN 109)", "coolPress", 0, 300, 2), ("Poziom płynu chł. [%] (SPN 111)", "coolLevel", 0, 100, 1),
       ("Doładowanie [kPa] (SPN 102)", "boost", 0, 400, 2), ("Temp. kolektora [°C] (SPN 105)", "imt", -40, 120, 1),
       ("Temp. spalin [°C] (SPN 173)", "egt", 0, 800, 5), ("Zużycie paliwa [l/h] (SPN 183)", "fuelRate", 0, 120, 0.5),
       ("Akumulator [V] (SPN 168)", "battV", 8, 32, 0.1), ("Ciśn. barometryczne [kPa] (SPN 108)", "baro", 80, 110, 0.5),
       ("Temp. powietrza dolot. [°C] (SPN 172)", "airIn", -20, 60, 1)]
for i, (l, t, a, b, st) in enumerate(man):
    slider(l, t, a, b, st, i + 1)

def gauge(title, units, mn, mx, segs, order):
    return add({"id": nid(), "type": "ui-gauge", "z": TAB, "name": title, "group": G_LIVE["id"], "order": order, "width": 3,
                "height": 3, "gtype": "gauge-half", "gstyle": "needle", "title": title, "alwaysShowTitle": False,
                "floatingTitlePosition": "top-left", "units": units, "icon": "", "prefix": "", "suffix": "",
                "segments": [{"from": f, "color": c} for f, c in segs], "min": mn, "max": mx, "sizeThickness": 16,
                "sizeGap": 4, "sizeKeyThickness": 8, "styleRounded": True, "styleGlow": False, "className": "",
                "value": "payload", "valueType": "msg", "x": 0, "y": 0, "wires": []})
g_rpm = gauge("Obroty", "rpm", 0, 4000, [(0, "#5cd65c"), (3600, "#ffc800"), (3900, "#ea5353")], 1)
g_cool = gauge("Płyn chłodzący", "°C", 0, 120, [(0, "#5cd65c"), (95, "#ffc800"), (105, "#ea5353")], 2)
g_oil = gauge("Ciśnienie oleju", "kPa", 0, 700, [(0, "#ea5353"), (100, "#ffc800"), (150, "#5cd65c")], 3)
t_hours = add({"id": nid(), "type": "ui-text", "z": TAB, "group": G_LIVE["id"], "order": 4, "width": 0, "height": 0,
               "name": "Motogodziny", "label": "Motogodziny (HOURS, SPN 247)", "format": "{{msg.payload}}", "layout": "row-spread",
               "style": False, "font": "", "fontSize": 16, "color": "#717171", "wrapText": False, "className": "",
               "value": "payload", "valueType": "msg", "x": 0, "y": 0, "wires": []})
tpl = add({"id": nid(), "type": "ui-template", "z": TAB, "group": G_TAB["id"], "page": "", "ui": "", "name": "Tabela wartości",
           "order": 1, "width": 0, "height": 0, "head": "", "format": TABLE_TPL, "storeOutMessages": True, "passthru": False,
           "resendOnRefresh": True, "templateScope": "local", "className": "", "x": 0, "y": 0, "wires": [[]]})

LIVE_SW = nid(); INIT_SW = nid(); CANOUT = nid(); DBG = nid()
add({"id": SIM, "type": "function", "z": TAB, "name": "Silnik J1939 (model + harmonogram)", "func": MAIN, "outputs": 4,
     "timeout": 0, "noerr": 0, "initialize": INIT, "finalize": FINAL, "libs": [], "x": 560, "y": 300,
     "outputLabels": ["ramki CAN", "tabela", "gauge/tekst", "init widgetów"],
     "wires": [[CANOUT, DBG], [tpl["id"]], [LIVE_SW], [INIT_SW]]})
add({"id": CANOUT, "type": "socketcan-in", "z": TAB, "name": "CAN TX (socketcan-in)", "config": CANCFG["id"], "x": 900, "y": 260, "wires": []})
add({"id": DBG, "type": "debug", "z": TAB, "name": "podgląd ramek", "active": False, "tosidebar": True, "console": False,
     "tostatus": False, "complete": "payload", "targetType": "msg", "statusVal": "", "statusType": "auto", "x": 900, "y": 300, "wires": []})
live = [("rpm", g_rpm), ("coolant", g_cool), ("oilPress", g_oil), ("hours", t_hours)]
add({"id": LIVE_SW, "type": "switch", "z": TAB, "name": "po topic", "property": "topic", "propertyType": "msg",
     "rules": [{"t": "eq", "v": t, "vt": "str"} for t, _ in live], "checkall": "false", "repair": False,
     "outputs": len(live), "x": 900, "y": 360, "wires": [[w["id"]] for _, w in live]})
add({"id": INIT_SW, "type": "switch", "z": TAB, "name": "init widgetów po topic", "property": "topic", "propertyType": "msg",
     "rules": [{"t": "eq", "v": t, "vt": "str"} for _, t in widgets], "checkall": "false", "repair": False,
     "outputs": len(widgets), "x": 300, "y": 520, "wires": [[w["id"]] for w, _ in widgets]})
# refresh button: re-push current state to widgets (after browser reload)
add({"id": nid(), "type": "inject", "z": TAB, "name": "odśwież widgety", "props": [{"p": "topic", "vt": "str"}],
     "repeat": "", "crontab": "", "once": False, "onceDelay": 0.1, "topic": "refresh", "x": 300, "y": 300, "wires": [[SIM]]})
add({"id": nid(), "type": "comment", "z": TAB, "name": "Interfejs CAN = zmienna środowiskowa CAN_IF (domyślnie can0); VP_START_HOURS = motogodziny startowe",
     "info": "CAN_IF ustawiasz w docker-compose (.env) albo przed startem: CAN_IF=vcan0 node-red. Można też nadpisać VP_CAN_IF we właściwościach zakładki (Edit flow → Environment).", "x": 320, "y": 80, "wires": []})

# layout positions for widgets
y = 120
for w, _ in widgets:
    w["x"], w["y"] = 300, y; y += 40
for i, (_, w) in enumerate(live):
    w["x"], w["y"] = 1150, 340 + 40 * i
tpl["x"], tpl["y"] = 900, 420
for n in nodes:
    if n["type"] in ("ui-switch", "ui-slider", "ui-number-input"):
        n["x"], n["y"] = n["x"], n["y"]
json.dump(nodes, open(os.path.join(D, '..', 'flow.json'), 'w'), ensure_ascii=False, indent=1)
print('flow.json:', len(nodes), 'nodes')
