"""PDF / Excel 보고서 생성. 모든 수치는 DB의 실제 검사 기록에서 집계한다."""
import io
import os
import secrets
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (App, AppVersion, CrashLog, Customer, Device, PerformanceMetric, Report, Screenshot, TestPlan,
                      TestResult)
from . import storage

KINDS = {
    "comprehensive": "앱 검사 종합보고서", "daily": "일별 검사보고서", "device": "기기별 검사보고서",
    "version": "앱 버전별 비교보고서", "crash": "크래시 및 오류 분석보고서", "performance": "성능 측정보고서",
    "screenshot": "스크린샷 보고서", "completion": "테스트 완료보고서",
}
SECTIONS = {
    "comprehensive": ["summary", "daily", "device", "crash", "performance", "advice"],
    "daily": ["summary", "daily"], "device": ["summary", "device"], "version": ["summary", "version"],
    "crash": ["summary", "crash", "advice"], "performance": ["summary", "performance"],
    "screenshot": ["summary", "screenshot"],
    "completion": ["summary", "daily", "device", "version", "crash", "performance", "screenshot", "advice"],
}
METRIC_NAMES = {"cold_start_ms": "앱 실행 시간", "cpu_percent": "CPU 사용량", "memory_mb": "RAM 사용량",
                "storage_mb": "저장공간 사용량", "temperature_c": "기기 온도", "response_ms": "화면 응답 시간",
                "install_ms": "설치 시간"}
NOTICE = ("본 보고서는 독립적인 제3자 품질검사 서비스의 실기기 자동화 검사 결과이며 Google의 공식 문서가 아닙니다. "
          "자동화 검사 기록은 Google Play 비공개 테스트의 인간 테스터 참여 기록이 아니며, 프로덕션 승인을 보장하지 않습니다.")
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
_fonts_ready = False


def _fonts():
    global _fonts_ready
    if not _fonts_ready:
        pdfmetrics.registerFont(TTFont("Nanum", os.path.join(FONT_DIR, "NanumGothic-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("NanumB", os.path.join(FONT_DIR, "NanumGothic-Bold.ttf")))
        _fonts_ready = True


def collect(db: Session, plan: TestPlan) -> dict:
    customer = db.get(Customer, plan.customer_id)
    app: App = plan.app
    results = db.scalars(select(TestResult).where(TestResult.plan_id == plan.id).order_by(TestResult.id)).all()
    devices = {d.id: d for d in db.scalars(select(Device).where(Device.id.in_({r.device_id for r in results} or {0})))}
    daily, per_device = defaultdict(Counter), defaultdict(Counter)
    failed_steps = Counter()
    for r in results:
        day = (r.finished_at or r.created_at).strftime("%Y-%m-%d")
        daily[day][r.status] += 1
        per_device[r.device_id][r.status] += 1
        per_device[r.device_id]["crash"] += r.crash_count
        per_device[r.device_id]["anr"] += r.anr_count
        for s in r.steps or []:
            if s.get("status") == "failed":
                failed_steps[s.get("name") or s.get("key")] += 1
    crashes = db.scalars(select(CrashLog).where(CrashLog.plan_id == plan.id).order_by(CrashLog.id)).all()
    groups: dict[str, dict] = {}
    for c in crashes:
        g = groups.setdefault(c.signature, {"kind": c.kind, "title": c.title, "severity": c.severity,
                                            "category": c.category, "count": 0, "devices": set(), "detail": c.detail,
                                            "advice": ((c.analysis or {}).get("rule") or {}).get("advice", ""),
                                            "ai": (c.analysis or {}).get("ai")})
        g["count"] += 1
        g["devices"].add(c.device_id)
    metrics = defaultdict(list)
    for m in db.scalars(select(PerformanceMetric).where(PerformanceMetric.plan_id == plan.id)):
        metrics[(m.metric, m.unit)].append(m.value)
    perf = [{"metric": k[0], "name": METRIC_NAMES.get(k[0], k[0]), "unit": k[1], "count": len(v),
             "avg": sum(v) / len(v), "min": min(v), "max": max(v)} for k, v in sorted(metrics.items())]
    # 버전별 비교: 같은 앱의 모든 검사 계획 결과
    versions = []
    vrows = db.execute(select(TestResult.app_version_id, TestResult.status, TestResult.crash_count, TestResult.anr_count)
                       .join(TestPlan, TestPlan.id == TestResult.plan_id)
                       .where(TestPlan.app_id == app.id, TestResult.is_mock == plan.is_mock)).all()
    vagg = defaultdict(Counter)
    for vid, status, cc, ac in vrows:
        vagg[vid][status] += 1
        vagg[vid]["crash"] += cc
        vagg[vid]["anr"] += ac
    for vid, cnt in sorted(vagg.items()):
        v = db.get(AppVersion, vid)
        versions.append({"version": f"{v.version_name} ({v.version_code})", **{k: cnt[k] for k in ("passed", "failed", "error", "crash", "anr")}})
    shots = db.scalars(select(Screenshot).where(Screenshot.plan_id == plan.id).order_by(Screenshot.id)).all()
    advice = []
    for g in groups.values():
        if g["advice"] and g["advice"] not in advice:
            advice.append(g["advice"])
    for name, n in failed_steps.most_common(5):
        advice.append(f"'{name}' 단계가 {n}회 실패했습니다. 해당 기능의 기기별 동작을 확인하세요.")
    total = Counter(r.status for r in results)
    return {
        "customer": customer.company or customer.user.name or customer.user.email, "app": app.name,
        "package": app.package_name, "version": f"{plan.app_version.version_name} ({plan.app_version.version_code})",
        "period": f"{plan.start_at:%Y-%m-%d} ~ {plan.end_at:%Y-%m-%d}", "order_no": plan.order.order_no,
        "is_mock": plan.is_mock, "total": len(results), "passed": total["passed"], "failed": total["failed"],
        "error": total["error"], "crash": sum(r.crash_count for r in results), "anr": sum(r.anr_count for r in results),
        "devices": [{"name": d.name or d.serial, "model": f"{d.manufacturer} {d.model}".strip(),
                     "android": d.android_version, **{k: per_device[d.id][k] for k in ("passed", "failed", "error", "crash", "anr")}}
                    for d in devices.values()],
        "daily": [{"day": day, **{k: c[k] for k in ("passed", "failed", "error")}} for day, c in sorted(daily.items())],
        "crashes": sorted(groups.values(), key=lambda g: -g["count"]), "perf": perf, "versions": versions,
        "screenshots": shots, "advice": advice, "failed_steps": failed_steps.most_common(10),
        "android_versions": sorted({d.android_version for d in devices.values() if d.android_version}),
    }


def _pdf(data: dict, kind: str, report_no: str) -> bytes:
    _fonts()
    h1 = ParagraphStyle("h1", fontName="NanumB", fontSize=18, leading=24, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName="NanumB", fontSize=12, leading=16, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("body", fontName="Nanum", fontSize=9, leading=13)
    small = ParagraphStyle("small", fontName="Nanum", fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))
    warn = ParagraphStyle("warn", fontName="NanumB", fontSize=10, leading=14, textColor=colors.HexColor("#b42318"))

    def table(rows, widths=None):
        t = Table([[Paragraph(str(c), body) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9ced6")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    story = [Paragraph(KINDS[kind], h1), Paragraph(f"보고서 고유번호 {report_no} · 발행일 {utcnow():%Y-%m-%d}", small), Spacer(1, 6)]
    if data["is_mock"]:
        story.append(Paragraph("※ 모의(MOCK) 장비·모의 결제 환경의 시험 결과입니다. 실제 기기 검사 결과가 아닙니다.", warn))
    sections = SECTIONS[kind]
    if "summary" in sections:
        rate = f"{data['passed'] / data['total'] * 100:.1f}%" if data["total"] else "-"
        story += [Paragraph("검사 개요", h2), table([
            ["항목", "내용"], ["고객명", esc(data["customer"])], ["앱 이름", esc(data["app"])], ["패키지명", esc(data["package"])],
            ["앱 버전", esc(data["version"])], ["검사 기간", data["period"]], ["주문번호", data["order_no"]],
            ["실제 검사 기기", f"{len(data['devices'])}대"], ["Android 버전", ", ".join(data["android_versions"]) or "-"],
            ["검사 횟수", f"{data['total']}회 (성공 {data['passed']} / 실패 {data['failed']} / 수행 불가 {data['error']})"],
            ["검사 성공률", rate], ["크래시 / ANR", f"{data['crash']}건 / {data['anr']}건"]], [40 * mm, 130 * mm])]
        if not data["total"]:
            story.append(Paragraph("기록된 검사 결과가 없습니다.", body))
    if "daily" in sections and data["daily"]:
        story += [Paragraph("일별 검사 결과", h2),
                  table([["일자", "성공", "실패", "수행 불가"]] + [[d["day"], d["passed"], d["failed"], d["error"]] for d in data["daily"]])]
    if "device" in sections and data["devices"]:
        story += [Paragraph("기기별 검사 결과", h2),
                  table([["기기", "모델", "Android", "성공", "실패", "수행 불가", "크래시", "ANR"]] +
                        [[esc(d["name"]), esc(d["model"]), d["android"], d["passed"], d["failed"], d["error"], d["crash"], d["anr"]]
                         for d in data["devices"]])]
    if "version" in sections and data["versions"]:
        story += [Paragraph("앱 버전별 비교", h2),
                  table([["버전", "성공", "실패", "수행 불가", "크래시", "ANR"]] +
                        [[esc(v["version"]), v["passed"], v["failed"], v["error"], v["crash"], v["anr"]] for v in data["versions"]])]
    if "crash" in sections:
        story.append(Paragraph("크래시 및 오류 내역", h2))
        if not data["crashes"]:
            story.append(Paragraph("검사 기간 중 수집된 크래시·ANR·오류 로그가 없습니다.", body))
        for g in data["crashes"][:30]:
            story.append(table([["종류", "분류(규칙 기반)", "심각도", "발생", "기기 수"],
                                [g["kind"], esc(g["category"]), g["severity"], f"{g['count']}회", len(g["devices"])]]))
            story.append(Paragraph(f"<b>{esc(g['title'])}</b><br/>{esc(g['detail'][:900]).replace(chr(10), '<br/>')}", small))
            if g.get("ai") and not g["ai"].get("error"):
                story.append(Paragraph(f"[AI 추정 · 미확인] {esc(g['ai'].get('cause', ''))} / 권고: {esc(g['ai'].get('advice', ''))}", small))
            story.append(Spacer(1, 6))
    if "performance" in sections and data["perf"]:
        story += [Paragraph("성능 측정", h2),
                  table([["항목", "측정 횟수", "평균", "최소", "최대", "단위"]] +
                        [[p["name"], p["count"], f"{p['avg']:.1f}", f"{p['min']:.1f}", f"{p['max']:.1f}", p["unit"]] for p in data["perf"]])]
    if "screenshot" in sections and data["screenshots"]:
        story += [PageBreak(), Paragraph("실제 스크린샷", h2)]
        cells = []
        for s in data["screenshots"][:24]:
            try:
                img = Image(storage.abspath(s.path))
                ratio = img.imageHeight / float(img.imageWidth or 1)
                img.drawWidth, img.drawHeight = 50 * mm, min(50 * mm * ratio, 95 * mm)
                cells.append([img, Paragraph(esc(s.label), small)])
            except Exception:  # noqa: BLE001 - 손상 이미지는 건너뛴다
                continue
        rows = [cells[i:i + 3] for i in range(0, len(cells), 3)]
        for r in rows:
            r += [""] * (3 - len(r))
            story.append(Table([r], colWidths=[57 * mm] * 3))
    if "advice" in sections:
        story.append(Paragraph("개선 권고사항", h2))
        if data["advice"]:
            story += [Paragraph(f"· {esc(a)}", body) for a in data["advice"]]
        else:
            story.append(Paragraph("수집된 오류가 없어 별도 권고사항이 없습니다.", body))
    story += [Spacer(1, 14), Paragraph(NOTICE, small)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                      title=f"{KINDS[kind]} {report_no}").build(story)
    return buf.getvalue()


def _xlsx(data: dict, kind: str, report_no: str) -> bytes:
    wb = Workbook()
    head_fill, bold = PatternFill("solid", fgColor="EEF1F5"), Font(bold=True)

    def sheet(title, rows, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font, c.fill = bold, head_fill
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width * 1.6))
            for c in col:
                c.alignment = Alignment(vertical="top", wrap_text=True)
        return ws

    sheet("개요", [["항목", "내용"], ["보고서", KINDS[kind]], ["보고서 고유번호", report_no], ["발행일", f"{utcnow():%Y-%m-%d}"],
                 ["구분", "모의(MOCK) 시험 결과 - 실제 기기 결과 아님" if data["is_mock"] else "실기기 검사 결과"],
                 ["고객명", data["customer"]], ["앱 이름", data["app"]], ["패키지명", data["package"]], ["앱 버전", data["version"]],
                 ["검사 기간", data["period"]], ["실제 검사 기기 수", len(data["devices"])],
                 ["Android 버전", ", ".join(data["android_versions"])], ["검사 횟수", data["total"]], ["성공", data["passed"]],
                 ["실패", data["failed"]], ["수행 불가", data["error"]], ["크래시", data["crash"]], ["ANR", data["anr"]],
                 ["안내", NOTICE]], first=True)
    sections = SECTIONS[kind]
    if "daily" in sections:
        sheet("일별", [["일자", "성공", "실패", "수행 불가"]] + [[d["day"], d["passed"], d["failed"], d["error"]] for d in data["daily"]])
    if "device" in sections:
        sheet("기기별", [["기기", "모델", "Android", "성공", "실패", "수행 불가", "크래시", "ANR"]] +
              [[d["name"], d["model"], d["android"], d["passed"], d["failed"], d["error"], d["crash"], d["anr"]] for d in data["devices"]])
    if "version" in sections:
        sheet("버전별", [["버전", "성공", "실패", "수행 불가", "크래시", "ANR"]] +
              [[v["version"], v["passed"], v["failed"], v["error"], v["crash"], v["anr"]] for v in data["versions"]])
    if "crash" in sections:
        sheet("오류", [["종류", "제목", "분류(규칙 기반)", "심각도", "발생 횟수", "기기 수", "권고", "AI 추정(미확인)", "로그"]] +
              [[g["kind"], g["title"], g["category"], g["severity"], g["count"], len(g["devices"]), g["advice"],
                (g.get("ai") or {}).get("cause", ""), g["detail"][:3000]] for g in data["crashes"]])
    if "performance" in sections:
        sheet("성능", [["항목", "측정 횟수", "평균", "최소", "최대", "단위"]] +
              [[p["name"], p["count"], round(p["avg"], 2), round(p["min"], 2), round(p["max"], 2), p["unit"]] for p in data["perf"]])
    if "screenshot" in sections:
        sheet("스크린샷", [["번호", "설명", "촬영 시각(UTC)"]] +
              [[s.id, s.label, f"{s.created_at:%Y-%m-%d %H:%M}"] for s in data["screenshots"]])
    if "advice" in sections:
        sheet("권고", [["개선 권고사항"]] + [[a] for a in data["advice"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_report(db: Session, plan: TestPlan, kind: str, fmt: str) -> Report:
    if kind not in KINDS or fmt not in ("pdf", "xlsx"):
        raise ValueError("지원하지 않는 보고서 형식입니다.")
    report_no = f"R{utcnow():%y%m%d}-{secrets.token_hex(4).upper()}"
    data = collect(db, plan)
    blob = _pdf(data, kind, report_no) if fmt == "pdf" else _xlsx(data, kind, report_no)
    rel, size, _ = storage.save_bytes(blob, "reports", "." + fmt)
    report = Report(report_no=report_no, plan_id=plan.id, customer_id=plan.customer_id, kind=kind, fmt=fmt,
                    path=rel, size=size, is_mock=plan.is_mock)
    db.add(report)
    db.flush()
    return report
