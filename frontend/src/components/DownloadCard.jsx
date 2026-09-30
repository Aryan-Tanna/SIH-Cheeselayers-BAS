import { Download, Rocket } from 'lucide-react';
import { ZIP_DOWNLOAD_URL, RELEASES_URL } from '../lib/downloads.js';

export default function DownloadCard() {
  return (
    <section
      id="get-started"
      className="bg-blue-50 border border-blue-100 rounded-2xl p-8 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-6"
    >
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Rocket size={20} className="text-primary" />
          <h2 className="text-2xl font-bold text-gray-900">Ready to Deploy VYOM antariksh?</h2>
        </div>
        <p className="text-gray-600 max-w-md">
          Set up the on-board co-pilot in minutes. Runs on a laptop CPU, air-gapped, with no
          external dependencies. Built for the Bharatiya Antariksh Station.
        </p>
        <div className="flex items-center gap-3 mt-4 text-sm text-gray-600">
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">✅ Windows .exe (packaged in the zip)</span>
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">✅ Linux / macOS (from source)</span>
          <span className="bg-white border border-gray-200 rounded-full px-3 py-1">🔜 ARM (planned)</span>
        </div>
      </div>
      <div className="flex flex-col items-center sm:items-end gap-2 shrink-0">
        <a
          href={ZIP_DOWNLOAD_URL}
          className="inline-flex items-center gap-2 bg-primary text-white px-8 py-3 rounded-full font-semibold hover:bg-primary/90 transition-colors whitespace-nowrap shadow-md"
        >
          <Download size={18} />
          Download ZIP (~325 MB)
        </a>
        <a
          href={RELEASES_URL}
          className="text-xs text-gray-500 hover:text-primary underline underline-offset-2"
        >
          Browse all releases
        </a>
      </div>
    </section>
  );
}
