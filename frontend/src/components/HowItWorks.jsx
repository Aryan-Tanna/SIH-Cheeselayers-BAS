import { Camera, GitBranch, Volume2, FileText } from 'lucide-react';

const steps = [
  {
    title: 'Capture',
    desc: 'A fixed payload camera streams to the on-board system. Every frame is timestamped at acquisition — no network needed.',
    Icon: Camera,
  },
  {
    title: 'Detect & Track',
    desc: 'YOLOv8n-OBB (ONNX, CPU-only) identifies objects and ArUco markers. MediaPipe tracks hand skeleton for grasp cues.',
    Icon: GitBranch,
  },
  {
    title: 'Alert',
    desc: 'The deterministic protocol engine raises voice alerts (skip, out_of_order, wrong_object) via Piper TTS — offline.',
    Icon: Volume2,
  },
  {
    title: 'Log & Downlink',
    desc: 'A hash-chained JSONL log is verified on arrival. One JPEG per step — 486 KB vs 3.6 MB of video — is sent to Earth.',
    Icon: FileText,
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-white">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <h2 className="text-3xl font-bold text-center text-gray-900 mb-2">How VYOM antariksh Works</h2>
        <p className="text-center text-gray-500 mb-12">
          Four stages. Entirely on-board. No cloud, no GPU, no internet.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {steps.map(({ title, desc, Icon }, i) => (
            <div
              key={title}
              className="bg-blue-50 border border-blue-100 rounded-2xl p-6 hover:border-primary/40 transition-colors group"
            >
              <div className="w-14 h-14 rounded-xl bg-white flex items-center justify-center mb-4 shadow-sm group-hover:shadow-md transition-shadow">
                <Icon size={28} strokeWidth={1.75} className="text-primary" />
              </div>
              <div className="text-xs font-bold text-primary uppercase tracking-widest mb-1">
                STEP {i + 1}
              </div>
              <h3 className="font-bold text-gray-900 mb-2">{title}</h3>
              <p className="text-sm text-gray-600 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
