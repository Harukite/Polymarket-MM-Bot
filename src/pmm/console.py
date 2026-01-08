from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional
import threading

from rich.console import Console
from rich.console import Group
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.progress_bar import ProgressBar


@dataclass
class RecentRequest:
    name: str
    url: str
    ts: int


def _fmt_ts(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
    except Exception:
        return "-"


def _short_id(v: Any, *, head: int = 5, tail: int = 3) -> str:
    s = str(v or "")
    if len(s) <= head + tail + 1:
        return s or "-"
    return f"{s[:head]}…{s[-tail:]}"


def _status_text(status: Any) -> Text:
    s = str(status or "-").upper()
    style = {
        "PLACED": "bold green",
        "NEW": "green",
        "PARTIAL": "yellow",
        "FILLED": "bold cyan",
        "CANCELED": "dim",
        "CANCELLED": "dim",
        "REJECTED": "bold red",
        "ERROR": "bold red",
    }.get(s, "white")
    return Text(s, style=style)


def _side_text(side: Any) -> Text:
    s = str(side or "-").upper()
    style = "green" if s == "BUY" else ("red" if s == "SELL" else "white")
    return Text(s, style=style)


def _kpi_card(*, title: str, value: str, style: str, subtitle: str = "") -> Panel:
    body = Table.grid(padding=(0, 0))
    body.add_column()
    body.add_row(Text(title, style="dim"))
    body.add_row(Text(value, style=style))
    if subtitle:
        body.add_row(Text(subtitle, style="dim"))
    # padding 过大会导致在小终端高度下数值被裁剪，看起来“是空的”
    return Panel(body, box=box.ROUNDED, border_style=style, padding=(0, 1))


class RichDashboard:
    """
    一个轻量的实时控制台仪表盘（Rich Live）。
    目标：不改变策略逻辑，只优化可观测性（资金/订单/成交/风控/请求链接）。
    """

    def __init__(self, *, run_id: str, mode: str, dry_run: bool, console: Optional[Console] = None):
        self.run_id = run_id
        self.mode = mode
        self.dry_run = dry_run
        self.console = console or Console()
        self._live: Optional[Live] = None
        self._recent_requests: list[RecentRequest] = []
        self._started_ts = int(time.time())
        self._layout = self._build_layout()
        self._refresh_sec = float(
            __import__("os").getenv("PMM_DASHBOARD_REFRESH_SEC", "1.0")  # 节流：降低终端重绘抖动
        )
        self._lock = threading.Lock()
        self._last_payload: dict[str, Any] | None = None
        self._stop_evt = threading.Event()
        self._ticker: Optional[threading.Thread] = None

    def start(self) -> Live:
        if self._live is None:
            # 关键点：
            # - screen=True: 使用 alternate screen，避免滚屏/闪烁感
            # - auto_refresh=False: 不启用后台刷新线程，只在 update() 时刷新
            # - redirect_stdout/stderr=False: 避免捕获输出导致频繁重绘
            self._live = Live(
                self._render_empty(),
                console=self.console,
                screen=True,
                auto_refresh=False,
                refresh_per_second=2,
                transient=False,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start()
            # 后台定时刷新：解耦交易主循环（通常 3s）与仪表盘刷新（例如 1s）
            if self._refresh_sec > 0:
                self._stop_evt.clear()
                self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
                self._ticker.start()
        return self._live

    def stop(self) -> None:
        self._stop_evt.set()
        if self._ticker is not None and self._ticker.is_alive():
            try:
                self._ticker.join(timeout=1.0)
            except Exception:
                pass
        self._ticker = None
        if self._live is not None:
            self._live.stop()
            self._live = None

    def record_request(self, *, name: str, url: str) -> None:
        url = str(url)
        if not url:
            return
        self._recent_requests.append(RecentRequest(name=str(name), url=url, ts=int(time.time())))
        self._recent_requests = self._recent_requests[-6:]

    def update(
        self,
        *,
        loop_ts: int,
        universe_n: int,
        cash: float,
        equity: float,
        gross_exposure: float,
        realized: float,
        unrealized: float,
        cb_stats: dict[str, Any],
        recent_orders: list[dict[str, Any]],
        recent_trades: list[dict[str, Any]],
        recent_risk_events: list[dict[str, Any]],
    ) -> None:
        if self._live is None:
            return
        with self._lock:
            self._last_payload = {
                "loop_ts": loop_ts,
                "universe_n": universe_n,
                "cash": cash,
                "equity": equity,
                "gross_exposure": gross_exposure,
                "realized": realized,
                "unrealized": unrealized,
                "cb_stats": cb_stats,
                "recent_orders": recent_orders,
                "recent_trades": recent_trades,
                "recent_risk_events": recent_risk_events,
            }
        # 主循环触发一次立即刷新，保证数据一到就能看到
        self._render_from_last_payload()

    def _tick_loop(self) -> None:
        # 按 refresh_sec 定时刷新（即使数据没变化，也能稳定更新时间/uptime）
        while not self._stop_evt.is_set():
            try:
                self._render_from_last_payload()
            except Exception:
                pass
            self._stop_evt.wait(timeout=max(0.2, float(self._refresh_sec)))

    def _render_from_last_payload(self) -> None:
        if self._live is None:
            return
        with self._lock:
            p = dict(self._last_payload) if self._last_payload else None
        if not p:
            return
        self._update_layout(
            loop_ts=int(p["loop_ts"]),
            universe_n=int(p["universe_n"]),
            cash=float(p["cash"]),
            equity=float(p["equity"]),
            gross_exposure=float(p["gross_exposure"]),
            realized=float(p["realized"]),
            unrealized=float(p["unrealized"]),
            cb_stats=p["cb_stats"],
            recent_orders=p["recent_orders"],
            recent_trades=p["recent_trades"],
            recent_risk_events=p["recent_risk_events"],
        )
        self._live.update(self._layout, refresh=True)

    def _render_empty(self):
        title = f"PMM 控制台（run_id={self.run_id}）"
        return Panel(Text("启动中…", style="bold yellow"), title=title, border_style="cyan")

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            # 顶部包含：meta + KPI + bars，至少需要 11~13 行；否则会被裁剪导致 KPI 数值不显示
            Layout(name="top", size=13),
            Layout(name="bottom"),
        )
        layout["bottom"].split_row(
            Layout(name="left"),
            Layout(name="right"),
        )
        layout["left"].split_column(
            Layout(name="orders"),
            Layout(name="trades"),
        )
        layout["right"].split_column(
            Layout(name="risk", ratio=2),
            Layout(name="req", ratio=1),
        )
        # init placeholders to keep stable height (reduces layout jump)
        layout["top"].update(Panel(Text("启动中…", style="dim"), box=box.ROUNDED, border_style="bright_cyan"))
        layout["orders"].update(Panel(Text("加载中…", style="dim"), box=box.ROUNDED, border_style="blue"))
        layout["trades"].update(Panel(Text("加载中…", style="dim"), box=box.ROUNDED, border_style="blue"))
        layout["risk"].update(Panel(Text("加载中…", style="dim"), box=box.ROUNDED, border_style="bright_red"))
        layout["req"].update(Panel(Text("加载中…", style="dim"), box=box.ROUNDED, border_style="bright_cyan"))
        return layout

    def _update_layout(
        self,
        *,
        loop_ts: int,
        universe_n: int,
        cash: float,
        equity: float,
        gross_exposure: float,
        realized: float,
        unrealized: float,
        cb_stats: dict[str, Any],
        recent_orders: list[dict[str, Any]],
        recent_trades: list[dict[str, Any]],
        recent_risk_events: list[dict[str, Any]],
    ) -> None:

        # ===== Top summary (clean + human friendly) =====
        mode_txt = f"{self.mode.upper()}"
        if self.dry_run:
            mode_txt += "  ⏸️ DRY-RUN"
        uptime = int(time.time()) - self._started_ts
        uptime_txt = time.strftime("%H:%M:%S", time.gmtime(uptime))

        # KPI cards
        reject_rate = 0.0
        try:
            placed = float(cb_stats.get("placed", 0))
            rejected = float(cb_stats.get("rejected", 0))
            reject_rate = rejected / max(1.0, placed)
        except Exception:
            reject_rate = 0.0
        meta = Table.grid(expand=True)
        meta.add_column(justify="left", ratio=2)
        meta.add_column(justify="right", ratio=1)
        meta.add_row(
            Text(f"PMM 交易台  •  universe {universe_n}  •  {mode_txt}  •  uptime {uptime_txt}", style="bold bright_white"),
            Text(f"loop {_fmt_ts(loop_ts)}", style="dim"),
        )

        # 使用 Table.grid 固定 4 列，避免 Columns 自适应导致的重排抖动
        kpi_grid = Table.grid(expand=True)
        for _ in range(4):
            kpi_grid.add_column(ratio=1)
        kpi_grid.add_row(
            _kpi_card(title="现金 (Cash)", value=f"{cash:,.2f}", style="green"),
            _kpi_card(title="权益 (Equity)", value=f"{equity:,.2f}", style="green"),
            _kpi_card(title="敞口 (Gross)", value=f"{gross_exposure:,.2f}", style="yellow"),
            _kpi_card(title="盈亏 (已/未)", value=f"{realized:,.2f} / {unrealized:,.2f}", style="magenta"),
        )

        bars = Table.grid(expand=True)
        bars.add_column(ratio=1)
        bars.add_column(ratio=2)
        bars.add_column(ratio=1, justify="right")
        bars.add_row(
            Text("拒单率", style="dim"),
            ProgressBar(total=100, completed=min(100, int(reject_rate * 100)), width=24),
            Text(f"{reject_rate*100:.2f}%", style="bright_cyan"),
        )
        bars.add_row(
            Text("订单统计", style="dim"),
            Text(
                f"下单 {cb_stats.get('placed', 0)}  •  拒单 {cb_stats.get('rejected', 0)}  •  撤单/分 {cb_stats.get('cancels_1m', 0)}  •  错误 {cb_stats.get('errors', 0)}",
                style="bright_cyan",
            ),
            Text("", style="dim"),
        )

        header = Group(meta, kpi_grid, bars)
        self._layout["top"].update(
            Panel(
                header,
                title=f"运行 ID  {_short_id(self.run_id, head=8, tail=4)}",
                subtitle="退出：Ctrl+C   •   日志：./data/pmm.log（默认）   •   刷新：PMM_DASHBOARD_REFRESH_SEC（默认 1.0s）",
                border_style="bright_cyan",
                box=box.ROUNDED,
                padding=(1, 1),
            )
        )

        # Orders / Trades / Risk / Requests
        self._layout["orders"].update(Panel(self._orders_table(recent_orders), title="最近订单", border_style="blue", box=box.ROUNDED, padding=(0, 1)))
        self._layout["trades"].update(Panel(self._trades_table(recent_trades), title="最近成交", border_style="blue", box=box.ROUNDED, padding=(0, 1)))
        self._layout["risk"].update(Panel(self._risk_table(recent_risk_events), title="风控事件", border_style="bright_red", box=box.ROUNDED, padding=(0, 1)))
        self._layout["req"].update(Panel(self._req_table(), title="请求链接", border_style="bright_cyan", box=box.ROUNDED, padding=(0, 1)))

    def _orders_table(self, rows: list[dict[str, Any]]) -> Table:
        t = Table(show_header=True, header_style="bold bright_white", expand=True, box=box.MINIMAL, show_lines=False, pad_edge=False)
        t.row_styles = ["none", "dim"]
        t.add_column("time", width=8, no_wrap=True)
        t.add_column("token", width=10, overflow="ellipsis")
        t.add_column("side", width=4)
        t.add_column("price", width=8, justify="right")
        t.add_column("size", width=9, justify="right")
        t.add_column("status", width=10)
        view = rows[:12]
        if not view:
            view = [{}] * 12
        for r in view:
            t.add_row(
                _fmt_ts(r.get("updated_ts") or r.get("created_ts")) if r else "-",
                _short_id(r.get("token_id"), head=5, tail=3) if r else "-",
                _side_text(r.get("side")) if r else Text("-", style="dim"),
                f"{float(r.get('price') or 0):.4f}" if r else "-",
                f"{float(r.get('size') or 0):.2f}" if r else "-",
                _status_text(r.get("status")) if r else Text("—", style="dim"),
            )
        return t

    def _trades_table(self, rows: list[dict[str, Any]]) -> Table:
        t = Table(show_header=True, header_style="bold bright_white", expand=True, box=box.MINIMAL, show_lines=False, pad_edge=False)
        t.row_styles = ["none", "dim"]
        t.add_column("time", width=8, no_wrap=True)
        t.add_column("token", width=10, overflow="ellipsis")
        t.add_column("side", width=4)
        t.add_column("price", width=8, justify="right")
        t.add_column("size", width=9, justify="right")
        t.add_column("status", width=10)
        view = rows[:12]
        if not view:
            view = [{}] * 12
        for r in view:
            t.add_row(
                _fmt_ts(r.get("ts")) if r else "-",
                _short_id(r.get("token_id"), head=5, tail=3) if r else "-",
                _side_text(r.get("side")) if r else Text("-", style="dim"),
                f"{float(r.get('price') or 0):.4f}" if r else "-",
                f"{float(r.get('size') or 0):.2f}" if r else "-",
                _status_text(r.get("status")) if r else Text("—", style="dim"),
            )
        return t

    def _risk_table(self, rows: list[dict[str, Any]]) -> Table:
        t = Table(show_header=True, header_style="bold bright_white", expand=True, box=box.MINIMAL, show_lines=False, pad_edge=False)
        t.row_styles = ["none", "dim"]
        t.add_column("time", width=8, no_wrap=True)
        t.add_column("lvl", width=5)
        t.add_column("code", width=14, overflow="ellipsis")
        t.add_column("message", overflow="ellipsis")
        view = rows[:12]
        if not view:
            view = [{}] * 12
        for r in view:
            lvl = str(r.get("level") or "")
            style = "red" if lvl == "ERROR" else ("yellow" if lvl == "WARN" else "green")
            t.add_row(
                _fmt_ts(r.get("ts")) if r else "-",
                Text(lvl or "-", style=style) if r else Text("-", style="dim"),
                str(r.get("code") or "-") if r else "-",
                str(r.get("message") or "-") if r else Text("—", style="dim"),
            )
        return t

    def _req_table(self) -> Table:
        t = Table(show_header=True, header_style="bold bright_white", expand=True, box=box.MINIMAL, show_lines=False, pad_edge=False)
        t.row_styles = ["none", "dim"]
        t.add_column("time", width=8, no_wrap=True)
        t.add_column("name", width=12, overflow="ellipsis")
        t.add_column("url", overflow="ellipsis")
        reqs = list(reversed(self._recent_requests))[:6]
        if not reqs:
            reqs = [None] * 6
        for rr in reqs:
            if rr is None:
                t.add_row("-", "-", Text("—", style="dim"))
            else:
                t.add_row(_fmt_ts(rr.ts), rr.name, rr.url)
        return t

