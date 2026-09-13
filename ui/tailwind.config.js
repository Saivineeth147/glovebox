/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // No webfont: the console has to work with the network down, which is also when an
        // operator most needs it. The system stack is set deliberately, not by default.
        sans: [
          "ui-sans-serif", "-apple-system", "BlinkMacSystemFont", "Segoe UI Variable",
          "Segoe UI", "Inter", "system-ui", "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "JetBrains Mono", "monospace"],
      },
      colors: {
        // Near-black with a trace of warmth, so the surface reads as material rather than void.
        ink: {
          980: "#0a0b0d", 950: "#0d0e11", 900: "#111216", 850: "#16181d",
          800: "#1b1e24", 700: "#23262e", 600: "#2e323b", 500: "#414651",
          400: "#6b7180", 300: "#9aa0ac", 200: "#c9cdd6", 100: "#ecedf1",
        },
        // Sodium lamp: attention only, never decoration.
        attention: { DEFAULT: "#f2a71b", 300: "#ffc75a", 600: "#c9860a" },
        accent: { DEFAULT: "#f2a71b", 300: "#ffc75a", 600: "#c9860a" },
      },
      borderRadius: { panel: "12px", port: "10px", pill: "999px" },
      spacing: { band: "52px", rail: "64px" },
      boxShadow: {
        // One soft lift, used only where something genuinely sits above the page.
        lift: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 30px -12px rgba(0,0,0,0.9)",
      },
      letterSpacing: { display: "-0.021em" },
    },
  },
  plugins: [],
};
