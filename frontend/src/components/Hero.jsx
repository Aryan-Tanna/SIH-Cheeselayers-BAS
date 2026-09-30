import { Link } from 'react-router-dom';
import {
  Star,
  CheckCircle2,
  Play,
  ArrowRight,
  Network,
  Shield,
  Cpu,
  Sparkles,
  ExternalLink,
  ShieldAlert,
  Zap,
  Download,
} from 'lucide-react';
import { ZIP_DOWNLOAD_URL } from '../lib/downloads.js';

const YOUTUBE_VIDEO_ID = 'N_Sa6XlcNHM'; // Can be customized or user can switch to local

export default function Hero() {
  return (
    <section className="relative overflow-hidden bg-slate-50 pb-16 pt-6 lg:pb-24 lg:pt-8">
      {/* Background grid pattern matching Sahayak */}
      <div className="absolute inset-0 bg-slate-50 pointer-events-none">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#e2e8f0_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f0_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_80%_at_50%_0%,#000_70%,transparent_110%)]"></div>
      </div>

      <div className="relative z-10 mx-auto grid max-w-7xl grid-cols-1 gap-12 px-6 lg:grid-cols-12 lg:gap-x-10 lg:gap-y-0 xl:gap-x-14 lg:items-start">
        
        {/* ── Left Column: Headline and Value Props (lg:col-span-7) ── */}
        <div className="flex flex-col space-y-8 lg:col-span-7 lg:max-w-xl xl:max-w-2xl">
          
          {/* Badge & Star Rating */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="inline-block rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white shadow-sm">
              AI for Bharat · ISRO PS 26174
            </span>
            <div className="flex items-center gap-1">
              {[...Array(5)].map((_, i) => (
                <Star key={i} className="h-4 w-4 fill-current text-amber-400" />
              ))}
              <span className="ml-2 text-sm font-semibold text-slate-700">
                mAP50 0.89 · 0 False Alarms
              </span>
            </div>
          </div>

          {/* Main Hero Headline */}
          <h1 className="text-5xl font-black leading-tight text-slate-900 lg:text-6xl xl:text-7xl">
            Autonomous AI
            <span className="block text-primary">Co-Pilot</span>
            <span className="block text-slate-700">for BAS Experiments</span>
          </h1>

          {/* Subtitle / Description from README */}
          <p className="max-w-xl text-xl leading-relaxed text-slate-600">
            Empower astronauts on the Bharatiya Antariksh Station with real-time biological payload activity recognition, instant safety gating, voice alerts via Piper TTS, and tamper-evident Earth telemetry.
          </p>

          {/* 4 Feature Badges (2x2 Grid) */}
          <div className="grid w-full max-w-xl grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 hover:border-blue-200 transition-colors">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              <span className="font-semibold text-slate-700 text-sm sm:text-base">16/16 Rule Fixtures Verified</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 hover:border-blue-200 transition-colors">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              <span className="font-semibold text-slate-700 text-sm sm:text-base">86% Downlink Reduction</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 hover:border-blue-200 transition-colors">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              <span className="font-semibold text-slate-700 text-sm sm:text-base">Sub-Second Voice Alerts</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 hover:border-blue-200 transition-colors">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
              <span className="font-semibold text-slate-700 text-sm sm:text-base">Hash-Chained Audit Log</span>
            </div>
          </div>

          {/* CTA Buttons */}
          <div className="flex flex-col gap-4 pt-2 sm:flex-row sm:flex-wrap">
            <Link
              to="/dashboard"
              className="group flex items-center justify-center gap-3 rounded-xl bg-primary px-8 py-4 font-semibold text-white shadow-lg transition hover:bg-[#003366] hover:shadow-xl sm:flex-initial"
            >
              <Play className="h-5 w-5 fill-current" />
              <span>Launch Mission Control</span>
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>

            <a
              href={ZIP_DOWNLOAD_URL}
              className="flex items-center justify-center gap-3 rounded-xl border-2 border-primary px-8 py-4 font-semibold text-primary transition hover:bg-blue-50"
            >
              <Download className="h-5 w-5" />
              <span>Download ZIP</span>
            </a>

            <a
              href="#architecture"
              className="flex items-center justify-center gap-3 rounded-xl border-2 border-slate-300 px-8 py-4 font-semibold text-slate-700 transition hover:bg-slate-100 hover:border-slate-400"
            >
              <Network className="h-5 w-5 text-primary" />
              <span>Constraint Engine</span>
            </a>

            <a
              href="#scenarios"
              className="flex items-center justify-center gap-3 rounded-xl border-2 border-emerald-500 px-8 py-4 font-semibold text-emerald-700 transition hover:bg-emerald-50"
            >
              <Shield className="h-5 w-5 text-emerald-600" />
              <span>Safety Scenarios</span>
            </a>
          </div>

        </div>

        {/* ── Right Column: Showcase Demo Card (lg:col-span-5, sticky) ── */}
        <div className="lg:col-span-5 lg:sticky lg:top-24 lg:self-start">
          <div className="rounded-3xl border border-slate-200/90 bg-white/95 p-5 shadow-xl shadow-slate-300/40 ring-1 ring-slate-900/[0.04] backdrop-blur-sm sm:p-6">
            
            {/* Showcase Demo Video Section */}
            <div id="demo-video" className="scroll-mt-28" aria-labelledby="demo-video-heading">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-2 border-b border-slate-100 pb-3">
                <div>
                  <h2 id="demo-video-heading" className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
                    Showcase Demo
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    See VYOM antariksh in action on BAS Glovebox
                  </p>
                </div>
                <a
                  href="#demo-video-local"
                  className="text-sm font-semibold text-primary underline-offset-2 hover:text-[#00284d] hover:underline flex items-center gap-1"
                >
                  Local Video &darr;
                </a>
              </div>

              {/* Video Player */}
              <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-900 shadow-inner ring-1 ring-black/10">
                <iframe
                  className="absolute inset-0 h-full w-full"
                  src={`https://www.youtube.com/embed/${YOUTUBE_VIDEO_ID}?rel=0&modestbranding=1`}
                  title="VYOM antariksh AI showcase demo"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  allowFullScreen
                />
              </div>
            </div>

            {/* Subtle Divider */}
            <div className="my-6 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" aria-hidden="true" />

            {/* Edge AI Engine Showcase (Mirroring Sahayak's MCP Card) */}
            <div id="edge-integration" className="scroll-mt-28">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-primary">
                <Cpu className="h-3 w-3" />
                Edge AI · CPU Only
              </div>
              
              <h3 className="text-lg font-bold tracking-tight text-slate-900">
                Runs on On-Board Low-Power Hardware
              </h3>
              
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                YOLOv8n-OBB detector + ArUco rack homography + MediaPipe hands fused inside an offline edge process with zero internet dependency.
              </p>
              
              <p className="mt-3 text-xs leading-snug text-slate-500">
                Pipeline: <span className="font-semibold text-slate-700">detector · fusion · constraint-graph · piper-tts · downlink-pack</span>
              </p>

              <a
                href="#architecture"
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50/90 px-4 py-2.5 text-sm font-semibold text-primary shadow-sm transition hover:bg-blue-100 hover:border-blue-300"
              >
                <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                See VYOM antariksh Pipeline Architecture
              </a>

              <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Link
                  to="/dashboard"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-center text-sm font-semibold text-white shadow-md transition hover:bg-slate-800"
                >
                  Crew Console
                  <ArrowRight className="h-3.5 w-3.5 opacity-90" />
                </Link>

                <a
                  href="#protocol"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border-2 border-primary bg-white px-4 py-3 text-center text-sm font-semibold text-primary transition hover:bg-blue-50"
                >
                  Protocol Rules
                  <ArrowRight className="h-3.5 w-3.5 opacity-90" />
                </a>
              </div>

              <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500 border border-slate-100">
                Deterministic engine guarantees: <code className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-700 ring-1 ring-slate-200">0 neural nets in alert path</code> — eliminates false positives, skips, and hallucinated protocol completions.
              </p>
            </div>

            {/* Constraint Graph & State Explorer Card (Mirroring Sahayak's Graph Intelligence card) */}
            <div className="mt-5 rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-indigo-50 p-4 shadow-sm">
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-primary">
                <Network className="h-3 w-3" />
                Graph Intelligence
              </div>
              
              <h3 className="text-lg font-bold tracking-tight text-slate-900">
                Deterministic Safety State Machine
              </h3>
              
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
                Maintains a set of permissible next steps across the 12-stage biological workflow. Enforces mutual exclusion and non-overridable physical safety rules.
              </p>
              
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200 font-medium">12 Protocol Steps</span>
                <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200 font-medium">3 Safety Tiers</span>
                <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200 font-medium">Auto-Rollback</span>
              </div>

              <a
                href="#protocol"
                className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white shadow-md transition hover:bg-[#003366] w-full"
              >
                <span>Open Protocol Explorer</span>
                <ExternalLink className="h-3.5 w-3.5 opacity-90" />
              </a>
            </div>

          </div>
        </div>

      </div>
    </section>
  );
}
