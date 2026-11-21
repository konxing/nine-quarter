# nine-quarter — AI 股票筛选与模拟投资系统

版本 V2.0（精简实施版）。每天自动筛选 A 股、用 AI 选出具有上涨潜力的股票、进行**纯虚拟**模拟投资，并在后续交易日复盘决策、持续检验过去的判断。

> 个人非商业研究用途。不接真实证券账户、不实盘交易。所有行情/公告来自真实且允许个人使用的免费数据源；模拟账户完全虚拟。AI 负责研究判断，Python 负责全部数值计算、成交与账户余额。

## 四个核心模块

1. **信息收集**：BaoStock 行情/日历/股票池，AKShare 新闻/公告/实时盘口/个股行业市值。
2. **每日筛股**：Python 透明指标全市场初筛约 30 只 → AI 横向比较选出 3～5 只关注（其中 1～3 只买入候选，允许空仓）。
3. **模拟投资**：10 万虚拟账户，遵守 T+1、交易单位、涨跌停/停牌、手续费印花税；收盘后决策**只能次日按真实可得价格成交**，禁止未来价格。
4. **每日复盘**：追踪推荐股（含未买入）第 1/3/5 交易日表现（相对行业/沪深300），同时给出**收盘价口径**（选股是否看对）与**账户口径**（按次日真实成交价与费用实际能赚多少），两者不混用；AI 复盘四类失误，改进建议只保存待验证、不自动改算法；AI 对持仓的持有/减仓/卖出判断按日结构化保存，并同样追踪第 1/3/5 交易日表现，供后续持续检验。

## 技术栈

- 后端：Python 3.12 + FastAPI + Pandas/NumPy + BaoStock + AKShare + APScheduler
- 数据库：SQLite（WAL）
- AI：OpenAI 兼容接口（httpx），环境变量配置地址/模型/Key
- 前端：Next.js 15 + TypeScript（每日选股/模拟投资/每日复盘/历史记录四个业务页 + 设置页）

## 目录结构

```
nine-quarter/
├── backend/
│   ├── main.py            FastAPI 入口 + 调度器启动
│   ├── cli.py             命令行（init/backfill/daily/morning/info/status/serve）
│   ├── pipeline.py        每日全流程编排
│   ├── config.py / db.py  配置与 SQLite schema
│   ├── data_sources/      BaoStock/AKShare 封装、收集、校验、日历、新闻
│   ├── screening/         指标、过滤、排序、初筛编排
│   ├── ai_analysis/       AI 客户端、选股、新闻分析、提示词
│   ├── simulation/        交易规则、账户持仓、订单撮合、仓位计划
│   ├── review/            决策追踪、复盘编排
│   └── scheduler/         APScheduler 任务
├── frontend/              Next.js 前端
├── launcher/              桌面启动器（Tkinter，首次引导 + 控制台）
├── build_exe.py           打包 nine-quarter.exe
├── build.bat              一键装依赖并打包 EXE（新机器只需跑这个）
├── data/nine-quarter.db   SQLite 数据库（运行时生成）
├── reports/               每日报告与复盘（运行时生成）
├── logs/                  日志（运行时生成）
├── tests/                 单元 + 集成测试
├── .env.example
└── requirements.txt
```

## 快速开始（Windows，两步）

前置：Python 3.12（安装时勾选 Add to PATH）+ Node.js 20/22 LTS。

1. **双击 `build.bat`**：一个脚本做完所有准备——创建 `.venv`、装后端依赖、装 PyInstaller、装前端依赖、打包出 `nine-quarter.exe`。
2. **双击 `nine-quarter.exe`**：首次引导自动停在第一个未完成的步骤——① 环境 → ② 行情回填（约 15～20 分钟，可中断续跑）→ ③ AI 配置（地址/模型/Key，可测试连接，Key 只显示掩码）→ ④ 启动并打开浏览器。

以后每次启动只需双击 `nine-quarter.exe`。

启动器控制台提供：状态灯（后端 8000 / 前端 3100 / AI / 数据）、启动与停止服务、打开页面与设置页、立即执行今日流程、补充行业市值、实时日志。关闭启动器时会询问是否一并停止服务，避免留下占用端口的僵尸进程。

- 页面：`http://localhost:3100`　后端 API：`http://127.0.0.1:8000`
- 服务日志：`logs/launcher-backend.log`、`logs/launcher-frontend.log`
- 前端默认请求 `http://127.0.0.1:8000`，可用 `NEXT_PUBLIC_API_BASE` 覆盖

### AI 配置

引导第 3 步或页面 `http://localhost:3100/settings` 填写，保存到本机 SQLite，**立即生效、无需重启**，且优先于 `.env`：

- 接口地址：OpenAI 兼容地址，火山方舟为 `https://ark.cn-beijing.volces.com/api/v3`
- 模型名：方舟推理接入点（`ep-xxxx`）或已开通的模型名，**必填**
- API Key：若环境中已有 `ARK_API_KEY`，地址与 Key 会自动预填，通常只需填模型名
- 未配置 AI 时系统照常运行，但不产生选股与订单（绝不伪造）

也可用 `.env`（复制 `.env.example`）：`AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` / `AI_PROXY`（需要代理时显式填写，系统不读取 Windows 系统代理）。

### 命令行（可选，运维/调试）

```bash
.venv\Scripts\python.exe -m backend.cli init      # 初始化数据库
.venv\Scripts\python.exe -m backend.cli backfill  # 全量回填（可中断续跑）
.venv\Scripts\python.exe -m backend.cli info      # 补充行业/市值（可跳过，行业因子降级为中性）
.venv\Scripts\python.exe -m backend.cli daily     # 手动执行当日流程
.venv\Scripts\python.exe -m backend.cli morning   # 手动处理昨日订单
.venv\Scripts\python.exe -m backend.cli status    # 查看数据与任务状态
.venv\Scripts\python.exe -m backend.cli serve --port 8000   # 只起后端（含调度器）
```

改了启动器代码后重新打包：再跑一次 `build.bat`，或 `.venv\Scripts\python.exe build_exe.py`。

## 新电脑克隆后如何启动

```bat
git clone https://github.com/konxing/nine-quarter.git
```

然后**双击 `build.bat`，再双击 `nine-quarter.exe`**，跟着引导走完即可。就这两步。

仓库里不含 `.venv`、`node_modules`、数据库、日志、报告、`.env` 和 EXE（都在 `.gitignore` 里）：`build.bat` 负责装依赖并打包，启动器引导负责回填数据与配置 AI。

> macOS/Linux：`build.bat`/EXE 仅面向 Windows。其它平台手动执行 `python -m venv .venv`、`.venv/bin/python -m pip install -r requirements.txt`、`cd frontend && npm install`，再分别运行 `.venv/bin/python -m backend.cli serve --port 8000` 与 `npm run dev`。

## 每日自动流程（北京时间 Asia/Shanghai）

调度器在后端进程内运行（APScheduler），工作日触发、内部按交易日历跳过节假日：

- **上午 09:35**：按实时可得价格处理前一交易日的模拟订单；不可得则留待盘后。上午任务同样写入 `job_runs`，状态可在 `/api/status` 与前端看到。
- **盘后 18:00/18:30/19:00/19:30**（重试时段）：更新行情→覆盖率校验→次日订单按开盘价撮合→收盘估值→初筛→新闻→AI 选股→生成次日订单→复盘昨日→日报。数据未就绪自动等待下一时段；当日成功则幂等跳过。

也可用命令行手动运行/当日重试（`--date` 只能指定行情已更新到的当日；历史日不可回放，避免使用未来新闻）：

```bash
.venv\Scripts\python.exe -m backend.cli daily --date 2026-11-09
.venv\Scripts\python.exe -m backend.cli morning
.venv\Scripts\python.exe -m backend.cli status
```

### Windows 任务计划程序（可选替代）

若不想常驻后端进程，可用任务计划程序每交易日 18:00 调用：

```
程序：D:\nine-quarter\.venv\Scripts\python.exe
参数：-m backend.cli daily
起始于：D:\nine-quarter
```

前端需后端 API 时再单独启动 `serve`。

## 数据源与授权

- **BaoStock**（免费、匿名登录、个人非商业）：历史日线、交易日历、股票池。注意其 `get_data()` 与 pandas≥2 不兼容，本项目一律逐行读取。
- **AKShare**（聚合东方财富等公开免费接口，个人研究）：全球快讯、个股新闻、公告、实时盘口、个股行业/市值。
- 单一来源失败独立跳过，不阻塞主流程；无法合法稳定获取的来源不强行爬取。

## 关键正确性保证

- **无未来价格**：撮合日必须严格晚于决策日；收盘后决策次日按开盘价（或上午实时价）成交。
- **保守成交**：停牌、开盘涨跌停、一字板、缺数据、T+1 不足、现金不足 → 保留未成交或缩减整手，超期作废，绝不虚构成交。
- **仓位上限**：单只股票总市值不超过总资产的 `MAX_POSITION_WEIGHT`（默认 20%）；已持仓再被推荐时只按剩余空间补仓。
- **数据校验**：异常 bar 拒收；当日覆盖率不足阈值则停止，不用旧行情冒充当日。
- **幂等可恢复**：行情按股断点续传；订单（同日/同股/同方向）、快照、复盘、建议重复运行不产生重复记录；已有同方向待成交订单时不再叠加新单（避免重复买入超仓位）；AI 失败后当日重试成功仍会正常补写建议与持仓判断。
- **决策不可篡改**：每日原始 AI 输出、初筛快照、成交记录追加保存。
- **AI 失效降级**：接口失败/未配置 → 记录失败、不产生选股与订单，仍完成估值与量化复盘。

## 测试

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

覆盖：交易规则（涨跌停/单位/费用/T+1/成交判定）、账户与 FIFO 收益回撤、订单撮合与无未来价格、单只仓位上限（含已持仓补仓）、初筛确定性与过滤、数据校验与去重、断点续传、AI 客户端失效、页面内 AI 配置（持久化/掩码/即生效/连通测试不落库）、桌面启动器（环境检测/命令流式执行与中止/AI 配置读写/引导步骤定位/图标与打包自检）、新闻/选股/复盘编排、API、流水线失败场景（非交易日/数据未就绪/AI 降级）、AI 失败后重试补写、同一决策日订单幂等与待成交单不叠加、复盘账户口径（成交价+费用）、检查点漏跑按真实交易日补记、上午任务 job_runs 记录、两日端到端（AI 选股→次日开盘成交→估值复盘）。

## 已知限制

- AI 选股/复盘需配置可用的模型（页面 `/settings` 或 `.env` 的 `AI_MODEL`）；否则降级运行。
- 行业/市值由 `info` 任务补充，未运行时行业相对强度降级为中性。
- 初筛评分为透明启发式（动量/量能/趋势/行业/流动性/低波），**不是上涨概率**；最终判断由 AI 横向比较。
- 页面内 AI 配置会把 Key 明文存入本机 SQLite，页面只显示掩码；`serve` 默认只监听 `127.0.0.1`，不要把后端暴露到公网或不受信任的局域网。
- 均线用不复权收盘价，收益用 BaoStock pctChg（已处理除权除息）。
- 单机 SQLite + 进程内调度，面向单机稳定运行；未做分布式/服务器部署。
```