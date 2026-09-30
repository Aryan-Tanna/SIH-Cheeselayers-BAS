import { Link } from 'react-router-dom';
import { CheckCircle2, ShieldAlert } from 'lucide-react';

const pills = [
  'CPU-Only Inference',
  '100% Offline',
  'Deterministic Alert Engine',
  'Tamper-Evident Log',
];

// Replace with your actual YouTube video ID
const YOUTUBE_VIDEO_ID = 'dQw4w9WgXcQ';

export default function Hero() {
  return (
    <section id="demo-video" className="relative bg-white overflow-hidden">
      {/* Subtle grid overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            'linear-gradient(to right, #e2e8f0 1px, transparent 1px), linear-gradient(to bottom, #e2e8f0 1px, transparent 1px)',
          backgroundSize: '56px 56px',
        }}
      />

      <div className="relative z-10 max-w-7xl mx-auto px-4 pt-8 pb-16 lg:pt-10 lg:pb-20 grid grid-cols-1 lg:grid-cols-2 gap-12 items-center w-full">

        {/* ── Left: headline ── */}
        <div>
          <div className="flex items-center flex-wrap gap-3 mb-6">
            <span className="bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest">
              SIH 2026 · PS 26174
            </span>
            <span className="bg-white border border-gray-200 text-gray-600 text-xs font-semibold px-4 py-1.5 rounded-full uppercase tracking-widest">
              ISRO / Dept. of Space
            </span>
          </div>

          <h1 className="text-5xl sm:text-6xl font-black tracking-tight leading-[1.05] mb-6">
            <span className="block text-gray-900">Meet</span>
            <span className="block text-primary">Abhay</span>
            <span className="block text-gray-700 text-3xl sm:text-4xl font-bold mt-2 leading-tight">
              AI Human Activity Recognition<br />for On-board BAS Experiments
            </span>
          </h1>

          <p className="max-w-lg text-lg text-gray-600 mb-8 leading-relaxed">
            Abhay watches a fixed payload camera, guides the astronaut through every
            experiment step, and raises a voice alert the instant something goes wrong —
            with zero internet and zero cloud.
          </p>

          <div className="flex items-center gap-4 flex-wrap mb-10">
            <Link
              to="/dashboard"
              className="bg-primary text-white px-8 py-3 rounded-full font-semibold hover:opacity-90 transition-opacity shadow-md"
            >
              Launch Mission Control
            </Link>
            <a
              href="#how-it-works"
              className="border border-gray-300 text-gray-700 px-8 py-3 rounded-full font-semibold hover:bg-gray-50 transition-colors"
            >
              How It Works
            </a>
          </div>

          <div className="grid grid-cols-2 gap-3 max-w-md">
            {pills.map((label) => (
              <div
                key={label}
                className="flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-sm"
              >
                <CheckCircle2 size={16} className="text-green-600 shrink-0" />
                <span className="text-sm font-semibold text-gray-800">{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Right: YouTube demo video ── */}
        <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6">
          <div className="text-xs font-bold text-primary tracking-widest uppercase mb-1">
            Showcase Demo
          </div>
          <p className="text-sm text-gray-500 mb-4">
            See Abhay in action — live experiment tracking on BAS Glovebox
          </p>

          {/* YouTube embed */}
          <div className="relative w-full aspect-video rounded-xl overflow-hidden mb-5 shadow-inner bg-gray-100">
            <iframe
              src={`https://www.youtube.com/embed/${YOUTUBE_VIDEO_ID}?rel=0&modestbranding=1`}
              title="Abhay Demo Video"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              className="absolute inset-0 w-full h-full rounded-xl"
            />
          </div>

          <span className="inline-flex items-center gap-1.5 bg-blue-50 border border-primary/20 text-primary text-xs font-bold uppercase tracking-wide px-3 py-1 rounded-full mb-3">
            <ShieldAlert size={12} />
            Deterministic Engine
          </span>
          <h3 className="font-bold text-gray-900 text-lg mb-1">No Neural Net in the Alert Path</h3>
          <p className="text-sm text-gray-600 mb-3">
            Vision identifies objects; the constraint-graph engine decides. Same input always
            produces the same alert — it cannot hallucinate a step.
          </p>
          <p className="text-xs text-gray-400 uppercase tracking-wide mb-4">
            Detects: skip &middot; out_of_order &middot; wrong_object &middot; extra_step
          </p>
          <a href="#how-it-works" className="text-primary font-semibold text-sm hover:underline">
            See How It Works &rarr;
          </a>
        </div>

      </div>
    </section>
  );
}
