export default function Footer() {
  return (
    <footer className="bg-gray-900 text-gray-400 text-sm">
      <div className="max-w-7xl mx-auto px-4 py-8 flex flex-col sm:flex-row justify-between gap-4">
        <div>
          <p className="text-white font-semibold mb-1">Abhay</p>
          <p className="text-gray-400 text-xs">
            AI Human Activity Recognition for On-board BAS Experiments
          </p>
          <p className="mt-2 text-xs">
            &copy; {new Date().getFullYear()} Team Cheeselayers &mdash; Smart India Hackathon 2026 &middot; PS 26174
          </p>
          <p className="text-xs">Built for ISRO / Department of Space</p>
        </div>
        <nav className="flex gap-6 items-start">
          <a href="#how-it-works" className="hover:text-white transition-colors">How It Works</a>
          <a href="#capabilities" className="hover:text-white transition-colors">Capabilities</a>
          <a href="#get-started" className="hover:text-white transition-colors">Get Started</a>
        </nav>
      </div>
    </footer>
  );
}
