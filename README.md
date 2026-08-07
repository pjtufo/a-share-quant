# 中国A股 + 港股 量化交易工具

一个轻量级、零密钥、开箱即用的 A 股 / 港股量化回测工具。支持多策略、多股对比、参数优化、风控和 CSV 导出。

## 功能特性

- **5 种内置策略**：双均线、MACD、布林带、RSI、海龟策略
- **A 股 + 港股**：自动识别市场，腾讯 ifzq 免费数据源，无需 API Key
- **回测引擎**：含佣金、印花税、滑点，整手/碎股适配
- **风控模块**：止损、止盈、最大回撤熔断、ATR 动态仓位
- **参数优化**：网格搜索最优参数组合，按 Sharpe / 收益率 / 最大回撤排序
- **多股对比**：一次回测 N 只股票，输出净值曲线 + 绩效汇总
- **数据导出**：CSV（净值曲线、交易记录、绩效指标）
- **可视化**：自动生成 PNG 图表（价格 + 买卖点、净值曲线、回撤）

## 环境要求

- Python 3.10+
- pandas、numpy、matplotlib、requests

安装依赖：

```bash
pip install pandas numpy matplotlib requests
```

## 快速开始

### 单股回测（双均线）

```bash
python quant.py --code 600519 --strategy dual_ma
```

### 指定均线参数

```bash
python quant.py --code 000858 --strategy dual_ma --short 10 --long 30
```

### 带止损止盈 + 导出

```bash
python quant.py --code 000001 --strategy rsi --stop -0.05 --take 0.15 --export
```

### 多股对比

```bash
python quant.py --code 000001,600519,000858 --compare
```

### 参数优化（网格搜索）

```bash
python quant.py --code 000001 --strategy dual_ma --optimize --metric Sharpe
```

### 海龟策略 + ATR 仓位管理

```bash
python quant.py --code 000858 --strategy turtle --atr-size
```

## 策略说明

| 策略 | 参数 | 逻辑 |
|---|---|---|
| `dual_ma` | `--short` `--long` | MA_short > MA_long 持仓，否则空仓 |
| `macd` | `--macd-fast` `--macd-slow` `--macd-sig` | DIF > DEA 持仓，否则空仓 |
| `boll` | `--boll-n` `--boll-k` | 收盘价跌破下轨买入，突破上轨卖出 |
| `rsi` | `--rsi-n` `--rsi-buy` `--rsi-sell` | RSI < buy_level 买入，> sell_level 卖出 |
| `turtle` | `--turtle-entry` `--turtle-exit` `--atr-n` `--atr-mult` | N日突破入场/出场，ATR 仓位管理 |

## 风控参数

```bash
--stop -0.05           # 亏损 5% 强制平仓
--take 0.15            # 盈利 15% 强制平仓
--max-dd 0.20          # 回撤 20% 熔断，停止交易
--atr-size             # 启用 ATR 动态仓位（海龟式）
--atr-risk 0.01        # 单笔风险比例（默认 1%）
```

## 市场适配

| 市场 | 识别方式 | 佣金 | 印花税 | 交易单位 |
|---|---|---|---|---|
| A股 | 6/3/0 开头（非0开头5位） | 万 2.5 | 千 5（仅卖出） | 100 股/手 |
| 港股 | 0 开头 5 位 / hk 前缀 | 万 2.5 | 0 | 1 股（碎股） |

## 输出说明

运行后会在当前目录生成：

- `{code}_{strategy}_{start}_{end}.png` — 回测图表
- `{code}_{strategy}_equity.csv` — 每日净值曲线
- `{code}_{strategy}_trades.csv` — 交易记录（含盈亏）
- `{code}_{strategy}_metrics.csv` — 绩效指标
- `compare_{strategy}_summary.csv` — 多股对比汇总（`--compare` 时）
- `optimize_{strategy}_{code}.csv` — 参数优化结果（`--optimize` 时）

## 注意事项

- 数据源为腾讯 ifzq 公开接口（免费），不做任何商业保证
- 港股数据通过 ifzq 的 `hk{code}` 格式获取，历史长度受接口限制
- 回测结果仅供参考，不构成投资建议
- 参数优化存在过拟合风险，实盘前请用样本外数据验证

## License

MIT
