# Changelog

所有项目的显著变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [2.5.0] - 2026-08-14

### 新增
- **系统托盘最小化功能**：最小化到托盘、事件提示小窗口、双击恢复、右键菜单（恢复/退出）
- **自定义图标资源**：money.jpg 作为窗口图标、datanaly.jpeg 作为托盘默认图标、target.jpeg 作为事件闪烁图标
- **个股诊断器双击弹窗放大**：双击诊断文本/图表可弹出独立放大窗口，支持 ESC 关闭
- **诊断图表四象限标识**：左上①价格走势、右上②股东数量、左下③大单净流入、右下④筹码集中度，每个子图增加标题编号、网格、图例、轴标签、marker 样式
- **股票池人性化优化**：输入框占位提示文本、拼音首字母非连续缩写匹配（如 `gmt` → 贵州茅台）、多选弹窗批量添加
- **多市场支持**：A股/港股/美股数据获取（腾讯 ifzq + akshare），日股/韩股/台湾股/欧股暂标记不支持
- **本地缓存模块**：股票代码名称对照表（5543+ 只 A 股）、个股价格缓存、三级更新策略（定期/即时/触发式）

### 修复
- 修复 `DiagnosisPanel._show_diagnosis` 使用 `self.root.after()` 导致的 `AttributeError`，改用 `self.winfo_toplevel().after()`
- 修复 `PoolPanel` 缺少 `self.status_label` 初始化导致的 `AttributeError`
- 修复 `fetch_stock_basic_info` akshare 接口超时问题，切换主数据源为腾讯 `qt.gtimg.cn`
- 修复 `fetch_sector_info` akshare 板块接口无限阻塞问题，增加线程超时包装逻辑
- 修复 `search_stocks()` 中文名称匹配逻辑，支持纯中文查询
- 修复 `classify_channel` confidence 格式从百分比字符串改为 float 数值（0.0-1.0）
- 修复财联社 API 失效问题，实现多源回退机制（cls.cn → akshare stock_news_main_cx → stock_news_em）
- 修复 `plot_diagnosis_charts` 函数内部异常导致返回空字典的问题

### 改进
- 股票池整合为单数据源：`PortfolioApp.pool_list` 作为唯一主数据源，子面板通过 `refresh_pool()` 统一刷新
- 新闻分类新增军事突发、供应链、地缘政治三类关键词标签
- 选股分析扩展至 17 类因子（新增趋势分析、均线排列、双底双顶、支撑阻力、综合场景判断）
- 实时监控日志颜色高亮（下载/完成/失败/跳过）
- 新闻面板展示股票数据最后获取时间戳 + 新闻最后获取时间戳
- 诊断器查询支持多种输入格式（`sh.600519`、`600519`、`贵州茅台`、`茅台`）

### 性能
- 个股价格数据本地缓存到 `data/cache/prices/{market}_{code}.csv`
- 数据获取日志按阶段 emit 结构化日志（股票代码、日期段、Bars 数、流量大小、请求延迟、HTTP 状态码）
- 图表 DPI 提升至 150，生成质量更高

---

## [2.4.0] - 2026-08-13

### 新增
- 新增个股诊断器面板（DiagnosisPanel）— 8 维度诊断 + 报告导出
- 新增 5 个多因子分析函数：`analyze_lhb()`、`analyze_pledge()`、`analyze_restricted_release()`、`analyze_north_flow()`、`analyze_margin()`
- 新增 7 个场景/趋势分析函数：`analyze_fund_flow_trend`、`analyze_holder_trend`、`analyze_north_flow_trend`、`analyze_ma_alignment`、`analyze_pattern_double`、`analyze_support_resistance`、`classify_scenario`
- 新增技术形态识别函数：`classify_channel()`（上升/下降/横盘通道 + 突破/跌破）
- 个股诊断器支持代码/缩写/中文模糊查询
- 个股诊断器展示详细基本面、板块关系、K线图、筹码图表

### 改进
- 选股分析扩展至 17 类因子输出
- SelectionPanel 表格扩展至 17 列
- 新闻面板新增分类标签筛选栏

### 修复
- 修复 `fetch_news()` 财联社 API 失效问题
- 修复 `fetch_holder_data()` 缺失 `import akshare as ak` 导致的 `NameError`
- 修复 `analyze_selection` 返回字段缺失问题

---

## [2.3.0] - 2026-08-12

### 新增
- 新增「🔍 实时监控」标签页，展示数据获取日志（时间、股票代码、日期段、状态、Bars、流量KB、延迟ms）
- 新增 `fetch_holder_data()` 函数，获取股东数量、十大股东、大单交易数据
- 新增 `analyze_holder_correlation()` 函数，计算股东数量变化、大单净流入占比与未来股价波动的相关性
- 新增「📊 选股分析」标签页，支持选择标的查看股东/大单数据与股价相关性分析

### 改进
- `fetch_price()` 函数新增 `log_callback` 参数，按阶段 emit 结构化日志
- 新闻分类新增 MILITARY_KEYWORDS、SUPPLY_CHAIN_KEYWORDS、BREAKING_KEYWORDS 三类关键词标签
- `fetch_news()` 返回结果新增 `category`、`publish_time`、`sentiment` 字段

### 修复
- 修复 `ScorePanel` 初始化线程安全问题：先检查父窗口是否已映射，未映射时绑定 `<Map>` 事件后再调度 `after`

---

## [2.2.0] - 2026-08-11

### 新增
- 股票池管理面板人性化优化：拼音首字母映射、多选批量添加、提示文本
- 多市场支持：`_market_type()` 新增 bj/hk/us/jp/kr/tw/eu 识别
- `fetch_name()` 支持多市场名称查询（腾讯 `qt.gtimg.cn`）
- `fetch_price()` 扩展为多分支（A股/港股用腾讯 fqkline，美股用 akshare `stock_us_daily`）
- 本地缓存模块：股票代码名称对照表 + 个股价格缓存 + 三级更新策略
- 搜索功能支持拼音首字母非连续缩写匹配（如 `gmt` 匹配 GZMT）

### 改进
- 默认回测区间改为最近 2 年（730 天）
- `_ensure_stock_index()` 为股票名称索引增加 `py_init` 列
- 股票搜索优先使用本地对照表，本地无数据时才在线查询

### 修复
- 修复 `CACHE_DIR` 常量缺失导致的 `NameError`
- 修复 `dt.datetime.now()` 未定义问题
- 修复 `search_stocks()` 中文名称匹配逻辑
- 修复 `search_stocks()` 返回字段缺失问题

---

## [2.1.0] - 2026-08-10

### 新增
- 新增 `MonitorPanel` 实时监控标签页
- 新增 `NewsPanel` 新闻监控标签页，支持分类筛选
- 新增 `SelectionPanel` 选股分析标签页

### 改进
- 新闻分类能力：新增军事突发、供应链、地缘政治三类关键词标签
- 新闻面板展示新闻最后获取时间戳 + 股票数据最后获取时间戳

### 修复
- 修复 `ScorePanel` 线程安全问题
- 修复财联社 API 失效问题，实现多源回退机制

---

## [2.0.0] - 2026-08-09

### 新增
- 四层评分体系（宏观 / 政策 / 行业 / 个股）
- 组合构建（评分加权 + 风险平价）
- 回测复盘引擎（周度/月度调仓）
- GUI 可视化（7 标签页）
- 报告输出（Markdown + PNG + CSV）

### 技术栈
- tkinter GUI 框架
- pandas + numpy 数据处理
- matplotlib 图表绘制
- akshare + 腾讯 ifzq 数据源

---

## [1.0.0] - 2026-08-07

### 新增
- 5 种内置策略：双均线、MACD、布林带、RSI、海龟策略
- 三市场支持：sh、sz、hk
- 风控模块：止损、止盈、最大回撤熔断、ATR 动态仓位
- 参数优化：网格搜索最优参数组合
- 多股对比：一次回测 N 只股票
- 数据导出：CSV（净值曲线、交易记录、绩效指标）

---

*文档版本：v1.0 — 2026-08-14*
