import { Link } from 'react-router-dom';
import Logo from './Logo.jsx';
import { ArrowUp } from 'lucide-react';

export default function Footer() {
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <footer className="bg-slate-900 text-slate-400 border-t border-slate-800">
      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 pb-8 border-b border-slate-800">
          
          <div className="flex items-center gap-3">
            <div className="bg-white rounded-lg p-1.5">
              <Logo />
            </div>
          </div>

          <nav className="flex flex-wrap items-center justify-center gap-6 text-sm font-medium">
            <a href="#" className="hover:text-white transition-colors">Home</a>
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#challenge" className="hover:text-white transition-colors">The Challenge</a>
            <a href="#scenarios" className="hover:text-white transition-colors">Scenarios</a>
            <a href="#architecture" className="hover:text-white transition-colors">Architecture</a>
            <a href="#metrics" className="hover:text-white transition-colors">Metrics</a>
            <Link to="/dashboard" className="text-cyan-400 hover:text-cyan-300 font-semibold transition-colors">
              Mission Control
            </Link>
          </nav>

          <button
            onClick={scrollToTop}
            className="p-2.5 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors shadow-sm"
            aria-label="Scroll to top"
          >
            <ArrowUp className="w-4 h-4" />
          </button>
        </div>

        <div className="pt-8 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-4">
          <p>
            &copy; {new Date().getFullYear()} Abhay &mdash; AI Human Activity Recognition for On-board BAS Experiments. Built by Team <strong>Cheeselayers</strong> for Smart India Hackathon (SIH 2026, PS 26174) &middot; ISRO / Department of Space.
          </p>
          <p className="shrink-0 font-medium">
            All rights reserved. Verified on-board CPU offline.
          </p>
        </div>
      </div>
    </footer>
  );
}
