import { Package, RotateCw, CheckCircle2, ShieldAlert, AlertOctagon, Info, Mic } from 'lucide-react';

const experimentSteps = [
  { step: 1, label: 'Open specimen container', detail: 'Hatch release detected', color: 'bg-primary' },
  { step: 2, label: 'Extract red module', detail: 'Single module constraint active', color: 'bg-rose-600' },
  { step: 3, label: 'Unscrew cap (red)', detail: 'Lid separation confirmed', color: 'bg-rose-600' },
  { step: 4, label: 'Stow cap on rig floor', detail: 'Cap in designated zone', color: 'bg-rose-600' },
  { step: 5, label: 'Screw cap back securely', detail: 'Hermetic seal verified', color: 'bg-rose-600' },
  { step: 6, label: 'Return red module to slot', detail: 'Slot occupancy confirmed', color: 'bg-rose-600' },
  { step: 7, label: 'Extract yellow module', detail: 'Red confirmed returned', color: 'bg-amber-600' },
  { step: 8, label: 'Unscrew cap (yellow)', detail: 'Lid separation confirmed', color: 'bg-amber-600' },
  { step: 9, label: 'Stow cap on rig floor', detail: 'Cap in designated zone', color: 'bg-amber-600' },
  { step: 10, label: 'Screw cap back securely', detail: 'Hermetic seal verified', color: 'bg-amber-600' },
  { step: 11, label: 'Return yellow module', detail: 'Both modules returned', color: 'bg-amber-600' },
  { step: 12, label: 'Seal specimen container', detail: 'Experiment complete', color: 'bg-primary' },
];

const safetyTiers = [
  {
    tier: 'Tier 1: Physical Impossibilities',
    badge: 'bg-rose-50 text-rose-700 border-rose-200',
    icon: AlertOctagon,
    desc: 'Guarantees physical reality invariants that can never be disabled (e.g., a module cannot exit a closed container; a lid cannot be stowed before it is unscrewed).',
  },
  {
    tier: 'Tier 2: Non-Overridable Safety Rules',
    badge: 'bg-amber-50 text-amber-700 border-amber-200',
    icon: ShieldAlert,
    desc: 'Essential mission safety requirements (e.g., container must be verified empty before closing; no loose uncontained tools or lids on the glovebox rig floor).',
  },
  {
    tier: 'Tier 3: Configurable Protocol Rules',
    badge: 'bg-blue-50 text-primary border-blue-200',
    icon: Info,
    desc: 'Procedural rules configurable per experiment: mutual exclusion (one module out at a time), sealed before return, attended while open (5s), and step timeouts.',
  },
];

export default function ExperimentProtocol() {
  return (
    <section id="protocol" className="py-24 bg-slate-50 border-t border-slate-100">
      <div className="max-w-7xl mx-auto px-6">
        
        {/* Section Header */}
        <div className="text-center mb-16">
          <div className="inline-block px-3.5 py-1 bg-blue-50 text-primary text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-blue-100">
            Validated Protocol
          </div>
          <h2 className="text-4xl font-extrabold text-slate-900 mb-4 sm:text-5xl">
            The 12-Step BAS Experiment Protocol
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Grounded in ISRO Problem Statement 26174 — "a box containing two smaller boxes, red and yellow." Modules can be operated in either order under strict safety constraints.
          </p>
        </div>

        {/* 2-Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-start">
          
          {/* Left: 12 Procedure Steps (7 cols) */}
          <div className="lg:col-span-7 bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-100">
              <h3 className="font-bold text-slate-900 text-lg">
                Sequential State Transitions
              </h3>
              <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
                12 Steps · Either Module First
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {experimentSteps.map(({ step, label, detail, color }) => (
                <div
                  key={step}
                  className="flex items-start gap-3 bg-slate-50 hover:bg-blue-50/50 border border-slate-200/80 rounded-2xl p-3.5 transition-colors"
                >
                  <span
                    className={`w-7 h-7 rounded-xl ${color} text-white text-xs font-black flex items-center justify-center shrink-0 shadow-sm mt-0.5`}
                  >
                    {step}
                  </span>
                  <div>
                    <div className="text-sm font-bold text-slate-900 leading-snug">{label}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">{detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Safety Rules & Operator Authority (5 cols) */}
          <div className="lg:col-span-5 space-y-6">
            
            <div className="bg-white rounded-3xl p-6 sm:p-8 border border-slate-200 shadow-sm">
              <h3 className="font-bold text-slate-900 text-lg mb-6 pb-4 border-b border-slate-100">
                Three-Tier Safety Invariant Architecture
              </h3>

              <div className="space-y-4">
                {safetyTiers.map(({ tier, badge, icon: Icon, desc }) => (
                  <div key={tier} className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1 rounded-full border ${badge}`}>
                        <Icon className="w-3.5 h-3.5 shrink-0" />
                        {tier}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed">{desc}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Operator Authority Box */}
            <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-3xl p-6 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <div className="p-2 bg-primary text-white rounded-lg">
                  <Mic className="w-4 h-4" />
                </div>
                <h4 className="font-bold text-slate-900 text-sm">Operator Authority &amp; Voice Commands</h4>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed mb-3">
                The astronaut is always in command: <code className="bg-white px-1.5 py-0.5 rounded font-mono text-primary font-semibold">"Hey BAS, next step"</code> overrides or confirms unoccluded actions. Voice commands: <em>pause · resume · repeat · quiet</em>.
              </p>
              <div className="text-[11px] font-semibold text-primary flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Alerts once per root cause &mdash; never blocks execution.
              </div>
            </div>

          </div>

        </div>

      </div>
    </section>
  );
}
