import { Link } from 'react-router-dom';
import Logo from './Logo.jsx';
import AccessibilityControls from './AccessibilityControls.jsx';

const navLinks = [
  { to: '/', label: 'Home' },
  { href: '#how-it-works', label: 'How It Works' },
  { href: '#demo-video-local', label: 'Demo Video' },
  { href: '#architecture', label: 'Architecture' },
  { href: '#protocol', label: 'Protocol' },
  { href: '#results', label: 'Results' },
  { href: '#downlink', label: 'Downlink' },
];

export default function LandingHeader() {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
        <Logo />
        <nav className="hidden min-[1400px]:flex items-center gap-6 text-sm font-medium text-gray-600">
          {navLinks.map((link) =>
            link.to ? (
              <Link key={link.label} to={link.to} className="hover:text-primary transition-colors">
                {link.label}
              </Link>
            ) : (
              <a key={link.label} href={link.href} className="hover:text-primary transition-colors">
                {link.label}
              </a>
            )
          )}
          <Link
            to="/dashboard"
            className="border border-primary text-primary px-3 py-1.5 rounded-md text-sm font-medium hover:bg-blue-50 transition-colors"
          >
            Mission Control
          </Link>
        </nav>
        <div className="flex items-center gap-3 flex-wrap">
          <AccessibilityControls />
          <Link
            to="/dashboard"
            className="bg-primary text-white px-5 py-2 rounded-full font-medium text-sm hover:opacity-90 transition-opacity shadow-md"
          >
            Get Started
          </Link>
        </div>
      </div>
    </header>
  );
}
