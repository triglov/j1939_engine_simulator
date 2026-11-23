#!/usr/bin/env python3
"""Zapasowy symulator silnika Volvo Penta / J1939 (python-can, SocketCAN). Te same ramki co flow Node-RED.
   pip install python-can      uruchom:  python3 sim.py -c can0 --rpm 1500        (Ctrl+C = stop)
   Opcje: --sweep (700<->3800 rpm, 60 s)  --manual (bez modelu)  --fault (DM1 SPN100 FMI1)  --hours 1234.5
"""
import argparse, json, math, os, time
import can

SA, RATED, IDLE = 0x00, 3800, 700
def cid(prio, pgn): return ((prio & 7) << 26) | ((pgn & 0x3FFFF) << 8) | SA
def clamp(v, lo, hi): return min(hi, max(lo, v))
def r8(v, s, o=0): return clamp(round((v - o) / s), 0, 0xFA)
def r16(v, s, o=0): return clamp(round((v - o) / s), 0, 0xFAFF)
def r32(v, s, o=0): return clamp(round((v - o) / s), 0, 0xFAFFFFFF)
def put16(d, i, r): d[i], d[i + 1] = r & 0xFF, (r >> 8) & 0xFF
def put32(d, i, r):
    for k in range(4): d[i + k] = (r >> (8 * k)) & 0xFF
FF = lambda: bytearray(b'\xff' * 8)

def enc_eec1(s): d = FF(); d[1] = r8(s['demandTq'], 1, -125); d[2] = r8(s['actualTq'], 1, -125); put16(d, 3, r16(s['rpm'], 0.125)); return d
def enc_eec2(s): d = FF(); d[1] = r8(s['pedal'], 0.4); d[2] = r8(s['load'], 1); return d
def enc_lfe(s):  d = FF(); put16(d, 0, r16(s['fuelRate'], 0.05)); d[6] = r8(s['pedal'], 0.4); return d
def enc_eflp1(s): d = FF(); d[3] = r8(s['oilPress'], 4); d[6] = r8(s['coolPress'], 2); d[7] = r8(s['coolLevel'], 0.4); return d
def enc_ic1(s):  d = FF(); d[1] = r8(s['boost'], 2); d[2] = r8(s['imt'], 1, -40); put16(d, 5, r16(s['egt'], 0.03125, -273)); return d
def enc_et1(s):  d = FF(); d[0] = r8(s['coolant'], 1, -40); d[1] = r8(s['fuelTemp'], 1, -40); put16(d, 2, r16(s['oilTemp'], 0.03125, -273)); return d
def enc_amb(s):  d = FF(); d[0] = r8(s['baro'], 0.5); d[5] = r8(s['airIn'], 1, -40); return d
def enc_vep1(s): d = FF(); put16(d, 4, r16(s['battV'], 0.05)); return d
def enc_hours(s): d = FF(); put32(d, 0, r32(s['hours'], 0.05)); put32(d, 4, r32(s['revs'], 1000)); return d
def enc_dm1(s):
    if not s['fault']: return bytearray([0x00, 0xFF, 0, 0, 0, 0, 0xFF, 0xFF])
    spn, fmi, oc = 100, 1, 1
    return bytearray([0x10, 0xFF, spn & 0xFF, (spn >> 8) & 0xFF, (((spn >> 16) & 7) << 5) | fmi, oc, 0xFF, 0xFF])

PGNS = [  # name, prio, pgn, period [s], encoder
    ('EEC1', 3, 61444, 0.020, enc_eec1), ('EEC2', 3, 61443, 0.050, enc_eec2), ('LFE', 6, 65266, 0.100, enc_lfe),
    ('EFL/P1', 6, 65263, 0.500, enc_eflp1), ('IC1', 6, 65270, 0.500, enc_ic1), ('ET1', 6, 65262, 1.0, enc_et1),
    ('AMB', 6, 65269, 1.0, enc_amb), ('VEP1', 6, 65271, 1.0, enc_vep1), ('HOURS', 6, 65253, 1.0, enc_hours),
    ('DM1', 6, 65226, 1.0, enc_dm1)]

def lag(cur, tgt, tau, dt): return cur + (tgt - cur) * (1 - math.exp(-dt / tau))

def step(s, a, dt):
    rpm_t = a.rpm
    if a.sweep:
        s['sweepT'] = (s['sweepT'] + dt) % 60; ph = s['sweepT'] / 30
        rpm_t = IDLE + (RATED - IDLE) * (ph if ph < 1 else 2 - ph)
    if a.engine_off: rpm_t = 0
    elif not a.manual: rpm_t = clamp(rpm_t, IDLE, RATED + 200)
    s['rpm'] = rpm_t if a.manual else lag(s['rpm'], rpm_t, 0.4, dt)
    if s['rpm'] < 1: s['rpm'] = 0
    run, n = s['rpm'] > 0, s['rpm'] / RATED
    if a.manual:
        s.update(load=a.load, pedal=a.load, actualTq=a.load, demandTq=a.load, coolant=a.coolant, fuelTemp=35, oilTemp=90,
                 oilPress=40 if a.fault else 400, coolPress=80, coolLevel=100, boost=80, imt=40, egt=350, fuelRate=12,
                 battV=14.2 if run else 12.6, baro=101, airIn=25)
        if not run: s.update(load=0, pedal=0, actualTq=0, demandTq=0, fuelRate=0)
    else:
        amb = 25
        s['load'] = lag(s['load'], clamp(100 * n * n, 5, 100) if run else 0, 0.5, dt)
        s['pedal'] = clamp((rpm_t - IDLE) / (RATED - IDLE) * 100, 0, 100) if run else 0
        s['actualTq'] = s['load']; s['demandTq'] = clamp(s['load'] + 2, 0, 125) if run else 0
        s['coolant'] = lag(s['coolant'], 80 + 6 * s['load'] / 100 if run else amb, 240 if run else 1800, dt)
        s['oilTemp'] = lag(s['oilTemp'], 85 + 25 * s['load'] / 100 if run else amb, 420 if run else 2400, dt)
        s['fuelTemp'] = lag(s['fuelTemp'], 35 + 15 * s['load'] / 100 if run else amb, 900, dt)
        op = 0 if not run else 40 if a.fault else clamp(180 + 340 * (s['rpm'] - IDLE) / (RATED - IDLE) - 1.5 * (s['oilTemp'] - 85), 120, 600)
        s['oilPress'] = lag(s['oilPress'], op, 0.3, dt)
        s['coolPress'] = clamp(10 + 1.1 * (s['coolant'] - amb), 0, 120) if run else lag(s['coolPress'], 0, 600, dt)
        s['coolLevel'] = 100
        s['boost'] = lag(s['boost'], 220 * (s['load'] / 100) ** 1.5 * n + 2 if run else 0, 1.0, dt)
        s['imt'] = lag(s['imt'], amb + 8 + 0.12 * s['boost'], 20, dt)
        s['egt'] = lag(s['egt'], 180 + 4.2 * s['load'] if run else amb, 8 if run else 120, dt)
        s['fuelRate'] = 1.2 + 60 * (s['load'] / 100) * n if run else 0
        s['battV'] = lag(s['battV'], 14.2 if run else 12.6, 5, dt)
        s['baro'], s['airIn'] = 101, amb
    if run: s['hours'] += dt / 3600; s['revs'] += s['rpm'] * dt / 60

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('-c', '--channel', default='can0'); p.add_argument('-i', '--interface', default='socketcan')
    p.add_argument('--rpm', type=float, default=1500); p.add_argument('--load', type=float, default=40, help='tylko --manual')
    p.add_argument('--coolant', type=float, default=82, help='tylko --manual')
    p.add_argument('--sweep', action='store_true'); p.add_argument('--manual', action='store_true')
    p.add_argument('--fault', action='store_true'); p.add_argument('--engine-off', action='store_true', help='zapłon bez pracy silnika')
    p.add_argument('--hours', type=float, default=None, help='motogodziny startowe (domyślnie z pliku stanu lub 1234.5)')
    p.add_argument('--state', default=os.path.expanduser('~/.vp_sim_hours.json')); p.add_argument('--duration', type=float, default=0)
    a = p.parse_args()
    st = {'hours': 1234.5, 'revs': 1234.5 * 60 * 1500}
    if os.path.exists(a.state):
        try: st.update(json.load(open(a.state)))
        except Exception: pass
    if a.hours is not None: st['hours'] = a.hours
    s = dict(rpm=0, load=0, pedal=0, demandTq=0, actualTq=0, coolant=20, fuelTemp=20, oilTemp=20, oilPress=0, coolPress=0,
             coolLevel=100, boost=0, imt=25, egt=25, fuelRate=0, battV=12.6, baro=101, airIn=25, sweepT=0, fault=a.fault, **st)
    bus = can.Bus(interface=a.interface, channel=a.channel)
    t0 = last = time.monotonic(); nxt = [t0 + 0.005 * i for i in range(len(PGNS))]; nshow = nsave = t0
    print(f'TX na {a.channel}: EEC1 20ms, EEC2 50ms, LFE 100ms, EFL/P1+IC1 500ms, ET1/AMB/VEP1/HOURS/DM1 1s. Ctrl+C = stop')
    try:
        while not a.duration or time.monotonic() - t0 < a.duration:
            now = time.monotonic(); step(s, a, min(now - last, 1)); last = now
            for k, (name, prio, pgn, per, enc) in enumerate(PGNS):
                if now >= nxt[k]:
                    bus.send(can.Message(arbitration_id=cid(prio, pgn), is_extended_id=True, data=enc(s)))
                    nxt[k] += per
                    if nxt[k] <= now: nxt[k] = now + per
            if now >= nshow:
                nshow = now + 1
                print(f"\r{s['rpm']:6.0f} rpm  load {s['load']:3.0f}%  cool {s['coolant']:5.1f}C  oil {s['oilPress']:4.0f}kPa  {s['hours']:.3f} h ", end='', flush=True)
            if now >= nsave:
                nsave = now + 10; json.dump({'hours': s['hours'], 'revs': s['revs']}, open(a.state, 'w'))
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        json.dump({'hours': s['hours'], 'revs': s['revs']}, open(a.state, 'w')); bus.shutdown(); print()

if __name__ == '__main__':
    main()
