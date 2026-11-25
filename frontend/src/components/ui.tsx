import { X } from "lucide-react";
import { useCallback, useEffect, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { STATUS, TONE, useI18n } from "../lib/i18n";

const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");
export { cx };

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" | "lg" };
export function Button({ variant = "secondary", size = "md", className, ...rest }: BtnProps) {
  const v = { primary: "bg-accent text-white hover:bg-accent-dark", secondary: "bg-raised text-ink hover:bg-[#e6eaef]",
    ghost: "text-sub hover:bg-raised hover:text-ink", danger: "bg-bad-soft text-bad hover:bg-[#fbdcdc]" }[variant];
  const s = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-[14px]", lg: "h-12 px-6 text-[16px]" }[size];
  return <button {...rest} className={cx("inline-flex items-center justify-center gap-2 rounded-ctl font-semibold transition-colors duration-150 ease-out disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap", v, s, className)} />;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  const { t } = useI18n();
  return <label className="block"><span className="mb-1.5 block text-[13px] font-medium text-sub">{t(label)}</span>{children}{hint && <span className="mt-1.5 block text-xs text-mute">{t(hint)}</span>}</label>;
}
const ctl = "w-full rounded-ctl border border-line bg-card px-3 text-[14px] text-ink placeholder:text-mute transition-shadow duration-150 focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10 disabled:bg-raised disabled:text-mute";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(ctl, "h-10", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(ctl, "h-10", p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(ctl, "min-h-[96px] py-2", p.className)} />;
export function Check({ label, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return <label className="flex cursor-pointer items-start gap-2.5 text-[14px] leading-6 text-sub"><input type="checkbox" {...p} className="mt-1 h-4 w-4 shrink-0" /><span>{label}</span></label>;
}

export function Card({ title, action, children, className, pad = true }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx("min-w-0 rounded-card border border-line bg-card", className)}>
      {(title || action) && <header className="flex min-h-[60px] flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 pb-2 pt-4"><h2 className="text-[17px] font-bold">{title}</h2>{action}</header>}
      <div className={pad ? cx("px-6 pb-6", title || action ? "pt-2" : "pt-6") : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  const { t } = useI18n();
  return <div className="rounded-card border border-line bg-card p-6"><div className="text-[13px] font-medium text-mute">{t(label)}</div><div className="num mt-2 text-[30px] font-bold leading-9 tracking-[-0.02em]">{value}</div><div className="mt-1 min-h-5 text-[13px] text-sub">{note}</div></div>;
}

export function Dot({ status, label }: { status: string; label?: string }) {
  const { t } = useI18n();
  const tone = TONE[status] || "mute";
  const color = { ok: "bg-ok-soft text-ok", bad: "bg-bad-soft text-bad", warn: "bg-warn-soft text-warn", mute: "bg-raised text-sub", accent: "bg-accent-soft text-accent" }[tone];
  return <span className={cx("inline-flex h-6 items-center whitespace-nowrap rounded-md px-2 text-[12px] font-semibold", color)}>{label ?? t(STATUS[status] || status)}</span>;
}
export const MockTag = () => <span className="inline-flex h-6 items-center rounded-md bg-warn-soft px-2 text-[12px] font-semibold text-warn">모의</span>;

export type Col<T> = { key: string; label: string; render?: (row: T) => ReactNode; right?: boolean; mono?: boolean; width?: string };
export function Table<T extends Record<string, any>>({ cols, rows, onRow, empty = "표시할 데이터가 없습니다" }: { cols: Col<T>[]; rows: T[] | null | undefined; onRow?: (row: T) => void; empty?: string }) {
  const { t } = useI18n();
  if (!rows) return <div className="p-5 text-sm text-mute">{t("불러오는 중")}</div>;
  if (!rows.length) return <div className="p-8 text-center text-sm text-mute">{t(empty)}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-[14px]">
        <thead><tr className="bg-raised text-[13px] text-sub">{cols.map((c) => <th key={c.key} style={{ width: c.width }} className={cx("h-10 whitespace-nowrap px-5 font-medium", c.right && "text-right")}>{t(c.label)}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => (
          <tr key={row.id ?? i} onClick={onRow ? () => onRow(row) : undefined} className={cx("border-b border-line last:border-0", onRow && "cursor-pointer transition-colors duration-150 hover:bg-[#f8fafc]")}>
            {cols.map((c) => <td key={c.key} className={cx("h-[52px] px-5 py-2 align-middle", c.right && "text-right", (c.right || c.mono) && "num")}>{c.render ? c.render(row) : String(row[c.key] ?? "-")}</td>)}
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const { t } = useI18n();
  useEffect(() => { const h = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[#191f28]/45 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal className={cx("rise w-full rounded-panel border border-line bg-card shadow-float", wide ? "max-w-3xl" : "max-w-lg")}>
        <header className="flex h-16 items-center justify-between px-6"><h2 className="text-[19px] font-bold">{t(title)}</h2><button onClick={onClose} aria-label="닫기" className="rounded p-1 text-mute hover:bg-raised hover:text-ink"><X size={18} strokeWidth={1.5} /></button></header>
        <div className="px-6 pb-6">{children}</div>
      </div>
    </div>
  );
}

export function Notice({ tone = "mute", children }: { tone?: "mute" | "bad" | "ok" | "warn"; children: ReactNode }) {
  const c = { mute: "bg-raised text-sub", bad: "bg-bad-soft text-bad", ok: "bg-ok-soft text-ok", warn: "bg-warn-soft text-[#8a4b00]" }[tone];
  return <div className={cx("rounded-ctl px-4 py-3 text-[14px] leading-6", c)}>{children}</div>;
}

export function PageHead({ title, desc, action }: { title: string; desc?: string; action?: ReactNode }) {
  const { t } = useI18n();
  return <div className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-[26px] font-bold leading-9">{t(title)}</h1>{desc && <p className="mt-1.5 text-[15px] text-sub">{t(desc)}</p>}</div>{action}</div>;
}

// 데이터 로딩 훅: 실제 API 응답만 표시한다.
export function useLoad<T = any>(fn: () => Promise<T>, deps: any[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => fn().then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message)), deps); // eslint-disable-line
  useEffect(() => { reload(); if (!pollMs) return; const id = setInterval(reload, pollMs); return () => clearInterval(id); }, [reload, pollMs]);
  return { data, error, reload, setData };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const run = async (fn: () => Promise<any>, okMsg = "") => {
    setBusy(true); setError(""); setDone("");
    try { const r = await fn(); setDone(okMsg); return r; } catch (e: any) { setError(e.message || "오류가 발생했습니다"); return undefined; } finally { setBusy(false); }
  };
  return { busy, error, done, run, setError };
}
export const Msg = ({ a }: { a: { error: string; done: string } }) => (a.error ? <Notice tone="bad">{a.error}</Notice> : a.done ? <Notice tone="ok">{a.done}</Notice> : null);
