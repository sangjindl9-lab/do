import { Activity, Archive, BadgePercent, Bell, Boxes, Bug, CalendarClock, ClipboardList, Cpu, CreditCard, Database, FileText, FolderTree, HardDrive, Image, LayoutDashboard, LifeBuoy, ListChecks, ListOrdered, Mail, Megaphone, MessageCircleQuestion, MonitorSmartphone, Package, Receipt, RotateCcw, ScrollText, Settings, ShieldCheck, TrendingUp, TriangleAlert, UserRound, Users, Wallet, Workflow } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bars, StackedDays } from "../components/charts";
import { AppShell, type NavGroup } from "../components/shell";
import { Button, Card, Check, Dot, Field, Input, MockTag, Modal, Msg, Notice, PageHead, Select, Stat, Table, Textarea, cx, useAction, useLoad, type Col } from "../components/ui";
import { del, download, get, patch, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ago, dt, num, size, won } from "../lib/format";
import { STATUS } from "../lib/i18n";
import { Scenarios, Thread } from "./dash";
import { CHECKS } from "./public";

const NAVS: NavGroup[] = [
  { label: "운영관리", items: [{ to: "/admin", label: "통합 대시보드", icon: LayoutDashboard, end: true, perm: "dashboard" }, { to: "/admin/customers", label: "고객 관리", icon: Users, perm: "customers" },
    { to: "/admin/users", label: "회원·권한 관리", icon: ShieldCheck, perm: "users" }, { to: "/admin/apps", label: "앱 관리", icon: Boxes, perm: "orders" }, { to: "/admin/orders", label: "주문 관리", icon: ClipboardList, perm: "orders" },
    { to: "/admin/products", label: "상품·가격 관리", icon: Package, perm: "products" }, { to: "/admin/coupons", label: "쿠폰 관리", icon: BadgePercent, perm: "products" }] },
  { label: "결제관리", items: [{ to: "/admin/payments", label: "결제 현황", icon: CreditCard, perm: "payments" }, { to: "/admin/revenue", label: "매출 현황", icon: TrendingUp, perm: "payments" },
    { to: "/admin/refunds", label: "환불·취소 관리", icon: RotateCcw, perm: "payments" }, { to: "/admin/pg", label: "PG 설정", icon: Wallet, perm: "payments" }] },
  { label: "장비관리", items: [{ to: "/admin/devices", label: "폰팜 통합 관리", icon: MonitorSmartphone, perm: "devices" }, { to: "/admin/device-groups", label: "기기 그룹", icon: FolderTree, perm: "devices" },
    { to: "/admin/agents", label: "PC 에이전트", icon: Cpu, perm: "devices" }, { to: "/admin/incidents", label: "장애·유지보수", icon: TriangleAlert, perm: "devices" }] },
  { label: "검사관리", items: [{ to: "/admin/live", label: "실시간 검사 현황", icon: Activity, perm: "tests" }, { to: "/admin/jobs", label: "검사 작업 대기열", icon: ListOrdered, perm: "tests" },
    { to: "/admin/plans", label: "검사 스케줄", icon: CalendarClock, perm: "tests" }, { to: "/admin/scenarios", label: "검사 시나리오", icon: Workflow, perm: "tests" }, { to: "/admin/results", label: "검사 결과", icon: ListChecks, perm: "tests" },
    { to: "/admin/crashes", label: "크래시·오류 분석", icon: Bug, perm: "tests" }, { to: "/admin/screenshots", label: "스크린샷", icon: Image, perm: "tests" }, { to: "/admin/reports", label: "보고서 관리", icon: FileText, perm: "tests" }] },
  { label: "고객지원", items: [{ to: "/admin/tickets", label: "고객 문의", icon: LifeBuoy, perm: "support" }, { to: "/admin/announcements", label: "공지사항", icon: Megaphone, perm: "support" },
    { to: "/admin/faqs", label: "FAQ", icon: MessageCircleQuestion, perm: "support" }, { to: "/admin/legal", label: "약관·정책", icon: ScrollText, perm: "support" }] },
  { label: "시스템 설정", items: [{ to: "/admin/settings", label: "환경 설정", icon: Settings, perm: "system" }, { to: "/admin/status", label: "서버·DB 상태", icon: Database, perm: "system" },
    { to: "/admin/emails", label: "이메일 발송 내역", icon: Mail, perm: "system" }, { to: "/admin/templates", label: "알림 템플릿", icon: Bell, perm: "system" }, { to: "/admin/audit", label: "관리자 활동 기록", icon: Receipt, perm: "system" },
    { to: "/admin/logs", label: "시스템 로그", icon: HardDrive }, { to: "/admin/backups", label: "백업·복구", icon: Archive, perm: "system" }, { to: "/admin/account", label: "내 계정", icon: UserRound }] },
];
export const AdminLayout = () => <AppShell groups={NAVS} home="/admin" badge="관리자" />;
const st = (s: string) => STATUS[s] || s;

// ---------------- 공통 CRUD 화면 ----------------
type F = { key: string; label: string; type?: "text" | "number" | "bool" | "textarea" | "select" | "datetime" | "checks"; options?: [string, string][]; hint?: string; required?: boolean };
function CrudPage({ title, desc, path, cols, fields, defaults = {} }: { title: string; desc?: string; path: string; cols: Col<any>[]; fields: F[]; defaults?: any }) {
  const list = useLoad<any[]>(() => get(path), [path]);
  const [edit, setEdit] = useState<any>(null);
  const a = useAction();
  const set = (k: string, v: any) => setEdit((p: any) => ({ ...p, [k]: v }));
  const save = (e: FormEvent) => {
    e.preventDefault();
    const body: any = {};
    fields.forEach((f) => { let v = edit[f.key]; if (f.type === "number") v = v === "" || v == null ? 0 : Number(v); if (f.type === "datetime") v = v ? new Date(v).toISOString() : null; body[f.key] = v ?? (f.type === "bool" ? false : f.type === "checks" ? [] : ""); });
    a.run(() => (edit.id ? put(`${path}/${edit.id}`, body) : post(path, body))).then((r) => { if (r) { setEdit(null); list.reload(); } });
  };
  return (
    <>
      <PageHead title={title} desc={desc} action={<Button variant="primary" onClick={() => { a.setError(""); setEdit({ ...defaults }); }}>추가</Button>} />
      <Card pad={false}><Table rows={list.data} cols={[...cols, { key: "_", label: "", right: true, render: (r) => <span className="flex justify-end gap-1"><Button size="sm" onClick={() => { a.setError(""); setEdit({ ...r, ...Object.fromEntries(fields.filter((f) => f.type === "datetime").map((f) => [f.key, r[f.key] ? r[f.key].slice(0, 16) : ""])) }); }}>수정</Button>
        <Button size="sm" variant="ghost" onClick={() => confirm("삭제할까요?") && a.run(() => del(`${path}/${r.id}`)).then(list.reload)}>삭제</Button></span> }]} /></Card>
      {!edit && <div className="mt-3"><Msg a={a} /></div>}
      {edit && <Modal title={edit.id ? "수정" : "추가"} onClose={() => setEdit(null)} wide>
        <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
          {fields.map((f) => <div key={f.key} className={cx((f.type === "textarea" || f.type === "checks") && "sm:col-span-2")}>
            {f.type === "bool" ? <div className="pt-6"><Check checked={!!edit[f.key]} onChange={(e) => set(f.key, e.target.checked)} label={f.label} /></div> :
              <Field label={f.label} hint={f.hint}>
                {f.type === "textarea" ? <Textarea value={edit[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)} required={f.required} /> :
                  f.type === "select" ? <Select value={edit[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>{f.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select> :
                  f.type === "checks" ? <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{Object.entries(CHECKS).map(([k, l]) => <Check key={k} label={l} checked={(edit[f.key] || []).includes(k)} onChange={(e) => set(f.key, e.target.checked ? [...(edit[f.key] || []), k] : (edit[f.key] || []).filter((x: string) => x !== k))} />)}</div> :
                  <Input type={f.type === "number" ? "number" : f.type === "datetime" ? "datetime-local" : "text"} value={edit[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)} required={f.required} />}
              </Field>}
          </div>)}
          <div className="space-y-3 sm:col-span-2"><Msg a={a} /><div className="flex justify-end gap-2"><Button type="button" onClick={() => setEdit(null)}>취소</Button><Button variant="primary" disabled={a.busy}>저장</Button></div></div>
        </form>
      </Modal>}
    </>
  );
}
const yn = (k: string) => (r: any) => (r[k] ? "예" : "아니오");

export const Products = () => <CrudPage title="상품·가격 관리" desc="가격과 검사 조건은 신규 주문부터 적용됩니다. 기존 주문은 주문 시점의 조건을 유지합니다" path="/admin/products" defaults={{ is_active: true, pdf_report: true, coupon_allowed: true, daily_runs: 1, checks: ["install", "launch"] }}
  cols={[{ key: "name", label: "상품명", render: (r) => <span className="font-medium">{r.name}</span> }, { key: "device_count", label: "검사 기기", right: true }, { key: "duration_days", label: "기간(일)", right: true }, { key: "daily_runs", label: "일일 검사", right: true },
    { key: "list_price", label: "정상가", right: true, render: (r) => won(r.list_price) }, { key: "price", label: "판매가", right: true, render: (r) => (r.is_quote ? "별도 견적" : won(r.price)) }, { key: "is_active", label: "판매", render: (r) => <Dot status={r.is_active ? "active" : "disabled"} label={r.is_active ? "판매 중" : "중지"} /> }]}
  fields={[{ key: "code", label: "상품 코드", required: true }, { key: "name", label: "상품명", required: true }, { key: "list_price", label: "정상가격", type: "number" }, { key: "discount_price", label: "할인가격", type: "number" }, { key: "price", label: "판매가격", type: "number" },
    { key: "duration_days", label: "검사 기간(일)", type: "number" }, { key: "device_count", label: "검사 기기 수", type: "number" }, { key: "daily_runs", label: "일일 검사 횟수", type: "number" }, { key: "sort", label: "정렬 순서", type: "number" },
    { key: "description", label: "상품 설명", type: "textarea" }, { key: "description_en", label: "상품 설명(영문)", type: "textarea" }, { key: "checks", label: "검사 항목", type: "checks" },
    { key: "ai_analysis", label: "AI 분석 제공", type: "bool" }, { key: "pdf_report", label: "PDF 보고서 제공", type: "bool" }, { key: "excel_report", label: "Excel 보고서 제공", type: "bool" }, { key: "priority", label: "우선 배정", type: "bool" },
    { key: "coupon_allowed", label: "쿠폰 적용 가능", type: "bool" }, { key: "is_active", label: "판매 활성화", type: "bool" }, { key: "is_quote", label: "별도 견적 상품", type: "bool" }]} />;

export const Coupons = () => <CrudPage title="쿠폰 관리" path="/admin/coupons" defaults={{ kind: "percent", is_active: true, value: 10 }}
  cols={[{ key: "code", label: "코드", mono: true }, { key: "kind", label: "종류", render: (r) => (r.kind === "percent" ? "정률" : "정액") }, { key: "value", label: "할인", right: true, render: (r) => (r.kind === "percent" ? `${r.value}%` : won(r.value)) },
    { key: "used_count", label: "사용", right: true, render: (r) => `${r.used_count}${r.max_uses ? ` / ${r.max_uses}` : ""}` }, { key: "valid_to", label: "만료", mono: true, render: (r) => dt(r.valid_to, false) }, { key: "is_active", label: "활성", render: yn("is_active") }]}
  fields={[{ key: "code", label: "쿠폰 코드", required: true }, { key: "kind", label: "종류", type: "select", options: [["percent", "정률(%)"], ["fixed", "정액(원)"]] }, { key: "value", label: "할인 값", type: "number" }, { key: "max_uses", label: "사용 한도", type: "number", hint: "0이면 무제한" },
    { key: "min_amount", label: "최소 결제금액", type: "number" }, { key: "valid_from", label: "시작", type: "datetime" }, { key: "valid_to", label: "만료", type: "datetime" }, { key: "is_active", label: "활성화", type: "bool" }]} />;

export const Announcements = () => <CrudPage title="공지사항" path="/admin/announcements" defaults={{ is_published: true }}
  cols={[{ key: "title", label: "제목" }, { key: "pinned", label: "상단 고정", render: yn("pinned") }, { key: "is_published", label: "게시", render: yn("is_published") }, { key: "created_at", label: "등록일", mono: true, render: (r) => dt(r.created_at) }]}
  fields={[{ key: "title", label: "제목", required: true }, { key: "body", label: "내용", type: "textarea" }, { key: "is_published", label: "게시", type: "bool" }, { key: "pinned", label: "상단 고정", type: "bool" }]} />;

export const Faqs = () => <CrudPage title="FAQ" path="/admin/faqs" defaults={{ locale: "ko", is_published: true }}
  cols={[{ key: "question", label: "질문" }, { key: "locale", label: "언어", mono: true }, { key: "sort", label: "순서", right: true }, { key: "is_published", label: "게시", render: yn("is_published") }]}
  fields={[{ key: "question", label: "질문", required: true }, { key: "locale", label: "언어", type: "select", options: [["ko", "한국어"], ["en", "English"], ["ja", "日本語"], ["zh", "中文"]] }, { key: "answer", label: "답변", type: "textarea", required: true }, { key: "sort", label: "정렬 순서", type: "number" }, { key: "is_published", label: "게시", type: "bool" }]} />;

export const DeviceGroups = () => <CrudPage title="기기 그룹" desc="랙·장비 박스 단위로 기기를 묶어 관리합니다" path="/admin/device-groups" cols={[{ key: "name", label: "그룹명" }, { key: "description", label: "설명" }]} fields={[{ key: "name", label: "그룹명", required: true }, { key: "description", label: "설명" }]} />;

export const Templates = () => <CrudPage title="알림 템플릿" desc="{name}, {order_no}, {app} 등 중괄호 변수를 사용할 수 있습니다" path="/admin/notification-templates"
  cols={[{ key: "event", label: "이벤트", mono: true }, { key: "locale", label: "언어", mono: true }, { key: "subject", label: "제목" }]}
  fields={[{ key: "event", label: "이벤트", required: true }, { key: "locale", label: "언어", type: "select", options: [["ko", "한국어"], ["en", "English"], ["ja", "日本語"], ["zh", "中文"]] }, { key: "subject", label: "제목", required: true }, { key: "body", label: "본문", type: "textarea", required: true }]} />;

// ---------------- 통합 대시보드 ----------------
export function AdminHome() {
  const d = useLoad(() => get("/admin/dashboard"), [], 20000);
  const x = d.data;
  const sum = (o: any, keys: string[]) => keys.reduce((n, k) => n + (o?.[k] || 0), 0);
  return (
    <>
      <PageHead title="통합 대시보드" />
      {d.error && <Notice tone="bad">{d.error}</Notice>}
      {x && <div className="mb-4 space-y-2">
        {x.secret_key_ephemeral && <Notice tone="bad">SECRET_KEY 환경변수가 설정되지 않았습니다. 서버가 재시작되면 로그인 세션과 암호화된 설정(PG 키 등)을 읽을 수 없습니다</Notice>}
        {!x.payment.enabled && <Notice tone="warn">결제 비활성 상태입니다. PG 인증정보를 등록하면 실제 결제가 열립니다 <Link className="underline" to="/admin/pg">PG 설정</Link></Notice>}
        {x.payment.mode === "mock" && <Notice tone="warn">모의 결제 환경이 켜져 있습니다. 실제 금전 거래가 발생하지 않으며 모의 주문에는 모의 장비만 배정됩니다</Notice>}
        {!x.devices_total && <Notice tone="warn">연결된 실기기가 없습니다. PC 에이전트를 설치하고 폰팜 장비를 연결해 주세요 <Link className="underline" to="/admin/agents">PC 에이전트</Link></Notice>}
        {!x.smtp_configured && <Notice>SMTP 미설정: 이메일 알림은 대기열에만 기록되고 실제 발송되지 않습니다 <Link className="underline" to="/admin/settings">환경 설정</Link></Notice>}
      </div>}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="이번 달 실매출" value={won(x?.month_revenue)} note="환불 차감 · 모의 결제 제외" />
        <Stat label="진행 중인 주문" value={num(sum(x?.orders, ["paid", "waiting_devices", "scheduled", "running"]))} note={`기기 배정 대기 ${x?.waiting_plans ?? 0}`} />
        <Stat label="실기기 연결" value={`${num(sum(x?.devices, ["idle", "assigned", "testing"]))} / ${num(x?.devices_total)}`} note={`에이전트 ${x?.agents_online ?? 0}/${x?.agents_total ?? 0} · 모의 기기 ${x?.mock_devices ?? 0}`} />
        <Stat label="오늘 실기기 검사" value={num(sum(x?.results_today, ["passed", "failed", "error"]))} note={`성공 ${x?.results_today?.passed ?? 0} · 실패 ${sum(x?.results_today, ["failed", "error"])}`} />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card title="최근 30일 실매출"><Bars unit="원" data={(x?.daily_revenue || []).slice(-10).map((r: any) => ({ label: r.day.slice(5), value: r.amount - r.refunded }))} /></Card>
        <Card title="현황" pad={false}><ul className="divide-y divide-[rgba(23,23,23,0.09)] text-sm">
          {[["고객", x?.customers, "/admin/customers"], ["등록 앱", x?.apps, "/admin/apps"], ["대기 중 작업", x?.jobs?.queued || 0, "/admin/jobs"], ["실행 중 작업", sum(x?.jobs, ["leased", "running"]), "/admin/live"], ["미답변 문의", x?.open_tickets, "/admin/tickets"]].map(([l, v, to]) => (
            <li key={l as string}><Link to={to as string} className="flex h-11 items-center justify-between px-5 hover:bg-raised"><span className="text-sub">{l}</span><span className="num">{num(v as number)}</span></Link></li>))}</ul></Card>
      </div>
    </>
  );
}

// ---------------- 고객 / 회원 ----------------
export function Customers() {
  const [q, setQ] = useState("");
  const list = useLoad<any[]>(() => get(`/admin/customers?q=${encodeURIComponent(q)}`), [q]);
  const [open, setOpen] = useState<any>(null);
  const a = useAction();
  return (
    <>
      <PageHead title="고객 관리" action={<Input className="!w-64" placeholder="이메일·이름·회사 검색" value={q} onChange={(e) => setQ(e.target.value)} />} />
      <Card pad={false}><Table rows={list.data} onRow={(r) => get(`/admin/customers/${r.id}`).then(setOpen)} cols={[{ key: "email", label: "이메일" }, { key: "name", label: "이름" }, { key: "kind", label: "구분", render: (r) => (r.kind === "business" ? "기업" : "일반") }, { key: "company", label: "회사" },
        { key: "apps", label: "앱", right: true }, { key: "paid_orders", label: "결제 주문", right: true }, { key: "spent", label: "누적 결제", right: true, render: (r) => won(r.spent) }, { key: "is_active", label: "상태", render: (r) => <Dot status={r.is_active ? "active" : "disabled"} label={r.is_active ? "활성" : "정지"} /> }, { key: "created_at", label: "가입일", mono: true, render: (r) => dt(r.created_at, false) }]} /></Card>
      {open && <Modal title={open.customer.user.email} onClose={() => setOpen(null)} wide>
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-sub"><span>{open.customer.user.name}</span><span>{open.customer.company}</span><span>{open.customer.phone}</span>
          <Button size="sm" variant={open.customer.is_active ? "danger" : "secondary"} onClick={() => a.run(() => patch(`/admin/users/${open.customer.user_id}`, { is_active: !open.customer.is_active })).then(() => { setOpen(null); list.reload(); })}>{open.customer.is_active ? "계정 정지" : "정지 해제"}</Button>
          <Button size="sm" onClick={() => a.run(() => patch(`/admin/users/${open.customer.user_id}`, { unlock: true }), "잠금을 해제했습니다")}>로그인 잠금 해제</Button></div>
        <Msg a={a} />
        <h3 className="mb-2 mt-4 text-[13px] text-mute">앱</h3><Table rows={open.apps} cols={[{ key: "name", label: "앱" }, { key: "package_name", label: "패키지명", mono: true }, { key: "v", label: "버전 수", right: true, render: (r) => r.versions.length }]} />
        <h3 className="mb-2 mt-4 text-[13px] text-mute">주문</h3><Table rows={open.orders} cols={[{ key: "order_no", label: "주문번호", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "final_amount", label: "금액", right: true, render: (r) => won(r.final_amount) }, { key: "created_at", label: "주문일", mono: true, render: (r) => dt(r.created_at) }]} />
        <h3 className="mb-2 mt-4 text-[13px] text-mute">최근 로그인</h3><Table rows={open.logins} cols={[{ key: "at", label: "시각", mono: true, render: (r) => dt(r.at) }, { key: "ip", label: "IP", mono: true }, { key: "success", label: "결과", render: (r) => (r.success ? "성공" : `실패 (${r.reason})`) }]} />
      </Modal>}
    </>
  );
}

export function UsersPage() {
  const { user } = useAuth();
  const users = useLoad<any[]>(() => get("/admin/users?staff_only=true"));
  const roles = useLoad(() => get("/admin/roles"));
  const [form, setForm] = useState<any>(null);
  const a = useAction();
  const staffRoles = (roles.data?.roles || []).filter((r: any) => r.is_staff);
  return (
    <>
      <PageHead title="회원·권한 관리" desc="관리자 계정과 역할별 메뉴 권한을 관리합니다. 고객 계정은 고객 관리에서 다룹니다" action={<Button variant="primary" onClick={() => setForm({ email: "", username: "", name: "", password: "", role: "operator" })}>관리자 추가</Button>} />
      <Msg a={a} />
      <Card title="관리자 계정" pad={false}><Table rows={users.data} cols={[{ key: "username", label: "아이디", mono: true }, { key: "name", label: "이름" }, { key: "email", label: "이메일" },
        { key: "role", label: "역할", render: (r) => <Select className="!h-8 w-40" disabled={r.id === user.id} value={r.role} onChange={(e) => a.run(() => patch(`/admin/users/${r.id}`, { role: e.target.value })).then(users.reload)}>{staffRoles.map((x: any) => <option key={x.code} value={x.code}>{x.name}</option>)}</Select> },
        { key: "is_active", label: "상태", render: (r) => <Dot status={r.locked ? "failed" : r.is_active ? "active" : "disabled"} label={r.locked ? "잠김" : r.is_active ? "활성" : "정지"} /> }, { key: "last_login_at", label: "최근 로그인", mono: true, render: (r) => dt(r.last_login_at) },
        { key: "_", label: "", right: true, render: (r) => r.id !== user.id && <span className="flex justify-end gap-1"><Button size="sm" onClick={() => { const p = prompt("새 초기 비밀번호 (8자 이상, 영문+숫자)"); if (p) a.run(() => patch(`/admin/users/${r.id}`, { new_password: p }), "비밀번호를 초기화했습니다. 다음 로그인 시 변경이 요구됩니다"); }}>비밀번호 초기화</Button>
          <Button size="sm" variant="ghost" onClick={() => a.run(() => patch(`/admin/users/${r.id}`, { is_active: !r.is_active, unlock: true })).then(users.reload)}>{r.is_active ? "정지" : "해제"}</Button></span> }]} /></Card>
      <div className="mt-4"><Card title="역할별 메뉴 권한" pad={false}>
        <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-[13px]"><thead><tr className="border-b border-line text-mute"><th className="h-10 px-4 text-left font-normal">권한</th>{staffRoles.map((r: any) => <th key={r.code} className="px-4 font-normal">{r.name}</th>)}</tr></thead>
          <tbody>{(roles.data?.permissions || []).map((p: any) => <tr key={p.code} className="border-b border-line last:border-0"><td className="h-10 px-4">{p.name}</td>{staffRoles.map((r: any) => <td key={r.code} className="px-4 text-center">
            <input type="checkbox" className="h-4 w-4 accent-[#0f766e]" disabled={r.code === "superadmin"} checked={r.code === "superadmin" || r.permissions.includes(p.code)}
              onChange={(e) => a.run(() => put(`/admin/roles/${r.code}`, { permissions: e.target.checked ? [...r.permissions, p.code] : r.permissions.filter((c: string) => c !== p.code) })).then(roles.reload)} /></td>)}</tr>)}</tbody></table></div></Card></div>
      {form && <Modal title="관리자 추가" onClose={() => setForm(null)}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => post("/admin/users", form)).then((r) => { if (r) { setForm(null); users.reload(); } }); }}>
          <Field label="아이디"><Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required minLength={3} /></Field>
          <Field label="이름"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="이메일"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
          <Field label="초기 비밀번호" hint="첫 로그인 시 변경이 요구됩니다"><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></Field>
          <Field label="역할"><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{staffRoles.map((x: any) => <option key={x.code} value={x.code}>{x.name}</option>)}</Select></Field>
          <Msg a={a} /><div className="text-right"><Button variant="primary" disabled={a.busy}>추가</Button></div>
        </form></Modal>}
    </>
  );
}

// ---------------- 앱 / 주문 ----------------
export function AdminApps() {
  const apps = useLoad<any[]>(() => get("/admin/apps"));
  const q = useLoad<any[]>(() => get("/admin/files/quarantine"));
  return (
    <>
      <PageHead title="앱 관리" />
      <Card title="등록 앱" pad={false}><Table rows={apps.data} cols={[{ key: "name", label: "앱" }, { key: "package_name", label: "패키지명", mono: true }, { key: "customer_email", label: "고객" },
        { key: "v", label: "최신 버전", mono: true, render: (r) => (r.versions[0] ? `${r.versions[0].version_name} (${r.versions[0].version_code})` : "-") }, { key: "own", label: "검사 권한 확인", render: (r) => (r.ownership_confirmed ? "확인" : "미확인") }, { key: "created_at", label: "등록일", mono: true, render: (r) => dt(r.created_at, false) }]} /></Card>
      <div className="mt-4"><Card title="격리된 파일" pad={false}><Table rows={q.data} empty="격리된 파일이 없습니다" cols={[{ key: "filename", label: "파일" }, { key: "size", label: "크기", right: true, render: (r) => size(r.size) }, { key: "sha256", label: "SHA-256", mono: true, render: (r) => r.sha256.slice(0, 16) + "…" },
        { key: "quarantine_reason", label: "격리 사유" }, { key: "created_at", label: "업로드", mono: true, render: (r) => dt(r.created_at) }, { key: "_", label: "", right: true, render: (r) => <Button size="sm" variant="danger" onClick={() => del(`/admin/files/quarantine/${r.id}`).then(q.reload)}>영구 삭제</Button> }]} /></Card></div>
    </>
  );
}

export function AdminOrders() {
  const [f, setF] = useState({ status: "", q: "" });
  const list = useLoad<any[]>(() => get(`/admin/orders?status=${f.status}&q=${encodeURIComponent(f.q)}`), [f.status, f.q], 30000);
  const [open, setOpen] = useState<any>(null);
  const a = useAction();
  return (
    <>
      <PageHead title="주문 관리" action={<div className="flex gap-2"><Select className="!w-40" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">전체 상태</option>{["pending_payment", "waiting_devices", "scheduled", "running", "completed", "cancelled", "refunded"].map((s) => <option key={s} value={s}>{st(s)}</option>)}</Select><Input className="!w-56" placeholder="주문번호·이메일" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></div>} />
      <Card pad={false}><Table rows={list.data} onRow={(r) => get(`/admin/orders/${r.id}`).then(setOpen)} cols={[{ key: "order_no", label: "주문번호", mono: true, render: (r) => <span className="flex items-center gap-2">{r.order_no}{r.is_mock && <MockTag />}</span> }, { key: "customer_email", label: "고객" }, { key: "app", label: "앱", render: (r) => r.app.name },
        { key: "product", label: "상품", render: (r) => r.product.name }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "final_amount", label: "금액", right: true, render: (r) => won(r.final_amount) }, { key: "runs", label: "검사", right: true, render: (r) => r.plan?.total_runs ?? "-" }, { key: "created_at", label: "주문일", mono: true, render: (r) => dt(r.created_at) }]} /></Card>
      {open && <Modal title={open.order_no} onClose={() => setOpen(null)} wide>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-3">{[["고객", open.customer_email], ["앱", `${open.app.name} ${open.version}`], ["상품", open.product.name], ["상태", st(open.status)], ["금액", won(open.final_amount)], ["할인", won(open.discount)], ["희망 Android", open.desired_android || "-"], ["결제일", dt(open.paid_at)], ["요청사항", open.request_notes || "-"]].map(([k, v]) => <div key={k}><dt className="text-xs text-mute">{k}</dt><dd>{v}</dd></div>)}</dl>
        {open.plan && <p className="num mt-4 text-[13px] text-sub">검사 {dt(open.plan.start_at, false)} ~ {dt(open.plan.end_at, false)} · 기기 {open.plan.assigned_devices}/{open.plan.device_count} · {open.plan.total_runs}회 <Link className="ml-2 underline" to="/admin/plans">검사 스케줄</Link></p>}
        <h3 className="mb-2 mt-4 text-[13px] text-mute">결제</h3><Table rows={open.payments} empty="결제 내역 없음" cols={[{ key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "mode", label: "구분" }, { key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "refunded_amount", label: "환불", right: true, render: (r) => won(r.refunded_amount) }, { key: "failure_message", label: "비고" }]} />
        <div className="mt-4 space-y-3"><Msg a={a} />{!["completed", "cancelled", "refunded"].includes(open.status) && <Button variant="danger" onClick={() => confirm("주문을 취소하고 검사를 중단할까요? 환불은 결제 현황에서 별도로 처리합니다") && a.run(() => post(`/admin/orders/${open.id}/cancel`)).then((r) => { if (r) { setOpen(null); list.reload(); } })}>주문 취소·검사 중단</Button>}</div>
      </Modal>}
    </>
  );
}

// ---------------- 결제 ----------------
export function AdminPayments() {
  const [f, setF] = useState({ status: "", mode: "" });
  const list = useLoad<any[]>(() => get(`/admin/payments?status=${f.status}&mode=${f.mode}`), [f.status, f.mode]);
  const events = useLoad<any[]>(() => get("/admin/payment-events"));
  const [open, setOpen] = useState<any>(null);
  const [rf, setRf] = useState({ amount: "", reason: "" });
  const a = useAction();
  const openPay = (r: any) => get(`/admin/payments/${r.id}`).then((d) => { setOpen({ ...d, idem: crypto.randomUUID() }); setRf({ amount: "", reason: "" }); a.setError(""); });
  return (
    <>
      <PageHead title="결제 현황" desc="모의(MOCK) 결제는 실매출과 분리되어 표시됩니다" action={<div className="flex gap-2"><Select className="!w-36" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">전체 상태</option>{["paid", "failed", "ready", "partial_refunded", "refunded"].map((s) => <option key={s} value={s}>{st(s)}</option>)}</Select>
        <Select className="!w-32" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="">전체 구분</option><option value="live">실결제</option><option value="test">PG 테스트</option><option value="mock">모의</option></Select></div>} />
      <Card pad={false}><Table rows={list.data} onRow={openPay} empty="결제 내역이 없습니다" cols={[{ key: "order_no", label: "주문번호", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "mode", label: "구분", render: (r) => (r.mode === "mock" ? <MockTag /> : r.mode) }, { key: "provider", label: "PG" }, { key: "method", label: "수단" },
        { key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "refunded_amount", label: "환불", right: true, render: (r) => won(r.refunded_amount) }, { key: "failure_code", label: "오류 코드", mono: true }, { key: "created_at", label: "일시", mono: true, render: (r) => dt(r.approved_at || r.created_at) }]} /></Card>
      <div className="mt-4"><Card title="웹훅 수신 기록" pad={false}><Table rows={events.data} empty="수신된 웹훅이 없습니다" cols={[{ key: "provider", label: "PG" }, { key: "event_type", label: "이벤트", mono: true }, { key: "processed", label: "처리", render: (r) => (r.processed ? "완료" : "미처리") }, { key: "note", label: "처리 결과" }, { key: "created_at", label: "수신", mono: true, render: (r) => dt(r.created_at) }]} /></Card></div>
      {open && <Modal title={`결제 상세 · ${open.order_no}`} onClose={() => setOpen(null)} wide>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">{[["상태", st(open.status)], ["구분", open.mode], ["금액", won(open.amount)], ["환불 누계", won(open.refunded_amount)], ["수단", open.method || "-"], ["승인일", dt(open.approved_at)], ["오류", open.failure_message || "-"]].map(([k, v]) => <div key={k}><dt className="text-xs text-mute">{k}</dt><dd>{v}</dd></div>)}</dl>
        {open.receipt_url && <a className="mt-3 inline-block text-sm underline" href={open.receipt_url} target="_blank" rel="noreferrer">영수증 보기</a>}
        <h3 className="mb-2 mt-4 text-[13px] text-mute">환불 내역</h3><Table rows={open.refunds} empty="환불 내역 없음" cols={[{ key: "amount", label: "금액", right: true, render: (r) => won(r.amount) }, { key: "reason", label: "사유" }, { key: "provider_ref", label: "PG 참조", mono: true }, { key: "created_at", label: "일시", mono: true, render: (r) => dt(r.created_at) }]} />
        {["paid", "partial_refunded"].includes(open.status) && <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (!confirm("환불을 진행할까요? PG에 결제 취소가 요청됩니다")) return; a.run(() => post(`/admin/payments/${open.id}/refund`, { amount: rf.amount ? Number(rf.amount) : null, reason: rf.reason, idempotency_key: open.idem })).then((r) => { if (r) { setOpen(null); list.reload(); } }); }}>
          <Field label="환불 금액" hint={`비우면 잔액 전체(${won(open.amount - open.refunded_amount)}) · 전체 환불 시 검사가 중단됩니다`}><Input type="number" min={1} max={open.amount - open.refunded_amount} value={rf.amount} onChange={(e) => setRf({ ...rf, amount: e.target.value })} /></Field>
          <Field label="사유"><Input value={rf.reason} onChange={(e) => setRf({ ...rf, reason: e.target.value })} required /></Field><Button variant="danger" disabled={a.busy}>환불·결제 취소</Button></form>}
        <div className="mt-3"><Msg a={a} /></div>
      </Modal>}
    </>
  );
}

export function Revenue() {
  const [unit, setUnit] = useState("day");
  const d = useLoad(() => get(`/admin/revenue?unit=${unit}`), [unit]);
  const cols: Col<any>[] = [{ key: "period", label: "기간", mono: true }, { key: "count", label: "결제 건수", right: true }, { key: "amount", label: "결제 금액", right: true, render: (r) => won(r.amount) }, { key: "refunded", label: "환불", right: true, render: (r) => won(r.refunded) }, { key: "net", label: "순매출", right: true, render: (r) => won(r.net) }];
  return (
    <>
      <PageHead title="매출 현황" action={<div className="flex gap-1">{[["day", "일별"], ["month", "월별"], ["year", "연간"]].map(([k, l]) => <Button key={k} size="sm" variant={unit === k ? "primary" : "secondary"} onClick={() => setUnit(k)}>{l}</Button>)}</div>} />
      <Card title="실매출 (실결제 + PG 테스트 모드 제외 여부는 구분 열 참고)"><Bars unit="원" data={(d.data?.real || []).slice(0, 12).reverse().map((r: any) => ({ label: r.period.slice(-5), value: r.net }))} /></Card>
      <div className="mt-4"><Card title="실매출 내역" pad={false}><Table rows={d.data?.real} empty="실결제 내역이 없습니다" cols={cols} /></Card></div>
      <div className="mt-4"><Card title={<span className="flex items-center gap-2">모의 결제 집계 <MockTag /></span>} pad={false}><Table rows={d.data?.mock} empty="모의 결제 내역이 없습니다" cols={cols} /></Card></div>
    </>
  );
}

export function Refunds() {
  const r = useLoad<any[]>(() => get("/admin/refunds"));
  return <><PageHead title="환불·취소 관리" desc="환불 처리는 결제 현황의 결제 상세에서 진행합니다" action={<Link to="/admin/payments"><Button>결제 현황</Button></Link>} /><Card pad={false}><Table rows={r.data} empty="환불 내역이 없습니다" cols={[{ key: "order_no", label: "주문번호", mono: true }, { key: "mode", label: "구분", render: (x) => (x.mode === "mock" ? <MockTag /> : x.mode) }, { key: "amount", label: "환불 금액", right: true, render: (x) => won(x.amount) }, { key: "reason", label: "사유" }, { key: "status", label: "상태", render: (x) => <Dot status={x.status} /> }, { key: "provider_ref", label: "PG 참조", mono: true }, { key: "created_at", label: "일시", mono: true, render: (x) => dt(x.created_at) }]} /></Card></>;
}

export function PgSettings() {
  const d = useLoad(() => get("/admin/pg"));
  const [f, setF] = useState<any>(null);
  const [test, setTest] = useState<any>(null);
  const a = useAction();
  const cur = f || { mode: d.data?.state.mode || "disabled", client_key: d.data?.state.client_key ?? d.data?.settings.find((s: any) => s.key === "pg.toss.client_key")?.value ?? "", secret_key: "" };
  const secret = d.data?.settings.find((s: any) => s.key === "pg.toss.secret_key");
  return (
    <>
      <PageHead title="PG 설정" desc="인증정보를 등록하기 전에는 실제 결제가 비활성화됩니다" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="토스페이먼츠">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => put("/admin/pg", { provider: "toss", ...cur, secret_key: cur.secret_key || null }), "저장되었습니다").then((r) => { if (r) { setF(null); d.reload(); } }); }}>
            <Field label="PG사"><Select disabled value="toss">{(d.data?.providers || []).map((p: any) => <option key={p.code} value={p.code}>{p.name}</option>)}</Select></Field>
            <Field label="결제 모드" hint="모의: PG 없이 전체 흐름 검증 · 테스트: test_ 키 · 운영: live_ 키"><Select value={cur.mode} onChange={(e) => setF({ ...cur, mode: e.target.value })}><option value="disabled">결제 비활성화</option><option value="mock">모의 결제 환경</option><option value="test">테스트 모드</option><option value="live">운영 모드</option></Select></Field>
            <Field label="Client Key"><Input className="font-mono" value={cur.client_key} onChange={(e) => setF({ ...cur, client_key: e.target.value })} placeholder="test_ck_… / live_ck_…" /></Field>
            <Field label="Secret Key" hint={secret?.is_set ? `등록됨 (${secret.hint}). 변경할 때만 입력` : "암호화하여 저장되며 다시 표시되지 않습니다"}><Input className="font-mono" type="password" autoComplete="new-password" value={cur.secret_key} onChange={(e) => setF({ ...cur, secret_key: e.target.value })} placeholder="test_sk_… / live_sk_…" /></Field>
            <Msg a={a} /><div className="flex gap-2"><Button variant="primary" disabled={a.busy}>저장</Button><Button type="button" onClick={() => post("/admin/pg/test").then(setTest)}>연동 시험</Button></div>
            {test && <Notice tone={test.ok ? "ok" : "warn"}>{test.message}</Notice>}
          </form>
        </Card>
        <Card title="연결 상태·주소">
          <dl className="space-y-4 text-sm">
            <div><dt className="text-xs text-mute">결제 활성화</dt><dd className="mt-1"><Dot status={d.data?.state.enabled ? "active" : "disabled"} label={d.data?.state.enabled ? `활성 (${d.data.state.mode})` : "비활성"} /></dd></div>
            {[["Webhook URL (토스 개발자센터에 등록)", d.data?.webhook_url], ["결제 성공 URL", d.data?.success_url], ["결제 실패 URL", d.data?.fail_url]].map(([k, v]) => <div key={k}><dt className="text-xs text-mute">{k}</dt><dd className="mt-1 break-all font-mono text-[13px]">{v}</dd></div>)}
          </dl>
          <div className="mt-4"><Notice>웹훅은 내용을 그대로 믿지 않고 PG에 결제를 재조회해 상태를 동기화합니다. 실제 결제·취소 검증은 가맹점 인증정보 등록 후 진행해 주세요</Notice></div>
        </Card>
      </div>
    </>
  );
}

// ---------------- 장비 ----------------
const CELL: Record<string, string> = { idle: "bg-[#2dd4bf]", assigned: "bg-[#60a5fa]", testing: "bg-[#fbbf24]", offline: "bg-[#52525b]", error: "bg-[#f87171]", overheat: "bg-[#f87171]", low_storage: "bg-[#fb923c]", maintenance: "bg-[#a78bfa]", disabled: "bg-[#3f3f46]", online: "bg-[#2dd4bf]" };

export function DevicesPage() {
  const [f, setF] = useState({ status: "", group: "", mock: "" });
  const d = useLoad(() => get(`/admin/devices?status=${f.status}${f.group ? `&group_id=${f.group}` : ""}${f.mock ? `&mock=${f.mock}` : ""}`), [f.status, f.group, f.mock], 10000);
  const groups = useLoad<any[]>(() => get("/admin/device-groups"));
  const apps = useLoad<any[]>(() => get("/admin/apps"));
  const [sel, setSel] = useState<number[]>([]);
  const [open, setOpen] = useState<any>(null);
  const [cmd, setCmd] = useState({ type: "screenshot", package: "", app_version_id: "" });
  const [sent, setSent] = useState<string>("");
  const results = useLoad<any[]>(() => (sent ? get(`/admin/commands?ids=${sent}`) : Promise.resolve([])), [sent], sent ? 3000 : undefined);
  const a = useAction();
  const items: any[] = d.data?.items || [];
  const toggle = (id: number) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const send = (ids: number[], type = cmd.type) => {
    const params: any = {};
    if (["uninstall", "launch", "stop", "app_version"].includes(type)) params.package = cmd.package;
    if (type === "install_apk") params.app_version_id = Number(cmd.app_version_id);
    if (type === "reboot" && !confirm(`기기 ${ids.length}대를 재부팅할까요?`)) return;
    a.run(() => post("/admin/commands", { device_ids: ids, type, params }), `${ids.length}대에 명령을 보냈습니다`).then((r) => r && setSent(r.map((c: any) => c.id).join(",")));
  };
  const needsPkg = ["uninstall", "launch", "stop", "app_version"].includes(cmd.type);
  return (
    <>
      <PageHead title="폰팜 통합 관리" desc="기기를 선택해 승인된 명령을 보냅니다. 임의 셸 명령은 지원하지 않습니다" action={<div className="flex flex-wrap gap-2">
        <Select className="!w-36" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">전체 상태</option>{Object.keys(CELL).filter((k) => k !== "online").map((s) => <option key={s} value={s}>{st(s)} {d.data?.counts?.[s] ? `(${d.data.counts[s]})` : ""}</option>)}</Select>
        <Select className="!w-36" value={f.group} onChange={(e) => setF({ ...f, group: e.target.value })}><option value="">전체 그룹</option>{(groups.data || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select>
        <Select className="!w-32" value={f.mock} onChange={(e) => setF({ ...f, mock: e.target.value })}><option value="">실기기+모의</option><option value="false">실기기만</option><option value="true">모의만</option></Select></div>} />
      <div className="rounded-panel bg-rack-bg p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-xs text-rack-text">
          <span>{items.length} DEVICES</span>{Object.entries(d.data?.counts || {}).map(([k, v]) => <span key={k} className="flex items-center gap-1.5"><i className={cx("h-1.5 w-1.5 rounded-full", CELL[k])} />{st(k)} {v as number}</span>)}
          <button className="ml-auto underline" onClick={() => setSel(sel.length === items.length ? [] : items.map((x) => x.id))}>{sel.length === items.length && items.length ? "선택 해제" : "전체 선택"}</button>
        </div>
        {!items.length && <p className="py-12 text-center font-mono text-xs text-rack-text">{d.data ? "연결된 기기가 없습니다. PC 에이전트를 설치하고 장비를 연결해 주세요" : "불러오는 중"}</p>}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(132px,1fr))] gap-2">{items.map((x) => (
          <div key={x.id} role="button" tabIndex={0} onClick={() => toggle(x.id)} onDoubleClick={() => get(`/admin/devices/${x.id}`).then(setOpen)} onKeyDown={(e) => e.key === "Enter" && toggle(x.id)}
            className={cx("cursor-pointer rounded-ctl border p-2.5 text-left transition-colors duration-150", sel.includes(x.id) ? "border-[#2dd4bf] bg-[#232325]" : "border-rack-line bg-rack-cell hover:bg-[#232325]", !x.enabled && "opacity-50")}>
            <div className="flex items-center justify-between"><span className={cx("h-1.5 w-1.5 rounded-full", CELL[x.status])} /><span className="font-mono text-[10px] text-rack-text">{x.is_mock ? "MOCK" : `A${x.android_version}`}</span></div>
            <div className="mt-2 truncate text-[13px] text-[#ededed]">{x.name || x.serial}</div>
            <div className="truncate font-mono text-[10px] text-rack-text">{x.serial}</div>
            <div className="mt-2 flex justify-between font-mono text-[10px] text-rack-text"><span>{st(x.status)}</span><span>{x.battery}% · {x.temperature}℃</span></div>
            <div className="mt-1 h-3 truncate font-mono text-[10px] text-[#fbbf24]">{x.current_job ? `${x.current_job.package} ${x.current_job.progress}%` : ""}</div>
            <button className="mt-1 font-mono text-[10px] text-rack-text underline" onClick={(e) => { e.stopPropagation(); get(`/admin/devices/${x.id}`).then(setOpen); }}>상세</button>
          </div>))}</div>
      </div>
      <div className="mt-4"><Card title={`원격 제어 · 선택 ${sel.length}대`}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="명령"><Select className="!w-48" value={cmd.type} onChange={(e) => setCmd({ ...cmd, type: e.target.value })}>{[["screenshot", "화면 확인(스크린샷)"], ["status", "기기 상태 확인"], ["storage", "저장공간 확인"], ["install_apk", "허가된 APK 설치"], ["launch", "앱 실행"], ["stop", "앱 종료"], ["app_version", "앱 버전 조회"], ["uninstall", "검사 대상 앱 삭제"], ["reconnect", "ADB 재연결"], ["reboot", "기기 재부팅"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>
          {needsPkg && <Field label="대상 앱"><Select className="!w-64" value={cmd.package} onChange={(e) => setCmd({ ...cmd, package: e.target.value })}><option value="">선택</option>{(apps.data || []).map((x) => <option key={x.id} value={x.package_name}>{x.name} ({x.package_name})</option>)}</Select></Field>}
          {cmd.type === "install_apk" && <Field label="앱 버전(APK)"><Select className="!w-72" value={cmd.app_version_id} onChange={(e) => setCmd({ ...cmd, app_version_id: e.target.value })}><option value="">선택</option>{(apps.data || []).flatMap((x) => x.versions.filter((v: any) => v.file?.status === "clean").map((v: any) => <option key={v.id} value={v.id}>{x.name} {v.version_name} ({v.version_code})</option>))}</Select></Field>}
          <Button variant="primary" disabled={!sel.length || a.busy || (needsPkg && !cmd.package) || (cmd.type === "install_apk" && !cmd.app_version_id)} onClick={() => send(sel)}>명령 보내기</Button>
        </div>
        <div className="mt-3"><Msg a={a} /></div>
        {!!results.data?.length && <div className="-mx-5 mt-4 border-t border-line"><Table rows={results.data} cols={[{ key: "device_id", label: "기기", render: (r) => items.find((x) => x.id === r.device_id)?.name || r.device_id }, { key: "type", label: "명령", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> },
          { key: "result", label: "결과", render: (r) => (r.result?.screenshot_url ? <a href={r.result.screenshot_url} target="_blank" rel="noreferrer"><img src={r.result.screenshot_url} alt="" className="h-24 rounded border border-line" /></a> : <span className="break-all text-sub">{r.result?.message}</span>) }]} /></div>}
        <p className="mt-4 text-xs text-mute">실시간 화면은 스크린샷 주기 갱신 방식입니다. 연속 미러링은 제어 PC의 에이전트 프로그램에서 scrcpy로 실행합니다</p>
      </Card></div>
      {open && <DeviceModal data={open} groups={groups.data || []} onClose={() => setOpen(null)} onChanged={() => { d.reload(); get(`/admin/devices/${open.device.id}`).then(setOpen); }} />}
    </>
  );
}

function DeviceModal({ data, groups, onClose, onChanged }: { data: any; groups: any[]; onClose: () => void; onChanged: () => void }) {
  const x = data.device;
  const a = useAction();
  const save = (body: any) => a.run(() => patch(`/admin/devices/${x.id}`, body)).then((r) => r && onChanged());
  return (
    <Modal title={x.name || x.serial} onClose={onClose} wide>
      <div className="mb-4 flex flex-wrap items-center gap-3"><Dot status={x.status} />{x.is_mock && <MockTag />}<span className="num text-[13px] text-mute">{x.serial} · {x.agent_name} · 마지막 연결 {ago(x.last_seen_at)}</span></div>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">{[["제조사", x.manufacturer], ["모델", x.model], ["Android", `${x.android_version} (SDK ${x.sdk})`], ["CPU", x.cpu], ["RAM", `${num(x.ram_mb)} MB`], ["저장공간", `${num(x.storage_free_mb)} / ${num(x.storage_total_mb)} MB`], ["배터리", `${x.battery}%`], ["온도", `${x.temperature}℃`], ["해상도", x.resolution], ["네트워크", x.network], ["ADB 상태", x.conn_state], ["마지막 검사", dt(x.last_test_at)]].map(([k, v]) => <div key={k}><dt className="text-xs text-mute">{k}</dt><dd className="num">{v || "-"}</dd></div>)}</dl>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Field label="기기 이름"><Input defaultValue={x.name} onBlur={(e) => e.target.value !== x.name && save({ name: e.target.value })} /></Field>
        <Field label="그룹"><Select value={x.group_id || ""} onChange={(e) => save(e.target.value ? { group_id: Number(e.target.value) } : { clear_group: true })}><option value="">없음</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></Field>
        <Field label="메모"><Input defaultValue={x.notes} onBlur={(e) => e.target.value !== x.notes && save({ notes: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Field label="기기에 로그인된 Google 계정 이메일" hint="고객에게 '검사 기기 계정 목록'으로 제공됩니다. 비밀번호는 입력·저장하지 않습니다"><Input type="email" defaultValue={x.google_account_email} placeholder="example@gmail.com" onBlur={(e) => e.target.value !== x.google_account_email && save({ google_account_email: e.target.value })} /></Field></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-6"><Check label="사용 (해제 시 사용 중지)" checked={x.enabled} onChange={(e) => save({ enabled: e.target.checked })} /><Check label="유지보수 중" checked={x.maintenance} onChange={(e) => save({ maintenance: e.target.checked })} />
        <Check label="Google 계정 로그인 확인함 (운영자가 기기에서 직접 로그인 · 비밀번호는 저장하지 않음)" checked={x.google_account_confirmed} onChange={(e) => save({ google_account_confirmed: e.target.checked })} /></div>
      <div className="mt-3"><Msg a={a} /></div>
      {Object.keys(x.installed_apps).length > 0 && <p className="num mt-4 text-[13px] text-sub">설치된 검사 대상 앱: {Object.entries(x.installed_apps).map(([p, v]) => `${p} ${v}`).join(", ")}</p>}
      <h3 className="mb-2 mt-5 text-[13px] text-mute">배정 이력</h3><Table rows={data.assignments} empty="배정 이력 없음" cols={[{ key: "app", label: "앱" }, { key: "status", label: "배정", render: (r) => <Dot status={r.status} /> }, { key: "plan_status", label: "검사", render: (r) => <Dot status={r.plan_status} /> }, { key: "assigned_at", label: "배정일", mono: true, render: (r) => dt(r.assigned_at) }]} />
      <h3 className="mb-2 mt-5 text-[13px] text-mute">최근 상태 기록</h3><Table rows={data.heartbeats.slice(-8).reverse()} empty="기록 없음" cols={[{ key: "at", label: "시각", mono: true, render: (r) => dt(r.at) }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "battery", label: "배터리", right: true, render: (r) => `${r.battery}%` }, { key: "temperature", label: "온도", right: true, render: (r) => `${r.temperature}℃` }, { key: "storage_free_mb", label: "여유 공간(MB)", right: true, render: (r) => num(r.storage_free_mb) }]} />
      <div className="mt-4 text-right"><Button variant="danger" size="sm" onClick={() => confirm("기기 등록을 삭제할까요? 검사 이력이 있으면 삭제되지 않습니다") && a.run(() => del(`/admin/devices/${x.id}`)).then((r) => r && (onClose(), onChanged()))}>등록 삭제</Button></div>
    </Modal>
  );
}

export function Agents() {
  const list = useLoad<any[]>(() => get("/admin/agents"), [], 10000);
  const dl = useLoad(() => get("/admin/agent-downloads"));
  const [form, setForm] = useState<any>(null);
  const [code, setCode] = useState<any>(null);
  const a = useAction();
  return (
    <>
      <PageHead title="PC 에이전트" desc="제어용 PC에 설치하는 Google Auto Tester Agent를 관리합니다" action={<Button variant="primary" onClick={() => setForm({ name: "", kind: "real" })}>에이전트 등록</Button>} />
      <Msg a={a} />
      <Card pad={false}><Table rows={list.data} empty="등록된 에이전트가 없습니다" cols={[{ key: "name", label: "이름", render: (r) => <span className="flex items-center gap-2 font-medium">{r.name}{r.kind === "mock" && <MockTag />}</span> }, { key: "uid", label: "에이전트 ID", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> },
        { key: "hostname", label: "호스트", render: (r) => <span className="text-sub">{r.hostname} {r.os && `· ${r.os}`}</span> }, { key: "version", label: "버전", mono: true }, { key: "devices", label: "기기", right: true, render: (r) => `${r.devices_online}/${r.devices}` }, { key: "last_seen_at", label: "마지막 연결", mono: true, render: (r) => ago(r.last_seen_at) },
        { key: "tok", label: "인증키 만료", mono: true, render: (r) => dt(r.tokens.find((t: any) => t.active)?.expires_at, false) },
        { key: "_", label: "", right: true, render: (r) => r.status !== "revoked" && <span className="flex justify-end gap-1"><Button size="sm" onClick={() => a.run(() => post(`/admin/agents/${r.id}/enroll-code`)).then((x) => x && setCode({ ...r, enroll_code: x.enroll_code }))}>등록 코드 발급</Button>
          <Button size="sm" variant="danger" onClick={() => confirm("이 에이전트의 인증키를 모두 폐기하고 사용을 중지할까요?") && a.run(() => post(`/admin/agents/${r.id}/revoke`)).then(list.reload)}>인증키 폐기</Button></span> }]} /></Card>
      <div className="mt-4"><Card title="에이전트 다운로드">
        <p className="mb-4 text-sm text-sub">최신 버전 <span className="num">{dl.data?.latest_version}</span> · {dl.data?.note}</p>
        <div className="flex flex-wrap gap-3">{(dl.data?.files || []).map((f: any) => <a key={f.name} href={f.url}><Button>{f.os} · {f.name}</Button></a>)}<a href={dl.data?.releases_url} target="_blank" rel="noreferrer"><Button variant="ghost">전체 릴리스</Button></a></div>
      </Card></div>
      {form && <Modal title="에이전트 등록" onClose={() => setForm(null)}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => post("/admin/agents", form)).then((r) => { if (r) { setForm(null); setCode(r); list.reload(); } }); }}>
          <Field label="이름" hint="예: 1호 제어 PC"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
          <Field label="종류" hint="모의 에이전트의 기기와 결과는 실제 검사 결과와 분리되며 모의 결제 주문에만 배정됩니다"><Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}><option value="real">실기기 폰팜</option><option value="mock">모의 장비(시스템 검증용)</option></Select></Field>
          <Msg a={a} /><div className="text-right"><Button variant="primary" disabled={a.busy}>등록</Button></div>
        </form></Modal>}
      {code && <Modal title="에이전트 등록 코드" onClose={() => setCode(null)}>
        <Notice tone="warn">이 코드는 지금만 표시되며 24시간 동안 1회 사용할 수 있습니다</Notice>
        <dl className="mt-4 space-y-3 text-sm"><div><dt className="text-xs text-mute">서버 주소</dt><dd className="font-mono">{location.origin}</dd></div><div><dt className="text-xs text-mute">에이전트 ID</dt><dd className="font-mono">{code.uid}</dd></div>
          <div><dt className="text-xs text-mute">등록 코드</dt><dd className="break-all rounded-ctl bg-raised p-3 font-mono text-[15px]">{code.enroll_code}</dd></div></dl>
        <pre className="mt-4 overflow-x-auto rounded-ctl bg-rack-bg p-3 font-mono text-xs text-[#ededed]">{`gat-agent enroll --server ${location.origin} --code ${code.enroll_code}`}</pre>
        <div className="mt-4 text-right"><Button onClick={() => navigator.clipboard.writeText(code.enroll_code)}>코드 복사</Button></div>
      </Modal>}
    </>
  );
}

export function Incidents() {
  const d = useLoad(() => get("/admin/incidents"), [], 15000);
  const a = useAction();
  const cmd = (id: number, type: string) => a.run(() => post("/admin/commands", { device_ids: [id], type, params: {} }), "명령을 보냈습니다");
  return (
    <>
      <PageHead title="장애·유지보수" desc="연결이 끊겼거나 과열·저장공간 부족 상태인 장비입니다" />
      <Msg a={a} />
      <Card title="문제 상태 기기" pad={false}><Table rows={d.data?.devices} empty="문제 상태인 기기가 없습니다" cols={[{ key: "name", label: "기기" }, { key: "serial", label: "Serial", mono: true }, { key: "agent_name", label: "에이전트" }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "temperature", label: "온도", right: true, render: (r) => `${r.temperature}℃` }, { key: "storage_free_mb", label: "여유(MB)", right: true, render: (r) => num(r.storage_free_mb) }, { key: "last_seen_at", label: "마지막 연결", mono: true, render: (r) => ago(r.last_seen_at) },
        { key: "_", label: "", right: true, render: (r) => <span className="flex justify-end gap-1"><Button size="sm" onClick={() => cmd(r.id, "reconnect")}>ADB 재연결</Button><Button size="sm" onClick={() => a.run(() => patch(`/admin/devices/${r.id}`, { maintenance: true })).then(d.reload)}>유지보수 전환</Button></span> }]} /></Card>
      <div className="mt-4"><Card title="오프라인 에이전트" pad={false}><Table rows={d.data?.agents} empty="오프라인 에이전트가 없습니다" cols={[{ key: "name", label: "이름" }, { key: "hostname", label: "호스트" }, { key: "devices", label: "기기 수", right: true }, { key: "last_seen_at", label: "마지막 연결", mono: true, render: (r) => ago(r.last_seen_at) }]} /></Card></div>
      <div className="mt-4"><Card title="장애 기록" pad={false}><LogTable rows={d.data?.logs} /></Card></div>
    </>
  );
}
const LogTable = ({ rows }: { rows: any[] | null | undefined }) => <Table rows={rows} empty="기록이 없습니다" cols={[{ key: "created_at", label: "시각", mono: true, width: "150px", render: (r) => dt(r.created_at) }, { key: "level", label: "수준", width: "80px", render: (r) => <Dot status={r.level === "error" ? "failed" : r.level === "warn" ? "queued" : "passed"} label={r.level} /> }, { key: "source", label: "출처", mono: true, width: "110px" }, { key: "message", label: "내용" }]} />;

// ---------------- 검사 ----------------
export function Live() {
  const d = useLoad(() => get("/admin/live"), [], 5000);
  return (
    <>
      <PageHead title="실시간 검사 현황" desc="5초마다 갱신됩니다" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4"><Stat label="실행 중" value={num(d.data?.running.length)} /><Stat label="대기 중" value={num(d.data?.queued)} /><Stat label="최근 1시간 성공" value={num(d.data?.last_hour?.passed)} /><Stat label="최근 1시간 실패·수행 불가" value={num((d.data?.last_hour?.failed || 0) + (d.data?.last_hour?.error || 0))} /></div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card title="실행 중인 작업" pad={false}><JobTable rows={d.data?.running} /></Card>
        <Card title="다음 예정 회차" pad={false}><Table rows={d.data?.upcoming} empty="예정된 검사가 없습니다" cols={[{ key: "app", label: "앱" }, { key: "devices", label: "기기", right: true }, { key: "next_run_at", label: "예정", mono: true, render: (r) => dt(r.next_run_at) }]} /></Card>
      </div>
    </>
  );
}
function JobTable({ rows, actions }: { rows: any[] | undefined; actions?: (r: any) => ReactNode }) {
  return <Table rows={rows} empty="작업이 없습니다" cols={[{ key: "id", label: "#", mono: true, width: "64px" }, { key: "package", label: "패키지", mono: true, render: (r) => <span className="flex items-center gap-2">{r.package}{r.is_mock && <MockTag />}</span> }, { key: "device", label: "기기" }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> },
    { key: "progress", label: "진행", right: true, render: (r) => `${r.progress}%` }, { key: "attempts", label: "시도", right: true, render: (r) => `${r.attempts}/${r.max_attempts}` }, { key: "next_attempt_at", label: "다음 시도", mono: true, render: (r) => (r.status === "queued" ? dt(r.next_attempt_at) : "-") }, { key: "error", label: "오류", render: (r) => <span className="block max-w-[260px] truncate text-sub" title={r.error}>{r.error}</span> },
    ...(actions ? [{ key: "_", label: "", right: true, render: actions }] : [])]} />;
}

export function Jobs() {
  const [status, setStatus] = useState("");
  const d = useLoad(() => get(`/admin/jobs?status=${status}`), [status], 10000);
  const a = useAction();
  const act = (id: number, action: string) => a.run(() => post(`/admin/jobs/${id}/${action}`)).then(d.reload);
  return (
    <>
      <PageHead title="검사 작업 대기열" action={<Select className="!w-44" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">전체</option>{["queued", "leased,running", "succeeded", "failed,timeout", "cancelled"].map((s) => <option key={s} value={s}>{s.split(",").map(st).join("·")} ({s.split(",").reduce((n, k) => n + (d.data?.counts?.[k] || 0), 0)})</option>)}</Select>} />
      <Msg a={a} />
      <Card pad={false}><JobTable rows={d.data?.items} actions={(r) => <span className="flex justify-end gap-1">{["queued", "leased", "running"].includes(r.status) && <Button size="sm" onClick={() => act(r.id, "cancel")}>취소</Button>}{["failed", "timeout", "cancelled"].includes(r.status) && <Button size="sm" onClick={() => act(r.id, "retry")}>재시도</Button>}</span>} /></Card>
    </>
  );
}

export function Plans() {
  const [status, setStatus] = useState("waiting_devices,scheduled,running,paused");
  const d = useLoad<any[]>(() => get(`/admin/plans?status=${status}`), [status], 15000);
  const [edit, setEdit] = useState<any>(null);
  const a = useAction();
  const act = (id: number, action: string, msg = "") => a.run(() => post(`/admin/plans/${id}/${action}`), msg).then(d.reload);
  return (
    <>
      <PageHead title="검사 스케줄" desc="시간은 UTC 기준입니다" action={<Select className="!w-48" value={status} onChange={(e) => setStatus(e.target.value)}><option value="waiting_devices,scheduled,running,paused">진행 중</option><option value="completed">완료</option><option value="cancelled">취소</option><option value="">전체</option></Select>} />
      <Msg a={a} />
      <Card pad={false}><Table rows={d.data} empty="검사 계획이 없습니다" cols={[{ key: "app", label: "앱", render: (r) => <span className="flex items-center gap-2 font-medium">{r.app}{r.is_mock && <MockTag />}</span> }, { key: "order_no", label: "주문번호", mono: true }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> },
        { key: "dev", label: "기기", right: true, render: (r) => `${r.assigned_devices}/${r.device_count}` }, { key: "daily_runs", label: "일일", right: true, render: (r) => (r.run_times.length ? r.run_times.join(" ") : `${r.daily_runs}회`) }, { key: "next_run_at", label: "다음 검사", mono: true, render: (r) => dt(r.next_run_at) }, { key: "end_at", label: "종료", mono: true, render: (r) => dt(r.end_at, false) },
        { key: "runs", label: "검사/성공률", right: true, render: (r) => `${r.total_runs} / ${r.success_rate ?? "-"}%` },
        { key: "_", label: "", right: true, render: (r) => <span className="flex justify-end gap-1">
          {r.status === "waiting_devices" && <Button size="sm" onClick={() => act(r.id, "allocate", "배정을 다시 시도했습니다")}>배정 시도</Button>}
          {["scheduled", "running"].includes(r.status) && <><Button size="sm" onClick={() => act(r.id, "run-now", "즉시 검사 작업을 만들었습니다")}>즉시 실행</Button><Button size="sm" onClick={() => act(r.id, "pause")}>일시정지</Button></>}
          {r.status === "paused" && <Button size="sm" onClick={() => act(r.id, "resume")}>재개</Button>}
          {!["completed", "cancelled"].includes(r.status) && <><Button size="sm" onClick={() => setEdit({ id: r.id, daily_runs: r.daily_runs, run_times: r.run_times.join(", "), priority: r.priority })}>일정</Button><Button size="sm" variant="ghost" onClick={() => confirm("검사를 취소할까요?") && act(r.id, "cancel")}>취소</Button></>}</span> }]} /></Card>
      {edit && <Modal title="검사 일정 변경" onClose={() => setEdit(null)}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => patch(`/admin/plans/${edit.id}`, { daily_runs: Number(edit.daily_runs), priority: Number(edit.priority), run_times: edit.run_times.split(/[\s,]+/).filter(Boolean) })).then((r) => { if (r) { setEdit(null); d.reload(); } }); }}>
          <Field label="일일 검사 횟수"><Input type="number" min={1} max={24} value={edit.daily_runs} onChange={(e) => setEdit({ ...edit, daily_runs: e.target.value })} /></Field>
          <Field label="특정 시간 검사 (UTC, HH:MM)" hint="비우면 일일 횟수에 맞춰 균등 간격으로 실행"><Input value={edit.run_times} onChange={(e) => setEdit({ ...edit, run_times: e.target.value })} placeholder="03:00, 15:00" /></Field>
          <Field label="우선순위" hint="숫자가 클수록 먼저 배정·실행"><Input type="number" value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: e.target.value })} /></Field>
          <Msg a={a} /><div className="text-right"><Button variant="primary" disabled={a.busy}>저장</Button></div></form></Modal>}
    </>
  );
}

export const AdminScenarios = () => <Scenarios base="/admin/scenarios" title="검사 시나리오" />;

function MockFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <Select className="!w-36" value={value} onChange={(e) => onChange(e.target.value)}><option value="false">실기기 결과</option><option value="true">모의 결과</option><option value="">전체</option></Select>;
}

export function Results() {
  const [f, setF] = useState({ status: "", mock: "false" });
  const d = useLoad<any[]>(() => get(`/admin/results?status=${f.status}${f.mock ? `&mock=${f.mock}` : ""}`), [f.status, f.mock]);
  const [open, setOpen] = useState<any>(null);
  return (
    <>
      <PageHead title="검사 결과" action={<div className="flex gap-2"><Select className="!w-36" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">전체 결과</option>{["passed", "failed", "error"].map((s) => <option key={s} value={s}>{st(s)}</option>)}</Select><MockFilter value={f.mock} onChange={(mock) => setF({ ...f, mock })} /></div>} />
      <Card pad={false}><Table rows={d.data} onRow={setOpen} empty="검사 결과가 없습니다" cols={[{ key: "created_at", label: "시각", mono: true, render: (r) => dt(r.created_at) }, { key: "app", label: "앱", render: (r) => <span className="flex items-center gap-2">{r.app}{r.is_mock && <MockTag />}</span> }, { key: "device", label: "기기" }, { key: "android", label: "Android", mono: true }, { key: "status", label: "결과", render: (r) => <Dot status={r.status} /> },
        { key: "steps", label: "단계", right: true, render: (r) => `${r.steps.filter((s: any) => s.status === "passed").length}/${r.steps.length}` }, { key: "crash_count", label: "크래시", right: true }, { key: "anr_count", label: "ANR", right: true }, { key: "duration_ms", label: "소요", right: true, render: (r) => `${(r.duration_ms / 1000).toFixed(1)}s` }]} /></Card>
      {open && <Modal title={`${open.app} · ${open.device}`} onClose={() => setOpen(null)} wide>{open.summary?.reason && <Notice tone="bad">{open.summary.reason}</Notice>}
        <table className="w-full text-[13px]"><tbody>{open.steps.map((s: any, i: number) => <tr key={i} className="border-t border-line align-top first:border-0"><td className="w-44 py-2 pr-3">{s.name}</td><td className="w-24 py-2"><Dot status={s.status} /></td><td className="py-2 text-sub">{s.expected && <span className="text-mute">기대: {s.expected} → </span>}{s.actual}</td></tr>)}</tbody></table>
        <pre className="mt-4 overflow-auto rounded-ctl bg-raised p-3 font-mono text-xs">{JSON.stringify(open.summary, null, 2)}</pre></Modal>}
    </>
  );
}

export function Crashes() {
  const [mock, setMock] = useState("false");
  const d = useLoad<any[]>(() => get(`/admin/crashes${mock ? `?mock=${mock}` : ""}`), [mock]);
  const [open, setOpen] = useState<any>(null);
  const a = useAction();
  return (
    <>
      <PageHead title="크래시·오류 분석" desc="규칙 기반 분류는 항상 동작합니다. AI 분석은 인증정보 등록 시에만 수행되며 '추정'으로 구분됩니다" action={<MockFilter value={mock} onChange={setMock} />} />
      <Card pad={false}><Table rows={d.data} onRow={(r) => { a.setError(""); setOpen(r); }} empty="수집된 오류가 없습니다" cols={[{ key: "created_at", label: "시각", mono: true, render: (r) => dt(r.created_at) }, { key: "app", label: "앱" }, { key: "kind", label: "종류", mono: true }, { key: "title", label: "제목", render: (r) => <span className="block max-w-[360px] truncate">{r.title}</span> },
        { key: "category", label: "분류" }, { key: "severity", label: "심각도", render: (r) => <Dot status={["critical", "high"].includes(r.severity) ? "failed" : r.severity === "medium" ? "queued" : "disabled"} label={r.severity} /> }, { key: "analysis_source", label: "분석", render: (r) => (r.analysis_source === "ai" ? "규칙+AI 추정" : "규칙 기반") }, { key: "signature", label: "서명", mono: true, render: (r) => r.signature.slice(0, 8) }]} /></Card>
      {open && <Modal title={open.title} onClose={() => setOpen(null)} wide>
        <p className="text-sm">{open.analysis?.rule?.advice}</p>
        {open.analysis?.ai && <div className="mt-3"><Notice tone="warn">{open.analysis.ai.error ? `AI 분석 실패: ${open.analysis.ai.error}` : `AI 추정(미확인): ${open.analysis.ai.cause || ""} · 권고: ${open.analysis.ai.advice || ""}`}</Notice></div>}
        <pre className="mt-4 max-h-80 overflow-auto rounded-ctl bg-raised p-3 font-mono text-xs leading-5">{open.detail}</pre>
        <div className="mt-4 space-y-3"><Msg a={a} /><Button disabled={a.busy} onClick={() => a.run(() => post(`/admin/crashes/${open.id}/analyze`)).then((r) => { if (r) { setOpen({ ...open, analysis: r.analysis }); if (!r.ai_configured) a.setError("AI 인증정보가 없어 규칙 기반 분석만 갱신했습니다"); d.reload(); } })}>분석 다시 실행</Button></div>
      </Modal>}
    </>
  );
}

export function Screenshots() {
  const d = useLoad<any[]>(() => get("/admin/screenshots"));
  return <><PageHead title="스크린샷" desc="최근 200건" /><Card>{d.data && !d.data.length && <p className="py-4 text-center text-sm text-mute">수집된 스크린샷이 없습니다</p>}
    <div className="grid grid-cols-3 gap-4 sm:grid-cols-5 lg:grid-cols-8">{(d.data || []).map((s) => <a key={s.id} href={s.url} target="_blank" rel="noreferrer"><img src={s.url} alt={s.label} loading="lazy" className="aspect-[9/16] w-full rounded-ctl border border-line bg-raised object-cover" /><span className="mt-1 flex items-center gap-1 truncate text-xs text-sub">{s.is_mock && <MockTag />}{s.label}</span><span className="num block text-[11px] text-mute">{dt(s.created_at)}</span></a>)}</div></Card></>;
}

export function AdminReports() {
  const d = useLoad(() => get("/admin/reports"));
  const plans = useLoad<any[]>(() => get("/admin/plans"));
  const [f, setF] = useState({ plan_id: "", kind: "comprehensive", fmt: "pdf" });
  const a = useAction();
  return (
    <>
      <PageHead title="보고서 관리" />
      <Card title="보고서 생성"><div className="flex flex-wrap items-end gap-3">
        <Field label="검사 계획"><Select className="!w-72" value={f.plan_id} onChange={(e) => setF({ ...f, plan_id: e.target.value })}><option value="">선택</option>{(plans.data || []).map((p) => <option key={p.id} value={p.id}>{p.app} · {p.order_no}{p.is_mock ? " · MOCK" : ""}</option>)}</Select></Field>
        <Field label="종류"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{Object.entries(d.data?.kinds || {}).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}</Select></Field>
        <Field label="형식"><Select value={f.fmt} onChange={(e) => setF({ ...f, fmt: e.target.value })}><option value="pdf">PDF</option><option value="xlsx">Excel</option></Select></Field>
        <Button variant="primary" disabled={!f.plan_id || a.busy} onClick={() => a.run(() => post("/admin/reports", { ...f, plan_id: Number(f.plan_id) }), "보고서를 생성했습니다").then(d.reload)}>생성</Button></div><div className="mt-3"><Msg a={a} /></div></Card>
      <div className="mt-4"><Card pad={false}><Table rows={d.data?.items} empty="발행된 보고서가 없습니다" cols={[{ key: "report_no", label: "보고서 번호", mono: true, render: (r) => <span className="flex items-center gap-2">{r.report_no}{r.is_mock && <MockTag />}</span> }, { key: "app", label: "앱" }, { key: "kind_name", label: "종류" }, { key: "fmt", label: "형식", mono: true }, { key: "size", label: "크기", right: true, render: (r) => size(r.size) }, { key: "created_at", label: "발행일", mono: true, render: (r) => dt(r.created_at) },
        { key: "_", label: "", right: true, render: (r) => <Button size="sm" onClick={() => download(`/reports/${r.id}/download`, `${r.report_no}.${r.fmt}`)}>다운로드</Button> }]} /></Card></div>
    </>
  );
}

// ---------------- 고객지원 ----------------
export function Tickets() {
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const d = useLoad<any[]>(() => get(`/admin/tickets?status=${status}`), [status], 30000);
  return <><PageHead title="고객 문의" action={<Select className="!w-36" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">전체</option>{["open", "answered", "closed"].map((s) => <option key={s} value={s}>{st(s)}</option>)}</Select>} />
    <Card pad={false}><Table rows={d.data} onRow={(r) => nav(`/admin/tickets/${r.id}`)} empty="문의가 없습니다" cols={[{ key: "subject", label: "제목" }, { key: "customer_email", label: "고객" }, { key: "category", label: "분류" }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "updated_at", label: "최근 갱신", mono: true, render: (r) => dt(r.updated_at) }]} /></Card></>;
}
export const TicketDetail = () => { const { id } = useParams(); return <Thread key={id} back="/admin/tickets" load={() => get(`/admin/tickets/${id}`)} send={(body, close) => post(`/admin/tickets/${id}/reply`, { body, close })} />; };

export function LegalAdmin() {
  const d = useLoad<any[]>(() => get("/admin/legal"));
  const [edit, setEdit] = useState<any>(null);
  const a = useAction();
  const names: Record<string, string> = { terms: "이용약관", privacy: "개인정보처리방침", refund: "환불 정책" };
  return (
    <>
      <PageHead title="약관·정책" desc="운영 개시 전 사업자 정보와 세부 조항을 확정해 주세요" action={<Button onClick={() => setEdit({ key: "terms", locale: "en", title: "", body: "" })}>다른 언어 추가</Button>} />
      <Card pad={false}><Table rows={d.data} cols={[{ key: "key", label: "문서", render: (r) => names[r.key] }, { key: "locale", label: "언어", mono: true }, { key: "title", label: "제목" }, { key: "updated_at", label: "최종 수정", mono: true, render: (r) => dt(r.updated_at) }, { key: "_", label: "", right: true, render: (r) => <Button size="sm" onClick={() => setEdit(r)}>수정</Button> }]} /></Card>
      {edit && <Modal title="문서 편집" onClose={() => setEdit(null)} wide>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); a.run(() => put(`/admin/legal/${edit.key}`, { title: edit.title, body: edit.body, locale: edit.locale })).then((r) => { if (r) { setEdit(null); d.reload(); } }); }}>
          <div className="grid gap-4 sm:grid-cols-3"><Field label="문서"><Select value={edit.key} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, key: e.target.value })}>{Object.entries(names).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <Field label="언어"><Select value={edit.locale} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, locale: e.target.value })}>{["ko", "en", "ja", "zh"].map((l) => <option key={l}>{l}</option>)}</Select></Field><Field label="제목"><Input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} required /></Field></div>
          <Textarea className="!min-h-[360px]" value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} />
          <Msg a={a} /><div className="text-right"><Button variant="primary" disabled={a.busy}>저장</Button></div></form></Modal>}
    </>
  );
}

// ---------------- 시스템 ----------------
const GROUPS: [string, string, string][] = [["site.", "기본 환경·다국어", ""], ["smtp.", "이메일(SMTP)", "미설정 시 이메일은 발송되지 않고 대기열에 '미발송'으로 기록됩니다"], ["ai.", "AI 연동(선택)", "미설정 시 규칙 기반 오류 분석만 동작합니다"],
  ["google.", "Google OAuth 로그인", "Google Cloud Console에서 OAuth 클라이언트를 만들고 리디렉션 URI에 /api/auth/google/callback 을 등록합니다"], ["storage.", "스토리지", ""], ["limits.", "검사·장비 한도", ""], ["retention.", "데이터 보존", ""], ["agent.", "PC 에이전트", ""]];

export function SettingsPage() {
  const d = useLoad<any[]>(() => get("/admin/settings"));
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [mail, setMail] = useState("");
  const [test, setTest] = useState<any>(null);
  const a = useAction();
  const save = () => a.run(() => put("/admin/settings", edits), "저장되었습니다").then((r) => { if (r) { setEdits({}); d.reload(); } });
  return (
    <>
      <PageHead title="환경 설정" desc="비밀값은 암호화하여 저장되며 다시 표시되지 않습니다. PG 키는 결제관리 > PG 설정에서 다룹니다" action={<Button variant="primary" disabled={!Object.keys(edits).length || a.busy} onClick={save}>변경 사항 저장</Button>} />
      <div className="mb-4"><Msg a={a} /></div>
      <div className="grid gap-4 xl:grid-cols-2">{GROUPS.map(([prefix, title, note]) => (
        <Card key={prefix} title={title}>
          {note && <p className="mb-4 text-[13px] text-mute">{note}</p>}
          <div className="space-y-4">{(d.data || []).filter((s) => s.key.startsWith(prefix)).map((s) => (
            <Field key={s.key} label={s.description} hint={s.is_secret ? (s.is_set ? `등록됨 (${s.hint}). 변경할 때만 입력` : "미등록") : s.key}>
              <Input type={s.is_secret ? "password" : "text"} autoComplete="new-password" className={s.is_secret ? "font-mono" : ""} value={edits[s.key] ?? (s.is_secret ? "" : s.value)} onChange={(e) => setEdits({ ...edits, [s.key]: e.target.value })} /></Field>))}</div>
          {prefix === "smtp." && <div className="mt-4 flex items-end gap-3"><Field label="시험 메일 수신 주소"><Input type="email" value={mail} onChange={(e) => setMail(e.target.value)} /></Field><Button disabled={!mail} onClick={() => post("/admin/settings/test-email", { to: mail }).then(setTest)}>시험 발송</Button></div>}
          {prefix === "ai." && <div className="mt-4"><Button onClick={() => post("/admin/settings/test-ai").then(setTest)}>연동 시험</Button></div>}
          {test && ["smtp.", "ai."].includes(prefix) && <div className="mt-3"><Notice tone={test.ok ? "ok" : "warn"}>{test.message}</Notice></div>}
        </Card>))}</div>
    </>
  );
}

export function StatusPage() {
  const d = useLoad(() => get("/admin/status"), [], 15000);
  const x = d.data;
  return (
    <>
      <PageHead title="서버·DB 상태" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="서버 가동 시간" value={x ? `${Math.floor(x.server.uptime_sec / 3600)}h ${Math.floor((x.server.uptime_sec % 3600) / 60)}m` : "-"} note={x?.server.env} />
        <Stat label="스케줄러" value={x ? (x.server.scheduler_running ? "실행 중" : "중지") : "-"} />
        <Stat label="데이터베이스" value={x ? `${x.database.ping_ms} ms` : "-"} note={x ? `PostgreSQL ${x.database.version} · ${x.database.size_mb} MB · 마이그레이션 ${x.database.migration}` : ""} />
        <Stat label="저장소 여유 공간" value={x?.storage.free_mb != null ? `${num(x.storage.free_mb)} MB` : "-"} note={x ? `${x.storage.path} · ${x.storage.writable ? "쓰기 가능" : "쓰기 불가"}` : ""} />
      </div>
      <div className="mt-4"><Card title="테이블별 행 수 (통계 기준 추정치)" pad={false}><Table rows={x?.database.tables} cols={[{ key: "name", label: "테이블", mono: true }, { key: "rows", label: "행 수", right: true, render: (r) => num(r.rows) }]} /></Card></div>
    </>
  );
}

export function Emails() {
  const d = useLoad(() => get("/admin/emails"), [], 30000);
  return <><PageHead title="이메일 발송 내역" desc="실제 발송 여부를 상태로 구분합니다" />
    {d.data && !d.data.smtp_configured && <div className="mb-4"><Notice tone="warn">SMTP가 설정되지 않아 이메일이 실제로 발송되지 않습니다</Notice></div>}
    <div className="mb-4 flex flex-wrap gap-6 text-sm">{Object.entries(d.data?.counts || {}).map(([k, v]) => <span key={k} className="flex items-center gap-2"><Dot status={k} /><span className="num">{v as number}</span></span>)}</div>
    <Card pad={false}><Table rows={d.data?.items} empty="발송 내역이 없습니다" cols={[{ key: "created_at", label: "생성", mono: true, render: (r) => dt(r.created_at) }, { key: "to", label: "수신" }, { key: "event", label: "이벤트", mono: true }, { key: "title", label: "제목" }, { key: "status", label: "상태", render: (r) => <Dot status={r.status} /> }, { key: "attempts", label: "시도", right: true }, { key: "last_error", label: "오류" }]} /></Card></>;
}

export function Audit() {
  const d = useLoad<any[]>(() => get("/admin/audit-logs"));
  return <><PageHead title="관리자 활동 기록" /><Card pad={false}><Table rows={d.data} empty="기록이 없습니다" cols={[{ key: "created_at", label: "시각", mono: true, render: (r) => dt(r.created_at) }, { key: "actor", label: "관리자" }, { key: "action", label: "작업", mono: true }, { key: "target", label: "대상", mono: true, render: (r) => `${r.target_type} ${r.target_id}` }, { key: "detail", label: "내용", render: (r) => <span className="block max-w-[420px] truncate font-mono text-xs text-sub" title={JSON.stringify(r.detail)}>{r.detail ? JSON.stringify(r.detail) : ""}</span> }, { key: "ip", label: "IP", mono: true }]} /></Card></>;
}

export function Logs() {
  const [level, setLevel] = useState("");
  const d = useLoad<any[]>(() => get(`/admin/system-logs?level=${level}`), [level], 30000);
  return <><PageHead title="시스템 로그" action={<Select className="!w-32" value={level} onChange={(e) => setLevel(e.target.value)}><option value="">전체</option><option>info</option><option>warn</option><option>error</option></Select>} /><Card pad={false}><LogTable rows={d.data} /></Card></>;
}

export function Backups() {
  const d = useLoad<any[]>(() => get("/admin/backups"));
  const a = useAction();
  return (
    <>
      <PageHead title="백업·복구" desc="전체 데이터베이스를 파일로 내보냅니다. 업로드 파일(APK·스크린샷·보고서)은 Railway 볼륨 백업으로 별도 보관해 주세요" action={<Button variant="primary" disabled={a.busy} onClick={() => a.run(() => post("/admin/backups"), "백업을 만들었습니다").then(d.reload)}>지금 백업</Button>} />
      <div className="mb-4"><Msg a={a} /></div>
      <Card pad={false}><Table rows={d.data} empty="백업 이력이 없습니다" cols={[{ key: "created_at", label: "시각", mono: true, render: (r) => dt(r.created_at) }, { key: "kind", label: "종류", render: (r) => ({ manual: "수동 백업", pre_restore: "복구 직전 자동 백업", restore: "복구 실행" } as any)[r.kind] || r.kind }, { key: "size", label: "크기", right: true, render: (r) => (r.size ? size(r.size) : "-") }, { key: "note", label: "비고" },
        { key: "_", label: "", right: true, render: (r) => r.path && <span className="flex justify-end gap-1"><Button size="sm" onClick={() => download(`/admin/backups/${r.id}/download`, r.path.split("/").pop())}>다운로드</Button>
          <Button size="sm" variant="danger" onClick={() => { if (prompt("이 백업 시점으로 전체 데이터를 되돌립니다. 이후 변경분은 사라집니다.\n진행하려면 RESTORE 를 입력하세요") === "RESTORE") a.run(() => post(`/admin/backups/${r.id}/restore`, { confirm: "RESTORE" }), "복구가 완료되었습니다. 다시 로그인해 주세요").then(d.reload); }}>복구</Button></span> }]} /></Card>
    </>
  );
}
