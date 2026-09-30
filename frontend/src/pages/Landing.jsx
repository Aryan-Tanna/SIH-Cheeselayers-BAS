import LandingHeader from '../components/LandingHeader.jsx';
import AnnouncementBanner from '../components/AnnouncementBanner.jsx';
import Hero from '../components/Hero.jsx';
import HeroCarousel from '../components/HeroCarousel.jsx';
import HowItWorks from '../components/HowItWorks.jsx';
import ProblemSolution from '../components/ProblemSolution.jsx';
import TrustStrip from '../components/TrustStrip.jsx';
import DownloadCard from '../components/DownloadCard.jsx';
import Footer from '../components/Footer.jsx';

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <LandingHeader />
      <AnnouncementBanner />
      <main className="flex-1">
        <Hero />
        <section className="bg-white border-t border-gray-100">
          <h2 className="text-center text-xs font-bold text-gray-400 uppercase tracking-widest pt-10 mb-0">
            Project Highlights
          </h2>
          <HeroCarousel />
        </section>
        <HowItWorks />
        <ProblemSolution />
        <TrustStrip />
        <section className="bg-white">
          <div className="max-w-7xl mx-auto px-4 py-16">
            <DownloadCard />
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
