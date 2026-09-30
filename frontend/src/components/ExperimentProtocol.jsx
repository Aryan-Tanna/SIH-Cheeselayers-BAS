const experiment = [
  { step: 1, label: 'Open container', icon: '📦' },
  { step: 2, label: 'Take out red module', icon: '🔴' },
  { step: 3, label: 'Unscrew cap (red)', icon: '🔩' },
  { step: 4, label: 'Put cap down', icon: '⬇️' },
  { step: 5, label: 'Screw cap back', icon: '🔩' },
  { step: 6, label: 'Return red module', icon: '↩️' },
  { step: 7, label: 'Take out yellow module', icon: '🟡' },
  { step: 8, label: 'Unscrew cap (yellow)', icon: '🔩' },
  { step: 9, label: 'Put cap down', icon: '⬇️' },
  { step: 10, label: 'Screw cap back', icon: '🔩' },
  { step: 11, label: 'Return yellow module', icon: '↩️' },
  { step: 12, label: 'Close container', icon: '📦' },
];

const rules = [
  { tier: 'Physical impossibility', desc: 'A module cannot leave a closed container. Cannot be disabled.', badge: 'bg-red-100 text-red-700 border-red-200' },
  { tier: 'Non-overridable safety', desc: 'Container must be empty before close. No loose objects on rig.', badge: 'bg-orange-100 text-orange-700 border-orange-200' },
  { tier: 'Overridable rules', desc: 'One module at a time, sealed before return, out-of-order, skip, wrong object, extra step, step time limit.', badge: 'bg-blue-100 text-primary border-primary/20' },
];

export default function ExperimentProtocol() {
  return (
    <section id="protocol" className="bg-blue-50 border-t border-blue-100">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <div className="text-center mb-14">
          <span className="inline-block bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest mb-4">
            Sample Experiment
          </span>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">The 12-Step BAS Protocol</h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            Based on the PS example — "a box that contains two smaller boxes, red and yellow."
            Modules can be done in either order, but only one may be out at a time.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
          {/* Step grid */}
          <div>
            <h3 className="font-bold text-gray-900 mb-5">Procedure Steps</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {experiment.map(({ step, label, icon }) => (
                <div
                  key={step}
                  className="flex items-center gap-3 bg-white border border-gray-100 rounded-xl px-4 py-3 shadow-sm"
                >
                  <span className="w-7 h-7 rounded-full bg-primary text-white text-xs font-bold flex items-center justify-center shrink-0">
                    {step}
                  </span>
                  <span className="text-lg">{icon}</span>
                  <span className="text-sm font-medium text-gray-800">{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Safety rules */}
          <div>
            <h3 className="font-bold text-gray-900 mb-5">Safety Rule Tiers</h3>
            <div className="space-y-4 mb-8">
              {rules.map(({ tier, desc, badge }) => (
                <div key={tier} className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm">
                  <span className={`inline-block border text-xs font-bold px-3 py-1 rounded-full mb-3 ${badge}`}>
                    {tier}
                  </span>
                  <p className="text-sm text-gray-600">{desc}</p>
                </div>
              ))}
            </div>

            <div className="bg-white border border-primary/20 rounded-2xl p-5 shadow-sm">
              <h4 className="font-bold text-gray-900 mb-2">Operator Authority</h4>
              <p className="text-sm text-gray-600">
                "Hey BAS, next step" confirms a step the camera missed (logged as operator-confirmed).
                Pause / resume / repeat / quiet by voice. Alert once per root cause — never block the astronaut.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
