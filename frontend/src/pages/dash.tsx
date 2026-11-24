import { Bell, Boxes, ClipboardList, CreditCard, FileText, LayoutDashboard, LifeBuoy, ListChecks, PlusCircle, UserRound, Workflow } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Progress, StackedDays } from "../components/charts";
import { AppShell, type NavGroup } from "../components/shell";
import { Button, Card, Check, Dot, Field, Input, MockTag, Modal, Msg, Notice, PageHead, Select, Stat, Table, Textarea, cx, useAction, useLoad } from "../components/ui";
import { ApiError, clearSession, del, download, get, patch, post, put, storeSession, upload } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dt, num, size, won } from "../lib/format";
import { STATUS, useI18n } from "../lib/i18n";
import { CHECKS } from "./public";

const NAVS: NavGroup[] = [
  { items: [{ to: "/dashboard", label: "대시보드", icon: LayoutDashboard, end: true }, { to: "/dashboard/apps", label: "앱 등록·관리", icon: Boxes },
    { to: "/dashboard/new-test", label: "신규 테스트 신청", icon: PlusCircle }] },
  { label: "검사", items: [{ to: "/dashboard/orders", label: "주문·진행 현황", icon: ClipboardList }, { to: "/dashboard/results", label: "검사 결과", icon: ListChecks },
    { to: "/dashboard/reports", label: "보고서", icon: FileText }, { to: "/dashboard/scenarios", label: "검사 시나리오", icon: Workflow }] },
  { label: "계정", items: [{ to: "/dashboard/payments", label: "결제 내역", icon: CreditCard }, { to: "/dashboard/support", label: "고객 문의", icon: LifeBuoy },
    { to: "/dashboard/notifications", label: "알림", icon: Bell }, { to: "/dashboard/account", label: "마이페이지", icon: UserRound }] },
];
export const DashLayout = () => <AppShell groups={NAVS} home="/dashboard" />;

const MockNote = () => { const { t } = useI18n(); return <Notice tone="warn">{t("모의(MOCK) 결제·모의 장비로 진행된 시험 데이터입니다. 실제 기기 검사 결과가 아닙니다")}</Notice>; };

export function Overview() {
  const { t } = useI18n();
  const nav = useNavigate();
  const d = useLoad(() => get("/dashboard"), [], 30000);
  const x = d.data;
  return (
    <>
      <PageHead title="대시보드" action={<Link to="/dashboard/new-test"><Button variant="primary">{t("신규 테스트 신청")}</Button></Link>} />
      {d.error && <Notice tone="bad">{d.error}</Notice>}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="등록 앱" value={num(x?.apps)} />
        <Stat label="진행 중인 주문" value={num(x?.orders_active)} note={x ? `${t("완료")} ${x.orders_completed} · ${t("결제 대기")} ${x.orders_pending_payment}` : ""} />
        <Stat label="검사 성공률" value={x?.success_rate == null ? "-" : `${x.success_rate}%`} note={x ? `${t("전체")} ${num(x.runs_total)}${t("회")} · ${t("실패")} ${num(x.runs_failed)}` : ""} />
        <Stat label="크래시 / ANR" value={x ? `${num(x.crash_count)} / ${num(x.anr_count)}` : "-"} />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card title={t("일별 검사 결과")} action={<span className="flex gap-4 text-xs text-mute"><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-accent" />{t("성공")}</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-[#a3a3a3]" />{t("실패·수행 불가")}</span></span>}>
          <StackedDays data={x?.daily || []} />
        </Card>
        <Card title={t("진행 중인 검사")} pad={false}>
          {!x?.active_plans?.length && <p className="p-8 text-center text-sm text-mute">{t("진행 중인 검사가 없습니다")}</p>}
          {(x?.active_plans || []).map((p: any) => (
            <button key={p.id} onClick={() => nav(`/dashboard/orders/${p.order_id}`)} className="block w-full border-b border-line px-5 py-4 text-left last:border-0 hover:bg-raised">
              <div className="flex items-center justify-between gap-3"><span className="truncate font-medium">{p.app}</span><Dot status={p.status} /></div>
              <div className="mt-3"><Progress value={p.progress} /></div>
              <div className="num mt-2 flex justify-between text-xs text-mute"><span>{t("남은 기간")} {p.days_left}{t("일")}</span><span>{t("기기")} {p.connected_devices}/{p.assigned_devices}</span></div>
            </button>))}
        </Card>
      </div>
    </>
  );
}

// ---------------- 앱 ----------------
const EMPTY_APP = { name: "", package_name: "", play_url: "", closed_test_url: "", google_group: "", description: "", request_notes: "", languages: [] as string[], test_login_id: "", test_login_password: "", ownership_confirmed: false, closed_test_started_on: "", improvements: "" };

function AppForm({ initial, onSaved, onClose }: { initial?: any; onSaved: (app: any) => void; onClose: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [f, setF] = useState<any>(initial ? { ...EMPTY_APP, ...initial, test_login_id: "", test_login_password: "" } : EMPTY_APP);
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = { ...f, languages: typeof f.languages === "string" ? f.languages.split(",").map((s: string) => s.trim()).filter(Boolean) : f.languages };
    if (initial && !f.test_login_id && !f.test_login_password) { delete body.test_login_id; delete body.test_login_password; }
    const app = await a.run(() => (initial ? put(`/apps/${initial.id}`, body) : post("/apps", body)));
    if (app) onSaved(app);
  };
  return (
    <Modal title={initial ? "앱 정보 수정" : "앱 등록"} onClose={onClose} wide>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="앱 이름"><Input value={f.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <Field label="패키지명" hint="예: com.example.app"><Input className="font-mono" value={f.package_name} onChange={(e) => set("package_name", e.target.value)} required disabled={!!initial} /></Field>
        <Field label="Google Play 주소"><Input value={f.play_url} onChange={(e) => set("play_url", e.target.value)} placeholder="https://" /></Field>
        <Field label="비공개 테스트 안내 링크"><Input value={f.closed_test_url} onChange={(e) => set("closed_test_url", e.target.value)} placeholder="https://" /></Field>
        <Field label="지원 언어" hint="쉼표로 구분"><Input value={Array.isArray(f.languages) ? f.languages.join(", ") : f.languages} onChange={(e) => set("languages", e.target.value)} placeholder="ko, en" /></Field>
        <Field label="Google Groups"><Input value={f.google_group} onChange={(e) => set("google_group", e.target.value)} /></Field>
        <Field label="테스트용 로그인 아이디" hint={initial?.has_test_login ? "저장되어 있음. 변경할 때만 입력" : "암호화하여 저장"}><Input value={f.test_login_id} onChange={(e) => set("test_login_id", e.target.value)} autoComplete="off" /></Field>
        <Field label="테스트용 로그인 비밀번호"><Input type="password" value={f.test_login_password} onChange={(e) => set("test_login_password", e.target.value)} autoComplete="new-password" /></Field>
        <div className="sm:col-span-2"><Field label="앱 설명"><Textarea value={f.description} onChange={(e) => set("description", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><Field label="검사 요청사항"><Textarea value={f.request_notes} onChange={(e) => set("request_notes", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><Check checked={f.ownership_confirmed} disabled={initial?.ownership_confirmed} onChange={(e) => set("ownership_confirmed", e.target.checked)} label={t("이 앱의 소유자이거나 검사 권한을 보유하고 있음을 확인합니다")} /></div>
        <div className="space-y-3 sm:col-span-2"><Msg a={a} /><div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>{t("취소")}</Button><Button variant="primary" disabled={a.busy}>{t("저장")}</Button></div></div>
      </form>
    </Modal>
  );
}

export function Apps() {
  const { t } = useI18n();
  const nav = useNavigate();
  const apps = useLoad<any[]>(() => get("/apps"));
  const [form, setForm] = useState(false);
  return (
    <>
      <PageHead title="앱 등록·관리" desc="검사 권한을 보유한 앱만 등록할 수 있습니다" action={<Button variant="primary" onClick={() => setForm(true)}>{t("앱 등록")}</Button>} />
      <Card pad={false}>
        <Table rows={apps.data} onRow={(r) => nav(`/dashboard/apps/${r.id}`)} empty="등록된 앱이 없습니다" cols={[
          { key: "name", label: "앱", render: (r) => <span className="flex items-center gap-3">{r.icon_url ? <img src={r.icon_url} alt="" className="h-7 w-7 rounded-md border border-line object-cover" /> : <span className="h-7 w-7 rounded-md bg-raised" />}<span className="font-medium">{r.name}</span></span> },
          { key: "package_name", label: "패키지명", mono: true },
          { key: "v", label: "최신 버전", mono: true, render: (r) => (r.versions[0] ? `${r.versions[0].version_name} (${r.versions[0].version_code})` : "-") },
          { key: "n", label: "버전 수", right: true, render: (r) => r.versions.length },
          { key: "created_at", label: "등록일", mono: true, render: (r) => dt(r.created_at, false) }]} />
      </Card>
      {form && <AppForm onClose={() => setForm(false)} onSaved={(app) => nav(`/dashboard/apps/${app.id}`)} />}
    </>
  );
}

function VersionUpload({ app, onDone }: { app: any; onDone: () => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ version_name: "", version_code: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [warn, setWarn] = useState("");
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setError(""); setWarn(""); setPct(0);
    const form = new FormData();
    Object.entries(f).forEach(([k, v]) => form.append(k, v));
    if (file) form.append("file", file);
    try {
      const res = await upload(`/apps/${app.id}/versions`, form, setPct);
      setPct(null); setFile(null); setF({ version_name: "", version_code: "", notes: "" });
      if (res.warning) setWarn(res.warning);
      onDone();
    } catch (err: any) { setPct(null); setError(err.message); }
  };
  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-[1fr_1fr_2fr]">
      <Field label="앱 버전"><Input value={f.version_name} onChange={(e) => setF({ ...f, version_name: e.target.value })} placeholder="1.0.0" required /></Field>
      <Field label="버전 코드"><Input type="number" min={1} value={f.version_code} onChange={(e) => setF({ ...f, version_code: e.target.value })} required /></Field>
      <Field label="APK 파일" hint="APK가 없으면 설치 검사는 '미수행'으로 기록됩니다"><input type="file" accept=".apk" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block h-9 w-full text-[13px] text-sub file:mr-3 file:h-9 file:rounded-ctl file:border file:border-line file:bg-card file:px-3 file:text-[13px]" /></Field>
      <div className="sm:col-span-3"><Field label="변경 내용"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
      <div className="space-y-3 sm:col-span-3">
        {pct !== null && <div><Progress value={pct} /><div className="num mt-1 text-xs text-mute">{t("업로드")} {pct}%</div></div>}
        {error && <Notice tone="bad">{error} <button type="button" className="ml-2 underline" onClick={() => submit()}>{t("다시 시도")}</button></Notice>}
        {warn && <Notice tone="warn">{warn}</Notice>}
        <Button variant="primary" disabled={pct !== null}>{t("버전 등록")}</Button>
      </div>
    </form>
  );
}

export function AppDetail() {
  const { t } = useI18n();
  const { id } = useParams();
  const nav = useNavigate();
  const app = useLoad(() => get(`/apps/${id}`), [id]);
  const ct = useLoad(() => get(`/apps/${id}/closed-test`), [id]);
  const [edit, setEdit] = useState(false);
  const [emails, setEmails] = useState("");
  const [notes, setNotes] = useState("");
  const a = useAction();
  const iconRef = useRef<HTMLInputElement>(null);
  if (!app.data) return <p className="text-mute">{app.error || t("불러오는 중")}</p>;
  const x = app.data;
  const reloadAll = () => { app.reload(); ct.reload(); };
  return (
    <>
      <PageHead title={x.name} desc={x.package_name} action={<div className="flex gap-2">
        <input ref={iconRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); a.run(() => upload(`/apps/${id}/icon`, fd, () => {})).then(app.reload); }} />
        <Button onClick={() => iconRef.current?.click()}>{t("아이콘 변경")}</Button><Button onClick={() => setEdit(true)}>{t("정보 수정")}</Button>
        <Button variant="danger" onClick={() => confirm(t("이 앱을 삭제할까요?")) && a.run(() => del(`/apps/${id}`)).then((r) => r && nav("/dashboard/apps"))}>{t("삭제")}</Button>
        <Link to={`/dashboard/new-test?app=${id}`}><Button variant="primary">{t("테스트 신청")}</Button></Link></div>} />
      <div className="space-y-4">
        <Msg a={a} />
        <Card title={t("버전 이력")} pad={false}>
          <Table rows={x.versions} empty="등록된 버전이 없습니다" cols={[
            { key: "version_name", label: "버전", mono: true }, { key: "version_code", label: "버전 코드", mono: true },
            { key: "file", label: "APK", render: (r) => (r.file ? <span className="num text-sub">{r.file.filename} · {size(r.file.size)}</span> : <span className="text-mute">{t("미등록")}</span>) },
            { key: "sha", label: "SHA-256", mono: true, render: (r) => (r.file ? <span title={r.file.sha256}>{r.file.sha256.slice(0, 12)}…</span> : "-") },
            { key: "st", label: "파일 상태", render: (r) => (r.file ? <Dot status={r.file.status} /> : "-") },
            { key: "created_at", label: "등록일", mono: true, render: (r) => dt(r.created_at) }]} />
        </Card>
        <Card title={t("새 버전 등록")}><VersionUpload app={x} onDone={app.reload} /></Card>
        <Card title={t("Google Play 비공개 테스트 관리")}>
          <Notice>{ct.data?.notice}</Notice>
          <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="실제 테스터(참여 확인)" value={`${ct.data?.human_testers_confirmed ?? 0} / ${ct.data?.human_testers_invited ?? 0}`} note={t("직접 관리하는 사람 테스터")} />
            <Stat label="실기기 자동 검사 기기" value={num(ct.data?.real_devices_tested)} note={t("테스터 참여와 별개")} />
            <Stat label="기기 Google 계정 확인" value={num(ct.data?.device_google_accounts_confirmed)} note={t("운영자 확인 항목")} />
            <Stat label="테스트 경과일" value={ct.data?.days_since_start ?? "-"} note={x.closed_test_started_on || t("시작일 미입력")} />
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div>
              <Field label="실제 테스터 이메일 추가" hint="줄바꿈 또는 쉼표로 구분"><Textarea value={emails} onChange={(e) => setEmails(e.target.value)} /></Field>
              <div className="mt-3 flex gap-2"><Button onClick={() => a.run(() => post(`/apps/${id}/testers`, { emails: emails.split(/[\s,;]+/).filter(Boolean) })).then(() => { setEmails(""); ct.reload(); })}>{t("추가")}</Button>
                <Button onClick={() => download(`/apps/${id}/testers.csv`, `testers-${id}.csv`)}>{t("CSV 내보내기")}</Button>
                <Button onClick={() => get(`/apps/${id}/production-notes`).then((r) => setNotes(r.text))}>{t("프로덕션 신청 참고자료")}</Button></div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="비공개 테스트 시작일"><Input type="date" defaultValue={x.closed_test_started_on} onBlur={(e) => e.target.value !== x.closed_test_started_on && put(`/apps/${id}`, { ...x, closed_test_started_on: e.target.value }).then(reloadAll)} /></Field>
              <div className="sm:col-span-2"><Field label="테스트 결과를 반영한 개선사항"><Textarea defaultValue={x.improvements} onBlur={(e) => e.target.value !== x.improvements && put(`/apps/${id}`, { ...x, improvements: e.target.value }).then(reloadAll)} /></Field></div>
            </div>
          </div>
          <div className="-mx-5 mt-6 border-t border-line">
            <Table rows={ct.data?.testers} empty="등록된 실제 테스터가 없습니다" cols={[
              { key: "email", label: "이메일" },
              { key: "status", label: "상태", render: (r) => <Select className="!h-8 w-32" value={r.status} onChange={(e) => patch(`/apps/${id}/testers/${r.id}`, { status: e.target.value }).then(ct.reload)}>{["invited", "joined", "confirmed"].map((s) => <option key={s} value={s}>{t(STATUS[s])}</option>)}</Select> },
              { key: "feedback", label: "피드백", render: (r) => <Input className="!h-8" defaultValue={r.feedback} placeholder={t("테스터 피드백 기록")} onBlur={(e) => e.target.value !== r.feedback && patch(`/apps/${id}/testers/${r.id}`, { feedback: e.target.value }).then(ct.reload)} /> },
              { key: "x", label: "", right: true, render: (r) => <Button size="sm" variant="ghost" onClick={() => del(`/apps/${id}/testers/${r.id}`).then(ct.reload)}>{t("삭제")}</Button> }]} />
          </div>
        </Card>
      </div>
      {edit && <AppForm initial={x} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); reloadAll(); }} />}
      {notes && <Modal title="프로덕션 신청 참고자료" onClose={() => setNotes("")} wide><pre className="whitespace-pre-wrap rounded-ctl bg-raised p-4 font-sans text-[13px] leading-6">{notes}</pre><div className="mt-4 text-right"><Button onClick={() => navigator.clipboard.writeText(notes)}>{t("복사")}</Button></div></Modal>}
    </>
  );
}

// ---------------- 신규 테스트 신청 ----------------
export function NewTest() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const apps = useLoad<any[]>(() => get("/apps"));
  const products = useLoad<any[]>(() => get("/public/products"));
  const scenarios = useLoad<any[]>(() => get("/scenarios"));
  const a = useAction();
  const [f, setF] = useState({ app_id: sp.get("app") || "", app_version_id: "", product_id: "", scenario_id: "", coupon_code: "", desired_start: "", desired_android: "", request_notes: "" });
  const [quote, setQuote] = useState<any>(null);
  const [idem] = useState(() => crypto.randomUUID());
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const app = apps.data?.find((x) => String(x.id) === f.app_id);
  const product = products.data?.find((x) => String(x.id) === f.product_id);
  useEffect(() => { if (app && !app.versions.some((v: any) => String(v.id) === f.app_version_id)) set("app_version_id", app.versions[0] ? String(app.versions[0].id) : ""); }, [app]); // eslint-disable-line
  useEffect(() => {
    setQuote(null);
    if (!f.product_id) return;
    post("/orders/quote", { product_id: Number(f.product_id), coupon_code: f.coupon_code }).then(setQuote).catch((e) => setQuote({ error: e.message }));
  }, [f.product_id, f.coupon_code]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const order = await a.run(() => post("/orders", { app_id: Number(f.app_id), app_version_id: Number(f.app_version_id), product_id: Number(f.product_id),
      scenario_id: f.scenario_id ? Number(f.scenario_id) : null, coupon_code: f.coupon_code, desired_android: f.desired_android, request_notes: f.request_notes,
      desired_start: f.desired_start ? new Date(f.desired_start).toISOString() : null }, { "Idempotency-Key": idem }));
    if (order) nav(`/dashboard/pay/${order.id}`);
  };
  return (
    <>
      <PageHead title="신규 테스트 신청" />
      {apps.data && !apps.data.length && <Notice tone="warn">{t("먼저 앱을 등록해 주세요")} <Link to="/dashboard/apps" className="underline">{t("앱 등록")}</Link></Notice>}
      <form onSubmit={submit} className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-4">
          <Card title={t("1. 앱과 버전")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="앱"><Select value={f.app_id} onChange={(e) => set("app_id", e.target.value)} required><option value="">{t("선택")}</option>{(apps.data || []).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.package_name})</option>)}</Select></Field>
              <Field label="검사할 버전"><Select value={f.app_version_id} onChange={(e) => set("app_version_id", e.target.value)} required><option value="">{t("선택")}</option>{(app?.versions || []).map((v: any) => <option key={v.id} value={v.id} disabled={v.file?.status === "quarantined"}>{v.version_name} ({v.version_code}){v.file ? "" : ` · ${t("APK 없음")}`}</option>)}</Select></Field>
            </div>
            {app && !app.versions.length && <div className="mt-3"><Notice tone="warn">{t("이 앱에 등록된 버전이 없습니다")} <Link className="underline" to={`/dashboard/apps/${app.id}`}>{t("버전 등록")}</Link></Notice></div>}
          </Card>
          <Card title={t("2. 상품")} pad={false}>
            {(products.data || []).filter((p) => !p.is_quote).map((p) => (
              <label key={p.id} className={cx("flex cursor-pointer items-center gap-4 border-b border-line px-5 py-4 last:border-0 transition-colors duration-150", String(p.id) === f.product_id ? "bg-accent-soft" : "hover:bg-raised")}>
                <input type="radio" name="product" className="accent-[#0f766e]" checked={String(p.id) === f.product_id} onChange={() => set("product_id", String(p.id))} required />
                <span className="flex-1"><span className="font-medium">{p.name}</span><span className="num ml-3 text-[13px] text-sub">{p.device_count}{t("대")} · {p.duration_days}{t("일")} · {t("하루")} {p.daily_runs}{t("회")}</span></span>
                <span className="num">{won(p.price)}</span>
              </label>))}
          </Card>
          <Card title={t("3. 검사 옵션")}>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="검사 시나리오" hint={product && !product.checks.includes("scenario") ? "선택한 상품은 시나리오 검사를 포함하지 않습니다" : undefined}><Select value={f.scenario_id} onChange={(e) => set("scenario_id", e.target.value)}><option value="">{t("기본 검사만")}</option>{(scenarios.data || []).map((s) => <option key={s.id} value={s.id}>{s.name} v{s.version}</option>)}</Select></Field>
              <Field label="희망 시작일"><Input type="datetime-local" value={f.desired_start} onChange={(e) => set("desired_start", e.target.value)} /></Field>
              <Field label="희망 Android 버전" hint="비워 두면 전체 기기"><Input value={f.desired_android} onChange={(e) => set("desired_android", e.target.value)} placeholder="13" /></Field>
              <div className="sm:col-span-3"><Field label="검사 요청사항"><Textarea value={f.request_notes} onChange={(e) => set("request_notes", e.target.value)} /></Field></div>
            </div>
          </Card>
        </div>
        <div><div className="sticky top-20 space-y-4">
          <Card title={t("결제 금액")}>
            {product && <ul className="mb-4 space-y-1.5 text-[13px] text-sub">{product.checks.map((c: string) => <li key={c} className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-accent" />{t(CHECKS[c] || c)}</li>)}</ul>}
            <Field label="쿠폰 코드"><Input value={f.coupon_code} onChange={(e) => set("coupon_code", e.target.value.toUpperCase())} /></Field>
            {quote?.error && <div className="mt-3"><Notice tone="bad">{quote.error}</Notice></div>}
            <dl className="num mt-4 space-y-2 text-sm"><div className="flex justify-between text-sub"><dt className="font-sans">{t("상품 금액")}</dt><dd>{won(quote?.amount)}</dd></div>
              <div className="flex justify-between text-sub"><dt className="font-sans">{t("할인")}</dt><dd>-{won(quote?.discount)}</dd></div>
              <div className="flex justify-between border-t border-line pt-3 text-[18px] font-medium"><dt className="font-sans">{t("결제 금액")}</dt><dd>{won(quote?.final_amount)}</dd></div></dl>
            <div className="mt-4 space-y-3"><Msg a={a} /><Button variant="primary" size="lg" className="w-full" disabled={a.busy || !!quote?.error}>{t("주문하고 결제하기")}</Button></div>
          </Card>
          <p className="text-xs leading-5 text-mute">{t("검사 기기 수는 실제 검사 기기 수량이며 Google Play 비공개 테스트의 독립적인 참여자 수를 의미하지 않습니다")}</p>
        </div></div>
      </form>
    </>
  );
}

// ---------------- 결제 ----------------
function loadToss(): Promise<any> {
  return new Promise((resolve, reject) => {
    if ((window as any).TossPayments) return resolve((window as any).TossPayments);
    const s = document.createElement("script");
    s.src = "https://js.tosspayments.com/v2/standard";
    s.onload = () => resolve((window as any).TossPayments);
    s.onerror = () => reject(new Error("결제 모듈을 불러오지 못했습니다"));
    document.head.appendChild(s);
  });
}

export function Pay() {
  const { t } = useI18n();
  const { id } = useParams();
  const nav = useNavigate();
  const order = useLoad(() => get(`/orders/${id}`), [id]);
  const cfg = useLoad(() => get("/payments/config"));
  const a = useAction();
  const o = order.data;
  const payToss = (method: string) => a.run(async () => {
    const prep = await post("/payments/prepare", { order_id: Number(id) });
    const Toss = await loadToss();
    await Toss(prep.client_key).payment({ customerKey: prep.customer_key }).requestPayment({
      method, amount: { currency: "KRW", value: prep.amount }, orderId: prep.order_no, orderName: prep.order_name,
      successUrl: `${location.origin}/pay/success`, failUrl: `${location.origin}/pay/fail` });
  });
  const payMock = (outcome: string) => a.run(async () => {
    await post("/payments/prepare", { order_id: Number(id) });
    const issued = await post("/payments/mock/issue", { order_id: Number(id), outcome });
    await post("/payments/confirm", issued);
    nav(`/dashboard/orders/${id}`);
  });
  if (!o) return <p className="text-mute">{order.error || t("불러오는 중")}</p>;
  return (
    <div className="mx-auto max-w-xl">
      <PageHead title="결제" desc={o.order_no} />
      <Card>
        <dl className="space-y-3 text-sm"><div className="flex justify-between"><dt className="text-sub">{t("앱")}</dt><dd>{o.app.name} <span className="num text-mute">{o.version}</span></dd></div>
          <div className="flex justify-between"><dt className="text-sub">{t("상품")}</dt><dd>{o.product.name} <span className="num text-mute">{o.product.device_count}{t("대")} · {o.product.duration_days}{t("일")}</span></dd></div>
          <div className="num flex justify-between border-t border-line pt-3 text-[20px] font-medium"><dt className="font-sans">{t("결제 금액")}</dt><dd>{won(o.final_amount)}</dd></div></dl>
        <div className="mt-6 space-y-3">
          {o.status !== "pending_payment" ? <><Notice tone="ok">{t("이미 처리된 주문입니다")}</Notice><Link to={`/dashboard/orders/${id}`}><Button className="w-full">{t("주문 보기")}</Button></Link></> :
            !cfg.data ? null : !cfg.data.enabled ? <Notice tone="warn">{t("현재 결제가 준비되지 않았습니다. PG 가맹점 인증정보 등록 후 결제할 수 있습니다. 주문은 저장되어 있습니다")}</Notice> :
            cfg.data.mode === "mock" ? <>
              <Notice tone="warn">{t("모의 결제 환경입니다. 실제 금전 거래가 발생하지 않으며, 모의 결제 주문에는 모의 장비만 배정됩니다")}</Notice>
              <div className="grid grid-cols-2 gap-3"><Button variant="primary" size="lg" disabled={a.busy} onClick={() => payMock("success")}>{t("모의 결제 승인")}</Button><Button size="lg" disabled={a.busy} onClick={() => payMock("fail")}>{t("모의 결제 실패")}</Button></div></> :
            <>{cfg.data.mode === "test" && <Notice tone="warn">{t("PG 테스트 모드입니다. 실제 결제가 이루어지지 않습니다")}</Notice>}
              <div className="grid grid-cols-2 gap-3"><Button variant="primary" size="lg" disabled={a.busy} onClick={() => payToss("CARD")}>{t("카드·간편결제")}</Button><Button size="lg" disabled={a.busy} onClick={() => payToss("TRANSFER")}>{t("계좌이체")}</Button></div></>}
          <Msg a={a} />
        </div>
      </Card>
    </div>
  );
}

export function PaySuccess() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [error, setError] = useState("");
  useEffect(() => {
    post("/payments/confirm", { paymentKey: sp.get("paymentKey"), orderId: sp.get("orderId"), amount: Number(sp.get("amount")) })
      .then((r) => nav(`/dashboard/orders/${r.order_id}`, { replace: true })).catch((e) => setError(e.message));
  }, []); // eslint-disable-line
  return <div className="mx-auto max-w-xl py-8">{error ? <><Notice tone="bad">{error}</Notice><Link to="/dashboard/orders"><Button className="mt-4">{t("주문 내역")}</Button></Link></> : <p className="text-mute">{t("결제를 확인하고 있습니다")}</p>}</div>;
}

export function PayFail() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  useEffect(() => { if (sp.get("orderId")) post("/payments/fail", { orderId: sp.get("orderId"), code: sp.get("code") || "", message: sp.get("message") || "" }).catch(() => {}); }, []); // eslint-disable-line
  return <div className="mx-auto max-w-xl py-8"><Notice tone="bad">{t("결제가 완료되지 않았습니다")}: {sp.get("message") || sp.get("code")}</Notice><Link to="/dashboard/orders"><Button className="mt-4">{t("주문 내역")}</Button></Link></div>;
}

// ---------------- 주문 / 검사 ----------------
export function Orders({ resultsMode }: { resultsMode?: boolean }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const orders = useLoad<any[]>(() => get("/orders"), [], 30000);
  const rows = resultsMode ? orders.data?.filter((o) => o.plan) : orders.data;
  return (
    <>
      <PageHead title={resultsMode ? "검사 결과" : "주문·진행 현황"} action={<Link to="/dashboard/new-test"><Button variant="primary">{t("신규 테스트 신청")}</Button></Link>} />
      <Card pad={false}>
        <Table rows={rows} onRow={(r) => nav(`/dashboard/orders/${r.id}${resultsMode ? "?tab=results" : ""}`)} empty={resultsMode ? "검사가 시작된 주문이 없습니다" : "주문 내역이 없습니다"} cols={[
          { key: "order_no", label: "주문번호", mono: true, render: (r) => <span className="flex items-center gap-2">{r.order_no}{r.is_mock && <MockTag />}</span> },
          { key: "app", label: "앱", render: (r) => r.app.name }, { key: "product", label: "상품", render: (r) => r.product.name },
          { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> },
          { key: "progress", label: "진행률", width: "140px", render: (r) => (r.plan ? <Progress value={r.plan.progress} /> : "-") },
          { key: "runs", label: "검사 횟수", right: true, render: (r) => r.plan?.total_runs ?? "-" },
          { key: "rate", label: "성공률", right: true, render: (r) => (r.plan?.success_rate == null ? "-" : `${r.plan.success_rate}%`) },
          resultsMode ? { key: "end", label: "종료일", mono: true, render: (r) => dt(r.plan?.end_at, false) } : { key: "final_amount", label: "결제 금액", right: true, render: (r) => won(r.final_amount) },
          { key: "created_at", label: "주문일", mono: true, render: (r) => dt(r.created_at, false) }]} />
      </Card>
    </>
  );
}

function StepList({ steps }: { steps: any[] }) {
  const { t } = useI18n();
  return <table className="w-full text-[13px]"><tbody>{steps.map((s, i) => (
    <tr key={i} className="border-t border-line align-top"><td className="w-44 py-2 pr-3">{s.name}</td><td className="w-24 py-2"><Dot status={s.status} /></td>
      <td className="py-2 text-sub">{s.expected && <span className="text-mute">{t("기대")}: {s.expected} → </span>}{s.actual}</td><td className="num w-20 py-2 text-right text-mute">{s.duration_ms ? `${s.duration_ms}ms` : ""}</td></tr>))}</tbody></table>;
}

export function OrderDetail() {
  const { t } = useI18n();
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "status";
  const order = useLoad(() => get(`/orders/${id}`), [id], 20000);
  const o = order.data;
  const pid = o?.plan?.id;
  const plan = useLoad(() => (pid ? get(`/plans/${pid}`) : Promise.resolve(null)), [pid], 20000);
  const results = useLoad(() => (pid && tab === "results" ? get(`/plans/${pid}/results`) : Promise.resolve(null)), [pid, tab]);
  const crashes = useLoad(() => (pid && tab === "crashes" ? get(`/plans/${pid}/crashes`) : Promise.resolve(null)), [pid, tab]);
  const shots = useLoad(() => (pid && tab === "screenshots" ? get(`/plans/${pid}/screenshots`) : Promise.resolve(null)), [pid, tab]);
  const reports = useLoad(() => (tab === "reports" ? get("/reports") : Promise.resolve(null)), [tab]);
  const [open, setOpen] = useState<any>(null);
  const [zoom, setZoom] = useState<any>(null);
  const [rep, setRep] = useState({ kind: "comprehensive", fmt: "pdf" });
  const a = useAction();
  if (!o) return <p className="text-mute">{order.error || t("불러오는 중")}</p>;
  const p = plan.data;
  const tabs = [["status", "진행 현황"], ["devices", "기기별 현황"], ["results", "검사 결과"], ["crashes", "오류·크래시"], ["screenshots", "스크린샷"], ["reports", "보고서"]];
  return (
    <>
      <PageHead title={o.app.name} desc={`${o.order_no} · ${o.product.name} · ${o.version}`} action={<div className="flex items-center gap-3"><Dot status={o.status} />
        {o.status === "pending_payment" && <><Link to={`/dashboard/pay/${o.id}`}><Button variant="primary">{t("결제하기")}</Button></Link><Button variant="danger" onClick={() => a.run(() => post(`/orders/${o.id}/cancel`)).then(order.reload)}>{t("주문 취소")}</Button></>}</div>} />
      {o.is_mock && <div className="mb-4"><MockNote /></div>}
      {o.status === "waiting_devices" && <div className="mb-4"><Notice tone="warn">{t("가용 검사 기기가 부족하여 배정 대기 중입니다. 기기가 확보되면 자동으로 시작되며 검사 기간은 시작 시점부터 계산됩니다")}</Notice></div>}
      <Msg a={a} />
      {!o.plan ? (
        <Card title={t("결제 정보")} pad={false}><Table rows={o.payments} empty="결제 내역이 없습니다" cols={[{ key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "method", label: "수단" }, { key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "failure_message", label: "비고" }]} /></Card>
      ) : (
        <>
          <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line">{tabs.map(([k, label]) => <button key={k} onClick={() => setSp({ tab: k })} className={cx("-mb-px h-10 whitespace-nowrap border-b-2 px-3 text-sm transition-colors duration-150", tab === k ? "border-ink text-ink" : "border-transparent text-sub hover:text-ink")}>{t(label)}</button>)}</div>
          {tab === "status" && p && <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Stat label="검사 진행률" value={`${p.progress}%`} note={`${dt(p.start_at, false)} ~ ${dt(p.end_at, false)}`} />
              <Stat label="남은 검사 기간" value={`${p.days_left}${t("일")}`} note={p.next_run_at ? `${t("다음 검사")} ${dt(p.next_run_at)}` : ""} />
              <Stat label="배정 기기 / 현재 연결" value={`${p.assigned_devices} / ${p.connected_devices}`} note={`${t("신청")} ${p.device_count}${t("대")}`} />
              <Stat label="검사 성공률" value={p.success_rate == null ? "-" : `${p.success_rate}%`} note={`${t("완료")} ${p.total_runs} · ${t("실패")} ${p.failed + p.error}`} />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
              <Card title={t("일별 검사 결과")}><StackedDays data={p.daily} /></Card>
              <Card title={t("성능 측정 평균")} pad={false}><Table rows={p.metrics} empty="아직 기록된 검사 결과가 없습니다" cols={[{ key: "metric", label: "항목", mono: true }, { key: "avg", label: "평균", right: true, render: (m: any) => `${m.avg} ${m.unit}` }, { key: "max", label: "최대", right: true, render: (m: any) => `${m.max} ${m.unit}` }, { key: "count", label: "측정", right: true }]} /></Card>
            </div>
            <div className="mt-4"><Card title={t("결제 정보")} pad={false}><Table rows={o.payments} cols={[{ key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "mode", label: "구분", render: (r) => (r.mode === "mock" ? <MockTag /> : r.mode) }, { key: "method", label: "수단" }, { key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "refunded_amount", label: "환불", right: true, render: (r) => won(r.refunded_amount) }, { key: "approved_at", label: "승인일", mono: true, render: (r) => dt(r.approved_at) }, { key: "receipt_url", label: "영수증", render: (r) => (r.receipt_url ? <a className="underline" href={r.receipt_url} target="_blank" rel="noreferrer">{t("보기")}</a> : "-") }]} /></Card></div>
          </>}
          {tab === "devices" && <Card pad={false}><Table rows={p?.devices} empty="배정된 기기가 없습니다" cols={[
            { key: "name", label: "기기" }, { key: "model", label: "모델" }, { key: "android", label: "Android", mono: true }, { key: "resolution", label: "해상도", mono: true },
            { key: "connected", label: "연결", render: (r) => <Dot status={r.connected ? "online" : "offline"} /> }, { key: "status", label: "상태", render: (r) => <Dot status={r.running_job ? "testing" : r.assignment === "active" ? r.status : r.assignment} /> },
            { key: "passed", label: "성공", right: true }, { key: "failed", label: "실패", right: true }, { key: "error", label: "수행 불가", right: true }, { key: "crash", label: "크래시", right: true }, { key: "anr", label: "ANR", right: true }]} /></Card>}
          {tab === "results" && <Card pad={false}><Table rows={results.data} onRow={setOpen} empty="아직 기록된 검사 결과가 없습니다" cols={[
            { key: "finished_at", label: "검사 시각", mono: true, render: (r) => dt(r.finished_at) }, { key: "device", label: "기기" }, { key: "model", label: "모델" }, { key: "android", label: "Android", mono: true },
            { key: "status", label: "결과", render: (r) => <Dot status={r.status} /> }, { key: "steps", label: "단계", right: true, render: (r) => `${r.steps.filter((s: any) => s.status === "passed").length}/${r.steps.length}` },
            { key: "crash_count", label: "크래시", right: true }, { key: "anr_count", label: "ANR", right: true }, { key: "duration_ms", label: "소요", right: true, render: (r) => `${(r.duration_ms / 1000).toFixed(1)}s` }]} /></Card>}
          {tab === "crashes" && <div className="space-y-4">{crashes.data && !crashes.data.length && <Card><p className="py-4 text-center text-sm text-mute">{t("수집된 크래시·ANR·오류 로그가 없습니다")}</p></Card>}
            {(crashes.data || []).map((c: any) => (
              <Card key={c.signature} title={<span className="flex flex-wrap items-center gap-3"><span className="font-mono text-[13px]">{c.kind}</span>{c.title}</span>} action={<span className="num text-[13px] text-mute">{c.count}{t("회")} · {t("기기")} {c.devices}</span>}>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-sub"><span>{t("분류(규칙 기반)")}: {c.category}</span><span>{t("심각도")}: {c.severity}</span><span>{t("실제 수집된 오류")}</span></div>
                {c.analysis?.rule?.advice && <p className="mt-3 text-sm">{c.analysis.rule.advice}</p>}
                {c.analysis?.ai && !c.analysis.ai.error && <div className="mt-3"><Notice tone="warn">{t("AI 추정(미확인)")}: {c.analysis.ai.cause} {c.analysis.ai.advice && `· ${c.analysis.ai.advice}`}</Notice></div>}
                <pre className="mt-4 max-h-64 overflow-auto rounded-ctl bg-raised p-3 font-mono text-xs leading-5 text-sub">{c.detail}</pre>
              </Card>))}</div>}
          {tab === "screenshots" && <Card>{shots.data && !shots.data.length && <p className="py-4 text-center text-sm text-mute">{t("수집된 스크린샷이 없습니다")}</p>}
            <div className="grid grid-cols-3 gap-4 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">{(shots.data || []).map((s: any) => (
              <button key={s.id} onClick={() => setZoom(s)} className="text-left"><img src={s.url} alt={s.label} loading="lazy" className="aspect-[9/16] w-full rounded-ctl border border-line bg-raised object-cover" /><span className="mt-1 block truncate text-xs text-sub">{s.label}</span><span className="num block text-[11px] text-mute">{dt(s.created_at)}</span></button>))}</div></Card>}
          {tab === "reports" && <Card title={t("보고서 생성")} pad={false}>
            <div className="flex flex-wrap items-end gap-3 p-5"><Field label="종류"><Select value={rep.kind} onChange={(e) => setRep({ ...rep, kind: e.target.value })}>{Object.entries(reports.data?.kinds || {}).map(([k, v]) => <option key={k} value={k}>{t(v as string)}</option>)}</Select></Field>
              <Field label="형식"><Select value={rep.fmt} onChange={(e) => setRep({ ...rep, fmt: e.target.value })}><option value="pdf">PDF</option><option value="xlsx">Excel</option></Select></Field>
              <Button variant="primary" disabled={a.busy} onClick={() => a.run(() => post(`/plans/${pid}/reports`, rep)).then(reports.reload)}>{t("생성")}</Button></div>
            <div className="border-t border-line"><ReportTable rows={reports.data?.items?.filter((r: any) => r.plan_id === pid)} /></div></Card>}
        </>
      )}
      {open && <Modal title="검사 결과 상세" onClose={() => setOpen(null)} wide><div className="mb-3 flex flex-wrap items-center gap-4 text-[13px] text-sub"><span>{open.device} · {open.model} · Android {open.android}</span><Dot status={open.status} />{open.is_mock && <MockTag />}</div>{open.summary?.reason && <Notice tone="bad">{open.summary.reason}</Notice>}<StepList steps={open.steps} /></Modal>}
      {zoom && <Modal title={zoom.label || "스크린샷"} onClose={() => setZoom(null)}><img src={zoom.url} alt={zoom.label} className="mx-auto max-h-[70vh] rounded-ctl border border-line" /></Modal>}
    </>
  );
}

function ReportTable({ rows }: { rows: any[] | undefined }) {
  const { t } = useI18n();
  return <Table rows={rows} empty="발행된 보고서가 없습니다" cols={[
    { key: "report_no", label: "보고서 번호", mono: true, render: (r) => <span className="flex items-center gap-2">{r.report_no}{r.is_mock && <MockTag />}</span> },
    { key: "app", label: "앱" }, { key: "kind_name", label: "종류", render: (r) => t(r.kind_name) }, { key: "fmt", label: "형식", mono: true, render: (r) => r.fmt.toUpperCase() },
    { key: "size", label: "크기", right: true, render: (r) => size(r.size) }, { key: "created_at", label: "발행일", mono: true, render: (r) => dt(r.created_at) },
    { key: "dl", label: "", right: true, render: (r) => <Button size="sm" onClick={() => download(`/reports/${r.id}/download`, `${r.report_no}.${r.fmt}`)}>{t("다운로드")}</Button> }]} />;
}

export function Reports() {
  const r = useLoad(() => get("/reports"));
  return <><PageHead title="보고서" desc="검사 기간이 끝나면 최종 보고서가 자동 발행됩니다. 진행 중에도 주문 화면에서 직접 생성할 수 있습니다" /><Card pad={false}><ReportTable rows={r.data?.items} /></Card></>;
}

// ---------------- 시나리오 편집기 ----------------
const ACTIONS: [string, string][] = [["launch", "앱 실행"], ["find", "화면 요소 검색"], ["tap", "버튼 선택"], ["input", "텍스트 입력"], ["scroll", "스크롤"], ["back", "뒤로 이동"], ["home", "홈 이동"], ["wait", "대기"],
  ["screenshot", "화면 캡처"], ["assert_exists", "요소 존재 확인"], ["assert_text", "텍스트 검증"], ["assert_no_error", "오류 확인"], ["stop", "앱 종료"]];
const NEEDS_SEL = ["find", "tap", "input", "assert_exists"];

export function ScenarioEditor({ initial, base, onClose, onSaved }: { initial?: any; base: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [name, setName] = useState(initial?.name || "");
  const [steps, setSteps] = useState<any[]>(initial?.steps?.length ? initial.steps : [{ action: "launch", name: "", selector: {}, text: "", expected: "" }]);
  const upd = (i: number, patchObj: any) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patchObj } : s)));
  const move = (i: number, d: number) => { const n = [...steps]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); setSteps(n); };
  const save = () => a.run(() => (initial ? put(`${base}/${initial.id}`, { name, steps }) : post(base, { name, steps }))).then((r) => r && onSaved());
  return (
    <Modal title={initial ? `시나리오 수정 (새 버전 v${initial.version + 1}로 저장)` : "시나리오 작성"} onClose={onClose} wide>
      <Field label="시나리오 이름"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <ol className="mt-4 space-y-3">{steps.map((s, i) => (
        <li key={i} className="rounded-ctl border border-line p-3">
          <div className="flex flex-wrap items-center gap-2"><span className="num w-6 text-mute">{i + 1}</span>
            <Select className="!w-40" value={s.action} onChange={(e) => upd(i, { action: e.target.value })}>{ACTIONS.map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}</Select>
            <Input className="!w-auto flex-1" placeholder={t("단계 이름")} value={s.name || ""} onChange={(e) => upd(i, { name: e.target.value })} />
            <Button size="sm" variant="ghost" disabled={i === 0} onClick={() => move(i, -1)}>↑</Button><Button size="sm" variant="ghost" disabled={i === steps.length - 1} onClick={() => move(i, 1)}>↓</Button>
            <Button size="sm" variant="ghost" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>{t("삭제")}</Button></div>
          <div className="mt-2 grid gap-2 pl-8 sm:grid-cols-3">
            {NEEDS_SEL.includes(s.action) && <><Input className="font-mono" placeholder="resource_id" value={s.selector?.resource_id || ""} onChange={(e) => upd(i, { selector: { ...s.selector, resource_id: e.target.value } })} />
              <Input placeholder={t("표시 텍스트(text)")} value={s.selector?.text || ""} onChange={(e) => upd(i, { selector: { ...s.selector, text: e.target.value } })} />
              <Input placeholder="content_desc" value={s.selector?.content_desc || ""} onChange={(e) => upd(i, { selector: { ...s.selector, content_desc: e.target.value } })} /></>}
            {["input", "assert_text"].includes(s.action) && <Input placeholder={s.action === "input" ? t("입력할 텍스트 ({{login_id}}, {{login_password}} 사용 가능)") : t("화면에 있어야 할 텍스트")} value={s.text || ""} onChange={(e) => upd(i, { text: e.target.value })} className="sm:col-span-2" />}
            {s.action === "wait" && <Input type="number" min={0} max={60} placeholder={t("초")} value={s.seconds || ""} onChange={(e) => upd(i, { seconds: Number(e.target.value) })} />}
            {s.action === "scroll" && <Select value={s.direction || "down"} onChange={(e) => upd(i, { direction: e.target.value })}>{["down", "up", "left", "right"].map((d) => <option key={d}>{d}</option>)}</Select>}
            <Input placeholder={t("기대 결과")} value={s.expected || ""} onChange={(e) => upd(i, { expected: e.target.value })} className="sm:col-span-3" />
          </div>
        </li>))}</ol>
      <div className="mt-3"><Button onClick={() => setSteps([...steps, { action: "tap", name: "", selector: {}, text: "", expected: "" }])}>{t("단계 추가")}</Button></div>
      <details className="mt-4"><summary className="cursor-pointer text-[13px] text-sub">JSON</summary><pre className="mt-2 max-h-48 overflow-auto rounded-ctl bg-raised p-3 font-mono text-xs">{JSON.stringify(steps, null, 2)}</pre></details>
      <div className="mt-4 space-y-3"><Msg a={a} /><div className="flex justify-end gap-2"><Button onClick={onClose}>{t("취소")}</Button><Button variant="primary" disabled={a.busy} onClick={save}>{t("저장")}</Button></div></div>
    </Modal>
  );
}

export function Scenarios({ base = "/scenarios", title = "검사 시나리오" }: { base?: string; title?: string }) {
  const { t } = useI18n();
  const list = useLoad<any[]>(() => get(base), [base]);
  const [edit, setEdit] = useState<any>(null);
  const [hist, setHist] = useState<any[] | null>(null);
  const admin = base.startsWith("/admin");
  return (
    <>
      <PageHead title={title} desc="UI 요소 식별자(resource_id, text, content_desc) 기반으로 검사 단계를 구성합니다. 수정하면 새 버전으로 저장됩니다" action={<Button variant="primary" onClick={() => setEdit({})}>{t("시나리오 작성")}</Button>} />
      <Card pad={false}><Table rows={list.data} empty="작성된 시나리오가 없습니다" cols={[
        { key: "name", label: "이름", render: (r) => <span className="font-medium">{r.name}</span> }, { key: "version", label: "버전", mono: true, render: (r) => `v${r.version}` },
        { key: "steps", label: "단계 수", right: true, render: (r) => r.steps.length }, { key: "is_global", label: "구분", render: (r) => t(r.is_global ? "공용" : "내 시나리오") },
        { key: "created_at", label: "저장일", mono: true, render: (r) => dt(r.created_at) },
        { key: "x", label: "", right: true, render: (r) => <span className="flex justify-end gap-1">{!admin && <Button size="sm" variant="ghost" onClick={() => get(`${base}/${r.id}/versions`).then(setHist)}>{t("이력")}</Button>}
          {(admin || !r.is_global) && <><Button size="sm" onClick={() => setEdit(r)}>{t("수정")}</Button><Button size="sm" variant="ghost" onClick={() => del(`${base}/${r.id}`).then(list.reload)}>{t("삭제")}</Button></>}</span> }]} /></Card>
      {edit && <ScenarioEditor base={base} initial={edit.id ? edit : undefined} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); list.reload(); }} />}
      {hist && <Modal title="버전 이력" onClose={() => setHist(null)}><Table rows={hist} cols={[{ key: "version", label: "버전", mono: true, render: (r) => `v${r.version}` }, { key: "name", label: "이름" }, { key: "steps", label: "단계 수", right: true, render: (r) => r.steps.length }, { key: "created_at", label: "저장일", mono: true, render: (r) => dt(r.created_at) }]} /></Modal>}
    </>
  );
}

// ---------------- 고객 문의 ----------------
export function Support() {
  const { t } = useI18n();
  const nav = useNavigate();
  const list = useLoad<any[]>(() => get("/tickets"));
  const [form, setForm] = useState(false);
  const [f, setF] = useState({ subject: "", category: "general", body: "" });
  const a = useAction();
  return (
    <>
      <PageHead title="고객 문의" action={<Button variant="primary" onClick={() => setForm(true)}>{t("문의하기")}</Button>} />
      <Card pad={false}><Table rows={list.data} onRow={(r) => nav(`/dashboard/support/${r.id}`)} empty="문의 내역이 없습니다" cols={[{ key: "subject", label: "제목" }, { key: "category", label: "분류" }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "updated_at", label: "최근 갱신", mono: true, render: (r) => dt(r.updated_at) }]} /></Card>
      {form && <Modal title="문의하기" onClose={() => setForm(false)}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => post("/tickets", f)).then((r) => r && nav(`/dashboard/support/${r.id}`)); }}>
          <Field label="분류"><Select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="general">{t("일반")}</option><option value="payment">{t("결제·환불")}</option><option value="test">{t("검사")}</option><option value="quote">{t("기업 견적")}</option></Select></Field>
          <Field label="제목"><Input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} required /></Field>
          <Field label="내용"><Textarea className="!min-h-[160px]" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} required /></Field>
          <Msg a={a} /><div className="text-right"><Button variant="primary" disabled={a.busy}>{t("등록")}</Button></div>
        </form></Modal>}
    </>
  );
}

export function Thread({ load, send, back }: { load: () => Promise<any>; send: (body: string, close: boolean) => Promise<any>; back: string }) {
  const { t } = useI18n();
  const d = useLoad(load);
  const [body, setBody] = useState("");
  const a = useAction();
  const staff = back.startsWith("/admin");
  if (!d.data) return <p className="text-mute">{d.error || t("불러오는 중")}</p>;
  return (
    <div className="max-w-3xl">
      <PageHead title={d.data.subject} desc={d.data.customer_email} action={<div className="flex items-center gap-3"><Dot status={d.data.status} /><Link to={back}><Button>{t("목록")}</Button></Link></div>} />
      <div className="space-y-3">{d.data.messages.map((m: any) => (
        <div key={m.id} className={cx("rounded-card border border-line p-4", m.is_staff ? "bg-accent-soft" : "bg-card")}><div className="mb-2 flex justify-between text-xs text-mute"><span>{t(m.is_staff ? "운영팀" : "고객")}</span><span className="num">{dt(m.created_at)}</span></div><p className="whitespace-pre-line text-sm leading-6">{m.body}</p></div>))}</div>
      <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); a.run(() => send(body, false)).then((r) => { if (r) { setBody(""); d.setData(r); } }); }}>
        <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder={t(staff ? "답변 내용" : "추가 문의 내용")} required />
        <Msg a={a} /><div className="flex justify-end gap-2">{staff && <Button type="button" disabled={!body || a.busy} onClick={() => a.run(() => send(body, true)).then((r) => { if (r) { setBody(""); d.setData(r); } })}>{t("답변 후 종료")}</Button>}<Button variant="primary" disabled={a.busy}>{t(staff ? "답변 등록" : "등록")}</Button></div>
      </form>
    </div>
  );
}
export const SupportDetail = () => { const { id } = useParams(); return <Thread key={id} back="/dashboard/support" load={() => get(`/tickets/${id}`)} send={(body) => post(`/tickets/${id}/messages`, { body })} />; };

export function NotificationsPage() {
  const nav = useNavigate();
  const n = useLoad(() => get("/notifications"));
  return <><PageHead title="알림" /><Card pad={false}><Table rows={n.data?.items} onRow={(r) => r.link && nav(r.link)} empty="알림이 없습니다" cols={[{ key: "title", label: "제목" }, { key: "body", label: "내용", render: (r) => <span className="text-sub">{r.body}</span> }, { key: "created_at", label: "시각", mono: true, render: (r) => dt(r.created_at) }]} /></Card></>;
}

export function Payments() {
  const { t } = useI18n();
  const p = useLoad<any[]>(() => get("/payments"));
  return <><PageHead title="결제 내역" /><Card pad={false}><Table rows={p.data} empty="결제 내역이 없습니다" cols={[
    { key: "order_no", label: "주문번호", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "mode", label: "구분", render: (r) => (r.mode === "mock" ? <MockTag /> : r.mode === "test" ? "TEST" : t("실결제")) },
    { key: "method", label: "수단" }, { key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "refunded_amount", label: "환불", right: true, render: (r) => won(r.refunded_amount) },
    { key: "created_at", label: "일시", mono: true, render: (r) => dt(r.approved_at || r.created_at) }, { key: "failure_message", label: "비고", render: (r) => r.failure_message || (r.receipt_url ? <a className="underline" href={r.receipt_url} target="_blank" rel="noreferrer">{t("영수증")}</a> : "") }]} /></Card></>;
}

export function Account() {
  const { t, setLocale } = useI18n();
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const logins = useLoad<any[]>(() => get("/me/logins"));
  const [f, setF] = useState({ name: user?.name || "", locale: user?.locale || "ko", company: user?.customer?.company || "", phone: user?.customer?.phone || "", business_no: user?.customer?.business_no || "" });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [wd, setWd] = useState("");
  const a = useAction(), b = useAction(), c = useAction();
  return (
    <>
      <PageHead title={user?.is_staff ? "내 계정" : "마이페이지"} desc={user?.email} />
      {user?.must_change_password && <div className="mb-4"><Notice tone="warn">{t("초기 비밀번호를 사용 중입니다. 비밀번호를 변경해 주세요")}</Notice></div>}
      {!user?.is_staff && !user?.email_verified && <div className="mb-4"><Notice tone="warn">{t("이메일 인증이 완료되지 않았습니다")} <button className="ml-2 underline" onClick={() => post("/auth/resend-verification").then((r) => alert(t(r.smtp_configured === false ? "현재 이메일 발송이 설정되지 않아 인증 메일을 보낼 수 없습니다" : "인증 메일을 보냈습니다")))}>{t("인증 메일 다시 받기")}</button></Notice></div>}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={t("회원정보 변경")}>
          <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); a.run(() => patch("/me", f), t("저장되었습니다")).then((u) => { if (u) { setUser(u); setLocale(u.locale); } }); }}>
            <Field label="이름"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="알림 언어"><Select value={f.locale} onChange={(e) => setF({ ...f, locale: e.target.value })}><option value="ko">한국어</option><option value="en">English</option></Select></Field>
            {user?.customer && <><Field label="회사명"><Input value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></Field><Field label="연락처"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
              <Field label="사업자등록번호"><Input value={f.business_no} onChange={(e) => setF({ ...f, business_no: e.target.value })} /></Field></>}
            <div className="space-y-3 sm:col-span-2"><Msg a={a} /><Button variant="primary" disabled={a.busy}>{t("저장")}</Button></div>
          </form>
        </Card>
        <Card title={t("비밀번호 변경")}>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); b.run(() => post("/auth/change-password", pw), t("비밀번호가 변경되었습니다")).then((r) => { if (r) { storeSession(r); setPw({ current_password: "", new_password: "" }); } }); }}>
            <Field label="현재 비밀번호"><Input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required /></Field>
            <Field label="새 비밀번호" hint="8자 이상, 영문과 숫자 포함"><Input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required /></Field>
            <Msg a={b} /><Button variant="primary" disabled={b.busy}>{t("변경하기")}</Button>
          </form>
        </Card>
        <Card title={t("로그인 기록")} pad={false}><Table rows={logins.data} cols={[{ key: "at", label: "시각", mono: true, render: (r) => dt(r.at) }, { key: "ip", label: "IP", mono: true }, { key: "success", label: "결과", render: (r) => <Dot status={r.success ? "passed" : "failed"} label={t(r.success ? "성공" : "실패")} /> }, { key: "user_agent", label: "기기", render: (r) => <span className="block max-w-[220px] truncate text-mute">{r.user_agent}</span> }]} /></Card>
        {!user?.is_staff && <Card title={t("회원 탈퇴")}>
          <p className="text-sm text-sub">{t("탈퇴하면 계정 정보가 즉시 익명화되며 복구할 수 없습니다. 진행 중인 검사가 있으면 탈퇴할 수 없습니다")}</p>
          <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (confirm(t("정말 탈퇴할까요?"))) c.run(() => post("/me/withdraw", { password: wd })).then((r) => { if (r) { clearSession(); nav("/"); } }); }}>
            <Field label="비밀번호 확인"><Input type="password" value={wd} onChange={(e) => setWd(e.target.value)} required /></Field><Button variant="danger" disabled={c.busy}>{t("탈퇴하기")}</Button></form>
          <div className="mt-3"><Msg a={c} /></div>
        </Card>}
      </div>
    </>
  );
}
