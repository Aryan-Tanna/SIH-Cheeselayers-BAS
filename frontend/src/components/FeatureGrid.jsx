const features = [
  {
    icon: '🎯',
    title: 'mAP50 0.89 Detector',
    desc: 'YOLOv8n-OBB trained on 1,032 hand-labelled frames. Runs on CPU via ONNX — no GPU needed.',
  },
  {
    icon: '🔔',
    title: 'Voice Alert Engine',
    desc: 'Spoken alerts via Piper TTS (offline) for skip, out_of_order, wrong_object, and extra_step violations.',
  },
  {
    icon: '📡',
    title: 'Mission Control (Earth)',
    desc: 'Ground station receives the hash-chained log + 1 JPEG per step. 486 KB vs 3.6 MB of raw video.',
  },
  {
    icon: '🖥️',
    title: 'Crew Co-Pilot GUI',
    desc: 'Real-time NOW banner, next-step voice prompt, and procedure editor with hot reload — no restart needed.',
  },
  {
    icon: '🛡️',
    title: 'Tamper-Evident Log',
    desc: 'Hash-chained JSONL log verified on arrival. Altered lines are flagged with "LOG TAMPERED" on the ground.',
  },
  {
    icon: '⚙️',
    title: 'Protocol Editor',
    desc: 'Add, reorder, or set per-step time limits. Every rule is validated before save — no silent inert rules.',
  },
];

export default function FeatureGrid() {
  return (
    <section id="capabilities">
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Core Capabilities</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {features.map((f) => (
          <div
            key={f.title}
            className="bg-blue-50 border border-blue-100 rounded-2xl p-6 hover:border-primary/40 transition-colors"
          >
            <div className="text-3xl mb-3">{f.icon}</div>
            <h3 className="font-semibold text-gray-900 mb-1">{f.title}</h3>
            <p className="text-sm text-gray-600">{f.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
