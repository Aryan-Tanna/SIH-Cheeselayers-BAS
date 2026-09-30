const badges = [
  'Offline · No Internet Required',
  'CPU-Only · No GPU',
  'ISRO · Department of Space',
  'Tamper-Evident Log',
  'Voice Alerts via Piper TTS',
];

export default function TrustStrip() {
  return (
    <section className="bg-gradient-to-r from-primary/80 to-accent/70">
      <div className="max-w-7xl mx-auto px-4 py-8 flex flex-wrap items-center justify-center gap-4">
        {badges.map((badge) => (
          <span
            key={badge}
            className="bg-white/10 text-white border border-white/25 rounded-full px-5 py-2 text-sm font-medium backdrop-blur-sm"
          >
            {badge}
          </span>
        ))}
      </div>
    </section>
  );
}
