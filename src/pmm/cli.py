from __future__ import annotations
import argparse
import os
import uuid
import json
import time
import logging
import math

from dotenv import load_dotenv

from pmm.config import load_settings
from pmm.logging import setup_logging
from pmm.db.schema import connect, init_db
from pmm.db import repo
from pmm.market.gamma import GammaClient
from pmm.market.universe import fetch_top_liquidity_markets
from pmm.market.clob_public import ClobPublic
from pmm.execution.paper_exchange import PaperExchange
from pmm.execution.live_exchange import LiveExchange
from pmm.execution.live_user_stream import UserStream
from pmm.execution.order_manager import OrderManager
from pmm.strategy.risk import RiskLimits, RiskManager
from pmm.strategy.calibrator import Calibrator, MarketCalibParams
from pmm.strategy.mm_spread import SymmetricSpreadMM
from pmm.strategy.circuit_breaker import CircuitBreaker, CircuitConfig
from pmm.strategy.allocator import CapitalAllocator, MarketFeatures
from pmm.analytics.inventory import InventoryEngine, load_fills_from_trades
from pmm.analytics.pnl import snapshot_pnl
from pmm.console import RichDashboard

log = logging.getLogger("pmm")

def cmd_db_init(args):
    s = load_settings()
    setup_logging(s.log_level)
    os.makedirs(os.path.dirname(s.db_path) or ".", exist_ok=True)
    conn = connect(s.db_path)
    init_db(conn)
    log.info("DB initialized: %s", s.db_path)

def cmd_universe_refresh(args):
    s = load_settings()
    setup_logging(s.log_level)
    conn = connect(s.db_path)
    init_db(conn)
    gamma = GammaClient(s.gamma_host)
    rows = fetch_top_liquidity_markets(
        gamma,
        limit=s.universe_limit,
        order_field=s.universe_order_field,
        ascending=s.universe_ascending,
        only_active=s.only_active,
        only_open=s.only_open,
    )
    repo.upsert_markets(conn, rows)
    log.info("Universe refreshed: %s markets", len(rows))

def _parse_clob_token_ids(raw) -> tuple[str, str] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return str(raw[0]), str(raw[1])
    raw = str(raw).strip()
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list) and len(arr) >= 2:
                return str(arr[0]), str(arr[1])
        except Exception:
            pass
    parts = [p.strip().strip('"') for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None

def cmd_run(args):
    s = load_settings()
    # Rich dashboard (default on; disable with PMM_RICH=false)
    rich_enabled = os.getenv("PMM_RICH", "true").lower() == "true"
    # 仪表盘开启时，默认不把日志刷到控制台（避免 Live 重绘闪烁）；日志写到 ./data/pmm.log
    if rich_enabled:
        os.environ.setdefault("PMM_CONSOLE_LOGS", "false")
        os.environ.setdefault("PMM_RICH_LOGS", "false")

    setup_logging(s.log_level)
    conn = connect(s.db_path)
    init_db(conn)

    run_id = args.run_id or str(uuid.uuid4())
    repo.insert_run(conn, run_id, s.mode, s.model_dump())

    dashboard = RichDashboard(run_id=run_id, mode=args.mode, dry_run=bool(getattr(args, "dry_run", False))) if rich_enabled else None

    def _refresh_universe_in_process() -> None:
        gamma = GammaClient(s.gamma_host)
        rows = fetch_top_liquidity_markets(
            gamma,
            limit=s.universe_limit,
            order_field=s.universe_order_field,
            ascending=s.universe_ascending,
            only_active=s.only_active,
            only_open=s.only_open,
        )
        repo.upsert_markets(conn, rows)
        if dashboard and gamma.last_url:
            dashboard.record_request(name="Gamma /markets", url=gamma.last_url)
        log.info("Universe refreshed: %s markets", len(rows))

    log.info("Refreshing universe data...")
    try:
        _refresh_universe_in_process()
    except Exception as e:
        log.warning("Universe refresh failed; continuing with existing DB universe. err=%s", e)

    markets = repo.list_universe(conn, s.universe_limit)
    if not markets:
        raise SystemExit("Universe empty. Run: pmm universe refresh")

    dry_run = bool(getattr(args, "dry_run", False))

    # Execution mode
    if args.mode == "paper":
        exchange = PaperExchange()
    elif args.mode == "live":
        exchange = LiveExchange(s) if not dry_run else PaperExchange()
    else:
        raise SystemExit("Unknown mode")

    # CLOB public feed
    clob_pub = ClobPublic(host=s.clob_host, chain_id=s.chain_id)

    # Circuit breaker
    is_paper = bool(getattr(exchange, "is_paper", False))
    cb = CircuitBreaker(CircuitConfig.from_env(is_paper=is_paper))

    # User tape (live)
    if args.mode == "live" and s.enable_wss_user and (not dry_run):
        if not (s.api_key and s.api_secret and s.api_passphrase):
            log.warning("User WSS tape requires PMM_API_KEY/SECRET/PASSPHRASE. Skipping user stream.")
            repo.insert_risk_event(conn, run_id, int(time.time()), "WARN", "WSS_USER_DISABLED", "Missing L2 creds; skipping user tape", {})
        else:
            condition_ids = [m["condition_id"] for m in markets]
            UserStream(
                run_id=run_id,
                db_path=s.db_path,
                wss_base=s.wss_base,
                api_key=s.api_key,
                api_secret=s.api_secret,
                api_passphrase=s.api_passphrase,
                markets=condition_ids,
                ping_sec=s.wss_ping_sec,
            ).start()
            repo.insert_risk_event(conn, run_id, int(time.time()), "INFO", "WSS_USER_STARTED", "User tape started", {"markets": len(condition_ids)})

    # Strategy & calibration
    risk = RiskManager(RiskLimits(alpha=s.alpha, max_usd_per_market=s.max_usd_per_market, max_gross_usd=s.max_gross_usd))
    calibrator = Calibrator(s.alpha, s.target_spread_bps, s.max_usd_per_market, s.quote_refresh_sec, s.cancel_reprice_sec)

    # Capital allocator
    allocator = CapitalAllocator(
        total_budget_usd=min(s.max_gross_usd, s.starting_cash),
        min_per_market=s.min_usd_per_market,
        max_per_market=s.max_usd_per_market,
        liquidity_power=s.alloc_liquidity_power,
        quality_k=s.alloc_quality_k,
    )

    # Persistent order managers per token
    oms: dict[str, OrderManager] = {}
    tick_fallback = 0.001

    # Inventory/PnL
    inv = InventoryEngine(starting_cash=s.starting_cash)
    last_fill_ts = 0

    log.info("Run started: %s (%s) dry_run=%s", run_id, args.mode, dry_run)

    def _rows_to_dicts(cur) -> list[dict]:
        return [dict(r) for r in cur.fetchall()]

    if dashboard:
        dashboard.start()
    try:
        while True:
            loop_ts = int(time.time())
            midpoint_by_token: dict[str, float] = {}
            depth_samples: list[float] = []

            def _quantile(vals: list[float], q: float) -> float:
                if not vals:
                    return 0.0
                q = max(0.0, min(1.0, float(q)))
                xs = sorted(float(v) for v in vals if v is not None and float(v) >= 0.0)
                if not xs:
                    return 0.0
                if len(xs) == 1:
                    return xs[0]
                pos = (len(xs) - 1) * q
                lo = int(math.floor(pos))
                hi = int(math.ceil(pos))
                if lo == hi:
                    return xs[lo]
                w = pos - lo
                return xs[lo] * (1.0 - w) + xs[hi] * w

            # depth_ref 自动估计（用于下一轮），本轮使用冻结值，避免同一轮内强度跳动
            depth_ref_mode = os.getenv("PMM_PAPER_DEPTH_REF_MODE", "quantile").lower()  # quantile|static
            depth_ref_q = float(os.getenv("PMM_PAPER_DEPTH_REF_QUANTILE", "0.70"))
            depth_ref_static = float(os.getenv("PMM_PAPER_DEPTH_REF", "2000"))
            depth_ref_min = float(os.getenv("PMM_PAPER_DEPTH_REF_MIN", "200"))
            depth_ref_max = float(os.getenv("PMM_PAPER_DEPTH_REF_MAX", "50000"))
            depth_ref_ema = float(os.getenv("PMM_PAPER_DEPTH_REF_EMA", "0.80"))  # 0~1, 越大越平滑
            if not hasattr(cmd_run, "_paper_depth_ref"):
                setattr(cmd_run, "_paper_depth_ref", depth_ref_static)
            loop_depth_ref = float(getattr(cmd_run, "_paper_depth_ref"))

            def _parse_book(book: dict | None, *, top_levels: int) -> tuple[float | None, float | None, float]:
                """
                解析 orderbook，返回 best_bid/best_ask 与 top 深度（前 N 档 bids+asks size 之和）。
                兼容 list[dict] 或 list[list/tuple] 两种常见结构。
                """
                if not book:
                    return None, None, 0.0
                bids = book.get("bids") or []
                asks = book.get("asks") or []
                def _p(x):
                    return float(x["price"]) if isinstance(x, dict) and "price" in x else float(x[0])
                def _s(x):
                    if isinstance(x, dict):
                        v = x.get("size") or x.get("amount") or x.get("quantity")
                        return float(v) if v is not None else 0.0
                    return float(x[1]) if len(x) > 1 else 0.0
                best_bid = _p(bids[0]) if bids else None
                best_ask = _p(asks[0]) if asks else None
                n = max(1, int(top_levels))
                depth = sum(_s(x) for x in bids[:n]) + sum(_s(x) for x in asks[:n])
                return best_bid, best_ask, float(depth)

            def _paper_intensity(depth_top: float, tick: float, best_bid: float | None, best_ask: float | None) -> float | None:
                """
                paper/dry-run 成交强度自适应：根据 top depth 调整强度；
                spread 的惩罚策略由 PMM_PAPER_SPREAD_MODE 控制：
                - factor：在 simulate_fills 内部惩罚
                - intensity：在这里把 spread 惩罚并入 intensity（避免双重惩罚）
                """
                if not getattr(exchange, "is_paper", False):
                    return None
                if os.getenv("PMM_PAPER_INTENSITY_ADAPT", "true").lower() != "true":
                    return None
                base = float(os.getenv("PMM_PAPER_FILL_INTENSITY", "0.003"))
                # 使用“冻结”的 depth_ref，避免同一轮内强度波动
                depth_ref = loop_depth_ref if depth_ref_mode != "static" else float(depth_ref_static)
                # depth_factor = sqrt(depth/depth_ref) 并做夹逼，避免极端值
                factor = math.sqrt(max(0.0, depth_top) / max(1.0, depth_ref)) if depth_ref > 0 else 1.0
                factor = max(0.25, min(3.0, factor))
                v = base * factor

                # spread penalty moved into intensity when enabled
                spread_mode = os.getenv("PMM_PAPER_SPREAD_MODE", "intensity").lower()
                if spread_mode == "intensity" and best_bid is not None and best_ask is not None:
                    spread_ticks = max(0.0, (float(best_ask) - float(best_bid)) / max(1e-9, float(tick)))
                    k = float(os.getenv("PMM_PAPER_SPREAD_K", "0.6"))
                    spread_factor = 1.0 / (1.0 + k * max(0.0, spread_ticks - 1.0))
                    v *= spread_factor

                v_min = float(os.getenv("PMM_PAPER_INTENSITY_MIN", "0.0005"))
                v_max = float(os.getenv("PMM_PAPER_INTENSITY_MAX", "0.05"))
                return max(v_min, min(v_max, v))

            # === Update inventory from fills ===
            fills = load_fills_from_trades(conn, run_id, last_fill_ts)
            for f in fills:
                inv.apply_fill(f["token_id"], f["side"], f["price"], f["size"], fee=f.get("fee", 0.0))
                last_fill_ts = max(last_fill_ts, int(f["ts"]))

            # === Build market features and allocate capital ===
            feats = []
            for m in markets:
                condition_id = m["condition_id"]
                row = repo.get_calibration(conn, condition_id)
                if row and row["state_json"]:
                    st = json.loads(row["state_json"])
                    fills_n = int(st.get("fills", 0))
                    quotes_n = int(st.get("quotes", 0))
                    markout_sum = float(st.get("markout_sum", 0.0))
                    realized_spread_sum = float(st.get("realized_spread_sum", 0.0))
                else:
                    fills_n = 0
                    quotes_n = 0
                    markout_sum = 0.0
                    realized_spread_sum = 0.0
                feats.append(MarketFeatures(
                    condition_id=condition_id,
                    liquidity_num=float(m["liquidity_num"] or 0.0),
                    fills=fills_n,
                    quotes=quotes_n,
                    markout_sum=markout_sum,
                    realized_spread_sum=realized_spread_sum,
                ))

            alloc_map = allocator.allocate(feats) if s.enable_allocator else {f.condition_id: s.max_usd_per_market for f in feats}

            # === Market loop ===
            for m in markets:
                condition_id = m["condition_id"]
                tok = _parse_clob_token_ids(m["clob_token_ids"])
                if not tok:
                    continue
                token_yes, token_no = tok

                # Midpoints
                mid_yes = clob_pub.get_midpoint(token_yes) or 0.5
                mid_no = clob_pub.get_midpoint(token_no) or (1.0 - mid_yes)
                midpoint_by_token[token_yes] = float(mid_yes)
                midpoint_by_token[token_no] = float(mid_no)

                # Load calib row or init (shared per condition)
                row = repo.get_calibration(conn, condition_id)
                if row:
                    state = json.loads(row["state_json"] or "{}")
                    st = calibrator.from_state_json(state)
                    params = MarketCalibParams(
                        alpha=float(row["alpha"]),
                        target_spread_bps=float(row["target_spread_bps"]),
                        max_usd=float(row["max_usd"]),
                        quote_refresh_sec=float(row["quote_refresh_sec"]),
                        cancel_reprice_sec=float(row["cancel_reprice_sec"]),
                        state=st,
                    )
                else:
                    params = calibrator.init_params()

                # Apply allocator budget for this market
                params.max_usd = float(alloc_map.get(condition_id, params.max_usd))

                # Adaptive update (spread/refresh)
                params = calibrator.next_params(params)

                # Exposure gate (global)
                gross_exposure = 0.0
                for tid, p in inv.pos.items():
                    mid = midpoint_by_token.get(tid)
                    if mid is not None:
                        gross_exposure += abs(p.qty) * float(mid)
                if gross_exposure >= s.max_gross_usd:
                    repo.insert_risk_event(conn, run_id, loop_ts, "WARN", "MAX_GROSS_EXPOSURE", "Gross exposure cap reached; skipping new quotes",
                                           {"gross_exposure": gross_exposure, "cap": s.max_gross_usd})
                    continue

                top_levels = int(os.getenv("PMM_PAPER_DEPTH_LEVELS", "3"))

                # 同时对 YES/NO 两个 token 报价 + 模拟成交（更贴近二元市场）
                for token_id, mid in ((token_yes, mid_yes), (token_no, mid_no)):
                    book = clob_pub.get_orderbook(token_id)
                    best_bid, best_ask, depth_top = _parse_book(book, top_levels=top_levels)
                    if depth_top and depth_top > 0:
                        depth_samples.append(float(depth_top))
                    if book:
                        try:
                            bids = book.get("bids") or []
                            asks = book.get("asks") or []
                            midpoint = (best_bid + best_ask)/2 if (best_bid is not None and best_ask is not None) else float(mid)
                            repo.insert_orderbook(conn, run_id, token_id, loop_ts, best_bid, best_ask, midpoint, bids, asks)
                        except Exception:
                            pass

                    tick = clob_pub.get_tick_size(token_id) or tick_fallback

                    # per-market budget split across YES/NO books to avoid doubling total exposure
                    mm = SymmetricSpreadMM(
                        target_spread_bps=params.target_spread_bps,
                        max_usd=float(params.max_usd) / 2.0,
                        alpha_scale=risk.size_scale(),
                    )
                    quotes = mm.quotes(mid)
                    params.state.quotes += 1

                    om = oms.get(token_id)
                    if om is None:
                        om = OrderManager(
                            run_id=run_id,
                            conn=conn,
                            exchange=exchange,
                            max_orders_per_token=s.max_orders_per_market,
                            cancel_reprice_sec=params.cancel_reprice_sec,
                            post_only=s.post_only,
                            tick_size=tick,
                        )
                        oms[token_id] = om
                    else:
                        om.cancel_reprice_sec = float(params.cancel_reprice_sec)
                        om.max_orders_per_token = int(s.max_orders_per_market)
                        om.tick_size = tick if (tick and tick > 0) else om.tick_size

                    cancels = om.cancel_stale()
                    if cancels:
                        cb.record_cancel()

                    for q in quotes[: s.max_orders_per_market]:
                        notional = float(q.price) * float(q.size)
                        if notional > max(1.0, (float(params.max_usd) / 2.0) * 1.10):
                            continue

                        res = om.place_or_replace(
                            condition_id=condition_id,
                            token_id=token_id,
                            side=q.side,
                            price=q.price,
                            size=q.size,
                            best_bid=best_bid,
                            best_ask=best_ask,
                        )
                        # SKIP（同价同量）不应计入 placed，否则会高估真实下单频率
                        if not (res.raw and isinstance(res.raw, dict) and res.raw.get("action") == "SKIP"):
                            cb.record_place(ok=res.success)

                        halt, why = cb.should_halt()
                        if halt:
                            repo.insert_risk_event(conn, run_id, int(time.time()), "ERROR", "HALT", why, {})
                            raise SystemExit(f"Circuit breaker HALT: {why}")

                    # paper/dry-run: intensity adaptive by top depth
                    intensity_eff = _paper_intensity(depth_top, tick, best_bid, best_ask)
                    sim_stats = om.simulate_fills(
                        condition_id=condition_id,
                        token_id=token_id,
                        midpoint=mid,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        dt_sec=float(s.quote_refresh_sec),
                        ts=loop_ts,
                        intensity_override=intensity_eff,
                        depth_top=depth_top,
                        pos_qty=float(getattr(inv.pos.get(str(token_id)), "qty", 0.0)) if hasattr(inv, "pos") else 0.0,
                    )
                    if sim_stats.fills:
                        params.state.fills += int(sim_stats.fills)
                        params.state.markout_sum += float(sim_stats.markout_sum)
                        params.state.realized_spread_sum += float(sim_stats.realized_spread_sum)

                # Persist calibration (with allocation and updated state)
                repo.upsert_calibration(
                    conn, condition_id,
                    alpha=params.alpha,
                    target_spread_bps=params.target_spread_bps,
                    max_usd=params.max_usd,
                    quote_refresh_sec=params.quote_refresh_sec,
                    cancel_reprice_sec=params.cancel_reprice_sec,
                    state=calibrator.to_state_json(params),
                )

            # 更新 depth_ref（用于下一轮）
            if depth_ref_mode != "static":
                est = _quantile(depth_samples, depth_ref_q)
                est = max(depth_ref_min, min(depth_ref_max, est if est > 0 else depth_ref_static))
                prev = float(getattr(cmd_run, "_paper_depth_ref"))
                ema = max(0.0, min(0.99, depth_ref_ema))
                new_ref = prev * ema + est * (1.0 - ema)
                setattr(cmd_run, "_paper_depth_ref", float(new_ref))

            # Persist position snapshots + PnL snapshot
            ts = int(time.time())
            equity = inv.equity(midpoint_by_token)
            for tid, p in inv.pos.items():
                mid = midpoint_by_token.get(tid)
                unreal = (float(mid) - p.avg_cost) * p.qty if mid is not None else 0.0
                repo.insert_position_snapshot(
                    conn, run_id, tid, ts,
                    qty=p.qty, avg_cost=p.avg_cost,
                    realized=p.realized, unrealized=unreal,
                    cash=inv.cash, equity=equity,
                    meta={"mid": mid},
                )
            snapshot_pnl(conn, run_id, inv, midpoint_by_token)

            # Dashboard refresh（轻量查询：最近订单/成交/风控事件）
            if dashboard:
                recent_orders = _rows_to_dicts(conn.execute(
                    "SELECT token_id, side, price, size, status, created_ts, updated_ts, local_order_id FROM orders WHERE run_id=? ORDER BY updated_ts DESC, local_order_id DESC LIMIT ?",
                    (run_id, 12),
                ))
                recent_trades = _rows_to_dicts(conn.execute(
                    "SELECT token_id, side, price, size, status, ts, trade_id FROM trades WHERE run_id=? ORDER BY ts DESC, trade_id DESC LIMIT ?",
                    (run_id, 12),
                ))
                recent_risk = _rows_to_dicts(conn.execute(
                    "SELECT level, code, message, ts FROM risk_events WHERE run_id=? ORDER BY ts DESC, code DESC LIMIT ?",
                    (run_id, 12),
                ))
                gross_exposure = 0.0
                unrealized = 0.0
                for tid, p in inv.pos.items():
                    mid = midpoint_by_token.get(tid)
                    if mid is None:
                        continue
                    gross_exposure += abs(p.qty) * float(mid)
                    unrealized += (float(mid) - p.avg_cost) * p.qty
                dashboard.update(
                    loop_ts=loop_ts,
                    universe_n=len(markets),
                    cash=float(inv.cash),
                    equity=float(equity),
                    gross_exposure=float(gross_exposure),
                    realized=float(inv.realized_total()),
                    unrealized=float(unrealized),
                    cb_stats={
                        "placed": int(cb.state.placed),
                        "rejected": int(cb.state.rejected),
                        "errors": int(cb.state.errors),
                        "cancels_1m": int(len(cb.state.cancel_events)),
                    },
                    recent_orders=recent_orders,
                    recent_trades=recent_trades,
                    recent_risk_events=recent_risk,
                )

            time.sleep(max(0.5, float(s.quote_refresh_sec)))
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C，正在退出…")
    finally:
        if dashboard:
            dashboard.stop()
        try:
            clob_pub.close()
        except Exception:
            pass

def cmd_report(args):
    from pmm.analytics import reports
    s = load_settings()
    setup_logging(s.log_level)
    conn = connect(s.db_path)
    init_db(conn)
    run_id = args.run_id
    import pandas as pd
    pd.set_option("display.width", 200)
    print("\n== Account ==")
    print(reports.latest_account(conn, run_id))
    print("\n== Recent Risk Events ==")
    print(reports.recent_risk_events(conn, run_id, n=30))
    print("\n== Top Markets by Notional ==")
    print(reports.top_markets_by_trade_notional(conn, run_id, n=10))
    print("\n== Latest Positions (last 50 rows) ==")
    print(reports.latest_positions(conn, run_id, n=50))

def build_parser():
    p = argparse.ArgumentParser(prog="pmm")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_db = sub.add_parser("db")
    sub_db = p_db.add_subparsers(dest="db_cmd", required=True)
    sub_db.add_parser("init").set_defaults(func=cmd_db_init)

    p_uni = sub.add_parser("universe")
    sub_uni = p_uni.add_subparsers(dest="u_cmd", required=True)
    sub_uni.add_parser("refresh").set_defaults(func=cmd_universe_refresh)

    p_run = sub.add_parser("run")
    p_run.add_argument("mode", choices=["paper", "live"])
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--dry-run", action="store_true", help="live mode: do not place orders (still journals)")
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report")
    p_rep.add_argument("--run-id", required=True)
    p_rep.set_defaults(func=cmd_report)

    return p

def main():
    # 先读 .env（如果存在），再读 env.example 作为“缺省兜底”（不覆盖已存在变量）
    load_dotenv()
    load_dotenv("env.example")
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "run":
        os.environ["PMM_MODE"] = args.mode
    args.func(args)
