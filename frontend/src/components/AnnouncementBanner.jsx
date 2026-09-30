import { Satellite } from 'lucide-react';

export default function AnnouncementBanner() {
  return (
    <a
      href="#how-it-works"
      className="block bg-gradient-to-r from-primary to-accent text-white text-center py-2.5 text-sm font-medium hover:opacity-90 transition-opacity"
    >
      <span className="inline-flex items-center gap-2">
        <Satellite size={14} />
        SIH 2026 · PS 26174 — AI Human Activity Recognition for On-board BAS Experiments
        <span aria-hidden="true">→</span>
      </span>
    </a>
  );
}
