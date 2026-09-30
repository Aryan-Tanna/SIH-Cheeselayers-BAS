import { Link } from 'react-router-dom';
import { Play, FileText, Shield, CheckCircle2, Cpu, Globe } from 'lucide-react';

export default function DeployCTA() {
  return (
    <section className="py-24 bg-gradient-to-b from-blue-50/70 via-white to-slate-50 relative overflow-hidden border-t border-slate-100">
      <div className="max-w-5xl mx-auto px-6 text-center">
        
        <h2 className="text-4xl sm:text-5xl lg:text-6xl font-black text-slate-900 mb-6 tracking-tight">
          Ready to Safeguard Space Station Experiments?
        </h2>
        
        <p className="text-lg sm:text-xl text-slate-600 max-w-2xl mx-auto mb-10 leading-relaxed">
          Equip astronauts on the Bharatiya Antariksh Station with Abhay — the autonomous AI co-pilot engineered for zero-error microgravity payload operations.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-4 mb-16">
          <Link
            to="/dashboard"
            className="inline-flex items-center justify-center gap-3 rounded-xl bg-primary px-8 py-4 font-bold text-white shadow-lg transition hover:bg-[#003366] hover:shadow-xl active:scale-95"
          >
            <Play className="h-5 w-5 fill-current" />
            <span>Launch Mission Control &rarr;</span>
          </Link>

          <a
            href="#architecture"
            className="inline-flex items-center justify-center gap-3 rounded-xl border-2 border-primary bg-white px-8 py-4 font-bold text-primary transition hover:bg-blue-50 active:scale-95"
          >
            <FileText className="h-5 w-5" />
            <span>Explore Technical Architecture</span>
          </a>
        </div>

        {/* 4 Trust Badges matching Sahayak bottom row */}
        <div className="pt-12 border-t border-slate-200 grid grid-cols-2 md:grid-cols-4 gap-6 text-slate-600 text-sm font-semibold">
          <div className="flex items-center justify-center gap-2">
            <Shield className="w-5 h-5 text-emerald-500" />
            <span>ISRO PS 26174</span>
          </div>

          <div className="flex items-center justify-center gap-2">
            <Cpu className="w-5 h-5 text-primary" />
            <span>100% Offline Edge CPU</span>
          </div>

          <div className="flex items-center justify-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-cyan-600" />
            <span>Zero Cloud Sockets</span>
          </div>

          <div className="flex items-center justify-center gap-2">
            <Globe className="w-5 h-5 text-indigo-600" />
            <span>Tamper-Evident SHA-256</span>
          </div>
        </div>

      </div>
    </section>
  );
}
