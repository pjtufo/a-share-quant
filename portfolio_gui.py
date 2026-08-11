#!/usr/bin/env python3
"""
一揽子股票选股组合分析系统 - GUI 界面 v2
"""

import argparse
import datetime as dt
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portfolio_selector import (
    fetch_price, fetch_name, score_stock, build_portfolio,
    fetch_macro, score_macro, fetch_news,
    backtest_portfolio, generate_report, plot_portfolio, plot_score_breakdown,
    monitor_news, DEFAULT_POOL,
    analyze_selection, analyze_technical,
)

# ──────────────────────────────────────────────────────────────
# 主题
# ──────────────────────────────────────────────────────────────
COLORS = {
    "bg_primary": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_card": "#0f3460",
    "accent": "#e94560",
    "accent_hover": "#ff6b81",
    "text_primary": "#ffffff",
    "text_secondary": "#a0a0c0",
    "success": "#2ecc71",
    "warning": "#f39c12",
    "danger": "#e74c3c",
    "border": "#2a2a4a",
}

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC"]
plt.rcParams["axes.unicode_minus"] = False


class ModernStyle:
    def __init__(self, root):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=COLORS["bg_primary"])
        self.style.configure("TLabel", background=COLORS["bg_primary"],
                             foreground=COLORS["text_primary"], font=("Microsoft YaHei", 10))
        self.style.configure("TButton", background=COLORS["accent"], foreground="white",
                             font=("Microsoft YaHei", 10, "bold"), padding=8)
        self.style.map("TButton", background=[("active", COLORS["accent_hover"])])
        self.style.configure("TNotebook", background=COLORS["bg_secondary"], borderwidth=0)
        self.style.configure("TNotebook.Tab", background=COLORS["bg_card"],
                             foreground=COLORS["text_primary"], padding=[12, 8],
                             font=("Microsoft YaHei", 10))
        self.style.map("TNotebook.Tab", background=[("selected", COLORS["accent"])])
        self.style.configure("TEntry", fieldbackground=COLORS["bg_card"],
                             foreground=COLORS["text_primary"], padding=6)
        self.style.configure("TCombobox", fieldbackground=COLORS["bg_card"],
                             foreground=COLORS["text_primary"])
        self.style.configure("Treeview", background=COLORS["bg_card"],
                             foreground=COLORS["text_primary"], fieldbackground=COLORS["bg_card"],
                             borderwidth=0)
        self.style.configure("Treeview.Heading", background=COLORS["bg_secondary"],
                             foreground=COLORS["text_primary"], font=("Microsoft YaHei", 9, "bold"))
        self.style.map("Treeview", background=[("selected", COLORS["accent"])])
        root.configure(bg=COLORS["bg_primary"])


# ──────────────────────────────────────────────────────────────
# 股票池管理面板
# ──────────────────────────────────────────────────────────────
class PoolPanel(ttk.Frame):
    def __init__(self, parent, pool_list, on_change_callback):
        super().__init__(parent)
        self.pool_list = pool_list
        self.on_change = on_change_callback

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text="股票池管理", font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="加载默认池", command=self.load_default).pack(side=tk.RIGHT, padx=5)

        input_frame = ttk.Frame(self)
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(input_frame, text="添加股票:").pack(side=tk.LEFT, padx=5)
        self.entry = ttk.Entry(input_frame, width=20)
        self.entry.pack(side=tk.LEFT, padx=5)
        self.entry.bind("<Return>", lambda e: self.add_stock())
        ttk.Button(input_frame, text="添加", command=self.add_stock).pack(side=tk.LEFT, padx=5)
        ttk.Button(input_frame, text="从文件导入", command=self.import_from_file).pack(side=tk.LEFT, padx=5)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(list_frame, columns=("code", "name"), show="headings",
                                 yscrollcommand=scrollbar.set, height=12)
        self.tree.heading("code", text="代码")
        self.tree.heading("name", text="名称")
        self.tree.column("code", width=120, anchor=tk.CENTER)
        self.tree.column("name", width=150, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="删除选中", command=self.remove_selected).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self.clear_all).pack(side=tk.RIGHT, padx=5)

        self.refresh_list()

    def refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for code in self.pool_list:
            name = fetch_name(code)
            self.tree.insert("", tk.END, values=(code, name))

    def add_stock(self):
        text = self.entry.get().strip()
        if not text:
            return
        codes = [c.strip() for c in text.replace("，", ",").split(",") if c.strip()]
        for code in codes:
            if code not in self.pool_list:
                self.pool_list.append(code)
        self.entry.delete(0, tk.END)
        self.refresh_list()
        self.on_change()

    def remove_selected(self):
        for item in self.tree.selection():
            code = self.tree.item(item)["values"][0]
            if code in self.pool_list:
                self.pool_list.remove(code)
        self.refresh_list()
        self.on_change()

    def clear_all(self):
        self.pool_list.clear()
        self.refresh_list()
        self.on_change()

    def load_default(self):
        self.pool_list.clear()
        self.pool_list.extend(DEFAULT_POOL)
        self.refresh_list()
        self.on_change()

    def import_from_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    code = line.strip()
                    if code and code not in self.pool_list:
                        self.pool_list.append(code)
            self.refresh_list()
            self.on_change()
            messagebox.showinfo("导入成功", f"已导入股票池，共 {len(self.pool_list)} 只")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))


# ──────────────────────────────────────────────────────────────
# 参数配置面板
# ──────────────────────────────────────────────────────────────
class ConfigPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.vars = {}

        date_frame = ttk.Frame(self)
        date_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(date_frame, text="开始日期:").pack(side=tk.LEFT, padx=5)
        two_years_ago = (dt.date.today() - dt.timedelta(days=730)).strftime("%Y-%m-%d")
        self.vars["start"] = tk.StringVar(value=two_years_ago)
        ttk.Entry(date_frame, textvariable=self.vars["start"], width=15).pack(side=tk.LEFT, padx=5)

        ttk.Label(date_frame, text="结束日期:").pack(side=tk.LEFT, padx=5)
        self.vars["end"] = tk.StringVar(value=dt.date.today().strftime("%Y-%m-%d"))
        ttk.Entry(date_frame, textvariable=self.vars["end"], width=15).pack(side=tk.LEFT, padx=5)

        freq_frame = ttk.Frame(self)
        freq_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(freq_frame, text="调仓频率:").pack(side=tk.LEFT, padx=5)
        self.vars["rebalance"] = tk.StringVar(value="W")
        freq_cb = ttk.Combobox(freq_frame, textvariable=self.vars["rebalance"],
                               values=["W", "M"], state="readonly", width=10)
        freq_cb.pack(side=tk.LEFT, padx=5)

        ttk.Label(freq_frame, text="权重方案:").pack(side=tk.LEFT, padx=5)
        self.vars["method"] = tk.StringVar(value="评分加权")
        method_cb = ttk.Combobox(freq_frame, textvariable=self.vars["method"],
                                 values=["评分加权", "风险平价"], state="readonly", width=15)
        method_cb.pack(side=tk.LEFT, padx=5)

        ttk.Label(freq_frame, text="初始资金(元):").pack(side=tk.LEFT, padx=5)
        self.vars["capital"] = tk.StringVar(value="100000")
        ttk.Entry(freq_frame, textvariable=self.vars["capital"], width=12).pack(side=tk.LEFT, padx=5)

    def get_config(self):
        return {
            "start": self.vars["start"].get(),
            "end": self.vars["end"].get(),
            "rebalance": self.vars["rebalance"].get(),
            "method": self.vars["method"].get(),
            "capital": float(self.vars["capital"].get()),
        }


# ──────────────────────────────────────────────────────────────
# 结果显示面板
# ──────────────────────────────────────────────────────────────
class ResultPanel(ttk.Frame):
    def __init__(self, parent, report_dir):
        super().__init__(parent)
        self.report_dir = report_dir

        self.metrics_frame = ttk.Frame(self)
        self.metrics_frame.pack(fill=tk.X, padx=10, pady=5)

        self.metric_labels = {}
        metrics = ["总收益率(%)", "年化收益率(%)", "最大回撤(%)", "回测天数"]
        for i, m in enumerate(metrics):
            frame = tk.Frame(self.metrics_frame, bg=COLORS["bg_card"], relief=tk.RAISED, bd=1)
            frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=5, pady=5)
            tk.Label(frame, text=m, bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                    font=("Microsoft YaHei", 9)).pack(pady=5)
            self.metric_labels[m] = tk.Label(frame, text="--", bg=COLORS["bg_card"],
                                             fg=COLORS["accent"], font=("Microsoft YaHei", 14, "bold"))
            self.metric_labels[m].pack(pady=5)

        chart_frame = ttk.Frame(self)
        chart_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(chart_frame, variable=self.progress_var,
                                             maximum=100, mode="determinate")
        self.progress_bar.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.progress_label = tk.Label(chart_frame, text="就绪", bg=COLORS["bg_primary"],
                                       fg=COLORS["text_secondary"], font=("Microsoft YaHei", 9))
        self.progress_label.pack(anchor=tk.W, padx=5, pady=(0, 5))

        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        self.fig = Figure(figsize=(10, 5), dpi=100, facecolor=COLORS["bg_primary"])
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor(COLORS["bg_secondary"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btn_frame, text="打开报告", command=self.open_report).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开净值曲线", command=self.open_equity).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="打开交易记录", command=self.open_trades).pack(side=tk.LEFT, padx=5)

    def update_metrics(self, metrics: dict):
        for k, label in self.metric_labels.items():
            value = metrics.get(k, "--")
            label.config(text=str(value))
            if "收益率" in k and isinstance(value, (int, float)):
                color = COLORS["success"] if value >= 0 else COLORS["danger"]
                label.config(fg=color)

    def plot_equity_curve(self, equity_df: pd.DataFrame, pool: list[str], method: str):
        self.ax.clear()
        self.ax.plot(equity_df["date"], equity_df["equity"],
                     label=f"组合 ({method})", color="#2E86AB", linewidth=2)
        self.ax.fill_between(equity_df["date"], equity_df["equity"], alpha=0.1, color="#2E86AB")
        self.ax.set_title("组合净值曲线", color=COLORS["text_primary"], fontsize=14, fontweight="bold")
        self.ax.set_xlabel("日期", color=COLORS["text_secondary"])
        self.ax.set_ylabel("账户资产 (元)", color=COLORS["text_secondary"])
        self.ax.legend(loc="best", facecolor=COLORS["bg_card"], labelcolor=COLORS["text_primary"])
        self.ax.grid(True, alpha=0.3, color=COLORS["border"])
        self.ax.tick_params(colors=COLORS["text_secondary"])
        self.fig.tight_layout()
        self.canvas.draw()

    def open_report(self):
        path = os.path.join(self.report_dir, "portfolio_current.md")
        if not os.path.exists(path):
            path = os.path.join(self.report_dir, "portfolio_report_latest.md")
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("提示", "请先运行报告生成")

    def open_equity(self):
        path = os.path.join(self.report_dir, "portfolio_equity_latest.csv")
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("提示", "请先运行回测")

    def open_trades(self):
        path = os.path.join(self.report_dir, "portfolio_trades_latest.csv")
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("提示", "请先运行回测")


# ──────────────────────────────────────────────────────────────
# 监控日志面板
# ──────────────────────────────────────────────────────────────
class MonitorPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text="实时监控日志", font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="清空日志", command=self.clear).pack(side=tk.RIGHT, padx=5)

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ("time", "code", "range", "status", "bars", "size", "latency", "message")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 yscrollcommand=scrollbar.set, height=18)
        self.tree.heading("time", text="时间")
        self.tree.heading("code", text="股票代码")
        self.tree.heading("range", text="日期段")
        self.tree.heading("status", text="状态")
        self.tree.heading("bars", text="Bars")
        self.tree.heading("size", text="流量KB")
        self.tree.heading("latency", text="延迟ms")
        self.tree.heading("message", text="详情/错误")
        self.tree.column("time", width=120, anchor=tk.CENTER)
        self.tree.column("code", width=90, anchor=tk.CENTER)
        self.tree.column("range", width=130, anchor=tk.CENTER)
        self.tree.column("status", width=70, anchor=tk.CENTER)
        self.tree.column("bars", width=60, anchor=tk.CENTER)
        self.tree.column("size", width=80, anchor=tk.CENTER)
        self.tree.column("latency", width=80, anchor=tk.CENTER)
        self.tree.column("message", width=240, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        self.tree.tag_configure("download", foreground=COLORS["success"])
        self.tree.tag_configure("complete", foreground=COLORS["success"])
        self.tree.tag_configure("skip", foreground=COLORS["warning"])
        self.tree.tag_configure("fail", foreground=COLORS["danger"])

    def append(self, text):
        # text format: [下载] code | beg~ed | N bars | XKB | Yms | 200
        #             [完成] code | beg~ed | N bars
        #             [失败] code | beg~ed | error | Yms
        try:
            parts = text.split(" | ")
            time_str = dt.datetime.now().strftime("%H:%M:%S")
            status_tag = "download"
            status_text = parts[0].replace("[", "").replace("]", "").strip()
            if status_text.startswith("完成"):
                status_tag = "complete"
            elif status_text.startswith("跳过"):
                status_tag = "skip"
            elif status_text.startswith("失败"):
                status_tag = "fail"

            if status_text.startswith("下载"):
                # [下载] code | beg~ed | N bars | XKB | Yms | 200
                code = parts[1].strip() if len(parts) > 1 else ""
                range_str = parts[2].strip() if len(parts) > 2 else ""
                bars = parts[3].strip() if len(parts) > 3 else ""
                size = parts[4].strip() if len(parts) > 4 else ""
                latency = parts[5].strip() if len(parts) > 5 else ""
                message = ""
            elif status_text.startswith("完成"):
                # [完成] code | beg~ed | N bars
                code = parts[1].strip() if len(parts) > 1 else ""
                range_str = parts[2].strip() if len(parts) > 2 else ""
                bars = parts[3].strip() if len(parts) > 3 else ""
                size = ""
                latency = ""
                message = ""
            elif status_text.startswith("失败"):
                # [失败] code | beg~ed | error | Yms
                code = parts[1].strip() if len(parts) > 1 else ""
                range_str = parts[2].strip() if len(parts) > 2 else ""
                bars = ""
                size = ""
                latency = parts[3].strip() if len(parts) > 3 else ""
                message = parts[2].strip() if len(parts) > 2 else ""
            else:
                code = ""
                range_str = ""
                bars = ""
                size = ""
                latency = ""
                message = text

            self.tree.insert("", tk.END, values=(time_str, code, range_str, status_text, bars, size, latency, message),
                             tags=(status_tag,))
            self.tree.see(self.tree.get_children()[-1])
        except Exception:
            pass

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)


# ──────────────────────────────────────────────────────────────
# 新闻监控面板
# ──────────────────────────────────────────────────────────────
class NewsPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text="实时新闻监控", font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="刷新", command=self.refresh).pack(side=tk.RIGHT, padx=5)

        # 顶部：预警级别 + 最后获取时间 + 标签统计
        top_frame = tk.Frame(self, bg=COLORS["bg_secondary"])
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        self.alert_frame = tk.Frame(top_frame, bg=COLORS["bg_card"], relief=tk.RAISED, bd=1)
        self.alert_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5), pady=2)
        self.alert_label = tk.Label(self.alert_frame, text="预警级别: --",
                                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                                     font=("Microsoft YaHei", 11, "bold"))
        self.alert_label.pack(pady=10)

        self.time_frame = tk.Frame(top_frame, bg=COLORS["bg_card"], relief=tk.RAISED, bd=1)
        self.time_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=2)
        self.time_label = tk.Label(self.time_frame, text="最后获取: --\n数据: --",
                                    bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                                    font=("Microsoft YaHei", 10))
        self.time_label.pack(pady=10)

        # 标签统计栏
        self.tag_frame = tk.Frame(self, bg=COLORS["bg_secondary"])
        self.tag_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.tag_labels = {}
        for tag in ["地缘政治", "军事突发", "产业链", "其他"]:
            frm = tk.Frame(self.tag_frame, bg=COLORS["bg_card"], relief=tk.RAISED, bd=1)
            frm.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2)
            lbl = tk.Label(frm, text=f"{tag}: 0", bg=COLORS["bg_card"],
                           fg=COLORS["text_secondary"], font=("Microsoft YaHei", 9, "bold"))
            lbl.pack(pady=5)
            self.tag_labels[tag] = lbl

        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ("time", "tag", "keyword", "content")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                 yscrollcommand=scrollbar.set, height=15)
        self.tree.heading("time", text="时间")
        self.tree.heading("tag", text="标签")
        self.tree.heading("keyword", text="关键词")
        self.tree.heading("content", text="内容")
        self.tree.column("time", width=150, anchor=tk.CENTER)
        self.tree.column("tag", width=90, anchor=tk.CENTER)
        self.tree.column("keyword", width=100, anchor=tk.CENTER)
        self.tree.column("content", width=300, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        self.tree.tag_configure("地缘政治", foreground=COLORS["danger"])
        self.tree.tag_configure("军事突发", foreground=COLORS["accent"])
        self.tree.tag_configure("产业链", foreground=COLORS["success"])
        self.tree.tag_configure("其他", foreground=COLORS["text_secondary"])

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.alert_label.config(text="正在获取新闻...", fg=COLORS["warning"])
        self.time_label.config(text="最后获取: 加载中...")
        self.update()

        def _fetch():
            try:
                result = monitor_news([])
                events = result.get("events", [])
                alert = result.get("alert_level", "normal")
                last_updated = result.get("last_updated")
                tag_counts = result.get("tag_counts", {})
                total = result.get("total", 0)
                self.winfo_toplevel().after(0, lambda: self._update_news(events, alert, last_updated, tag_counts, total))
            except Exception as e:
                self.winfo_toplevel().after(0, lambda: self.alert_label.config(
                    text=f"获取失败: {str(e)[:50]}", fg=COLORS["danger"]))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_news(self, events, alert, last_updated, tag_counts, total):
        color_map = {"normal": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        text_map = {"normal": "正常", "medium": "中等预警", "high": "高度预警"}
        self.alert_label.config(text=f"预警级别: {text_map.get(alert, alert)}",
                                fg=color_map.get(alert, COLORS["text_secondary"]))

        now_str = dt.datetime.now().strftime("%H:%M:%S")
        news_time = str(last_updated) if last_updated else "未知"
        self.time_label.config(text=f"最后获取: {news_time}\n新闻条数: {total}\n刷新时间: {now_str}")

        for tag, lbl in self.tag_labels.items():
            count = tag_counts.get(tag, 0)
            lbl.config(text=f"{tag}: {count}")

        for ev in events:
            tag = ev.get("tag", "其他")
            self.tree.insert("", tk.END, values=(ev.get("time", ""), tag,
                                                  ev.get("keyword", ""),
                                                  ev.get("content", "")[:100]),
                             tags=(tag,))


# ──────────────────────────────────────────────────────────────
# 选股分析面板
# ──────────────────────────────────────────────────────────────
class SelectionPanel(ttk.Frame):
    def __init__(self, parent, pool_list, report_dir):
        super().__init__(parent)
        self.pool_list = pool_list
        self.report_dir = report_dir

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text="选股分析 (股东/大单/龙虎榜/质押/解禁/北向)",
                  font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="刷新分析", command=self.refresh).pack(side=tk.RIGHT, padx=5)
        ttk.Button(header, text="导出报告", command=self.export_report).pack(side=tk.RIGHT, padx=5)

        self.info_label = tk.Label(self, text="点击刷新分析获取多因子数据",
                                   bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                   font=("Microsoft YaHei", 9))
        self.info_label.pack(anchor=tk.W, padx=10, pady=(0, 5))

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ("code", "name", "holder_now", "holder_chg", "big_inflow", "super_big",
                   "lhb_times", "lhb_net", "pledge_risk", "release_ratio", "north_chg",
                   "tech_pattern", "fund_trend", "north_trend", "scenario", "score", "signals")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 yscrollcommand=scrollbar.set, height=18)
        self.tree.heading("code", text="代码")
        self.tree.heading("name", text="名称")
        self.tree.heading("holder_now", text="股东数")
        self.tree.heading("holder_chg", text="股东变化")
        self.tree.heading("big_inflow", text="大单净流入")
        self.tree.heading("super_big", text="超大单")
        self.tree.heading("lhb_times", text="龙虎榜")
        self.tree.heading("lhb_net", text="机构净额")
        self.tree.heading("pledge_risk", text="质押风险")
        self.tree.heading("release_ratio", text="解禁占比%")
        self.tree.heading("north_chg", text="北向变化")
        self.tree.heading("tech_pattern", text="技术形态")
        self.tree.heading("fund_trend", text="资金趋势")
        self.tree.heading("north_trend", text="北向趋势")
        self.tree.heading("scenario", text="综合场景")
        self.tree.heading("score", text="评分")
        self.tree.heading("signals", text="信号")
        for col in columns:
            self.tree.column(col, width=72, anchor=tk.CENTER)
        self.tree.column("code", width=100)
        self.tree.column("name", width=120)
        self.tree.column("signals", width=220, anchor=tk.W)
        self.tree.column("lhb_net", width=90)
        self.tree.column("north_chg", width=90)
        self.tree.column("tech_pattern", width=90)
        self.tree.column("fund_trend", width=100)
        self.tree.column("north_trend", width=100)
        self.tree.column("scenario", width=100)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        self.tree.tag_configure("positive", foreground=COLORS["success"])
        self.tree.tag_configure("negative", foreground=COLORS["danger"])
        self.tree.tag_configure("neutral", foreground=COLORS["text_secondary"])

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.pool_list:
            return

        self.info_label.config(text="正在获取多因子数据...", fg=COLORS["warning"])
        self.update()

        def _fetch():
            rows = []
            for code in self.pool_list:
                try:
                    summary = analyze_selection(code)
                    rows.append(summary)
                except Exception:
                    pass
            self.winfo_toplevel().after(0, lambda: self._update_table(rows))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_table(self, rows):
        self.info_label.config(text=f"分析完成: {len(rows)}/{len(self.pool_list)} 只", fg=COLORS["success"])
        for row in rows:
            code = row["code"]
            name = fetch_name(code)
            holder = row.get("holder", {})
            fund = row.get("fund_flow", {})
            lhb = row.get("lhb", {})
            pledge = row.get("pledge", {})
            release = row.get("release", {})
            north = row.get("north_flow", {})
            tech = row.get("tech", {})
            fund_trend = row.get("fund_trend", {})
            north_trend = row.get("north_trend", {})
            scenario = row.get("scenario", {})
            score = row.get("score", 0)
            signals = "; ".join(row.get("signals", []))

            h_now = holder.get("shareholder_count_now", "--") or "--"
            h_chg = holder.get("shareholder_change", "--")
            if h_chg is not None:
                h_chg = f"{int(h_chg):+d}"
            else:
                h_chg = "--"

            big = fund.get("big_net_inflow") or 0
            super_big = fund.get("super_big_net_inflow") or 0
            lhb_times = lhb.get("lhb_times") if lhb.get("lhb_times") is not None else "--"
            lhb_net = lhb.get("lhb_inst_net") if lhb.get("lhb_inst_net") is not None else "--"
            if lhb_net != "--":
                lhb_net = f"{lhb_net/10000:.0f}万"
            pledge_risk = pledge.get("pledge_risk") or "--"
            release_ratio = release.get("release_ratio") if release.get("release_ratio") is not None else "--"
            if release_ratio != "--":
                release_ratio = f"{release_ratio:.2f}%"
            north_chg = north.get("hold_change") if north.get("hold_change") is not None else "--"
            if north_chg != "--":
                north_chg = f"{north_chg/10000:.0f}万"
            tech_pattern = tech.get("pattern") or "--"
            fund_trend_text = fund_trend.get("trend") or "--"
            north_trend_text = north_trend.get("trend") or "--"
            scenario_text = scenario.get("scenario") or "--"

            tag = "positive" if score > 0.5 else "negative" if score < 0 else "neutral"

            self.tree.insert("", tk.END, values=(
                code, name, h_now, h_chg,
                f"{big/10000:.0f}万", f"{super_big/10000:.0f}万",
                lhb_times, lhb_net,
                pledge_risk, release_ratio, north_chg,
                tech_pattern,
                fund_trend_text, north_trend_text, scenario_text,
                f"{score:.2f}", signals
            ), tags=(tag,))

    def export_report(self):
        if not self.tree.get_children():
            messagebox.showinfo("提示", "请先刷新分析")
            return

        path = os.path.join(self.report_dir, "portfolio_selection.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 选股分析报告\n\n")
            f.write("| 代码 | 名称 | 股东数 | 股东变化 | 大单 | 超大单 | 龙虎榜 | 机构净额 | 质押风险 | 解禁占比 | 北向变化 | 技术形态 | 资金趋势 | 北向趋势 | 综合场景 | 评分 | 信号 |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
            for item in self.tree.get_children():
                vals = self.tree.item(item)["values"]
                f.write(f"| {'| '.join(str(v) for v in vals)} |\n")

        messagebox.showinfo("完成", f"选股报告已导出:\n{path}")


# ──────────────────────────────────────────────────────────────
# 评分面板
# ──────────────────────────────────────────────────────────────
class ScorePanel(ttk.Frame):
    def __init__(self, parent, pool_list, report_dir):
        super().__init__(parent)
        self.pool_list = pool_list
        self.report_dir = report_dir

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(btn_frame, text="个股评分", font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="刷新评分", command=self.refresh_scores).pack(side=tk.RIGHT, padx=5)

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ("code", "name", "score", "trend", "macd", "rsi", "vol", "volatility")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 yscrollcommand=scrollbar.set, height=12)
        self.tree.heading("code", text="代码")
        self.tree.heading("name", text="名称")
        self.tree.heading("score", text="综合评分")
        self.tree.heading("trend", text="趋势")
        self.tree.heading("macd", text="MACD")
        self.tree.heading("rsi", text="RSI")
        self.tree.heading("vol", text="量价")
        self.tree.heading("volatility", text="波动率")
        for col in columns:
            self.tree.column(col, width=80, anchor=tk.CENTER)
        self.tree.column("code", width=100)
        self.tree.column("name", width=120)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        parent_tk = self.winfo_toplevel()
        if parent_tk.winfo_ismapped():
            parent_tk.after(100, self.refresh_scores)
        else:
            self.bind("<Map>", lambda e: self.after(100, self.refresh_scores))

    def refresh_scores(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.pool_list:
            return

        def _fetch():
            scores_data = []
            for code in self.pool_list:
                try:
                    end = dt.date.today().strftime("%Y-%m-%d")
                    start = (dt.date.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d")
                    df = fetch_price(code, start, end)
                    if not df.empty and len(df) >= 30:
                        result = score_stock(df, code)
                        details = result.get("details", {})
                        scores_data.append({
                            "code": code,
                            "score": result.get("score", 0),
                            "trend": details.get("趋势", 0),
                            "macd": details.get("MACD", 0),
                            "rsi": details.get("RSI", 0),
                            "vol": details.get("量价", 0),
                            "volatility": details.get("波动率", 0),
                        })
                except Exception:
                    pass
            self.winfo_toplevel().after(0, lambda: self._update_table(scores_data))

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_table(self, scores_data):
        for data in scores_data:
            score = data["score"]
            tag = "positive" if score > 0.3 else "negative" if score < 0 else "neutral"
            name = fetch_name(data["code"])
            self.tree.insert("", tk.END, values=(
                data["code"], name, f"{score:.3f}", f"{data['trend']:.2f}",
                f"{data['macd']:.2f}", f"{data['rsi']:.2f}",
                f"{data['vol']:.2f}", f"{data['volatility']:.2f}"
            ), tags=(tag,))

        self.tree.tag_configure("positive", foreground=COLORS["success"])
        self.tree.tag_configure("negative", foreground=COLORS["danger"])
        self.tree.tag_configure("neutral", foreground=COLORS["text_secondary"])


# ──────────────────────────────────────────────────────────────
# 主应用窗口
# ──────────────────────────────────────────────────────────────
class PortfolioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("一揽子股票选股组合分析系统")
        self.root.geometry("1500x900")
        self.root.minsize(1300, 700)

        self.report_dir = os.path.dirname(os.path.abspath(__file__))
        self.pool_list = DEFAULT_POOL.copy()

        ModernStyle(root)
        self._build_ui()

        self.status_var = tk.StringVar(value="就绪")
        status_bar = tk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN,
                              anchor=tk.W, bg=COLORS["bg_secondary"], fg=COLORS["text_secondary"],
                              font=("Microsoft YaHei", 9))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["bg_secondary"], height=60)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        title = tk.Label(header, text="📊 一揽子股票选股组合分析系统",
                         bg=COLORS["bg_secondary"], fg=COLORS["accent"],
                         font=("Microsoft YaHei", 16, "bold"))
        title.pack(side=tk.LEFT, padx=20, pady=10)

        btn_frame = tk.Frame(header, bg=COLORS["bg_secondary"])
        btn_frame.pack(side=tk.RIGHT, padx=20, pady=10)

        self.run_backtest_btn = tk.Button(btn_frame, text="▶ 运行回测", command=self.run_backtest,
                                          bg=COLORS["accent"], fg="white",
                                          font=("Microsoft YaHei", 10, "bold"), padx=15, pady=5,
                                          relief=tk.FLAT, cursor="hand2")
        self.run_backtest_btn.pack(side=tk.LEFT, padx=5)

        self.run_report_btn = tk.Button(btn_frame, text="📄 生成报告", command=self.run_report,
                                        bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                                        font=("Microsoft YaHei", 10), padx=15, pady=5,
                                        relief=tk.FLAT, cursor="hand2")
        self.run_report_btn.pack(side=tk.LEFT, padx=5)

        self.run_news_btn = tk.Button(btn_frame, text="📰 新闻监控", command=self.run_news,
                                      bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                                      font=("Microsoft YaHei", 10), padx=15, pady=5,
                                      relief=tk.FLAT, cursor="hand2")
        self.run_news_btn.pack(side=tk.LEFT, padx=5)

        main_container = tk.Frame(self.root, bg=COLORS["bg_primary"])
        main_container.pack(fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(main_container, bg=COLORS["bg_secondary"], width=380)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        self.pool_panel = PoolPanel(sidebar, self.pool_list, self._on_pool_change)
        self.pool_panel.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Label(sidebar, text="参数配置", font=("Microsoft YaHei", 11, "bold")).pack(
            anchor=tk.W, padx=10, pady=(10, 5))
        self.config_panel = ConfigPanel(sidebar)
        self.config_panel.pack(fill=tk.X, padx=5, pady=5)

        self.notebook = ttk.Notebook(main_container)
        self.notebook.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.result_panel = ResultPanel(self.notebook, self.report_dir)
        self.notebook.add(self.result_panel, text="📈 回测结果")

        self.monitor_panel = MonitorPanel(self.notebook)
        self.notebook.add(self.monitor_panel, text="🔍 实时监控")

        self.score_panel = ScorePanel(self.notebook, self.pool_list, self.report_dir)
        self.notebook.add(self.score_panel, text="⭐ 个股评分")

        self.news_panel = NewsPanel(self.notebook)
        self.notebook.add(self.news_panel, text="📰 新闻监控")

        self.selection_panel = SelectionPanel(self.notebook, self.pool_list, self.report_dir)
        self.notebook.add(self.selection_panel, text="🎯 选股分析")

    def _on_pool_change(self):
        self.score_panel.pool_list = self.pool_list.copy()
        if hasattr(self, 'selection_panel'):
            self.selection_panel.pool_list = self.pool_list.copy()
        self.status_var.set(f"股票池已更新: {len(self.pool_list)} 只")

    def _set_running(self, running: bool):
        state = tk.DISABLED if running else tk.NORMAL
        self.run_backtest_btn.config(state=state)
        self.run_report_btn.config(state=state)
        self.run_news_btn.config(state=state)

    def run_backtest(self):
        if not self.pool_list:
            messagebox.showwarning("警告", "股票池为空，请先添加股票")
            return

        config = self.config_panel.get_config()
        pool = self.pool_list.copy()

        self._set_running(True)
        self.status_var.set("正在运行回测...")
        self.result_panel.progress_var.set(0)
        self.result_panel.progress_label.config(text="准备中...")
        self.monitor_panel.clear()

        def _run():
            try:
                def _progress(text, pct):
                    self.root.after(0, lambda: (
                        self.result_panel.progress_var.set(pct),
                        self.result_panel.progress_label.config(text=text),
                        self.status_var.set(f"回测中: {text}")
                    ))

                def _log(text):
                    self.root.after(0, lambda: self.monitor_panel.append(text))

                equity_df, metrics, trades_df = backtest_portfolio(
                    pool, config["start"], config["end"],
                    rebalance_freq=config["rebalance"],
                    method=config["method"],
                    initial_capital=config["capital"],
                    progress_callback=_progress,
                    log_callback=_log,
                )

                if equity_df.empty:
                    self.root.after(0, lambda: messagebox.showerror("错误", "回测失败：数据不足"))
                    return

                equity_path = os.path.join(self.report_dir, "portfolio_equity_latest.csv")
                equity_df.to_csv(equity_path, index=False, encoding="utf-8-sig")
                if not trades_df.empty:
                    trades_path = os.path.join(self.report_dir, "portfolio_trades_latest.csv")
                    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")

                macro_data = fetch_macro(config["start"], config["end"])
                news_df = fetch_news()
                macro_score = score_macro(macro_data, news_df)

                report_path = os.path.join(self.report_dir, "portfolio_report_latest.md")
                generate_report(equity_df, metrics, pool, config["method"],
                               macro_score, save_path=report_path)

                chart_path = os.path.join(self.report_dir, "portfolio_chart_latest.png")
                plot_portfolio(equity_df, pool, config["method"], save_path=chart_path)

                self.root.after(0, lambda: self._on_backtest_complete(equity_df, metrics, pool, config["method"]))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("回测失败", str(e)))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_run, daemon=True).start()

    def _on_backtest_complete(self, equity_df, metrics, pool, method):
        self.result_panel.update_metrics(metrics)
        self.result_panel.plot_equity_curve(equity_df, pool, method)
        self.notebook.select(0)
        self.status_var.set(f"回测完成: 年化 {metrics.get('年化收益率(%)', '--')}%, "
                           f"最大回撤 {metrics.get('最大回撤(%)', '--')}%")

    def run_report(self):
        if not self.pool_list:
            messagebox.showwarning("警告", "股票池为空，请先添加股票")
            return

        self._set_running(True)
        self.status_var.set("正在生成报告...")

        def _run():
            try:
                pool = self.pool_list.copy()
                scores = {}
                for code in pool:
                    end = dt.date.today().strftime("%Y-%m-%d")
                    start = (dt.date.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d")
                    df = fetch_price(code, start, end)
                    result = score_stock(df, code)
                    scores[code] = result.get("score", 0)

                prices = {}
                for code in pool:
                    end = dt.date.today().strftime("%Y-%m-%d")
                    start = (dt.date.today() - dt.timedelta(days=5)).strftime("%Y-%m-%d")
                    df = fetch_price(code, start, end)
                    if not df.empty:
                        prices[code] = df["close"].iloc[-1]

                config = self.config_panel.get_config()
                weights = build_portfolio(scores, prices, method=config["method"])

                macro_data = fetch_macro(
                    (dt.date.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d"),
                    dt.date.today().strftime("%Y-%m-%d")
                )
                news_df = fetch_news()
                macro_score = score_macro(macro_data, news_df)

                report_path = os.path.join(self.report_dir, "portfolio_current.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(generate_report(pd.DataFrame(), {}, pool, config["method"], macro_score))
                    f.write("\n## 当前建议组合\n\n")
                    f.write("| 代码 | 名称 | 评分 | 权重 |\n|---|---|---|---|\n")
                    for code, w in sorted(weights.items(), key=lambda x: -x[1]):
                        s = scores.get(code, 0)
                        name = fetch_name(code)
                        f.write(f"| {code} | {name} | {s:.3f} | {w*100:.1f}% |\n")

                score_path = os.path.join(self.report_dir, "portfolio_scores.png")
                plot_score_breakdown(scores, save_path=score_path)

                self.root.after(0, lambda: messagebox.showinfo("完成", f"报告已生成:\n{report_path}"))
                self.root.after(0, lambda: self.status_var.set("报告生成完成"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("失败", str(e)))
            finally:
                self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_run, daemon=True).start()

    def run_news(self):
        self.notebook.select(3)
        self.news_panel.refresh()
        self.status_var.set("正在获取新闻...")


# ──────────────────────────────────────────────────────────────
# 启动入口
# ──────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app = PortfolioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
