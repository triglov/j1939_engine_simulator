const fs=require("fs"),vm=require("vm");const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+"/engine.js","utf8")+";this.X={PGNS,defaultState,step,frame};",ctx);
const {PGNS,defaultState,step,frame}=ctx.X; const hex=a=>a.map(b=>b.toString(16).padStart(2,"0").toUpperCase()).join(" ");
const s=defaultState(); s.realistic=false; s.engineOn=true; s.in.rpm=1500; s.in.coolant=82; s.hours=1234.5; s.revs=0; step(s,0.02);
const out={};
for(const p of PGNS){const f=frame(p,s); out[p.name]={id:f.canid.toString(16).toUpperCase().padStart(8,'0'),data:f.data}; console.log(p.name.padEnd(7),out[p.name].id,hex(f.data));}
const e=out.EEC1.data; console.assert(out.EEC1.id==='0CF00400'&&e[3]===0xE0&&e[4]===0x2E,'EEC1 1500rpm');
console.assert(out.HOURS.id==='18FEE500'&&out.ET1.id==='18FEEE00'&&out.ET1.data[0]===122,'ids/coolant');
s.fault=true; console.log('DM1 fault', hex(frame(PGNS.find(p=>p.name==='DM1'),s).data));
// realistic 15 min run
const r=defaultState(); r.engineOn=true; r.in.rpm=3000; for(let t=0;t<900;t+=0.02) step(r,0.02);
console.log('realistic 15min @3000:', JSON.stringify(Object.fromEntries(['rpm','load','coolant','oilTemp','oilPress','boost','egt','fuelRate','battV','hours'].map(k=>[k,+r[k].toFixed(2)]))));
fs.writeFileSync('/tmp/frames.json',JSON.stringify(out));
