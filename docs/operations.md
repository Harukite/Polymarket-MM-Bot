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

## 3) 实盘

确保你已填写 `.env` 中的 L2 creds（用于 user tape），并确认风控参数。

```bash
pmm run live
```

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
