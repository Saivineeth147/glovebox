/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
      colors: {
        ink: { 950: "#0a0b0e", 900: "#101217", 850: "#14171d", 800: "#1a1e26", 700: "#252a34", 600: "#343a47", 400: "#6b7385", 300: "#9aa3b5", 200: "#c7cdd9", 100: "#eef0f4" },
        accent: { DEFAULT: "#7c6cff", 600: "#6a5aef", 300: "#a99dff" },
      },
      boxShadow: { panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 40px -24px rgba(0,0,0,0.8)" },
    },
  },
  plugins: [],
};
