/** 흰 바탕 + 선명한 파랑 하나. 글꼴은 Pretendard, 간격은 4px 격자. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#f4f6f9", card: "#ffffff", raised: "#f2f4f7", line: "#e4e8ee",
        ink: "#191f28", sub: "#4e5968", mute: "#8b95a1",
        accent: { DEFAULT: "#1a63f5", soft: "#ecf3ff", dark: "#124fcf" },
        ok: { DEFAULT: "#0a9a5c", soft: "#e5f6ee" }, bad: { DEFAULT: "#e03e44", soft: "#fdecec" }, warn: { DEFAULT: "#c76a00", soft: "#fff3df" },
        rack: { bg: "#131a26", cell: "#1d2635", line: "rgba(226,232,240,0.12)", text: "#9aa6b8" },
      },
      fontFamily: {
        sans: ['"Pretendard Variable"', "Pretendard", "-apple-system", "BlinkMacSystemFont", "system-ui", '"Apple SD Gothic Neo"', '"Malgun Gothic"', "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: { ctl: "10px", card: "16px", panel: "20px" },
      boxShadow: { sm2: "0 1px 2px rgba(25,31,40,0.06)", float: "0 12px 32px rgba(25,31,40,0.10)", lift: "0 24px 60px rgba(26,99,245,0.14)" },
      transitionTimingFunction: { out: "cubic-bezier(0.22, 1, 0.36, 1)" },
    },
  },
  plugins: [],
};
