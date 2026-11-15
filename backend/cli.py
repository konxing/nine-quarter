"""命令行入口：手动运行/回补/状态查询（自动调度之外的运维手段）。

用法：python -m backend.cli <command>
  init       初始化数据库
  backfill   首次全量回填（日历+股票池+日线+指数）
  status     查看数据与任务状态
"""
from __future__ import annotations

import argparse
import json
import logging

from .config import settings
from .db import connect, init_db
from .logging_setup import setup_logging

log = logging.getLogger("nine-quarter.cli")


def cmd_init(args) -> None:
    init_db(settings.db_path)
    print(f"数据库已初始化: {settings.db_path}")


def cmd_backfill(args) -> None:
    from .data_sources.update import run_initial
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        stats = run_initial(conn, settings)
        print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    finally:
        conn.close()


def cmd_status(args) -> None:
    conn = connect(settings.db_path)
    try:
        for t in ("stocks", "daily_bars", "index_bars", "trade_calendar",
                  "picks", "orders", "trades", "reviews", "job_runs"):
            n = conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            print(f"{t}: {n}")
        row = conn.execute("SELECT MAX(date) d FROM daily_bars").fetchone()
        print("最新日线日期:", row["d"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM stocks WHERE type='1' AND status='1'").fetchone()
        print("在市股票数:", row["n"])
        row = conn.execute(
            "SELECT COUNT(*) n FROM stocks WHERE industry!='' AND industry IS NOT NULL").fetchone()
        print("已有行业信息:", row["n"])
    finally:
        conn.close()


def cmd_daily(args) -> None:
    from .ai_config import apply_ai_overrides, load_ai_overrides
    from .pipeline import DataNotReadyError, run_daily
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        apply_ai_overrides(settings, load_ai_overrides(conn))
        res = run_daily(conn, settings, today=args.date)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    except DataNotReadyError as e:
        print(f"数据未就绪（稍后重试）: {e}")
    finally:
        conn.close()


def cmd_morning(args) -> None:
    from .ai_config import apply_ai_overrides, load_ai_overrides
    from .pipeline import run_morning
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        apply_ai_overrides(settings, load_ai_overrides(conn))
        res = run_morning(conn, settings, today=args.date)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    finally:
        conn.close()


def cmd_info(args) -> None:
    from .data_sources.info import update_stock_info
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        stats = update_stock_info(conn, force=args.force)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    finally:
        conn.close()


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=False)


def main() -> None:
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)
    p = argparse.ArgumentParser(prog="nine-quarter")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("backfill").set_defaults(fn=cmd_backfill)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    d = sub.add_parser("daily")
    d.add_argument("--date", default=None, help="YYYY-MM-DD，默认北京时间今日")
    d.set_defaults(fn=cmd_daily)
    m = sub.add_parser("morning")
    m.add_argument("--date", default=None)
    m.set_defaults(fn=cmd_morning)
    inf = sub.add_parser("info")
    inf.add_argument("--force", action="store_true", help="强制刷新已有行业")
    inf.set_defaults(fn=cmd_info)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()