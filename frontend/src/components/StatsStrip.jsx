const stats = [
  { label: 'Detector mAP50', value: '0.89' },
  { label: 'Rule Fixtures Passed', value: '16/16' },
  { label: 'Downlink vs Video', value: '7×' },
  { label: 'False Alarms', value: '0' },
];

export default function StatsStrip() {
  return (
    <section className="bg-primary rounded-2xl p-6 grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
      {stats.map((s) => (
        <div key={s.label}>
          <div className="text-3xl font-black text-white">{s.value}</div>
          <div className="text-sm text-white/75 mt-1">{s.label}</div>
        </div>
      ))}
    </section>
  );
}
