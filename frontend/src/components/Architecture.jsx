import { Camera, Clock, Search, Network, Cpu, Radio, Shield, Monitor, Volume2, FileText, Globe, Hand, Crosshair } from 'lucide-react';

const pipeline = [
  {
    id: 'cam',
    label: 'Fixed Camera',
    sublabel: 'Glovebox payload view',
    icon: Camera,
    arrow: true,
  },
  {
    id: 'capture',
    label: 'Capture Buffer',
    sublabel: 'Monotonic timestamping',
    icon: Clock,
    arrow: true,
  },
  {
    id: 'detect',
    label: 'YOLOv8n-OBB',
    sublabel: 'CPU ONNX · 23ms latency',
    icon: Search,
    arrow: true,
  },
  {
    id: 'fusion',
    label: 'Perception Fusion',
    sublabel: 'k-of-n voting & hold filter',
    icon: Network,
    arrow: true,
  },
  {
    id: 'engine',
    label: 'Protocol Engine',
    sublabel: 'Deterministic constraint graph',
    icon: Cpu,
    arrow: true,
  },
  {
    id: 'out',
    label: 'Multimodal Out',
    sublabel: 'Audio · GUI · Hash-Chained Log',
    icon: Radio,
    arrow: false,
  },
];

const sideInputs = [
  {
    icon: Hand,
    label: 'MediaPipe Hands',
    sublabel: 'Grasp detection & activity line',
    badge: 'Derived Cue',
  },
  {
    icon: Crosshair,
    label: 'ArUco Markers',
    sublabel: 'Rack-to-image 6DOF homography',
    badge: '1.0 px Error',
  },
];

const outputs = [
  {
    icon: Monitor,
    label: 'Crew Visual Console',
    sublabel: 'NOW banner, due steps, and real-time state cues',
  },
  {
    icon: Volume2,
    label: 'Piper Voice Synthesis',
    sublabel: 'Sub-second spoken alerts with 8s cooldown',
  },
  {
    icon: FileText,
    label: 'SHA-256 Chained Log',
    sublabel: 'Tamper-evident JSONL ledger for post-flight audit',
  },
  {
    icon: Globe,
    label: 'Earth Downlink',
    sublabel: '486 KB packet: event deltas + attested keyframes',
  },
];

export default function Architecture() {
  return (
    <section id="architecture" className="py-24 bg-white border-t border-slate-100">
      <div className="max-w-7xl mx-auto px-6">
        
        {/* Section Header */}
        <div className="text-center mb-16">
          <div className="inline-block px-3.5 py-1 bg-blue-50 text-primary text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-blue-100">
            System Design
          </div>
          <h2 className="text-4xl font-extrabold text-slate-900 mb-4 sm:text-5xl">
            Three-Layer Architecture
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Vision identifies objects; the deterministic engine decides safety. No neural network sits in the alert path — ensuring zero hallucinations.
          </p>
        </div>

        {/* Main Linear Pipeline */}
        <div className="bg-slate-50 border border-slate-200/80 rounded-3xl p-8 mb-12 shadow-sm">
          <div className="text-xs font-bold uppercase tracking-wider text-slate-400 text-center mb-8">
            Live Perception-to-Action Execution Flow
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-4">
            {pipeline.map(({ id, label, sublabel, icon: Icon, arrow }) => (
              <div key={id} className="flex items-center">
                <div className="flex flex-col items-center w-28 sm:w-36 text-center">
                  <div className="w-16 h-16 rounded-2xl bg-white border-2 border-blue-100 flex items-center justify-center shadow-md mb-3 text-primary group hover:border-primary transition-colors">
                    <Icon className="w-7 h-7" />
                  </div>
                  <div className="text-xs sm:text-sm font-bold text-slate-900">{label}</div>
                  <div className="text-[11px] text-slate-500 mt-1 leading-tight">{sublabel}</div>
                </div>
                {arrow && (
                  <div className="text-slate-300 font-bold text-xl sm:text-2xl mx-1 pb-8 shrink-0">
                    &rarr;
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Side Inputs & Rig Calibration */}
        <div className="mb-14">
          <div className="text-center text-xs font-bold text-slate-400 uppercase tracking-wider mb-6">
            Ancillary Perception Modules
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 max-w-2xl mx-auto">
            {sideInputs.map(({ icon: Icon, label, sublabel, badge }) => (
              <div
                key={label}
                className="flex items-center justify-between bg-white border border-slate-200 rounded-2xl p-5 shadow-sm hover:border-blue-200 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-blue-50 text-primary rounded-xl">
                    <Icon className="w-6 h-6" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-slate-900">{label}</div>
                    <div className="text-xs text-slate-500">{sublabel}</div>
                  </div>
                </div>
                <span className="text-[10px] font-bold text-primary bg-blue-50 border border-blue-100 px-2.5 py-1 rounded-full uppercase">
                  {badge}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* System Outputs 4-card grid */}
        <div>
          <div className="text-center text-xs font-bold text-slate-400 uppercase tracking-wider mb-6">
            Multimodal System Outputs
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {outputs.map(({ icon: Icon, label, sublabel }) => (
              <div
                key={label}
                className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm hover:shadow-md hover:border-blue-300 transition-all text-center flex flex-col items-center justify-between"
              >
                <div className="p-4 bg-gradient-to-br from-blue-50 to-indigo-50 text-primary rounded-2xl mb-4 border border-blue-100">
                  <Icon className="w-7 h-7" />
                </div>
                <div>
                  <h4 className="font-bold text-slate-900 text-sm mb-1">{label}</h4>
                  <p className="text-xs text-slate-500 leading-relaxed">{sublabel}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </section>
  );
}
