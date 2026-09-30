import { Link, useNavigate } from 'react-router-dom';
import Logo from './Logo.jsx';

export default function DashboardHeader() {
  const navigate = useNavigate();

  const handleLogout = () => {
    console.log('Mock logout');
    navigate('/');
  };

  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4 flex-wrap">
        <Logo />
        <nav className="flex items-center gap-6 text-sm font-medium text-gray-600 flex-wrap">
          <Link to="/dashboard" className="text-primary font-semibold">
            Mission Control
          </Link>
          <a href="#capabilities" className="hover:text-primary transition-colors">Capabilities</a>
          <a href="#get-started" className="hover:text-primary transition-colors">Get Started</a>
          <button onClick={handleLogout} className="hover:text-primary transition-colors">Logout</button>
        </nav>
      </div>
    </header>
  );
}
