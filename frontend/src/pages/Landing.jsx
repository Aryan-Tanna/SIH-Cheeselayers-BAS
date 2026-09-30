import LandingHeader from '../components/LandingHeader.jsx';
import ShowcaseRibbon from '../components/ShowcaseRibbon.jsx';
import Hero from '../components/Hero.jsx';
import PowerfulFeatures from '../components/PowerfulFeatures.jsx';
import ChallengeSolve from '../components/ChallengeSolve.jsx';
import OperationalScenarios from '../components/OperationalScenarios.jsx';
import MissionMetrics from '../components/MissionMetrics.jsx';
import Architecture from '../components/Architecture.jsx';
import ExperimentProtocol from '../components/ExperimentProtocol.jsx';
import EarthDownlink from '../components/EarthDownlink.jsx';
import DemoVideo from '../components/DemoVideo.jsx';
import DeployCTA from '../components/DeployCTA.jsx';
import Footer from '../components/Footer.jsx';

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col bg-white font-sans antialiased text-slate-900 selection:bg-blue-100 selection:text-primary">
      {/* 1 — Fixed Header Navigation (h-16) */}
      <LandingHeader />

      {/* Main container with pt-16 to offset fixed header */}
      <main className="flex-1 pt-16">
        {/* 2 — Sticky Showcase Demo Bar (sticks at top-16 under navbar) */}
        <ShowcaseRibbon />

        {/* 3 — Sahayak-style Split Grid Hero Section */}
        <Hero />

        {/* 4 — Powerful AI Features (Carousel with ambient glow) */}
        <PowerfulFeatures />

        {/* 5 — The Challenge We Solve (Problems vs Solutions split cards in dark theme) */}
        <ChallengeSolve />

        {/* 6 — Transforming Space Station Operations (6 Scenario Cards Grid) */}
        <OperationalScenarios />

        {/* 7 — Validated for BAS / Mission Metrics (Blue section) */}
        <MissionMetrics />

        {/* 8 — Three-Layer System Architecture */}
        <Architecture />

        {/* 9 — The 12-Step BAS Experiment Protocol & Safety Invariants */}
        <ExperimentProtocol />

        {/* 10 — Earth Downlink & Bandwidth Efficiency (486 KB vs 3.6 MB) */}
        <EarthDownlink />

        {/* 11 — Local Demo Video Upload Player (drop demo-video.mp4 into assets) */}
        <DemoVideo />

        {/* 12 — Pre-Footer Deploy CTA Banner */}
        <DeployCTA />
      </main>

      {/* 13 — Footer */}
      <Footer />
    </div>
  );
}
