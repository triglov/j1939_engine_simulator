// ===== Volvo Penta / J1939 engine simulator core (embedded into the Node-RED function node) =====
// Pure JS, no Node-RED APIs. All frames: 29-bit extended ID, 8 bytes, little endian (Intel).
const SA = 0x00;                       // engine ECU source address
const RATED = 3800, IDLE = 700;        // rpm (typical Volvo Penta D4/D6 range)
const id = (prio, pgn) => (((prio & 7) << 26) | ((pgn & 0x3FFFF) << 8) | SA) >>> 0;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// raw = (phys - offset) / scale, clipped to the J1939 valid range (8-bit: 0..250, 16-bit: 0..64255, 32-bit: 0..4211081215)
const raw8  = (v, s, o = 0) => clamp(Math.round((v - o) / s), 0, 0xFA);
const raw16 = (v, s, o = 0) => clamp(Math.round((v - o) / s), 0, 0xFAFF);
const raw32 = (v, s, o = 0) => clamp(Math.round((v - o) / s), 0, 0xFAFFFFFF);
const ff = () => [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF];
const u16 = (d, i, r) => { d[i] = r & 0xFF; d[i + 1] = (r >>> 8) & 0xFF; };
const u32 = (d, i, r) => { d[i] = r & 0xFF; d[i + 1] = (r >>> 8) & 0xFF; d[i + 2] = (r >>> 16) & 0xFF; d[i + 3] = (r >>> 24) & 0xFF; };

// name, prio, pgn, period ms, encoder(state) -> 8 bytes   (byte index below is 0-based; J1939 docs are 1-based)
const PGNS = [
  { name: 'EEC1', prio: 3, pgn: 61444, period: 20, enc: s => { const d = ff();
      d[1] = raw8(s.demandTq, 1, -125);          // SPN 512 driver's demand torque, byte 2, 1 %/bit, -125
      d[2] = raw8(s.actualTq, 1, -125);          // SPN 513 actual engine torque,  byte 3, 1 %/bit, -125
      u16(d, 3, raw16(s.rpm, 0.125));            // SPN 190 engine speed, bytes 4-5, 0.125 rpm/bit
      return d; } },
  { name: 'EEC2', prio: 3, pgn: 61443, period: 50, enc: s => { const d = ff();
      d[1] = raw8(s.pedal, 0.4);                 // SPN 91 accel pedal position 1, byte 2, 0.4 %/bit
      d[2] = raw8(s.load, 1);                    // SPN 92 percent load at current speed, byte 3, 1 %/bit
      return d; } },
  { name: 'LFE', prio: 6, pgn: 65266, period: 100, enc: s => { const d = ff();
      u16(d, 0, raw16(s.fuelRate, 0.05));        // SPN 183 fuel rate, bytes 1-2, 0.05 L/h per bit
      d[6] = raw8(s.pedal, 0.4);                 // SPN 51 throttle position, byte 7, 0.4 %/bit
      return d; } },
  { name: 'EFL_P1', prio: 6, pgn: 65263, period: 500, enc: s => { const d = ff();
      d[3] = raw8(s.oilPress, 4);                // SPN 100 oil pressure, byte 4, 4 kPa/bit
      d[6] = raw8(s.coolPress, 2);               // SPN 109 coolant pressure, byte 7, 2 kPa/bit
      d[7] = raw8(s.coolLevel, 0.4);             // SPN 111 coolant level, byte 8, 0.4 %/bit
      return d; } },
  { name: 'IC1', prio: 6, pgn: 65270, period: 500, enc: s => { const d = ff();
      d[1] = raw8(s.boost, 2);                   // SPN 102 intake manifold 1 (boost) pressure, byte 2, 2 kPa/bit
      d[2] = raw8(s.imt, 1, -40);                // SPN 105 intake manifold 1 temp, byte 3, 1 C/bit, -40
      u16(d, 5, raw16(s.egt, 0.03125, -273));    // SPN 173 exhaust gas temp, bytes 6-7, 0.03125 C/bit, -273
      return d; } },
  { name: 'ET1', prio: 6, pgn: 65262, period: 1000, enc: s => { const d = ff();
      d[0] = raw8(s.coolant, 1, -40);            // SPN 110 coolant temp, byte 1, 1 C/bit, -40
      d[1] = raw8(s.fuelTemp, 1, -40);           // SPN 174 fuel temp, byte 2, 1 C/bit, -40
      u16(d, 2, raw16(s.oilTemp, 0.03125, -273));// SPN 175 oil temp 1, bytes 3-4, 0.03125 C/bit, -273
      return d; } },
  { name: 'AMB', prio: 6, pgn: 65269, period: 1000, enc: s => { const d = ff();
      d[0] = raw8(s.baro, 0.5);                  // SPN 108 barometric pressure, byte 1, 0.5 kPa/bit
      d[5] = raw8(s.airIn, 1, -40);              // SPN 172 engine air inlet temp, byte 6, 1 C/bit, -40
      return d; } },
  { name: 'VEP1', prio: 6, pgn: 65271, period: 1000, enc: s => { const d = ff();
      u16(d, 4, raw16(s.battV, 0.05));           // SPN 168 battery potential, bytes 5-6, 0.05 V/bit
      return d; } },
  { name: 'HOURS', prio: 6, pgn: 65253, period: 1000, enc: s => { const d = ff();
      u32(d, 0, raw32(s.hours, 0.05));           // SPN 247 total engine hours, bytes 1-4, 0.05 h/bit
      u32(d, 4, raw32(s.revs, 1000));            // SPN 249 total revolutions, bytes 5-8, 1000 r/bit
      return d; } },
  { name: 'DM1', prio: 6, pgn: 65226, period: 1000, enc: s => {
      if (!s.fault) return [0x00, 0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF];   // no active DTC, lamps off
      const spn = 100, fmi = 1, oc = 1;            // SPN 100 FMI 1 = oil pressure below normal (most severe)
      return [0x10, 0xFF,                          // byte1: red stop lamp ON (bits 5-6 = 01); byte2: flash n/a
              spn & 0xFF, (spn >>> 8) & 0xFF,      // DTC bytes 3-4: SPN bits 1-16
              (((spn >>> 16) & 0x07) << 5) | (fmi & 0x1F), // byte5: SPN bits 17-19 (bits 6-8), FMI (bits 1-5)
              oc & 0x7F,                           // byte6: CM=0 (bit 8), occurrence count (bits 1-7)
              0xFF, 0xFF]; } },
];
PGNS.forEach(p => { p.id = id(p.prio, p.pgn); });

function defaultState() {
  return {
    tx: true, engineOn: false, sweep: false, realistic: true, fault: false,
    // manual inputs (sliders)
    in: { rpm: 1500, load: 40, pedal: 40, coolant: 80, fuelTemp: 35, oilTemp: 90, oilPress: 400, coolPress: 80,
          coolLevel: 100, boost: 80, imt: 40, egt: 350, fuelRate: 12, battV: 14.2, baro: 101, airIn: 25 },
    // simulated (sent) values
    rpm: 0, load: 0, pedal: 0, demandTq: 0, actualTq: 0, coolant: 20, fuelTemp: 20, oilTemp: 20, oilPress: 0,
    coolPress: 0, coolLevel: 100, boost: 0, imt: 25, egt: 25, fuelRate: 0, battV: 12.6, baro: 101, airIn: 25,
    hours: 1234.5, revs: 1234.5 * 60 * 1500, sweepT: 0,
  };
}

const lag = (cur, target, tau, dt) => cur + (target - cur) * (1 - Math.exp(-dt / tau));

// advance model by dt seconds
function step(s, dt) {
  const I = s.in;
  // --- engine speed target
  let rpmT = I.rpm;
  if (s.sweep) {                      // triangle IDLE -> RATED -> IDLE, 60 s period
    s.sweepT = (s.sweepT + dt) % 60;
    const ph = s.sweepT / 30;
    rpmT = IDLE + (RATED - IDLE) * (ph < 1 ? ph : 2 - ph);
  }
  if (!s.engineOn) rpmT = 0;
  else if (s.realistic) rpmT = clamp(rpmT, IDLE, RATED + 200);   // a running engine can't go below idle
  s.rpm = s.realistic ? lag(s.rpm, rpmT, 0.4, dt) : rpmT;
  if (s.rpm < 1) s.rpm = 0;
  const run = s.rpm > 0, n = s.rpm / RATED;

  if (s.realistic) {
    const amb = I.airIn;
    const loadT = run ? clamp(100 * n * n, 5, 100) : 0;                // propeller law: torque ~ rpm^2
    s.load = lag(s.load, loadT, 0.5, dt);
    s.pedal = run ? clamp((rpmT - IDLE) / (RATED - IDLE) * 100, 0, 100) : 0;
    s.actualTq = s.load; s.demandTq = run ? clamp(s.load + 2, 0, 125) : 0;
    s.coolant = lag(s.coolant, run ? 80 + 6 * s.load / 100 : amb, run ? 240 : 1800, dt); // thermostat ~80 C
    s.oilTemp = lag(s.oilTemp, run ? 85 + 25 * s.load / 100 : amb, run ? 420 : 2400, dt);
    s.fuelTemp = lag(s.fuelTemp, run ? 35 + 15 * s.load / 100 : amb, 900, dt);
    const opT = !run ? 0 : s.fault ? 40 : clamp(180 + 340 * (s.rpm - IDLE) / (RATED - IDLE) - 1.5 * (s.oilTemp - 85), 120, 600);
    s.oilPress = lag(s.oilPress, opT, 0.3, dt);
    s.coolPress = run ? clamp(10 + 1.1 * (s.coolant - amb), 0, 120) : lag(s.coolPress, 0, 600, dt);
    s.coolLevel = I.coolLevel;
    s.boost = lag(s.boost, run ? 220 * Math.pow(s.load / 100, 1.5) * n + 2 : 0, 1.0, dt);  // kPa (gauge)
    s.imt = lag(s.imt, amb + 8 + 0.12 * s.boost, 20, dt);
    s.egt = lag(s.egt, run ? 180 + 4.2 * s.load : amb, run ? 8 : 120, dt);
    s.fuelRate = run ? 1.2 + 60 * (s.load / 100) * n : 0;                  // L/h, ~60 L/h at rated (D4-300 class)
    s.battV = lag(s.battV, run ? 14.2 : 12.6, 5, dt);
    s.baro = I.baro; s.airIn = amb;
  } else {
    Object.assign(s, { load: I.load, pedal: I.pedal, actualTq: I.load, demandTq: I.load, coolant: I.coolant,
      fuelTemp: I.fuelTemp, oilTemp: I.oilTemp, oilPress: s.fault ? 40 : I.oilPress, coolPress: I.coolPress,
      coolLevel: I.coolLevel, boost: I.boost, imt: I.imt, egt: I.egt, fuelRate: I.fuelRate, battV: I.battV,
      baro: I.baro, airIn: I.airIn });
    if (!run) { s.load = s.pedal = s.actualTq = s.demandTq = s.fuelRate = 0; }
  }
  if (run) { s.hours += dt / 3600; s.revs += s.rpm * dt / 60; }   // hours only while rpm > 0
}

function frame(p, s) {
  return { canfd: false, ext: true, rtr: false, canid: p.id, dlc: 8, data: p.enc(s) };
}
// ===== end of core =====
