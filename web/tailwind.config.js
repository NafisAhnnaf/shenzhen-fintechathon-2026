/** Lavender palette from design/prototype: one violet for action, blue for done, plum for stop. Old token names kept. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F6F5FF",
        surface: "#FFFFFF",
        sunk: "#EEECFF",
        ink: "#1E1B4B",
        body: "#4A4775",
        muted: "#6B6799",
        faint: "#8F8BB5",
        rule: "#DAD6FB",
        ledger: { DEFAULT: "#4B3BD6", soft: "#E4E0FF" },
        done: { DEFAULT: "#1F4CB8", soft: "#DCE8FF" },
        ochre: { DEFAULT: "#3C2EB8", soft: "#E4E0FF" },
        oxblood: { DEFAULT: "#7A2E9E", soft: "#F1E4FB" },
      },
      fontFamily: {
        sans: ['"Nunito Sans"', "Segoe UI", "system-ui", "sans-serif"],
        display: ["Fredoka", '"Trebuchet MS"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        xs: ["12px", "16px"],
        sm: ["14px", "20px"],
        base: ["16px", "24px"],
        lg: ["18px", "26px"],
        xl: ["22px", "28px"],
        "2xl": ["28px", "34px"],
        "3xl": ["40px", "44px"],
      },
      borderRadius: { DEFAULT: "10px", sm: "6px", lg: "16px" },
    },
  },
  plugins: [],
};
