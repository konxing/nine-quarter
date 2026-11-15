"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { getPicks, type Pick } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Empty, ErrorBox, Loading } from "@/components/States";
import {
  DASH,
  fmtNum,
  fmtPctFraction,
  fmtPctValue,
  fmtWeight,
  pnlClass,
  trAction,
  trAiStatus,
  trCheckpoint,
  trPotential,
  trRegime,
} from "@/lib/format";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PicksView />
    </Suspense>
  );
}

function PicksView() {
  const searchParams = useSearchParams();
  const dateParam = searchParams.get("date");
  const { data, loading, error } = useApi(() => getPicks(dateParam), [dateParam]);

  return (
    <div>
      <h1 className="page-title">每日选股</h1>
      <p className="page-desc">
        AI 结合量化筛选给出的候选与观察列表。潜力等级为定性等级，非上涨概率；
        所有内容仅供研究参考，不构成投资建议。
        {dateParam ? (
          <>
            {" "}
            当前查看 {dateParam} 的选股，<Link href="/">返回最新一天</Link>。
          </>
        ) : null}
      </p>

      {loading ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {!loading && !error && data ? (
        data.date === null ? (
          <Empty text="暂无选股记录（可能尚未运行每日任务，或 AI 未配置/不可用）" />
        ) : (
          <>
            <div className="card">
              <div className="info-row">
                <strong>日期：{data.date}</strong>
                {data.market_env ? (
                  <span>
                    市场环境：
                    <strong>{trRegime(data.market_env.regime)}</strong>
                    <span className="hint">
                      （{data.market_env.above_ma20 ? "指数在20日线上方" : "指数在20日线下方"}，
                      近5日涨跌{" "}
                      <span className={pnlClass(data.market_env.ret_5d)}>
                        {fmtPctFraction(data.market_env.ret_5d)}
                      </span>
                      ）
                    </span>
                  </span>
                ) : (
                  <span className="hint">市场环境：暂无数据</span>
                )}
                {data.decision ? (
                  <span
                    className={
                      data.decision.ai_status === "ok"
                        ? "badge badge-ok"
                        : "badge badge-failed"
                    }
                  >
                    {trAiStatus(data.decision.ai_status)}
                  </span>
                ) : (
                  <span className="badge badge-neutral">无决策记录</span>
                )}
                {data.decision?.model ? (
                  <span className="hint">模型：{data.decision.model}</span>
                ) : null}
                {data.rule_version ? (
                  <span className="hint">规则版本：{data.rule_version}</span>
                ) : null}
                {typeof data.candidate_count === "number" ? (
                  <span className="hint">量化候选数：{data.candidate_count}</span>
                ) : null}
              </div>
              {data.decision?.ai_status === "failed" ? (
                <p className="hint">AI 调用失败，当日结果可能仅含量化筛选信息。</p>
              ) : null}
              {data.decision?.market_comment ? (
                <div className="comment-box">{data.decision.market_comment}</div>
              ) : (
                <p className="hint">暂无市场点评</p>
              )}
            </div>

            {data.picks.length === 0 ? (
              <Empty text="当日无选股（可能空仓或 AI 未配置/不可用）" />
            ) : (
              data.picks.map((p) => <PickCard key={p.id} pick={p} />)
            )}
          </>
        )
      ) : null}
    </div>
  );
}

function PickCard({ pick: p }: { pick: Pick }) {
  return (
    <div className="card">
      <div className="pick-head">
        <span className="pick-code">{p.code}</span>
        <span className="pick-name">{p.name || DASH}</span>
        <span
          className={
            p.action === "buy_candidate" ? "badge badge-buy" : "badge badge-watch"
          }
        >
          {trAction(p.action)}
        </span>
        <span className={`badge badge-${p.potential_level || "low"}`}>
          潜力：{trPotential(p.potential_level)}
        </span>
        <span className="hint">（定性等级，非上涨概率）</span>
      </div>

      <div className="pick-meta">
        <span>
          参考价：<strong>{fmtNum(p.ref_price)}</strong>
          {p.ref_price_time ? `（${p.ref_price_time}）` : ""}
        </span>
        <span>建议仓位：{fmtWeight(p.suggested_weight)}</span>
        <span>持有周期：{p.horizon || DASH}</span>
      </div>

      <div className="pick-fields">
        <Field label="推荐理由" value={p.reason} />
        <Field label="上涨逻辑" value={p.bull_logic} />
        <Field label="主要风险" value={p.bear_risks} />
        <Field label="买入触发条件" value={p.buy_trigger} />
        <Field label="失效条件" value={p.invalid_condition} />
        <Field label="相对优势" value={p.edge_vs_peers} />
      </div>

      <h3>后续表现</h3>
      {p.outcomes.length === 0 ? (
        <p className="hint">暂无后续数据</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>检查点</th>
                <th>评估日期</th>
                <th className="num">个股收益</th>
                <th className="num">行业收益</th>
                <th className="num">指数收益</th>
                <th className="num">相对指数超额</th>
              </tr>
            </thead>
            <tbody>
              {p.outcomes.map((o) => (
                <tr key={o.checkpoint}>
                  <td>{trCheckpoint(o.checkpoint)}</td>
                  <td>{o.eval_date}</td>
                  <td className={`num ${pnlClass(o.ret_pct)}`}>
                    {fmtPctValue(o.ret_pct)}
                  </td>
                  <td className={`num ${pnlClass(o.industry_ret_pct)}`}>
                    {fmtPctValue(o.industry_ret_pct)}
                  </td>
                  <td className={`num ${pnlClass(o.index_ret_pct)}`}>
                    {fmtPctValue(o.index_ret_pct)}
                  </td>
                  <td className={`num ${pnlClass(o.excess_vs_index)}`}>
                    {fmtPctValue(o.excess_vs_index)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="pick-field">
      <div className="field-label">{label}</div>
      <div className="field-value">{value || DASH}</div>
    </div>
  );
}