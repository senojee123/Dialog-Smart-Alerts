/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand:   { DEFAULT: '#DA1F26', hover: '#B81A20' },
        maroon:  '#7B1E28',
        orange:  '#F2841C',
        sev: {
          critical: '#D92D20',
          high:     '#F2841C',
          medium:   '#F5B70A',
          low:      '#12B76A',
        },
        surface: { DEFAULT: '#F7F8FA', alt: '#F2F4F7' },
        ink:     { DEFAULT: '#1A1A1A', muted: '#667085' },
        line:    '#E4E7EC',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        pulse_sev: {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0.5' },
        },
      },
      animation: {
        'pulse-sev': 'pulse_sev 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
