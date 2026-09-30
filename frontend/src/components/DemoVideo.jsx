import { useRef, useState } from 'react';
import { Play, Pause, Volume2, VolumeX, Maximize, Upload } from 'lucide-react';

/**
 * ──────────────────────────────────────────────
 *  UPLOAD YOUR VIDEO  (one step)
 * ──────────────────────────────────────────────
 *  1. Drop your video file into:
 *       frontend/src/assets/demo-video.mp4
 *  2. Refresh the browser — the player appears.
 *
 *  Supported: .mp4  .webm  .mov
 *  If the file is not present, a placeholder is shown.
 * ──────────────────────────────────────────────
 */
const VIDEO_FILE = '/src/assets/demo-video.mp4'; // adjust filename if needed

export default function DemoVideo() {
  const videoRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [hasError, setHasError] = useState(false);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); }
    else { v.pause(); setPlaying(false); }
  };

  const toggleMute = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
  };

  const fullscreen = () => videoRef.current?.requestFullscreen?.();

  return (
    <section id="demo-video-local" className="bg-white border-t border-gray-100">
      <div className="max-w-5xl mx-auto px-4 py-20">
        <div className="text-center mb-10">
          <span className="inline-block bg-primary text-white text-xs font-bold px-4 py-1.5 rounded-full uppercase tracking-widest mb-4">
            Live Demo
          </span>
          <h2 className="text-3xl font-bold text-gray-900 mb-3">See Abhay in Action</h2>
          <p className="text-gray-500 max-w-xl mx-auto">
            Watch the co-pilot guide an astronaut through the BAS Glovebox experiment —
            detecting every step, alerting on violations, all on a laptop CPU with no internet.
          </p>
        </div>

        {hasError ? (
          /* ── Placeholder shown until video is uploaded ── */
          <div className="relative bg-gray-50 border-2 border-dashed border-primary/30 rounded-2xl overflow-hidden aspect-video flex flex-col items-center justify-center gap-4">
            <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center">
              <Upload size={32} className="text-primary" />
            </div>
            <div className="text-center px-6">
              <p className="font-semibold text-gray-800 mb-1">Video coming soon</p>
              <p className="text-sm text-gray-500">
                Drop <code className="bg-gray-100 px-1 rounded text-xs">demo-video.mp4</code> into{' '}
                <code className="bg-gray-100 px-1 rounded text-xs">frontend/src/assets/</code> to activate this player.
              </p>
            </div>
          </div>
        ) : (
          /* ── Video player ── */
          <div className="relative bg-gray-900 rounded-2xl overflow-hidden shadow-2xl group">
            <video
              ref={videoRef}
              src={VIDEO_FILE}
              className="w-full aspect-video object-cover"
              onEnded={() => setPlaying(false)}
              onError={() => setHasError(true)}
              playsInline
            />

            {/* Hover overlay controls */}
            <div className="absolute inset-0 bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
              <button
                onClick={toggle}
                className="w-16 h-16 rounded-full bg-white/90 hover:bg-white flex items-center justify-center shadow-lg transition-colors"
                aria-label={playing ? 'Pause video' : 'Play video'}
              >
                {playing
                  ? <Pause size={26} className="text-primary" />
                  : <Play size={26} className="text-primary ml-1" fill="currentColor" />
                }
              </button>
            </div>

            {/* Bottom bar */}
            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-5 py-4 flex items-center justify-between opacity-0 group-hover:opacity-100 transition-opacity">
              <span className="text-white text-sm font-semibold">Abhay — BAS Glovebox Demo</span>
              <div className="flex items-center gap-3">
                <button onClick={toggleMute} aria-label="Toggle mute" className="text-white/80 hover:text-white">
                  {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
                </button>
                <button onClick={fullscreen} aria-label="Fullscreen" className="text-white/80 hover:text-white">
                  <Maximize size={18} />
                </button>
              </div>
            </div>

            {/* Initial big play button */}
            {!playing && (
              <button onClick={toggle} aria-label="Play demo video"
                className="absolute inset-0 flex items-center justify-center">
                <span className="w-20 h-20 rounded-full bg-white/90 hover:bg-white flex items-center justify-center shadow-xl transition-colors">
                  <Play size={32} className="text-primary ml-1" fill="currentColor" />
                </span>
              </button>
            )}
          </div>
        )}

        <p className="text-center text-xs text-gray-400 mt-4">
          Recorded on a standard laptop CPU &mdash; no GPU, no internet connection required.
        </p>
      </div>
    </section>
  );
}
