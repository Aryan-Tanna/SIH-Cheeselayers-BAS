import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import UtilityBar from '../components/UtilityBar.jsx';
import Logo from '../components/Logo.jsx';

export default function Auth() {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '', confirmPassword: '' });
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const isSignup = mode === 'signup';

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');
    if (!form.email || !form.password) { setError('Email and password are required.'); return; }
    if (isSignup) {
      if (!form.name) { setError('Name is required.'); return; }
      if (form.password !== form.confirmPassword) { setError('Passwords do not match.'); return; }
    }
    console.log(`Mock ${mode} submit:`, form);
    navigate('/dashboard');
  };

  const switchMode = (next) => { setMode(next); setError(''); };

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <UtilityBar />
      <div className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-md">
          <div className="flex justify-center mb-8">
            <Link to="/"><Logo /></Link>
          </div>

          <div className="bg-white border border-gray-200 rounded-2xl shadow-lg p-8">
            <div className="flex border border-gray-200 rounded-full p-1 mb-6 bg-gray-50">
              <button type="button" onClick={() => switchMode('login')}
                className={`flex-1 py-2 rounded-full text-sm font-semibold transition-colors ${
                  mode === 'login' ? 'bg-primary text-white' : 'text-gray-600 hover:text-gray-900'
                }`}>
                Login
              </button>
              <button type="button" onClick={() => switchMode('signup')}
                className={`flex-1 py-2 rounded-full text-sm font-semibold transition-colors ${
                  mode === 'signup' ? 'bg-primary text-white' : 'text-gray-600 hover:text-gray-900'
                }`}>
                Sign Up
              </button>
            </div>

            <h1 className="text-xl font-bold text-gray-900 mb-1">
              {isSignup ? 'Create your account' : 'Welcome back'}
            </h1>
            <p className="text-sm text-gray-500 mb-6">
              {isSignup
                ? 'Sign up to access Mission Control for Abhay.'
                : 'Log in to access your Mission Control dashboard.'}
            </p>

            {error && (
              <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              {isSignup && (
                <div>
                  <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                  <input id="name" name="name" type="text" value={form.name} onChange={handleChange}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    placeholder="Full name" />
                </div>
              )}
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input id="email" name="email" type="email" value={form.email} onChange={handleChange}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="you@isro.gov.in" />
              </div>
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input id="password" name="password" type="password" value={form.password} onChange={handleChange}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="••••••••" />
              </div>
              {isSignup && (
                <div>
                  <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-1">Confirm Password</label>
                  <input id="confirmPassword" name="confirmPassword" type="password" value={form.confirmPassword} onChange={handleChange}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    placeholder="••••••••" />
                </div>
              )}
              <button type="submit"
                className="w-full bg-primary text-white py-2.5 rounded-lg font-semibold hover:bg-primary/90 transition-colors shadow-md">
                {isSignup ? 'Create Account' : 'Log In to Mission Control'}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
