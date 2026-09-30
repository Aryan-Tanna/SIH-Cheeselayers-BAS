import { Link } from 'react-router-dom';
import { Rocket } from 'lucide-react';

export default function DownloadCard() {
  return (
    <section
      id="get-started"
      className="bg-blue-50 border border-blue-100 rounded-2xl p-8 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-6"
    >
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Rocket size={20} className="text-primary" />
          <h2 className="text-2xl font-bold text-gray-900">Ready to Deploy Abhay?</h2>
        </div>
        <p className="text-gray-600 max-w-md">
          Set up the on-board co-pilot in minutes. Runs on a laptop CPU, air-gapped, with no
          external dependencies. Built for the Bharatiya Antariksh Station.
        </p>
        <div className="flex items-center gap-3 mt-4 text-sm text-gray-600">
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">✅ Windows .exe</span>
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">✅ Linux / macOS</span>
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">🔜 ARM (planned)</span>
        </div>
      </div>
      <Link
        to="/auth"
        className="bg-primary text-white px-8 py-3 rounded-full font-semibold hover:bg-primary/90 transition-colors whitespace-nowrap shadow-md"
      >
        Launch Mission Control →
      </Link>
    </section>
  );
}
