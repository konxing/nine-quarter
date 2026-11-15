/** 显示格式化与中文翻译。所有数字均来自 API，这里只做单位换算与格式化。 */

export const DASH = "—";

/** 金额：人民币，两位小数 */
export function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return `¥${v.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** 盈亏金额：带正负号 */
export function fmtSignedMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const sign = v > 0 ? "+" : "";
  return `${sign}${fmtMoney(v)}`;
}

/** 普通数字 */
export function fmtNum(
  v: number | null | undefined,
  digits = 2
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 整数（股数等） */
export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("zh-CN");
}

/**
 * 小数比例 → 带符号百分数（0.0512 → +5.12%）。
 * 用于 cum_return、ret_5d 等后端以小数存储的字段。
 */
export function fmtPctFraction(
  v: number | null | undefined,
  signed = true
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return fmtPctValue(v * 100, signed);
}

/**
 * 已是百分数的值 → 带符号百分数（3.5 → +3.50%）。
 * 用于 pick_outcomes 的 ret_pct / excess_vs_index 等字段。
 */
export function fmtPctValue(
  v: number | null | undefined,
  signed = true
): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const sign = signed && v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/** 仓位比例（小数）→ 百分数，不带符号（0.15 → 15.0%） */
export function fmtWeight(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return `${(v * 100).toFixed(1)}%`;
}

/** A股习惯：涨红跌绿。返回 CSS class */
export function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

/* ---------- 中文翻译 ---------- */

export function trRegime(regime: string | null | undefined): string {
  switch (regime) {
    case "strong":
      return "强势";
    case "neutral":
      return "震荡";
    case "weak":
      return "弱势";
    default:
      return regime || DASH;
  }
}

export function trAction(action: string): string {
  return action === "buy_candidate" ? "买入候选" : action === "watch" ? "观察" : action;
}

export function trPotential(level: string): string {
  switch (level) {
    case "high":
      return "高";
    case "medium":
      return "中";
    case "low":
      return "低";
    default:
      return level || DASH;
  }
}

export function trOrderStatus(status: string): string {
  switch (status) {
    case "pending":
      return "待成交";
    case "filled":
      return "已成交";
    case "cancelled":
      return "已作废";
    case "expired":
      return "已过期";
    default:
      return status;
  }
}

export function trSide(side: string): string {
  return side === "buy" ? "买入" : side === "sell" ? "卖出" : side;
}

export function trAiStatus(status: string | null | undefined): string {
  if (status === "ok") return "AI 正常";
  if (status === "failed") return "AI 失败";
  return status || DASH;
}

export function trSuggestionStatus(status: string): string {
  switch (status) {
    case "proposed":
      return "待验证";
    case "validated":
      return "已验证";
    case "adopted":
      return "已采纳";
    case "rejected":
      return "已拒绝";
    default:
      return status;
  }
}

/** checkpoint → 第 N 个交易日 */
export function trCheckpoint(cp: number): string {
  return `第${cp}个交易日`;
}

/** AI 持仓判断动作 */
export function trPositionAction(action: string): string {
  switch (action) {
    case "hold":
      return "持有";
    case "reduce":
      return "减仓";
    case "sell":
      return "卖出";
    default:
      return action || DASH;
  }
}