const pipeline = [
  {
    id: 'cam',
    label: 'Camera',
    sublabel: 'Fixed payload cam',
    icon: '📷',
    arrow: true,
  },
  {
    id: 'capture',
    label: 'Capture',
    sublabel: 'Timestamp at acquisition',
    icon: '⏱️',
    arrow: true,
  },
  {
    id: 'detect',
    label: 'Detector',
    sublabel: 'YOLOv8n-OBB · ONNX · CPU',
    icon: '🔍',
    arrow: true,
  },
  {
    id: 'fusion',
    label: 'Fusion',
    sublabel: 'k-of-n votes + min hold',
    icon: '🔗',
    arrow: true,
  },
  {
    id: 'engine',
    label: 'Protocol Engine',
    sublabel: 'Constraint-graph · deterministic',
    icon: '⚙️',
    arrow: true,
  },
  {
    id: 'out',
    label: 'Output',
    sublabel: 'GUI · TTS · Log · Downlink',
    icon: '📡',
    arrow: false,
  },
];

const outputs = [
  { icon: '🖥️', label: 'Crew GUI', sublabel: 'NOW banner + next step' },
  { icon: '🔊', label: 'Voice Alert', sublabel: 'Piper TTS — offline' },
  { icon: '📝', label: 'JSONL Log', sublabel: 'Hash-chained, tamper-evident' },
  { icon: '🌍', label: 'Earth Downlink', sublabel: '486 KB · 1 JPEG/step' },
];

const sideInputs = [
  { icon: '🖐️', label: 'MediaPipe Hands', sublabel: 'Grasp + activity cue' },
  { icon: '📐', label: 'ArUco Markers', sublabel: 'Rack-to-image mapping' },
];

export default function Architecture() {
  return (
    <section id="architecture" className="bg-blue-50 border-t border-blue-100">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <div className="text-center mb-14">
          <span className="inline-block bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest mb-4">
            System Design
          </span>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">Three-Layer Architecture</h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            Vision identifies objects. The deterministic engine decides. No neural network
            ever sits in the alert path — the same input will always produce the same output.
          </p>
        </div>

        {/* Main pipeline */}
        <div className="flex flex-wrap items-center justify-center gap-0 mb-12">
          {pipeline.map(({ id, label, sublabel, icon, arrow }) => (
            <div key={id} className="flex items-center">
              <div className="flex flex-col items-center w-28 sm:w-32">
                <div className="w-16 h-16 rounded-2xl bg-white border-2 border-primary/20 flex items-center justify-center text-2xl shadow-sm mb-2">
                  {icon}
                </div>
                <div className="text-xs font-bold text-gray-900 text-center">{label}</div>
                <div className="text-[10px] text-gray-500 text-center leading-tight mt-0.5">{sublabel}</div>
              </div>
              {arrow && (
                <div className="text-primary font-bold text-2xl mx-1 sm:mx-2 pb-6 shrink-0">→</div>
              )}
            </div>
          ))}
        </div>

        {/* Side inputs row */}
        <div className="flex flex-wrap justify-center gap-4 mb-12">
          <p className="w-full text-center text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">
            Additional Inputs to Detector
          </p>
          {sideInputs.map(({ icon, label, sublabel }) => (
            <div key={label} className="flex items-center gap-3 bg-white border border-primary/20 rounded-xl px-5 py-3 shadow-sm">
              <span className="text-xl">{icon}</span>
              <div>
                <div className="text-sm font-semibold text-gray-900">{label}</div>
                <div className="text-xs text-gray-500">{sublabel}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Output cards */}
        <div>
          <p className="text-center text-xs font-semibold text-gray-400 uppercase tracking-widest mb-6">
            System Outputs
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {outputs.map(({ icon, label, sublabel }) => (
              <div key={label} className="bg-white border border-gray-100 rounded-2xl p-5 text-center shadow-sm hover:border-primary/30 transition-colors">
                <div className="text-3xl mb-2">{icon}</div>
                <div className="font-semibold text-gray-900 text-sm">{label}</div>
                <div className="text-xs text-gray-500 mt-1">{sublabel}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
