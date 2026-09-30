import { FileCheck, Cpu, HardDrive, ShieldCheck } from 'lucide-react';

const stats = [
  {
    icon: FileCheck,
    value: '16 / 16',
    label: 'Rule Fixtures Verified',
    subtext: '100% test scenario pass rate',
  },
  {
    icon: Cpu,
    value: '0.89',
    label: 'mAP@50 Detection',
    subtext: 'On unseen recording sessions',
  },
  {
    icon: HardDrive,
    value: '486 KB',
    label: 'Downlink per Session',
    subtext: 'Down from 3.6 MB raw video',
  },
  {
    icon: ShieldCheck,
    value: '99.9%',
    label: 'Edge System Uptime',
    subtext: 'Zero crashes, CPU-native',
  },
];

export default function MissionMetrics() {
  return (
    <section id="metrics" className="py-24 bg-primary text-white relative overflow-hidden">
      {/* Subtle background glow */}
      <div className="absolute inset-0 opacity-20 pointer-events-none">
        <div className="absolute -top-32 -left-32 w-96 h-96 bg-cyan-400 rounded-full blur-3xl" />
        <div className="absolute -bottom-32 -right-32 w-96 h-96 bg-blue-300 rounded-full blur-3xl" />
      </div>

      <div className="max-w-7xl mx-auto px-6 text-center relative z-10">
        
        {/* Section Header */}
        <div className="mb-16">
          <div className="inline-block px-3.5 py-1 bg-white/10 text-cyan-200 text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-white/15">
            Empirical Validation
          </div>
          <h2 className="text-4xl sm:text-5xl font-black mb-4 tracking-tight">
            Validated for Bharatiya Antariksh Station
          </h2>
          <p className="text-xl text-blue-100 max-w-2xl mx-auto font-normal">
            Real mission impact, verifiable engineering results across 1,032 hand-labelled frames
          </p>
        </div>

        {/* 4 Top Glass Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-16">
          {stats.map((item, idx) => {
            const Icon = item.icon;
            return (
              <div
                key={idx}
                className="bg-white/10 backdrop-blur-md rounded-2xl p-8 border border-white/20 hover:bg-white/15 transition-all duration-300 flex flex-col items-center justify-center shadow-lg"
              >
                <div className="p-3 bg-white/15 rounded-xl mb-4 text-cyan-200">
                  <Icon className="w-8 h-8" />
                </div>
                <div className="text-4xl lg:text-5xl font-black text-white mb-2 tracking-tight">
                  {item.value}
                </div>
                <div className="text-base font-bold text-white mb-1">
                  {item.label}
                </div>
                <div className="text-xs text-blue-200 font-medium">
                  {item.subtext}
                </div>
              </div>
            );
          })}
        </div>

        {/* 3 Large Stat Callouts */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 pt-10 border-t border-white/20">
          <div className="space-y-2">
            <div className="text-5xl lg:text-6xl font-black text-amber-300 tracking-tight">
              86.5%
            </div>
            <div className="text-lg font-bold text-white">Downlink Bandwidth Saved</div>
            <div className="text-sm text-blue-200">486 KB vs 3.6 MB video per 12-step session</div>
          </div>

          <div className="space-y-2">
            <div className="text-5xl lg:text-6xl font-black text-emerald-300 tracking-tight">
              0
            </div>
            <div className="text-lg font-bold text-white">False Alarms on Correct Fixtures</div>
            <div className="text-sm text-blue-200">Deterministic constraint graph prevents hallucination</div>
          </div>

          <div className="space-y-2">
            <div className="text-5xl lg:text-6xl font-black text-white tracking-tight">
              &lt;300ms
            </div>
            <div className="text-lg font-bold text-white">Voice Alert Latency</div>
            <div className="text-sm text-blue-200">Instant offline Piper TTS intervention</div>
          </div>
        </div>

      </div>
    </section>
  );
}
