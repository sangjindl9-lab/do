import { Menu, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Button, Card, Check, Field, Input, Msg, Notice, Select, Table, cx, useAction, useLoad } from "../components/ui";
import { get, post, refresh, setRefreshToken, storeSession } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dt, won } from "../lib/format";
import { LOCALES, useI18n } from "../lib/i18n";

const NAV = [["/service", "서비스 소개"], ["/how-it-works", "이용 방법"], ["/pricing", "요금제"], ["/devices", "지원 기기"], ["/faq", "자주 묻는 질문"], ["/notices", "공지사항"]];
const CHECKS: Record<string, string> = {
  install: "APK 설치", launch: "앱 실행", cold_start: "초기 로딩 시간", display: "화면 표시", orientation: "화면 방향 변경", restart: "종료·재실행",
  background: "백그라운드 전환·복귀", permissions: "권한 요청 동작", cpu: "CPU 사용량", memory: "RAM 사용량", storage: "저장공간 사용량",
  temperature: "기기 온도", crash: "크래시", anr: "ANR", logcat: "Logcat 오류", scenario: "고객 지정 시나리오", network: "네트워크 장애 대응",
};
export { CHECKS };

export function Logo({ to = "/" }: { to?: string }) {
  const { t } = useI18n();
  return (
    <Link to={to} className="flex items-center gap-2 text-[16px] font-semibold tracking-tight text-ink">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="#171717" /><g fill="#ededed"><rect x="7" y="7" width="5" height="8" rx="1.2" /><rect x="13.5" y="7" width="5" height="8" rx="1.2" /><rect x="20" y="7" width="5" height="8" rx="1.2" fill="#2dd4bf" /><rect x="7" y="17" width="5" height="8" rx="1.2" /><rect x="13.5" y="17" width="5" height="8" rx="1.2" /><rect x="20" y="17" width="5" height="8" rx="1.2" /></g></svg>
      {t("구글자동테스터")}
    </Link>
  );
}

export function LocaleSwitch() {
  const { locale, setLocale } = useI18n();
  return <select aria-label="Language" value={locale} onChange={(e) => setLocale(e.target.value)} className="h-8 rounded-ctl border border-line bg-card px-2 text-[13px] text-sub">{LOCALES.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select>;
}

export function PublicLayout() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const site = useLoad(() => get("/public/site"));
  const home = user ? (user.is_staff ? "/admin" : "/dashboard") : null;
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-page/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-8 px-6">
          <Logo />
          <nav className="hidden flex-1 items-center gap-6 lg:flex">{NAV.map(([to, label]) => <NavLink key={to} to={to} className={({ isActive }) => cx("text-sm transition-colors duration-150", isActive ? "text-ink" : "text-sub hover:text-ink")}>{t(label)}</NavLink>)}</nav>
          <div className="ml-auto flex items-center gap-4">
            <span className="hidden sm:block"><LocaleSwitch /></span>
            {home ? <Link to={home}><Button variant="primary" size="sm">{t("대시보드")}</Button></Link> : <>
              <Link to="/login" className="hidden text-sm text-sub hover:text-ink sm:block">{t("로그인")}</Link>
              <Link to="/register"><Button variant="primary" size="sm">{t("시작하기")}</Button></Link></>}
            <button className="rounded p-1 text-sub lg:hidden" aria-label="메뉴" onClick={() => setOpen(!open)}>{open ? <X size={20} strokeWidth={1.5} /> : <Menu size={20} strokeWidth={1.5} />}</button>
          </div>
        </div>
        {open && <nav className="border-t border-line px-6 py-2 lg:hidden">{NAV.map(([to, label]) => <Link key={to} to={to} onClick={() => setOpen(false)} className="block h-10 leading-10 text-sub">{t(label)}</Link>)}<Link to="/login" onClick={() => setOpen(false)} className="block h-10 leading-10 text-sub sm:hidden">{t("로그인")}</Link><div className="py-2 sm:hidden"><LocaleSwitch /></div></nav>}
      </header>
      <main className="flex-1"><Outlet /></main>
      <footer className="border-t border-line">
        <div className="mx-auto max-w-[1200px] px-6 py-10">
          <p className="max-w-3xl text-[13px] leading-5 text-mute">{t(site.data?.notice || "")}</p>
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-sub">
            <Link to="/legal/terms" className="hover:text-ink">{t("이용약관")}</Link>
            <Link to="/legal/privacy" className="hover:text-ink">{t("개인정보처리방침")}</Link>
            <Link to="/legal/refund" className="hover:text-ink">{t("환불 정책")}</Link>
            {site.data?.support_email && <a href={`mailto:${site.data.support_email}`} className="hover:text-ink">{site.data.support_email}</a>}
            <span className="ml-auto text-mute">Google Auto Tester</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

const Section = ({ children, className }: { children: ReactNode; className?: string }) => <section className={cx("mx-auto max-w-[1200px] px-6", className)}>{children}</section>;

/** 20칸 폰팜 랙. 실제 등록된 실기기 수만큼만 칸이 켜진다(모의 장비 제외). */
function Rack({ total, models }: { total: number; models: any[] }) {
  const { t } = useI18n();
  const lit = Math.min(20, total);
  return (
    <div className="rounded-panel bg-rack-bg p-5 text-rack-text shadow-float">
      <div className="flex items-center justify-between font-mono text-xs">
        <span>PHONE FARM BOX · 20-IN-1</span>
        <span className="flex items-center gap-2"><span className={cx("h-1.5 w-1.5 rounded-full", total ? "bg-[#2dd4bf]" : "bg-[#85858b]")} />{total ? `${total} ${t("대 연결")}` : t("연결 대기")}</span>
      </div>
      <div className="mt-4 grid grid-cols-5 gap-2 sm:grid-cols-10 lg:grid-cols-5 xl:grid-cols-10">
        {Array.from({ length: 20 }, (_, i) => (
          <div key={i} className={cx("flex aspect-[9/16] flex-col justify-between rounded-md border p-1.5", i < lit ? "border-rack-line bg-rack-cell" : "border-dashed border-rack-line")}>
            <span className={cx("h-1 w-1 rounded-full", i < lit ? "bg-[#2dd4bf]" : "bg-transparent")} />
            <span className="font-mono text-[10px] leading-none">{String(i + 1).padStart(2, "0")}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 border-t border-rack-line pt-4 font-mono text-xs leading-5">
        {total ? models.slice(0, 3).map((m) => <div key={m.model + m.android_version} className="flex justify-between"><span>{m.manufacturer} {m.model} · Android {m.android_version}</span><span>×{m.count}</span></div>)
          : <span>{t("등록된 실기기가 아직 없습니다. 장비가 연결되면 이 화면에 실제 수량이 표시됩니다")}</span>}
      </div>
    </div>
  );
}

export function Home() {
  const { t } = useI18n();
  const devices = useLoad(() => get("/public/devices"));
  const products = useLoad<any[]>(() => get("/public/products"));
  const steps = [["앱 등록", "패키지명과 APK를 등록하고 검사 권한을 확인합니다"], ["상품 선택·결제", "검사 기기 수와 기간을 고르고 결제합니다"],
    ["실기기 자동 검사", "배정된 실기기에서 정해진 기간 동안 매일 반복 검사합니다"], ["결과·보고서", "기기별 결과, 스크린샷, 오류 로그와 PDF 보고서를 받습니다"]];
  return (
    <>
      <Section className="grid items-center gap-12 py-16 lg:grid-cols-[1fr_1.1fr] lg:py-24">
        <div className="rise">
          <p className="font-mono text-xs text-accent">{t("Android 실기기 자동화 품질검사")}</p>
          <h1 className="mt-4 text-[38px] font-medium leading-[1.12] tracking-[-0.02em] sm:text-[52px]">{t("출시 전 앱을 실제 폰 여러 대에서 매일 자동으로 검사합니다")}</h1>
          <p className="mt-6 max-w-[34rem] text-[17px] leading-7 text-sub">{t("설치, 실행, 화면 전환, 크래시, ANR, 성능을 폰팜 실기기에서 반복 측정하고 기기별 결과와 보고서를 제공합니다")}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/register"><Button variant="primary" size="lg">{t("테스트 신청하기")}</Button></Link>
            <Link to="/pricing"><Button size="lg">{t("요금제 보기")}</Button></Link>
          </div>
        </div>
        <Rack total={devices.data?.total ?? 0} models={devices.data?.models ?? []} />
      </Section>
      <Section className="border-t border-line py-16">
        <h2 className="text-[24px] font-medium">{t("진행 순서")}</h2>
        <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">{steps.map(([title, body], i) => (
          <li key={title}><span className="num text-[13px] text-mute">{String(i + 1).padStart(2, "0")}</span><h3 className="mt-2 text-[16px] font-medium">{t(title)}</h3><p className="mt-2 text-sm text-sub">{t(body)}</p></li>))}</ol>
      </Section>
      <Section className="border-t border-line py-16">
        <div className="grid gap-12 lg:grid-cols-[1fr_1.4fr]">
          <div><h2 className="text-[24px] font-medium">{t("검사 항목")}</h2><p className="mt-3 text-sm text-sub">{t("수행하지 못한 항목은 성공으로 기록하지 않고 '미수행'으로 표시합니다")}</p></div>
          <ul className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">{Object.values(CHECKS).map((c) => <li key={c} className="flex items-center gap-2 text-sm text-sub"><span className="h-1.5 w-1.5 rounded-full bg-accent" />{t(c)}</li>)}</ul>
        </div>
      </Section>
      <Section className="border-t border-line py-16">
        <div className="flex items-end justify-between"><h2 className="text-[24px] font-medium">{t("요금제")}</h2><Link to="/pricing" className="text-sm text-sub hover:text-ink">{t("전체 비교")}</Link></div>
        <div className="mt-8"><PriceTable products={products.data} compact /></div>
      </Section>
    </>
  );
}

function PriceTable({ products, compact }: { products: any[] | null; compact?: boolean }) {
  const { t, locale } = useI18n();
  if (!products) return <p className="text-mute">{t("불러오는 중")}</p>;
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-card">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead><tr className="border-b border-line text-[13px] text-mute"><th className="h-11 px-5 font-normal">{t("상품")}</th><th className="px-5 text-right font-normal">{t("검사 기기")}</th><th className="px-5 text-right font-normal">{t("검사 기간")}</th><th className="px-5 text-right font-normal">{t("일일 검사")}</th>{!compact && <th className="px-5 font-normal">{t("보고서·분석")}</th>}<th className="px-5 text-right font-normal">{t("가격")}</th><th className="px-5" /></tr></thead>
        <tbody>{products.map((p) => (
          <tr key={p.id} className="border-b border-line last:border-0">
            <td className="h-14 px-5"><span className="font-medium">{p.name}</span><span className="mt-0.5 block text-xs text-mute">{locale === "en" ? p.description_en : p.description}</span></td>
            <td className="num px-5 text-right">{p.is_quote ? "-" : `${p.device_count}${t("대")}`}</td>
            <td className="num px-5 text-right">{p.is_quote ? "-" : `${p.duration_days}${t("일")}`}</td>
            <td className="num px-5 text-right">{p.is_quote ? "-" : `${p.daily_runs}${t("회")}`}</td>
            {!compact && <td className="px-5 text-[13px] text-sub">{[p.pdf_report && "PDF", p.excel_report && "Excel", p.ai_analysis && t("AI 오류 분석(선택)"), p.priority && t("우선 배정")].filter(Boolean).join(" · ")}</td>}
            <td className="num px-5 text-right">{p.is_quote ? t("별도 견적") : <>{p.list_price > p.price && <s className="mr-2 text-mute">{won(p.list_price)}</s>}{won(p.price)}</>}</td>
            <td className="px-5 text-right"><Link to={p.is_quote ? "/dashboard/support" : "/dashboard/new-test"}><Button size="sm">{t(p.is_quote ? "문의" : "신청")}</Button></Link></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

const Page = ({ title, lead, children }: { title: string; lead?: string; children: ReactNode }) => {
  const { t } = useI18n();
  return <Section className="py-14"><h1 className="text-[32px] font-medium leading-tight">{t(title)}</h1>{lead && <p className="mt-4 max-w-2xl text-[16px] leading-7 text-sub">{t(lead)}</p>}<div className="mt-10">{children}</div></Section>;
};

export function Service() {
  const { t } = useI18n();
  const items = [["실기기 폰팜", "에뮬레이터가 아닌 실제 Android 기기에서 검사합니다. 기기는 표준 ADB로 제어합니다"],
    ["정해진 기간 반복 검사", "상품별 기간 동안 하루 정해진 횟수만큼 자동으로 검사하고, 실패한 작업은 자동 재시도합니다"],
    ["기기별 결과와 증적", "기기별 성공·실패, 실제 스크린샷, 크래시·ANR 로그, 성능 측정값을 그대로 보여줍니다"],
    ["규칙 기반 오류 분석", "크래시 로그를 유형과 심각도로 분류하고 중복 오류를 묶습니다. AI 분석은 선택 사항이며 '추정'으로 구분 표시합니다"],
    ["검사 시나리오", "UI 요소 식별자 기반으로 버튼 선택, 입력, 화면 검증 단계를 직접 구성할 수 있습니다"],
    ["PDF·Excel 보고서", "종합, 일별, 기기별, 버전별, 오류 분석, 성능, 스크린샷, 완료 보고서를 내려받습니다"]];
  return (
    <Page title="서비스 소개" lead="구글자동테스터는 Android 앱 개발자를 위한 실기기 자동화 품질검사 서비스입니다">
      <div className="grid gap-x-12 gap-y-10 md:grid-cols-2">{items.map(([h, b]) => <div key={h}><h2 className="text-[17px] font-medium">{t(h)}</h2><p className="mt-2 text-sm leading-6 text-sub">{t(b)}</p></div>)}</div>
      <div className="mt-12 max-w-3xl space-y-3">
        <Notice>{t("본 서비스는 Google의 공식 서비스가 아닌 독립적인 제3자 앱 품질검사 서비스입니다")}</Notice>
        <Notice>{t("기기 자동 검사 기록은 Google Play 비공개 테스트의 인간 테스터 참여로 집계되지 않으며, 테스트 참여 요건을 대신하지 않습니다. 프로덕션 승인을 보장하지 않습니다")}</Notice>
      </div>
    </Page>
  );
}

export function HowTo() {
  const { t } = useI18n();
  const steps = [["회원가입", "이메일로 가입합니다"], ["앱 등록", "앱 이름, 패키지명을 입력하고 검사 권한 보유를 확인합니다. APK를 올리면 형식·패키지명·해시를 검증합니다"],
    ["테스트 신청", "앱 버전과 상품을 고르고 필요하면 검사 시나리오와 희망 Android 버전을 지정합니다"], ["결제", "결제가 서버에서 검증되면 주문이 확정됩니다"],
    ["기기 자동 배정", "가용 실기기를 자동 배정합니다. 기기가 부족하면 대기 상태가 되고 확보되는 즉시 시작합니다"],
    ["반복 검사", "검사 기간 동안 매일 자동 검사하며 진행 현황을 대시보드에서 확인합니다"], ["완료·보고서", "기간이 끝나면 최종 보고서가 자동 생성되고 알림을 보냅니다"]];
  return (
    <Page title="이용 방법">
      <ol className="max-w-3xl">{steps.map(([h, b], i) => (
        <li key={h} className="grid grid-cols-[48px_1fr] border-t border-line py-5 first:border-0"><span className="num text-mute">{String(i + 1).padStart(2, "0")}</span><div><h2 className="text-[16px] font-medium">{t(h)}</h2><p className="mt-1 text-sm text-sub">{t(b)}</p></div></li>))}</ol>
      <div className="mt-8"><Link to="/register"><Button variant="primary" size="lg">{t("테스트 신청하기")}</Button></Link></div>
    </Page>
  );
}

export function Pricing() {
  const { t } = useI18n();
  const products = useLoad<any[]>(() => get("/public/products"));
  return (
    <Page title="상품 및 요금제" lead="검사 기기 수와 기간에 따라 선택합니다. 가격은 부가세 포함 여부 등 운영 정책에 따라 변경될 수 있습니다">
      <PriceTable products={products.data} />
      <p className="mt-6 max-w-3xl text-[13px] leading-5 text-mute">{t("검사 기기 수는 실제 검사에 사용되는 기기 수량이며 Google Play 비공개 테스트의 독립적인 참여자 수를 의미하지 않습니다")}</p>
    </Page>
  );
}

export function Devices() {
  const { t } = useI18n();
  const d = useLoad(() => get("/public/devices"));
  return (
    <Page title="지원 기기 안내" lead="현재 폰팜에 등록되어 검사에 사용되는 실기기 목록입니다">
      <Card pad={false} title={<>{t("등록 실기기")} <span className="num ml-2 text-mute">{d.data?.total ?? 0}</span></>}>
        <Table rows={d.data?.models} empty="등록된 실기기가 아직 없습니다. 장비 연결 후 이 목록에 표시됩니다" cols={[
          { key: "manufacturer", label: "제조사" }, { key: "model", label: "모델" }, { key: "android_version", label: "Android", mono: true },
          { key: "resolution", label: "해상도", mono: true }, { key: "count", label: "수량", right: true }]} />
      </Card>
    </Page>
  );
}

export function FaqPage() {
  const { locale } = useI18n();
  const f = useLoad<any[]>(() => get(`/public/faqs?locale=${locale}`), [locale]);
  return <Page title="자주 묻는 질문"><div className="max-w-3xl">{(f.data || []).map((q) => <details key={q.id} className="border-t border-line py-4 first:border-0"><summary className="cursor-pointer text-[16px] font-medium">{q.question}</summary><p className="mt-3 whitespace-pre-line text-sm leading-6 text-sub">{q.answer}</p></details>)}</div></Page>;
}

export function Notices() {
  const { t } = useI18n();
  const n = useLoad<any[]>(() => get("/public/announcements"));
  return (
    <Page title="공지사항">
      <div className="max-w-3xl">{n.data && !n.data.length && <p className="text-mute">{t("등록된 공지사항이 없습니다")}</p>}
        {(n.data || []).map((a) => <article key={a.id} className="border-t border-line py-5 first:border-0"><div className="num text-xs text-mute">{dt(a.created_at, false)}</div><h2 className="mt-1 text-[16px] font-medium">{a.title}</h2><p className="mt-2 whitespace-pre-line text-sm leading-6 text-sub">{a.body}</p></article>)}</div>
    </Page>
  );
}

export function Legal() {
  const { key } = useParams();
  const { locale, t } = useI18n();
  const d = useLoad(() => get(`/public/legal/${key}?locale=${locale}`), [key, locale]);
  return <Page title={d.data?.title || ""}><article className="max-w-3xl whitespace-pre-line text-sm leading-7 text-sub">{d.data?.body}</article>{d.data && <p className="num mt-8 text-xs text-mute">{t("최종 수정")} {dt(d.data.updated_at, false)}</p>}</Page>;
}

// ---------------- 인증 화면 ----------------
function AuthShell({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  const { t } = useI18n();
  return <div className="mx-auto w-full max-w-[400px] px-6 py-16"><h1 className="text-[26px] font-medium">{t(title)}</h1><div className="mt-8 space-y-4">{children}</div>{footer && <div className="mt-6 text-sm text-sub">{footer}</div>}</div>;
}

export function Login({ admin }: { admin?: boolean }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const a = useAction();
  const [f, setF] = useState({ identifier: "", password: "" });
  const site = useLoad(() => get("/public/site"));
  const errs: Record<string, string> = { oauth_state: "Google 로그인 요청이 만료되었습니다", oauth_failed: "Google 로그인에 실패했습니다", oauth_email: "인증된 Google 이메일이 필요합니다", oauth_denied: "이 계정은 Google 로그인을 사용할 수 없습니다" };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const data = await a.run(() => post("/auth/login", f));
    if (!data) return;
    storeSession(data);
    nav(data.user.must_change_password ? (data.user.is_staff ? "/admin/account" : "/dashboard/account") : sp.get("next") || (data.user.is_staff ? "/admin" : "/dashboard"), { replace: true });
  };
  return (
    <AuthShell title={admin ? "관리자 로그인" : "로그인"} footer={!admin && <><Link to="/forgot" className="hover:text-ink">{t("비밀번호 찾기")}</Link><span className="mx-3 text-mute">·</span><Link to="/register" className="hover:text-ink">{t("회원가입")}</Link></>}>
      {sp.get("error") && <Notice tone="bad">{t(errs[sp.get("error")!] || "로그인에 실패했습니다")}</Notice>}
      <form onSubmit={submit} className="space-y-4">
        <Field label={admin ? "관리자 아이디" : "이메일"}><Input autoFocus autoComplete="username" value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} required /></Field>
        <Field label="비밀번호"><Input type="password" autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required /></Field>
        <Msg a={a} />
        <Button variant="primary" size="lg" className="w-full" disabled={a.busy}>{t("로그인")}</Button>
      </form>
      {!admin && site.data?.google_login && <a href="/api/auth/google/start"><Button size="lg" className="w-full">{t("Google 계정으로 로그인")}</Button></a>}
    </AuthShell>
  );
}

export function Register() {
  const { t, locale } = useI18n();
  const nav = useNavigate();
  const a = useAction();
  const [f, setF] = useState({ email: "", password: "", name: "", kind: "individual", company: "", phone: "", agree_terms: false });
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const data = await a.run(() => post("/auth/register", { ...f, locale }));
    if (data) { storeSession(data); nav("/dashboard", { replace: true }); }
  };
  return (
    <AuthShell title="회원가입" footer={<Link to="/login" className="hover:text-ink">{t("이미 계정이 있습니다")}</Link>}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="이메일"><Input type="email" autoComplete="email" value={f.email} onChange={(e) => set("email", e.target.value)} required /></Field>
        <Field label="비밀번호" hint="8자 이상, 영문과 숫자 포함"><Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} required minLength={8} /></Field>
        <Field label="이름"><Input value={f.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <Field label="회원 구분"><Select value={f.kind} onChange={(e) => set("kind", e.target.value)}><option value="individual">{t("일반 고객")}</option><option value="business">{t("기업 고객")}</option></Select></Field>
        {f.kind === "business" && <><Field label="회사명"><Input value={f.company} onChange={(e) => set("company", e.target.value)} /></Field><Field label="연락처"><Input value={f.phone} onChange={(e) => set("phone", e.target.value)} /></Field></>}
        <Check checked={f.agree_terms} onChange={(e) => set("agree_terms", e.target.checked)} label={<><Link to="/legal/terms" target="_blank" className="underline">{t("이용약관")}</Link>, <Link to="/legal/privacy" target="_blank" className="underline">{t("개인정보처리방침")}</Link>{t("에 동의합니다")}</>} />
        <Msg a={a} />
        <Button variant="primary" size="lg" className="w-full" disabled={a.busy || !f.agree_terms}>{t("가입하기")}</Button>
      </form>
    </AuthShell>
  );
}

export function Forgot() {
  const { t } = useI18n();
  const a = useAction();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<any>(null);
  return (
    <AuthShell title="비밀번호 찾기" footer={<Link to="/login" className="hover:text-ink">{t("로그인으로 돌아가기")}</Link>}>
      {sent ? <Notice tone={sent.smtp_configured ? "ok" : "warn"}>{t(sent.smtp_configured ? "가입된 이메일이라면 재설정 링크를 보냈습니다" : "현재 이메일 발송이 설정되지 않아 메일을 보낼 수 없습니다. 고객 문의로 요청해 주세요")}</Notice> :
        <form className="space-y-4" onSubmit={async (e) => { e.preventDefault(); const r = await a.run(() => post("/auth/forgot", { email })); if (r) setSent(r); }}>
          <Field label="이메일"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <Msg a={a} /><Button variant="primary" size="lg" className="w-full" disabled={a.busy}>{t("재설정 링크 받기")}</Button>
        </form>}
    </AuthShell>
  );
}

export function Reset() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  const a = useAction();
  const [password, setPassword] = useState("");
  return (
    <AuthShell title="비밀번호 재설정">
      {a.done ? <><Notice tone="ok">{a.done}</Notice><Link to="/login"><Button variant="primary" className="w-full">{t("로그인")}</Button></Link></> :
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => post("/auth/reset", { token: sp.get("token") || "", password }), t("비밀번호가 변경되었습니다")); }}>
          <Field label="새 비밀번호" hint="8자 이상, 영문과 숫자 포함"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} /></Field>
          <Msg a={a} /><Button variant="primary" size="lg" className="w-full" disabled={a.busy}>{t("변경하기")}</Button>
        </form>}
    </AuthShell>
  );
}

export function VerifyEmail() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  const [state, setState] = useState<"wait" | "ok" | "bad">("wait");
  useEffect(() => { post("/auth/verify-email", { token: sp.get("token") || "" }).then(() => setState("ok")).catch(() => setState("bad")); }, []); // eslint-disable-line
  return <AuthShell title="이메일 인증">{state === "wait" ? <p className="text-mute">{t("확인 중")}</p> : <Notice tone={state === "ok" ? "ok" : "bad"}>{t(state === "ok" ? "이메일 인증이 완료되었습니다" : "유효하지 않거나 만료된 링크입니다")}</Notice>}<Link to="/dashboard"><Button className="w-full">{t("대시보드")}</Button></Link></AuthShell>;
}

export function OAuthComplete() {
  const nav = useNavigate();
  useEffect(() => {
    const token = new URLSearchParams(location.hash.slice(1)).get("refresh_token");
    if (token) { setRefreshToken(token); history.replaceState(null, "", location.pathname); refresh().then((ok) => nav(ok ? "/dashboard" : "/login?error=oauth_failed", { replace: true })); }
    else nav("/login?error=oauth_failed", { replace: true });
  }, []); // eslint-disable-line
  return <div className="p-8 text-mute">로그인 처리 중</div>;
}
