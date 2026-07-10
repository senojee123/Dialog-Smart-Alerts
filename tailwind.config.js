/** @type {import('tailwindcss').Config} */

// ── Elevated Dialog — single design-token source of truth ──────────────────────
// Everything visual derives from here. CSS variables in src/theme/tokens.css are
// generated to mirror these for the few non-Tailwind contexts (Leaflet icons).
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Brand chrome — reserved for primary actions + active nav + logo band.
        brand:   { DEFAULT: '#DA1F26', hover: '#B81A20', subtle: '#FDECEC' },
        maroon:  { DEFAULT: '#7B1E28', hover: '#641821' },
        orange:  '#F2841C',

        // Severity — a hue-spread scale kept separate from brand chrome so
        // criticality is legible at a glance (always paired with a label + icon).
        sev: {
          critical: '#D92D20',
          high:     '#F2841C',
          medium:   '#F5B70A',
          low:      '#12B76A',
        },

        // Notification delivery states.
        state: {
          dispatched: '#667085',
          delivered:  '#12B76A',
          failed:     '#D92D20',
        },

        // Hardware / actuator states.
        hw: {
          on:      '#12B76A',
          off:     '#98A2B3',
          offline: '#D92D20',
          error:   '#D92D20',
          manual:  '#7B1E28',
        },

        // Neutral system. `surface` is the page canvas, white is the elevated card.
        surface: {
          DEFAULT: '#F7F8FA',  // page canvas
          alt:     '#F2F4F7',  // nested panels, table headers
          sunken:  '#EDEFF3',  // wells, track backgrounds
        },
        ink:  { DEFAULT: '#1A1A1A', muted: '#667085', subtle: '#98A2B3' },
        line: { DEFAULT: '#E4E7EC', strong: '#D0D5DD' },
      },

      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },

      borderRadius: {
        // Spec: 4px inputs · 6px chips · 8px cards.
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },

      boxShadow: {
        // Flat by default; elevation only on cards, drawers, modals, popovers.
        card:    '0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)',
        drawer:  '-8px 0 24px rgba(16,24,40,0.10)',
        modal:   '0 12px 32px rgba(16,24,40,0.18)',
        popover: '0 4px 12px rgba(16,24,40,0.12)',
      },

      zIndex: {
        nav:     '30',
        sticky:  '40',
        drawer:  '50',
        modal:   '60',
        toast:   '70',
      },

      keyframes: {
        pulse_sev:  { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.5' } },
        slide_in:   { from: { opacity: '0', transform: 'translateY(-6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        fade_in:    { from: { opacity: '0' }, to: { opacity: '1' } },
        flash:      { '0%': { backgroundColor: 'rgba(218,31,38,0.10)' }, '100%': { backgroundColor: 'transparent' } },
      },
      animation: {
        'pulse-sev': 'pulse_sev 1.5s ease-in-out infinite',
        'slide-in':  'slide_in 0.18s ease-out',
        'fade-in':   'fade_in 0.15s ease-out',
        'flash':     'flash 1.2s ease-out',
      },
    },
  },
  plugins: [],
}
