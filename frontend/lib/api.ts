/** 后端 API 封装。所有数据来自 FastAPI 后端，前端不做任何 mock。 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path, { cache: "no-store" });
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(
      `无法连接后端，请确认后端已在 8000 端口启动（${API_BASE}）`
    );
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: string };
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new ApiError(
      detail
        ? `请求失败：${detail}（HTTP ${res.status}）`
        : `请求失败（HTTP ${res.status}）`,
      res.status
    );
  }
  return (await res.json()) as T;
}

/* ---------- /api/status ---------- */

export interface JobRun {
  job_name: string;
  biz_date: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  message: string | null;
}

export interface AccountInfo {
  initial_capital: number;
  cash: number;
  realized_pnl: number;
}

/** 注意：cum_return / max_drawdown 为小数比例（0.05 = 5%） */
export interface AccountSnapshot {
  date: string;
  cash: number;
  market_value: number;
  total_assets: number;
  unrealized_pnl: number;
  realized_pnl: number;
  cum_return: number;
  peak_assets: number;
  max_drawdown: number;
}

export interface StatusResponse {
  counts: {
    stocks: number;
    daily_bars: number;
    picks: number;
    orders: number;
    trades: number;
    reviews: number;
  };
  latest_bar_date: string | null;
  active_stocks: number;
  jobs: JobRun[];
  ai_configured: boolean;
  ai_model: string;
  account: AccountInfo | null;
  latest_snapshot: AccountSnapshot | null;
}

export const getStatus = () => get<StatusResponse>("/api/status");

/* ---------- /api/picks ---------- */

/** 注意：outcomes 中 ret_pct 等字段已是百分数（3.5 = 3.5%） */
export interface PickOutcome {
  checkpoint: number;
  eval_date: string;
  ret_pct: number | null;
  industry_ret_pct: number | null;
  index_ret_pct: number | null;
  excess_vs_index: number | null;
}

export interface Pick {
  id: number;
  run_date: string;
  code: string;
  name: string;
  action: "buy_candidate" | "watch" | string;
  ref_price: number | null;
  ref_price_time: string | null;
  reason: string;
  bull_logic: string;
  bear_risks: string;
  horizon: string;
  buy_trigger: string;
  invalid_condition: string;
  edge_vs_peers: string;
  potential_level: "high" | "medium" | "low" | string;
  /** 小数比例（0.15 = 15%） */
  suggested_weight: number;
  outcomes: PickOutcome[];
}

export interface DailyDecision {
  run_date: string;
  model: string;
  ai_status: "ok" | "failed" | string;
  market_comment: string;
}

export interface MarketEnv {
  regime: "strong" | "neutral" | "weak" | string;
  above_ma20: boolean;
  /** 小数比例 */
  ret_5d: number;
}

export interface PicksResponse {
  date: string | null;
  picks: Pick[];
  decision: DailyDecision | null;
  market_env: MarketEnv | null;
  rule_version?: string | null;
  candidate_count?: number;
}

export const getPicks = (date?: string | null) =>
  get<PicksResponse>(
    date ? `/api/picks?date=${encodeURIComponent(date)}` : "/api/picks"
  );

/* ---------- /api/account ---------- */

export interface PositionAdvice {
  decision_date: string;
  action: "hold" | "reduce" | "sell" | string;
  reason: string;
  ref_price: number | null;
}

export interface Position {
  code: string;
  name: string;
  industry: string;
  shares: number;
  avg_cost: number;
  latest_price: number | null;
  price_date: string | null;
  market_value: number;
  unrealized_pnl: number;
  /** 小数比例 */
  weight: number;
  /** 最近一次 AI 持仓判断；从未复盘过则为 null */
  ai_advice: PositionAdvice | null;
}

export interface AccountResponse {
  account: AccountInfo;
  snapshots: AccountSnapshot[];
  positions: Position[];
}

export const getAccount = () => get<AccountResponse>("/api/account");

/* ---------- /api/orders ---------- */

export interface Order {
  id: number;
  decision_date: string;
  code: string;
  name: string;
  side: "buy" | "sell" | string;
  status: "pending" | "filled" | "cancelled" | "expired" | string;
  /** 小数比例 */
  target_weight: number;
  planned_shares: number;
  ref_price: number;
  filled_date: string;
  filled_price: number;
  filled_shares: number;
  fees: number;
  reason: string;
  wait_days: number;
}

export interface OrdersResponse {
  orders: Order[];
}

export const getOrders = (status?: string, limit = 100) => {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (status) qs.set("status", status);
  return get<OrdersResponse>(`/api/orders?${qs.toString()}`);
};

/* ---------- /api/trades ---------- */

export interface Trade {
  id: number;
  order_id: number;
  code: string;
  side: "buy" | "sell" | string;
  trade_date: string;
  price: number;
  shares: number;
  amount: number;
  commission: number;
  stamp_tax: number;
  transfer_fee: number;
  price_source: string;
}

export interface TradesResponse {
  trades: Trade[];
}

export const getTrades = (limit = 100) =>
  get<TradesResponse>(`/api/trades?limit=${limit}`);

/* ---------- /api/reviews ---------- */

export interface Suggestion {
  id: number;
  review_date: string;
  category: string;
  content: string;
  status: "proposed" | "validated" | "adopted" | "rejected" | string;
  evidence: string;
}

export interface Review {
  review_date: string;
  target_date: string;
  ai_status: "ok" | "failed" | string;
  quant_json: string;
  report_md: string;
  ai_raw: string;
}

export interface PositionDecisionOutcome {
  checkpoint: number;
  eval_date: string;
  /** 已是百分数 */
  ret_pct: number | null;
  /** 已是百分数 */
  index_ret_pct: number | null;
}

/** AI 对某只股票/持仓给出的判断记录，按日保存可用于后续复盘 */
export interface PositionDecision {
  id: number;
  decision_date: string;
  code: string;
  name: string;
  action: "hold" | "reduce" | "sell" | string;
  reason: string;
  ref_price: number | null;
  created_at: string;
  outcomes: PositionDecisionOutcome[];
}

export interface ReviewsResponse {
  date: string | null;
  review: Review | null;
  suggestions?: Suggestion[];
  position_decisions?: PositionDecision[];
}

export const getReviews = (date?: string | null) =>
  get<ReviewsResponse>(
    date ? `/api/reviews?date=${encodeURIComponent(date)}` : "/api/reviews"
  );

/* ---------- /api/history ---------- */

export interface HistoryItem {
  run_date: string;
  model: string;
  ai_status: "ok" | "failed" | string;
  market_comment: string;
  created_at: string;
  pick_count: number;
  buy_count: number;
  account: {
    total_assets: number;
    /** 小数比例 */
    cum_return: number;
    /** 小数比例 */
    max_drawdown: number;
  } | null;
}

export interface HistoryResponse {
  history: HistoryItem[];
}

export const getHistory = (limit = 60) =>
  get<HistoryResponse>(`/api/history?limit=${limit}`);

/* ---------- /api/suggestions ---------- */

export interface SuggestionsResponse {
  suggestions: Suggestion[];
}

export const getSuggestions = (limit = 100) =>
  get<SuggestionsResponse>(`/api/suggestions?limit=${limit}`);

/* ---------- /api/settings/ai ---------- */

export interface AISettingsInput {
  base_url: string;
  model: string;
  /** 留空表示保留已配置的 Key（后端不会回显完整 Key） */
  api_key: string;
}

export interface AISettingsState {
  base_url: string;
  model: string;
  key_configured: boolean;
  /** 掩码，如 ****abcd；未配置为空 */
  key_masked: string;
  /** db=本机页面保存；env=环境变量；none=未配置 */
  source: "db" | "env" | "none" | string;
}

export interface AITestResult {
  ok: boolean;
  message: string;
}

export const getAISettings = () => get<AISettingsState>("/api/settings/ai");

export const saveAISettings = (input: AISettingsInput) =>
  post<AISettingsState>("/api/settings/ai", input);

export const testAISettings = (input: AISettingsInput) =>
  post<AITestResult>("/api/settings/ai/test", input);