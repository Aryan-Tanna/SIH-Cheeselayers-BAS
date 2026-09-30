import { useEffect, useState, useCallback } from 'react';
import { ChevronLeft, ChevronRight, Pause, Play } from 'lucide-react';

const slides = [
  {
    headline: 'Zero Network. Full Intelligence.',
    subtext:
      'Abhay runs the entire detection-to-alert pipeline on a laptop CPU — air-gapped, offline, and ready for the Bharatiya Antariksh Station.',
    emoji: '🛸',
  },
  {
    headline: 'Deterministic. Never Hallucinates.',
    subtext:
      'Vision identifies objects. The constraint engine decides. No neural network in the alert path — same input always gives the same output.',
    emoji: '🔒',
  },
  {
    headline: '3-Layer Object Detection',
    subtext:
      'YOLOv8n-OBB + ArUco rack mapping + MediaPipe hand skeleton. Trained on 1,032 hand-labelled frames. mAP50 0.89 on held-out sessions.',
    emoji: '👁️',
  },
  {
    headline: 'Mission Control on Earth',
    subtext:
      'Store-and-forward log verified line by line. One JPEG per step attested in the hash chain. 486 KB vs 3.6 MB of raw video.',
    emoji: '📡',
  },
];

const AUTO_ADVANCE_MS = 5500;

export default function HeroCarousel() {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  const next = useCallback(() => setIndex((i) => (i + 1) % slides.length), []);
  const prev = useCallback(() => setIndex((i) => (i - 1 + slides.length) % slides.length), []);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(next, AUTO_ADVANCE_MS);
    return () => clearInterval(id);
  }, [playing, next]);

  const { headline, subtext, emoji } = slides[index];

  return (
    <div className="max-w-7xl mx-auto px-4 pt-4 pb-16">
      <div className="relative bg-gradient-to-br from-primary to-blue-500 rounded-3xl shadow-lg overflow-hidden">
        <div className="flex flex-col md:flex-row items-center gap-6 px-8 py-14 md:px-16 min-h-[260px]">
          <div className="text-8xl animate-float shrink-0">{emoji}</div>
          <div>
            <h2 className="text-2xl sm:text-3xl font-bold text-white mb-3">{headline}</h2>
            <p className="text-white/85 text-base max-w-xl leading-relaxed">{subtext}</p>
          </div>
        </div>

        <button type="button" onClick={prev} aria-label="Previous slide"
          className="absolute left-3 top-1/2 -translate-y-1/2 bg-white/20 hover:bg-white/30 text-white rounded-full p-2 transition-colors">
          <ChevronLeft size={20} />
        </button>
        <button type="button" onClick={next} aria-label="Next slide"
          className="absolute right-3 top-1/2 -translate-y-1/2 bg-white/20 hover:bg-white/30 text-white rounded-full p-2 transition-colors">
          <ChevronRight size={20} />
        </button>
        <button type="button" onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? 'Pause carousel' : 'Play carousel'}
          className="absolute bottom-4 right-4 bg-white/20 hover:bg-white/30 text-white rounded-full p-2 transition-colors">
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>

        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2">
          {slides.map((s, i) => (
            <button key={s.headline} type="button" onClick={() => setIndex(i)}
              aria-label={`Go to slide ${i + 1}`} aria-current={i === index}
              className={`rounded-full transition-all ${i === index ? 'w-6 h-2 bg-white' : 'w-2 h-2 bg-white/50 hover:bg-white/75'}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
