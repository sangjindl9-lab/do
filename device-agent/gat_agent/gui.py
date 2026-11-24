"""PC 관리 창(PySide6). 창을 닫아도 시스템 트레이에서 계속 동작한다."""
import shutil
import subprocess
import threading
import webbrowser

from . import __version__
from .config import Config

RELEASES = "https://github.com/sangjindl9-lab/do/releases/latest"


def run_gui(cfg: Config) -> int:
    try:
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
        from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                       QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon, QTableWidget,
                                       QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
    except ImportError:
        print("GUI를 사용하려면 PySide6가 필요합니다. 'gat-agent run'으로 백그라운드 실행은 가능합니다.")
        return 2
    from .api import ApiError, NetworkError
    from .core import Agent, enroll, make_provider, rotate_token

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    pix = QPixmap(64, 64)
    pix.fill(QColor("#171717"))
    painter = QPainter(pix)
    painter.fillRect(14, 14, 10, 16, QColor("#ededed")); painter.fillRect(27, 14, 10, 16, QColor("#ededed")); painter.fillRect(40, 14, 10, 16, QColor("#2dd4bf"))
    painter.fillRect(14, 34, 10, 16, QColor("#ededed")); painter.fillRect(27, 34, 10, 16, QColor("#ededed")); painter.fillRect(40, 34, 10, 16, QColor("#ededed"))
    painter.end()
    icon = QIcon(pix)
    state: dict = {"agent": None, "thread": None}

    def table(headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return t

    def fill(t, rows):
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                t.setItem(r, c, QTableWidgetItem(str(value)))

    win = QMainWindow()
    win.setWindowTitle(f"Google Auto Tester Agent {__version__}")
    win.setWindowIcon(icon)
    win.resize(980, 640)
    tabs = QTabWidget()
    win.setCentralWidget(tabs)

    # --- 서버 연결 / 인증 ---
    conn = QWidget(); form = QFormLayout(conn)
    server = QLineEdit(cfg.server_url); server.setPlaceholderText("https://")
    code = QLineEdit(); code.setPlaceholderText("관리자 페이지 > PC 에이전트에서 발급한 등록 코드")
    status = QLabel(); agent_id = QLabel(cfg.agent_id or "-"); expires = QLabel(cfg.token_expires_at or "-")
    btn_enroll, btn_rotate, btn_start, btn_stop = QPushButton("에이전트 인증(등록)"), QPushButton("인증키 갱신"), QPushButton("시작"), QPushButton("중지")
    row = QHBoxLayout()
    for b in (btn_enroll, btn_rotate, btn_start, btn_stop):
        row.addWidget(b)
    form.addRow("서버 주소", server); form.addRow("등록 코드", code); form.addRow("에이전트 ID", agent_id)
    form.addRow("인증키 만료", expires); form.addRow("연결 상태", status); form.addRow(row)
    tabs.addTab(conn, "서버 연결·인증")

    # --- 기기 ---
    dev_tab = QWidget(); dl = QVBoxLayout(dev_tab)
    devices = table(["Serial", "ADB 상태", "제조사", "모델", "Android", "배터리", "온도", "여유 공간(MB)", "해상도"])
    btn_scan, btn_mirror = QPushButton("기기 검색"), QPushButton("선택 기기 화면 보기(scrcpy)")
    r2 = QHBoxLayout(); r2.addWidget(btn_scan); r2.addWidget(btn_mirror); r2.addStretch()
    dl.addLayout(r2); dl.addWidget(devices)
    tabs.addTab(dev_tab, "연결 기기")

    jobs = table(["작업", "Serial", "패키지", "진행률"]); tabs.addTab(jobs, "검사 진행 현황")
    history = table(["시각", "작업", "Serial", "패키지", "결과", "비고"]); tabs.addTab(history, "검사 작업 목록")
    errors = table(["시각", "내용"]); tabs.addTab(errors, "오류 기록")

    # --- 환경 설정 / 업데이트 ---
    opt = QWidget(); of = QFormLayout(opt)
    provider = QComboBox(); provider.addItems(["adb", "mock"]); provider.setCurrentText(cfg.provider)
    adb_path = QLineEdit(cfg.adb_path); adb_path.setPlaceholderText("비워 두면 PATH의 adb 사용")
    parallel = QSpinBox(); parallel.setRange(1, 200); parallel.setValue(cfg.max_parallel)
    appium = QLineEdit(cfg.appium_url); appium.setPlaceholderText("선택: http://127.0.0.1:4723")
    auto_update = QCheckBox("새 버전이 있으면 알림"); auto_update.setChecked(cfg.auto_update)
    spool = QLabel("-"); version = QLabel(__version__)
    btn_save, btn_update = QPushButton("저장"), QPushButton("다운로드 페이지 열기")
    of.addRow("기기 제어 방식", provider); of.addRow("adb 경로", adb_path); of.addRow("동시 검사 기기 수", parallel)
    of.addRow("Appium 서버", appium); of.addRow("", auto_update); of.addRow("전송 대기(로컬 보관) 건수", spool)
    of.addRow("현재 / 최신 버전", version); of.addRow(btn_save, btn_update); of.addRow("설정·로그 폴더", QLabel(cfg.home))
    tabs.addTab(opt, "환경 설정·업데이트")

    def start():
        if state["agent"] or not cfg.token:
            return
        try:
            state["agent"] = Agent(cfg)
        except ValueError as exc:
            QMessageBox.warning(win, "오류", str(exc))
            return
        state["thread"] = threading.Thread(target=state["agent"].run_forever, daemon=True)
        state["thread"].start()

    def stop():
        if state["agent"]:
            state["agent"].stop()
            state["agent"] = None

    def do_enroll():
        try:
            data = enroll(cfg, server.text().strip(), code.text().strip())
        except (ApiError, NetworkError, ValueError) as exc:
            QMessageBox.warning(win, "인증 실패", str(exc))
            return
        code.clear(); agent_id.setText(data["agent_id"]); expires.setText(str(data["expires_at"])); provider.setCurrentText(cfg.provider)
        stop(); start()

    def do_rotate():
        try:
            rotate_token(cfg)
            expires.setText(cfg.token_expires_at)
            stop(); start()
        except (ApiError, NetworkError) as exc:
            QMessageBox.warning(win, "갱신 실패", str(exc))

    def do_save():
        cfg.provider, cfg.adb_path, cfg.max_parallel = provider.currentText(), adb_path.text().strip(), parallel.value()
        cfg.appium_url, cfg.auto_update = appium.text().strip(), auto_update.isChecked()
        cfg.save()
        stop(); start()

    def do_scan():
        try:
            p = state["agent"].provider if state["agent"] else make_provider(cfg)
            rows = []
            for serial, st in p.list_serials().items():
                d = p.describe(serial, []).to_dict() if st == "device" else {"serial": serial, "state": st}
                rows.append([d.get("serial"), d.get("state"), d.get("manufacturer", ""), d.get("model", ""), d.get("android_version", ""),
                             d.get("battery", ""), d.get("temperature", ""), d.get("storage_free_mb", ""), d.get("resolution", "")])
            fill(devices, rows)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(win, "기기 검색 실패", str(exc))

    def do_mirror():
        row_i = devices.currentRow()
        exe = shutil.which("scrcpy")
        if row_i < 0 or not exe:
            QMessageBox.information(win, "화면 보기", "기기를 선택해 주세요." if exe else "scrcpy가 설치되어 있지 않습니다. scrcpy를 설치하고 PATH에 추가해 주세요.")
            return
        subprocess.Popen([exe, "-s", devices.item(row_i, 0).text(), "--no-audio"])

    def refresh():
        agent = state["agent"]
        if not cfg.token:
            status.setText("미등록: 등록 코드로 인증해 주세요")
        elif not agent:
            status.setText("중지됨")
        else:
            status.setText("서버 연결됨" if agent.connected else "연결 끊김 (자동 재연결 중)")
            fill(devices, [[d.get("serial"), d.get("state"), d.get("manufacturer", ""), d.get("model", ""), d.get("android_version", ""), d.get("battery", ""),
                            d.get("temperature", ""), d.get("storage_free_mb", ""), d.get("resolution", "")] for d in agent.devices])
            fill(jobs, [[jid, j["serial"], j["package"], f"{j['progress']}%"] for jid, j in list(agent.running.items())])
            fill(history, [[h["at"], h["job_id"], h["serial"], h["package"], h["status"], h["note"]] for h in reversed(agent.history[-200:])])
            fill(errors, [[e["at"], e["message"]] for e in reversed(agent.errors[-200:])])
            spool.setText(str(len(agent.spool.items())))
            latest = agent.latest_version or "-"
            version.setText(f"{__version__} / {latest}" + ("  (새 버전 있음)" if latest not in ("-", __version__) else ""))
        tray.setToolTip(f"Google Auto Tester Agent - {status.text()}")

    btn_enroll.clicked.connect(do_enroll); btn_rotate.clicked.connect(do_rotate); btn_start.clicked.connect(start); btn_stop.clicked.connect(stop)
    btn_save.clicked.connect(do_save); btn_scan.clicked.connect(do_scan); btn_mirror.clicked.connect(do_mirror)
    btn_update.clicked.connect(lambda: webbrowser.open(RELEASES))

    tray = QSystemTrayIcon(icon)
    menu = QMenu()
    for label, fn in (("창 열기", win.showNormal), ("시작", start), ("중지", stop), ("재시작", lambda: (stop(), start()))):
        act = QAction(label, menu); act.triggered.connect(fn); menu.addAction(act)
    menu.addSeparator()
    quit_act = QAction("프로그램 종료", menu)
    quit_act.triggered.connect(lambda: (stop(), tray.hide(), app.quit()))
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: win.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    win.closeEvent = lambda event: (event.ignore(), win.hide())  # 닫기 = 트레이로 최소화
    timer = QTimer(); timer.timeout.connect(refresh); timer.start(1500)
    start(); refresh(); win.show()
    return app.exec()
