import logging
import os

def setup_logging(level: str | None = None) -> None:
    lvl = (level or os.getenv("PMM_LOG_LEVEL", "INFO")).upper()
    console_logs = os.getenv("PMM_CONSOLE_LOGS", "true").lower() == "true"
    log_file = os.getenv("PMM_LOG_FILE", "").strip()

    # 仪表盘模式下，默认把日志写文件，避免和 Live 抢控制台导致闪烁
    if not console_logs:
        if not log_file:
            log_file = "./data/pmm.log"
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        logging.basicConfig(
            level=getattr(logging, lvl, logging.INFO),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        )
        return

    use_rich_logs = os.getenv("PMM_RICH_LOGS", "true").lower() == "true"
    if use_rich_logs:
        try:
            from rich.logging import RichHandler
            logging.basicConfig(
                level=getattr(logging, lvl, logging.INFO),
                format="%(name)s | %(message)s",
                datefmt="%H:%M:%S",
                handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_level=True, show_path=False)],
            )
            return
        except Exception:
            # fallback to plain logging
            pass

    logging.basicConfig(level=getattr(logging, lvl, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
