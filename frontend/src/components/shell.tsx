import { Bell, LogOut, Menu, X, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { get, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { LocaleSwitch, Logo } from "../pages/public";
import { cx, useLoad } from "./ui";

export type NavGroup = { label?: string; items: { to: string; label: string; icon: LucideIcon; end?: boolean; perm?: string }[] };

export function AppShell({ groups, home, badge }: { groups: NavGroup[]; home: string; badge?: string }) {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [bell, setBell] = useState(false);
  const notes = useLoad(() => get("/notifications"), [], 30000);
  const can = (perm?: string) => !perm || user?.role === "superadmin" || user?.permissions?.includes(perm);
  const side = (
    <nav className="flex h-full flex-col overflow-y-auto px-3 pb-4">
      {groups.map((g, gi) => {
        const items = g.items.filter((i) => can(i.perm));
        if (!items.length) return null;
        return (
          <div key={gi}>
            {g.label && <div className="mb-2 mt-6 px-2 text-xs text-mute">{t(g.label)}</div>}
            <div className={cx("space-y-0.5", !g.label && "mt-3")}>{items.map((i) => (
              <NavLink key={i.to} to={i.to} end={i.end} onClick={() => setOpen(false)} className={({ isActive }) => cx("flex h-9 items-center gap-2.5 rounded-ctl px-2 text-sm transition-colors duration-150", isActive ? "bg-raised text-ink" : "text-sub hover:bg-raised hover:text-ink")}>
                <i.icon size={16} strokeWidth={1.5} className="shrink-0 text-mute" /><span className="truncate">{t(i.label)}</span>
              </NavLink>))}</div>
          </div>
        );
      })}
    </nav>
  );
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen flex-col border-r border-line bg-card lg:flex">
        <div className="flex h-14 shrink-0 items-center gap-2 px-5"><Logo to={home} />{badge && <span className="rounded border border-line px-1.5 py-0.5 text-[11px] text-mute">{t(badge)}</span>}</div>
        {side}
      </aside>
      {open && <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={() => setOpen(false)}><aside className="h-full w-[264px] bg-card pt-3" onClick={(e) => e.stopPropagation()}>{side}</aside></div>}
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-page/95 px-4 backdrop-blur sm:px-8">
          <button className="rounded p-1 text-sub lg:hidden" aria-label="메뉴" onClick={() => setOpen(true)}><Menu size={20} strokeWidth={1.5} /></button>
          <span className="lg:hidden"><Logo to={home} /></span>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden sm:block"><LocaleSwitch /></span>
            <div className="relative">
              <button aria-label="알림" className="relative rounded p-1.5 text-sub hover:bg-raised" onClick={() => { setBell(!bell); if (!bell && notes.data?.unread) post("/notifications/read").then(notes.reload); }}>
                <Bell size={18} strokeWidth={1.5} />{!!notes.data?.unread && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />}
              </button>
              {bell && (
                <div className="rise absolute right-0 top-10 z-30 max-h-[70vh] w-[340px] max-w-[90vw] overflow-y-auto rounded-card border border-line bg-card shadow-float">
                  <div className="flex h-11 items-center justify-between border-b border-line px-4 text-[13px] text-sub">{t("알림")}<button onClick={() => setBell(false)} aria-label="닫기"><X size={16} strokeWidth={1.5} /></button></div>
                  {!notes.data?.items?.length && <p className="p-6 text-center text-[13px] text-mute">{t("알림이 없습니다")}</p>}
                  {(notes.data?.items || []).slice(0, 30).map((n: any) => (
                    <button key={n.id} onClick={() => { setBell(false); if (n.link) nav(n.link); }} className="block w-full border-b border-line px-4 py-3 text-left last:border-0 hover:bg-raised">
                      <div className="text-[13px] text-ink">{n.title}</div><div className="mt-0.5 line-clamp-2 text-xs text-sub">{n.body}</div><div className="num mt-1 text-[11px] text-mute">{ago(n.created_at)}</div>
                    </button>))}
                </div>)}
            </div>
            <Link to={`${home}/account`} className="hidden max-w-[180px] truncate text-[13px] text-sub hover:text-ink sm:block">{user?.name || user?.email}</Link>
            <button aria-label="로그아웃" title={t("로그아웃")} className="rounded p-1.5 text-sub hover:bg-raised" onClick={async () => { await logout(); nav("/"); }}><LogOut size={18} strokeWidth={1.5} /></button>
          </div>
        </header>
        <main className="mx-auto max-w-[1440px] px-4 py-8 sm:px-8"><Outlet /></main>
      </div>
    </div>
  );
}
