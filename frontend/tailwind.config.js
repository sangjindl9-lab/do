/** 그래파이트 중립색 + 계측기 청록 단일 강조색. 간격은 4px 격자. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#fafafa", card: "#ffffff", raised: "#f4f4f5", line: "rgba(23,23,23,0.09)",
        ink: "#171717", sub: "#525252", mute: "#737373",
        accent: { DEFAULT: "#0f766e", soft: "#e6f2f0", dark: "#0b5a54" },
        ok: "#15803d", bad: "#dc2626", warn: "#b45309",
        rack: { bg: "#0f0f10", cell: "#19191b", line: "rgba(237,237,237,0.09)", text: "#a1a1a6" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans KR"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: { ctl: "8px", card: "12px", panel: "16px" },
      boxShadow: { sm2: "0 1px 2px rgba(0,0,0,0.05)", float: "0 8px 24px rgba(0,0,0,0.06)" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
};
