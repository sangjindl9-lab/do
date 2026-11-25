import { Bug, Check as CheckIcon, Clock, Download, FileText, Image as ImageIcon, ListChecks, Menu, RefreshCw, Smartphone, Users, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Button, Card, Check, Field, Input, Msg, Notice, Select, Table, cx, useAction, useLoad } from "../components/ui";
import { get, post, refresh, setRefreshToken, storeSession } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dt, won } from "../lib/format";
import { LOCALES, useI18n } from "../lib/i18n";

const NAV = [["/service", "서비스 소개"], ["/how-it-works", "이용 방법"], ["/pricing", "가격·환불"], ["/devices", "검사 기기"], ["/faq", "자주 묻는 질문"], ["/notices", "공지사항"]];
const CHECKS: Record<string, string> = {
  install: "APK 설치", launch: "앱 실행", cold_start: "초기 로딩 시간", display: "화면 표시", orientation: "화면 방향 변경", restart: "종료·재실행",
  background: "백그라운드 전환·복귀", permissions: "권한 요청 동작", cpu: "CPU 사용량", memory: "RAM 사용량", storage: "저장공간 사용량",
  temperature: "기기 온도", crash: "크래시", anr: "ANR", logcat: "Logcat 오류", scenario: "고객 지정 시나리오", network: "네트워크 장애 대응",
};
export { CHECKS };

export function Logo({ to = "/" }: { to?: string }) {
  const { t } = useI18n();
  return (
    <Link to={to} className="flex items-center gap-2.5 text-[18px] font-extrabold tracking-[-0.03em] text-ink">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="9" fill="#1a63f5" /><rect x="10" y="5.5" width="12" height="21" rx="3" fill="#fff" /><path d="M12.8 16.2l2.4 2.4 4.2-4.6" fill="none" stroke="#1a63f5" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      {t("구글자동테스터")}
    </Link>
  );
}

export function LocaleSwitch() {
  const { locale, setLocale } = useI18n();
  return <select aria-label="Language" value={locale} onChange={(e) => setLocale(e.target.value)} className="h-9 rounded-ctl bg-raised px-2 text-[13px] font-medium text-sub">{LOCALES.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select>;
}

export function PublicLayout() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const site = useLoad(() => get("/public/site"));
  const home = user ? (user.is_staff ? "/admin" : "/dashboard") : null;
  return (
    <div className="flex min-h-screen flex-col bg-card">
      <header className="sticky top-0 z-30 border-b border-line bg-card">
        <div className="mx-auto flex h-16 max-w-[1160px] items-center gap-10 px-5">
          <Logo />
          <nav className="hidden flex-1 items-center gap-7 lg:flex">{NAV.map(([to, label]) => <NavLink key={to} to={to} className={({ isActive }) => cx("text-[15px] font-medium transition-colors duration-150", isActive ? "text-accent" : "text-sub hover:text-ink")}>{t(label)}</NavLink>)}</nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden sm:block"><LocaleSwitch /></span>
            {home ? <Link to={home}><Button variant="primary">{t("대시보드")}</Button></Link> : <>
              <Link to="/login" className="hidden px-2 text-[15px] font-medium text-sub hover:text-ink sm:block">{t("로그인")}</Link>
              <Link to="/register"><Button variant="primary">{t("시작하기")}</Button></Link></>}
            <button className="rounded p-1 text-sub lg:hidden" aria-label="메뉴" onClick={() => setOpen(!open)}>{open ? <X size={22} strokeWidth={1.75} /> : <Menu size={22} strokeWidth={1.75} />}</button>
          </div>
        </div>
        {open && <nav className="border-t border-line px-5 py-2 lg:hidden">{NAV.map(([to, label]) => <Link key={to} to={to} onClick={() => setOpen(false)} className="block h-11 font-medium leading-[44px] text-sub">{t(label)}</Link>)}<Link to="/login" onClick={() => setOpen(false)} className="block h-11 font-medium leading-[44px] text-sub sm:hidden">{t("로그인")}</Link><div className="py-2 sm:hidden"><LocaleSwitch /></div></nav>}
      </header>
      <main className="flex-1"><Outlet /></main>
      <footer className="bg-[#f7f8fa]">
        <div className="mx-auto max-w-[1160px] px-5 py-12">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-3 text-[14px] font-medium text-sub">
            <Link to="/legal/terms" className="hover:text-ink">{t("이용약관")}</Link>
            <Link to="/legal/privacy" className="font-bold text-ink">{t("개인정보처리방침")}</Link>
            <Link to="/legal/refund" className="hover:text-ink">{t("가격 및 환불 정책")}</Link>
            {site.data?.support_email && <a href={`mailto:${site.data.support_email}`} className="hover:text-ink">{site.data.support_email}</a>}
          </div>
          <p className="mt-6 max-w-3xl text-[13px] leading-6 text-mute">{t(site.data?.notice || "")}</p>
          <p className="mt-4 text-[13px] text-mute">© {t("구글자동테스터")}</p>
        </div>
      </footer>
    </div>
  );
}

const Section = ({ children, className }: { children: ReactNode; className?: string }) => <section className={cx("mx-auto max-w-[1160px] px-5", className)}>{children}</section>;
const H2 = ({ kicker, children }: { kicker?: string; children: ReactNode }) => { const { t } = useI18n(); return <div>{kicker && <p className="text-[15px] font-bold text-accent">{t(kicker)}</p>}<h2 className="mt-2 text-[28px] font-bold leading-[1.3] sm:text-[36px]">{children}</h2></div>; };

const TINTS = ["#dbe8ff", "#ffe7d1", "#d9f3e6", "#ece4ff", "#ffe0e3", "#d8f0f6", "#fff0c2", "#e4e8ee"];
/** 일별 실행 기록 화면의 예시 그림. 실제 고객 데이터가 아니라 화면 구성을 보여주는 그림이다. */
function RecordPreview() {
  const { t } = useI18n();
  return (
    <div className="rounded-panel border border-line bg-card p-5 shadow-lift sm:p-6">
      <div className="flex items-center justify-between">
        <div><div className="text-[13px] font-medium text-mute">{t("일별 실행 기록")} · {t("예시 화면")}</div><div className="mt-0.5 text-[18px] font-bold">{t("3일차")}</div></div>
        <span className="inline-flex h-7 items-center rounded-md bg-ok-soft px-2.5 text-[13px] font-semibold text-ok">{t("실행 확인")} 16/16</span>
      </div>
      <div className="mt-5 grid grid-cols-4 gap-2.5 sm:grid-cols-8 lg:grid-cols-4 xl:grid-cols-8">
        {Array.from({ length: 16 }, (_, i) => (
          <div key={i}>
            <div className="aspect-[9/17] overflow-hidden rounded-[10px] border border-line bg-card">
              <div className="h-[34%]" style={{ background: TINTS[i % TINTS.length] }} />
              <div className="space-y-1 p-1.5"><div className="h-1 w-4/5 rounded bg-[#d5dbe3]" /><div className="h-1 w-3/5 rounded bg-[#e4e8ee]" /><div className="h-1 w-2/3 rounded bg-[#e4e8ee]" /></div>
            </div>
            <div className="num mt-1 text-center text-[11px] font-medium text-mute">02:{String(1 + i * 2).padStart(2, "0")}</div>
          </div>))}
      </div>
      <div className="mt-5 grid grid-cols-3 divide-x divide-line rounded-ctl bg-raised py-3 text-center">
        {[["테스트 진행", "3일차"], ["참여 기기", "16대"], ["총 실행 횟수", "48회"]].map(([k, v]) => <div key={k}><div className="text-[12px] font-medium text-mute">{t(k)}</div><div className="num mt-0.5 text-[16px] font-bold">{t(v)}</div></div>)}
      </div>
    </div>
  );
}

export function Home() {
  const { t } = useI18n();
  const devices = useLoad(() => get("/public/devices"));
  const products = useLoad<any[]>(() => get("/public/products"));
  const plan = (products.data || []).find((p) => !p.is_quote);
  const steps: [typeof ListChecks, string, string][] = [
    [Users, "테스터 목록 추가", "테스터 목록 CSV를 받아 Play Console 비공개 테스트의 테스터로 추가합니다"],
    [Smartphone, "앱 등록", "Play 스토어 링크나 패키지명만 넣으면 앱 정보를 불러옵니다"],
    [Download, "결제 후 설치 요청", "버튼 한 번이면 검사 기기가 차례로 앱을 설치합니다"],
    [ListChecks, "매일 실행 기록 확인", "기기별 실행 화면과 실행 횟수를 날짜별로 확인합니다"]];
  const feats: [typeof ListChecks, string, string][] = [
    [Smartphone, "실제 Android 기기", "에뮬레이터가 아닌 실기기에서 Play 스토어로 앱을 설치하고 실행합니다"],
    [Clock, "매일 오전 2시 자동 실행", "테스트 기간 동안 하루도 빠지지 않고 앱을 실행하고 화면을 남깁니다"],
    [RefreshCw, "새 버전 자동 업데이트", "스토어에 새 버전을 올리면 실행 전에 먼저 업데이트합니다"],
    [ImageIcon, "기기별 실행 화면", "어느 기기에서 언제 실행했는지 화면 캡처로 바로 확인합니다"],
    [Bug, "크래시·ANR 기록", "실행 중 발생한 크래시와 응답 없음을 로그와 함께 기록합니다"],
    [FileText, "보고서와 신청 참고자료", "PDF·Excel 보고서와 프로덕션 신청에 참고할 기록 요약을 제공합니다"]];
  return (
    <>
      <div className="bg-[#f3f7ff]">
        <Section className="grid items-center gap-12 py-14 lg:grid-cols-[1fr_1.05fr] lg:py-20">
          <div>
            <span className="inline-flex h-8 items-center rounded-full bg-card px-3.5 text-[13px] font-bold text-accent shadow-sm2">{t("Google Play 비공개 테스트용")}</span>
            <h1 className="mt-5 text-[36px] font-extrabold leading-[1.25] tracking-[-0.03em] sm:text-[52px]">{t("비공개 테스트 14일,")}<br />{t("실기기 16대가")}<br /><span className="text-accent">{t("매일 실행합니다")}</span></h1>
            <p className="mt-6 max-w-[32rem] text-[17px] leading-8 text-sub">{t("테스터 목록을 추가하고 앱만 등록하세요. 설치, 매일 실행, 업데이트 확인, 실행 화면 기록까지 자동으로 진행합니다")}</p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/register"><Button variant="primary" size="lg">{plan ? `${won(plan.price)}${t("으로 시작하기")}` : t("시작하기")}</Button></Link>
              <Link to="/how-it-works"><Button size="lg" className="!bg-card">{t("이용 방법 보기")}</Button></Link>
            </div>
            <p className="mt-5 text-[14px] text-mute">{t("앱 1개 기준 · 부가세 포함 · 12대 이상 설치되지 않으면 전액 환불")}</p>
          </div>
          <RecordPreview />
        </Section>
      </div>

      <Section className="py-20">
        <H2 kicker="진행 순서">{t("등록부터 실행 기록까지 네 단계")}</H2>
        <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{steps.map(([Icon, title, body], i) => (
          <li key={title} className="rounded-card bg-[#f7f8fa] p-6">
            <div className="flex items-center justify-between"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-card text-accent shadow-sm2"><Icon size={22} strokeWidth={1.75} /></span><span className="num text-[14px] font-bold text-mute">{i + 1} / 4</span></div>
            <h3 className="mt-5 text-[18px] font-bold">{t(title)}</h3><p className="mt-2 text-[15px] leading-6 text-sub">{t(body)}</p>
          </li>))}</ol>
      </Section>

      <div className="bg-[#f7f8fa]">
        <Section className="py-20">
          <H2 kicker="제공 내용">{t("테스트 기간 동안 이렇게 진행합니다")}</H2>
          <div className="mt-10 grid gap-x-10 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">{feats.map(([Icon, title, body]) => (
            <div key={title} className="flex gap-4"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent"><Icon size={22} strokeWidth={1.75} /></span>
              <div><h3 className="text-[17px] font-bold">{t(title)}</h3><p className="mt-1.5 text-[15px] leading-6 text-sub">{t(body)}</p></div></div>))}</div>
        </Section>
      </div>

      <Section className="py-20">
        <H2 kicker="가격">{t("요금제는 하나입니다")}</H2>
        <div className="mt-10"><PlanCard plan={plan} /></div>
      </Section>

      <Section className="pb-20">
        <div className="flex flex-col items-start justify-between gap-6 rounded-panel bg-accent px-8 py-10 text-white sm:flex-row sm:items-center sm:px-12">
          <div><h2 className="text-[26px] font-bold leading-9">{t("지금 앱을 등록해 보세요")}</h2><p className="mt-2 text-[16px] text-white/80">{devices.data?.total ? `${t("현재 연결된 검사 기기")} ${devices.data.total}${t("대")}` : t("가입은 무료이고, 결제 전까지 비용이 들지 않습니다")}</p></div>
          <Link to="/register"><Button size="lg" className="!bg-white !text-accent hover:!bg-[#f3f7ff]">{t("무료로 가입하기")}</Button></Link>
        </div>
      </Section>
    </>
  );
}

function PlanCard({ plan }: { plan: any }) {
  const { t } = useI18n();
  const inc = ["검사 기기 16대, 필수 기간 14일 + 여유 기간 4일 = 18일", "매일 오전 2시(한국시간) 앱 실행, 실행 전 스토어 새 버전 업데이트", "일별 실행 기록·화면 캡처, 보고서, 프로덕션 신청 참고자료"];
  return (
    <div className="grid overflow-hidden rounded-panel border border-line lg:grid-cols-[1fr_1.15fr]">
      <div className="bg-card p-8 sm:p-10">
        <div className="text-[15px] font-bold text-accent">{plan?.name || t("비공개 테스트 18일")}</div>
        <div className="mt-3 flex items-end gap-2"><span className="num text-[48px] font-extrabold leading-none tracking-[-0.03em]">{plan ? plan.price.toLocaleString("ko-KR") : "-"}</span><span className="pb-1 text-[20px] font-bold">{t("원")}</span><span className="pb-1.5 text-[14px] text-mute">/ {t("앱 1개 · 부가세 포함")}</span></div>
        <ul className="mt-8 space-y-3.5">{inc.map((x) => <li key={x} className="flex gap-3 text-[15px] leading-6 text-sub"><span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent text-white"><CheckIcon size={13} strokeWidth={3} /></span>{t(x)}</li>)}</ul>
        <Link to="/dashboard/new-test" className="mt-9 block"><Button variant="primary" size="lg" className="w-full">{t("테스트 신청하기")}</Button></Link>
      </div>
      <div className="grid content-start gap-8 bg-[#f7f8fa] p-8 sm:p-10">
        <div><h3 className="text-[18px] font-bold">{t("무료 연장")}</h3><p className="mt-2 text-[15px] leading-7 text-sub">{t("테스트 시작 후 14일 안에 앱을 2회 이상 업데이트한 이력이 확인되면 추가 결제 없이 18일을 1회 연장합니다")}</p></div>
        <div><h3 className="text-[18px] font-bold">{t("환불")}</h3>
          <dl className="mt-3 space-y-3 text-[15px] leading-6">
            <div className="flex gap-3"><dt className="inline-flex h-6 shrink-0 items-center rounded-md bg-ok-soft px-2 text-[12px] font-semibold text-ok">{t("전액 환불")}</dt><dd className="text-sub">{t("12대 이상의 검사 기기에 앱이 설치되지 않은 경우, 서비스 장애로 피해가 발생한 경우")}</dd></div>
            <div className="flex gap-3"><dt className="inline-flex h-6 shrink-0 items-center rounded-md bg-bad-soft px-2 text-[12px] font-semibold text-bad">{t("환불 불가")}</dt><dd className="text-sub">{t("12대 이상 설치되어 테스트가 시작된 경우, TWA 앱으로 확인된 경우")}</dd></div>
          </dl></div>
        <Link to="/legal/refund" className="text-[14px] font-semibold text-accent">{t("가격 및 환불 정책 전문 보기")} →</Link>
      </div>
    </div>
  );
}

const Page = ({ title, lead, children }: { title: string; lead?: string; children: ReactNode }) => {
  const { t } = useI18n();
  return <><div className="bg-[#f7f8fa]"><Section className="py-12 sm:py-14"><h1 className="text-[30px] font-extrabold leading-[1.3] tracking-[-0.03em] sm:text-[38px]">{t(title)}</h1>{lead && <p className="mt-3 max-w-2xl text-[17px] leading-7 text-sub">{t(lead)}</p>}</Section></div><Section className="py-12">{children}</Section></>;
};

export function Service() {
  const { t } = useI18n();
  const items: [typeof ListChecks, string, string][] = [[Smartphone, "실기기 폰팜", "에뮬레이터가 아닌 실제 Android 기기에서 검사합니다. 기기는 표준 ADB로 제어합니다"],
    [Clock, "정해진 기간 반복 검사", "상품별 기간 동안 하루 정해진 횟수만큼 자동으로 검사하고, 실패한 작업은 자동 재시도합니다"],
    [ImageIcon, "기기별 결과와 증적", "기기별 성공·실패, 실제 스크린샷, 크래시·ANR 로그, 성능 측정값을 그대로 보여줍니다"],
    [Bug, "규칙 기반 오류 분석", "크래시 로그를 유형과 심각도로 분류하고 중복 오류를 묶습니다. AI 분석은 선택 사항이며 '추정'으로 구분 표시합니다"],
    [ListChecks, "검사 시나리오", "UI 요소 식별자 기반으로 버튼 선택, 입력, 화면 검증 단계를 직접 구성할 수 있습니다"],
    [FileText, "PDF·Excel 보고서", "종합, 일별, 기기별, 버전별, 오류 분석, 성능, 스크린샷, 완료 보고서를 내려받습니다"]];
  return (
    <Page title="서비스 소개" lead="구글자동테스터는 Android 앱 개발자를 위한 실기기 자동화 품질검사 서비스입니다">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{items.map(([Icon, h, b]) => <div key={h} className="rounded-card border border-line p-6"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-soft text-accent"><Icon size={22} strokeWidth={1.75} /></span><h2 className="mt-5 text-[18px] font-bold">{t(h)}</h2><p className="mt-2 text-[15px] leading-6 text-sub">{t(b)}</p></div>)}</div>
      <div className="mt-10 max-w-3xl space-y-3">
        <Notice>{t("본 서비스는 Google의 공식 서비스가 아닌 독립적인 제3자 앱 품질검사 서비스입니다")}</Notice>
        <Notice>{t("기기 자동 검사 기록은 Google Play 비공개 테스트의 인간 테스터 참여로 집계되지 않으며, 테스트 참여 요건을 대신하지 않습니다. 프로덕션 승인을 보장하지 않습니다")}</Notice>
      </div>
    </Page>
  );
}

export function HowTo() {
  const { t } = useI18n();
  const steps = [["회원가입", "이메일로 가입합니다"],
    ["비공개 테스트 출시", "Play Console에서 비공개 테스트 트랙에 앱을 출시합니다"],
    ["테스터 목록 추가", "대시보드의 테스터 목록에서 CSV를 받아 Play Console 비공개 테스트의 이메일 목록에 모두 추가합니다"],
    ["앱 등록", "확인 항목을 체크하고 Play 스토어 링크나 패키지명을 넣으면 앱 정보를 불러옵니다"],
    ["테스트 신청·결제", "결제가 서버에서 검증되면 주문이 확정되고 검사 기기가 배정됩니다"],
    ["설치 요청", "앱 화면에서 설치 요청을 누르면 검사 기기가 차례로 앱을 설치합니다. 12대 이상 설치되면 테스트 기간이 시작됩니다"],
    ["매일 실행", "매일 오전 2시(한국시간)에 앱을 실행하고 실행 화면을 기록합니다. 새 버전은 실행 전에 업데이트합니다"],
    ["완료·보고서", "기간이 끝나면 최종 보고서가 자동 생성되고 알림을 보냅니다"]];
  return (
    <Page title="이용 방법" lead="앱을 비공개 테스트로 출시한 뒤 아래 순서대로 진행합니다">
      <ol className="max-w-3xl space-y-3">{steps.map(([h, b], i) => (
        <li key={h} className="flex gap-5 rounded-card border border-line p-5 sm:p-6"><span className="num flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-[15px] font-bold text-white">{i + 1}</span><div><h2 className="text-[17px] font-bold leading-9">{t(h)}</h2><p className="text-[15px] leading-6 text-sub">{t(b)}</p></div></li>))}</ol>
      <div className="mt-8"><Link to="/register"><Button variant="primary" size="lg">{t("테스트 신청하기")}</Button></Link></div>
    </Page>
  );
}

export function Pricing() {
  const { t } = useI18n();
  const products = useLoad<any[]>(() => get("/public/products"));
  const list = products.data || [];
  const plan = list.find((p) => !p.is_quote);
  return (
    <Page title="가격 및 환불 정책" lead="단일 요금제입니다. 앱 1개당 8,000원(부가세 포함)으로 18일 동안 검사 기기에서 매일 앱을 실행합니다">
      <PlanCard plan={plan} />
      {list.length > 1 && <div className="mt-8"><PriceTable products={list} /></div>}
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="rounded-card border border-line p-6"><h2 className="text-[18px] font-bold">{t("무료 연장 안내")}</h2><p className="mt-2 text-[15px] leading-7 text-sub">{t("2~3일 간격 업데이트를 권장합니다. 조건에 해당하지 않으면 다시 결제하여 진행할 수 있습니다")}</p></div>
        <div className="rounded-card border border-line p-6"><h2 className="text-[18px] font-bold">{t("환불 절차")}</h2><p className="mt-2 text-[15px] leading-7 text-sub">{t("시작 전에는 앱 화면에서 바로 환불됩니다. 장애 환불은 고객 문의 후 영업일 3~5일 심사, 승인 시 5~7일 안에 결제 수단으로 환불됩니다")}</p></div>
      </div>
      <p className="mt-8 max-w-3xl text-[14px] leading-6 text-mute">{t("검사 기기 수는 실제 검사에 사용되는 기기 수량이며 Google Play 비공개 테스트의 독립적인 참여자 수를 의미하지 않습니다")}</p>
    </Page>
  );
}

function PriceTable({ products }: { products: any[] }) {
  const { t, locale } = useI18n();
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-card">
      <table className="w-full min-w-[720px] text-left text-[15px]">
        <thead><tr className="bg-raised text-[13px] text-sub"><th className="h-11 px-6 font-medium">{t("상품")}</th><th className="px-6 text-right font-medium">{t("검사 기기")}</th><th className="px-6 text-right font-medium">{t("검사 기간")}</th><th className="px-6 text-right font-medium">{t("일일 검사")}</th><th className="px-6 text-right font-medium">{t("가격")}</th><th className="px-6" /></tr></thead>
        <tbody>{products.map((p) => (
          <tr key={p.id} className="border-t border-line">
            <td className="h-16 px-6"><span className="font-bold">{p.name}</span><span className="mt-0.5 block text-[13px] text-mute">{locale === "en" ? p.description_en : p.description}</span></td>
            <td className="num px-6 text-right">{p.is_quote ? "-" : `${p.device_count}${t("대")}`}</td>
            <td className="num px-6 text-right">{p.is_quote ? "-" : `${p.duration_days}${t("일")}`}</td>
            <td className="num px-6 text-right">{p.is_quote ? "-" : `${p.daily_runs}${t("회")}`}</td>
            <td className="num px-6 text-right font-bold">{p.is_quote ? t("별도 견적") : won(p.price)}</td>
            <td className="px-6 text-right"><Link to={p.is_quote ? "/dashboard/support" : "/dashboard/new-test"}><Button size="sm">{t(p.is_quote ? "문의" : "신청")}</Button></Link></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

export function Devices() {
  const { t } = useI18n();
  const d = useLoad(() => get("/public/devices"));
  return (
    <Page title="검사 기기 안내" lead="현재 폰팜에 등록되어 검사에 사용되는 실기기 목록입니다">
      <Card pad={false} title={<>{t("등록 실기기")} <span className="num ml-1 text-accent">{d.data?.total ?? 0}</span></>}>
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
  return <Page title="자주 묻는 질문"><div className="max-w-3xl space-y-3">{(f.data || []).map((q) => <details key={q.id} className="group rounded-card border border-line px-6 py-5 open:bg-[#f7f8fa]"><summary className="cursor-pointer list-none text-[17px] font-bold marker:hidden"><span className="mr-3 text-accent">Q</span>{q.question}</summary><p className="mt-4 whitespace-pre-line text-[15px] leading-7 text-sub">{q.answer}</p></details>)}</div></Page>;
}

export function Notices() {
  const { t } = useI18n();
  const n = useLoad<any[]>(() => get("/public/announcements"));
  return (
    <Page title="공지사항">
      <div className="max-w-3xl">{n.data && !n.data.length && <p className="text-mute">{t("등록된 공지사항이 없습니다")}</p>}
        {(n.data || []).map((a) => <article key={a.id} className="border-b border-line py-6 first:pt-0"><div className="num text-[13px] text-mute">{dt(a.created_at, false)}</div><h2 className="mt-1 text-[18px] font-bold">{a.title}</h2><p className="mt-2 whitespace-pre-line text-[15px] leading-7 text-sub">{a.body}</p></article>)}</div>
    </Page>
  );
}

export function Legal() {
  const { key } = useParams();
  const { locale, t } = useI18n();
  const d = useLoad(() => get(`/public/legal/${key}?locale=${locale}`), [key, locale]);
  return <Page title={d.data?.title || ""}><article className="max-w-3xl whitespace-pre-line text-[15px] leading-8 text-sub">{d.data?.body}</article>{d.data && <p className="num mt-8 text-xs text-mute">{t("최종 수정")} {dt(d.data.updated_at, false)}</p>}</Page>;
}

// ---------------- 인증 화면 ----------------
function AuthShell({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  const { t } = useI18n();
  return <div className="min-h-[calc(100vh-64px)] bg-[#f7f8fa] px-5 py-12 sm:py-16"><div className="mx-auto w-full max-w-[440px] rounded-panel border border-line bg-card p-7 sm:p-9"><h1 className="text-[26px] font-extrabold tracking-[-0.03em]">{t(title)}</h1><div className="mt-7 space-y-4">{children}</div>{footer && <div className="mt-6 text-center text-[14px] font-medium text-sub">{footer}</div>}</div></div>;
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
