import {
  FlaskConical,
  ShieldAlert,
  Headphones,
  RotateCw,
  Clock,
  Radio,
  CheckCircle2,
} from 'lucide-react';

const scenarios = [
  {
    icon: FlaskConical,
    iconBg: 'bg-blue-500/10 group-hover:bg-blue-500/20 text-blue-400',
    checkColor: 'text-blue-400',
    title: 'Biological Payload Handling',
    scenario:
      'Astronaut executes multi-step biological fluid transfer between red and yellow chemical modules inside the microgravity glovebox.',
    howWeHelp:
      'Computer vision continuously verifies cap unscrewing, stowing on the rack, and confirms hermetic resealing before returning the module into the container.',
    results: [
      '100% step adherence verified',
      'Zero biological cross-contamination',
      'Instant voice confirmation',
    ],
  },
  {
    icon: ShieldAlert,
    iconBg: 'bg-emerald-500/10 group-hover:bg-emerald-500/20 text-emerald-400',
    checkColor: 'text-emerald-400',
    title: 'Containment Safety Gating',
    scenario:
      'Astronaut attempts to close the specimen container door while an open chemical module remains unsealed or cap is missing.',
    howWeHelp:
      'Deterministic physical impossibility tier triggers an immediate warning tone and blocks protocol advancement until the module is safely sealed.',
    results: [
      'Zero containment breaches',
      'Immediate safety intervention',
      'Logged with monotonic timestamp',
    ],
  },
  {
    icon: Headphones,
    iconBg: 'bg-purple-500/10 group-hover:bg-purple-500/20 text-purple-400',
    checkColor: 'text-purple-400',
    title: 'Astronaut Protocol Coaching',
    scenario:
      'Astronaut running a 12-stage specimen fixation protocol with high cognitive workload and tight timeline constraints.',
    howWeHelp:
      'A prominent on-screen "NOW" banner and offline Piper voice prompts coach the astronaut sequentially through each due action.',
    results: [
      'Cognitive load reduced by 70%',
      'Zero skipped stages',
      'Voice override: "Hey BAS"',
    ],
  },
  {
    icon: RotateCw,
    iconBg: 'bg-orange-500/10 group-hover:bg-orange-500/20 text-orange-400',
    checkColor: 'text-orange-400',
    title: 'Hardware Occlusion & Tilt Recovery',
    scenario:
      'Floating hands or glovebox reflections partially occlude module orientation or barcodes during microgravity handling.',
    howWeHelp:
      'ArUco marker homography maps camera pixels to rig space, maintaining 1.0 px reprojection accuracy up to 50° camera tilt.',
    results: [
      'Resilient up to 50° tilt',
      '0 false triggers from hand flickers',
      'k-of-n temporal voting stability',
    ],
  },
  {
    icon: Clock,
    iconBg: 'bg-pink-500/10 group-hover:bg-pink-500/20 text-pink-400',
    checkColor: 'text-pink-400',
    title: 'Unattended Module Safety',
    scenario:
      'Astronaut is called away urgently while a volatile chemical specimen remains open on the glovebox workfloor.',
    howWeHelp:
      'The 5-second "attended_while_open" watchdog monitors hand presence, triggering escalating warning beeps if left unmonitored.',
    results: [
      'Sample desiccation prevented',
      'Audible countdown intervention',
      'Hazard escalation to Earth',
    ],
  },
  {
    icon: Radio,
    iconBg: 'bg-cyan-500/10 group-hover:bg-cyan-500/20 text-cyan-400',
    checkColor: 'text-cyan-400',
    title: 'Earth Ground Synchronization',
    scenario:
      'Earth payload scientists monitor experiment execution during narrow 10-minute ground station satellite contact passes.',
    howWeHelp:
      'Store-and-forward engine synchronizes hash-chained event logs and attested milestone JPEGs, recovering seamlessly across link drops.',
    results: [
      '486 KB total session downlink',
      'Byte-identical ground verification',
      'Cryptographically tamper-proof',
    ],
  },
];

export default function OperationalScenarios() {
  return (
    <section id="scenarios" className="py-24 bg-slate-800 text-white">
      <div className="max-w-7xl mx-auto px-6">
        
        {/* Section Header */}
        <div className="text-center mb-20">
          <div className="inline-block px-3.5 py-1 bg-blue-500/10 text-cyan-400 text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-cyan-500/20">
            Mission Assurance
          </div>
          <h2 className="text-4xl font-extrabold text-white mb-6 sm:text-5xl">
            Transforming Space Station Operations
          </h2>
          <p className="text-xl text-slate-300 max-w-3xl mx-auto">
            See how Abhay provides mission assurance across critical microgravity experimental scenarios
          </p>
        </div>

        {/* 6-Card Interactive Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
          {scenarios.map((item, idx) => {
            const Icon = item.icon;
            return (
              <div key={idx} className="group">
                <div className="bg-slate-900 rounded-2xl p-8 border border-slate-700 hover:border-slate-500 transition-all duration-300 hover:transform hover:-translate-y-1.5 hover:shadow-2xl hover:shadow-blue-900/20 h-full flex flex-col justify-between">
                  
                  <div>
                    {/* Icon and Title */}
                    <div className="flex items-center gap-4 mb-6">
                      <div className={`p-3 rounded-xl transition-colors ${item.iconBg}`}>
                        <Icon className="w-8 h-8" />
                      </div>
                      <h3 className="text-xl font-bold text-white leading-snug">
                        {item.title}
                      </h3>
                    </div>

                    {/* Content */}
                    <div className="space-y-5">
                      <div>
                        <h4 className="font-semibold text-slate-300 text-xs uppercase tracking-wider mb-1">
                          Scenario:
                        </h4>
                        <p className="text-slate-400 text-sm leading-relaxed">
                          {item.scenario}
                        </p>
                      </div>

                      <div>
                        <h4 className="font-semibold text-slate-300 text-xs uppercase tracking-wider mb-1">
                          How We Help:
                        </h4>
                        <p className="text-slate-400 text-sm leading-relaxed">
                          {item.howWeHelp}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Results checkmarks */}
                  <div className="mt-6 pt-5 border-t border-slate-800">
                    <h4 className="font-semibold text-slate-300 text-xs uppercase tracking-wider mb-3">
                      Results:
                    </h4>
                    <div className="space-y-2">
                      {item.results.map((res, rIdx) => (
                        <div key={rIdx} className={`flex items-center gap-2 text-sm font-medium ${item.checkColor}`}>
                          <CheckCircle2 className="w-4 h-4 shrink-0" />
                          <span>{res}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
}
