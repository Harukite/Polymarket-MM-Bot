# Polymarket MM Bot（研究 + 纸交易 + 实盘脚手架）

本项目提供一个**可落地**的 Polymarket CLOB 做市/流动性策略研究框架，目标是：

- **只交易流动性 Top 50 市场**（Gamma `/markets` 按 `liquidityNum` 排序）。citeturn9view0
- 同时支持：
  - **Paper Trading（撮合模拟 / 记录 trade tape）**
  - **Live Trading（接 py-clob-client 下单 / 撤单 + user websocket 监听成交与订单事件）**
- 所有数据（市场快照、盘口/中间价、委托、成交、PnL、参数校准）**统一落地 SQLite**。

> 风险提示：实盘交易存在资金损失风险。本项目默认保守风控（`α=1.5`）并提供“逐市场自适应校准”，但不保证盈利。

---

## 1) 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp env.example .env
```

> 注意：仓库提供的是 `env.example`（配置示例）。请把敏感信息（私钥、API key/secret 等）只放在你本地的 `.env`，不要提交到仓库。

---

## 2) 获取 Top 50 市场（Gamma）

Gamma API Base：`https://gamma-api.polymarket.com`。citeturn1view3turn8search1

项目默认调用：

- `GET /markets?limit=50&offset=0&active=true&closed=false&order=liquidityNum&ascending=false` citeturn9view0

运行：

```bash
pmm universe refresh
```

---

## 3) 纸交易（Paper）

```bash
pmm db init
pmm run paper
```

### 3.1 Paper 现在会“模拟真实成交”
Paper/Dry-run 会基于真实 CLOB 公共行情（mid、orderbook、tick）：
- 对 YES/NO 两个 token 都挂单
- 按盘口深度/价差做成交强度自适应，并生成 `PARTIAL/FILLED` 的模拟成交写入 `trades`
- 生成成交后的 `markout`（成交后价格漂移）与 `realized_spread` 作为质量信号，写入 trade `raw_json`，并累计进 `market_calibration.state_json`

常用调参入口都在 `env.example` 的 `PMM_PAPER_*`。

---

## 4) 实盘准备（Live）

### 4.1 CLOB 端点

- CLOB REST：`https://clob.polymarket.com` citeturn1view3
- CLOB WebSocket：`wss://ws-subscriptions-clob.polymarket.com/ws/`（`market` 公共，`user` 需鉴权）citeturn1view3

### 4.2 认证（L1/L2）

CLOB 有两级认证：

- L1：用私钥签名派生/创建 API Key
- L2：API `key/secret/passphrase`，用于下单/撤单/拉取私有数据 citeturn1view0

快速派生 L2 凭据（py-clob-client）示例在官方文档中给出：citeturn6view0turn7view0

> 你可以把派生出的 L2 凭据写入 `.env`，避免每次启动都派生。

### 4.3 user websocket（trade tape）

User channel 会推送 `order` / `trade` 事件（PLACEMENT/UPDATE/CANCELLATION、MATCHED/MINED/CONFIRMED…），用于“接近实盘”的 tape 记录。citeturn3view1turn4search0turn2view0

---

## 5) 运行实盘（建议先 dry-run）

```bash
pmm db init
# 先 paper 跑稳定，再 live
pmm run live --dry-run
pmm run live
```

### 5.1 仪表盘刷新频率
仪表盘默认 **1 秒刷新一次**（可配置）：`PMM_DASHBOARD_REFRESH_SEC=1.0`。
做市主循环的节奏仍由 `PMM_QUOTE_REFRESH_SEC` 控制（默认 3 秒），两者已解耦。

---

## 6) 项目结构

```
polymarket_mm_bot/
  src/pmm/
    cli.py
    config.py
    logging.py
    db/
      schema.py
      repo.py
    market/
      gamma.py
      universe.py
    execution/
      exchange_base.py
      paper_exchange.py
      live_exchange.py
      live_user_stream.py
    strategy/
      base.py
      mm_spread.py
      calibrator.py
      risk.py
    analytics/
      pnl.py
      reports.py
    utils/
      time.py
      math.py
  docs/
    architecture.md
    operations.md
    risk.md
  scripts/
    run_paper.sh
    run_live.sh
```

---

## 7) 下一步（你可以直接做）

- 增加更多策略（统计套利、盘口失衡、跨市场对冲）
- 增加“撮合引擎精度”（多层盘口、队列、部分成交）
- 增加“实盘安全阀”（最大撤单频率、断线自动平仓、异常保护）


## 如何“快速校准到你想要的 fills/min”
- 想让 fills 更多：优先调大 PMM_PAPER_FILL_INTENSITY
- 想让 价差越宽越难成交：调大 PMM_PAPER_SPREAD_K
- 想让 partial 更少 / full 更多：调大 PMM_PAPER_FULL_FILL_PROB
- 想让 partial 更小更碎：增大 PMM_PAPER_PARTIAL_BETA_B（或降低 MAX_FRAC）

> 提醒：`placed` 是“下单/换价次数”，不等同于成交次数。成交以 `trades` 表为准。
