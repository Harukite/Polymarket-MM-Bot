# Risk & Circuit Breaker (v3)

## Why

实盘最常见的亏损路径不是“策略预测错”，而是：
- 订单跨价吃单（taker）导致负 markout
- 撤单风暴 / 连接抖动导致重复下单
- 拒单率异常（tick/min size/跨价/post-only）却仍然持续发送请求

## Circuit Breaker (默认)

- reject_rate >= 30% 且 placed>=20 => HALT
- cancels > 120 / minute => HALT（实盘默认）
- errors >= 10 => HALT

熔断事件会写入 `risk_events` 表，并停止进程。

## 配置项（环境变量）
本项目支持从环境变量覆盖熔断阈值：

- `PMM_CB_MAX_REJECT_RATE`（默认 0.30）
- `PMM_CB_WINDOW_SEC`（默认 300）
- `PMM_CB_MAX_ERRORS`（默认 10）
- `PMM_CB_MAX_CANCELS_PER_MIN`（实盘默认 120）
- `PMM_CB_MAX_CANCELS_PER_MIN_PAPER`（paper/dry-run 默认 10000）

> 说明：paper/dry-run 会频繁“撤旧挂新”用于研究复盘，默认把撤单熔断阈值放宽，避免误触发 HALT；实盘建议保持严格阈值。
