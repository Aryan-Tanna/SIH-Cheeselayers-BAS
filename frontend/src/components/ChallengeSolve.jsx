import { AlertTriangle, CheckCircle2 } from 'lucide-react';

const problems = [
  {
    title: 'Manual Procedure Strain & Cognitive Load',
    description:
      'Astronauts manage high-precision biological protocols under physical spaceflight strain, risking missed steps, incorrect tool order, or left-open vials.',
    impact: 'Irreversible specimen loss & experiment abort',
  },
  {
    title: 'Ground Communication Latency',
    description:
      'Orbital geometry and ground relay links introduce 10–30 minute signal roundtrips; Earth scientists cannot intervene during rapid chemical reaction steps.',
    impact: 'Zero real-time ground supervision possible',
  },
  {
    title: 'Bandwidth-Constrained Downlink',
    description:
      'Streaming continuous raw 1080p glovebox video exhausts narrow satellite passes and drops transmission during critical mission phases.',
    impact: '3.6 MB/s continuous downlink bottleneck',
  },
  {
    title: 'Unverifiable Flight Telemetry',
    description:
      'Manual handwritten flight logs lack cryptographic proof of timing, hand interactions, and exact sequence order for post-mission peer review.',
    impact: 'Disputed scientific reproducibility on Earth',
  },
];

const solutions = [
  {
    title: 'Autonomous Edge Computer Vision',
    description:
      'YOLOv8n-OBB + ArUco rack homography continuously tracks modules, lids, and gloved hands on-board with 0 human overhead and no internet.',
    benefit: '100% autonomous astronaut co-pilot',
  },
  {
    title: 'Sub-Second On-Board Voice Alerts',
    description:
      'Offline Piper TTS speaks instant alerts (skip, out_of_order, extra_step) directly to astronaut headsets before mistakes become irreversible.',
    benefit: 'Immediate auditory intervention (<300ms)',
  },
  {
    title: 'Semantic Delta Telemetry Downlink',
    description:
      'Transmits structured JSONL state updates and attested milestone keyframe snapshots instead of raw continuous video feeds.',
    benefit: '86.5% bandwidth saved: 486 KB vs 3.6 MB',
  },
  {
    title: 'Tamper-Evident SHA-256 Hash Chain',
    description:
      'Every state transition and snapshot hash is immutably linked in an on-board ledger, cryptographically verifiable upon arrival on Earth.',
    benefit: '100% verifiable scientific audit trail',
  },
];

export default function ChallengeSolve() {
  return (
    <section id="challenge" className="py-24 bg-slate-900 text-white">
      <div className="max-w-7xl mx-auto px-6">
        
        {/* Section Header */}
        <div className="text-center mb-20">
          <div className="inline-block px-3.5 py-1 bg-blue-500/10 text-cyan-400 text-xs font-bold rounded-full uppercase tracking-wider mb-3 border border-cyan-500/20">
            Mission Gap Analysis
          </div>
          <h2 className="text-4xl font-extrabold text-white mb-6 sm:text-5xl">
            The Challenge We Solve
          </h2>
          <p className="text-xl text-slate-300 max-w-3xl mx-auto">
            Traditional experiment execution is holding back scientific velocity on the space station
          </p>
        </div>

        {/* 2-Column Split Grid */}
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-stretch">
          
          {/* Left Column: Current Problems (Red Theme) */}
          <div className="flex flex-col h-full">
            <div className="bg-red-500/10 border border-red-500/20 rounded-2xl p-8 flex flex-col h-full shadow-lg shadow-red-950/20">
              
              <div className="flex items-center gap-4 mb-8">
                <div className="p-3 bg-red-500 rounded-xl shadow-md">
                  <AlertTriangle className="w-8 h-8 text-white" />
                </div>
                <div>
                  <h3 className="text-2xl font-bold text-red-400">Current Problems</h3>
                  <p className="text-xs text-slate-400 mt-0.5">On-board space station constraints</p>
                </div>
              </div>

              <div className="space-y-5 flex-grow">
                {problems.map((prob, idx) => (
                  <div
                    key={idx}
                    className="bg-slate-800/60 hover:bg-slate-800 rounded-xl p-5 border border-slate-700/80 transition-colors"
                  >
                    <h4 className="font-bold text-white text-base mb-2">{prob.title}</h4>
                    <p className="text-slate-300 text-sm mb-3 leading-relaxed">
                      {prob.description}
                    </p>
                    <div className="text-xs text-red-400 font-semibold bg-red-500/15 border border-red-500/20 px-3 py-1 rounded-full inline-block">
                      Impact: {prob.impact}
                    </div>
                  </div>
                ))}
              </div>

            </div>
          </div>

          {/* Right Column: Our Solutions (Emerald Theme) */}
          <div className="flex flex-col h-full">
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-8 flex flex-col h-full shadow-lg shadow-emerald-950/20">
              
              <div className="flex items-center gap-4 mb-8">
                <div className="p-3 bg-emerald-500 rounded-xl shadow-md">
                  <CheckCircle2 className="w-8 h-8 text-white" />
                </div>
                <div>
                  <h3 className="text-2xl font-bold text-emerald-400">Our Solutions</h3>
                  <p className="text-xs text-slate-400 mt-0.5">Abhay on-board intelligence</p>
                </div>
              </div>

              <div className="space-y-5 flex-grow">
                {solutions.map((sol, idx) => (
                  <div
                    key={idx}
                    className="bg-slate-800/60 hover:bg-slate-800 rounded-xl p-5 border border-slate-700/80 transition-colors"
                  >
                    <h4 className="font-bold text-white text-base mb-2">{sol.title}</h4>
                    <p className="text-slate-300 text-sm mb-3 leading-relaxed">
                      {sol.description}
                    </p>
                    <div className="text-xs text-emerald-400 font-semibold bg-emerald-500/15 border border-emerald-500/20 px-3 py-1 rounded-full inline-block">
                      Benefit: {sol.benefit}
                    </div>
                  </div>
                ))}
              </div>

            </div>
          </div>

        </div>

      </div>
    </section>
  );
}
