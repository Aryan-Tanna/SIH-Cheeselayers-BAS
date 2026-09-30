import { HardDrive, Camera, Radio, Globe, ArrowRight, ShieldCheck, CheckCircle2 } from 'lucide-react';

const steps = [
  {
    icon: HardDrive,
    title: 'On-Board Hash Ledger',
    desc: 'Each step and alert is written to a hash-chained JSONL log. Monotonic timestamps ensure strict chronological verification.',
  },
  {
    icon: Camera,
    title: 'Attested JPEG Snapshots',
    desc: 'One keyframe snapshot is captured per step completion and alert. The SHA-256 is sealed directly into the ledger on board.',
  },
  {
    icon: Radio,
    title: 'Store & Forward Engine',
    desc: 'Everything is cached locally until ground handshake. After signal loss, telemetry resumes from the exact missing block.',
  },
  {
    icon: Globe,
    title: 'Earth Mission Control',
    desc: 'Ground station verifies every block against the cryptographic hash chain. Any altered payload byte flags "LOG TAMPERED".',
  },
];

export default function EarthDownlink() {
  return (
    <section id="downlink" className="py-24 bg-white border-t border-slate-100">
      <div className="max-w-7xl mx-auto px-6">
        
        {/* Section Header */}
        <div className="text-center mb-16">
          <div className="inline-block px-3.5 py-1 bg-blue-50 text-primary text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-blue-100">
            Bandwidth Efficiency
          </div>
          <h2 className="text-4xl font-extrabold text-slate-900 mb-4 sm:text-5xl">
            Transmitting to Earth &mdash; Without Video
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Satellite downlink budgets cannot support continuous raw video streaming. Abhay transmits semantic state deltas and attested milestone frames — slashing bandwidth by 86.5%.
          </p>
        </div>

        {/* 4 Pipeline Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-16">
          {steps.map(({ icon: Icon, title, desc }) => (
            <div
              key={title}
              className="bg-slate-50 border border-slate-200 rounded-3xl p-6 hover:border-blue-300 hover:shadow-md transition-all flex flex-col justify-between"
            >
              <div>
                <div className="p-3.5 bg-white border border-slate-200 text-primary rounded-2xl w-fit mb-5 shadow-sm">
                  <Icon className="w-6 h-6" />
                </div>
                <h3 className="font-bold text-slate-900 text-base mb-2">{title}</h3>
                <p className="text-xs text-slate-600 leading-relaxed">{desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Bandwidth Comparison Box */}
        <div className="bg-gradient-to-br from-slate-50 via-white to-blue-50/50 border border-blue-200/80 rounded-3xl p-8 sm:p-12 shadow-sm">
          <div className="text-center mb-8">
            <span className="text-xs font-bold uppercase tracking-widest text-primary bg-blue-100/60 px-3 py-1 rounded-full border border-blue-200">
              Measured Benchmark · Dataset 12 Clip (32.5s, 12 Steps)
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 items-center text-center">
            
            {/* Old Method */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
              <div className="text-4xl sm:text-5xl font-black text-rose-500 mb-2">3.6 MB</div>
              <div className="text-sm font-bold text-slate-800">Raw H.264 Video Stream</div>
              <div className="text-xs text-slate-500 mt-1">Exceeds standard S-band telemetry passes</div>
            </div>

            {/* Savings Arrow */}
            <div className="flex flex-col items-center justify-center">
              <div className="text-primary font-black text-lg sm:text-xl flex items-center gap-2 mb-1">
                <span>86.5% Bandwidth Saved</span>
                <ArrowRight className="w-5 h-5 text-primary" />
              </div>
              <span className="text-xs font-medium text-slate-500 bg-white px-3 py-1 rounded-full border border-slate-200 shadow-xs">
                7.4&times; Smaller Payload
              </span>
            </div>

            {/* Abhay Method */}
            <div className="bg-white rounded-2xl p-6 border-2 border-emerald-500 shadow-md">
              <div className="text-4xl sm:text-5xl font-black text-emerald-600 mb-2">486 KB</div>
              <div className="text-sm font-bold text-slate-800">Hash-Chained Log + 12 JPEGs</div>
              <div className="text-xs text-slate-500 mt-1 flex items-center justify-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                <span>100% Cryptographically Attested</span>
              </div>
            </div>

          </div>
        </div>

      </div>
    </section>
  );
}
