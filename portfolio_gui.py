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
from tray_icon import TrayIcon
from portfolio_selector import (
    fetch_price, fetch_name, score_stock, build_portfolio,
    fetch_macro, score_macro, fetch_news,
    backtest_portfolio, generate_report, plot_portfolio, plot_score_breakdown,
    monitor_news, DEFAULT_POOL,
    analyze_selection, analyze_technical,
    analyze_fund_flow_trend, analyze_holder_trend, analyze_north_flow_trend,
    analyze_ma_alignment, analyze_pattern_double, analyze_support_resistance,
    fetch_stock_basic_info, fetch_sector_info, plot_diagnosis_charts,
    _clean_code, search_stocks,
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
        self.entry = ttk.Entry(input_frame, width=30)
        self.entry.pack(side=tk.LEFT, padx=5)
        self.entry.insert(0, "支持: 600519 / 茅台 / gmt / 比亚迪")
        self.entry.config(foreground=COLORS.get("text_secondary", "#888888"))
        self.entry.bind("<FocusIn>", lambda e: self._on_entry_focus_in())
        self.entry.bind("<FocusOut>", lambda e: self._on_entry_focus_out())
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

        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.status_label = ttk.Label(status_frame, text="", foreground=COLORS["text_secondary"],
                                      font=("Microsoft YaHei", 9))
        self.status_label.pack(side=tk.LEFT)

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

    def _on_entry_focus_in(self):
        if self.entry.get().startswith("支持:"):
            self.entry.delete(0, tk.END)
            self.entry.config(foreground=COLORS.get("text", "#000000"))

    def _on_entry_focus_out(self):
        if not self.entry.get().strip():
            self.entry.insert(0, "支持: 600519 / 茅台 / gmt / 比亚迪")
            self.entry.config(foreground=COLORS.get("text_secondary", "#888888"))

    def add_stock(self):
        text = self.entry.get().strip()
        if not text:
            return
        raw_items = [c.strip() for c in text.replace("，", ",").split(",") if c.strip()]
        added = []
        skipped = []
        for raw in raw_items:
            code = _clean_code(raw)
            if not code:
                continue
            if code in self.pool_list:
                skipped.append(code)
                continue
            # 如果输入看起来像代码，直接添加；否则模糊查询
            if re.fullmatch(r"\d{6}", code):
                self.pool_list.append(code)
                added.append(code)
            else:
                hits = search_stocks(code, limit=8)
                if not hits:
                    skipped.append(raw)
                elif len(hits) == 1:
                    c = hits[0]["code"]
                    if c not in self.pool_list:
                        self.pool_list.append(c)
                        added.append(c)
                    else:
                        skipped.append(c)
                else:
                    selected = self._pick_from_suggestions(hits)
                    if selected:
                        for sel in (selected if isinstance(selected, list) else [selected]):
                            if sel not in self.pool_list:
                                self.pool_list.append(sel)
                                added.append(sel)
                            else:
                                skipped.append(sel)
        self.entry.delete(0, tk.END)
        self.refresh_list()
        self.on_change()
        if added:
            self.status_label.config(text=f"已添加: {', '.join(added)}")
        if skipped:
            self.status_label.config(text=f"已添加: {', '.join(added)}; 跳过/未找到: {', '.join(skipped)}")

    def _pick_from_suggestions(self, hits: list[dict]) -> str | None:
        """弹窗让用户从候选中选择一只股票"""
        pick = {"value": None}
        top = tk.Toplevel(self.winfo_toplevel())
        top.title("选择股票")
        top.geometry("420x320")
        top.transient(self.winfo_toplevel())
        top.grab_set()

        ttk.Label(top, text="找到多只候选，请点击选择：").pack(pady=5)
        listbox = tk.Listbox(top, font=("Microsoft YaHei", 10), selectmode=tk.EXTENDED)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        for h in hits:
            listbox.insert(tk.END, f"{h['code']}  {h['name']}")

        def on_confirm():
            sels = listbox.curselection()
            pick["value"] = [hits[i]["code"] for i in sels] if sels else None
            top.destroy()

        def on_double(_):
            on_confirm()

        listbox.bind("<Double-Button-1>", on_double)
        ttk.Button(top, text="确定", command=on_confirm).pack(pady=5)
        ttk.Label(top, text="提示: Ctrl/Shift 可多选，双击快速确认",
                  foreground=COLORS.get("text_secondary", "#888888"),
                  font=("Microsoft YaHei", 8)).pack(pady=(0, 5))
        self.winfo_toplevel().wait_window(top)
        return pick["value"]

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

    def refresh_pool(self):
        self.refresh()

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
# 个股诊断器面板
# ──────────────────────────────────────────────────────────────
class DiagnosisPanel(ttk.Frame):
    def __init__(self, parent, pool_list, report_dir):
        super().__init__(parent)
        self.pool_list = pool_list
        self.report_dir = report_dir

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(header, text="🔬 个股诊断器 (多因子 + 技术形态 + 趋势 + 场景)",
                  font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="诊断选中", command=self.diagnose_selected).pack(side=tk.RIGHT, padx=5)

        # 搜索框
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        ttk.Label(search_frame, text="🔍 查询诊断:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<Return>", lambda e: self.diagnose_from_search())
        ttk.Button(search_frame, text="诊断", command=self.diagnose_from_search).pack(side=tk.LEFT, padx=5)
        ttk.Label(search_frame, text="支持: 代码(sh.600519) / 缩写(600519) / 中文(贵州茅台)",
                  foreground=COLORS["text_secondary"], font=("Microsoft YaHei", 8)).pack(side=tk.LEFT, padx=10)

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # 左侧股票列表
        left = ttk.Frame(main)
        main.add(left, weight=1)
        ttk.Label(left, text="股票池 (双击选择)").pack(anchor=tk.W, padx=5, pady=5)
        self.pool_tree = ttk.Treeview(left, columns=("code", "name"), show="headings", height=20)
        self.pool_tree.heading("code", text="代码")
        self.pool_tree.heading("name", text="名称")
        self.pool_tree.column("code", width=100)
        self.pool_tree.column("name", width=120)
        self.pool_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.pool_tree.bind("<Double-1>", lambda e: self.diagnose_selected())
        for code in self.pool_list:
            self.pool_tree.insert("", tk.END, values=(code, fetch_name(code)))

        # 右侧诊断结果
        right = ttk.Frame(main)
        main.add(right, weight=3)
        self.info_label = tk.Label(right, text="双击左侧股票开始诊断",
                                   bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                   font=("Microsoft YaHei", 9))
        self.info_label.pack(anchor=tk.W, padx=10, pady=5)

        self.result_text = tk.Text(right, wrap=tk.WORD, font=("Consolas", 10),
                                   bg=COLORS["bg_primary"], fg=COLORS["text_primary"],
                                   relief=tk.FLAT, padx=10, pady=10)
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.result_text.bind("<Double-Button-1>", self._open_diagnosis_popup)
        self.result_text.tag_config("title", font=("Microsoft YaHei", 12, "bold"), foreground=COLORS["accent"])
        self.result_text.tag_config("section", font=("Microsoft YaHei", 10, "bold"), foreground=COLORS["accent"])
        self.result_text.tag_config("positive", foreground=COLORS["success"])
        self.result_text.tag_config("negative", foreground=COLORS["danger"])
        self.result_text.tag_config("neutral", foreground=COLORS["text_secondary"])
        # 双击诊断文本放大查看
        self.result_text.bind("<Double-1>", self._open_diagnosis_popup)

        # 图表区域
        chart_frame = ttk.LabelFrame(right, text="📈 诊断图表")
        chart_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.chart_canvas_frame = ttk.Frame(chart_frame)
        self.chart_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chart_label = tk.Label(self.chart_canvas_frame,
                                   text="诊断完成后显示图表",
                                   bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                   font=("Microsoft YaHei", 9))
        self.chart_label.pack(anchor=tk.CENTER, expand=True)

        # K线图叠加控制
        kline_ctrl = ttk.Frame(right)
        kline_ctrl.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(kline_ctrl, text="叠加K线:").pack(side=tk.LEFT)
        self.kline_overlay_var = tk.StringVar(value="")
        ttk.Entry(kline_ctrl, textvariable=self.kline_overlay_var, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(kline_ctrl, text="刷新图表", command=self._refresh_chart).pack(side=tk.LEFT, padx=5)
        self.kline_overlay_var.trace_add("write", lambda *_: self._refresh_chart())

        # 当前诊断代码
        self._current_code = None
        self._current_chart_paths = {}

    def refresh_pool(self):
        # 刷新左侧股票池列表
        for item in self.pool_tree.get_children():
            self.pool_tree.delete(item)
        for code in self.pool_list:
            self.pool_tree.insert("", tk.END, values=(code, fetch_name(code)))

    def diagnose_selected(self):
        sel = self.pool_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在左侧选择一只股票")
            return
        code = self.pool_tree.item(sel[0])["values"][0]
        self._run_diagnosis(code)

    def diagnose_from_search(self):
        text = self.search_var.get().strip()
        if not text:
            messagebox.showinfo("提示", "请输入股票代码或名称")
            return
        code = self._resolve_code(text)
        if not code:
            messagebox.showwarning("未找到", f"未找到匹配股票: {text}")
            return
        self.search_var.set(code)
        self._run_diagnosis(code)

    def _resolve_code(self, text: str) -> str | None:
        """将输入解析为标准代码: 直接代码 / 6位缩写 / 中文名称"""
        text = text.strip()
        # 已是标准代码
        if re.match(r'^(sh|sz|hk)\.\d{6}$', text):
            return text
        # 6位数字缩写
        if re.match(r'^\d{6}$', text):
            prefix = "sh" if text.startswith(('600', '601', '603', '605', '688')) else "sz"
            return f"{prefix}.{text}"
        # 中文/字母名称模糊匹配
        name_map = {}
        for code in self.pool_list:
            try:
                name = fetch_name(code)
                name_map[name] = code
            except Exception:
                pass
        # 去除全角空格/半角空格用于匹配
        norm = lambda s: s.replace(' ', '').replace('　', '')
        norm_map = {norm(k): k for k in name_map}
        norm_text = norm(text)
        # 精确匹配（去除空格）
        if norm_text in norm_map:
            return name_map[norm_map[norm_text]]
        # 模糊匹配（去除空格）
        matches = [n for n in norm_map if norm_text in n]
        if len(matches) == 1:
            return name_map[norm_map[matches[0]]]
        elif len(matches) > 1:
            names = "\n".join([f"{norm_map[n]} ({name_map[norm_map[n]]})" for n in matches])
            messagebox.showinfo("多只匹配", f"找到 {len(matches)} 只:\n{names}")
            return None
        return None

    def _run_diagnosis(self, code: str):
        self.result_text.delete("1.0", tk.END)
        self.info_label.config(text=f"正在诊断 {code} ...", fg=COLORS["warning"])
        self.update()

        def _run():
            try:
                result = analyze_selection(code)
                basic = fetch_stock_basic_info(code)
                sector = fetch_sector_info(code)
                # 生成图表
                end = dt.datetime.today().strftime("%Y-%m-%d")
                start = (dt.datetime.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d")
                df = fetch_price(code, start, end)
                holders_df = pd.DataFrame()
                fund_df = pd.DataFrame()
                cyq_df = pd.DataFrame()
                try:
                    holders_df = ak.stock_circulate_stock_holder(symbol=_clean_code(code))
                except Exception:
                    pass
                try:
                    fund_df = ak.stock_individual_fund_flow(symbol=_clean_code(code))
                except Exception:
                    pass
                try:
                    cyq_df = ak.stock_cyq_em(symbol=_clean_code(code), adjust="qfq")
                except Exception:
                    pass
                chart_paths = plot_diagnosis_charts(code, df, holders_df, fund_df, cyq_df,
                                                    os.path.join(self.report_dir, f"diag_{_clean_code(code)}"))
                self.winfo_toplevel().after(0, lambda: self._show_diagnosis(code, result, basic, sector, chart_paths))
            except Exception as e:
                self.winfo_toplevel().after(0, lambda: self.info_label.config(
                    text=f"诊断失败: {str(e)[:60]}", fg=COLORS["danger"]))

        threading.Thread(target=_run, daemon=True).start()

    def _open_diagnosis_popup(self, event=None):
        """双击诊断文本弹出放大窗口"""
        popup = tk.Toplevel(self)
        popup.title("个股诊断详情")
        popup.geometry("900x700")
        popup.configure(bg=COLORS["bg_primary"])

        txt = tk.Text(popup, wrap=tk.WORD, font=("Consolas", 11),
                       bg=COLORS["bg_primary"], fg=COLORS["text_primary"],
                       relief=tk.FLAT, padx=15, pady=15)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.tag_config("title", font=("Microsoft YaHei", 14, "bold"), foreground=COLORS["accent"])
        txt.tag_config("section", font=("Microsoft YaHei", 11, "bold"), foreground=COLORS["accent"])
        txt.tag_config("positive", foreground=COLORS["success"])
        txt.tag_config("negative", foreground=COLORS["danger"])
        txt.tag_config("neutral", foreground=COLORS["text_secondary"])

        content = self.result_text.get("1.0", tk.END)
        for tag in ("title", "section", "positive", "negative", "neutral"):
            txt.tag_config(tag, font=self.result_text.tag_cget(tag, "font"),
                           foreground=self.result_text.tag_cget(tag, "foreground"))
        txt.insert("1.0", content)
        txt.config(state=tk.DISABLED)

        popup.bind("<Escape>", lambda e: popup.destroy())
        txt.bind("<Escape>", lambda e: popup.destroy())

    def _show_diagnosis(self, code: str, result: dict, basic: dict = None, sector: dict = None, chart_paths: dict = None):
        self.result_text.delete("1.0", tk.END)
        self.info_label.config(text=f"诊断完成: {code} | 评分 {result['score']:.2f}",
                               fg=COLORS["success"])
        txt = self.result_text
        basic = basic or {}
        sector = sector or {}
        chart_paths = chart_paths or {}

        def w(tag, text):
            txt.insert(tk.END, text + "\n", tag)

        def section(title):
            w("section", f"\n▌ {title}")
            w("neutral", "─" * 40)

        def kv(key, val, fmt=str):
            if val is None or val == "":
                return
            w("neutral", f"  {key}: {fmt(val)}")

        # 标题
        name = basic.get("name") or fetch_name(code)
        w("title", f"【{code} {name}】 综合诊断")
        w("neutral", f"综合评分: {result['score']:.2f}")
        scenario = result.get("scenario", {})
        conf = scenario.get("confidence", 0)
        if isinstance(conf, (int, float)) and conf > 1:
            conf = conf / 100
        w("neutral", f"综合场景: {scenario.get('scenario','未知')} (建议: {scenario.get('action','观望')})")
        w("neutral", f"置信度: {conf:.0%}")

        # 0. 基本信息
        section("0. 基本信息")
        kv("股票简称", basic.get("name"))
        kv("所属行业", basic.get("industry"))
        kv("主营业务", basic.get("main_business"))
        kv("总股本", basic.get("capital"))
        kv("流通股", basic.get("float_shares"))
        kv("总市值", basic.get("total_mv"))
        kv("市盈率(动态)", basic.get("pe"))
        kv("市净率", basic.get("pb"))
        kv("股权质押", basic.get("pledge_ratio"))
        kv("融资余额", basic.get("margin_balance"))
        kv("上市时间", basic.get("updated_at"))
        for key in ["pe", "pb", "pledge_ratio", "margin_balance"]:
            val = basic.get(key)
            if val and ("-" in str(val) or "亏" in str(val) or "无" in str(val)):
                w("neutral", f"  ⚠ {key}: {val}")

        # 0.1 板块分类与排名
        section("0.1 板块分类与排名")
        kv("所属行业", sector.get("industry"))
        kv("行业排名", sector.get("industry_rank"))
        concepts = sector.get("concept", [])
        if concepts:
            w("neutral", f"  概念板块: {', '.join(concepts)}")
        related = sector.get("related", [])
        if related:
            w("neutral", "  同板块相关:")
            for r in related[:10]:
                w("neutral", f"    {r[0]} {r[1]}")

        # 1. 股东分析
        section("1. 股东分析")
        holder = result.get("holder", {})
        holder_trend = result.get("holder_trend", {})
        kv("当前股东数", holder.get("shareholder_count_now"), lambda x: f"{x:,} 户")
        chg = holder.get("shareholder_change")
        if chg is not None:
            color = "positive" if chg < 0 else "negative" if chg > 0 else "neutral"
            w(color, f"  股东变化: {chg:+.0f} 户 ({'筹码集中' if chg < 0 else '筹码分散' if chg > 0 else '持平'})")
        kv("股东趋势", holder_trend.get("trend"))
        kv("连续期数", holder_trend.get("consecutive_periods"), lambda x: f"{x} 期")
        kv("趋势强度", holder_trend.get("intensity"), lambda x: f"{x:.2f}")
        for sig in result.get("signals", []):
            if "股东" in sig:
                w("neutral", f"  • {sig}")

        # 2. 大单资金
        section("2. 大单/超大单资金")
        fund = result.get("fund_flow", {})
        fund_trend = result.get("fund_trend", {})
        kv("大单净流入", fund.get("big_net_inflow"), lambda x: f"{x/10000:.0f} 万")
        kv("超大单净流入", fund.get("super_big_net_inflow"), lambda x: f"{x/10000:.0f} 万")
        kv("大单占比", fund.get("big_ratio"), lambda x: f"{x:.2f}%")
        kv("超大单占比", fund.get("super_big_ratio"), lambda x: f"{x:.2f}%")
        kv("资金趋势", fund_trend.get("trend"))
        kv("连续天数", fund_trend.get("consecutive_days"), lambda x: f"{x} 日")
        kv("趋势方向", fund_trend.get("direction"))
        kv("趋势强度", fund_trend.get("intensity"), lambda x: f"{x:.2f}")
        for sig in result.get("signals", []):
            if "大单" in sig or "资金" in sig:
                w("neutral", f"  • {sig}")

        # 3. 龙虎榜
        section("3. 龙虎榜")
        lhb = result.get("lhb", {})
        kv("上榜次数", lhb.get("lhb_times"), lambda x: f"{x} 次")
        kv("机构净额", lhb.get("lhb_inst_net"), lambda x: f"{x/10000:.0f} 万")
        kv("游资净额", lhb.get("lhb_retail_net"), lambda x: f"{x/10000:.0f} 万")
        for sig in result.get("signals", []):
            if "龙虎榜" in sig:
                w("neutral", f"  • {sig}")

        # 4. 股权质押
        section("4. 股权质押")
        pledge = result.get("pledge", {})
        kv("质押比例", pledge.get("pledge_ratio"), lambda x: f"{x:.2f}%")
        kv("质押风险", pledge.get("pledge_risk"))
        for sig in result.get("signals", []):
            if "质押" in sig:
                w("neutral", f"  • {sig}")

        # 5. 限售解禁
        section("5. 限售解禁")
        release = result.get("release", {})
        kv("解禁数量", release.get("release_shares"), lambda x: f"{x/10000:.0f} 万股")
        kv("解禁占比", release.get("release_ratio"), lambda x: f"{x:.2f}%")
        kv("解禁日期", release.get("release_date"))
        for sig in result.get("signals", []):
            if "解禁" in sig:
                w("neutral", f"  • {sig}")

        # 6. 北向资金
        section("6. 北向资金")
        north = result.get("north_flow", {})
        north_trend = result.get("north_trend", {})
        kv("持股数量", north.get("hold_count"), lambda x: f"{x/10000:.0f} 万股")
        kv("持股变化", north.get("hold_change"), lambda x: f"{x/10000:.0f} 万股")
        kv("北向趋势", north_trend.get("trend"))
        kv("连续天数", north_trend.get("consecutive_days"), lambda x: f"{x} 日")
        kv("趋势方向", north_trend.get("direction"))
        kv("变化总量", north_trend.get("total_change"), lambda x: f"{x/10000:.0f} 万股")
        for sig in result.get("signals", []):
            if "北向" in sig:
                w("neutral", f"  • {sig}")

        # 7. 技术形态
        section("7. 技术形态")
        tech = result.get("tech", {})
        kv("形态识别", tech.get("pattern"))
        kv("通道斜率", tech.get("slope"), lambda x: f"{x:.4f}" if isinstance(x, (int, float)) else str(x))
        kv("R² 置信", tech.get("confidence"), lambda x: f"{x:.0f}%" if isinstance(x, (int, float)) else str(x))
        kv("年化波动率", tech.get("volatility"), lambda x: f"{x:.2f}%" if isinstance(x, (int, float)) else str(x))
        kv("突破状态", tech.get("breakout"))
        kv("20日高点", tech.get("high_20"), lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x))
        kv("20日低点", tech.get("low_20"), lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x))
        kv("当前价", tech.get("current"), lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x))
        kv("突破强度", tech.get("strength"), lambda x: f"{x:.0f}%" if isinstance(x, (int, float)) else str(x))
        kv("低波动原因", tech.get("low_vol_reason"))
        if tech.get("updated_at"):
            kv("数据日期", tech.get("updated_at"))

        # 7.1 均线排列
        ma = tech.get("ma_alignment", {})
        if ma:
            kv("均线排列", ma.get("alignment"))
            kv("MA5", ma.get("ma5"), lambda x: f"{x:.2f}")
            kv("MA10", ma.get("ma10"), lambda x: f"{x:.2f}")
            kv("MA20", ma.get("ma20"), lambda x: f"{x:.2f}")
            kv("MA60", ma.get("ma60"), lambda x: f"{x:.2f}")
            kv("均线信号", ma.get("signal"))

        # 7.2 双底双顶
        double = tech.get("double_pattern", {})
        if double:
            kv("形态", double.get("pattern"))
            kv("颈线", double.get("neckline"), lambda x: f"{x:.2f}")
            kv("目标价", double.get("target"), lambda x: f"{x:.2f}")
            kv("可靠性", double.get("reliability"), lambda x: f"{x:.0f}%")
            kv("已确认", double.get("confirmation"))

        # 7.3 支撑阻力
        sr = tech.get("support_resistance", {})
        if sr:
            kv("支撑位", sr.get("support"), lambda x: f"{x:.2f}")
            kv("支撑强度", sr.get("support_strength"), lambda x: f"{x} 次")
            kv("阻力位", sr.get("resistance"), lambda x: f"{x:.2f}")
            kv("阻力强度", sr.get("resistance_strength"), lambda x: f"{x} 次")
            kv("当前位置", sr.get("position"))

        # 综合信号汇总
        section("8. 综合信号")
        for sig in result.get("signals", []):
            if any(k in sig for k in ["场景", "均线", "W底", "M头", "突破", "跌破", "趋势"]):
                w("positive" if "利好" in sig or "增持" in sig or "流入" in sig or "上升" in sig or "W底" in sig else
                  "negative" if "利空" in sig or "减持" in sig or "流出" in sig or "下降" in sig or "M头" in sig or "跌破" in sig else
                  "neutral", f"  ► {sig}")

        # 底部建议
        action = scenario.get("action", "观望")
        if action == "买入":
            w("positive", f"\n★ 建议操作: {action}")
        elif action == "卖出":
            w("negative", f"\n★ 建议操作: {action}")
        else:
            w("neutral", f"\n★ 建议操作: {action}")

        # 保存当前状态并显示图表
        self._current_code = code
        self._current_chart_paths = chart_paths or {}
        if self._current_chart_paths.get("diagnosis"):
            self.winfo_toplevel().after(100, self._show_chart)
        else:
            self.chart_label.config(text="暂无图表数据")

    def _show_chart(self):
        # 清空图表区域
        for widget in self.chart_canvas_frame.winfo_children():
            widget.destroy()
        path = self._current_chart_paths.get("diagnosis")
        if not path or not os.path.exists(path):
            self.chart_label = tk.Label(self.chart_canvas_frame, text="图表未生成",
                                       bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                       font=("Microsoft YaHei", 9))
            self.chart_label.pack(anchor=tk.CENTER, expand=True)
            return
        # 显示图片
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            w = self.chart_canvas_frame.winfo_width() or 800
            h = self.chart_canvas_frame.winfo_height() or 600
            ratio = min(w / img.width, h / img.height, 1.0)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(self.chart_canvas_frame, image=photo, bg=COLORS["bg_primary"])
            lbl.image = photo
            lbl.pack(anchor=tk.CENTER, expand=True)
        except Exception:
            self.chart_label = tk.Label(self.chart_canvas_frame, text=f"图表: {path}",
                                       bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                       font=("Microsoft YaHei", 9))
            self.chart_label.pack(anchor=tk.CENTER, expand=True)

    def _refresh_chart(self):
        if not self._current_code:
            return
        overlay_text = self.kline_overlay_var.get().strip()
        if not overlay_text:
            # 重新生成默认图表
            try:
                end = dt.datetime.today().strftime("%Y-%m-%d")
                start = (dt.datetime.today() - dt.timedelta(days=365)).strftime("%Y-%m-%d")
                df = fetch_price(self._current_code, start, end)
                holders_df = pd.DataFrame()
                fund_df = pd.DataFrame()
                cyq_df = pd.DataFrame()
                try:
                    holders_df = ak.stock_circulate_stock_holder(symbol=_clean_code(self._current_code))
                except Exception:
                    pass
                try:
                    fund_df = ak.stock_individual_fund_flow(symbol=_clean_code(self._current_code))
                except Exception:
                    pass
                try:
                    cyq_df = ak.stock_cyq_em(symbol=_clean_code(self._current_code), adjust="qfq")
                except Exception:
                    pass
                paths = plot_diagnosis_charts(self._current_code, df, holders_df, fund_df, cyq_df,
                                              os.path.join(self.report_dir, f"diag_{_clean_code(self._current_code)}"))
                self._current_chart_paths = paths
                self._show_chart()
            except Exception:
                pass
            return
        # 解析叠加代码
        codes = [self._current_code]
        for part in re.split(r"[,，\s]+", overlay_text):
            part = part.strip()
            if not part:
                continue
            if re.match(r'^(sh|sz|hk)\.\d{6}$', part):
                codes.append(part)
            elif re.match(r'^\d{6}$', part):
                prefix = "sh" if part.startswith(('600', '601', '603', '605', '688')) else "sz"
                codes.append(f"{prefix}.{part}")
        # 生成叠加K线图
        try:
            end = dt.datetime.today().strftime("%Y-%m-%d")
            start = (dt.datetime.today() - dt.timedelta(days=180)).strftime("%Y-%m-%d")
            fig, axes = plt.subplots(1, 1, figsize=(10, 5), dpi=100)
            colors = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0"]
            for idx, c in enumerate(codes[:5]):
                try:
                    d = fetch_price(c, start, end)
                    if not d.empty and len(d) >= 20:
                        d = d.sort_values("date")
                        close = d["close"]
                        close_norm = close / close.iloc[0] * 100
                        axes.plot(d["date"], close_norm, label=c, color=colors[idx % len(colors)], linewidth=1.5)
                except Exception:
                    pass
            axes.set_title("叠加K线对比 (归一化)", fontsize=12)
            axes.legend()
            axes.grid(True, alpha=0.3)
            plt.tight_layout()
            save_path = os.path.join(self.report_dir, f"overlay_{_clean_code(self._current_code)}.png")
            plt.savefig(save_path, dpi=100, bbox_inches="tight")
            plt.close()
            self._current_chart_paths["overlay"] = save_path
            # 显示叠加图
            for widget in self.chart_canvas_frame.winfo_children():
                widget.destroy()
            try:
                from PIL import Image, ImageTk
                img = Image.open(save_path)
                w = self.chart_canvas_frame.winfo_width() or 800
                h = self.chart_canvas_frame.winfo_height() or 600
                ratio = min(w / img.width, h / img.height, 1.0)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(self.chart_canvas_frame, image=photo, bg=COLORS["bg_primary"])
                lbl.image = photo
                lbl.pack(anchor=tk.CENTER, expand=True)
            except Exception:
                self.chart_label = tk.Label(self.chart_canvas_frame, text=f"图表: {save_path}",
                                           bg=COLORS["bg_primary"], fg=COLORS["text_secondary"],
                                           font=("Microsoft YaHei", 9))
                self.chart_label.pack(anchor=tk.CENTER, expand=True)
        except Exception:
            pass


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

    def refresh_pool(self):
        self.refresh_scores()

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
        try:
            self.root.iconbitmap(os.path.join(self.report_dir, "data", "cache", "money.ico"))
        except Exception:
            pass
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

        # ── 系统托盘集成 ──
        icon_dir = os.path.join(self.report_dir, "data", "cache")
        self._tray = TrayIcon(
            root,
            title="一揽子股票选股组合分析系统",
            icon_path=os.path.join(icon_dir, "datanaly.ico"),
            flash_icon_path=os.path.join(icon_dir, "target.ico"),
            on_restore=self._restore_from_tray,
            on_exit=self._quit_from_tray,
        )
        self._tray.start()
        root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)

    def _minimize_to_tray(self):
        self._tray.notify("最小化", "程序已最小化到系统托盘\n双击恢复，右键查看更多")
        self.root.withdraw()

    def _restore_from_tray(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _quit_from_tray(self):
        try:
            self._tray.stop()
        except Exception:
            pass
        self.root.destroy()

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

        self.diagnosis_panel = DiagnosisPanel(self.notebook, self.pool_list, self.report_dir)
        self.notebook.add(self.diagnosis_panel, text="🔬 个股诊断")

    def _on_pool_change(self):
        # 子面板持有同一 list 引用，直接刷新 UI 即可
        self.score_panel.refresh_pool()
        self.selection_panel.refresh_pool()
        self.diagnosis_panel.refresh_pool()
        self.pool_panel.refresh_list()
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
