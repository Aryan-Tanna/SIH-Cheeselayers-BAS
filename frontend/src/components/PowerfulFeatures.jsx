import { useState, useEffect } from 'react';
import { Network, Volume2, Target, ShieldCheck, ChevronLeft, ChevronRight } from 'lucide-react';

const features = [
  {
    icon: Network,
    tag: 'DETERMINISTIC LOGIC',
    title: 'Constraint-Graph Protocol Engine',
    description:
      'A deterministic state machine evaluates permissible next steps across the 12-stage experiment workflow. Enforces strict mutual exclusion (one open module at a time) and impossible-transition guards — completely eliminating hallucinated protocol states.',
  },
  {
    icon: Volume2,
    tag: 'SUB-SECOND TTS',
    title: 'Real-Time Edge Voice Coaching',
    description:
      'Offline Piper TTS synthesizes instant spoken guidance into astronaut headsets. Alerts on skipped steps, out-of-order execution, loose caps, or unattended open ampoules with an 8-second root-cause cooldown to prevent alert fatigue.',
  },
  {
    icon: Target,
    tag: 'MICROGRAVITY VISION',
    title: 'Oriented Object Detection (YOLOv8n-OBB)',
    description:
      'Trained on 1,032 hand-labelled whole camera frames with 180° rotation photometric augmentations. Achieves 0.89 mAP@50 on unseen recording sessions, reliably detecting tilted containers, vials, lids, and gloved hands on a laptop CPU.',
  },
  {
    icon: ShieldCheck,
    tag: 'TAMPER-PROOF DOWNLINK',
    title: 'Cryptographic Hash-Chained Telemetry',
    description:
      'Each state transition writes UTC/monotonic timestamps, event confidence, and the previous line SHA-256 hash. Compresses mission telemetry from 3.6 MB video to 486 KB verifiable packets (an 86.5% reduction) for limited S-band ground passes.',
  },
];

export default function PowerfulFeatures() {
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % features.length);
    }, 5500);
    return () => clearInterval(timer);
  }, []);

  const current = features[currentIndex];
  const IconComponent = current.icon;

  return (
    <section id="features" className="py-24 bg-gradient-to-b from-blue-100/80 via-white to-slate-100/60 relative overflow-hidden">
      {/* Background radial glow */}
      <div className="absolute inset-0 opacity-60 pointer-events-none">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: `radial-gradient(circle at 20% 80%, rgba(0, 64, 121, 0.12) 0%, transparent 60%),
                              radial-gradient(circle at 80% 20%, rgba(14, 165, 233, 0.12) 0%, transparent 60%),
                              radial-gradient(circle at 40% 40%, rgba(59, 130, 246, 0.08) 0%, transparent 60%)`,
            backgroundSize: '600px 600px',
          }}
        />
      </div>

      <div className="max-w-7xl mx-auto px-6 relative z-10">
        
        {/* Section Header */}
        <div className="text-center mb-16">
          <div className="inline-block px-3 py-1 bg-blue-100/80 text-primary text-xs font-bold rounded-full uppercase tracking-wider mb-3">
            Core Capabilities
          </div>
          <h2 className="text-4xl font-extrabold text-slate-900 mb-4 sm:text-5xl">
            Powerful On-Board Features
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Discover cutting-edge capabilities that revolutionize astronaut activity recognition &amp; payload safety
          </p>
        </div>

        {/* Feature Carousel Card */}
        <div className="relative max-w-4xl mx-auto">
          {/* Ambient Glow */}
          <div className="absolute left-1/2 -translate-x-1/2 top-8 w-[98%] h-[90%] rounded-3xl bg-blue-200/40 blur-2xl shadow-2xl shadow-blue-300/40 z-0" />

          {/* Main Card */}
          <div className="bg-white/90 backdrop-blur-md rounded-3xl p-8 sm:p-14 border border-blue-100/80 shadow-xl shadow-blue-500/5 relative z-10">
            <div className="flex flex-col items-center justify-center text-center max-w-2xl mx-auto">
              
              {/* Icon in Rounded Gradient Container */}
              <div className="mb-8 flex justify-center">
                <div className="p-6 bg-gradient-to-br from-white to-blue-50 rounded-2xl shadow-lg border border-blue-100/80 backdrop-blur-sm">
                  <IconComponent className="w-14 h-14 text-primary animate-pulse-slow" />
                </div>
              </div>

              {/* Tag Pill */}
              <span className="text-xs font-bold tracking-widest text-primary uppercase bg-blue-50 px-3.5 py-1 rounded-full border border-blue-100 mb-3">
                {current.tag}
              </span>

              {/* Title */}
              <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-900 mb-5">
                {current.title}
              </h3>

              {/* Description */}
              <p className="text-slate-600 leading-relaxed text-base sm:text-lg">
                {current.description}
              </p>
            </div>

            {/* Left and Right navigation arrows */}
            <button
              onClick={() => setCurrentIndex((prev) => (prev - 1 + features.length) % features.length)}
              className="absolute left-4 top-1/2 -translate-y-1/2 p-2.5 rounded-full bg-white/80 hover:bg-white text-slate-700 shadow-md border border-slate-200 transition-all hover:scale-110"
              aria-label="Previous feature"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <button
              onClick={() => setCurrentIndex((prev) => (prev + 1) % features.length)}
              className="absolute right-4 top-1/2 -translate-y-1/2 p-2.5 rounded-full bg-white/80 hover:bg-white text-slate-700 shadow-md border border-slate-200 transition-all hover:scale-110"
              aria-label="Next feature"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>

          {/* Indicator Pills matching Sahayak */}
          <div className="flex justify-center items-center mt-8 gap-3">
            {features.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setCurrentIndex(idx)}
                className={`h-3 rounded-full transition-all duration-300 ${
                  currentIndex === idx
                    ? 'bg-primary w-12 shadow-lg shadow-blue-600/30'
                    : 'bg-slate-300 hover:bg-blue-400 w-3'
                }`}
                aria-label={`Go to slide ${idx + 1}`}
              />
            ))}
          </div>

        </div>

      </div>
    </section>
  );
}
