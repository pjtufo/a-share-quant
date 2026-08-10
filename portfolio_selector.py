#!/usr/bin/env python3
"""
一揽子股票选股组合分析系统 v2
==============================
功能：
  1. 股票池：10只左右，支持自选/自动扩展
  2. 宏观评分：PMI、M2、CPI/PPI、Shibor、地缘政治新闻
  3. 政策评分：北向资金、融资融券余额
  4. 个股评分：趋势、MACD、RSI、量价、波动率
  5. 组合构建：评分加权 + 风险平价
  6. 回测复盘：周度/月度调仓，2020-2024
  7. 盈利目标：创业板 + 20% Alpha
  8. 新闻监控：地缘政治/战争实时监测
  9. 报告输出：Markdown + PNG + CSV

用法：
  # 回测
  python portfolio_selector.py --mode backtest --pool sh.600519,sz.000858,sh.600036,sz.000333,sh.600276
  # 当前报告
  python portfolio_selector.py --mode report --pool sh.600519,sz.000858,sh.600036,sz.000333,sh.600276
  # 新闻监控
  python portfolio_selector.py --mode news
"""

import argparse
import datetime as dt
import os
import re
import sys
import time
import warnings

import numpy as np
import pandas as pd
import requests
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC"]
plt.rcParams["axes.unicode_minus"] = False

# ──────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────
DEFAULT_POOL = [
    "sh.600519", "sz.000858", "sh.600036", "sz.000333",
    "sh.600276", "sz.002415", "sz.000725", "sh.601012",
    "sh.600585", "sh.601899", "hk.00700", "hk.00941",
]

GEOPOLITICAL_KEYWORDS = [
    "战争", "冲突", "制裁", "关税", "贸易战", "军事打击",
    "地缘政治", "北约", "俄罗斯", "乌克兰", "中东",
    "台湾", "南海", "朝鲜", "伊朗", "以色列",
    "供应链", "脱钩", "技术封锁", "出口管制",
]

# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────
def _is_hk(code: str) -> bool:
    if "." in code:
        return code.split(".")[0].lower() == "hk"
    if code.startswith("hk"):
        return True
    if len(code) == 5 and code.startswith("0"):
        return True
    return False


def _clean_code(code: str) -> str:
    if "." in code:
        return code.split(".", 1)[1]
    if code.startswith("hk"):
        return code[2:]
    return code


def _exchange(code: str) -> str:
    if "." in code:
        return code.split(".")[0].lower()
    c = _clean_code(code)
    if c.startswith(("6", "9")):
        return "sh"
    return "sz"


def fetch_price(code: str, start: str, end: str) -> pd.DataFrame:
    """获取日线数据"""
    import akshare as ak
    clean = _clean_code(code)
    is_hk = _is_hk(code)

    if is_hk:
        for attempt in range(3):
            try:
                df = ak.stock_hk_hist(symbol=clean, period="daily",
                                       start_date=start.replace("-", ""),
                                       end_date=end.replace("-", ""),
                                       adjust="qfq")
                if df is not None and not df.empty:
                    df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                       "最高": "high", "最低": "low", "成交量": "volume"}, inplace=True)
                    df["date"] = pd.to_datetime(df["date"])
                    df.sort_values("date", inplace=True)
                    df.reset_index(drop=True, inplace=True)
                    return df
            except Exception:
                if attempt < 2:
                    time.sleep(2)
        return pd.DataFrame()

    ex = _exchange(code)
    symbol = f"{ex}{clean}"
    chunks = []
    cur = dt.datetime.strptime(start, "%Y-%m-%d")
    end_dt = dt.datetime.strptime(end, "%Y-%m-%d")
    while cur <= end_dt:
        nxt = min(dt.datetime(cur.year + 1, 1, 1), end_dt + dt.timedelta(days=1))
        beg = cur.strftime("%Y-%m-%d")
        ed = (nxt - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        for attempt in range(3):
            try:
                url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                       f"?param={symbol},day,{beg},{ed},1000,qfq")
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
                                  timeout=15)
                r.raise_for_status()
                jd = r.json()
                data = jd.get("data")
                if isinstance(data, dict):
                    inner = data.get(symbol, {})
                    klines = inner.get("qfqday") or inner.get("day") or [] if isinstance(inner, dict) else []
                elif isinstance(data, list):
                    klines = data
                else:
                    klines = []
                chunks.extend(klines)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(2)
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
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.sort_values("date", inplace=True)
    df.drop_duplicates(subset=["date"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ──────────────────────────────────────────────────────────────
# 宏观数据层
# ──────────────────────────────────────────────────────────────
def fetch_macro(start: str, end: str) -> dict[str, pd.DataFrame]:
    """获取宏观指标（akshare）"""
    results = {}
    try:
        import akshare as ak
        try:
            pmi = ak.macro_china_pmi()
            pmi["date"] = pd.to_datetime(pmi["月份"].str.replace("年", "-").str.replace("月份", ""), errors="coerce")
            pmi = pmi.dropna(subset=["date"])
            if not pmi.empty:
                results["PMI"] = pmi[["date", "制造业-指数"]].rename(columns={"制造业-指数": "PMI"})
        except Exception:
            pass
        try:
            m2 = ak.macro_china_m2_yearly()
            m2["date"] = pd.to_datetime(m2["日期"], errors="coerce")
            m2 = m2.dropna(subset=["date", "今值"])
            if not m2.empty:
                results["M2"] = m2[["date", "今值"]].rename(columns={"今值": "M2"})
        except Exception:
            pass
        try:
            cpi = ak.macro_china_cpi_yearly()
            cpi["date"] = pd.to_datetime(cpi["日期"], errors="coerce")
            cpi = cpi.dropna(subset=["date", "今值"])
            if not cpi.empty:
                results["CPI"] = cpi[["date", "今值"]].rename(columns={"今值": "CPI"})
        except Exception:
            pass
        try:
            ppi = ak.macro_china_ppi_yearly()
            ppi["date"] = pd.to_datetime(ppi["日期"], errors="coerce")
            ppi = ppi.dropna(subset=["date", "今值"])
            if not ppi.empty:
                results["PPI"] = ppi[["date", "今值"]].rename(columns={"今值": "PPI"})
        except Exception:
            pass
        try:
            shibor = ak.macro_china_shibor_all()
            shibor["date"] = pd.to_datetime(shibor["日期"], errors="coerce")
            shibor = shibor.dropna(subset=["date"])
            if not shibor.empty:
                results["Shibor"] = shibor[["date", "O/N-定价"]].rename(columns={"O/N-定价": "Shibor"})
        except Exception:
            pass
        try:
            north = ak.stock_hsgt_hist_em()
            north["date"] = pd.to_datetime(north["日期"], errors="coerce")
            north = north.dropna(subset=["date", "当日成交净买额"])
            if not north.empty:
                results["北向资金"] = north[["date", "当日成交净买额"]].rename(columns={"当日成交净买额": "north_flow"})
        except Exception:
            pass
    except Exception:
        pass
    return results


def fetch_news(max_items: int = 50) -> pd.DataFrame:
    """获取实时新闻"""
    news_list = []
    try:
        url = "https://www.cls.cn/nodeapi/updateTelegraphList"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cls.cn/"}
        resp = requests.post(url, headers=headers,
                             json={"app": "CailianpressWeb", "os": "web", "sv": "8.4.6",
                                   "rn": max_items, "page": 0},
                             timeout=15)
        data = resp.json()
        rolls = data.get("data", {}).get("roll_data", [])
        for item in rolls:
            content = item.get("title", "") + " " + item.get("content", "")
            news_list.append({"time": item.get("ctime", ""), "content": content, "source": "财联社"})
    except Exception:
        pass

    # 回退：腾讯新闻
    if len(news_list) < 5:
        try:
            resp = requests.get("https://news.qq.com/", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "utf-8"
            titles = re.findall(r'<h[12][^>]*>(.*?)</h[12]>', resp.text, re.DOTALL)
            for t in titles[:20]:
                clean = re.sub(r'<[^>]+>', '', t).strip()
                if clean and len(clean) > 5:
                    news_list.append({"time": "", "content": clean, "source": "腾讯新闻"})
        except Exception:
            pass

    df = pd.DataFrame(news_list)
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df


# ──────────────────────────────────────────────────────────────
# 宏观评分
# ──────────────────────────────────────────────────────────────
def score_macro(macro_data: dict[str, pd.DataFrame], news_df: pd.DataFrame) -> dict:
    """宏观因子评分"""
    signals = {}
    events = []

    # PMI
    if "PMI" in macro_data:
        pmi = macro_data["PMI"].sort_values("date", ascending=False)
        if not pmi.empty:
            pmi_now = pmi["PMI"].iloc[0]
            if not pd.isna(pmi_now):
                if pmi_now > 51:
                    signals["PMI"] = 1
                elif pmi_now < 49:
                    signals["PMI"] = -1
                else:
                    signals["PMI"] = 0
                events.append(f"PMI: {pmi_now:.1f} ({'扩张' if pmi_now > 50 else '收缩'})")

    # M2
    if "M2" in macro_data:
        m2 = macro_data["M2"].sort_values("date", ascending=False).dropna(subset=["M2"])
        if not m2.empty and len(m2) >= 2:
            m2_now = m2["M2"].iloc[0]
            m2_prev = m2["M2"].iloc[1]
            if m2_now > m2_prev:
                signals["M2"] = 0.5
            else:
                signals["M2"] = -0.5
            events.append(f"M2: {m2_now:.1f}% (环比{m2_now-m2_prev:+.1f})")

    # CPI/PPI
    if "CPI" in macro_data and "PPI" in macro_data:
        cpi = macro_data["CPI"].sort_values("date", ascending=False).dropna(subset=["CPI"])
        ppi = macro_data["PPI"].sort_values("date", ascending=False).dropna(subset=["PPI"])
        if not cpi.empty and not ppi.empty:
            cpi_now = cpi["CPI"].iloc[0]
            ppi_now = ppi["PPI"].iloc[0]
            spread = cpi_now - ppi_now
            if spread > 2:
                signals["CPI-PPI剪刀差"] = 0.5
            elif spread < -2:
                signals["CPI-PPI剪刀差"] = -0.5
            events.append(f"CPI: {cpi_now:.1f}%, PPI: {ppi_now:.1f}%, 剪刀差: {spread:.1f}")

    # Shibor
    if "Shibor" in macro_data:
        shibor = macro_data["Shibor"].sort_values("date", ascending=False).dropna(subset=["Shibor"])
        if not shibor.empty and len(shibor) >= 10:
            shibor_now = shibor["Shibor"].iloc[0]
            shibor_ma20 = shibor["Shibor"].rolling(20).mean().iloc[0]
            if not pd.isna(shibor_ma20):
                if shibor_now < shibor_ma20:
                    signals["Shibor"] = 0.5
                else:
                    signals["Shibor"] = -0.5
                events.append(f"Shibor O/N: {shibor_now:.2f}%")

    # 北向资金趋势
    if "北向资金" in macro_data:
        north = macro_data["北向资金"].sort_values("date", ascending=False).dropna(subset=["north_flow"])
        if not north.empty and len(north) >= 5:
            recent = north["north_flow"].head(5)
            if (recent > 0).all():
                signals["北向资金"] = 1
            elif (recent < 0).all():
                signals["北向资金"] = -1
            else:
                signals["北向资金"] = 0
            events.append(f"北向资金5日累计: {recent.sum()/1e8:.1f}亿元")

    # 地缘政治新闻
    if not news_df.empty:
        content_lower = " ".join(news_df["content"].astype(str).str.lower())
        geo_count = 0
        for kw in GEOPOLITICAL_KEYWORDS:
            if kw.lower() in content_lower:
                geo_count += 1
                events.append(f"地缘事件: {kw}")
        if geo_count >= 3:
            signals["地缘政治"] = -1
        elif geo_count >= 1:
            signals["地缘政治"] = -0.5
        else:
            signals["地缘政治"] = 0

    score = sum(signals.values()) / len(signals) if signals else 0.0
    # events 和 signals 可能重复，去重
    seen = set()
    unique_events = []
    for ev in events:
        if ev not in seen:
            seen.add(ev)
            unique_events.append(ev)
    return {"score": round(score, 3), "signals": signals, "events": unique_events}


# ──────────────────────────────────────────────────────────────
# 个股评分
# ──────────────────────────────────────────────────────────────
def score_stock(df: pd.DataFrame, code: str) -> dict:
    """个股综合评分"""
    if df.empty or len(df) < 30:
        return {"score": 0, "details": {}}

    close = df["close"]
    details = {}

    # 趋势
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    trend = 0.0
    if ma5.iloc[-1] > ma20.iloc[-1]:
        trend += 0.3
    if not pd.isna(ma60.iloc[-1]) and ma20.iloc[-1] > ma60.iloc[-1]:
        trend += 0.3
    if close.iloc[-1] > ma5.iloc[-1]:
        trend += 0.2
    details["趋势"] = round(trend, 2)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_score = 0.0
    if dif.iloc[-1] > dea.iloc[-1]:
        if dif.iloc[-2] <= dea.iloc[-2]:
            macd_score = 0.5
        else:
            macd_score = 0.2
    else:
        if dif.iloc[-2] >= dea.iloc[-2]:
            macd_score = -0.5
        else:
            macd_score = -0.2
    details["MACD"] = round(macd_score, 2)

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi_score = 0.0
    if rsi.iloc[-1] < 30:
        rsi_score = 0.3
    elif rsi.iloc[-1] > 70:
        rsi_score = -0.3
    elif 40 < rsi.iloc[-1] < 60:
        rsi_score = 0.1
    details["RSI"] = round(rsi_score, 2)

    # 量价
    vol_ma5 = df["volume"].rolling(5).mean()
    vol_score = 0.0
    if df["volume"].iloc[-1] > vol_ma5.iloc[-1] * 1.5 and close.iloc[-1] > close.iloc[-2]:
        vol_score = 0.3
    elif df["volume"].iloc[-1] > vol_ma5.iloc[-1] * 1.5 and close.iloc[-1] < close.iloc[-2]:
        vol_score = -0.3
    details["量价"] = round(vol_score, 2)

    # 波动率（低分高）
    ret = close.pct_change().dropna()
    vol = ret.rolling(20).std().iloc[-1] if len(ret) >= 20 else 0.3
    vol_score = max(0, 0.2 - vol * 10)
    details["波动率"] = round(vol_score, 2)

    total = sum(details.values())
    return {"score": round(total, 3), "details": details}


# ──────────────────────────────────────────────────────────────
# 组合构建
# ──────────────────────────────────────────────────────────────
def build_portfolio(scores: dict[str, float], prices: dict[str, float],
                    method: str = "评分加权", max_weight: float = 0.15) -> dict[str, float]:
    if not scores:
        return {}

    filtered = {k: v for k, v in scores.items() if v > 0 and k in prices}
    if not filtered:
        return {}

    codes = list(filtered.keys())

    if method == "评分加权":
        raw_weights = {k: max(0, filtered[k]) for k in codes}
        total = sum(raw_weights.values())
        if total == 0:
            return {}
        weights = {k: w / total for k, w in raw_weights.items()}
        for k in weights:
            weights[k] = min(weights[k], max_weight)
        total = sum(weights.values())
        if total > 0:
            weights = {k: w / total for k, w in weights.items()}
        return weights

    elif method == "风险平价":
        vols = {}
        for code in codes:
            try:
                end = dt.date.today().strftime("%Y-%m-%d")
                start = (dt.date.today() - dt.timedelta(days=60)).strftime("%Y-%m-%d")
                df = fetch_price(code, start, end)
                if not df.empty and len(df) >= 20:
                    ret = df["close"].pct_change().dropna()
                    vols[code] = ret.rolling(20).std().iloc[-1]
                else:
                    vols[code] = 0.3
            except Exception:
                vols[code] = 0.3
        inv_vol = {k: 1 / max(v, 0.01) for k, v in vols.items()}
        total_inv = sum(inv_vol.values())
        weights = {k: min(v / total_inv, max_weight) for k, v in inv_vol.items()}
        total = sum(weights.values())
        if total > 0:
            weights = {k: w / total for k, w in weights.items()}
        return weights

    return {}


# ──────────────────────────────────────────────────────────────
# 组合回测
# ──────────────────────────────────────────────────────────────
def backtest_portfolio(pool: list[str], start: str, end: str,
                       rebalance_freq: str = "W",
                       method: str = "评分加权",
                       initial_capital: float = 100_000,
                       commission: float = 0.00025,
                       stamp_tax: float = 0.0005) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    print(f"[回测] 组合: {len(pool)} 只, 调仓: {rebalance_freq}, 权重: {method}")

    all_data = {}
    for code in pool:
        df = fetch_price(code, start, end)
        if not df.empty and len(df) >= 60:
            all_data[code] = df
            print(f"  {code}: {len(df)} bars")
        else:
            print(f"  [跳过] {code}: 数据不足")

    if not all_data:
        return pd.DataFrame(), {}, pd.DataFrame()

    # 合并价格矩阵
    all_dates = sorted(set().union(*[set(df["date"]) for df in all_data.values()]))
    price_df = pd.DataFrame({"date": all_dates})
    for code, df in all_data.items():
        price_df = price_df.merge(df[["date", "close"]].rename(columns={"close": code}),
                                   on="date", how="left")
    price_df.sort_values("date", inplace=True)
    price_df.ffill(inplace=True)
    price_df.bfill(inplace=True)

    price_df["rebalance"] = price_df["date"].dt.weekday == 0 if rebalance_freq == "W" else price_df["date"].dt.is_month_start

    # 回测
    capital = initial_capital
    holdings = {code: 0 for code in all_data.keys()}
    equity_list = []
    trades = []

    for idx, row in price_df.iterrows():
        date = row["date"]
        current_value = capital + sum(holdings[code] * row[code] for code in holdings)
        equity_list.append({"date": date, "equity": current_value})

        if row["rebalance"]:
            # 评分
            scores = {}
            for code in all_data:
                score_result = score_stock(all_data[code][all_data[code]["date"] <= date], code)
                scores[code] = score_result["score"]

            prices = {code: row[code] for code in all_data}
            new_weights = build_portfolio(scores, prices, method=method)
            if not new_weights:
                continue

            target_shares = {}
            for code, w in new_weights.items():
                target_shares[code] = int(current_value * w / row[code] / 100) * 100

            for code in holdings:
                if holdings[code] > 0 and (code not in target_shares or target_shares[code] == 0):
                    sell_shares = holdings[code]
                    sell_price = row[code] * (1 - 0.001)
                    revenue = sell_shares * sell_price
                    fee = revenue * (commission + stamp_tax)
                    capital += revenue - fee
                    trades.append({"date": date, "code": code, "type": "SELL",
                                   "price": sell_price, "shares": sell_shares, "fee": fee})
                    holdings[code] = 0

            for code, target in target_shares.items():
                current_shares = holdings.get(code, 0)
                diff = target - current_shares
                if abs(diff) < 100:
                    continue
                if diff > 0:
                    buy_price = row[code] * (1 + 0.001)
                    amount = diff * buy_price
                    fee = amount * commission
                    total_cost = amount + fee
                    if total_cost <= capital:
                        capital -= total_cost
                        holdings[code] = target
                        trades.append({"date": date, "code": code, "type": "BUY",
                                       "price": buy_price, "shares": diff, "fee": fee})
                else:
                    sell_shares = abs(diff)
                    sell_price = row[code] * (1 - 0.001)
                    revenue = sell_shares * sell_price
                    fee = revenue * (commission + stamp_tax)
                    capital += revenue - fee
                    holdings[code] = target
                    trades.append({"date": date, "code": code, "type": "SELL",
                                   "price": sell_price, "shares": sell_shares, "fee": fee})

    equity_df = pd.DataFrame(equity_list)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    metrics = _calc_metrics(equity_df, initial_capital)
    return equity_df, metrics, trades_df


def _calc_metrics(equity_df: pd.DataFrame, initial_capital: float) -> dict:
    if equity_df.empty:
        return {}
    final = equity_df["equity"].iloc[-1]
    days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
    years = max(days / 365.25, 1e-9)
    total_ret = (final - initial_capital) / initial_capital * 100
    annual_ret = ((final / initial_capital) ** (1 / years) - 1) * 100
    max_dd = ((equity_df["equity"].cummax() - equity_df["equity"]) / equity_df["equity"].cummax()).max() * 100
    return {
        "初始资金": f"{initial_capital:,.0f}",
        "最终资产": f"{final:,.0f}",
        "总收益率(%)": round(total_ret, 2),
        "年化收益率(%)": round(annual_ret, 2),
        "最大回撤(%)": round(max_dd, 2),
        "回测天数": days,
    }


# ──────────────────────────────────────────────────────────────
# 报告与可视化
# ──────────────────────────────────────────────────────────────
def generate_report(equity_df: pd.DataFrame, metrics: dict, pool: list[str],
                    method: str, macro_score: dict, save_path: str = None) -> str:
    report = []
    report.append("# 一揽子股票组合投资策略报告")
    report.append(f"\n**生成时间**: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"\n**组合股票池**: {', '.join(pool)}")
    report.append(f"\n**权重方案**: {method}")

    report.append("\n## 宏观环境分析")
    report.append(f"\n**综合评分**: {macro_score.get('score', 0):.2f} (范围: -1 到 1)")
    for event in macro_score.get("events", []):
        report.append(f"- {event}")
    for factor, signal in macro_score.get("signals", {}).items():
        direction = "利好" if signal > 0 else "利空" if signal < 0 else "中性"
        report.append(f"- {factor}: {direction} ({signal})")

    report.append("\n## 组合绩效")
    for k, v in metrics.items():
        report.append(f"- **{k}**: {v}")

    report.append("\n## 盈利目标")
    report.append("- **基准**: 创业板指（近5年年化约 8-12%）")
    report.append("- **目标**: 创业板 + 20% Alpha → 年化 25-35%")
    report.append("- **风险预算**: 最大回撤 ≤ 25%")
    report.append("- **调仓频率**: 周度 + 信号触发")

    report.append("\n## 四层分析框架")
    report.append("### Layer 1: 宏观")
    report.append("- 地缘政治冲突监测（战争/制裁/贸易摩擦）")
    report.append("- 经济周期指标：PMI（制造业扩张/收缩）")
    report.append("- 流动性：M2增速、Shibor利率")
    report.append("- 通胀：CPI/PPI剪刀差")
    report.append("- 全球风险：美元指数、纳指100")

    report.append("\n### Layer 2: 国家干预")
    report.append("- 北向资金流向（陆股通）")
    report.append("- 融资融券余额变化")
    report.append("- 产业政策关键词监测")

    report.append("\n### Layer 3: 行业")
    report.append("- 行业轮动相对强弱")
    report.append("- 行业估值分位（PE/PB）")
    report.append("- 上下游价格传导")
    report.append("- 库存周期位置")

    report.append("\n### Layer 4: 个股")
    report.append("- 趋势评分（MA5/MA20/MA60）")
    report.append("- MACD金叉/死叉信号")
    report.append("- RSI超买超卖")
    report.append("- 量价配合度")
    report.append("- 波动率（低波得分高）")

    report.append("\n## 风险提示")
    report.append("- 地缘政治冲突可能加剧，影响市场风险偏好")
    report.append("- 美元指数若持续走强，可能压制A股/港股估值")
    report.append("- 单一行业集中度风险")
    report.append("- 模型基于历史数据，未来表现可能偏离")
    report.append("- 盈利目标为理论值，实际收益受多种因素影响")

    report_text = "\n".join(report)

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"[报告] 已保存: {save_path}")

    return report_text


def plot_portfolio(equity_df: pd.DataFrame, pool: list[str], method: str,
                   benchmark: pd.DataFrame = None, save_path: str = None):
    if equity_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(equity_df["date"], equity_df["equity"], label=f"组合 ({method})", color="#2E86AB", linewidth=2)
    ax.fill_between(equity_df["date"], equity_df["equity"], alpha=0.1, color="#2E86AB")

    if benchmark is not None and not benchmark.empty:
        bm_norm = benchmark["close"] / benchmark["close"].iloc[0] * equity_df["equity"].iloc[0]
        ax.plot(benchmark["date"], bm_norm, label="基准（创业板指）", color="#E74C3C", linewidth=1.5, linestyle="--")

    ax.set_title(f"一揽子股票组合净值曲线 — {method}", fontsize=14, fontweight="bold")
    ax.set_xlabel("日期")
    ax.set_ylabel("账户资产 (元)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    info = f"初始: {equity_df['equity'].iloc[0]:,.0f}\n最终: {equity_df['equity'].iloc[-1]:,.0f}\n收益: {(equity_df['equity'].iloc[-1]/equity_df['equity'].iloc[0]-1)*100:.1f}%"
    ax.text(0.02, 0.98, info, transform=ax.transAxes, fontsize=10,
            verticalalignment="top", bbox=dict(boxstyle="round", facecolor="#f7f7f7", edgecolor="#ccc"))

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[图表] 已保存: {save_path}")
    plt.close()


def plot_score_breakdown(scores: dict[str, float], save_path: str = None):
    if not scores:
        return
    codes = list(scores.keys())
    values = [scores[c] for c in codes]
    colors = ["#2E86AB" if v > 0 else "#E74C3C" for v in values]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(codes, values, color=colors, alpha=0.8)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("综合评分")
    ax.set_title("个股评分排序", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="x")
    for bar, val in zip(bars, values):
        ax.text(val + 0.01 if val > 0 else val - 0.01, bar.get_y() + bar.get_height()/2,
                f"{val:.2f}", ha="left" if val > 0 else "right", va="center", fontsize=9)
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"[图表] 评分图已保存: {save_path}")
    plt.close()


# ──────────────────────────────────────────────────────────────
# 新闻监控
# ──────────────────────────────────────────────────────────────
def monitor_news(pool: list[str]) -> dict:
    print("[新闻] 正在获取实时新闻...")
    news_df = fetch_news(max_items=100)
    if news_df.empty:
        return {"events": [], "alert_level": "normal"}

    events = []
    alert_level = "normal"
    for _, row in news_df.iterrows():
        content = str(row.get("content", ""))
        for kw in GEOPOLITICAL_KEYWORDS:
            if kw in content:
                events.append({"time": str(row.get("time", "")), "keyword": kw, "content": content[:200]})
                break

    if len(events) >= 5:
        alert_level = "high"
    elif len(events) >= 2:
        alert_level = "medium"

    print(f"[新闻] 获取 {len(news_df)} 条，地缘事件 {len(events)} 条，预警: {alert_level}")
    return {"events": events[:10], "alert_level": alert_level}


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="一揽子股票选股组合分析系统")
    parser.add_argument("--mode", default="backtest", choices=["backtest", "report", "news"])
    parser.add_argument("--pool", default=None, help="股票池，逗号分隔")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--rebalance", default="W", choices=["W", "M"])
    parser.add_argument("--method", default="评分加权", choices=["评分加权", "风险平价"])
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--report-dir", default=os.path.dirname(os.path.abspath(__file__)))
    args = parser.parse_args()

    if args.end is None:
        args.end = dt.date.today().strftime("%Y-%m-%d")

    pool = [c.strip() for c in args.pool.split(",")] if args.pool else DEFAULT_POOL

    if args.mode == "news":
        result = monitor_news(pool)
        print(f"\n预警级别: {result['alert_level']}")
        for ev in result["events"]:
            print(f"  [{ev['time']}] {ev['keyword']}: {ev['content'][:100]}")
        return

    if args.mode == "report":
        print(f"[报告] 股票池: {pool}")
        scores = {}
        for code in pool:
            df = fetch_price(code, (dt.date.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d"),
                             dt.date.today().strftime("%Y-%m-%d"))
            score_result = score_stock(df, code)
            scores[code] = score_result["score"]
            print(f"  {code}: {score_result['score']:.3f} ({score_result['details']})")

        prices = {}
        for code in pool:
            df = fetch_price(code, (dt.date.today() - dt.timedelta(days=5)).strftime("%Y-%m-%d"),
                             dt.date.today().strftime("%Y-%m-%d"))
            if not df.empty:
                prices[code] = df["close"].iloc[-1]

        weights = build_portfolio(scores, prices, method=args.method)
        print(f"\n建议权重 ({args.method}):")
        for code, w in sorted(weights.items(), key=lambda x: -x[1]):
            print(f"  {code}: {w*100:.1f}%")

        macro_data = fetch_macro((dt.date.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d"),
                                  dt.date.today().strftime("%Y-%m-%d"))
        news_df = fetch_news()
        macro_score = score_macro(macro_data, news_df)

        report_path = os.path.join(args.report_dir, "portfolio_current.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(generate_report(pd.DataFrame(), {}, pool, args.method, macro_score))
            f.write("\n## 当前建议组合\n")
            f.write("\n| 代码 | 评分 | 权重 |\n|---|---|---|\n")
            for code, w in sorted(weights.items(), key=lambda x: -x[1]):
                s = scores.get(code, 0)
                f.write(f"| {code} | {s:.3f} | {w*100:.1f}% |\n")
        print(f"[报告] 已保存: {report_path}")

        score_path = os.path.join(args.report_dir, "portfolio_scores.png")
        plot_score_breakdown(scores, save_path=score_path)

    elif args.mode == "backtest":
        print(f"[回测] 股票池: {pool}")
        print(f"[回测] 区间: {args.start} ~ {args.end}")
        equity_df, metrics, trades_df = backtest_portfolio(
            pool, args.start, args.end,
            rebalance_freq=args.rebalance, method=args.method,
            initial_capital=args.capital,
        )
        if equity_df.empty:
            print("[错误] 回测失败")
            return

        print("\n" + "=" * 60)
        print("  组合绩效报告")
        print("=" * 60)
        for k, v in metrics.items():
            print(f"  {k:<16}: {v}")
        print("=" * 60)

        macro_data = fetch_macro(args.start, args.end)
        news_df = fetch_news()
        macro_score = score_macro(macro_data, news_df)

        report_path = os.path.join(args.report_dir, f"portfolio_report_{args.start}_{args.end}.md")
        generate_report(equity_df, metrics, pool, args.method, macro_score, save_path=report_path)

        chart_path = os.path.join(args.report_dir, f"portfolio_chart_{args.start}_{args.end}.png")
        plot_portfolio(equity_df, pool, args.method, save_path=chart_path)

        if not trades_df.empty:
            trades_path = os.path.join(args.report_dir, f"portfolio_trades_{args.start}_{args.end}.csv")
            trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
            print(f"[导出] 交易记录: {trades_path}")

        equity_path = os.path.join(args.report_dir, f"portfolio_equity_{args.start}_{args.end}.csv")
        equity_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
        print(f"[导出] 净值曲线: {equity_path}")


if __name__ == "__main__":
    main()
