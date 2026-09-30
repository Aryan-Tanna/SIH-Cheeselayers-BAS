import { useState } from 'react';
import { Link } from 'react-router-dom';
import Logo from './Logo.jsx';
import AccessibilityControls from './AccessibilityControls.jsx';
import { Menu, X, Terminal, ArrowRight, ShieldCheck } from 'lucide-react';

const navLinks = [
  { href: '#', label: 'Home', active: true },
  { href: '#features', label: 'Features' },
  { href: '#challenge', label: 'The Challenge' },
  { href: '#scenarios', label: 'Scenarios' },
  { href: '#architecture', label: 'Architecture' },
  { href: '#metrics', label: 'Metrics' },
];

export default function LandingHeader() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="bg-white shadow-md fixed top-0 left-0 w-full z-50">
      <div className="w-full px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          
          {/* Mobile menu trigger */}
          <div className="flex lg:hidden">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="inline-flex items-center justify-center p-2 rounded-md text-gray-700 hover:text-primary hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary"
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>

          {/* Logo with ISRO / Department of Space */}
          <div className="flex items-center space-x-3">
            <Link to="/" className="flex items-center">
              <Logo />
            </Link>
          </div>

          {/* Desktop Navigation Menu */}
          <nav className="hidden lg:flex lg:items-center lg:space-x-7" aria-label="Desktop Navigation Menu">
            {navLinks.map((item) => (
              <a
                key={item.label}
                href={item.href}
                className={`text-sm font-medium transition-colors ${
                  item.active
                    ? 'text-primary font-bold'
                    : 'text-gray-700 hover:text-primary'
                }`}
              >
                {item.label}
              </a>
            ))}

            {/* Special border button mirroring Sahayak's 'Document Chat' */}
            <Link
              to="/dashboard"
              className="text-sm font-semibold border-2 border-emerald-500 rounded-lg px-3 py-1.5 text-emerald-700 hover:bg-emerald-50 transition-all duration-200 flex items-center gap-1.5"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              Live Telemetry
            </Link>
          </nav>

          {/* Right Action Buttons */}
          <div className="flex items-center space-x-3">
            <div className="hidden sm:block">
              <AccessibilityControls />
            </div>

            <Link
              to="/dashboard"
              className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-all h-10 px-5 bg-primary hover:bg-[#003366] text-white shadow-md hover:shadow-lg active:scale-95"
            >
              <Terminal className="h-4 w-4" />
              <span>Mission Control</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

        </div>
      </div>

      {/* Mobile navigation drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-t border-gray-200 bg-white px-4 pt-3 pb-6 space-y-2 shadow-xl">
          {navLinks.map((item) => (
            <a
              key={item.label}
              href={item.href}
              onClick={() => setMobileMenuOpen(false)}
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 hover:text-primary hover:bg-blue-50"
            >
              {item.label}
            </a>
          ))}
          <Link
            to="/dashboard"
            onClick={() => setMobileMenuOpen(false)}
            className="flex items-center justify-between px-3 py-2 rounded-md text-base font-semibold text-emerald-700 bg-emerald-50"
          >
            <span>Live Mission Control</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </header>
  );
}
