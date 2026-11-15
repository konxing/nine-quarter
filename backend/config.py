"""全局配置：环境变量 + .env（敏感信息只放环境变量）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # 路径
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    reports_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "reports")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

    # 账户与风险
    initial_capital: float = field(default_factory=lambda: _f("INITIAL_CAPITAL", 100000))
    max_position_weight: float = field(default_factory=lambda: _f("MAX_POSITION_WEIGHT", 0.20))
    order_expire_days: int = field(default_factory=lambda: _i("ORDER_EXPIRE_DAYS", 3))

    # 初筛
    prescreen_count: int = field(default_factory=lambda: _i("PRESCREEN_COUNT", 30))
    min_avg_amount_20d: float = field(default_factory=lambda: _f("MIN_AVG_AMOUNT_20D", 5e7))
    min_price: float = field(default_factory=lambda: _f("MIN_PRICE", 2.0))
    min_history_bars: int = field(default_factory=lambda: _i("MIN_HISTORY_BARS", 60))
    exclude_st: bool = field(default_factory=lambda: os.environ.get("EXCLUDE_ST", "1") == "1")
    min_data_coverage: float = field(default_factory=lambda: _f("MIN_DATA_COVERAGE", 0.90))

    # 费用
    commission_rate: float = field(default_factory=lambda: _f("COMMISSION_RATE", 0.00025))
    min_commission: float = field(default_factory=lambda: _f("MIN_COMMISSION", 5.0))
    stamp_tax_rate: float = field(default_factory=lambda: _f("STAMP_TAX_RATE", 0.0005))
    transfer_fee_rate: float = field(default_factory=lambda: _f("TRANSFER_FEE_RATE", 0.00001))

    # AI（OpenAI 兼容接口）。未显式配置时自动复用环境中的火山方舟 ARK_API_KEY。
    ai_base_url: str = field(default_factory=lambda: os.environ.get("AI_BASE_URL") or (
        "https://ark.cn-beijing.volces.com/api/v3" if os.environ.get("ARK_API_KEY") else ""))
    ai_api_key: str = field(default_factory=lambda: os.environ.get("AI_API_KEY")
                            or os.environ.get("ARK_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", ""))
    ai_temperature: float = field(default_factory=lambda: _f("AI_TEMPERATURE", 0.3))
    ai_timeout: float = field(default_factory=lambda: _f("AI_TIMEOUT", 180))
    ai_max_tokens: int = field(default_factory=lambda: _i("AI_MAX_TOKENS", 8000))
    ai_proxy: str = field(default_factory=lambda: os.environ.get("AI_PROXY", ""))

    # 调度（北京时间）
    timezone: str = "Asia/Shanghai"
    morning_time: str = field(default_factory=lambda: os.environ.get("MORNING_TIME", "09:35"))
    daily_times: str = field(default_factory=lambda: os.environ.get("DAILY_TIMES", "18:00,18:30,19:00,19:30"))

    # 数据
    backfill_calendar_days: int = field(default_factory=lambda: _i("BACKFILL_CALENDAR_DAYS", 150))
    index_codes: tuple = ("sh.000001", "sh.000300", "sz.399006")

    @property
    def db_path(self) -> Path:
        custom = os.environ.get("DB_PATH", "")
        return Path(custom) if custom else self.data_dir / "nine-quarter.db"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.reports_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()