#!/usr/bin/env python3
"""
中国A股 + 港股 量化交易工具 v3
================================
支持：
  1. 多策略：双均线 / MACD / 布林带 / RSI / 海龟
  2. 多股对比
  3. 参数优化（网格搜索）
  4. 风控：止损 / 止盈 / 回撤熔断 / ATR仓位
  5. 数据导出 CSV
  6. 港股支持（00518.HK 等），自动适配港股规则

用法：
  # A股
  python quant.py --code 600519 --strategy dual_ma
  # 港股（自动识别）
  python quant.py --code 00518 --strategy dual_ma
  python quant.py --code 00700 --strategy turtle
  # 多股对比
  python quant.py --code 000001,600519 --compare
"""

import argparse
import datetime as dt
import itertools
import json
import os
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC"]
plt.rcParams["axes.unicode_minus"] = False

# ──────────────────────────────────────────────────────────────
# 数据层
# ──────────────────────────────────────────────────────────────
def _is_hk(code: str) -> bool:
    code = code.strip().lower()
    if code.startswith("hk") or code.startswith("0") and len(code) == 5 and code.startswith("0"):
        return True
    return False


def _market(code: str) -> tuple:
    """返回 (exchange, clean_code, is_hk)
    支持显式前缀：
      sh:600519 / sz:000001 / hk:00518
    隐式推断：
      6xx / 9xx -> sh
      0xx / 3xx -> sz
      5 位 0 开头 -> hk（港股）
    """
    code = code.strip()
    if ":" in code:
        prefix, code_clean = code.split(":", 1)
        prefix = prefix.lower()
        if prefix == "hk":
            return "hk", code_clean, True
        if prefix == "sh":
            return "sh", code_clean, False
        if prefix == "sz":
            return "sz", code_clean, False
        raise ValueError(f"未知市场前缀: {prefix}")
    code_clean = code
    if code_clean.startswith("hk"):
        return "hk", code_clean[2:], True
    if len(code_clean) == 5 and code_clean.startswith("0"):
        return "hk", code_clean, True
    if code_clean.startswith(("6", "9")):
        return "sh", code_clean, False
    return "sz", code_clean, False


def _fetch_chunk_tencent(symbol: str, beg: str, end: str, count: int = 1000) -> list:
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,{beg},{end},{count},qfq"
    )
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://gu.qq.com/",
    }, timeout=15)
    r.raise_for_status()
    jd = r.json()
    data = jd.get("data")
    if isinstance(data, dict):
        inner = data.get(symbol, {})
        if isinstance(inner, dict):
            return inner.get("qfqday") or inner.get("day") or []
        return []
    elif isinstance(data, list):
        return data
    return []


def fetch_data(code: str, start: str, end: str, retries: int = 3) -> pd.DataFrame:
    exchange, code_clean, is_hk = _market(code)

    if is_hk:
        # 用腾讯 ifzq 获取港股日线（前复权）
        symbol = f"hk{code_clean}"
        print(f"[数据] 正在获取港股 {code_clean}.HK 日线: {start} ~ {end}")
        start_dt = dt.datetime.strptime(start, "%Y-%m-%d")
        end_dt = dt.datetime.strptime(end, "%Y-%m-%d")
        chunks = []
        cur = start_dt
        while cur <= end_dt:
            nxt = min(dt.datetime(cur.year + 1, 1, 1), end_dt + dt.timedelta(days=1))
            beg = cur.strftime("%Y-%m-%d")
            ed = (nxt - dt.timedelta(days=1)).strftime("%Y-%m-%d")
            last_err = None
            for attempt in range(retries):
                try:
                    chunks.extend(_fetch_chunk_tencent(symbol, beg, ed, count=1000))
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(2)
            if last_err:
                print(f"  [数据] {beg}~{ed} 失败: {last_err}")
            cur = nxt
        seen = set()
        rows = []
        for k in chunks:
            ds = k[0]
            if ds in seen:
                continue
            seen.add(ds)
            rows.append({"date": pd.to_datetime(ds), "open": float(k[1]), "close": float(k[2]),
                          "high": float(k[3]), "low": float(k[4]), "volume": float(k[5])})
        if not rows:
            print(f"[数据] 未获取到港股 {code_clean} 的数据。")
            sys.exit(1)
        df = pd.DataFrame(rows)
        df.sort_values("date", inplace=True)
        df.drop_duplicates(subset=["date"], keep="first", inplace=True)
        df.reset_index(drop=True, inplace=True)
        print(f"[数据] {code_clean}.HK 前复权日线: {len(df)} 条 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
        return df

    # A股：腾讯 ifzq
    symbol = f"{exchange}{code_clean}"
    start_dt = dt.datetime.strptime(start, "%Y-%m-%d")
    end_dt = dt.datetime.strptime(end, "%Y-%m-%d")
    chunks = []
    cur = start_dt
    while cur <= end_dt:
        nxt = min(dt.datetime(cur.year + 1, 1, 1), end_dt + dt.timedelta(days=1))
        beg = cur.strftime("%Y-%m-%d")
        ed = (nxt - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        last_err = None
        for attempt in range(retries):
            try:
                chunks.extend(_fetch_chunk_tencent(symbol, beg, ed, count=1000))
                break
            except Exception as e:
                last_err = e
                time.sleep(2)
        if last_err:
            print(f"  [数据] {beg}~{ed} 失败: {last_err}")
        cur = nxt
    seen = set()
    rows = []
    for k in chunks:
        ds = k[0]
        if ds in seen:
            continue
        seen.add(ds)
        rows.append({"date": pd.to_datetime(ds), "open": float(k[1]), "close": float(k[2]),
                      "high": float(k[3]), "low": float(k[4]), "volume": float(k[5])})
    if not rows:
        print(f"[数据] 未获取到 {code_clean} 的数据。")
        sys.exit(1)
    df = pd.DataFrame(rows)
    df.sort_values("date", inplace=True)
    df.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"[数据] {symbol} 前复权日线: {len(df)} 条 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
    return df


# ──────────────────────────────────────────────────────────────
# 指标计算
# ──────────────────────────────────────────────────────────────
def add_ma(df, short, long):
    df[f"ma{short}"] = df["close"].rolling(short).mean()
    df[f"ma{long}"] = df["close"].rolling(long).mean()
    return df


def add_macd(df, fast=12, slow=26, sig=9):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=sig, adjust=False).mean()
    df["macd_hist"] = 2 * (df["dif"] - df["dea"])
    return df


def add_boll(df, n=20, k=2):
    df["boll_mid"] = df["close"].rolling(n).mean()
    std = df["close"].rolling(n).std()
    df["boll_up"] = df["boll_mid"] + k * std
    df["boll_dn"] = df["boll_mid"] - k * std
    return df


def add_rsi(df, n=14):
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - 100 / (1 + rs)
    return df


def add_atr(df, n=14):
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=n, adjust=False).mean()
    return df


# ──────────────────────────────────────────────────────────────
# 策略信号
# ──────────────────────────────────────────────────────────────
def signal_dual_ma(df, short=5, long=20):
    add_ma(df, short, long)
    df["signal"] = (df[f"ma{short}"] > df[f"ma{long}"]).astype(int)
    df["trade"] = df["signal"].diff().fillna(0)
    df.loc[df["trade"] == 1, "trade"] = 1
    df.loc[df["trade"] == -1, "trade"] = -1
    return df


def signal_macd(df, fast=12, slow=26, sig=9):
    add_macd(df, fast, slow, sig)
    df["signal"] = (df["dif"] > df["dea"]).astype(int)
    df["trade"] = df["signal"].diff().fillna(0)
    df.loc[df["trade"] == 1, "trade"] = 1
    df.loc[df["trade"] == -1, "trade"] = -1
    return df


def signal_boll(df, n=20, k=2):
    add_boll(df, n, k)
    df["signal"] = 0
    df.loc[df["close"] < df["boll_dn"], "signal"] = 1
    df.loc[df["close"] > df["boll_up"], "signal"] = 0
    df["signal"] = df["signal"].replace(0, np.nan).ffill().fillna(0).astype(int)
    df["trade"] = df["signal"].diff().fillna(0)
    df.loc[df["trade"] == 1, "trade"] = 1
    df.loc[df["trade"] == -1, "trade"] = -1
    return df


def signal_rsi(df, n=14, buy_level=30, sell_level=70):
    add_rsi(df, n)
    df["signal"] = 0
    df.loc[df["rsi"] < buy_level, "signal"] = 1
    df.loc[df["rsi"] > sell_level, "signal"] = 0
    df["signal"] = df["signal"].replace(0, np.nan).ffill().fillna(0).astype(int)
    df["trade"] = df["signal"].diff().fillna(0)
    df.loc[df["trade"] == 1, "trade"] = 1
    df.loc[df["trade"] == -1, "trade"] = -1
    return df


def signal_turtle(df, entry_n=20, exit_n=10, atr_n=14, atr_mult=2.0):
    add_atr(df, atr_n)
    df["high_n"] = df["high"].rolling(entry_n).max().shift(1)
    df["low_n"] = df["low"].rolling(exit_n).min().shift(1)
    df["signal"] = 0
    df.loc[df["close"] > df["high_n"], "signal"] = 1
    df.loc[df["close"] < df["low_n"], "signal"] = 0
    df["signal"] = df["signal"].replace(0, np.nan).ffill().fillna(0).astype(int)
    df["trade"] = df["signal"].diff().fillna(0)
    df.loc[df["trade"] == 1, "trade"] = 1
    df.loc[df["trade"] == -1, "trade"] = -1
    df["atr_mult"] = atr_mult
    return df


STRATEGY_MAP = {
    "dual_ma": signal_dual_ma,
    "macd": signal_macd,
    "boll": signal_boll,
    "rsi": signal_rsi,
    "turtle": signal_turtle,
}


# ──────────────────────────────────────────────────────────────
# 风控
# ──────────────────────────────────────────────────────────────
def apply_stop_loss_take_profit(entry_price, current_price, stop_pct, take_pct):
    pnl_pct = (current_price - entry_price) / entry_price
    if stop_pct is not None and pnl_pct <= stop_pct:
        return True, "stop_loss"
    if take_pct is not None and pnl_pct >= take_pct:
        return True, "take_profit"
    return False, None


def atr_position_size(capital, price, atr, atr_mult=2.0, risk_pct=0.01, min_lots=100):
    if pd.isna(atr) or atr <= 0:
        return 0
    n = atr * atr_mult
    shares = int((capital * risk_pct) / n / min_lots) * min_lots
    return max(shares, 0)


# ──────────────────────────────────────────────────────────────
# 回测引擎
# ──────────────────────────────────────────────────────────────
def backtest(
    df: pd.DataFrame,
    initial_capital: float = 100_000,
    commission: float = 0.00025,
    stamp_tax: float = 0.0005,   # A股千5（仅卖出）；港股设为0
    slippage: float = 0.001,
    min_lots: int = 100,        # A股100股/手；港股可设1（碎股）
    stop_pct: float = None,
    take_pct: float = None,
    max_drawdown_pct: float = None,
    use_atr_sizing: bool = False,
    atr_risk_pct: float = 0.01,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    capital = initial_capital
    shares = 0
    cost_price = 0.0
    equity_list = []
    trades = []
    drawdown_paused = False

    for _, row in df.iterrows():
        price = row["close"]
        trade = row.get("trade", 0)
        atr = row.get("atr", np.nan)

        # 止损/止盈
        if shares > 0:
            force_close, reason = apply_stop_loss_take_profit(cost_price, price, stop_pct, take_pct)
            if force_close:
                sell_price = round(price * (1 - slippage), 4)
                revenue = shares * sell_price
                fee = revenue * (commission + stamp_tax)
                net = revenue - fee
                pnl = net - shares * cost_price
                capital += net
                trades.append({"date": row["date"], "type": f"SELL({reason})",
                               "price": sell_price, "shares": shares,
                               "amount": round(revenue, 2), "fee": round(fee, 2), "pnl": round(pnl, 2)})
                shares = 0
                cost_price = 0.0
                drawdown_paused = False
                equity_list.append({"date": row["date"], "equity": capital + shares * price})
                continue

        # 最大回撤熔断
        if max_drawdown_pct is not None and not drawdown_paused:
            equity_so_far = capital + shares * price
            peak = max((e["equity"] for e in equity_list), default=initial_capital)
            dd = (peak - equity_so_far) / peak if peak > 0 else 0
            if dd >= max_drawdown_pct:
                drawdown_paused = True
                if shares > 0:
                    sell_price = round(price * (1 - slippage), 4)
                    revenue = shares * sell_price
                    fee = revenue * (commission + stamp_tax)
                    net = revenue - fee
                    pnl = net - shares * cost_price
                    capital += net
                    trades.append({"date": row["date"], "type": "SELL(DRAWDOWN_STOP)",
                                   "price": sell_price, "shares": shares,
                                   "amount": round(revenue, 2), "fee": round(fee, 2), "pnl": round(pnl, 2)})
                    shares = 0
                    cost_price = 0.0

        if drawdown_paused:
            equity_list.append({"date": row["date"], "equity": capital + shares * price})
            continue

        # 买入
        if trade == 1 and shares == 0:
            if use_atr_sizing and not pd.isna(atr) and atr > 0:
                max_shares = atr_position_size(capital, price, atr, risk_pct=atr_risk_pct, min_lots=min_lots)
            else:
                buy_price = round(price * (1 + slippage), 4)
                max_shares = int(capital / buy_price / min_lots) * min_lots
            if max_shares > 0:
                buy_price = round(price * (1 + slippage), 4)
                amount = max_shares * buy_price
                fee = amount * commission
                total = amount + fee
                if total <= capital:
                    shares = max_shares
                    cost_price = buy_price
                    capital -= total
                    trades.append({"date": row["date"], "type": "BUY", "price": buy_price,
                                   "shares": shares, "amount": round(amount, 2), "fee": round(fee, 2)})

        # 卖出
        elif trade == -1 and shares > 0:
            sell_price = round(price * (1 - slippage), 4)
            revenue = shares * sell_price
            fee = revenue * (commission + stamp_tax)
            net = revenue - fee
            pnl = net - shares * cost_price
            capital += net
            trades.append({"date": row["date"], "type": "SELL", "price": sell_price,
                           "shares": shares, "amount": round(revenue, 2), "fee": round(fee, 2), "pnl": round(pnl, 2)})
            shares = 0
            cost_price = 0.0

        equity_list.append({"date": row["date"], "equity": capital + shares * price})

    df["equity"] = [e["equity"] for e in equity_list]
    df["drawdown"] = (df["equity"].cummax() - df["equity"]) / df["equity"].cummax()
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    metrics = _compute_metrics(df, initial_capital, trades_df)
    return df, metrics, trades_df


def _compute_metrics(df, initial_capital, trades):
    equity = df["equity"]
    final = float(equity.iloc[-1])
    days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
    years = max(days / 365.25, 1e-9)
    total_ret = (final - initial_capital) / initial_capital * 100
    annual_ret = ((final / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    max_dd = float(((equity.cummax() - equity) / equity.cummax()).max()) * 100
    rets = equity.pct_change().dropna()
    vol = float(rets.std() * np.sqrt(252) * 100)
    rf = 0.025
    sharpe = (annual_ret / 100 - rf) / (vol / 100) if vol > 1e-9 else 0.0
    n_trades = len(trades)
    wins = int((trades["pnl"] > 0).sum()) if "pnl" in trades.columns and n_trades else 0
    win_rate = (wins / n_trades * 100) if n_trades else 0.0
    avg_pnl = float(trades["pnl"].mean()) if "pnl" in trades.columns and n_trades else 0.0
    return {
        "初始资金": f"{initial_capital:,.0f}",
        "最终资产": f"{final:,.0f}",
        "总收益率(%)": round(total_ret, 2),
        "年化收益率(%)": round(annual_ret, 2),
        "最大回撤(%)": round(max_dd, 2),
        "年化波动率(%)": round(vol, 2),
        "Sharpe": round(sharpe, 2),
        "交易次数": n_trades,
        "盈利次数": wins,
        "胜率(%)": round(win_rate, 1),
        "平均盈亏": f"{avg_pnl:.2f}",
        "回测天数": days,
    }


# ──────────────────────────────────────────────────────────────
# 可视化
# ──────────────────────────────────────────────────────────────
def plot_results(df, code, strategy_name, metrics, save_path=None):
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.suptitle(f"量化回测 — {code} | 策略: {strategy_name}", fontsize=15, fontweight="bold")
    ax1 = axes[0]
    ax1.plot(df["date"], df["close"], label="收盘价", color="#333", linewidth=1)
    if "ma5" in df.columns:
        ax1.plot(df["date"], df["ma5"], label="MA5", color="#FF6B6B", linewidth=1.1, alpha=0.8)
    if "ma20" in df.columns:
        ax1.plot(df["date"], df["ma20"], label="MA20", color="#4ECDC4", linewidth=1.1, alpha=0.8)
    if "boll_mid" in df.columns:
        ax1.plot(df["date"], df["boll_mid"], label="BOLL中轨", color="#aaa", linewidth=1, linestyle="--")
        ax1.plot(df["date"], df["boll_up"], label="BOLL上轨", color="#888", linewidth=0.8, linestyle="--")
        ax1.plot(df["date"], df["boll_dn"], label="BOLL下轨", color="#888", linewidth=0.8, linestyle="--")
    buys, sells = df[df["trade"] == 1], df[df["trade"] == -1]
    ax1.scatter(buys["date"], buys["close"], marker="^", color="red", s=100, zorder=5, label="买入")
    ax1.scatter(sells["date"], sells["close"], marker="v", color="green", s=100, zorder=5, label="卖出")
    ax1.set_ylabel("价格")
    ax1.legend(loc="best", fontsize=8)
    ax1.set_title("价格走势与交易信号", fontsize=11)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(df["date"], df["equity"], color="#2E86AB", linewidth=1.5)
    ax2.fill_between(df["date"], df["equity"], alpha=0.12, color="#2E86AB")
    ax2.set_ylabel("账户资产")
    ax2.set_title("策略净值曲线", fontsize=11)
    ax2.grid(True, alpha=0.3)

    ax3 = axes[2]
    ax3.fill_between(df["date"], df["drawdown"] * 100, color="#E74C3C", alpha=0.7)
    ax3.set_ylabel("回撤(%)")
    ax3.set_xlabel("日期")
    ax3.set_title("回撤曲线", fontsize=11)
    ax3.grid(True, alpha=0.3)

    info_text = "\n".join([f"{k}: {v}" for k, v in metrics.items()])
    fig.text(0.72, 0.90, "绩效指标", fontsize=12, fontweight="bold", transform=fig.transFigure)
    fig.text(0.72, 0.82, info_text, fontsize=9, family="monospace",
             verticalalignment="top", transform=fig.transFigure,
             bbox=dict(boxstyle="round,pad=0.6", facecolor="#f7f7f7", edgecolor="#ccc"))
    plt.tight_layout(rect=[0, 0, 0.68, 0.96])
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[输出] 图表已保存: {save_path}")
    plt.close()


def plot_compare(results: dict, save_path=None):
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))
    fig.suptitle("多股策略净值曲线对比", fontsize=15, fontweight="bold")
    colors = plt.cm.tab10.colors
    ax1 = axes[0]
    for idx, (code, (df, metrics)) in enumerate(results.items()):
        color = colors[idx % len(colors)]
        ax1.plot(df["date"], df["equity"], label=code, color=color, linewidth=1.5)
    ax1.set_ylabel("账户资产")
    ax1.set_title("净值曲线")
    ax1.legend(loc="best")
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    codes = list(results.keys())
    rets = [results[c][1]["总收益率(%)"] for c in codes]
    colors_bar = [colors[i % len(colors)] for i in range(len(codes))]
    bars = ax2.bar(codes, rets, color=colors_bar, alpha=0.8)
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_ylabel("总收益率(%)")
    ax2.set_title("总收益率对比")
    ax2.grid(True, alpha=0.3, axis="y")
    for bar, ret in zip(bars, rets):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + (1 if ret >= 0 else -3),
                 f"{ret:.1f}%", ha="center", va="bottom" if ret >= 0 else "top", fontsize=9)
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[输出] 对比图已保存: {save_path}")
    plt.close()


# ──────────────────────────────────────────────────────────────
# 参数优化
# ──────────────────────────────────────────────────────────────
def optimize_parameters(df, strategy_fn, param_grid, metric="Sharpe",
                        commission=0.00025, stamp_tax=0.0005, min_lots=100):
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    results = []
    for combo in itertools.product(*values):
        kwargs = dict(zip(keys, combo))
        try:
            df_sig = strategy_fn(df.copy(), **kwargs)
            indicator_cols = [c for c in df_sig.columns if c.startswith("ma") or c in
                              ("dif", "dea", "macd_hist", "boll_mid", "boll_up", "boll_dn", "rsi", "atr")]
            if indicator_cols:
                df_sig.dropna(subset=indicator_cols, inplace=True)
            df_sig.reset_index(drop=True, inplace=True)
            if len(df_sig) < 5:
                continue
            _, metrics, _ = backtest(df_sig, commission=commission, stamp_tax=stamp_tax, min_lots=min_lots)
            row = {**kwargs, **metrics}
            results.append(row)
        except Exception:
            continue
    if not results:
        print("[优化] 未得到有效结果。")
        return pd.DataFrame()
    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values(metric, ascending=False).reset_index(drop=True)
    return result_df


# ──────────────────────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────────────────────
def export_results(df, trades_df, metrics, code, strategy_name, export_dir="."):
    os.makedirs(export_dir, exist_ok=True)
    prefix = f"{code}_{strategy_name}"
    equity_path = os.path.join(export_dir, f"{prefix}_equity.csv")
    df[["date", "close", "equity", "drawdown"]].to_csv(equity_path, index=False, encoding="utf-8-sig")
    if not trades_df.empty:
        trades_path = os.path.join(export_dir, f"{prefix}_trades.csv")
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
    metrics_path = os.path.join(export_dir, f"{prefix}_metrics.csv")
    pd.DataFrame([metrics]).to_csv(metrics_path, index=False, encoding="utf-8-sig")
    print(f"[导出] 净值曲线: {equity_path}")
    if not trades_df.empty:
        print(f"[导出] 交易记录: {trades_path}")
    print(f"[导出] 绩效指标: {metrics_path}")


# ──────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────
def run_single(args):
    df = fetch_data(args.code, args.start, args.end)
    exchange, code_clean, is_hk = _market(args.code)

    # 港股默认参数
    if is_hk:
        commission = args.commission  # 默认万2.5
        stamp_tax = 0.0              # 港股无印花税（简化）
        min_lots = 1                 # 港股支持碎股
        print(f"[市场] {code_clean}.HK — 港股模式（佣金万2.5, 印花税0, 碎股交易）")
    else:
        commission = args.commission
        stamp_tax = 0.0005
        min_lots = 100
        print(f"[市场] {code_clean} — A股模式（佣金万2.5, 印花税千5, 整手）")

    strategy_fn = STRATEGY_MAP.get(args.strategy)
    if not strategy_fn:
        print(f"[错误] 未知策略: {args.strategy}")
        sys.exit(1)

    strat_kwargs = {}
    if args.strategy == "dual_ma":
        strat_kwargs = {"short": args.short, "long": args.long}
    elif args.strategy == "macd":
        strat_kwargs = {"fast": args.macd_fast, "slow": args.macd_slow, "sig": args.macd_sig}
    elif args.strategy == "boll":
        strat_kwargs = {"n": args.boll_n, "k": args.boll_k}
    elif args.strategy == "rsi":
        strat_kwargs = {"n": args.rsi_n, "buy_level": args.rsi_buy, "sell_level": args.rsi_sell}
    elif args.strategy == "turtle":
        strat_kwargs = {"entry_n": args.turtle_entry, "exit_n": args.turtle_exit,
                        "atr_n": args.atr_n, "atr_mult": args.atr_mult}

    df = strategy_fn(df, **strat_kwargs)
    indicator_cols = [c for c in df.columns if c.startswith("ma") or c in
                      ("dif", "dea", "macd_hist", "boll_mid", "boll_up", "boll_dn", "rsi", "atr", "high_n", "low_n")]
    if indicator_cols:
        df.dropna(subset=indicator_cols, inplace=True)
    df.reset_index(drop=True, inplace=True)

    if len(df) < 5:
        print("[警告] 数据不足（<5条），请扩大日期范围。")
        sys.exit(1)

    print(f"[策略] {args.strategy} {strat_kwargs}")
    df, metrics, trades = backtest(
        df, initial_capital=args.capital,
        commission=commission, stamp_tax=stamp_tax, min_lots=min_lots,
        stop_pct=args.stop, take_pct=args.take, max_drawdown_pct=args.max_dd,
        use_atr_sizing=args.atr_size, atr_risk_pct=args.atr_risk,
    )

    print("\n" + "=" * 55)
    print(f"          回测绩效报告 — {args.code}")
    print("=" * 55)
    for k, v in metrics.items():
        print(f"  {k:<16}: {v}")
    print("=" * 55)

    if not trades.empty:
        print("\n最近 5 笔交易:")
        print(trades.tail(5).to_string(index=False))

    save = args.save or f"{args.code.replace(':', '_')}_{args.strategy}_{args.start}_{args.end}.png"
    plot_results(df, args.code, args.strategy, metrics, save_path=save)

    if args.export:
        export_results(df, trades, metrics, args.code.replace(':', '_'), args.strategy)


def run_compare(args):
    codes = [c.strip() for c in args.code.split(",")]
    results = {}
    for code in codes:
        df = fetch_data(code, args.start, args.end)
        exchange, code_clean, is_hk = _market(code)
        if is_hk:
            commission, stamp_tax, min_lots = args.commission, 0.0, 1
        else:
            commission, stamp_tax, min_lots = args.commission, 0.0005, 100

        strategy_fn = STRATEGY_MAP.get(args.strategy, signal_dual_ma)
        strat_kwargs = {}
        if args.strategy == "dual_ma":
            strat_kwargs = {"short": args.short, "long": args.long}
        elif args.strategy == "macd":
            strat_kwargs = {"fast": args.macd_fast, "slow": args.macd_slow, "sig": args.macd_sig}
        elif args.strategy == "boll":
            strat_kwargs = {"n": args.boll_n, "k": args.boll_k}
        elif args.strategy == "rsi":
            strat_kwargs = {"n": args.rsi_n, "buy_level": args.rsi_buy, "sell_level": args.rsi_sell}
        elif args.strategy == "turtle":
            strat_kwargs = {"entry_n": args.turtle_entry, "exit_n": args.turtle_exit,
                            "atr_n": args.atr_n, "atr_mult": args.atr_mult}

        df = strategy_fn(df.copy(), **strat_kwargs)
        indicator_cols = [c for c in df.columns if c.startswith("ma") or c in
                          ("dif", "dea", "macd_hist", "boll_mid", "boll_up", "boll_dn", "rsi", "atr", "high_n", "low_n")]
        if indicator_cols:
            df.dropna(subset=indicator_cols, inplace=True)
        df.reset_index(drop=True, inplace=True)
        if len(df) < 5:
            print(f"[跳过] {code}: 数据不足")
            continue
        df, metrics, trades = backtest(df, initial_capital=args.capital,
                                       commission=commission, stamp_tax=stamp_tax, min_lots=min_lots,
                                       stop_pct=args.stop, take_pct=args.take,
                                       max_drawdown_pct=args.max_dd,
                                       use_atr_sizing=args.atr_size, atr_risk_pct=args.atr_risk)
        results[code] = (df, metrics)
        print(f"  {code}: 总收益率={metrics['总收益率(%)']}%  Sharpe={metrics['Sharpe']}  最大回撤={metrics['最大回撤(%)']}%")

    if not results:
        print("[比较] 无有效结果。")
        sys.exit(1)
    summary = pd.DataFrame({code: m for code, (_, m) in results.items()}).T
    print("\n" + "=" * 70)
    print("  多股对比汇总")
    print("=" * 70)
    print(summary.to_string())
    print("=" * 70)
    save = args.save or f"compare_{args.strategy}_{args.start}_{args.end}.png"
    plot_compare(results, save_path=save)
    if args.export:
        summary.to_csv(f"compare_{args.strategy}_summary.csv", encoding="utf-8-sig")
        print(f"[导出] 汇总表: compare_{args.strategy}_summary.csv")


def run_optimize(args):
    df = fetch_data(args.code, args.start, args.end)
    exchange, code_clean, is_hk = _market(args.code)
    if is_hk:
        commission, stamp_tax, min_lots = args.commission, 0.0, 1
    else:
        commission, stamp_tax, min_lots = args.commission, 0.0005, 100

    strategy_fn = STRATEGY_MAP.get(args.strategy, signal_dual_ma)
    if args.strategy == "dual_ma":
        param_grid = {"short": list(range(3, 21, 2)), "long": list(range(20, 81, 10))}
    elif args.strategy == "macd":
        param_grid = {"fast": [8, 12, 16], "slow": [20, 26, 32], "sig": [7, 9, 12]}
    elif args.strategy == "boll":
        param_grid = {"n": [15, 20, 25, 30], "k": [1.5, 2.0, 2.5]}
    elif args.strategy == "rsi":
        param_grid = {"n": [6, 14, 21], "buy_level": [20, 30], "sell_level": [70, 80]}
    else:
        print(f"[优化] 策略 {args.strategy} 暂不支持参数优化。")
        sys.exit(1)

    print(f"[优化] 正在网格搜索 {args.strategy} 参数，按 {args.metric} 排序...")
    result_df = optimize_parameters(df, strategy_fn, param_grid, metric=args.metric,
                                     commission=commission, stamp_tax=stamp_tax, min_lots=min_lots)
    if result_df.empty:
        sys.exit(1)
    print(f"\n[优化] Top 10 参数组合（按 {args.metric} 降序）：")
    show_cols = list(param_grid.keys()) + ["总收益率(%)", "最大回撤(%)", "Sharpe", "交易次数", "胜率(%)"]
    show_cols = [c for c in show_cols if c in result_df.columns]
    print(result_df[show_cols].head(10).to_string(index=False))
    if args.export:
        result_df.to_csv(f"optimize_{args.strategy}_{args.code}.csv", index=False, encoding="utf-8-sig")
        print(f"[导出] 优化结果: optimize_{args.strategy}_{args.code}.csv")


def main():
    parser = argparse.ArgumentParser(description="中国A股 + 港股 量化交易工具")
    parser.add_argument("--code", required=True, help="股票代码，如 600519 / 00518 / 000001,600519,00518")
    parser.add_argument("--start", default="2020-01-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--strategy", default="dual_ma",
                        choices=["dual_ma", "macd", "boll", "rsi", "turtle"])
    parser.add_argument("--capital", type=float, default=100_000, help="初始资金（默认 10 万）")
    parser.add_argument("--save", default=None, help="保存图表路径")
    parser.add_argument("--export", action="store_true", help="导出 CSV")
    parser.add_argument("--commission", type=float, default=0.00025, help="佣金率（默认万2.5）")
    parser.add_argument("--short", type=int, default=5)
    parser.add_argument("--long", type=int, default=20)
    parser.add_argument("--macd-fast", type=int, default=12)
    parser.add_argument("--macd-slow", type=int, default=26)
    parser.add_argument("--macd-sig", type=int, default=9)
    parser.add_argument("--boll-n", type=int, default=20)
    parser.add_argument("--boll-k", type=float, default=2.0)
    parser.add_argument("--rsi-n", type=int, default=14)
    parser.add_argument("--rsi-buy", type=int, default=30)
    parser.add_argument("--rsi-sell", type=int, default=70)
    parser.add_argument("--turtle-entry", type=int, default=20)
    parser.add_argument("--turtle-exit", type=int, default=10)
    parser.add_argument("--atr-n", type=int, default=14)
    parser.add_argument("--atr-mult", type=float, default=2.0)
    parser.add_argument("--stop", type=float, default=None, help="止损比例，如 -0.05")
    parser.add_argument("--take", type=float, default=None, help="止盈比例，如 0.10")
    parser.add_argument("--max-dd", type=float, default=None, help="最大回撤熔断，如 0.20")
    parser.add_argument("--atr-size", action="store_true", help="启用 ATR 动态仓位")
    parser.add_argument("--atr-risk", type=float, default=0.01, help="单笔风险比例（默认 1%）")
    parser.add_argument("--optimize", action="store_true", help="网格搜索最优参数")
    parser.add_argument("--metric", default="Sharpe", choices=["Sharpe", "总收益率(%)", "最大回撤(%)"])
    parser.add_argument("--compare", action="store_true", help="多股对比模式")
    args = parser.parse_args()
    if args.end is None:
        args.end = dt.date.today().strftime("%Y-%m-%d")
    if args.compare:
        run_compare(args)
    elif args.optimize:
        run_optimize(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
