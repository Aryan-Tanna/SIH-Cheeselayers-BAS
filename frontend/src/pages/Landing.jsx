import LandingHeader from '../components/LandingHeader.jsx';
import AnnouncementBanner from '../components/AnnouncementBanner.jsx';
import Hero from '../components/Hero.jsx';
import HeroCarousel from '../components/HeroCarousel.jsx';
import HowItWorks from '../components/HowItWorks.jsx';
import DemoVideo from '../components/DemoVideo.jsx';
import Architecture from '../components/Architecture.jsx';
import ExperimentProtocol from '../components/ExperimentProtocol.jsx';
import ProblemSolution from '../components/ProblemSolution.jsx';
import ResultsMetrics from '../components/ResultsMetrics.jsx';
import EarthDownlink from '../components/EarthDownlink.jsx';
import TrustStrip from '../components/TrustStrip.jsx';
import DownloadCard from '../components/DownloadCard.jsx';
import Footer from '../components/Footer.jsx';

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <LandingHeader />
      <AnnouncementBanner />

      <main className="flex-1">
        {/* 1 — Hero + YouTube placeholder */}
        <Hero />

        {/* 2 — Project highlight carousel */}
        <section className="bg-white border-t border-gray-100">
          <h2 className="text-center text-xs font-bold text-gray-400 uppercase tracking-widest pt-10 mb-0">
            Project Highlights
          </h2>
          <HeroCarousel />
        </section>

        {/* 3 — How it works (4 pipeline steps) */}
        <HowItWorks />

        {/* 4 — Local demo video (drop your .mp4 into src/assets/) */}
        <DemoVideo />

        {/* 5 — System architecture */}
        <Architecture />

        {/* 6 — 12-step experiment protocol + safety rules */}
        <ExperimentProtocol />

        {/* 7 — Problem / Solution pairs */}
        <ProblemSolution />

        {/* 8 — Measured results & violation codes */}
        <ResultsMetrics />

        {/* 9 — Earth downlink & bandwidth comparison */}
        <EarthDownlink />

        {/* 10 — Trust badges */}
        <TrustStrip />

        {/* 11 — Deploy CTA */}
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
