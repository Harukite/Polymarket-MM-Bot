# Risk & Circuit Breaker (v3)

## Why

实盘最常见的亏损路径不是“策略预测错”，而是：
- 订单跨价吃单（taker）导致负 markout
- 撤单风暴 / 连接抖动导致重复下单
- 拒单率异常（tick/min size/跨价/post-only）却仍然持续发送请求

## Circuit Breaker (默认)

- reject_rate >= 30% 且 placed>=20 => HALT
- cancels > 120 / minute => HALT
- errors >= 10 => HALT

熔断事件会写入 `risk_events` 表，并停止进程。
