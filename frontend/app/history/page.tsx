"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { getHistory } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Empty, ErrorBox, Loading } from "@/components/States";
import {
  DASH,
  fmtMoney,
  fmtPctFraction,
  trAiStatus,
} from "@/lib/format";

export default function HistoryPage() {
  const router = useRouter();
  const { data, loading, error } = useApi(() => getHistory(60), []);

  return (
    <div>
      <h1 className="page-title">历史记录</h1>
      <p className="page-desc">
        每日决策运行记录（按日期降序）。点击某一行可查看当天的选股详情。
      </p>

      {loading ? <Loading /> : null}
      {error ? <ErrorBox message={error} /> : null}

      {!loading && !error && data ? (
        data.history.length === 0 ? (
          <Empty text="暂无历史记录（可能尚未运行每日任务）" />
        ) : (
          <div className="card">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>日期</th>
                    <th>AI 状态</th>
                    <th className="num">选股数</th>
                    <th className="num">买入候选数</th>
                    <th>市场点评</th>
                    <th className="num">当日总资产</th>
                    <th className="num">累计收益</th>
                    <th className="num">最大回撤</th>
                    <th>复盘</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((h) => (
                    <tr
                      key={h.run_date}
                      className="clickable"
                      onClick={() =>
                        router.push(`/?date=${encodeURIComponent(h.run_date)}`)
                      }
                    >
                      <td>
                        <Link href={`/?date=${encodeURIComponent(h.run_date)}`}>
                          {h.run_date}
                        </Link>
                      </td>
                      <td>
                        <span
                          className={
                            h.ai_status === "ok"
                              ? "badge badge-ok"
                              : "badge badge-failed"
                          }
                        >
                          {trAiStatus(h.ai_status)}
                        </span>
                      </td>
                      <td className="num">{h.pick_count}</td>
                      <td className="num">{h.buy_count}</td>
                      <td className="cell-comment" title={h.market_comment}>
                        {h.market_comment || DASH}
                      </td>
                      <td className="num">
                        {h.account ? fmtMoney(h.account.total_assets) : DASH}
                      </td>
                      <td
                        className={`num ${h.account ? (h.account.cum_return > 0 ? "up" : h.account.cum_return < 0 ? "down" : "flat") : ""}`}
                      >
                        {h.account ? fmtPctFraction(h.account.cum_return) : DASH}
                      </td>
                      <td className="num">
                        {h.account
                          ? fmtPctFraction(h.account.max_drawdown, false)
                          : DASH}
                      </td>
                      <td>
                        <Link href={`/review?date=${encodeURIComponent(h.run_date)}`}>
                          查看复盘
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : null}
    </div>
  );
}