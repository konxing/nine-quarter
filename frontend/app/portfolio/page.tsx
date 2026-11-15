"use client";

import {
  ApiError,
  getAccount,
  getOrders,
  getTrades,
  type AccountResponse,
  type AccountSnapshot,
  type Order,
  type Position,
  type Trade,
} from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Empty, ErrorBox, Loading } from "@/components/States";
import {
  DASH,
  fmtInt,
  fmtMoney,
  fmtNum,
  fmtPctFraction,
  fmtSignedMoney,
  fmtWeight,
  pnlClass,
  trOrderStatus,
  trPositionAction,
  trSide,
} from "@/lib/format";

interface PortfolioData {
  account: AccountResponse | null; // 账户未初始化时为 null（后端 404）
  orders: Order[];
  trades: Trade[];
}

export default function PortfolioPage() {
  const { data, loading, error } = useApi<PortfolioData>(async () => {
    const [account, ordersRes, tradesRes] = await Promise.all([
      getAccount().catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }),
      getOrders(undefined, 100),
      getTrades(100),
    ]);
    return { account, orders: ordersRes.orders, trades: tradesRes.trades };
  }, []);

  const latest: AccountSnapshot | null =
    data?.account && data.account.snapshots.length > 0
      ? data.account.snapshots[0]
      : null;

  return (
    <div>
      <h1 className="page-title">模拟投资</h1>
      <p className="page-desc">
        模拟账户的持仓、订单与成交记录，全部来自后端真实模拟数据（非实盘）。
      </p>

      {loading ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {!loading && !error && data ? (
        <>
          {data.account === null ? (
            <Empty text="模拟账户未初始化，暂无账户数据" />
          ) : (
            <>
              <div className="stat-grid">
                <Stat
                  label="总资产"
                  value={fmtMoney(
                    latest ? latest.total_assets : data.account.account.cash
                  )}
                  note={latest ? `快照日期 ${latest.date}` : "暂无快照，以可用资金计"}
                />
                <Stat
                  label="可用资金"
                  value={fmtMoney(data.account.account.cash)}
                  note={`初始资金 ${fmtMoney(data.account.account.initial_capital)}`}
                />
                <Stat
                  label="累计收益率"
                  value={fmtPctFraction(latest ? latest.cum_return : null)}
                  valueClass={pnlClass(latest ? latest.cum_return : null)}
                />
                <Stat
                  label="最大回撤"
                  value={
                    latest ? fmtPctFraction(latest.max_drawdown, false) : DASH
                  }
                  note="回撤幅度（相对资产峰值）"
                />
                <Stat
                  label="已实现盈亏"
                  value={fmtSignedMoney(data.account.account.realized_pnl)}
                  valueClass={pnlClass(data.account.account.realized_pnl)}
                />
                {latest ? (
                  <Stat
                    label="浮动盈亏"
                    value={fmtSignedMoney(latest.unrealized_pnl)}
                    valueClass={pnlClass(latest.unrealized_pnl)}
                  />
                ) : null}
              </div>

              <div className="card">
                <h2>总资产走势（最近 {data.account.snapshots.length} 个快照）</h2>
                <AssetSparkline snapshots={data.account.snapshots} />
              </div>

              <div className="card">
                <h2>当前持仓</h2>
                {data.account.positions.length === 0 ? (
                  <p className="hint">当前无持仓</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>代码 / 名称</th>
                          <th>行业</th>
                          <th className="num">股数</th>
                          <th className="num">成本价</th>
                          <th className="num">最新价（日期）</th>
                          <th className="num">市值</th>
                          <th className="num">浮动盈亏</th>
                          <th className="num">仓位占比</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.account.positions.map((pos) => (
                          <tr key={pos.code}>
                            <td>
                              {pos.code} {pos.name}
                            </td>
                            <td>{pos.industry || DASH}</td>
                            <td className="num">{fmtInt(pos.shares)}</td>
                            <td className="num">{fmtNum(pos.avg_cost, 3)}</td>
                            <td className="num">
                              {fmtNum(pos.latest_price)}
                              {pos.price_date ? `（${pos.price_date}）` : ""}
                            </td>
                            <td className="num">{fmtMoney(pos.market_value)}</td>
                            <td className={`num ${pnlClass(pos.unrealized_pnl)}`}>
                              {fmtSignedMoney(pos.unrealized_pnl)}
                            </td>
                            <td className="num">{fmtWeight(pos.weight)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <AdviceCard positions={data.account.positions} />
            </>
          )}

          <div className="card">
            <h2>模拟订单（最近 {data.orders.length} 条）</h2>
            {data.orders.length === 0 ? (
              <p className="hint">暂无模拟订单</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>决策日期</th>
                      <th>代码 / 名称</th>
                      <th>方向</th>
                      <th>状态</th>
                      <th className="num">目标仓位</th>
                      <th className="num">计划股数</th>
                      <th className="num">参考价</th>
                      <th>成交（日期 / 价 / 股数）</th>
                      <th className="num">费用</th>
                      <th className="num">等待天数</th>
                      <th>原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.map((o) => (
                      <tr key={o.id}>
                        <td>{o.id}</td>
                        <td>{o.decision_date}</td>
                        <td>
                          {o.code} {o.name}
                        </td>
                        <td className={o.side === "buy" ? "up" : "down"}>
                          {trSide(o.side)}
                        </td>
                        <td>
                          <span className={`badge badge-${o.status}`}>
                            {trOrderStatus(o.status)}
                          </span>
                        </td>
                        <td className="num">{fmtWeight(o.target_weight)}</td>
                        <td className="num">{fmtInt(o.planned_shares)}</td>
                        <td className="num">{fmtNum(o.ref_price)}</td>
                        <td>
                          {o.status === "filled"
                            ? `${o.filled_date || DASH} / ${fmtNum(o.filled_price)} / ${fmtInt(o.filled_shares)}`
                            : DASH}
                        </td>
                        <td className="num">{fmtMoney(o.fees)}</td>
                        <td className="num">{o.wait_days}</td>
                        <td className="cell-comment" title={o.reason}>
                          {o.reason || DASH}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h2>成交记录（最近 {data.trades.length} 条）</h2>
            {data.trades.length === 0 ? (
              <p className="hint">暂无成交记录</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>成交日期</th>
                      <th>代码</th>
                      <th>方向</th>
                      <th className="num">成交价</th>
                      <th className="num">股数</th>
                      <th className="num">金额</th>
                      <th className="num">佣金</th>
                      <th className="num">印花税</th>
                      <th className="num">过户费</th>
                      <th>价格来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((t) => (
                      <tr key={t.id}>
                        <td>{t.id}</td>
                        <td>{t.trade_date}</td>
                        <td>{t.code}</td>
                        <td className={t.side === "buy" ? "up" : "down"}>
                          {trSide(t.side)}
                        </td>
                        <td className="num">{fmtNum(t.price)}</td>
                        <td className="num">{fmtInt(t.shares)}</td>
                        <td className="num">{fmtMoney(t.amount)}</td>
                        <td className="num">{fmtMoney(t.commission)}</td>
                        <td className="num">{fmtMoney(t.stamp_tax)}</td>
                        <td className="num">{fmtMoney(t.transfer_fee)}</td>
                        <td>{t.price_source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  valueClass = "",
  note,
}: {
  label: string;
  value: string;
  valueClass?: string;
  note?: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${valueClass}`}>{value}</div>
      {note ? <div className="stat-note">{note}</div> : null}
    </div>
  );
}

/** 当前持仓的最近一次 AI 判断（持有/减仓/卖出），来自每日复盘的真实记录。 */
function AdviceCard({ positions }: { positions: Position[] }) {
  if (positions.length === 0) return null;
  const advised = positions.filter((p) => p.ai_advice !== null);
  return (
    <div className="card">
      <h2>AI 持仓建议</h2>
      <p className="hint">
        每只持仓最近一次 AI 判断及判断日期；决定是否执行由你判断，系统不会自动改算法。
      </p>
      {advised.length === 0 ? (
        <p className="hint">暂无 AI 持仓判断记录（需完成带 AI 的复盘）</p>
      ) : (
        advised.map((p) => {
          const a = p.ai_advice!;
          const badge =
            a.action === "sell"
              ? "badge badge-cancelled"
              : a.action === "reduce"
                ? "badge badge-buy"
                : "badge badge-hold";
          return (
            <div key={p.code} className="suggestion-item">
              <div className="suggestion-head">
                <span className="pick-code">{p.code}</span>
                <span className="pick-name">{p.name || DASH}</span>
                <span className={badge}>{trPositionAction(a.action)}</span>
                <span className="hint">
                  判断日期 {a.decision_date}
                  {a.ref_price !== null ? `，判断时价格 ${fmtNum(a.ref_price)}` : ""}
                </span>
              </div>
              <div className="suggestion-content">{a.reason || DASH}</div>
            </div>
          );
        })
      )}
    </div>
  );
}

/** 轻量 SVG 折线：总资产走势（snapshots 按日期降序传入，内部反转为升序）。 */
function AssetSparkline({ snapshots }: { snapshots: AccountSnapshot[] }) {
  if (snapshots.length < 2) {
    return <p className="hint">快照不足两条，暂无走势可绘制</p>;
  }
  const asc = [...snapshots].reverse();
  const values = asc.map((s) => s.total_assets);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const W = 600;
  const H = 140;
  const PAD = 8;
  const span = max - min || 1;
  const points = asc
    .map((s, i) => {
      const x = PAD + (i / (asc.length - 1)) * (W - PAD * 2);
      const y = H - PAD - ((s.total_assets - min) / span) * (H - PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = asc[0];
  const last = asc[asc.length - 1];
  return (
    <div className="sparkline-box">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="总资产走势折线图">
        <polyline
          points={points}
          fill="none"
          stroke="#2563eb"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="sparkline-labels">
        <span>
          {first.date}：{fmtMoney(first.total_assets)}
        </span>
        <span>
          区间 {fmtMoney(min)} ~ {fmtMoney(max)}
        </span>
        <span>
          {last.date}：{fmtMoney(last.total_assets)}
        </span>
      </div>
    </div>
  );
}