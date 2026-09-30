/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        white: '#ffffff',
        space: '#0a0e1a',        // deep space background
        navy: '#0d1530',         // card / surface
        primary: '#04409f',      // ISRO blue — primary actions
        accent: '#06b6d4',       // cyan — highlights / glows
        success: '#22c55e',      // step-done green
        warn: '#f59e0b',         // alert amber
        danger: '#ef4444',       // violation red
        muted: '#94a3b8',        // secondary text
        surface: '#111827',      // elevated card
        border: '#1e293b',       // subtle borders
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-12px)' },
        },
      },
    },
  },
  plugins: [],
};

