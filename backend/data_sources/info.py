"""个股行业与市值更新（AKShare 单股信息，每周后台任务，断点续传）。

行业用于初筛相对行业强弱与复盘行业对比；缺失时相关因子降级为中性，不阻塞主流程。
"""
from __future__ import annotations

import logging
import sqlite3
import time

from .akshare_source import fetch_stock_info
from .collector import active_stock_codes

log = logging.getLogger("nine-quarter.info")


def update_stock_info(conn: sqlite3.Connection, force: bool = False,
                      progress_every: int = 200, sleep: float = 0.05) -> dict:
    codes = active_stock_codes(conn)
    updated = skipped = failed = 0
    for i, code in enumerate(codes, 1):
        if not force:
            row = conn.execute("SELECT industry FROM stocks WHERE code=?", (code,)).fetchone()
            if row and row["industry"]:
                skipped += 1
                continue
        info = fetch_stock_info(code)
        if info is None:
            failed += 1
        else:
            conn.execute("UPDATE stocks SET industry=?, total_mv=? WHERE code=?",
                         (info.get("industry", ""), info.get("total_mv"), code))
            conn.commit()
            updated += 1
        if i % progress_every == 0 or i == len(codes):
            log.info("个股信息进度 %d/%d（更新%d 跳过%d 失败%d）",
                     i, len(codes), updated, skipped, failed)
        if sleep:
            time.sleep(sleep)
    return dict(total=len(codes), updated=updated, skipped=skipped, failed=failed)