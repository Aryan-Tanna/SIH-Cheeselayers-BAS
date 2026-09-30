import { Play, ChevronDown } from 'lucide-react';

export default function ShowcaseRibbon() {
  return (
    <a
      href="#demo-video"
      className="sticky top-16 z-40 flex w-full flex-wrap items-center justify-center gap-2 border-b border-blue-400/30 bg-gradient-to-r from-[#002d54] via-[#004079] to-[#005a9e] px-4 py-3 text-center text-sm font-semibold text-white shadow-md transition-all hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white sm:gap-3 sm:text-base cursor-pointer"
    >
      <Play className="h-4 w-4 shrink-0 fill-current opacity-95 text-cyan-300" />
      <span>Watch the showcase demo — see VYOM antariksh on-board BAS Glovebox in action</span>
      <ChevronDown className="h-4 w-4 shrink-0 opacity-90 animate-bounce" />
    </a>
  );
}
