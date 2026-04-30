/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "#0a0a0f",
        card: "#12121a",
        "card-hover": "#1a1a28",
        border: "#1e1e2e",
        "border-light": "#2a2a3e",
        bullish: "#22c55e",
        bearish: "#ef4444",
        warning: "#f59e0b",
        accent: "#3b82f6",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};
