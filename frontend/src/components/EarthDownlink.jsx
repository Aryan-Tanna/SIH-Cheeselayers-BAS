const steps = [
  {
    icon: '🛸',
    title: 'On-Board Log',
    desc: 'Every step and alert is written to a hash-chained JSONL log on the station. The chain is verified end-to-end — one altered line is flagged.',
  },
  {
    icon: '📸',
    title: '1 JPEG per Step',
    desc: 'One attested JPEG is captured per step completion and per alert. Its sha256 is written into the hash chain on board before downlink.',
  },
  {
    icon: '📡',
    title: 'Store & Forward',
    desc: 'Everything is kept on board until the ground acknowledges it. After a signal loss, the system resends from where the ground stopped — byte-identical.',
  },
  {
    icon: '🌍',
    title: 'Mission Control (Earth)',
    desc: 'The ground station verifies each line against the hash chain as it arrives. A tampered line prints "LOG TAMPERED". Images are marked VERIFIED only if sha256 matches.',
  },
];

export default function EarthDownlink() {
  return (
    <section id="downlink" className="bg-white border-t border-gray-100">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <div className="text-center mb-14">
          <span className="inline-block bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest mb-4">
            Earth Downlink
          </span>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">Sending to Earth — Without Video</h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            Raw video to Earth is not viable. Abhay sends the log and one image per step —
            <strong className="text-gray-800"> 486 KB instead of 3.6 MB</strong> — fully tamper-evident.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          {steps.map(({ icon, title, desc }) => (
            <div key={title} className="bg-blue-50 border border-blue-100 rounded-2xl p-6 hover:border-primary/40 transition-colors">
              <div className="text-4xl mb-4">{icon}</div>
              <h3 className="font-bold text-gray-900 mb-2">{title}</h3>
              <p className="text-sm text-gray-600 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>

        {/* Bandwidth comparison */}
        <div className="bg-gray-50 border border-gray-100 rounded-2xl p-8 grid grid-cols-1 sm:grid-cols-3 gap-6 items-center text-center">
          <div>
            <div className="text-4xl font-black text-red-400 mb-1">3.6 MB</div>
            <div className="text-sm font-semibold text-gray-700">Raw video per session</div>
            <div className="text-xs text-gray-500 mt-1">Not viable for space-to-Earth downlink</div>
          </div>
          <div className="text-3xl text-primary font-black">→ 7× smaller →</div>
          <div>
            <div className="text-4xl font-black text-primary mb-1">486 KB</div>
            <div className="text-sm font-semibold text-gray-700">Log + JPEGs per session</div>
            <div className="text-xs text-gray-500 mt-1">Verified, tamper-evident, with light-time simulation</div>
          </div>
        </div>
      </div>
    </section>
  );
}
