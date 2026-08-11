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
import akshare as ak
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
MILITARY_KEYWORDS = [
    "军事", "演习", "导弹", "航母", "战机", "国防",
    "军队", "战区", "基地", "武器", "核", "无人机",
    "俄乌", "哈马斯", "真主党", "美军", "解放军",
]
INDUSTRY_KEYWORDS = [
    "产业链", "供应链", "上游", "下游", "芯片", "半导体",
    "光伏", "风电", "锂电", "新能源汽车", "电池",
    "稀土", "钢铁", "煤炭", "化工", "水泥",
    "医药", "创新药", "CXO", "医疗器械",
    "房地产", "基建", "建材",
    "AI", "人工智能", "算力", "数据", "大模型",
    "消费", "白酒", "食品", "饮料",
    "金融", "银行", "保险", "证券",
    "出口", "进口", "关税", "贸易",
]

# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────
def _is_hk(code: str) -> bool:
    if "." in code:
        return code.split(".")[0].lower() == "hk"
    if code.startswith("hk"):
        return True
    if len(code) == 5 and code.startswith(("0",)):
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


def fetch_name(code: str) -> str:
    """获取股票中文名称（腾讯qt接口）"""
    clean = _clean_code(code)
    is_hk = _is_hk(code)
    try:
        if is_hk:
            url = f"https://qt.gtimg.cn/q=hk{clean}"
        else:
            ex = _exchange(code)
            url = f"https://qt.gtimg.cn/q={ex}{clean}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        text = resp.text
        match = re.search(r'v_(?:sh|sz|hk)(\d+)="[^~]*~([^~]+)~', text)
        if match:
            return match.group(2)
    except Exception:
        pass
    return code


def fetch_price(code: str, start: str, end: str, log_callback=None) -> pd.DataFrame:
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
                    if log_callback:
                        log_callback(f"[完成] {code} | {start}~{end} | 港股 | {len(df)} bars")
                    return df
            except Exception as e:
                if log_callback:
                    log_callback(f"[失败] {code} | {start}~{end} | 港股 | {str(e)[:40]}")
                if attempt < 2:
                    time.sleep(2)
        if log_callback:
            log_callback(f"[跳过] {code} | {start}~{end} | 数据不足")
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
                t0 = time.time()
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
                                  timeout=15)
                dt_ms = int((time.time() - t0) * 1000)
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
                size_kb = len(r.content) // 1024
                if log_callback:
                    log_callback(f"[下载] {code} | {beg}~{ed} | {len(klines)} bars | {size_kb}KB | {dt_ms}ms | 200")
                break
            except Exception as e:
                dt_ms = int((time.time() - t0) * 1000) if 't0' in dir() else 0
                if log_callback:
                    log_callback(f"[失败] {code} | {beg}~{ed} | {str(e)[:40]} | {dt_ms}ms")
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
        if log_callback:
            log_callback(f"[跳过] {code} | {start}~{end} | 无数据")
        return pd.DataFrame()
    if log_callback:
        log_callback(f"[完成] {code} | {start}~{end} | {len(rows)} bars")
    return pd.DataFrame(rows)


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
    """获取实时新闻，并分类标签（多源回退）"""
    news_list = []

    # 来源1：财联社电报（可能失效）
    try:
        url = "https://www.cls.cn/nodeapi/updateTelegraphList"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cls.cn/"}
        resp = requests.post(url, headers=headers,
                             json={"app": "CailianpressWeb", "os": "web", "sv": "8.4.6",
                                   "rn": max_items, "page": 0},
                             timeout=15)
        data = resp.json()
        rolls = data.get("data", {}).get("roll_data", [])
        if not rolls:
            rolls = data.get("data", {}).get("list", [])
        for item in rolls:
            content = item.get("title", "") + " " + item.get("content", "")
            ctime = item.get("ctime", "")
            tags = []
            c = content.lower()
            for kw in GEOPOLITICAL_KEYWORDS:
                if kw in c:
                    tags.append("地缘政治")
                    break
            for kw in MILITARY_KEYWORDS:
                if kw in c:
                    tags.append("军事突发")
                    break
            for kw in INDUSTRY_KEYWORDS:
                if kw in c:
                    tags.append("产业链")
                    break
            if not tags:
                tags.append("其他")
            news_list.append({
                "time": ctime, "content": content, "source": "财联社", "tags": ",".join(tags)
            })
    except Exception:
        pass

    # 来源2：财联社 `stock_news_main_cx`（更稳定）
    if len(news_list) < 5:
        try:
            df_cx = ak.stock_news_main_cx()
            if df_cx is not None and not df_cx.empty:
                for _, row in df_cx.head(max_items).iterrows():
                    content = str(row.get("summary", ""))
                    tag_raw = str(row.get("tag", ""))
                    tags = [tag_raw] if tag_raw else ["其他"]
                    c = content.lower()
                    for kw in GEOPOLITICAL_KEYWORDS:
                        if kw in c and "地缘政治" not in tags:
                            tags.append("地缘政治")
                            break
                    for kw in MILITARY_KEYWORDS:
                        if kw in c and "军事突发" not in tags:
                            tags.append("军事突发")
                            break
                    for kw in INDUSTRY_KEYWORDS:
                        if kw in c and "产业链" not in tags:
                            tags.append("产业链")
                            break
                    if len(tags) == 1:
                        tags = ["其他"]
                    news_list.append({
                        "time": "", "content": content, "source": "财联社CX", "tags": ",".join(tags)
                    })
        except Exception:
            pass

    # 来源3：腾讯新闻
    if len(news_list) < 5:
        try:
            resp = requests.get("https://news.qq.com/", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "utf-8"
            titles = re.findall(r'<h[12][^>]*>(.*?)</h[12]>', resp.text, re.DOTALL)
            for t in titles[:20]:
                clean = re.sub(r'<[^>]+>', '', t).strip()
                if clean and len(clean) > 5:
                    news_list.append({"time": "", "content": clean, "source": "腾讯新闻", "tags": "其他"})
        except Exception:
            pass

    # 来源4：个股新闻（东方财富，按 stock_news_em）
    if len(news_list) < 5:
        try:
            df_em = ak.stock_news_em(symbol="600519")
            if df_em is not None and not df_em.empty:
                for _, row in df_em.head(max_items).iterrows():
                    content = str(row.get("新闻标题", "")) + " " + str(row.get("新闻内容", ""))
                    pub = str(row.get("发布时间", ""))
                    tags = []
                    c = content.lower()
                    for kw in INDUSTRY_KEYWORDS:
                        if kw in c:
                            tags.append("产业链")
                            break
                    if not tags:
                        tags.append("其他")
                    news_list.append({
                        "time": pub, "content": content, "source": "东方财富", "tags": ",".join(tags)
                    })
        except Exception:
            pass

    df = pd.DataFrame(news_list)
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df


# ──────────────────────────────────────────────────────────────
# 选股分析：股东 + 资金流向
# ──────────────────────────────────────────────────────────────
def analyze_holder(code: str) -> dict:
    """股东数量变化分析，返回近期股东总数变化"""
    result = {
        "code": code,
        "shareholder_count_now": None,
        "shareholder_count_prev": None,
        "shareholder_change": None,
        "holder_concentration": None,
        "updated_at": None,
    }
    try:
        clean = code.split(".")[-1] if "." in code else code
        df = ak.stock_main_stock_holder(stock=clean)
        if df is None or df.empty:
            return result

        # 清洗日期，按截至日期聚合去重
        date_col = "截至日期" if "截至日期" in df.columns else "公告日期"
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, "股东总数"])
        if df.empty:
            return result
        agg = df.groupby(date_col)["股东总数"].first().sort_index(ascending=False)

        if len(agg) < 2:
            return result

        cnt_now = float(agg.iloc[0])
        cnt_prev = float(agg.iloc[1])

        result["shareholder_count_now"] = int(cnt_now)
        result["shareholder_count_prev"] = int(cnt_prev)
        result["shareholder_change"] = cnt_now - cnt_prev
        result["updated_at"] = str(agg.index[0].date())
        result["holder_concentration"] = f"{(cnt_now / max(cnt_prev, 1) - 1) * 100:.1f}%"
    except Exception:
        pass
    return result


def analyze_lhb(code: str) -> dict:
    """近一月龙虎榜：上榜次数、机构净额、营业部净额"""
    result = {"code": code, "lhb_times": None, "lhb_inst_net": None,
              "lhb_dept_net": None, "updated_at": None}
    try:
        # 先拿全市场近一月统计，再按代码过滤
        df = ak.stock_lhb_ggtj_sina("5")
        if df is None or df.empty or "股票代码" not in df.columns:
            return result
        clean = code.split(".")[-1] if "." in code else code
        sub = df[df["股票代码"] == clean]
        if sub.empty:
            return result
        row = sub.iloc[0]
        result["lhb_times"] = int(row.get("上榜次数", 0) or 0)
        result["lhb_inst_net"] = float(row.get("净额", 0) or 0)
        result["lhb_dept_net"] = float(row.get("累积购买额", 0) or 0) - float(row.get("累积卖出额", 0) or 0)
        result["updated_at"] = "近一月"
    except Exception:
        pass
    return result


def analyze_pledge(code: str) -> dict:
    """股权质押：质押比例、风险等级（按东方财富质押比例数据）"""
    result = {"code": code, "pledge_ratio": None, "pledge_risk": None, "updated_at": None}
    try:
        df = ak.stock_gpzy_pledge_ratio_em()
        if df is None or df.empty:
            return result
        clean = code.split(".")[-1] if "." in code else code
        sub = df[df["股票代码"] == clean]
        if sub.empty:
            return result
        row = sub.iloc[0]
        ratio = float(row.get("质押比例", 0) or 0)
        result["pledge_ratio"] = ratio
        if ratio >= 50:
            result["pledge_risk"] = "高风险"
        elif ratio >= 30:
            result["pledge_risk"] = "中风险"
        else:
            result["pledge_risk"] = "低风险"
        result["updated_at"] = str(row.get("公告日期", ""))[:10]
    except Exception:
        pass
    return result


def analyze_restricted_release(code: str) -> dict:
    """限售股解禁：未来3个月内解禁数量、占流通市值比例"""
    result = {"code": code, "release_qty": None, "release_ratio": None,
              "release_date": None, "updated_at": None}
    try:
        clean = code.split(".")[-1] if "." in code else code
        # 取未来6个月窗口
        today = pd.Timestamp.today()
        end = today + pd.DateOffset(months=6)
        df = ak.stock_restricted_release_queue_em(clean,
                                                  start_date=today.strftime("%Y%m%d"),
                                                  end_date=end.strftime("%Y%m%d"))
        if df is None or df.empty:
            return result
        # 取最早解禁日
        date_col = "解禁时间"
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        if df.empty:
            return result
        df = df.sort_values(date_col, ascending=True)
        first = df.iloc[0]
        qty = float(first.get("实际解禁数量", 0) or 0)
        ratio = float(first.get("占总市值比例", 0) or 0)
        result["release_qty"] = qty
        result["release_ratio"] = ratio
        result["release_date"] = str(first[date_col].date())
        result["updated_at"] = result["release_date"]
    except Exception:
        pass
    return result


def analyze_north_flow(code: str) -> dict:
    """北向资金（沪股通/深股通）近期持股变化"""
    result = {"code": code, "hold_qty": None, "hold_ratio": None,
              "hold_change": None, "updated_at": None}
    try:
        clean = code.split(".")[-1] if "." in code else code
        # 先判断市场
        if code.startswith("sh."):
            df = ak.stock_hsgt_individual_em(clean)
        elif code.startswith("sz."):
            df = ak.stock_hsgt_individual_em(clean)
        else:
            df = ak.stock_hsgt_individual_em(clean)
        if df is None or df.empty:
            return result
        date_col = "持股日期"
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col, "持股数量"])
        if df.empty:
            return result
        df = df.sort_values(date_col, ascending=False)
        if len(df) < 2:
            return result
        now_qty = float(df.iloc[0]["持股数量"])
        prev_qty = float(df.iloc[1]["持股数量"])
        result["hold_qty"] = now_qty
        result["hold_change"] = now_qty - prev_qty
        ratio = float(df.iloc[0].get("持股数量占A股百分比", 0) or 0)
        result["hold_ratio"] = ratio
        result["updated_at"] = str(df.iloc[0][date_col].date())
    except Exception:
        pass
    return result


def analyze_margin(code: str) -> dict:
    """融资融券余额变化（近20日）"""
    result = {"code": code, "margin_balance": None, "margin_change": None,
              "margin_ratio": None, "updated_at": None}
    try:
        clean = code.split(".")[-1] if "." in code else code
        prefix = code.split(".")[0].lower() if "." in code else "sh"
        df = ak.stock_margin_detail_sse(date="20240101") if prefix == "sh" else ak.stock_margin_detail_szse(date="20240101")
        if df is None or df.empty or "股票代码" not in df.columns:
            return result
        sub = df[df["股票代码"] == clean]
        if sub.empty:
            return result
        row = sub.iloc[0]
        result["margin_balance"] = float(row.get("融资余额(万元)", 0) or 0)
        result["updated_at"] = str(row.get("交易日期", ""))[:10]
    except Exception:
        pass
    return result


def analyze_fund_flow(code: str) -> dict:
    """大单/超大单资金流向分析（东方财富接口，可能不稳定）"""
    result = {
        "code": code,
        "latest_date": None,
        "big_net_inflow": None,
        "super_big_net_inflow": None,
        "big_ratio": None,
        "super_big_ratio": None,
        "updated_at": None,
        "error": None,
    }
    try:
        clean = code.split(".")[-1] if "." in code else code
        prefix = code.split(".")[0].lower() if "." in code else "sh"
        df = ak.stock_individual_fund_flow(stock=clean, market=prefix)
        if df is None or df.empty:
            result["error"] = "数据为空"
            return result
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df.sort_values("日期", ascending=False)

        if "大单净流入-净额" not in df.columns or "超大单净流入-净额" not in df.columns:
            result["error"] = "列名变化"
            return result

        latest = df.iloc[0]
        result["latest_date"] = str(latest["日期"].date())
        result["big_net_inflow"] = float(latest.get("大单净流入-净额", 0))
        result["super_big_net_inflow"] = float(latest.get("超大单净流入-净额", 0))
        result["big_ratio"] = float(latest.get("大单净流入-净占比", 0))
        result["super_big_ratio"] = float(latest.get("超大单净流入-净占比", 0))
        result["updated_at"] = str(latest["日期"].date())
    except Exception as e:
        result["error"] = str(e)[:60]
    return result


def analyze_selection(code: str) -> dict:
    """综合选股分析：股东数量 + 大单 + 龙虎榜 + 股权质押 + 限售解禁 + 北向资金 + 回购 + 融资融券"""
    holder = analyze_holder(code)
    fund = analyze_fund_flow(code)
    lhb = analyze_lhb(code)
    pledge = analyze_pledge(code)
    release = analyze_restricted_release(code)
    north = analyze_north_flow(code)
    # margin 接口不稳定，不阻塞主流程
    margin = analyze_margin(code)

    summary = {
        "code": code,
        "holder": holder,
        "fund_flow": fund,
        "lhb": lhb,
        "pledge": pledge,
        "release": release,
        "north_flow": north,
        "margin": margin,
        "score": 0.0,
        "signals": [],
    }

    # 1. 股东减少 -> 筹码集中 -> 利好
    if holder.get("shareholder_change") is not None:
        chg = holder["shareholder_change"]
        if chg < 0:
            summary["score"] += 0.3
            summary["signals"].append(f"股东减少 {abs(int(chg))} 户 (筹码集中)")
        elif chg > 0:
            summary["score"] -= 0.2
            summary["signals"].append(f"股东增加 {int(chg)} 户 (筹码分散)")

    # 2. 大单/超大单净流入
    big = fund.get("big_net_inflow") or 0
    super_big = fund.get("super_big_net_inflow") or 0
    total_big = big + super_big
    if total_big > 1_000_000:
        summary["score"] += 0.4
        summary["signals"].append(f"大单净流入 {total_big/10000:.0f} 万")
    elif total_big < -1_000_000:
        summary["score"] -= 0.4
        summary["signals"].append(f"大单净流出 {abs(total_big)/10000:.0f} 万")

    if fund.get("big_ratio") is not None and fund["big_ratio"] > 5:
        summary["score"] += 0.2
        summary["signals"].append(f"大单占比 {fund['big_ratio']:.1f}%")
    if fund.get("super_big_ratio") is not None and fund["super_big_ratio"] > 5:
        summary["score"] += 0.2
        summary["signals"].append(f"超大单占比 {fund['super_big_ratio']:.1f}%")

    # 3. 龙虎榜：机构净额为正 -> 机构介入 -> 利好
    if lhb.get("lhb_times") is not None:
        inst_net = lhb.get("lhb_inst_net") or 0
        if lhb["lhb_times"] > 0 and inst_net > 0:
            summary["score"] += 0.3
            summary["signals"].append(f"龙虎榜机构净买 {inst_net/10000:.0f} 万")
        elif lhb["lhb_times"] > 0 and inst_net < 0:
            summary["score"] -= 0.2
            summary["signals"].append(f"龙虎榜机构净卖 {abs(inst_net)/10000:.0f} 万")

    # 4. 股权质押：高风险 -> 利空
    if pledge.get("pledge_risk") == "高风险":
        summary["score"] -= 0.3
        summary["signals"].append(f"股权质押高风险 {pledge.get('pledge_ratio', 0):.1f}%")
    elif pledge.get("pledge_risk") == "中风险":
        summary["score"] -= 0.1
        summary["signals"].append(f"股权质押中风险 {pledge.get('pledge_ratio', 0):.1f}%")

    # 5. 限售股解禁：占比高 -> 利空
    if release.get("release_ratio") is not None and release["release_ratio"] > 0:
        ratio = release["release_ratio"]
        if ratio > 5:
            summary["score"] -= 0.3
            summary["signals"].append(f"解禁占比 {ratio:.2f}% 高")
        elif ratio > 1:
            summary["score"] -= 0.1
            summary["signals"].append(f"解禁占比 {ratio:.2f}%")

    # 6. 北向资金增持 -> 利好；减持 -> 利空
    if north.get("hold_change") is not None:
        chg = north["hold_change"]
        if chg > 0:
            summary["score"] += 0.2
            summary["signals"].append(f"北向增持 {chg/10000:.0f} 万股")
        elif chg < 0:
            summary["score"] -= 0.15
            summary["signals"].append(f"北向减持 {abs(chg)/10000:.0f} 万股")

    # 7. 回购：有回购 -> 利好
    # 这里简化：若 `analyze_fund_flow` 返回 error 为 None 且有大单，可考虑回购信号
    # 实际回购数据需另外维护，此处留作扩展

    return summary


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
                       stamp_tax: float = 0.0005,
                       progress_callback=None,
                       log_callback=None) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    print(f"[回测] 组合: {len(pool)} 只, 调仓: {rebalance_freq}, 权重: {method}")

    all_data = {}
    total = len(pool)
    for idx, code in enumerate(pool, 1):
        if progress_callback:
            progress_callback(f"获取数据 {idx}/{total}: {code}", int((idx - 1) / total * 40))
        df = fetch_price(code, start, end, log_callback=log_callback)
        if not df.empty and len(df) >= 60:
            all_data[code] = df
            print(f"  {code}: {len(df)} bars")
        else:
            print(f"  [跳过] {code}: 数据不足")

    if not all_data:
        return pd.DataFrame(), {}, pd.DataFrame()

    # 合并价格矩阵
    if progress_callback:
        progress_callback("合并价格矩阵...", 40)
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
    total_bars = len(price_df)
    rebalance_dates = price_df[price_df["rebalance"] == True]

    for idx, row in price_df.iterrows():
        date = row["date"]
        current_value = capital + sum(holdings[code] * row[code] for code in holdings)
        equity_list.append({"date": date, "equity": current_value})

        if row["rebalance"]:
            if progress_callback:
                rebalance_idx = list(rebalance_dates.index).index(idx) if idx in rebalance_dates.index else 0
                total_rebalances = len(rebalance_dates)
                pct = 40 + int(rebalance_idx / max(total_rebalances, 1) * 50)
                progress_callback(f"调仓计算 {rebalance_idx+1}/{total_rebalances}: {date.strftime('%Y-%m-%d')}", pct)

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

    if progress_callback:
        progress_callback("计算绩效指标...", 95)

    equity_df = pd.DataFrame(equity_list)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    metrics = _calc_metrics(equity_df, initial_capital)

    if progress_callback:
        progress_callback("完成", 100)

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
        return {"events": [], "alert_level": "normal", "last_updated": None}

    last_updated = None
    if "time" in news_df.columns and not news_df["time"].isna().all():
        last_updated = str(news_df["time"].max())

    events = []
    alert_level = "normal"
    tag_counts = {"地缘政治": 0, "军事突发": 0, "产业链": 0, "其他": 0}

    for _, row in news_df.iterrows():
        content = str(row.get("content", ""))
        raw_tags = str(row.get("tags", "")).split(",")
        primary_tag = raw_tags[0] if raw_tags else "其他"
        # 只统计第一个标签到固定分类，其余合并到"其他"
        if primary_tag in tag_counts:
            tag_counts[primary_tag] += 1
        else:
            tag_counts["其他"] += 1

        # 高风险事件
        for kw in GEOPOLITICAL_KEYWORDS + MILITARY_KEYWORDS:
            if kw in content:
                events.append({
                    "time": str(row.get("time", "")),
                    "keyword": kw,
                    "content": content[:200],
                    "tag": primary_tag
                })
                break

    if len(events) >= 5:
        alert_level = "high"
    elif len(events) >= 2:
        alert_level = "medium"

    print(f"[新闻] 获取 {len(news_df)} 条，标签: {tag_counts}，预警: {alert_level}")
    return {
        "events": events[:10],
        "alert_level": alert_level,
        "last_updated": last_updated,
        "tag_counts": tag_counts,
        "total": len(news_df),
    }


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="一揽子股票选股组合分析系统")
    parser.add_argument("--mode", default="backtest", choices=["backtest", "report", "news"])
    parser.add_argument("--pool", default=None, help="股票池，逗号分隔")
    parser.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=730)).strftime("%Y-%m-%d"))
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
