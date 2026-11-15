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
├── start.bat              不用 EXE 时的一键启动脚本
├── data/nine-quarter.db   SQLite 数据库（运行时生成）
├── reports/               每日报告与复盘（运行时生成）
├── logs/                  日志（运行时生成）
├── tests/                 单元 + 集成测试
├── .env.example
└── requirements.txt
```

## 快速开始

### 0. 一键启动（推荐）

双击根目录 **`nine-quarter.exe`**：

- **首次引导**：自动检测并停在第一个未完成的步骤——① 环境（`.venv`、后端依赖、前端依赖，可一键安装）→ ② 行情数据（`init` + `backfill`，可中断续跑）→ ③ AI 配置（地址/模型/Key，可测试连接，Key 只显示掩码）→ ④ 启动。已完成的步骤自动跳过。
- **控制台**：状态灯（后端 8000 / 前端 3100 / AI / 数据）、启动与停止服务、打开页面与设置页、立即执行今日流程、补充行业市值、实时日志。
- 关闭启动器时会询问是否一并停止服务，避免留下占用端口的僵尸进程。
- 服务日志：`logs/launcher-backend.log`、`logs/launcher-frontend.log`。
- 前提：本机已安装 Node.js（前端用 npm 启动）；Python 虚拟环境可由引导自动创建。

重新打包（改了启动器代码后）：

```bash
.venv\Scripts\python.exe build_exe.py
```

不想用 EXE 时，可双击 `start.bat`（同样拉起后端 8000 + 前端 3100），或按下面手动执行。

### 1. 后端

```bash
cd D:\nine-quarter
# 已为本项目创建虚拟环境 .venv（官方 Python 3.12）。如换机器：
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 配置：可先跳过，启动后在页面 http://localhost:3100/settings 里填 AI（见下）
copy .env.example .env

# 初始化 + 首次全量回填（约 5200 只股票 ×150 天，约 15～20 分钟，可中断重跑）
.venv\Scripts\python.exe -m backend.cli init
.venv\Scripts\python.exe -m backend.cli backfill

# 补充个股行业/市值（约 30 分钟，可中断重跑；缺失时行业因子降级为中性）
.venv\Scripts\python.exe -m backend.cli info

# 启动后端（含自动调度器）
.venv\Scripts\python.exe -m backend.cli serve --port 8000
```

### 2. 前端

开发模式（页面热更新）：

```bash
cd D:\nine-quarter\frontend
npm install
npm run dev      # http://localhost:3100
# 或 npm run build && npm start（生产模式，同样 3100）
```

**一键同时拉起前后端**：双击根目录 `start.bat`，会各开一个窗口（后端 8000、前端 3100），浏览器打开 `http://localhost:3100`。

前端默认请求 `http://127.0.0.1:8000`，可用环境变量 `NEXT_PUBLIC_API_BASE` 覆盖。

### 3. AI 配置（重要）

两种方式，页面内配置优先于 `.env`：

1. **页面内（推荐）**：后端与前端启动后打开 `http://localhost:3100/settings`，
   填接口地址、模型名、API Key，可先“测试连接”，再“保存并生效”。保存到本机
   SQLite，**无需重启后端**；页面只显示 Key 掩码。若环境中已有 `ARK_API_KEY`，
   地址和 Key 会自动预填，通常只需填模型名。
2. **`.env`**：

- `AI_BASE_URL`：OpenAI 兼容地址。火山方舟为 `https://ark.cn-beijing.volces.com/api/v3`。
- `AI_API_KEY`：密钥。**若环境中已有 `ARK_API_KEY`，未填这两项时会自动复用方舟地址与密钥。**
- `AI_MODEL`：**必填**。填你的方舟推理接入点（`ep-xxxx`）或已开通的模型名。未填时系统正常运行但 AI 选股/复盘降级（不产生主观结论与订单，绝不伪造）。
- `AI_PROXY`：如需代理访问 AI 接口显式填写（系统不读取 Windows 系统代理）。

页面保存的配置在下次启动时也会自动加载并覆盖 `.env`；测试连接只发一次极小请求，不落库。

## 新电脑克隆后如何启动

仓库里**不包含**虚拟环境、`node_modules`、数据库、日志、报告、`.env` 和打包好的 EXE（都在 `.gitignore` 里），所以新机器需要装一次依赖并回填一次数据。

**前置**：Windows + Python 3.12（安装时勾选 Add to PATH）+ Node.js 20/22 LTS。

```bat
git clone https://github.com/konxing/nine-quarter.git
cd nine-quarter

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

cd frontend
npm install
cd ..
```

然后二选一：

- **图形启动器（推荐）**：`.venv\Scripts\python.exe -m pip install pyinstaller` → `.venv\Scripts\python.exe build_exe.py` → 双击生成的 `nine-quarter.exe`，按引导走完「环境 → 数据 → AI → 启动」。
- **脚本启动**：双击 `start.bat`（后端 8000 + 前端 3100），浏览器打开 `http://localhost:3100/settings` 配 AI；数据回填另开窗口执行：

```bat
.venv\Scripts\python.exe -m backend.cli init
.venv\Scripts\python.exe -m backend.cli backfill
.venv\Scripts\python.exe -m backend.cli info
```

回填约 15～20 分钟（可中断续跑），`info` 约 30 分钟（可跳过，行业因子会降级为中性）。之后每个交易日由后端内的调度器自动执行。

> macOS/Linux：把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`，`start.bat` 换成分别执行 `serve` 与 `npm run dev`；EXE 打包仅面向 Windows。

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


## 待验证升级：模拟交易正确性（upgrade/simulation-integrity-20261115）

此分支包含一组**向后兼容的正确性修复**，在完整测试与历史订单核验之前不合入 main：

- 订单等待时间以 **唯一交易日期** 计数：同一天上午与盘后多次重试，不应使订单重复增加等待天数。新表 `order_attempts` 记录尝试日期和原因。旧订单的既有 `wait_days` 值保留，不清零；旧数据库用 `init` 运行非破坏式建表。
- 成交撮合中的资金、持仓批次、成交明细、订单完成状态现在在 **同一个 SQLite 事务** 中提交。任何步骤发生数据库异常都回滚整笔撮合，避免账户变动但成交记录不完整。
- 历史日期初筛读取股票/指数日线时增加 `date<=expected_date` 上界，防止数据集存在未来记录时提前使用未来行情。
- 对上述场景补充回归测试。验证方式：`python -m backend.cli init`，之后运行 `python -m pytest tests/ -q`。

**目前未解决、不得宣称已通过验证**：完整交易流水与真实行情端到端一致性、实时报价有效时点、股票池历史生存者偏差、停牌/除权/新股价格限制、点时可得新闻、样本外 Walk-forward 回测、模型校准与交易成本敏感性。尤其不能把启发式评分或 AI 定性“潜力”当成上涨概率。

### 下一轮验证升级建议

1. **先构建可复现基线**：保存数据快照版本、策略版本、AI 提示词/模型版本、决策时点，记录恒定规则及随机/行业中性对照组。
2. **滚动时间外测试**：训练、调参、验证、测试时间区间严格隔离；纳入历史退市/停牌标的，且仅使用决策时点已公开的新闻、财务与成分股资料。
3. **区分信号与组合**：跟踪 1/3/5/10/20 日超额收益、命中率、精确率、IC/Rank IC、换手率、净收益、最大回撤、波动率；报告样本量和置信区间，避免重复试验后选择性展示。
4. **现实撮合**：涨跌停、价格跳空、滑点、停牌与无法成交保持保守处理；实时快照必须保存采集时间和有效性，不可捏造报价字段。
5. **安全与可维护性**：本机 API Key 改用系统凭据存储；锁定数据 SDK 的已验证版本；添加升级备份、数据校验与任务失败告警。保持纯虚拟投资，不连接真实证券账户。

## 已知限制

- AI 选股/复盘需配置可用的模型（页面 `/settings` 或 `.env` 的 `AI_MODEL`）；否则降级运行。
- 行业/市值由 `info` 任务补充，未运行时行业相对强度降级为中性。
- 初筛评分为透明启发式（动量/量能/趋势/行业/流动性/低波），**不是上涨概率**；最终判断由 AI 横向比较。
- 页面内 AI 配置会把 Key 明文存入本机 SQLite，页面只显示掩码；`serve` 默认只监听 `127.0.0.1`，不要把后端暴露到公网或不受信任的局域网。
- 均线用不复权收盘价，收益用 BaoStock pctChg（已处理除权除息）。
- 单机 SQLite + 进程内调度，面向单机稳定运行；未做分布式/服务器部署。
```