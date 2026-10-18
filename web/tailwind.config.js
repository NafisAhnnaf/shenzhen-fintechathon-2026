/** Ledger palette: cool paper, green-black ink, one ledger green for action, ochre and oxblood for states. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F8F9FA",
        surface: "#FFFFFF",
        ink: "#0F172A",
        muted: "#475569",
        faint: "#94A3B8",
        rule: "#E2E8F0",
        "rule-sub": "#EDF2F7",
        ledger: { DEFAULT: "#0F766E", hover: "#059669", mint: "#10B981", soft: "#ECFDF5" },
        ochre: { DEFAULT: "#D97706", hover: "#B45309", soft: "#FFFBEB" },
        oxblood: { DEFAULT: "#DC2626", dark: "#991B1B", soft: "#FEF2F2" },
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        // A modular scale on 15px body (ratio about 1.2)
        xs: ["12px", "16px"],
        sm: ["13px", "18px"],
        base: ["15px", "22px"],
        lg: ["18px", "24px"],
        xl: ["22px", "28px"],
        "2xl": ["28px", "34px"],
        "3xl": ["40px", "44px"],
      },
      borderRadius: { DEFAULT: "8px", sm: "4px", md: "8px", lg: "12px", xl: "16px", "2xl": "20px", "3xl": "24px" },
    },
  },
  plugins: [],
};
