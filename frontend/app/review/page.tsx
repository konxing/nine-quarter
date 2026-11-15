"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { getReviews, type PositionDecision } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Empty, ErrorBox, Loading } from "@/components/States";
import {
  DASH,
  fmtNum,
  fmtPctValue,
  pnlClass,
  trAiStatus,
  trCheckpoint,
  trPositionAction,
  trSuggestionStatus,
} from "@/lib/format";

export default function ReviewPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ReviewView />
    </Suspense>
  );
}

function ReviewView() {
  const searchParams = useSearchParams();
  const dateParam = searchParams.get("date");
  const { data, loading, error } = useApi(() => getReviews(dateParam), [dateParam]);
  const review = data?.review ?? null;
  const suggestions = data?.suggestions ?? [];
  const positionDecisions = data?.position_decisions ?? [];

  return (
    <div>
      <h1 className="page-title">每日复盘</h1>
      <p className="page-desc">
        复盘报告、AI 持仓判断记录与改进建议。建议仅保存待验证，不会自动修改算法。
        {dateParam ? (
          <>
            {" "}
            当前查看 {dateParam} 的复盘，<Link href="/review">返回最新一天</Link>。
          </>
        ) : null}
      </p>

      {loading ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {!loading && !error && data ? (
        data.date === null || review === null ? (
          <Empty text="暂无复盘记录（可能尚未运行复盘任务）" />
        ) : (
          <>
            <div className="card">
              <div className="info-row">
                <strong>复盘日期：{review.review_date}</strong>
                <span>复盘对象交易日：{review.target_date}</span>
                <span
                  className={
                    review.ai_status === "ok"
                      ? "badge badge-ok"
                      : "badge badge-failed"
                  }
                >
                  {trAiStatus(review.ai_status)}
                </span>
              </div>
              {review.ai_status === "failed" ? (
                <p className="hint">AI 复盘不可用，仅量化数据。</p>
              ) : null}
            </div>

            <div className="card">
              <h2>AI 持仓判断记录</h2>
              <p className="hint">
                当日 AI 对每只相关股票给出的判断（含持有），以及第 1/3/5 个交易日的实际表现。
              </p>
              {positionDecisions.length === 0 ? (
                <p className="hint">当日无 AI 持仓判断记录</p>
              ) : (
                positionDecisions.map((d) => (
                  <PositionDecisionItem key={d.id} decision={d} />
                ))
              )}
            </div>

            <div className="card">
              <h2>复盘报告</h2>
              {review.report_md ? (
                <pre className="report-pre">{review.report_md}</pre>
              ) : (
                <p className="hint">暂无报告文本</p>
              )}
              {review.quant_json ? (
                <details style={{ marginTop: 12 }}>
                  <summary className="hint">查看量化数据（quant_json）</summary>
                  <pre className="report-pre">{review.quant_json}</pre>
                </details>
              ) : null}
            </div>

            <div className="card">
              <h2>改进建议</h2>
              <p className="hint">建议仅保存待验证，不会自动修改算法。</p>
              {suggestions.length === 0 ? (
                <p className="hint">当日无改进建议</p>
              ) : (
                suggestions.map((s) => (
                  <div key={s.id} className="suggestion-item">
                    <div className="suggestion-head">
                      <span className="badge badge-neutral">
                        {s.category || DASH}
                      </span>
                      <span
                        className={
                          s.status === "adopted"
                            ? "badge badge-filled"
                            : s.status === "rejected"
                              ? "badge badge-cancelled"
                              : "badge badge-pending"
                        }
                      >
                        {trSuggestionStatus(s.status)}
                      </span>
                      <span className="hint">#{s.id}</span>
                    </div>
                    <div className="suggestion-content">{s.content}</div>
                    {s.evidence ? (
                      <div className="suggestion-evidence">依据：{s.evidence}</div>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </>
        )
      ) : null}
    </div>
  );
}

function PositionDecisionItem({ decision: d }: { decision: PositionDecision }) {
  const actionClass =
    d.action === "sell"
      ? "badge badge-cancelled"
      : d.action === "reduce"
        ? "badge badge-buy"
        : "badge badge-hold";
  return (
    <div className="suggestion-item">
      <div className="suggestion-head">
        <span className="pick-code">{d.code}</span>
        <span className="pick-name">{d.name || DASH}</span>
        <span className={actionClass}>{trPositionAction(d.action)}</span>
        {d.ref_price !== null ? (
          <span className="hint">判断时价格：{fmtNum(d.ref_price)}</span>
        ) : null}
      </div>
      <div className="suggestion-content">{d.reason || DASH}</div>
      {d.outcomes.length === 0 ? (
        <div className="suggestion-evidence">暂无后续数据</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>检查点</th>
                <th>评估日期</th>
                <th className="num">个股收益</th>
                <th className="num">指数收益</th>
              </tr>
            </thead>
            <tbody>
              {d.outcomes.map((o) => (
                <tr key={o.checkpoint}>
                  <td>{trCheckpoint(o.checkpoint)}</td>
                  <td>{o.eval_date}</td>
                  <td className={`num ${pnlClass(o.ret_pct)}`}>
                    {fmtPctValue(o.ret_pct)}
                  </td>
                  <td className={`num ${pnlClass(o.index_ret_pct)}`}>
                    {fmtPctValue(o.index_ret_pct)}
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
