import { X } from "lucide-react";
import { useCallback, useEffect, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { STATUS, TONE, useI18n } from "../lib/i18n";

const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");
export { cx };

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" | "lg" };
export function Button({ variant = "secondary", size = "md", className, ...rest }: BtnProps) {
  const v = { primary: "bg-ink text-white hover:bg-[#2b2b2b]", secondary: "bg-card text-ink border border-line hover:bg-raised",
    ghost: "text-sub hover:bg-raised hover:text-ink", danger: "bg-card text-bad border border-line hover:bg-[#fef2f2]" }[variant];
  const s = { sm: "h-8 px-3 text-[13px]", md: "h-9 px-4 text-sm", lg: "h-11 px-5 text-[15px]" }[size];
  return <button {...rest} className={cx("inline-flex items-center justify-center gap-2 rounded-ctl font-medium transition-colors duration-150 ease-out active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap", v, s, className)} />;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  const { t } = useI18n();
  return <label className="block"><span className="mb-1 block text-[13px] text-sub">{t(label)}</span>{children}{hint && <span className="mt-1 block text-xs text-mute">{t(hint)}</span>}</label>;
}
const ctl = "w-full rounded-ctl border border-line bg-card px-3 text-sm text-ink placeholder:text-mute transition-colors duration-150 focus:border-ink/40 focus:outline-none";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(ctl, "h-9", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(ctl, "h-9", p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(ctl, "min-h-[96px] py-2", p.className)} />;
export function Check({ label, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return <label className="flex items-start gap-2 text-sm text-sub"><input type="checkbox" {...p} className="mt-1 h-4 w-4 accent-[#0f766e]" /><span>{label}</span></label>;
}

export function Card({ title, action, children, className, pad = true }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={cx("min-w-0 rounded-card border border-line bg-card", className)}>
      {(title || action) && <header className="flex min-h-[52px] items-center justify-between gap-4 border-b border-line px-5 py-2"><h2 className="text-[15px] font-medium">{title}</h2>{action}</header>}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  const { t } = useI18n();
  return <div className="rounded-card border border-line bg-card p-5"><div className="text-[13px] text-sub">{t(label)}</div><div className="num mt-3 text-[28px] font-medium leading-none">{value}</div><div className="mt-3 h-5 text-xs text-mute">{note}</div></div>;
}

export function Dot({ status, label }: { status: string; label?: string }) {
  const { t } = useI18n();
  const tone = TONE[status] || "mute";
  const color = { ok: "bg-ok", bad: "bg-bad", warn: "bg-warn", mute: "bg-mute", accent: "bg-accent" }[tone];
  return <span className="inline-flex items-center gap-2 whitespace-nowrap text-[13px] text-sub"><span className={cx("h-1.5 w-1.5 rounded-full", color)} />{label ?? t(STATUS[status] || status)}</span>;
}
export const MockTag = () => <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[11px] text-warn">MOCK</span>;

export type Col<T> = { key: string; label: string; render?: (row: T) => ReactNode; right?: boolean; mono?: boolean; width?: string };
export function Table<T extends Record<string, any>>({ cols, rows, onRow, empty = "표시할 데이터가 없습니다" }: { cols: Col<T>[]; rows: T[] | null | undefined; onRow?: (row: T) => void; empty?: string }) {
  const { t } = useI18n();
  if (!rows) return <div className="p-5 text-sm text-mute">{t("불러오는 중")}</div>;
  if (!rows.length) return <div className="p-8 text-center text-sm text-mute">{t(empty)}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-[13px]">
        <thead><tr className="border-b border-line text-mute">{cols.map((c) => <th key={c.key} style={{ width: c.width }} className={cx("h-10 px-4 font-normal", c.right && "text-right")}>{t(c.label)}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => (
          <tr key={row.id ?? i} onClick={onRow ? () => onRow(row) : undefined} className={cx("border-b border-line last:border-0", onRow && "cursor-pointer transition-colors duration-150 hover:bg-raised")}>
            {cols.map((c) => <td key={c.key} className={cx("h-11 px-4 py-2 align-middle", c.right && "text-right", (c.right || c.mono) && "num")}>{c.render ? c.render(row) : String(row[c.key] ?? "-")}</td>)}
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
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal className={cx("rise w-full rounded-panel border border-line bg-card shadow-float", wide ? "max-w-3xl" : "max-w-lg")}>
        <header className="flex h-14 items-center justify-between border-b border-line px-5"><h2 className="text-[15px] font-medium">{t(title)}</h2><button onClick={onClose} aria-label="닫기" className="rounded p-1 text-mute hover:bg-raised hover:text-ink"><X size={18} strokeWidth={1.5} /></button></header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Notice({ tone = "mute", children }: { tone?: "mute" | "bad" | "ok" | "warn"; children: ReactNode }) {
  const c = { mute: "border-line bg-raised text-sub", bad: "border-bad/30 bg-[#fef2f2] text-bad", ok: "border-ok/30 bg-[#f0fdf4] text-ok", warn: "border-warn/30 bg-[#fffbeb] text-warn" }[tone];
  return <div className={cx("rounded-ctl border px-4 py-3 text-[13px] leading-5", c)}>{children}</div>;
}

export function PageHead({ title, desc, action }: { title: string; desc?: string; action?: ReactNode }) {
  const { t } = useI18n();
  return <div className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-[26px] font-medium leading-tight">{t(title)}</h1>{desc && <p className="mt-2 text-sm text-sub">{t(desc)}</p>}</div>{action}</div>;
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
