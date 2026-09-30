import DashboardHeader from '../components/DashboardHeader.jsx';
import DownloadCard from '../components/DownloadCard.jsx';
import FeatureGrid from '../components/FeatureGrid.jsx';
import StatsStrip from '../components/StatsStrip.jsx';
import Footer from '../components/Footer.jsx';

export default function Dashboard() {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <DashboardHeader />
      <main className="flex-1 max-w-7xl mx-auto px-4 py-10 w-full space-y-10">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 mb-1">Mission Control</h1>
          <p className="text-gray-500 text-sm">
            Abhay — AI Human Activity Recognition for On-board BAS Experiments
          </p>
        </div>
        <StatsStrip />
        <DownloadCard />
        <FeatureGrid />
      </main>
      <Footer />
    </div>
  );
}
