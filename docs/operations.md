# Operations (v5: 资金分配优化 = 最后一步)

## 1) 初始化

```bash
pmm db init
pmm universe refresh
```

## 2) 纸交易 / Dry-run

```bash
pmm run paper
pmm run live --dry-run
```

### 2.1 配置文件
仓库提供 `env.example`（配置示例）。建议：

```bash
cp env.example .env
```

> `.env` 用于存放你的本地私钥与 API 凭据，请不要提交到仓库。

### 2.2 Paper 成交调参（常用）
Paper/Dry-run 现在会生成模拟成交写入 `trades`，你可以通过环境变量快速调节成交节奏：

- **成交强度**：`PMM_PAPER_FILL_INTENSITY`（越大成交越多）
- **深度自适应**：`PMM_PAPER_INTENSITY_ADAPT=true`，并可用分位数自动标定 `PMM_PAPER_DEPTH_REF_MODE=quantile`
- **partial 比例与分布**：`PMM_PAPER_FULL_FILL_PROB`、`PMM_PAPER_PARTIAL_BETA_*`、`PMM_PAPER_PARTIAL_MIN/MAX_FRAC`
- **markout 波动**：`PMM_PAPER_MARKOUT_SIGMA_BPS`（常用 20 或 50）

## 3) 实盘

确保你已填写 `.env` 中的 L2 creds（用于 user tape），并确认风控参数。

```bash
pmm run live
```

### 3.1 仪表盘刷新
仪表盘默认 1 秒刷新一次：`PMM_DASHBOARD_REFRESH_SEC=1.0`（可配置）。

## 4) 资金分配（Capital Allocation Optimizer）

默认开启：`PMM_ENABLE_ALLOCATOR=true`

核心思想：
- 全局预算：`min(PMM_MAX_GROSS_USD, PMM_STARTING_CASH)`
- 逐市场预算：按 `liquidity^p` 与 “质量项（基于 fills/quotes/markout）” 加权分配
- 强制 min/max：
  - `PMM_MIN_USD_PER_MARKET`
  - `PMM_MAX_USD_PER_MARKET`

参数：
- `PMM_ALLOC_LIQUIDITY_POWER`（默认 0.5 = sqrt）
- `PMM_ALLOC_QUALITY_K`（默认 2.0：对负 markout 的惩罚强度）

分配结果会写回 `market_calibration.max_usd`，从而直接影响挂单 size。
