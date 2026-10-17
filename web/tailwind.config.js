/** Ledger palette: cool paper, green-black ink, one ledger green for action, ochre and oxblood for states. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F5F6F3",
        surface: "#FFFFFF",
        ink: "#1D2421",
        muted: "#5F6B66",
        faint: "#8D9893",
        rule: "#DCE0DB",
        ledger: { DEFAULT: "#22573F", soft: "#E6EFE9" },
        ochre: { DEFAULT: "#9A6A16", soft: "#F5ECDC" },
        oxblood: { DEFAULT: "#8E2B2B", soft: "#F4E3E1" },
      },
      fontFamily: {
        sans: ['"Instrument Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
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
      borderRadius: { DEFAULT: "6px", sm: "4px" },
    },
  },
  plugins: [],
};
