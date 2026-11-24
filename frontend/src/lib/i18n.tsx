// 다국어: 한국어 문구를 키로 사용하고, 언어별 사전(en 등)에서 번역을 찾는다. 사전에 없으면 한국어로 표시한다.
// 일본어·중국어 등은 아래 DICTS에 사전을 추가하면 확장된다.
import { createContext, useContext, useState, type ReactNode } from "react";
import { en } from "./locale-en";

const DICTS: Record<string, Record<string, string>> = { en };
export const LOCALES = [{ code: "ko", name: "한국어" }, { code: "en", name: "English" }];
const Ctx = createContext<{ locale: string; setLocale: (l: string) => void; t: (s: string) => string }>({ locale: "ko", setLocale: () => {}, t: (s) => s });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, set] = useState(() => localStorage.getItem("gat.locale") || (navigator.language.startsWith("ko") ? "ko" : "en"));
  const setLocale = (l: string) => { localStorage.setItem("gat.locale", l); document.documentElement.lang = l; set(l); };
  const t = (s: string) => (locale === "ko" ? s : DICTS[locale]?.[s] ?? s);
  return <Ctx.Provider value={{ locale, setLocale, t }}>{children}</Ctx.Provider>;
}
export const useI18n = () => useContext(Ctx);

export const STATUS: Record<string, string> = {
  pending_payment: "결제 대기", paid: "결제 완료", waiting_devices: "기기 배정 대기", scheduled: "검사 예정", running: "검사 중",
  paused: "일시정지", completed: "완료", cancelled: "취소", refunded: "환불", payment_failed: "결제 실패",
  ready: "결제 준비", failed: "실패", partial_refunded: "부분 환불", passed: "성공", error: "수행 불가", not_run: "미수행", skipped: "건너뜀",
  queued: "대기", leased: "배정됨", succeeded: "완료", timeout: "타임아웃", idle: "대기 중", assigned: "배정 완료", testing: "검사 중",
  offline: "오프라인", online: "온라인", maintenance: "유지보수", disabled: "사용 중지", overheat: "과열", low_storage: "저장공간 부족",
  open: "접수", answered: "답변 완료", closed: "종료", pending: "등록 대기", revoked: "폐기", sent: "전송됨", done: "완료",
  expired: "만료", invited: "초대", joined: "참여", confirmed: "참여 확인", clean: "정상", quarantined: "격리",
  not_sent_no_smtp: "미발송(SMTP 미설정)", unread: "읽지 않음", read: "읽음", active: "활성", released: "해제", replaced: "대체됨",
};
export const TONE: Record<string, "ok" | "bad" | "warn" | "mute" | "accent"> = {
  passed: "ok", completed: "ok", paid: "ok", succeeded: "ok", idle: "ok", online: "ok", done: "ok", clean: "ok", sent: "ok", confirmed: "ok", answered: "ok",
  failed: "bad", error: "bad", payment_failed: "bad", timeout: "bad", overheat: "bad", quarantined: "bad", revoked: "bad",
  waiting_devices: "warn", pending_payment: "warn", low_storage: "warn", maintenance: "warn", paused: "warn", partial_refunded: "warn", not_sent_no_smtp: "warn", queued: "warn", open: "warn",
  running: "accent", testing: "accent", scheduled: "accent", assigned: "accent", leased: "accent",
};
