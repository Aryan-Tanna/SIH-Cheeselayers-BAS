const metrics = [
  {
    value: '0.89',
    label: 'Detector mAP50',
    note: 'YOLOv8n-OBB v5 on held-out sessions',
    color: 'text-primary',
    bg: 'bg-blue-50 border-primary/20',
  },
  {
    value: '16 / 16',
    label: 'Rule Fixtures Passed',
    note: '0 false alarms across all synthetic test cases',
    color: 'text-green-600',
    bg: 'bg-green-50 border-green-200',
  },
  {
    value: '486 KB',
    label: 'Downlink per Session',
    note: 'vs 3.6 MB of raw video — 7× smaller',
    color: 'text-primary',
    bg: 'bg-blue-50 border-primary/20',
  },
  {
    value: '17 / 18',
    label: 'Events Detected',
    note: 'On 3 verified held-out clips (S05)',
    color: 'text-green-600',
    bg: 'bg-green-50 border-green-200',
  },
  {
    value: '12',
    label: 'Experiment Steps',
    note: 'Open · modules · unseal · reseal · close',
    color: 'text-primary',
    bg: 'bg-blue-50 border-primary/20',
  },
  {
    value: '0',
    label: 'False Alarms',
    note: 'On correct runs with settle window applied',
    color: 'text-green-600',
    bg: 'bg-green-50 border-green-200',
  },
];

const violations = [
  'skip', 'out_of_order', 'wrong_object', 'extra_step',
  'mutual_exclusion_breach', 'lid_unstowed', 'unattended_open_module',
  'module_not_sealed', 'module_not_returned', 'step_overdue',
];

export default function ResultsMetrics() {
  return (
    <section id="results" className="bg-white border-t border-gray-100">
      <div className="max-w-7xl mx-auto px-4 py-20">
        <div className="text-center mb-14">
          <span className="inline-block bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest mb-4">
            Measured Results
          </span>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">Numbers We Stand Behind</h2>
          <p className="text-gray-500 max-w-2xl mx-auto">
            All figures come from real held-out sessions or synthetic fixtures. Where a
            number was not measured, we say so.
          </p>
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-5 mb-16">
          {metrics.map(({ value, label, note, color, bg }) => (
            <div
              key={label}
              className={`border rounded-2xl p-6 text-center ${bg}`}
            >
              <div className={`text-4xl font-black mb-1 ${color}`}>{value}</div>
              <div className="font-semibold text-gray-900 text-sm mb-1">{label}</div>
              <div className="text-xs text-gray-500">{note}</div>
            </div>
          ))}
        </div>

        {/* Violation codes */}
        <div className="bg-gray-50 border border-gray-100 rounded-2xl p-8">
          <h3 className="font-bold text-gray-900 text-lg mb-2">Violation Codes Detected</h3>
          <p className="text-sm text-gray-500 mb-6">
            The protocol engine can recognise and speak any of these violations —
            one spoken alert per root cause (8 s cooldown, max 4/min).
          </p>
          <div className="flex flex-wrap gap-2">
            {violations.map((v) => (
              <span
                key={v}
                className="bg-white border border-primary/20 text-primary text-xs font-bold px-3 py-1.5 rounded-full font-mono"
              >
                {v}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
