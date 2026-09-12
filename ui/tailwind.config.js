/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // No webfont: the console must work with the network down, which is also when an
        // operator most needs it.
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      colors: {
        // Graphite with real blue in it — a machine housing, not a tinted black.
        ink: {
          950: "#0b1015", 900: "#0f151b", 850: "#131b22", 800: "#161e26",
          700: "#1e2833", 600: "#243039", 500: "#33424e", 400: "#5c6f7c",
          300: "#7d8f9a", 200: "#aebcc4", 100: "#dfe7ea",
        },
        // Sodium lamp. Attention only — never decoration, never a button fill.
        attention: { DEFAULT: "#f2a71b", 300: "#ffc75a", 600: "#c9860a" },
        // Retained name so existing call sites keep compiling; it is the same lamp.
        accent: { DEFAULT: "#f2a71b", 300: "#ffc75a", 600: "#c9860a" },
      },
      borderRadius: { panel: "4px", port: "6px" },
      spacing: { band: "34px", rail: "56px" },
    },
  },
  plugins: [],
};
