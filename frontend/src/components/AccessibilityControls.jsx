import { useState } from 'react';

export default function AccessibilityControls() {
  const [lang, setLang] = useState('EN');

  return (
    <div className="flex items-center gap-3 text-sm text-gray-600">
      <div className="flex items-center gap-1" aria-label="Text size">
        <button className="px-1.5 font-semibold hover:text-primary" aria-label="Increase text size">A+</button>
        <button className="px-1.5 hover:text-primary" aria-label="Default text size">A</button>
        <button className="px-1.5 text-xs hover:text-primary" aria-label="Decrease text size">A-</button>
      </div>
      <select
        value={lang}
        onChange={(e) => setLang(e.target.value)}
        className="border border-gray-300 rounded px-1.5 py-0.5 text-sm bg-white text-gray-700"
        aria-label="Select language"
      >
        <option value="EN">English</option>
        <option value="HI">हिन्दी</option>
      </select>
    </div>
  );
}
