/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Kenya MAM brand colours
        navy:   { DEFAULT: '#0B1F3A', 700: '#0B1F3A', 600: '#1B3A5C', 400: '#2C5282' },
        gold:   { DEFAULT: '#F5D98C', 600: '#C9920A', 400: '#F5D98C' },
        chirps: '#1E6B45',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
