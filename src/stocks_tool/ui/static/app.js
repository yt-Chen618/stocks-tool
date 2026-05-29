const LANGUAGE_STORAGE_KEY = "stocks-tool-language";
const DEFAULT_LANGUAGE = "zh";
const BROKER_REQUEST_TIMEOUT_MS = 25000;
const PRE_OPEN_BOARD_TIMEOUT_MS = 35000;
const PRE_OPEN_OVERLAY_TIMEOUT_MS = 70000;
const TEXT_NODE_ORIGINALS = new WeakMap();
const ATTRIBUTE_ORIGINALS = new WeakMap();
const TRANSLATIONS = {
  zh: {
    "Paper Trading Desk": "纸账户交易台",
    "Stocks Tool Workbench": "Stocks Tool 工作台",
    "Paper": "纸交易",
    "API Docs": "API 文档",
    "Account": "账户",
    "Account Control": "账户控制",
    "Refresh": "刷新",
    "Broker Account": "券商账户",
    "Sync Account": "同步账户",
    "Sync Orders": "同步订单",
    "Cash Balance": "现金余额",
    "Net Liquidation": "净清算值",
    "Buying Power": "购买力",
    "Latest Snapshot": "最新快照",
    "Auto Reconciliation": "自动对账",
    "Account Sync": "账户同步",
    "Orders Sync": "订单同步",
    "Select a broker account to view scheduler state.": "选择券商账户后查看调度状态。",
    "No account selected.": "未选择账户。",
    "Ready": "就绪",
    "Strategy": "策略",
    "Strategy Center": "策略中心",
    "Risk Calendar": "风险日历",
    "Market Event Calendar": "市场事件日历",
    "Events": "事件",
    "Upcoming Events": "即将到来的事件",
    "Experiment": "实验",
    "Strategy Experiment Bench": "策略实验台",
    "Active Proposals": "待处理提案",
    "Latest Run": "最近运行",
    "Signals": "信号",
    "Reviews": "复盘",
    "No strategy proposals loaded.": "尚未加载策略提案。",
    "No strategy runs recorded.": "尚无策略运行记录。",
    "No strategy signals recorded.": "尚无策略信号记录。",
    "No strategy reviews recorded.": "尚无策略复盘记录。",
    "Proposals": "提案",
    "Strategy Proposals": "策略提案",
    "No strategy experiment proposals yet.": "尚无策略实验提案。",
    "Runs": "运行",
    "Strategy Runs": "策略运行",
    "No strategy runs recorded yet.": "尚无策略运行记录。",
    "Signal Feed": "信号流",
    "No strategy signals recorded yet.": "尚无策略信号记录。",
    "Review Feed": "复盘流",
    "No strategy reviews recorded yet.": "尚无策略复盘记录。",
    "No market events loaded yet.": "尚未加载市场事件。",
    "No upcoming market events recorded.": "尚无即将到来的市场事件。",
    "Bull Put": "牛市看跌价差",
    "Bull Put Strategy": "牛市看跌策略",
    "Entry Status": "入场状态",
    "Monitoring": "监控中",
    "Daily Cap": "日内上限",
    "Scan Ready": "可扫描",
    "Resolve Controls": "处理控制项",
    "Next Action": "下一步",
    "No runtime state loaded.": "尚未加载运行状态。",
    "Daily Entries": "今日入场",
    "Waiting for first scan.": "等待首次扫描。",
    "Daily Realized PnL": "今日已实现盈亏",
    "No spread closes recorded today.": "今日暂无价差平仓记录。",
    "Last Scan": "最近扫描",
    "Waiting for first bull put scan.": "等待首次牛市看跌扫描。",
    "Auto Entry": "自动入场",
    "Enabled": "启用",
    "Disabled": "停用",
    "Manual Pause": "手动暂停",
    "Running": "运行中",
    "Paused": "已暂停",
    "Kill Switch": "熔断开关",
    "Off": "关闭",
    "On": "开启",
    "Paused Symbols": "暂停标的",
    "Strategy controls apply to new bull put entries only. Existing spreads remain monitored.": "策略控制只影响新的牛市看跌入场，已有价差仍会被监控。",
    "Save Controls": "保存控制",
    "Run Scan": "运行扫描",
    "Run Review": "运行复盘",
    "Last Skip": "最近跳过",
    "Latest Skip Reason": "最近跳过原因",
    "No bull put scan has been skipped yet.": "尚无牛市看跌扫描被跳过。",
    "Review": "复盘",
    "Latest Review": "最新复盘",
    "No bull put strategy review has been generated yet.": "尚未生成牛市看跌策略复盘。",
    "Journal": "日志",
    "Recent Strategy Notes": "近期策略笔记",
    "No bull put strategy notes for this account yet.": "此账户暂无牛市看跌策略笔记。",
    "Spreads": "价差",
    "Bull Put Monitor": "牛市看跌监控",
    "Active Spreads": "活跃价差",
    "No spread data loaded.": "尚未加载价差数据。",
    "Exit Pending": "平仓待处理",
    "Latest Exit Action": "最近平仓动作",
    "No spread exits recorded.": "暂无价差平仓记录。",
    "Last Monitor": "最近监控",
    "Waiting for first spread check.": "等待首次价差检查。",
    "Underlying": "标的",
    "Expiry": "到期日",
    "Width": "宽度",
    "Status": "状态",
    "Entry Credit": "入场权利金",
    "Entry / Risk": "入场/风险",
    "Monitor Mark": "监控估值",
    "PnL / Exit Distance": "盈亏/退出距离",
    "Credit": "权利金",
    "Latest Action": "最近动作",
    "Actions": "操作",
    "No bull put spreads loaded.": "尚未加载牛市看跌价差。",
    "Macro": "宏观",
    "Live Macro": "实时宏观",
    "Real-time Macro Board": "实时宏观板",
    "Load Live Macro": "加载实时宏观",
    "Load Option Overlays": "加载期权叠加层",
    "Save Current Board": "保存当前看板",
    "Downside Score": "下行分数",
    "Loading pre-open assessment...": "正在加载盘前评估...",
    "Signals": "信号",
    "Risk Proxies": "风险代理",
    "Waiting for market proxy signals.": "等待市场代理信号。",
    "Options": "期权",
    "QQQ / SPY Put Check": "QQQ / SPY 看跌检查",
    "Waiting for directional put snapshots.": "等待方向性看跌期权快照。",
    "Surface": "波动率面",
    "Option Chain Analysis": "期权链分析",
    "Waiting for front and next-expiry option chain analysis.": "等待近月和次近月期权链分析。",
    "Opening Follow-through": "开盘延续复盘",
    "Stored Review": "存档复盘",
    "Stored Opening Follow-through": "存档开盘复盘",
    "Select a broker account to load the latest pre-open capture and opening review.": "选择券商账户后加载最新盘前记录和开盘复盘。",
    "Portfolio": "持仓",
    "Holdings Overview": "持仓总览",
    "Open Positions": "持仓数量",
    "Gross Market Value": "总市值",
    "Unrealized PnL": "未实现盈亏",
    "Largest Holding": "最大持仓",
    "Symbol": "标的",
    "Type": "类型",
    "Qty": "数量",
    "Avg Cost": "平均成本",
    "Market Value": "市值",
    "Weight": "权重",
    "No positions in latest snapshot.": "最新快照中没有持仓。",
    "Execution": "执行",
    "Execution Desk": "执行工作台",
    "Ticket": "订单",
    "Order Ticket": "订单票据",
    "Side": "方向",
    "Buy": "买入",
    "Sell": "卖出",
    "Quantity": "数量",
    "Order Type": "订单类型",
    "Market": "市价",
    "Limit": "限价",
    "Stop": "止损",
    "Time In Force": "订单时效",
    "Limit Price": "限价",
    "Stop Price": "止损价",
    "Remark": "备注",
    "Submit Order": "提交订单",
    "Workflow": "流程",
    "Selected Order": "选中订单",
    "Select an order from the table to manage it.": "从表格中选择订单进行管理。",
    "Execution Summary": "成交摘要",
    "Latest Fill Snapshot": "最新成交快照",
    "No fills recorded for this order yet.": "此订单尚无成交记录。",
    "Review Workflow": "复盘流程",
    "Entry Type": "记录类型",
    "Plan": "计划",
    "Note": "备注",
    "Title": "标题",
    "Tags": "标签",
    "Notes": "笔记",
    "Select an order to save a plan note or post-trade review.": "选择订单后保存计划笔记或交易复盘。",
    "Save Entry": "保存记录",
    "Select an order to load journal entries.": "选择订单后加载日志记录。",
    "Replace": "改单",
    "Update Working Order": "更新工作订单",
    "Replace Order": "修改订单",
    "Orders": "订单",
    "Updated": "更新时间",
    "No orders loaded.": "尚未加载订单。",
    "No orders for this account.": "此账户暂无订单。",
    "Manage": "管理",
    "Monitor": "监控",
    "Cancel": "取消",
    "Board Status": "看板状态",
    "Regime": "市场状态",
    "Plain Put View": "裸买看跌视图",
    "Preferred Vehicle": "偏好工具",
    "Action": "动作",
    "Coverage": "覆盖范围",
    "Gap Chase Risk": "追跳空风险",
    "Session": "交易时段",
    "Target Session": "目标交易日",
    "Review Status": "复盘状态",
    "Checkpoints": "检查点",
    "Next Open": "下次开盘",
    "Action Bias": "动作偏向",
    "Session Px": "时段价",
    "Prev Close": "前收盘",
    "Change": "变动",
    "Strike": "行权价",
    "DTE": "到期天数",
    "Bid / Ask": "买一/卖一",
    "Mid / Spread": "中间价/价差",
    "Delta / IV": "Delta / 隐波",
    "Spot Distance": "距现货",
    "Spot": "现货",
    "Front ATM IV": "近月 ATM 隐波",
    "Next ATM IV": "次近月 ATM 隐波",
    "Term Slope": "期限斜率",
    "Front Put Skew": "近月看跌偏斜",
    "Front Median Spread": "近月中位价差",
    "Front Expiry": "近月到期",
    "Next Expiry": "次近月到期",
    "OI / Vol": "持仓/成交",
    "Spread / Delta": "价差/Delta",
    "ATM Put": "ATM 看跌",
    "ATM Delta / IV": "ATM Delta/隐波",
    "Put Skew Leg": "看跌偏斜腿",
    "Skew IV Lift": "偏斜隐波抬升",
    "Spread Buckets": "价差分组",
    "Median Spread": "中位价差",
    "External ID": "外部 ID",
    "Order Type": "订单类型",
    "Price Logic": "价格逻辑",
    "Filled Qty": "成交数量",
    "Avg Fill": "平均成交价",
    "Last Fill": "最近成交",
    "Derived from the latest broker order detail snapshot for this order.": "由此订单最新券商详情快照生成。",
    "Plan linked": "已关联计划",
    "Execution linked": "已关联成交",
    "Order linked": "已关联订单",
    "No journal entries linked to this order yet.": "此订单暂无关联日志。",
    "Optional for stop": "止损单可选",
    "Required for stop": "止损单必填",
    "Optional broker note": "可选券商备注",
    "Optional replace note": "可选改单备注",
    "Post-trade review headline": "交易后复盘标题",
    "discipline, entry, risk": "纪律, 入场, 风险",
    "What happened, what was learned, and what changes next time.": "记录发生了什么、学到了什么、下次如何调整。",
    "Idle": "空闲",
    "Live": "实时",
    "Refreshing": "刷新中",
    "Timed Out": "超时",
    "Circuit Open": "熔断中",
    "Stale": "旧数据",
    "Partial": "部分数据",
    "Unavailable": "不可用",
    "Success": "成功",
    "Syncing": "同步中",
    "Error": "错误",
    "Kill Switch": "熔断",
    "Selective Pause": "选择性暂停",
    "Broad Downside Risk": "广泛下行风险",
    "Selective Downside Risk": "选择性下行风险",
    "Balanced": "均衡",
    "Reasonable": "可考虑",
    "Selective": "选择性",
    "Avoid": "回避",
    "Wait For Open Confirmation": "等待开盘确认",
    "Wait For Failed Bounce": "等待反弹失败",
    "Use Intraday Confirmation": "使用盘中确认",
    "Selective Probe Only": "仅小仓试探",
    "Low": "低",
    "Medium": "中",
    "High": "高",
    "Premarket": "盘前",
    "Regular": "常规交易",
    "Postmarket": "盘后",
    "Weekend": "周末",
    "Holiday": "假日",
    "Complete": "完成",
    "Active": "进行中",
    "Pending": "等待",
    "Captured": "已捕获",
    "Confirmed": "确认",
    "Mixed": "混合",
    "Failed": "失败",
    "In Progress": "进行中",
    "Awaiting Open": "等待开盘",
    "Bearish": "偏空",
    "Supportive": "支撑",
    "Neutral": "中性",
    "Preferred": "偏好",
    "Reference": "参考",
    "Tight": "紧",
    "Workable": "可用",
    "Wide": "宽",
    "Front Loaded": "近月偏贵",
    "Next Richer": "次近月偏贵",
    "Flat": "平坦",
    "Unclear": "不清晰",
    "Open": "打开",
    "Closed": "已关闭",
    "Take Profit": "止盈",
    "Stop Loss": "止损",
    "Short Strike Breach": "短腿行权价被突破",
    "Expiration Guard": "到期保护",
    "Submitted": "已提交",
    "Filled": "已成交",
    "Partially Filled": "部分成交",
    "Canceled": "已取消",
    "Rejected": "已拒绝",
    "created": "已创建",
    "submitted": "已提交",
    "partially_filled": "部分成交",
    "filled": "已成交",
    "canceled": "已取消",
    "rejected": "已拒绝",
    "open": "打开",
    "closed": "已关闭",
    "entry_pending_long": "等待买入保护腿",
    "entry_pending_short": "等待卖出短腿",
    "exit_pending_short": "等待买回短腿",
    "exit_pending_long": "等待卖出长腿",
    "entry_failed": "入场失败",
    "rolled_back": "已回滚",
    "rollback_failed": "回滚失败",
    "Configured": "已配置",
    "Missing": "缺失",
    "No active holdings": "暂无持仓",
    "No open positions": "暂无持仓",
    "No ranked holdings": "暂无持仓排序",
    "No active spreads": "暂无活跃价差",
    "Daily cap reached": "已达到日内上限",
    "Monitor open spread": "监控当前价差",
    "Wait next session": "等待下一交易日",
    "Scan for entry": "扫描入场",
    "Resolve runtime controls": "处理运行控制",
    "Entry blocked": "入场受阻",
    "No pending spread exits": "暂无待处理平仓",
    "No exit actions recorded yet": "暂无平仓动作",
    "Waiting for first monitor run": "等待首次监控运行",
    "No open or exit-pending spreads are being monitored.": "当前没有打开或平仓待处理价差在监控中。",
    "Last Update": "最近更新",
    "Mark": "估值",
    "P/L": "盈亏",
    "BE": "盈亏平衡",
    "Max Loss": "最大亏损",
    "TP Gap": "止盈距离",
    "SL Gap": "止损距离",
    "Next Check": "下次检查",
    "No monitor snapshot": "暂无监控快照",
    "No monitor snapshot.": "暂无监控快照。",
    "Within thresholds": "未触发退出",
    "Live board loaded with partial coverage. Option overlays skipped for fast macro refresh.": "实时宏观代理已加载；为保持刷新速度，本次跳过期权叠加层。",
    "Option overlays were skipped so the macro board can refresh without waiting on slow option-chain calls.": "已跳过期权叠加层，避免宏观板等待较慢的期权链请求。",
    "Option overlays were skipped for fast macro refresh. Use Load Option Overlays to inspect QQQ / SPY puts.": "为保持宏观板快速刷新，本次跳过期权叠加层。需要查看 QQQ / SPY 看跌期权时请点击“加载期权叠加层”。",
    "Option-chain overlays were skipped for fast macro refresh. Load option overlays when you need volatility and liquidity detail.": "为保持宏观板快速刷新，本次跳过期权链叠加层。需要波动率和流动性细节时请加载期权叠加层。",
    "Refreshing live macro board with option overlays...": "正在刷新实时宏观板和期权叠加层...",
    "Select a broker account before saving the macro board.": "保存宏观板前请先选择券商账户。",
    "Load the live macro board before saving it.": "保存前请先加载实时宏观板。",
    "Only a live or partial live macro board can be saved.": "只能保存实时或部分实时宏观板。",
    "Saving macro board failed.": "保存宏观板失败。",
    "Select a broker account to load bull put controls.": "选择券商账户后加载牛市看跌控制项。",
    "No bull put skip reason recorded.": "暂无牛市看跌跳过原因。",
    "No bull put spreads for this account.": "此账户暂无牛市看跌价差。",
    "Load the live macro board to classify market tone.": "加载实时宏观板以判断市场状态。",
    "QQQ / SPY directional put bias will render here.": "QQQ / SPY 方向性看跌偏向将在此显示。",
    "Waiting for proxy dispersion.": "等待代理分化信号。",
    "No major bearish trigger is active": "暂无主要看跌触发器",
    "No bearish trigger is strong enough to favor plain index puts right now.": "当前没有足够强的看跌触发器支持裸买指数看跌。",
    "No market proxy signals are available.": "暂无市场代理信号。",
    "No short-dated reference puts were found.": "未找到短期期权参考。",
    "No option chain analysis is available.": "暂无期权链分析。",
    "No opening checkpoints were stored for this run.": "此次运行未存储开盘检查点。",
    "Stored pre-open assessment.": "已存储的盘前评估。",
    "Opening follow-through review is still waiting for the first checkpoint.": "开盘延续复盘仍在等待第一个检查点。",
    "Opening review is still waiting for this checkpoint.": "开盘复盘仍在等待此检查点。",
    "No liquid strikes were sampled for this expiry.": "此到期日没有采样到流动行权价。",
    "Filled, canceled, and rejected orders can be refreshed but not replaced.": "已成交、已取消和已拒绝订单只能刷新，不能改单。",
    "Select a broker account first.": "请先选择券商账户。",
    "Account sync already in progress.": "账户同步正在进行。",
    "Order sync already in progress.": "订单同步正在进行。",
    "Market orders use the selected paper account and do not require a price.": "市价单使用当前纸账户，不需要填写价格。",
    "Limit orders require a limit price.": "限价单必须填写限价。",
    "Stop orders require a stop price. Add an optional limit price to send a stop-limit style order.": "止损单必须填写止损价。可选填限价以提交类似止损限价单。",
    "Market order replacements update quantity only.": "市价改单只更新数量。",
    "Limit order replacements require a limit price.": "限价改单必须填写限价。",
    "Stop order replacements require a stop price. Limit price remains optional.": "止损改单必须填写止损价，限价仍为可选。",
    "Loading dashboard...": "正在加载工作台...",
    "Dashboard updated. Option strategy panels loaded first. Macro overlays are available on demand.": "工作台已更新。期权策略面板优先加载，宏观覆盖层可按需加载。",
    "No broker account selected.": "未选择券商账户。",
    "Enter a symbol.": "请输入标的。",
    "Refreshing live macro board...": "正在刷新实时宏观板...",
    "Account sync failed.": "账户同步失败。",
    "Order sync failed.": "订单同步失败。",
    "Bull put controls update failed.": "牛市看跌控制项更新失败。",
    "Bull put scan failed.": "牛市看跌扫描失败。",
    "Bull put review failed.": "牛市看跌复盘失败。",
    "Order submit failed.": "订单提交失败。",
    "Order refresh failed.": "订单刷新失败。",
    "Spread refresh failed.": "价差刷新失败。",
    "Spread monitor failed.": "价差监控失败。",
    "Order cancel failed.": "订单取消失败。",
    "Order replace failed.": "改单失败。",
    "Journal entry save failed.": "日志保存失败。",
    "Bull put review completed.": "牛市看跌复盘完成。",
    "Bull put scan completed without a new spread.": "牛市看跌扫描完成，未开新价差。"
  },
};

const state = {
  accounts: [],
  selectedAccountId: "",
  watchlists: [],
  orders: [],
  spreads: [],
  runtime: null,
  strategyExperiment: { proposals: [], runs: [], signals: [], reviews: [] },
  marketEvents: [],
  executions: [],
  journals: [],
  brokerStatus: null,
  latestSnapshot: null,
  selectedOrderId: "",
  quote: null,
  quoteStatus: { kind: "idle", detail: "Load a quote manually to keep the dashboard fast.", reason: "" },
  preOpenAssessment: null,
  preOpenStatus: { kind: "idle", detail: "Macro board is available on demand so option strategy requests stay first.", reason: "" },
  preOpenRuns: [],
  preOpenSeedAttempts: {},
  language: readStoredLanguage(),
};

const els = {};
let isApplyingLanguage = false;
let languageObserver = null;
let languageFrame = null;

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  wireEvents();
  startLanguageObserver();
  updateLanguageControls();
  applyLanguage();
  syncTicketOrderFields();
  renderSelectedOrder();
  await loadDashboard();
});

function bindElements() {
  els.languageOptions = Array.from(document.querySelectorAll("[data-lang-option]"));
  els.accountSelect = document.getElementById("account-select");
  els.statusBanner = document.getElementById("status-banner");
  els.reconciliationStrip = document.getElementById("reconciliation-strip");
  els.metricsStrip = document.getElementById("metrics-strip");
  els.positionsSummaryStrip = document.getElementById("positions-summary-strip");
  els.holdingsFocus = document.getElementById("holdings-focus");
  els.watchlistsBody = document.getElementById("watchlists-body");
  els.strategyRuntimeStrip = document.getElementById("strategy-runtime-strip");
  els.strategyControlsForm = document.getElementById("strategy-controls-form");
  els.strategyAutoEntry = document.getElementById("strategy-auto-entry");
  els.strategyManualPause = document.getElementById("strategy-manual-pause");
  els.strategyKillSwitch = document.getElementById("strategy-kill-switch");
  els.strategyPausedSymbols = document.getElementById("strategy-paused-symbols");
  els.strategyControlsHint = document.getElementById("strategy-controls-hint");
  els.saveStrategyControls = document.getElementById("save-strategy-controls");
  els.runStrategyScan = document.getElementById("run-strategy-scan");
  els.runStrategyReview = document.getElementById("run-strategy-review");
  els.strategySkipCard = document.getElementById("strategy-skip-card");
  els.strategyJournalFeed = document.getElementById("strategy-journal-feed");
  els.strategyReviewCard = document.getElementById("strategy-review-card");
  els.strategyExperimentStrip = document.getElementById("strategy-experiment-strip");
  els.strategyProposalsCard = document.getElementById("strategy-proposals-card");
  els.strategyRunsCard = document.getElementById("strategy-runs-card");
  els.strategySignalsCard = document.getElementById("strategy-signals-card");
  els.strategyReviewsCard = document.getElementById("strategy-reviews-card");
  els.marketEventsCard = document.getElementById("market-events-card");
  els.spreadSummaryStrip = document.getElementById("spread-summary-strip");
  els.spreadsBody = document.getElementById("spreads-body");
  els.ordersBody = document.getElementById("orders-body");
  els.positionsBody = document.getElementById("positions-body");
  els.brokerStatus = document.getElementById("broker-status");
  els.quoteForm = document.getElementById("quote-form");
  els.quoteSymbol = document.getElementById("quote-symbol");
  els.loadQuote = document.getElementById("load-quote");
  els.quoteCard = document.getElementById("quote-card");
  els.loadPreOpenBoard = document.getElementById("load-preopen-board");
  els.loadPreOpenOverlays = document.getElementById("load-preopen-overlays");
  els.savePreOpenBoard = document.getElementById("save-preopen-board");
  els.preOpenSummaryStrip = document.getElementById("preopen-summary-strip");
  els.preOpenAssessmentCard = document.getElementById("preopen-assessment-card");
  els.preOpenSignals = document.getElementById("preopen-signals");
  els.preOpenPuts = document.getElementById("preopen-puts");
  els.preOpenChainAnalysis = document.getElementById("preopen-chain-analysis");
  els.preOpenRunReview = document.getElementById("preopen-run-review");
  els.refreshDashboard = document.getElementById("refresh-dashboard");
  els.syncAccount = document.getElementById("sync-account");
  els.syncOrders = document.getElementById("sync-orders");
  els.orderTicketForm = document.getElementById("order-ticket-form");
  els.orderSymbol = document.getElementById("order-symbol");
  els.orderSide = document.getElementById("order-side");
  els.orderQuantity = document.getElementById("order-quantity");
  els.orderType = document.getElementById("order-type");
  els.orderTimeInForce = document.getElementById("order-time-in-force");
  els.orderLimitField = document.getElementById("order-limit-field");
  els.orderLimitPrice = document.getElementById("order-limit-price");
  els.orderStopField = document.getElementById("order-stop-field");
  els.orderStopPrice = document.getElementById("order-stop-price");
  els.orderRemark = document.getElementById("order-remark");
  els.orderFormHint = document.getElementById("order-form-hint");
  els.submitOrder = document.getElementById("submit-order");
  els.selectedOrderCard = document.getElementById("selected-order-card");
  els.selectedOrderExecution = document.getElementById("selected-order-execution");
  els.journalEntryForm = document.getElementById("journal-entry-form");
  els.journalEntryType = document.getElementById("journal-entry-type");
  els.journalTitle = document.getElementById("journal-title");
  els.journalTags = document.getElementById("journal-tags");
  els.journalNotes = document.getElementById("journal-notes");
  els.journalFormHint = document.getElementById("journal-form-hint");
  els.submitJournal = document.getElementById("submit-journal");
  els.selectedOrderJournal = document.getElementById("selected-order-journal");
  els.replaceOrderForm = document.getElementById("replace-order-form");
  els.replaceQuantity = document.getElementById("replace-quantity");
  els.replaceLimitField = document.getElementById("replace-limit-field");
  els.replaceLimitPrice = document.getElementById("replace-limit-price");
  els.replaceStopField = document.getElementById("replace-stop-field");
  els.replaceStopPrice = document.getElementById("replace-stop-price");
  els.replaceRemark = document.getElementById("replace-remark");
  els.replaceFormHint = document.getElementById("replace-form-hint");
}

function wireEvents() {
  for (const button of els.languageOptions) {
    button.addEventListener("click", () => {
      setLanguage(button.dataset.langOption || DEFAULT_LANGUAGE);
    });
  }

  els.accountSelect.addEventListener("change", async (event) => {
    state.selectedAccountId = event.target.value;
    await loadAccountData();
  });

  els.refreshDashboard.addEventListener("click", async () => {
    await loadDashboard();
  });

  els.syncAccount.addEventListener("click", async () => {
    if (!state.selectedAccountId) {
      setStatus("No broker account selected.", "warning");
      return;
    }
    await syncAccount();
  });

  els.syncOrders.addEventListener("click", async () => {
    if (!state.selectedAccountId) {
      setStatus("No broker account selected.", "warning");
      return;
    }
    await syncOrders();
  });

  if (els.quoteForm && els.loadQuote && els.quoteSymbol) {
    els.quoteForm.addEventListener("submit", (event) => {
      event.preventDefault();
    });

    els.loadQuote.addEventListener("click", async (event) => {
      if (!event.isTrusted) {
        return;
      }
      await loadQuote();
    });

    els.quoteSymbol.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter") {
        return;
      }
      if (!event.isTrusted) {
        return;
      }
      event.preventDefault();
      await loadQuote();
    });
  }

  els.loadPreOpenBoard.addEventListener("click", async () => {
    await loadPreOpenAssessment({
      includeOptionOverlays: false,
      timeoutMs: PRE_OPEN_BOARD_TIMEOUT_MS,
    });
  });

  els.loadPreOpenOverlays.addEventListener("click", async () => {
    await loadPreOpenAssessment({
      includeOptionOverlays: true,
      timeoutMs: PRE_OPEN_OVERLAY_TIMEOUT_MS,
    });
  });

  els.savePreOpenBoard.addEventListener("click", async () => {
    await saveCurrentPreOpenBoard();
  });

  els.strategyControlsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveStrategyControls();
  });

  els.runStrategyScan.addEventListener("click", async () => {
    await runStrategyScan();
  });

  els.runStrategyReview.addEventListener("click", async () => {
    await runStrategyReview();
  });

  els.orderType.addEventListener("change", () => {
    syncTicketOrderFields();
  });

  els.orderTicketForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitOrder();
  });

  els.ordersBody.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-order-action]");
    if (!button) {
      return;
    }

    const { orderAction, orderId } = button.dataset;
    if (!orderAction || !orderId) {
      return;
    }

    if (orderAction === "manage") {
      setSelectedOrder(orderId, true);
      return;
    }

    if (orderAction === "refresh") {
      await refreshOrder(orderId);
      return;
    }

    if (orderAction === "cancel") {
      await cancelOrder(orderId);
    }
  });

  els.spreadsBody.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-spread-action]");
    if (!button) {
      return;
    }

    const { spreadAction, spreadId } = button.dataset;
    if (!spreadAction || !spreadId) {
      return;
    }

    if (spreadAction === "refresh") {
      await refreshSpread(spreadId);
      return;
    }

    if (spreadAction === "monitor") {
      await monitorSpread(spreadId);
    }
  });

  els.selectedOrderCard.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-selected-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.selectedAction;
    const order = getSelectedOrder();
    if (!action || !order) {
      return;
    }

    if (action === "refresh") {
      await refreshOrder(order.id);
      return;
    }

    if (action === "cancel") {
      await cancelOrder(order.id);
    }
  });

  els.replaceOrderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await replaceSelectedOrder();
  });

  els.journalEntryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitJournalEntry();
  });
}

function readStoredLanguage() {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return stored === "en" || stored === "zh" ? stored : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

function setLanguage(language) {
  if (language !== "en" && language !== "zh") {
    return;
  }
  if (state.language === language) {
    return;
  }
  state.language = language;
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Ignore storage failures; the active page can still switch language.
  }
  renderAllForLanguage();
  applyLanguage();
}

function renderAllForLanguage() {
  renderAccountOptions();
  renderReconciliationStatus();
  renderMetrics();
  renderHoldings();
  renderPreOpenAssessment();
  renderLatestPreOpenRun();
  renderStrategyRuntime();
  renderSpreads();
  renderOrders();
  renderPositions();
  renderSelectedOrder();
  renderQuote();
  syncTicketOrderFields();
  const selectedOrder = getSelectedOrder();
  if (selectedOrder && !els.replaceOrderForm.classList.contains("hidden")) {
    syncReplaceOrderFields(selectedOrder.order_type);
  }
}

function startLanguageObserver() {
  if (languageObserver || !document.body) {
    return;
  }
  languageObserver = new MutationObserver(() => {
    scheduleLanguageRefresh();
  });
  languageObserver.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["placeholder", "title"],
  });
}

function scheduleLanguageRefresh() {
  if (isApplyingLanguage || languageFrame !== null) {
    return;
  }
  languageFrame = window.requestAnimationFrame(() => {
    languageFrame = null;
    applyLanguage();
  });
}

function applyLanguage() {
  if (!document.body || isApplyingLanguage) {
    return;
  }
  isApplyingLanguage = true;
  try {
    document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
    updateLanguageControls();
    translateTextNodes(document.body);
    translateElementAttributes(document.body);
  } finally {
    isApplyingLanguage = false;
  }
}

function updateLanguageControls() {
  if (!els.languageOptions) {
    return;
  }
  for (const button of els.languageOptions) {
    const active = button.dataset.langOption === state.language;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function translateTextNodes(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const dictionary = TRANSLATIONS[state.language] || {};
  let node = walker.nextNode();
  while (node) {
    let original = TEXT_NODE_ORIGINALS.get(node);
    const current = node.nodeValue || "";
    if (original === undefined) {
      original = current;
      TEXT_NODE_ORIGINALS.set(node, original);
    } else if (state.language !== "en" && current !== original && current !== translatedTextForOriginal(original, dictionary)) {
      original = current;
      TEXT_NODE_ORIGINALS.set(node, original);
    }

    const trimmed = original.trim();
    if (trimmed) {
      if (state.language === "en") {
        node.nodeValue = original;
      } else {
        const translated = translatedTextForOriginal(original, dictionary);
        if (translated !== original) {
          node.nodeValue = translated;
        }
      }
    }
    node = walker.nextNode();
  }
}

function translatedTextForOriginal(original, dictionary) {
  const trimmed = String(original || "").trim();
  const translated = translateText(trimmed, dictionary);
  if (!trimmed || !translated) {
    return original;
  }
  return original.replace(trimmed, translated);
}

function translateText(text, dictionary) {
  if (!text) {
    return "";
  }
  if (dictionary[text]) {
    return dictionary[text];
  }
  if (state.language !== "zh") {
    return "";
  }

  const dynamicRules = [
    [/^Refreshing ([A-Z0-9.]+) quote\.\.\.$/, "正在刷新 $1 行情..."],
    [/^Quote refreshed successfully\.$/, "行情刷新成功。"],
    [/^Quote refreshed (.+)\.$/, "行情已于 $1 刷新。"],
    [/^Live macro board refreshed (.+)\.$/, "实时宏观板已于 $1 刷新。"],
    [/^Showing the latest stored macro board captured (.+)\.$/, "正在显示 $1 捕获的最新存档宏观板。"],
    [/^Latest stored run for (.+)\.$/, "最新存储运行对应 $1。"],
    [/^Select a broker account before loading the macro board\.$/, "加载宏观板前请先选择券商账户。"],
    [/^No stored macro board is available yet\. Load it on demand when strategy work is done\.$/, "暂无存储的宏观板。策略工作完成后可按需加载。"],
    [/^(.+) proxies \/ option overlays skipped$/, "$1 个代理 / 已跳过期权叠加层"],
    [/^(.+) proxies \/ (.+) puts \/ (.+) chain layers$/, "$1 个代理 / $2 个看跌快照 / $3 个期权链层"],
    [/^Syncing account (.+)\.\.\.$/, "正在同步账户 $1..."],
    [/^Account (.+) synced\.$/, "账户 $1 已同步。"],
    [/^Syncing orders for (.+)\.\.\.$/, "正在同步 $1 的订单..."],
    [/^Orders for (.+) synced\.$/, "$1 的订单已同步。"],
    [/^Saving bull put controls for (.+)\.\.\.$/, "正在保存 $1 的牛市看跌控制项..."],
    [/^Bull put controls updated for (.+)\.$/, "$1 的牛市看跌控制项已更新。"],
    [/^Saving live macro board for (.+)\.\.\.$/, "正在保存 $1 的实时宏观板..."],
    [/^Stored macro board for (.+)\.$/, "已保存 $1 的宏观板。"],
    [/^Running bull put scan for (.+)\.\.\.$/, "正在为 $1 运行牛市看跌扫描..."],
    [/^Bull put scan opened (.+)\.$/, "牛市看跌扫描已开仓 $1。"],
    [/^Running bull put review for (.+)\.\.\.$/, "正在为 $1 运行牛市看跌复盘..."],
    [/^Submitting (.+) order for (.+)\.\.\.$/, "正在提交 $2 的 $1 订单..."],
    [/^Order submitted for (.+)\.$/, "$1 订单已提交。"],
    [/^Refreshing order (.+)\.\.\.$/, "正在刷新 $1 订单..."],
    [/^Order (.+) refreshed\.$/, "$1 订单已刷新。"],
    [/^Refreshing spread (.+)\.\.\.$/, "正在刷新 $1 价差..."],
    [/^Spread (.+) refreshed\.$/, "$1 价差已刷新。"],
    [/^Monitoring spread (.+)\.\.\.$/, "正在监控 $1 价差..."],
    [/^Canceling order (.+)\.\.\.$/, "正在取消 $1 订单..."],
    [/^Order (.+) canceled\.$/, "$1 订单已取消。"],
    [/^Replacing order (.+)\.\.\.$/, "正在修改 $1 订单..."],
    [/^Order (.+) updated\.$/, "$1 订单已更新。"],
    [/^Saving (.+) entry for (.+)\.\.\.$/, "正在保存 $2 的 $1 记录..."],
    [/^Journal entry saved for (.+)\.$/, "$1 的日志记录已保存。"],
    [/^New entries will attach to (.+) on (.+)\.$/, "新记录将关联到 $2 上的 $1。"],
    [/^New entries will attach (.+) for (.+)\.$/, "新记录将为 $2 关联 $1。"],
    [/^Last success (.+)$/, "最近成功 $1"],
    [/^Last attempt (.+)$/, "最近尝试 $1"],
    [/^Updated (.+)$/, "更新于 $1"],
    [/^Attempted (.+)$/, "尝试于 $1"],
    [/^Started (.+)$/, "开始于 $1"],
    [/^Session (.+)$/, "交易日 $1"],
    [/^Latest snapshot (.+)$/, "最新快照 $1"],
    [/^(.+) profitable \/ (.+) losing$/, "$1 个盈利 / $2 个亏损"],
    [/^(.+) open \/ (.+) exit pending$/, "$1 个打开 / $2 个平仓待处理"],
    [/^(.+) min to 09:30 ET regular open\.$/, "距离美东 09:30 正常开盘 $1 分钟。"],
  ];

  for (const [pattern, replacement] of dynamicRules) {
    if (pattern.test(text)) {
      return text.replace(pattern, replacement);
    }
  }

  return "";
}

function translateElementAttributes(root) {
  const dictionary = TRANSLATIONS[state.language] || {};
  const elements = root.querySelectorAll("[placeholder], [title]");
  for (const element of elements) {
    let originals = ATTRIBUTE_ORIGINALS.get(element);
    if (!originals) {
      originals = {};
      ATTRIBUTE_ORIGINALS.set(element, originals);
    }

    for (const attribute of ["placeholder", "title"]) {
      if (!element.hasAttribute(attribute)) {
        continue;
      }
      if (!Object.prototype.hasOwnProperty.call(originals, attribute)) {
        originals[attribute] = element.getAttribute(attribute) || "";
      }
      let original = originals[attribute];
      const current = element.getAttribute(attribute) || "";
      const translated = dictionary[original] || original;
      if (state.language !== "en" && current !== original && current !== translated) {
        original = current;
        originals[attribute] = original;
      }
      if (state.language === "en") {
        element.setAttribute(attribute, original);
      } else {
        element.setAttribute(attribute, dictionary[original] || original);
      }
    }
  }
}

async function loadDashboard() {
  setStatus("Loading dashboard...", "warning");
  try {
    await refreshAccounts();
    await loadAccountData();
    prepareMarketOverlayPanels();
    setStatus("Dashboard updated. Option strategy panels loaded first. Macro overlays are available on demand.", "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load dashboard.", "error");
  }
}

async function loadAccountData() {
  if (!state.selectedAccountId) {
    state.orders = [];
    state.spreads = [];
    state.runtime = null;
    state.strategyExperiment = { proposals: [], runs: [], signals: [], reviews: [] };
    state.marketEvents = [];
    state.executions = [];
    state.journals = [];
    state.preOpenRuns = [];
    state.latestSnapshot = null;
    state.selectedOrderId = "";
    state.preOpenAssessment = null;
    state.preOpenStatus = buildOverlayStatus("idle", "Select a broker account to load the macro board on demand.");
    renderReconciliationStatus();
    renderMetrics();
    renderHoldings();
    renderPreOpenAssessment();
    renderLatestPreOpenRun();
    renderStrategyRuntime();
    renderStrategyExperiment();
    renderMarketEvents();
    renderSpreads();
    renderOrders();
    renderPositions();
    renderSelectedOrder();
    updateSyncButtons();
    updateOrderTicketAvailability();
    updatePreOpenButtons();
    return;
  }

  try {
    const [latestSnapshot, orders, spreads, runtime, strategyExperiment, marketEvents, executions, journals, preOpenRuns] = await Promise.all([
      fetchJson(`/account-snapshots/latest?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/orders?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/bull-put/spreads?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/bull-put/runtime?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/experiment?external_account_id=${encodeURIComponent(state.selectedAccountId)}&limit=6`),
      fetchJson("/market-events?limit=8"),
      fetchJson(`/executions?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/journals?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/pre-open-runs?external_account_id=${encodeURIComponent(state.selectedAccountId)}&limit=1`),
    ]);
    state.orders = orders;
    state.spreads = spreads;
    state.runtime = runtime;
    state.strategyExperiment = strategyExperiment || { proposals: [], runs: [], signals: [], reviews: [] };
    state.marketEvents = Array.isArray(marketEvents) ? marketEvents : [];
    state.executions = executions;
    state.journals = journals;
    state.preOpenRuns = preOpenRuns;
    state.latestSnapshot = latestSnapshot;
    seedPreOpenAssessmentFromLatestRun({ clearWhenMissing: true });

    if (!orders.some((order) => order.id === state.selectedOrderId)) {
      state.selectedOrderId = orders[0]?.id || "";
    }

    renderReconciliationStatus();
    renderMetrics();
    renderHoldings();
    renderPreOpenAssessment();
    renderLatestPreOpenRun();
    renderStrategyRuntime();
    renderStrategyExperiment();
    renderMarketEvents();
    renderSpreads();
    renderOrders();
    renderPositions();
    renderSelectedOrder();
    updateSyncButtons();
    updateOrderTicketAvailability();
    updatePreOpenButtons();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load account data.", "error");
  }
}

function prepareMarketOverlayPanels() {
  if (els.quoteCard && !state.quote) {
    state.quoteStatus = buildOverlayStatus("idle", "Load a quote manually to keep the dashboard fast.");
    renderQuote();
  }
  if (!state.preOpenAssessment) {
    state.preOpenStatus = buildOverlayStatus(
      "idle",
      "Macro board is available on demand so option strategy requests stay first."
    );
    renderPreOpenAssessment();
  }
}

async function loadQuote(options = {}) {
  if (!els.quoteSymbol || !els.quoteCard) {
    return;
  }
  const { timeoutMs = BROKER_REQUEST_TIMEOUT_MS } = options;
  const symbol = els.quoteSymbol.value.trim().toUpperCase();
  if (!symbol) {
    state.quote = null;
    state.quoteStatus = buildOverlayStatus("idle", "Enter a symbol.");
    renderQuote();
    return;
  }

  const hasMatchingQuote = state.quote && state.quote.symbol === symbol;
  if (!hasMatchingQuote) {
    state.quote = null;
  }
  state.quoteStatus = buildOverlayStatus("loading", `Refreshing ${symbol} quote...`);
  renderQuote();

  try {
    state.quote = await fetchJson(
      `/brokers/longbridge/quote?symbol=${encodeURIComponent(symbol)}&mode=paper`,
      { timeoutMs }
    );
    state.quoteStatus = buildOverlayStatus("live", overlayLiveDetail("Quote", state.quote.timestamp));
    renderQuote();
  } catch (error) {
    console.error(error);
    const hasStaleQuote = state.quote && state.quote.symbol === symbol;
    if (!hasStaleQuote) {
      state.quote = null;
    }
    state.quoteStatus = classifyOverlayFailure(error, {
      label: "quote",
      stale: hasStaleQuote,
      staleAt: state.quote?.timestamp,
    });
    renderQuote();
  }
}

async function loadPreOpenAssessment(options = {}) {
  const { includeOptionOverlays = false, timeoutMs = PRE_OPEN_BOARD_TIMEOUT_MS } = options;
  if (!state.selectedAccountId) {
    state.preOpenStatus = buildOverlayStatus("idle", "Select a broker account before loading the macro board.");
    renderPreOpenAssessment();
    return;
  }
  state.preOpenStatus = buildOverlayStatus(
    "loading",
    includeOptionOverlays
      ? "Refreshing live macro board with option overlays..."
      : "Refreshing live macro board..."
  );
  renderPreOpenAssessment();

  try {
    const params = new URLSearchParams();
    params.set("external_account_id", state.selectedAccountId);
    params.set("include_option_overlays", includeOptionOverlays ? "true" : "false");
    const assessment = await fetchJson(
      `/strategies/pre-open-risk?${params.toString()}`,
      { timeoutMs }
    );
    applyPreOpenAssessmentResponse(assessment);
  } catch (error) {
    console.error(error);
    state.preOpenStatus = classifyOverlayFailure(error, {
      label: "live macro board",
      stale: Boolean(state.preOpenAssessment),
      staleAt: state.preOpenAssessment?.analyzed_at,
    });
    renderPreOpenAssessment();
  }
}

async function saveCurrentPreOpenBoard() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before saving the macro board.", "warning");
    return;
  }
  if (!state.preOpenAssessment || state.preOpenStatus.kind === "idle" || state.preOpenStatus.kind === "loading") {
    setStatus("Load the live macro board before saving it.", "warning");
    return;
  }
  if (state.preOpenStatus.kind !== "live" && state.preOpenStatus.kind !== "partial") {
    setStatus("Only a live or partial live macro board can be saved.", "warning");
    return;
  }

  setStatus(`Saving live macro board for ${state.selectedAccountId}...`, "warning");
  updatePreOpenButtons(true);
  try {
    const result = await fetchJson(
      `/strategies/pre-open-runs/${encodeURIComponent(state.selectedAccountId)}/capture?force=true&include_option_overlays=false`,
      {
        method: "POST",
        timeoutMs: PRE_OPEN_BOARD_TIMEOUT_MS,
      }
    );
    if (result.run) {
      state.preOpenRuns = [
        result.run,
        ...state.preOpenRuns.filter((run) => run.id !== result.run.id),
      ];
      state.preOpenAssessment = result.run.assessment || state.preOpenAssessment;
      applyPreOpenAssessmentResponse(state.preOpenAssessment);
      renderLatestPreOpenRun();
    }
    setStatus(`Stored macro board for ${formatSessionDate(result.run?.target_session_date)}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Saving macro board failed.", "error");
  } finally {
    updatePreOpenButtons(false);
  }
}

function seedPreOpenAssessmentFromLatestRun({ clearWhenMissing = false } = {}) {
  const run = Array.isArray(state.preOpenRuns) && state.preOpenRuns.length ? state.preOpenRuns[0] : null;
  if (!run?.assessment) {
    if (clearWhenMissing) {
      state.preOpenAssessment = null;
      if (state.preOpenStatus.kind !== "loading") {
        state.preOpenStatus = buildOverlayStatus(
          "idle",
          "No stored macro board is available yet. Load it on demand when strategy work is done."
        );
      }
    }
    return false;
  }

  state.preOpenAssessment = run.assessment;
  if (state.preOpenStatus.kind !== "loading") {
    state.preOpenStatus = buildOverlayStatus(
      "stale",
      run.assessment.freshness_detail || `Showing the latest stored macro board captured ${formatDateTime(run.assessment.analyzed_at)}.`,
      run.assessment.stale_reason || `Latest stored run for ${formatSessionDate(run.target_session_date)}.`
    );
  }
  return true;
}

function applyPreOpenAssessmentResponse(assessment) {
  state.preOpenAssessment = assessment;
  if (assessment?.freshness_status === "stale") {
    state.preOpenStatus = buildOverlayStatus(
      "stale",
      assessment.freshness_detail || buildStaleOverlayDetail("live macro board", "circuit_open", assessment.analyzed_at),
      assessment.stale_reason || ""
    );
  } else if (assessment?.freshness_status === "partial") {
    state.preOpenStatus = buildOverlayStatus(
      "partial",
      assessment.freshness_detail || "Live board loaded with partial proxy coverage.",
      assessment.stale_reason || ""
    );
  } else if (assessment?.freshness_status === "error") {
    state.preOpenStatus = buildOverlayStatus(
      "error",
      assessment.freshness_detail || "Live broker data is unavailable for the live macro board.",
      assessment.stale_reason || ""
    );
  } else {
    state.preOpenStatus = buildOverlayStatus(
      "live",
      assessment?.freshness_detail || overlayLiveDetail("Live macro board", assessment.analyzed_at)
    );
  }
  renderPreOpenAssessment();
  updatePreOpenButtons();
}

async function syncAccount() {
  setStatus(`Syncing account ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/brokers/longbridge/account-sync/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await refreshAccounts();
    await loadAccountData();
    setStatus(`Account ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Account sync failed.", "error");
  }
}

async function syncOrders() {
  setStatus(`Syncing orders for ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/orders/sync/longbridge/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await refreshAccounts();
    await loadAccountData();
    setStatus(`Orders for ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Order sync failed.", "error");
  }
}

async function saveStrategyControls() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before updating strategy controls.", "warning");
    return;
  }

  const payload = {
    auto_entry_enabled: els.strategyAutoEntry.value === "true",
    manual_pause: els.strategyManualPause.value === "true",
    kill_switch_active: els.strategyKillSwitch.value === "true",
    paused_symbols: parseSymbolList(els.strategyPausedSymbols.value),
  };

  setStatus(`Saving bull put controls for ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadAccountData();
    setStatus(`Bull put controls updated for ${state.selectedAccountId}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put controls update failed.", "error");
  }
}

async function runStrategyScan() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put scan.", "warning");
    return;
  }

  setStatus(`Running bull put scan for ${state.selectedAccountId}...`, "warning");
  try {
    const result = await fetchJson(
      `/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}/scan?mode=paper&force=true`,
      {
        method: "POST",
      }
    );
    await loadAccountData();
    const message = result.executed
      ? `Bull put scan opened ${result.executed_spread?.underlying_symbol || "a spread"}.`
      : result.reason || "Bull put scan completed without a new spread.";
    setStatus(message, result.executed ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put scan failed.", "error");
  }
}

async function runStrategyReview() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put review.", "warning");
    return;
  }

  setStatus(`Running bull put review for ${state.selectedAccountId}...`, "warning");
  try {
    const result = await fetchJson(
      `/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}/review?mode=paper&force=true`,
      {
        method: "POST",
      }
    );
    await loadAccountData();
    const message = result.recommendation || result.reason || result.strategy_state?.last_review_summary || "Bull put review completed.";
    setStatus(message, result.review_status === "suggested" ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put review failed.", "error");
  }
}

async function refreshAccounts() {
  const accounts = await fetchJson("/broker-accounts");
  applyAccounts(accounts);
}

async function refreshAccountsSilently() {
  try {
    await refreshAccounts();
  } catch (error) {
    console.error(error);
  }
}

function applyAccounts(accounts) {
  state.accounts = accounts;

  if (!state.selectedAccountId && accounts.length > 0) {
    state.selectedAccountId = accounts[0].external_account_id;
  } else if (accounts.every((account) => account.external_account_id !== state.selectedAccountId)) {
    state.selectedAccountId = accounts[0]?.external_account_id || "";
  }

  renderAccountOptions();
  renderReconciliationStatus();
  updateSyncButtons();
  updateOrderTicketAvailability();
}

async function submitOrder() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before submitting an order.", "warning");
    return;
  }

  try {
    const payload = buildCreateOrderPayload();
    setStatus(`Submitting ${payload.side.toUpperCase()} ${payload.symbol}...`, "warning");
    const created = await fetchJson("/orders/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedOrderId = created.id;
    els.orderRemark.value = "";
    await loadAccountData();
    setSelectedOrder(created.id);
    setStatus(`Order submitted for ${created.symbol}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order submission failed.", "error");
  }
}

async function refreshOrder(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  setStatus(`Refreshing order ${order?.symbol || orderId}...`, "warning");
  try {
    const refreshed = await fetchJson(`/orders/${encodeURIComponent(orderId)}/refresh`, {
      method: "POST",
    });
    state.selectedOrderId = refreshed.id;
    await loadAccountData();
    setSelectedOrder(refreshed.id);
    setStatus(`Order ${refreshed.symbol} refreshed.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order refresh failed.", "error");
  }
}

async function refreshSpread(spreadId) {
  const spread = state.spreads.find((item) => item.id === spreadId);
  setStatus(`Refreshing spread ${spread?.underlying_symbol || spreadId}...`, "warning");
  try {
    const refreshed = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/refresh`, {
      method: "POST",
    });
    await loadAccountData();
    setStatus(`Spread ${refreshed.underlying_symbol} refreshed.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Spread refresh failed.", "error");
  }
}

async function monitorSpread(spreadId) {
  const spread = state.spreads.find((item) => item.id === spreadId);
  setStatus(`Monitoring spread ${spread?.underlying_symbol || spreadId}...`, "warning");
  try {
    const result = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/monitor`, {
      method: "POST",
    });
    await loadAccountData();
    const action = result.should_close
      ? `Exit action ${formatSpreadExitReason(result.exit_reason)} evaluated for ${result.spread.underlying_symbol}.`
      : `Spread ${result.spread.underlying_symbol} remains within thresholds.`;
    setStatus(action, result.should_close ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Spread monitor failed.", "error");
  }
}

async function cancelOrder(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  if (!order) {
    setStatus("Order not found in the current table.", "error");
    return;
  }
  if (!isCancelableOrder(order)) {
    setStatus("This order can no longer be canceled.", "warning");
    return;
  }
  if (!window.confirm(`Cancel order ${order.symbol} ${order.side.toUpperCase()} ${order.quantity}?`)) {
    return;
  }

  setStatus(`Canceling order ${order.symbol}...`, "warning");
  try {
    const canceled = await fetchJson(`/orders/${encodeURIComponent(orderId)}/cancel`, {
      method: "POST",
    });
    state.selectedOrderId = canceled.id;
    await loadAccountData();
    setSelectedOrder(canceled.id);
    setStatus(`Order ${canceled.symbol} canceled.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order cancel failed.", "error");
  }
}

async function replaceSelectedOrder() {
  const order = getSelectedOrder();
  if (!order) {
    setStatus("Select an order before replacing it.", "warning");
    return;
  }
  if (!isReplaceableOrder(order)) {
    setStatus("Only working orders can be replaced.", "warning");
    return;
  }

  try {
    const payload = buildReplaceOrderPayload(order);
    setStatus(`Replacing order ${order.symbol}...`, "warning");
    const updated = await fetchJson(`/orders/${encodeURIComponent(order.id)}/replace`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedOrderId = updated.id;
    els.replaceRemark.value = "";
    await loadAccountData();
    setSelectedOrder(updated.id);
    setStatus(`Order ${updated.symbol} updated.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order replace failed.", "error");
  }
}

async function submitJournalEntry() {
  const order = getSelectedOrder();
  if (!order) {
    setStatus("Select an order before saving a journal entry.", "warning");
    return;
  }

  try {
    const title = els.journalTitle.value.trim();
    const notes = els.journalNotes.value.trim();
    if (!title) {
      throw new Error("Journal title is required.");
    }
    if (!notes) {
      throw new Error("Journal notes are required.");
    }

    const execution = getSelectedExecution();
    const payload = {
      external_account_id: order.external_account_id,
      symbol: order.symbol,
      entry_type: els.journalEntryType.value,
      title,
      notes,
      order_id: order.id,
      trade_plan_id: order.trade_plan_id,
      execution_id: execution?.id || null,
      tags: parseTags(els.journalTags.value),
    };
    setStatus(`Saving ${payload.entry_type} entry for ${order.symbol}...`, "warning");
    const created = await fetchJson("/journals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.journals = [created, ...state.journals.filter((entry) => entry.id !== created.id)];
    els.journalTitle.value = "";
    els.journalTags.value = "";
    els.journalNotes.value = "";
    renderSelectedJournal();
    setStatus(`Journal entry saved for ${created.symbol}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Journal entry save failed.", "error");
  }
}

function renderAccountOptions() {
  els.accountSelect.innerHTML = "";
  if (state.accounts.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No broker accounts";
    els.accountSelect.append(option);
    return;
  }

  for (const account of state.accounts) {
    const option = document.createElement("option");
    option.value = account.external_account_id;
    option.selected = account.external_account_id === state.selectedAccountId;
    option.textContent = `${account.display_name || account.external_account_id} / ${account.base_currency}`;
    els.accountSelect.append(option);
  }
}

function renderReconciliationStatus() {
  const account = getSelectedAccount();
  if (!account) {
    els.reconciliationStrip.innerHTML = `
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Auto Reconciliation</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">Select a broker account to view scheduler state.</span>
      </article>
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Account Sync</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">No account selected.</span>
      </article>
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Orders Sync</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">No account selected.</span>
      </article>
    `;
    return;
  }

  const cards = [
    {
      label: "Auto Reconciliation",
      tone: account.auto_reconcile_enabled ? "success" : "neutral",
      badge: account.auto_reconcile_enabled ? "Enabled" : "Disabled",
      value: account.auto_reconcile_enabled ? "Enabled" : "Disabled",
      detail: account.auto_reconcile_enabled
        ? "Background polling is active for this paper account."
        : "Automatic polling is disabled for this account.",
    },
    {
      label: "Account Sync",
      tone: reconciliationTone(account.account_sync_status),
      badge: reconciliationLabel(account.account_sync_status),
      value: formatSyncHeadline(account.account_last_synced_at, account.account_last_sync_attempt_at),
      detail: formatSyncDetail(
        account.account_sync_status,
        account.account_last_synced_at,
        account.account_last_sync_attempt_at,
        account.account_last_sync_error
      ),
    },
    {
      label: "Orders Sync",
      tone: reconciliationTone(account.orders_sync_status),
      badge: reconciliationLabel(account.orders_sync_status),
      value: formatSyncHeadline(account.orders_last_synced_at, account.orders_last_sync_attempt_at),
      detail: formatSyncDetail(
        account.orders_sync_status,
        account.orders_last_synced_at,
        account.orders_last_sync_attempt_at,
        account.orders_last_sync_error
      ),
    },
  ];

  els.reconciliationStrip.innerHTML = cards
    .map(
      (card) => `
        <article class="reconciliation-card">
          <div class="reconciliation-head">
            <span class="metric-label">${escapeHtml(card.label)}</span>
            <span class="pill ${escapeHtml(card.tone)}">${escapeHtml(card.badge)}</span>
          </div>
          <strong class="reconciliation-value">${escapeHtml(card.value)}</strong>
          <span class="reconciliation-detail">${escapeHtml(card.detail)}</span>
        </article>
      `
    )
    .join("");
}

function renderMetrics() {
  const snapshot = state.latestSnapshot;
  const values = [
    snapshot ? formatCurrency(snapshot.cash_balance, snapshot.currency) : "--",
    snapshot ? formatCurrency(snapshot.net_liquidation, snapshot.currency) : "--",
    snapshot ? formatCurrency(snapshot.buying_power, snapshot.currency) : "--",
    snapshot ? formatDateTime(snapshot.captured_at) : "--",
  ];

  const tiles = els.metricsStrip.querySelectorAll(".metric-value");
  tiles.forEach((tile, index) => {
    tile.textContent = values[index] || "--";
  });
}

function renderHoldings() {
  const snapshot = state.latestSnapshot;
  const positions = buildSortedPositions(snapshot?.positions || []);
  const currency = snapshot?.currency || "USD";
  const grossMarketValue = positions.reduce((sum, position) => sum + toFiniteNumber(position.market_value), 0);
  const totalUnrealizedPnl = positions.reduce((sum, position) => sum + toFiniteNumber(position.unrealized_pnl), 0);
  const largestHolding = positions[0] || null;
  const profitableCount = positions.filter((position) => toNumber(position.unrealized_pnl) > 0).length;
  const losingCount = positions.filter((position) => toNumber(position.unrealized_pnl) < 0).length;
  const summaryValues = [
    {
      label: "Open Positions",
      value: String(positions.length),
      tone: "",
      detail: positions.length ? `${profitableCount} profitable / ${losingCount} losing` : "No active holdings",
    },
    {
      label: "Gross Market Value",
      value: positions.length ? formatCurrency(grossMarketValue, currency) : "--",
      tone: "",
      detail: positions.length ? `Latest snapshot ${formatDateTime(snapshot?.captured_at)}` : "Sync account to load holdings",
    },
    {
      label: "Unrealized PnL",
      value: positions.length ? formatSignedCurrency(totalUnrealizedPnl, currency) : "--",
      tone: pnlTone(totalUnrealizedPnl),
      detail: positions.length ? `${formatPercent(totalUnrealizedPnl, grossMarketValue)}` : "No open positions",
    },
    {
      label: "Largest Holding",
      value: largestHolding ? largestHolding.symbol : "--",
      tone: "",
      detail: largestHolding ? `${formatCurrency(largestHolding.market_value, currency)} / ${formatWeight(largestHolding.market_value, grossMarketValue)}` : "No ranked holdings",
    },
  ];

  els.positionsSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  if (!els.holdingsFocus) {
    return;
  }

  if (positions.length === 0) {
    els.holdingsFocus.innerHTML = '<div class="holding-empty">No positions in latest snapshot.</div>';
    return;
  }

  els.holdingsFocus.innerHTML = positions
    .slice(0, 5)
    .map((position) => {
      const pnl = toNumber(position.unrealized_pnl);
      const tone = pnlTone(pnl);
      return `
        <article class="holding-card">
          <div class="holding-head">
            <div class="symbol-block">
              <strong>${escapeHtml(position.symbol)}</strong>
              <span>${escapeHtml(position.asset_type.toUpperCase())} / ${escapeHtml(formatWeight(position.market_value, grossMarketValue))}</span>
            </div>
            <span class="pill ${tone}">${escapeHtml(formatSignedCurrency(position.unrealized_pnl, currency))}</span>
          </div>
          <div class="holding-stats">
            <div>
              <span>Quantity</span>
              <strong>${escapeHtml(formatPositionQuantity(position.quantity))}</strong>
            </div>
            <div>
              <span>Avg Cost</span>
              <strong>${escapeHtml(formatCurrency(position.average_cost, currency))}</strong>
            </div>
            <div>
              <span>Market Value</span>
              <strong>${escapeHtml(formatCurrency(position.market_value, currency))}</strong>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderBrokerStatus() {
  if (!els.brokerStatus) {
    return;
  }
  const config = state.brokerStatus;
  if (!config) {
    els.brokerStatus.innerHTML = "";
    return;
  }

  const items = [
    ["App Key", config.app_key_configured ? "Configured" : "Missing"],
    ["App Secret", config.app_secret_configured ? "Configured" : "Missing"],
    ["Paper Token", config.paper_token_configured ? "Configured" : "Missing"],
    ["Live Token", config.live_token_configured ? "Configured" : "Missing"],
  ];

  els.brokerStatus.innerHTML = items
    .map(
      ([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>
      `
    )
    .join("");
}

function renderWatchlists() {
  if (!els.watchlistsBody) {
    return;
  }
  if (state.watchlists.length === 0) {
    els.watchlistsBody.innerHTML = '<div class="watchlist-block"><div class="watchlist-item">No watchlists found.</div></div>';
    return;
  }

  els.watchlistsBody.innerHTML = state.watchlists
    .map((watchlist) => {
      const items = watchlist.items.length
        ? watchlist.items
            .slice(0, 8)
            .map(
              (item) => `
                <div class="watchlist-item">
                  <div class="symbol-block">
                    <strong>${escapeHtml(item.symbol)}</strong>
                    <span>${escapeHtml(item.notes || item.asset_type)}</span>
                  </div>
                  <span class="pill neutral">${escapeHtml(item.asset_type)}</span>
                </div>
              `
            )
            .join("")
        : '<div class="watchlist-item">No symbols yet.</div>';

      return `
        <section class="watchlist-block">
          <div class="watchlist-head">
            <span class="watchlist-name">${escapeHtml(watchlist.name)}</span>
            <span class="watchlist-count">${watchlist.items.length} items</span>
          </div>
          <div class="watchlist-items">${items}</div>
        </section>
      `;
    })
    .join("");
}

function renderStrategyRuntime() {
  const runtime = state.runtime;
  if (!runtime) {
    els.strategyRuntimeStrip.innerHTML = `
      <article class="mini-metric-tile">
        <span class="metric-label">Entry Status</span>
        <strong class="mini-metric-value">--</strong>
        <span class="mini-metric-detail">Select a broker account to load bull put controls.</span>
      </article>
    `;
    els.strategySkipCard.className = "strategy-note-body empty";
    els.strategySkipCard.textContent = "No bull put scan has been skipped yet.";
    els.strategyJournalFeed.className = "strategy-note-body empty";
    els.strategyJournalFeed.textContent = "No bull put strategy notes for this account yet.";
    els.strategyReviewCard.className = "strategy-note-body empty";
    els.strategyReviewCard.textContent = "No bull put strategy review has been generated yet.";
    els.strategyControlsHint.textContent = "Strategy controls apply to new bull put entries only. Existing spreads remain monitored.";
    els.strategyAutoEntry.value = "true";
    els.strategyManualPause.value = "false";
    els.strategyKillSwitch.value = "false";
    els.strategyPausedSymbols.value = "";
    updateStrategyButtons();
    return;
  }

  const statusSummary = describeStrategyStatus(runtime);
  const summaryValues = [
    {
      label: "Entry Status",
      value: statusSummary.value,
      tone: statusSummary.tone,
      detail: statusSummary.detail,
    },
    {
      label: "Daily Entries",
      value: `${runtime.daily_entry_count}`,
      tone: runtime.daily_entry_count > 0 ? "success" : "",
      detail: runtime.daily_entry_cap_reached
        ? "Daily cap reached"
        : runtime.active_spread_count
          ? `${runtime.active_spread_count} active spread${runtime.active_spread_count === 1 ? "" : "s"}`
          : "ready for first spread",
    },
    {
      label: "Daily Realized PnL",
      value: formatSignedCurrency(runtime.daily_realized_pnl, "USD"),
      tone: pnlTone(runtime.daily_realized_pnl),
      detail: runtime.current_session_date ? `Session ${runtime.current_session_date}` : "No tracked session date",
    },
    {
      label: "Next Action",
      value: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "--",
      tone: runtime.last_scan_result === "executed" ? "success" : runtime.last_scan_result === "skipped" ? "warning" : "",
      detail: runtime.next_monitor_after
        ? `Next monitor ${formatDateTime(runtime.next_monitor_after)}`
        : runtime.last_scan_at
          ? `Last scan ${runtime.last_scan_symbol || "Account"} / ${formatDateTime(runtime.last_scan_at)}`
          : "Waiting for first bull put scan",
    },
  ];

  els.strategyRuntimeStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  els.strategyAutoEntry.value = runtime.auto_entry_enabled ? "true" : "false";
  els.strategyManualPause.value = runtime.manual_pause ? "true" : "false";
  els.strategyKillSwitch.value = runtime.kill_switch_active ? "true" : "false";
  els.strategyPausedSymbols.value = (runtime.paused_symbols || []).join(", ");
  els.strategyControlsHint.textContent = runtime.last_action
    ? `${runtime.last_action}${runtime.last_action_at ? ` (${formatDateTime(runtime.last_action_at)})` : ""}`
    : "Strategy controls apply to new bull put entries only. Existing spreads remain monitored.";

  const skipReason = runtime.last_skip_reason || "No bull put skip reason recorded.";
  els.strategySkipCard.className = `strategy-note-body ${runtime.last_skip_reason ? "" : "empty"}`;
  els.strategySkipCard.textContent = skipReason;

  const strategyNotes = state.journals.filter((entry) =>
    Array.isArray(entry.tags) && entry.tags.some((tag) => String(tag).toLowerCase() === "bull-put")
  );
  const reviewSummary = runtime.last_review_summary || "No bull put strategy review has been generated yet.";
  els.strategyReviewCard.className = `strategy-note-body ${runtime.last_review_summary ? "" : "empty"}`;
  els.strategyReviewCard.textContent = runtime.last_review_at
    ? `${reviewSummary} (${formatDateTime(runtime.last_review_at)})`
    : reviewSummary;
  if (strategyNotes.length === 0) {
    els.strategyJournalFeed.className = "strategy-note-body empty";
    els.strategyJournalFeed.textContent = "No bull put strategy notes for this account yet.";
  } else {
    els.strategyJournalFeed.className = "strategy-note-body";
    els.strategyJournalFeed.innerHTML = strategyNotes
      .slice(0, 4)
      .map(
        (entry) => `
          <article class="strategy-journal-entry">
            <div class="strategy-journal-head">
              <strong>${escapeHtml(entry.title)}</strong>
              <span>${escapeHtml(formatDateTime(entry.updated_at))}</span>
            </div>
            <p>${escapeHtml(entry.notes)}</p>
          </article>
        `
      )
      .join("");
  }

  updateStrategyButtons();
}

function renderStrategyExperiment() {
  const experiment = state.strategyExperiment || { proposals: [], runs: [], signals: [], reviews: [] };
  const proposals = Array.isArray(experiment.proposals) ? experiment.proposals : [];
  const runs = Array.isArray(experiment.runs) ? experiment.runs : [];
  const signals = Array.isArray(experiment.signals) ? experiment.signals : [];
  const reviews = Array.isArray(experiment.reviews) ? experiment.reviews : [];
  const pendingProposals = proposals.filter((proposal) => proposal.status === "pending");
  const latestRun = runs[0] || null;
  const latestSignal = signals[0] || null;
  const latestReview = reviews[0] || null;

  if (els.strategyExperimentStrip) {
    const summaryValues = [
      {
        label: "Active Proposals",
        value: String(pendingProposals.length),
        tone: pendingProposals.length ? "warning" : "",
        detail: proposals.length ? `${proposals.length} tracked proposal${proposals.length === 1 ? "" : "s"}` : "No strategy proposals loaded.",
      },
      {
        label: "Latest Run",
        value: latestRun ? formatStrategyStatusLabel(latestRun.status) : "--",
        tone: latestRun ? strategyStatusClass(latestRun.status) : "",
        detail: latestRun ? `${latestRun.strategy_id} / ${formatDateTime(latestRun.created_at)}` : "No strategy runs recorded.",
      },
      {
        label: "Signals",
        value: String(signals.length),
        tone: latestSignal ? strategyStatusClass(latestSignal.signal_type) : "",
        detail: latestSignal ? `${latestSignal.signal_type} / ${formatDateTime(latestSignal.emitted_at)}` : "No strategy signals recorded.",
      },
      {
        label: "Reviews",
        value: String(reviews.length),
        tone: latestReview ? strategyStatusClass(latestReview.status) : "",
        detail: latestReview ? `${latestReview.review_type} / ${formatDateTime(latestReview.reviewed_at)}` : "No strategy reviews recorded.",
      },
    ];
    els.strategyExperimentStrip.innerHTML = summaryValues
      .map(
        (item) => `
          <article class="mini-metric-tile">
            <span class="metric-label">${escapeHtml(item.label)}</span>
            <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
            <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
          </article>
        `
      )
      .join("");
  }

  renderStrategyExperimentList({
    element: els.strategyProposalsCard,
    items: proposals,
    emptyText: "No strategy experiment proposals yet.",
    renderItem: (proposal) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(proposal.title)}</strong>
          <span class="pill ${strategyStatusClass(proposal.status)}">${escapeHtml(formatStrategyStatusLabel(proposal.status))}</span>
        </div>
        <p>${escapeHtml(proposal.rationale)}</p>
        <span>${escapeHtml([proposal.strategy_id, proposal.symbol, proposal.proposed_action].filter(Boolean).join(" / "))}</span>
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategyRunsCard,
    items: runs,
    emptyText: "No strategy runs recorded yet.",
    renderItem: (run) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(`${run.strategy_id} / ${run.run_type}`)}</strong>
          <span class="pill ${strategyStatusClass(run.status)}">${escapeHtml(formatStrategyStatusLabel(run.status))}</span>
        </div>
        <p>${escapeHtml(run.summary || run.reason || "Run recorded without a summary.")}</p>
        <span>${escapeHtml(formatDateTime(run.completed_at || run.started_at || run.created_at))}</span>
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategySignalsCard,
    items: signals,
    emptyText: "No strategy signals recorded yet.",
    renderItem: (signal) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(signal.summary)}</strong>
          <span class="pill neutral">${escapeHtml(formatStrategyStatusLabel(signal.signal_type))}</span>
        </div>
        <p>${escapeHtml(signal.detail || [signal.strategy_id, signal.symbol].filter(Boolean).join(" / ") || "Signal recorded.")}</p>
        <span>${escapeHtml(formatDateTime(signal.emitted_at))}</span>
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategyReviewsCard,
    items: reviews,
    emptyText: "No strategy reviews recorded yet.",
    renderItem: (review) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(review.review_type)}</strong>
          <span class="pill ${strategyStatusClass(review.status)}">${escapeHtml(formatStrategyStatusLabel(review.status))}</span>
        </div>
        <p>${escapeHtml(review.recommendation || review.summary)}</p>
        <span>${escapeHtml(formatDateTime(review.reviewed_at))}</span>
      </article>
    `,
  });
}

function renderStrategyExperimentList({ element, items, emptyText, renderItem }) {
  if (!element) {
    return;
  }
  if (!items.length) {
    element.className = "strategy-note-body empty";
    element.textContent = emptyText;
    return;
  }
  element.className = "strategy-note-body";
  element.innerHTML = items.slice(0, 4).map(renderItem).join("");
}

function renderMarketEvents() {
  if (!els.marketEventsCard) {
    return;
  }
  const events = Array.isArray(state.marketEvents) ? state.marketEvents : [];
  if (!events.length) {
    els.marketEventsCard.className = "strategy-note-body empty";
    els.marketEventsCard.textContent = "No upcoming market events recorded.";
    return;
  }
  els.marketEventsCard.className = "strategy-note-body";
  els.marketEventsCard.innerHTML = events
    .slice(0, 6)
    .map(
      (event) => `
        <article class="strategy-journal-entry">
          <div class="strategy-journal-head">
            <strong>${escapeHtml(event.title)}</strong>
            <span class="pill ${strategyStatusClass(event.severity)}">${escapeHtml(formatStrategyStatusLabel(event.severity))}</span>
          </div>
          <p>${escapeHtml([event.symbol || "Market", event.event_type, event.source].filter(Boolean).join(" / "))}</p>
          <span>${escapeHtml(formatDateTime(event.scheduled_at))}</span>
        </article>
      `
    )
    .join("");
}

function renderSpreads() {
  const spreads = [...state.spreads].sort(
    (left, right) => new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime()
  );
  const activeSpreads = spreads.filter(isActiveSpread);
  const exitPendingSpreads = spreads.filter(isExitPendingSpread);
  const monitorableSpreads = spreads.filter(isMonitorableSpread);
  const monitoredOpenSpread = activeSpreads.find((spread) => spread.raw_payload?.monitor) || null;
  const monitoredSnapshot = monitoredOpenSpread ? monitoredOpenSpread.raw_payload.monitor : null;
  const lastMonitoredSpread = monitorableSpreads.find((spread) => spread.last_synced_at) || null;

  const summaryValues = [
    {
      label: "Active Spreads",
      value: String(activeSpreads.length),
      tone: "",
      detail: activeSpreads.length
        ? `${activeSpreads.filter((spread) => spread.status === "open").length} open / ${exitPendingSpreads.length} exit pending`
        : "No active spreads",
    },
    {
      label: "Monitor Mark",
      value: monitoredSnapshot?.estimated_exit_debit ? formatSpreadCredit(monitoredSnapshot.estimated_exit_debit) : "--",
      tone: monitoredSnapshot?.exit_reason ? "warning" : "",
      detail: monitoredOpenSpread
        ? `${monitoredOpenSpread.underlying_symbol} / ${formatDateTime(monitoredSnapshot.evaluated_at)}`
        : "No monitor snapshot",
    },
    {
      label: "P/L",
      value: monitoredSnapshot?.estimated_pnl ? formatSignedCurrency(monitoredSnapshot.estimated_pnl, "USD") : "--",
      tone: monitoredSnapshot?.estimated_pnl ? pnlTone(monitoredSnapshot.estimated_pnl) : "",
      detail: monitoredSnapshot
        ? `TP Gap ${formatSpreadCredit(monitoredSnapshot.distance_to_take_profit_debit)} / SL Gap ${formatSpreadCredit(monitoredSnapshot.distance_to_stop_loss_debit)}`
        : "No monitor snapshot",
    },
    {
      label: "Last Monitor",
      value: lastMonitoredSpread ? formatDateTime(lastMonitoredSpread.last_synced_at) : "--",
      tone: "",
      detail: lastMonitoredSpread
        ? `${lastMonitoredSpread.underlying_symbol} / ${formatSpreadStatusLabel(lastMonitoredSpread.status)}`
        : monitorableSpreads.length
          ? "Waiting for first monitor run"
          : "No open or exit-pending spreads are being monitored.",
    },
  ];

  els.spreadSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  if (spreads.length === 0) {
    els.spreadsBody.innerHTML = '<tr><td colspan="8" class="empty-row">No bull put spreads for this account.</td></tr>';
    return;
  }

  els.spreadsBody.innerHTML = spreads
    .map((spread) => {
      const monitorable = isMonitorableSpread(spread);
      const statusTone = spreadStatusClass(spread.status);
      const monitor = spread.raw_payload?.monitor || null;
      const legSummary = `${formatSpreadStrike(spread.long_strike)} / ${formatSpreadStrike(spread.short_strike)} puts`;
      const lastUpdatedAt = spread.last_synced_at || spread.updated_at || spread.created_at;
      const maxLoss = toNumber(spread.max_loss);
      const entryRiskLines = [
        `Credit ${formatSpreadCredit(spread.entry_net_credit)}`,
        `Max Loss ${Number.isFinite(maxLoss) ? formatSignedCurrency(-Math.abs(maxLoss), "USD") : "--"}`,
        `BE ${formatSpreadStrike(spread.break_even)}`,
      ];
      const monitorMark = monitor
        ? [
            `Mark ${formatSpreadCredit(monitor.estimated_exit_debit)}`,
            `Spot ${formatSpreadStrike(monitor.underlying_price)}`,
            `${monitor.days_to_expiration ?? "--"} DTE`,
          ]
        : ["No monitor snapshot"];
      const distanceLines = monitor
        ? [
            `P/L ${formatSignedCurrency(monitor.estimated_pnl, "USD")}`,
            `TP Gap ${formatSpreadCredit(monitor.distance_to_take_profit_debit)}`,
            `SL Gap ${formatSpreadCredit(monitor.distance_to_stop_loss_debit)}`,
          ]
        : [spread.exit_reason ? formatSpreadExitReason(spread.exit_reason) : "--"];
      const monitorLines = monitor
        ? [
            monitor.exit_reason ? formatSpreadExitReason(monitor.exit_reason) : "Within thresholds",
            `Next Check ${formatDateTime(monitor.next_monitor_after)}`,
            `Updated ${formatDateTime(monitor.evaluated_at)}`,
          ]
        : [`Updated ${formatDateTime(lastUpdatedAt)}`];
      return `
        <tr>
          <td>
            <div class="symbol-cell">
              <strong>${escapeHtml(spread.underlying_symbol)}</strong>
              <span>${escapeHtml(legSummary)}</span>
            </div>
          </td>
          <td>${escapeHtml(formatSpreadDate(spread.expiration_date))}</td>
          <td><span class="pill ${statusTone}">${escapeHtml(formatSpreadStatusLabel(spread.status))}</span></td>
          <td>
            ${renderSpreadDetailCell(entryRiskLines)}
          </td>
          <td>
            ${renderSpreadDetailCell(monitorMark)}
          </td>
          <td>
            ${renderSpreadDetailCell(distanceLines, monitor?.estimated_pnl)}
          </td>
          <td>
            ${renderSpreadDetailCell(monitorLines)}
          </td>
          <td>
            <div class="table-actions">
              <button class="table-action" type="button" data-spread-action="refresh" data-spread-id="${escapeHtml(spread.id)}">
                Refresh
              </button>
              ${
                monitorable
                  ? `<button class="table-action primary" type="button" data-spread-action="monitor" data-spread-id="${escapeHtml(spread.id)}">Monitor</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderSpreadDetailCell(lines, pnlValue = null) {
  const [primary = "--", ...secondary] = lines;
  const toneClass = pnlValue !== null && pnlValue !== undefined ? ` is-${pnlTone(toNumber(pnlValue))}` : "";
  return `
    <div class="spread-detail-cell">
      <strong class="${toneClass.trim()}">${escapeHtml(primary)}</strong>
      ${secondary.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
    </div>
  `;
}

function renderOrders() {
  if (state.orders.length === 0) {
    els.ordersBody.innerHTML = '<tr><td colspan="7" class="empty-row">No orders for this account.</td></tr>';
    return;
  }

  els.ordersBody.innerHTML = state.orders
    .slice(0, 10)
    .map((order) => {
      const pillClass = statusClass(order.status);
      const canCancel = isCancelableOrder(order);
      const selectedClass = order.id === state.selectedOrderId ? "is-selected" : "";
      return `
        <tr class="${selectedClass}">
          <td>
            <div class="symbol-cell">
              <strong>${escapeHtml(order.symbol)}</strong>
              <span>${escapeHtml(order.order_type.toUpperCase())} / ${escapeHtml(order.time_in_force.toUpperCase())}</span>
            </div>
          </td>
          <td>${escapeHtml(order.side.toUpperCase())}</td>
          <td>${escapeHtml(String(order.quantity))}</td>
          <td><span class="pill ${pillClass}">${escapeHtml(order.status)}</span></td>
          <td>${escapeHtml(formatOrderPrice(order))}</td>
          <td>${escapeHtml(formatDateTime(order.updated_at))}</td>
          <td>
            <div class="table-actions">
              <button class="table-action primary" type="button" data-order-action="manage" data-order-id="${escapeHtml(order.id)}">
                Manage
              </button>
              <button class="table-action" type="button" data-order-action="refresh" data-order-id="${escapeHtml(order.id)}">
                Refresh
              </button>
              ${
                canCancel
                  ? `<button class="table-action danger" type="button" data-order-action="cancel" data-order-id="${escapeHtml(order.id)}">Cancel</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderPositions() {
  const snapshot = state.latestSnapshot;
  const positions = buildSortedPositions(snapshot?.positions || []);
  const currency = snapshot?.currency || "USD";
  const grossMarketValue = positions.reduce((sum, position) => sum + toFiniteNumber(position.market_value), 0);
  if (positions.length === 0) {
    els.positionsBody.innerHTML = '<tr><td colspan="7" class="empty-row">No positions in latest snapshot.</td></tr>';
    return;
  }

  els.positionsBody.innerHTML = positions
    .map(
      (position) => `
        <tr>
          <td>${escapeHtml(position.symbol)}</td>
          <td><span class="pill neutral">${escapeHtml(position.asset_type)}</span></td>
          <td>${escapeHtml(formatPositionQuantity(position.quantity))}</td>
          <td>${escapeHtml(formatCurrency(position.average_cost, currency))}</td>
          <td>${escapeHtml(formatCurrency(position.market_value, currency))}</td>
          <td><span class="pnl-chip ${pnlTone(toNumber(position.unrealized_pnl))}">${escapeHtml(formatSignedCurrency(position.unrealized_pnl, currency))}</span></td>
          <td>${escapeHtml(formatWeight(position.market_value, grossMarketValue))}</td>
        </tr>
      `
    )
    .join("");
}

function renderQuote() {
  if (!els.quoteCard || !els.quoteSymbol) {
    return;
  }
  const quote = state.quote;
  const overlay = state.quoteStatus;
  const symbol = quote?.symbol || els.quoteSymbol.value.trim().toUpperCase();
  if (!quote) {
    if (overlay.kind === "idle") {
      els.quoteCard.className = "quote-card empty";
      els.quoteCard.textContent = overlay.detail || "No quote loaded.";
      return;
    }

    els.quoteCard.className = "quote-card";
    els.quoteCard.innerHTML = `
      <div class="overlay-status-row">
        <div class="overlay-status-copy">
          <span class="section-kicker">${escapeHtml(symbol || "Quick Quote")}</span>
          <strong>${escapeHtml(overlayStatusLabel(overlay.kind))}</strong>
        </div>
        <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
      </div>
      <p class="overlay-detail">${escapeHtml(overlay.detail || "Quote refresh is waiting for the next response.")}</p>
      ${renderOverlayReason(overlay)}
    `;
    return;
  }

  const lastDone = Number(quote.last_done);
  const prevClose = Number(quote.prev_close);
  const diff = lastDone - prevClose;
  const pct = prevClose === 0 ? 0 : (diff / prevClose) * 100;
  const changeClass = diff >= 0 ? "positive" : "negative";
  const changePrefix = diff >= 0 ? "+" : "";

  els.quoteCard.className = "quote-card";
  els.quoteCard.innerHTML = `
    <div class="overlay-status-row">
      <div class="overlay-status-copy">
        <span class="section-kicker">${escapeHtml(quote.symbol)}</span>
        <div class="quote-price">
          <strong>${formatNumber(quote.last_done)}</strong>
          <span class="quote-change ${changeClass}">${changePrefix}${formatNumber(diff.toFixed(2))} / ${changePrefix}${pct.toFixed(2)}%</span>
        </div>
      </div>
      <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
    </div>
    <p class="overlay-detail">${escapeHtml(overlay.detail || overlayLiveDetail("Quote", quote.timestamp))}</p>
    ${renderOverlayReason(overlay)}
    <div class="quote-meta">
      <div><span>Open</span><strong>${formatNumber(quote.open)}</strong></div>
      <div><span>Prev Close</span><strong>${formatNumber(quote.prev_close)}</strong></div>
      <div><span>High</span><strong>${formatNumber(quote.high)}</strong></div>
      <div><span>Low</span><strong>${formatNumber(quote.low)}</strong></div>
      <div><span>Volume</span><strong>${Number(quote.volume).toLocaleString()}</strong></div>
      <div><span>Timestamp</span><strong>${escapeHtml(formatDateTime(quote.timestamp))}</strong></div>
    </div>
  `;
}

function renderPreOpenAssessment() {
  const assessment = state.preOpenAssessment;
  const overlay = state.preOpenStatus;
  updatePreOpenButtons();
  if (!assessment) {
    const detail = overlay.detail || "Waiting for the latest macro proxy snapshot.";
    const summaryValues = [
      {
        label: "Board Status",
        value: overlayStatusLabel(overlay.kind),
        tone: overlayStatusTone(overlay.kind),
        detail,
      },
      {
        label: "Downside Score",
        value: "--",
        tone: "",
        detail,
      },
      {
        label: "Regime",
        value: "--",
        tone: "",
        detail: "Load the live macro board to classify market tone.",
      },
      {
        label: "Plain Put View",
        value: "--",
        tone: "",
        detail: "QQQ / SPY directional put bias will render here.",
      },
      {
        label: "Preferred Vehicle",
        value: "--",
        tone: "",
        detail: "Waiting for proxy dispersion.",
      },
    ];

    els.preOpenSummaryStrip.innerHTML = summaryValues
      .map(
        (item) => `
          <article class="mini-metric-tile">
            <span class="metric-label">${escapeHtml(item.label)}</span>
            <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
            <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
          </article>
        `
      )
      .join("");

    els.preOpenAssessmentCard.className = `strategy-note-body ${overlay.kind === "idle" || overlay.kind === "loading" ? "empty" : ""}`;
    els.preOpenAssessmentCard.innerHTML = `
      <div class="overlay-status-row">
        <div class="overlay-status-copy">
          <strong>Real-time Macro Board</strong>
          <span>${escapeHtml(detail)}</span>
        </div>
        <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
      </div>
      ${renderOverlayReason(overlay)}
    `;
    els.preOpenSignals.innerHTML = '<div class="holding-empty">Waiting for market proxy signals.</div>';
    els.preOpenPuts.innerHTML = '<div class="holding-empty">Waiting for directional put snapshots.</div>';
    els.preOpenChainAnalysis.innerHTML = '<div class="holding-empty">Waiting for option chain analysis.</div>';
    return;
  }

  const summaryValues = [
    {
      label: "Board Status",
      value: overlayStatusLabel(overlay.kind),
      tone: overlayStatusTone(overlay.kind),
      detail: overlay.detail || overlayLiveDetail("Live macro board", assessment.analyzed_at),
    },
    {
      label: "Downside Score",
      value: String(assessment.downside_score),
      tone: preOpenScoreTone(assessment.downside_score),
      detail: assessment.reasons.length
        ? `${assessment.reasons.length} bearish trigger${assessment.reasons.length === 1 ? "" : "s"} in play`
        : "No major bearish trigger is active",
    },
    {
      label: "Regime",
      value: formatPreOpenLabel(assessment.regime),
      tone: preOpenRegimeTone(assessment.regime),
      detail: `Session: ${formatPreOpenLabel(assessment.session)}`,
    },
    {
      label: "Plain Put View",
      value: formatPreOpenLabel(assessment.plain_put_view),
      tone: preOpenViewTone(assessment.plain_put_view),
      detail: assessment.market_open ? "Regular U.S. session is live." : formatPreOpenTimingDetail(assessment),
    },
    {
      label: "Action",
      value: formatPreOpenLabel(assessment.trade_action),
      tone: preOpenActionTone(assessment.trade_action),
      detail: assessment.preferred_vehicle
        ? `${assessment.preferred_vehicle} is the cleaner vehicle if the tape confirms.`
        : "No clean SPY / QQQ vehicle is standing out.",
    },
    {
      label: "Gap Chase Risk",
      value: formatPreOpenLabel(assessment.gap_chase_risk),
      tone: preOpenGapTone(assessment.gap_chase_risk),
      detail: "Measures the risk of overpaying for plain puts into the open.",
    },
  ];

  els.preOpenSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  const reasonsMarkup = assessment.reasons.length
    ? assessment.reasons
        .map(
          (reason) => `
            <article class="strategy-journal-entry">
              <p>${escapeHtml(reason)}</p>
            </article>
          `
        )
        .join("")
    : '<div class="strategy-note-body empty">No bearish trigger is strong enough to favor plain index puts right now.</div>';
  const checkpointsMarkup = assessment.checkpoints.length
    ? assessment.checkpoints
        .map(
          (checkpoint) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(checkpoint.label)}</strong>
                <span>${escapeHtml(checkpoint.timing_label)}</span>
              </div>
              <div class="strategy-action-cell">
                <strong>${escapeHtml(formatPreOpenLabel(checkpoint.status))}</strong>
                <span>${escapeHtml(checkpoint.detail)}</span>
              </div>
            </article>
          `
        )
        .join("")
    : "";

  els.preOpenAssessmentCard.className = "strategy-note-body";
  els.preOpenAssessmentCard.innerHTML = `
    <div class="overlay-status-row">
      <div class="overlay-status-copy">
        <strong>${escapeHtml(assessment.summary)}</strong>
        <span>${escapeHtml(formatDateTime(assessment.analyzed_at))}</span>
      </div>
      <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
    </div>
    <p class="overlay-detail">${escapeHtml(overlay.detail || overlayLiveDetail("Live macro board", assessment.analyzed_at))}</p>
    ${renderOverlayReason(overlay)}
    <div class="status-list">
      <div>
        <dt>Preferred Vehicle</dt>
        <dd>${escapeHtml(assessment.preferred_vehicle || "--")}</dd>
      </div>
      <div>
        <dt>Action</dt>
        <dd>${escapeHtml(formatPreOpenLabel(assessment.trade_action))}</dd>
      </div>
      <div>
        <dt>Gap Chase Risk</dt>
        <dd>${escapeHtml(formatPreOpenLabel(assessment.gap_chase_risk))}</dd>
      </div>
      <div>
        <dt>Session</dt>
        <dd>${escapeHtml(formatPreOpenTimingDetail(assessment))}</dd>
      </div>
      <div>
        <dt>Coverage</dt>
        <dd>${escapeHtml(formatPreOpenCoverage(assessment))}</dd>
      </div>
    </div>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(formatPreOpenNarrative(assessment))}</p>
    </article>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(assessment.trade_action_detail)}</p>
    </article>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(assessment.gap_chase_detail)}</p>
    </article>
    ${reasonsMarkup}
    ${checkpointsMarkup}
  `;

  if (!assessment.signals.length) {
    els.preOpenSignals.innerHTML = '<div class="holding-empty">No market proxy signals are available.</div>';
  } else {
    els.preOpenSignals.innerHTML = assessment.signals
      .map(
        (signal) => `
          <article class="holding-card">
            <div class="holding-head">
              <div class="symbol-block">
                <strong>${escapeHtml(signal.label)}</strong>
                <span>${escapeHtml(signal.symbol)}</span>
              </div>
              <span class="pill ${preOpenSignalTone(signal.signal)}">${escapeHtml(formatPreOpenLabel(signal.signal))}</span>
            </div>
            <div class="holding-stats">
              <div>
                <span>Session Px</span>
                <strong>${escapeHtml(formatNumber(signal.session_price))}</strong>
              </div>
              <div>
                <span>Prev Close</span>
                <strong>${escapeHtml(formatNumber(signal.reference_price))}</strong>
              </div>
              <div>
                <span>Change</span>
                <strong>${escapeHtml(formatSignedPercentValue(signal.change_pct))}</strong>
              </div>
            </div>
            <span class="mini-metric-detail">${escapeHtml(signal.note || "No extra context for this proxy move.")}</span>
          </article>
        `
      )
      .join("");
  }

  if (!assessment.put_snapshots.length) {
    els.preOpenPuts.innerHTML = preOpenOptionOverlaysSkipped(assessment)
      ? '<div class="holding-empty">Option overlays were skipped for fast macro refresh. Use Load Option Overlays to inspect QQQ / SPY puts.</div>'
      : '<div class="holding-empty">No short-dated reference puts were found.</div>';
  } else {
    els.preOpenPuts.innerHTML = assessment.put_snapshots
      .map((snapshot) => {
        const preferred =
          assessment.preferred_vehicle && snapshot.underlying_symbol.startsWith(assessment.preferred_vehicle);
        return `
          <article class="holding-card">
            <div class="holding-head">
              <div class="symbol-block">
                <strong>${escapeHtml(snapshot.underlying_symbol)}</strong>
                <span>${escapeHtml(snapshot.put_symbol)}</span>
              </div>
              <span class="pill ${preferred ? "warning" : preOpenLiquidityTone(snapshot.liquidity_label)}">${escapeHtml(preferred ? "Preferred" : snapshot.liquidity_label || "Reference")}</span>
            </div>
            <div class="holding-stats">
              <div>
                <span>Expiry</span>
                <strong>${escapeHtml(formatSpreadDate(snapshot.expiration_date))}</strong>
              </div>
              <div>
                <span>Strike</span>
                <strong>${escapeHtml(formatSpreadStrike(snapshot.strike))}</strong>
              </div>
              <div>
                <span>DTE</span>
                <strong>${escapeHtml(String(snapshot.days_to_expiration))}</strong>
              </div>
                <div>
                  <span>Bid / Ask</span>
                  <strong>${escapeHtml(`${formatNumber(snapshot.bid)} / ${formatNumber(snapshot.ask)}`)}</strong>
                </div>
                <div>
                  <span>Mid / Spread</span>
                  <strong>${escapeHtml(`${formatNumber(snapshot.mid_price)} / ${formatPercentValue(snapshot.spread_pct)}`)}</strong>
                </div>
                <div>
                  <span>Delta / IV</span>
                  <strong>${escapeHtml(`${formatSignedDecimal(snapshot.delta, 2)} / ${formatImpliedVolatility(snapshot.implied_volatility)}`)}</strong>
                </div>
                <div>
                  <span>Spot Distance</span>
                  <strong>${escapeHtml(formatSpotDistance(snapshot.distance_from_spot_pct))}</strong>
                </div>
              </div>
            </article>
        `;
      })
      .join("");
  }

  renderPreOpenChainAnalysis(assessment);
}

function renderPreOpenChainAnalysis(assessment) {
  const analyses = assessment?.chain_analyses || [];
  if (!Array.isArray(analyses) || !analyses.length) {
    els.preOpenChainAnalysis.innerHTML = preOpenOptionOverlaysSkipped(assessment)
      ? '<div class="holding-empty">Option-chain overlays were skipped for fast macro refresh. Load option overlays when you need volatility and liquidity detail.</div>'
      : '<div class="holding-empty">No option chain analysis is available.</div>';
    return;
  }

  els.preOpenChainAnalysis.innerHTML = analyses
    .map((analysis) => {
      const front = analysis.front_expiration;
      const next = analysis.next_expiration;
      const termLabel = formatOptionTermStructure(analysis.term_structure_label);
      return `
        <article class="holding-card">
          <div class="holding-head">
            <div class="symbol-block">
              <strong>${escapeHtml(analysis.underlying_symbol)}</strong>
              <span>${escapeHtml(analysis.sample_note || "Front/next expiry summary with liquidity sampling.")}</span>
            </div>
            <span class="pill ${preOpenTermTone(analysis.term_structure_label)}">${escapeHtml(termLabel)}</span>
          </div>
          <div class="holding-stats">
            <div>
              <span>Spot</span>
              <strong>${escapeHtml(formatNumber(analysis.underlying_price))}</strong>
            </div>
            <div>
              <span>Front ATM IV</span>
              <strong>${escapeHtml(front ? formatImpliedVolatility(front.atm_implied_volatility) : "--")}</strong>
            </div>
            <div>
              <span>Next ATM IV</span>
              <strong>${escapeHtml(next ? formatImpliedVolatility(next.atm_implied_volatility) : "--")}</strong>
            </div>
            <div>
              <span>Term Slope</span>
              <strong>${escapeHtml(formatSignedIvDifference(analysis.atm_iv_term_diff))}</strong>
            </div>
            <div>
              <span>Front Put Skew</span>
              <strong>${escapeHtml(front ? formatSignedIvDifference(front.put_skew_diff) : "--")}</strong>
            </div>
            <div>
              <span>Front Median Spread</span>
              <strong>${escapeHtml(front ? formatPercentValue(front.median_spread_pct) : "--")}</strong>
            </div>
          </div>
          ${front ? renderOptionExpiryAnalysis(front, "Front Expiry") : ""}
          ${next ? renderOptionExpiryAnalysis(next, "Next Expiry") : ""}
        </article>
      `;
    })
    .join("");
}

function renderLatestPreOpenRun() {
  const run = Array.isArray(state.preOpenRuns) && state.preOpenRuns.length ? state.preOpenRuns[0] : null;
  if (!state.selectedAccountId) {
    els.preOpenRunReview.className = "strategy-note-body empty";
    els.preOpenRunReview.textContent = "Select a broker account to load the latest pre-open capture and opening review.";
    return;
  }

  if (!run) {
    els.preOpenRunReview.className = "strategy-note-body empty";
    els.preOpenRunReview.textContent = "No pre-open capture has been stored for this broker account yet.";
    return;
  }

  const checkpoints = Array.isArray(run.checkpoints) ? run.checkpoints : [];
  const capturedCount = checkpoints.filter((checkpoint) => checkpoint.captured_at).length;
  const checkpointMarkup = checkpoints.length
    ? checkpoints
        .map(
          (checkpoint) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(checkpoint.label)}</strong>
                <span>${escapeHtml(checkpoint.timing_label)}</span>
              </div>
              <div class="status-list">
                <div>
                  <dt>Status</dt>
                  <dd><span class="pill ${preOpenReviewTone(checkpoint.status)}">${escapeHtml(formatPreOpenLabel(checkpoint.status))}</span></dd>
                </div>
                <div>
                  <dt>Review</dt>
                  <dd><span class="pill ${preOpenReviewTone(checkpoint.confirmation)}">${escapeHtml(formatPreOpenLabel(checkpoint.confirmation || "pending"))}</span></dd>
                </div>
                <div>
                  <dt>QQQ / SPY</dt>
                  <dd>${escapeHtml(`${formatSignedPercentValue(checkpoint.qqq_change_pct)} / ${formatSignedPercentValue(checkpoint.spy_change_pct)}`)}</dd>
                </div>
                <div>
                  <dt>Semis</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.semis_change_pct))}</dd>
                </div>
                <div>
                  <dt>QQQ vs SPY</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.qqq_vs_spy_diff))}</dd>
                </div>
                <div>
                  <dt>Semis vs QQQ</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.semis_vs_qqq_diff))}</dd>
                </div>
              </div>
              <p>${escapeHtml(checkpoint.detail || "Opening review is still waiting for this checkpoint.")}</p>
            </article>
          `
        )
        .join("")
    : '<div class="holding-empty">No opening checkpoints were stored for this run.</div>';

  const assessmentSummary = run.assessment?.summary || "Stored pre-open assessment.";
  const reviewSummary = run.review_summary || "Opening follow-through review is still waiting for the first checkpoint.";
  const targetSession = formatSessionDate(run.target_session_date);
  const nextOpen = run.assessment?.next_regular_open_at ? formatDateTime(run.assessment.next_regular_open_at) : "--";

  els.preOpenRunReview.className = "strategy-note-body";
  els.preOpenRunReview.innerHTML = `
    <div class="strategy-journal-head">
      <strong>${escapeHtml(assessmentSummary)}</strong>
      <span>${escapeHtml(formatDateTime(run.created_at))}</span>
    </div>
    <div class="status-list">
      <div>
        <dt>Target Session</dt>
        <dd>${escapeHtml(targetSession)}</dd>
      </div>
      <div>
        <dt>Review Status</dt>
        <dd><span class="pill ${preOpenReviewTone(run.review_status)}">${escapeHtml(formatPreOpenLabel(run.review_status))}</span></dd>
      </div>
      <div>
        <dt>Checkpoints</dt>
        <dd>${escapeHtml(`${capturedCount} / ${checkpoints.length}`)}</dd>
      </div>
      <div>
        <dt>Next Open</dt>
        <dd>${escapeHtml(nextOpen)}</dd>
      </div>
      <div>
        <dt>Preferred Vehicle</dt>
        <dd>${escapeHtml(run.assessment?.preferred_vehicle || "--")}</dd>
      </div>
      <div>
        <dt>Action Bias</dt>
        <dd>${escapeHtml(formatPreOpenLabel(run.assessment?.trade_action || "--"))}</dd>
      </div>
    </div>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(reviewSummary)}</p>
    </article>
    ${checkpointMarkup}
  `;
}

function preOpenOptionOverlaysSkipped(assessment) {
  const detail = `${assessment?.freshness_detail || ""} ${(assessment?.reasons || []).join(" ")}`.toLowerCase();
  return detail.includes("option overlays skipped");
}

function formatPreOpenCoverage(assessment) {
  const signalCount = Array.isArray(assessment?.signals) ? assessment.signals.length : 0;
  const putCount = Array.isArray(assessment?.put_snapshots) ? assessment.put_snapshots.length : 0;
  const chainCount = Array.isArray(assessment?.chain_analyses) ? assessment.chain_analyses.length : 0;
  if (preOpenOptionOverlaysSkipped(assessment)) {
    return `${signalCount} proxies / option overlays skipped`;
  }
  return `${signalCount} proxies / ${putCount} puts / ${chainCount} chain layers`;
}

function renderOptionExpiryAnalysis(expiry, label) {
  const liquidMarkup = Array.isArray(expiry.liquid_strikes) && expiry.liquid_strikes.length
    ? expiry.liquid_strikes
        .map(
          (strike) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(formatSpreadStrike(strike.strike))}</strong>
                <span>${escapeHtml(strike.put_symbol)}</span>
              </div>
              <div class="holding-stats compact">
                <div>
                  <span>OI / Vol</span>
                  <strong>${escapeHtml(`${formatPositionQuantity(strike.open_interest)} / ${formatPositionQuantity(strike.volume)}`)}</strong>
                </div>
                <div>
                  <span>Bid / Ask</span>
                  <strong>${escapeHtml(`${formatNumber(strike.bid)} / ${formatNumber(strike.ask)}`)}</strong>
                </div>
                <div>
                  <span>Spread / Delta</span>
                  <strong>${escapeHtml(`${formatPercentValue(strike.spread_pct)} / ${formatSignedDecimal(strike.delta, 2)}`)}</strong>
                </div>
              </div>
            </article>
          `
        )
        .join("")
    : '<div class="strategy-note-body empty">No liquid strikes were sampled for this expiry.</div>';

  return `
    <article class="strategy-journal-entry">
      <div class="strategy-journal-head">
        <strong>${escapeHtml(label)}</strong>
        <span>${escapeHtml(`${formatSpreadDate(expiry.expiration_date)} (${expiry.days_to_expiration} DTE)`)}</span>
      </div>
      <div class="status-list">
        <div>
          <dt>ATM Put</dt>
          <dd>${escapeHtml(`${formatSpreadStrike(expiry.atm_strike)} / ${formatNumber(expiry.atm_mid_price)}`)}</dd>
        </div>
        <div>
          <dt>ATM Delta / IV</dt>
          <dd>${escapeHtml(`${formatSignedDecimal(expiry.atm_delta, 2)} / ${formatImpliedVolatility(expiry.atm_implied_volatility)}`)}</dd>
        </div>
        <div>
          <dt>Put Skew Leg</dt>
          <dd>${escapeHtml(expiry.put_skew_strike ? `${formatSpreadStrike(expiry.put_skew_strike)} / ${formatSignedDecimal(expiry.put_skew_delta, 2)}` : "--")}</dd>
        </div>
        <div>
          <dt>Skew IV Lift</dt>
          <dd>${escapeHtml(formatSignedIvDifference(expiry.put_skew_diff))}</dd>
        </div>
        <div>
          <dt>Spread Buckets</dt>
          <dd>${escapeHtml(`${expiry.tight_count} tight / ${expiry.workable_count} workable / ${expiry.wide_count} wide`)}</dd>
        </div>
        <div>
          <dt>Median Spread</dt>
          <dd>${escapeHtml(formatPercentValue(expiry.median_spread_pct))}</dd>
        </div>
      </div>
      ${liquidMarkup}
    </article>
  `;
}

function renderSelectedOrder() {
  const order = getSelectedOrder();
  if (!order) {
    els.selectedOrderCard.className = "selected-order empty";
    els.selectedOrderCard.textContent = "Select an order from the table to manage it.";
    renderSelectedExecution();
    renderSelectedJournal();
    hideReplaceForm();
    return;
  }

  const canReplace = isReplaceableOrder(order);
  const canCancel = isCancelableOrder(order);
  const statusTone = statusClass(order.status);

  els.selectedOrderCard.className = "selected-order";
  els.selectedOrderCard.innerHTML = `
    <div class="selected-order-head">
      <div>
        <span class="section-kicker">Selected Order</span>
        <h3 class="selected-order-title">${escapeHtml(order.symbol)} ${escapeHtml(order.side.toUpperCase())} x ${escapeHtml(String(order.quantity))}</h3>
      </div>
      <span class="pill ${statusTone}">${escapeHtml(order.status)}</span>
    </div>
    <div class="selected-order-meta">
      <div>
        <span>External ID</span>
        <strong>${escapeHtml(order.external_order_id || "--")}</strong>
      </div>
      <div>
        <span>Account</span>
        <strong>${escapeHtml(order.external_account_id)}</strong>
      </div>
      <div>
        <span>Order Type</span>
        <strong>${escapeHtml(order.order_type.toUpperCase())}</strong>
      </div>
      <div>
        <span>Time In Force</span>
        <strong>${escapeHtml(order.time_in_force.toUpperCase())}</strong>
      </div>
      <div>
        <span>Price Logic</span>
        <strong>${escapeHtml(formatOrderPrice(order))}</strong>
      </div>
      <div>
        <span>Updated</span>
        <strong>${escapeHtml(formatDateTime(order.updated_at))}</strong>
      </div>
    </div>
    <div class="selected-order-actions">
      <button class="icon-button" type="button" data-selected-action="refresh">
        <span class="icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
            <path d="M21 3v6h-6"/>
          </svg>
        </span>
        <span>Refresh</span>
      </button>
      ${
        canCancel
          ? `
            <button class="icon-button" type="button" data-selected-action="cancel">
              <span class="icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M18 6 6 18"/>
                  <path d="m6 6 12 12"/>
                </svg>
              </span>
              <span>Cancel</span>
            </button>
          `
          : ""
      }
    </div>
    ${
      canReplace
        ? ""
        : '<p class="form-hint">Filled, canceled, and rejected orders can be refreshed but not replaced.</p>'
    }
  `;

  if (canReplace) {
    populateReplaceForm(order);
  } else {
    hideReplaceForm();
  }

  renderSelectedExecution();
  renderSelectedJournal();
}

function setSelectedOrder(orderId, shouldScroll = false) {
  state.selectedOrderId = orderId;
  renderOrders();
  renderSelectedOrder();

  if (shouldScroll) {
    els.selectedOrderCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function getSelectedOrder() {
  return state.orders.find((order) => order.id === state.selectedOrderId) || null;
}

function getSelectedAccount() {
  return state.accounts.find((account) => account.external_account_id === state.selectedAccountId) || null;
}

function getSelectedExecution() {
  return state.executions.find((execution) => execution.order_id === state.selectedOrderId) || null;
}

function getSelectedJournalEntries() {
  const order = getSelectedOrder();
  if (!order) {
    return [];
  }

  return state.journals.filter(
    (entry) =>
      entry.order_id === order.id ||
      (order.trade_plan_id && entry.trade_plan_id === order.trade_plan_id)
  );
}

function renderSelectedExecution() {
  const execution = getSelectedExecution();
  if (!execution) {
    els.selectedOrderExecution.className = "selected-order-execution empty";
    els.selectedOrderExecution.textContent = "No fills recorded for this order yet.";
    return;
  }

  els.selectedOrderExecution.className = "selected-order-execution";
  els.selectedOrderExecution.innerHTML = `
    <div class="execution-grid">
      <div>
        <span>Filled Qty</span>
        <strong>${escapeHtml(formatPositionQuantity(execution.quantity))}</strong>
      </div>
      <div>
        <span>Avg Fill</span>
        <strong>${escapeHtml(formatCurrency(execution.price))}</strong>
      </div>
      <div>
        <span>Last Fill</span>
        <strong>${escapeHtml(formatDateTime(execution.executed_at))}</strong>
      </div>
    </div>
    <p class="form-hint">Derived from the latest broker order detail snapshot for this order.</p>
  `;
}

function renderSelectedJournal() {
  const order = getSelectedOrder();
  if (!order) {
    updateJournalFormAvailability(false);
    els.journalFormHint.textContent = "Select an order to save a plan note or post-trade review.";
    els.selectedOrderJournal.className = "selected-order-journal empty";
    els.selectedOrderJournal.textContent = "Select an order to load journal entries.";
    return;
  }

  updateJournalFormAvailability(true);
  const execution = getSelectedExecution();
  const entries = getSelectedJournalEntries();
  const context = [];
  if (order.trade_plan_id) {
    context.push("trade plan context");
  }
  if (execution) {
    context.push("latest fill context");
  }
  els.journalFormHint.textContent = context.length
    ? `New entries will attach ${context.join(" and ")} for ${order.symbol}.`
    : `New entries will attach to ${order.symbol} on ${order.external_account_id}.`;

  if (!entries.length) {
    els.selectedOrderJournal.className = "selected-order-journal empty";
    els.selectedOrderJournal.textContent = "No journal entries linked to this order yet.";
    return;
  }

  els.selectedOrderJournal.className = "selected-order-journal";
  els.selectedOrderJournal.innerHTML = entries
    .map((entry) => {
      const linkMeta = [];
      if (entry.trade_plan_id) {
        linkMeta.push("Plan linked");
      }
      if (entry.execution_id) {
        linkMeta.push("Execution linked");
      }
      const tags = entry.tags.length
        ? `<div class="journal-entry-tags">${entry.tags
            .map((tag) => `<span class="journal-tag">${escapeHtml(tag)}</span>`)
            .join("")}</div>`
        : "";

      return `
        <article class="journal-entry-card">
          <div class="journal-entry-head">
            <div class="journal-entry-title-block">
              <span class="pill ${journalEntryTone(entry.entry_type)}">${escapeHtml(entry.entry_type)}</span>
              <strong>${escapeHtml(entry.title)}</strong>
            </div>
            <span class="journal-entry-time">${escapeHtml(formatDateTime(entry.updated_at))}</span>
          </div>
          <div class="journal-entry-meta">
            <span>${escapeHtml(linkMeta.join(" / ") || "Order linked")}</span>
            <span>${escapeHtml(entry.symbol)}</span>
          </div>
          <p class="journal-entry-notes">${formatMultilineText(entry.notes)}</p>
          ${tags}
        </article>
      `;
    })
    .join("");
}

function updateJournalFormAvailability(enabled) {
  els.journalEntryType.disabled = !enabled;
  els.journalTitle.disabled = !enabled;
  els.journalTags.disabled = !enabled;
  els.journalNotes.disabled = !enabled;
  els.submitJournal.disabled = !enabled;
  els.submitJournal.title = enabled ? "" : "Select an order first.";
}

function populateReplaceForm(order) {
  els.replaceOrderForm.dataset.orderId = order.id;
  els.replaceQuantity.value = String(order.quantity);
  els.replaceLimitPrice.value = order.limit_price ?? "";
  els.replaceStopPrice.value = order.stop_price ?? "";
  els.replaceRemark.value = "";
  syncReplaceOrderFields(order.order_type);
  els.replaceOrderForm.classList.remove("hidden");
}

function hideReplaceForm() {
  els.replaceOrderForm.dataset.orderId = "";
  els.replaceOrderForm.classList.add("hidden");
}

function updateOrderTicketAvailability() {
  const hasAccount = Boolean(state.selectedAccountId);
  els.submitOrder.disabled = !hasAccount;
  els.submitOrder.title = hasAccount ? "" : "Select a broker account first.";
}

function updateSyncButtons() {
  const account = getSelectedAccount();
  const hasAccount = Boolean(account);
  const accountSyncing = account?.account_sync_status === "syncing";
  const ordersSyncing = account?.orders_sync_status === "syncing";

  els.syncAccount.disabled = !hasAccount || accountSyncing;
  els.syncOrders.disabled = !hasAccount || ordersSyncing;
  els.syncAccount.title = !hasAccount ? "Select a broker account first." : accountSyncing ? "Account sync already in progress." : "";
  els.syncOrders.title = !hasAccount ? "Select a broker account first." : ordersSyncing ? "Order sync already in progress." : "";
}

function updateStrategyButtons() {
  const hasAccount = Boolean(state.selectedAccountId);
  els.saveStrategyControls.disabled = !hasAccount;
  els.runStrategyScan.disabled = !hasAccount;
  els.runStrategyReview.disabled = !hasAccount;
  els.saveStrategyControls.title = hasAccount ? "" : "Select a broker account first.";
  els.runStrategyScan.title = hasAccount ? "" : "Select a broker account first.";
  els.runStrategyReview.title = hasAccount ? "" : "Select a broker account first.";
}

function updatePreOpenButtons(forceSaving = false) {
  if (!els.loadPreOpenBoard || !els.loadPreOpenOverlays || !els.savePreOpenBoard) {
    return;
  }
  const hasAccount = Boolean(state.selectedAccountId);
  const loading = state.preOpenStatus?.kind === "loading";
  const hasLoadedAssessment = Boolean(state.preOpenAssessment) && !loading;
  const canSaveAssessment = hasLoadedAssessment && (state.preOpenStatus.kind === "live" || state.preOpenStatus.kind === "partial");

  els.loadPreOpenBoard.disabled = !hasAccount || loading;
  els.loadPreOpenOverlays.disabled = !hasAccount || loading;
  els.savePreOpenBoard.disabled = !hasAccount || !canSaveAssessment || forceSaving;

  els.loadPreOpenBoard.title = hasAccount ? "Refresh the fast live macro board." : "Select a broker account first.";
  els.loadPreOpenOverlays.title = hasAccount ? "Load slower QQQ / SPY option overlays on demand." : "Select a broker account first.";
  els.savePreOpenBoard.title = canSaveAssessment ? "Store the current live macro board as the latest run." : "Load the live macro board first.";
}

function syncTicketOrderFields() {
  syncOrderTypeFields({
    orderType: els.orderType.value,
    limitField: els.orderLimitField,
    stopField: els.orderStopField,
    limitInput: els.orderLimitPrice,
    stopInput: els.orderStopPrice,
    hintEl: els.orderFormHint,
    marketHint: "Market orders use the selected paper account and do not require a price.",
    limitHint: "Limit orders require a limit price.",
    stopHint: "Stop orders require a stop price. Add an optional limit price to send a stop-limit style order.",
  });
}

function syncReplaceOrderFields(orderType) {
  syncOrderTypeFields({
    orderType,
    limitField: els.replaceLimitField,
    stopField: els.replaceStopField,
    limitInput: els.replaceLimitPrice,
    stopInput: els.replaceStopPrice,
    hintEl: els.replaceFormHint,
    marketHint: "Market order replacements update quantity only.",
    limitHint: "Limit order replacements require a limit price.",
    stopHint: "Stop order replacements require a stop price. Limit price remains optional.",
  });
}

function syncOrderTypeFields({
  orderType,
  limitField,
  stopField,
  limitInput,
  stopInput,
  hintEl,
  marketHint,
  limitHint,
  stopHint,
}) {
  const showLimit = orderType === "limit" || orderType === "stop";
  const showStop = orderType === "stop";

  setFieldVisibility(limitField, limitInput, showLimit);
  setFieldVisibility(stopField, stopInput, showStop);

  if (orderType === "market") {
    limitInput.value = "";
    stopInput.value = "";
    hintEl.textContent = marketHint;
    return;
  }

  if (orderType === "limit") {
    stopInput.value = "";
    hintEl.textContent = limitHint;
    return;
  }

  hintEl.textContent = stopHint;
}

function setFieldVisibility(field, input, visible) {
  field.classList.toggle("hidden", !visible);
  input.disabled = !visible;
}

function buildCreateOrderPayload() {
  const symbol = els.orderSymbol.value.trim().toUpperCase();
  if (!symbol) {
    throw new Error("Order symbol is required.");
  }

  const payload = {
    external_account_id: state.selectedAccountId,
    symbol,
    side: els.orderSide.value,
    quantity: parsePositiveInteger(els.orderQuantity.value, "Order quantity"),
    order_type: els.orderType.value,
    time_in_force: els.orderTimeInForce.value,
    mode: "paper",
    remark: normalizeOptionalText(els.orderRemark.value),
  };
  applyOrderTypePrices({
    orderType: payload.order_type,
    limitValue: els.orderLimitPrice.value,
    stopValue: els.orderStopPrice.value,
    payload,
    contextLabel: "Order",
  });
  return payload;
}

function buildReplaceOrderPayload(order) {
  const payload = {
    quantity: parsePositiveInteger(els.replaceQuantity.value, "Replace quantity"),
    remark: normalizeOptionalText(els.replaceRemark.value),
  };
  applyOrderTypePrices({
    orderType: order.order_type,
    limitValue: els.replaceLimitPrice.value,
    stopValue: els.replaceStopPrice.value,
    payload,
    contextLabel: "Replace",
  });
  return payload;
}

function applyOrderTypePrices({ orderType, limitValue, stopValue, payload, contextLabel }) {
  if (orderType === "market") {
    payload.limit_price = null;
    payload.stop_price = null;
    return;
  }

  if (orderType === "limit") {
    payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, true);
    payload.stop_price = null;
    return;
  }

  if (orderType === "stop") {
    payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, false);
    payload.stop_price = parsePositiveNumber(stopValue, `${contextLabel} stop price`, true);
    return;
  }

  throw new Error(`Unsupported order type: ${orderType}`);
}

function parsePositiveInteger(value, label) {
  const number = Number.parseInt(String(value).trim(), 10);
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`${label} must be a positive whole number.`);
  }
  return number;
}

function parsePositiveNumber(value, label, required) {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) {
    if (required) {
      throw new Error(`${label} is required.`);
    }
    return null;
  }

  const number = Number(trimmed);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`${label} must be greater than 0.`);
  }
  return number;
}

function normalizeOptionalText(value) {
  const trimmed = String(value ?? "").trim();
  return trimmed ? trimmed : null;
}

function parseTags(value) {
  const seen = new Set();
  return String(value ?? "")
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => {
      if (!tag || seen.has(tag)) {
        return false;
      }
      seen.add(tag);
        return true;
      });
}

function parseSymbolList(value) {
  return String(value ?? "")
    .split(",")
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);
}

function isCancelableOrder(order) {
  return order.status === "created" || order.status === "submitted" || order.status === "partially_filled";
}

function isActiveSpread(spread) {
  return (
    spread.status === "entry_pending_long" ||
    spread.status === "entry_pending_short" ||
    spread.status === "open" ||
    spread.status === "exit_pending_short" ||
    spread.status === "exit_pending_long"
  );
}

function isExitPendingSpread(spread) {
  return spread.status === "exit_pending_short" || spread.status === "exit_pending_long";
}

function isMonitorableSpread(spread) {
  return spread.status === "open" || isExitPendingSpread(spread);
}

function isReplaceableOrder(order) {
  return order.status === "created" || order.status === "submitted" || order.status === "partially_filled";
}

function formatOrderPrice(order) {
  const parts = [];
  if (order.limit_price !== null && order.limit_price !== undefined) {
    parts.push(`L ${formatNumber(order.limit_price)}`);
  }
  if (order.stop_price !== null && order.stop_price !== undefined) {
    parts.push(`S ${formatNumber(order.stop_price)}`);
  }
  return parts.length > 0 ? parts.join(" / ") : "--";
}

function buildSortedPositions(positions) {
  return [...positions].sort((left, right) => toFiniteNumber(right.market_value) - toFiniteNumber(left.market_value));
}

function pnlTone(value) {
  if (value > 0) {
    return "success";
  }
  if (value < 0) {
    return "error";
  }
  return "neutral";
}

function describeStrategyStatus(runtime) {
  if (runtime.holding_open_position) {
    return {
      value: "Monitoring",
      tone: "warning",
      detail: `${runtime.open_spread_count || 1} open / next ${formatDateTime(runtime.next_monitor_after)}`,
    };
  }
  if (runtime.daily_entry_cap_reached) {
    return {
      value: "Daily Cap",
      tone: "warning",
      detail: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "Wait next session",
    };
  }
  if (runtime.kill_switch_active) {
    return {
      value: "Kill Switch",
      tone: "error",
      detail: "New bull put entries are blocked until the kill switch is cleared.",
    };
  }
  if (runtime.manual_pause) {
    return {
      value: "Paused",
      tone: "warning",
      detail: "Manual pause blocks new bull put entries while monitoring stays active.",
    };
  }
  if (!runtime.auto_entry_enabled) {
    return {
      value: "Disabled",
      tone: "neutral",
      detail: "Automatic entry is disabled for this account.",
    };
  }
  if ((runtime.paused_symbols || []).length) {
    return {
      value: "Selective Pause",
      tone: "warning",
      detail: `Paused symbols: ${(runtime.paused_symbols || []).join(", ")}`,
    };
  }
  return {
    value: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "Running",
    tone: "success",
    detail: runtime.entry_block_reason || "Automatic bull put entry is enabled for this account.",
  };
}

function preOpenScoreTone(score) {
  const number = toFiniteNumber(score);
  if (number >= 5) {
    return "error";
  }
  if (number >= 3) {
    return "warning";
  }
  return "success";
}

function preOpenRegimeTone(regime) {
  if (regime === "broad_downside_risk") {
    return "error";
  }
  if (regime === "selective_downside_risk") {
    return "warning";
  }
  return "success";
}

function preOpenViewTone(view) {
  if (view === "reasonable") {
    return "warning";
  }
  if (view === "selective") {
    return "neutral";
  }
  return "success";
}

function preOpenActionTone(action) {
  if (action === "wait_for_failed_bounce" || action === "wait_for_open_confirmation") {
    return "warning";
  }
  if (action === "use_intraday_confirmation" || action === "selective_probe_only") {
    return "neutral";
  }
  return "success";
}

function preOpenGapTone(risk) {
  if (risk === "high") {
    return "error";
  }
  if (risk === "medium") {
    return "warning";
  }
  return "success";
}

function preOpenSignalTone(signal) {
  if (signal === "bearish") {
    return "error";
  }
  if (signal === "supportive") {
    return "success";
  }
  return "neutral";
}

function preOpenLiquidityTone(label) {
  if (label === "wide") {
    return "error";
  }
  if (label === "workable") {
    return "warning";
  }
  if (label === "tight") {
    return "success";
  }
  return "neutral";
}

function preOpenTermTone(label) {
  if (label === "front_loaded") {
    return "error";
  }
  if (label === "next_richer") {
    return "warning";
  }
  return "neutral";
}

function preOpenReviewTone(value) {
  if (value === "confirmed") {
    return "success";
  }
  if (value === "failed") {
    return "error";
  }
  if (value === "mixed" || value === "in_progress" || value === "awaiting_open") {
    return "warning";
  }
  return "neutral";
}

function formatPreOpenLabel(value) {
  return String(value || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatOptionTermStructure(label) {
  if (label === "front_loaded") {
    return "Front Loaded";
  }
  if (label === "next_richer") {
    return "Next Richer";
  }
  if (label === "flat") {
    return "Flat";
  }
  return "Unclear";
}

function formatSignedIvDifference(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const points = Math.abs(number) <= 1 ? number * 100 : number;
  const prefix = points > 0 ? "+" : "";
  return `${prefix}${points.toFixed(1)} pts`;
}

function formatPreOpenTimingDetail(assessment) {
  if (assessment.market_open) {
    return "Regular U.S. session is live.";
  }
  if (assessment.minutes_to_regular_open !== null && assessment.minutes_to_regular_open !== undefined) {
    return `${assessment.minutes_to_regular_open} min to 09:30 ET regular open.`;
  }
  if (assessment.next_regular_open_at) {
    const nextOpen = new Date(assessment.next_regular_open_at);
    if (!Number.isNaN(nextOpen.getTime())) {
      const month = String(nextOpen.getMonth() + 1).padStart(2, "0");
      const day = String(nextOpen.getDate()).padStart(2, "0");
      return `Next regular open: ${nextOpen.getFullYear()}-${month}-${day} 09:30 ET.`;
    }
  }
  if (assessment.session === "holiday") {
    return "U.S. equity options are closed for a market holiday.";
  }
  if (assessment.session === "weekend") {
    return "U.S. equity options are closed for the weekend.";
  }
  return `${formatPreOpenLabel(assessment.session)} session snapshot.`;
}

function formatPreOpenNarrative(assessment) {
  const timing = formatPreOpenTimingDetail(assessment);
  if (!assessment.preferred_vehicle) {
    return `${assessment.summary} ${timing} ${assessment.trade_action_detail}`;
  }
  return `${assessment.summary} ${assessment.preferred_vehicle} is the cleaner plain-put expression for now. ${timing}`;
}

function formatSpotDistance(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  const suffix = number >= 0 ? " OTM" : " ITM";
  return `${prefix}${number.toFixed(2)}%${suffix}`;
}

function formatRuntimeScanResult(value) {
  return String(value || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatRuntimeNextAction(value) {
  if (value === "monitor_open_spread") {
    return "Monitor open spread";
  }
  if (value === "wait_next_session") {
    return "Wait next session";
  }
  if (value === "scan_for_entry") {
    return "Scan for entry";
  }
  if (value === "resolve_runtime_controls") {
    return "Resolve runtime controls";
  }
  if (value === "entry_blocked") {
    return "Entry blocked";
  }
  return formatRuntimeScanResult(value);
}

function formatSignedCurrency(value, currency = "USD") {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${formatCurrency(number, currency)}`;
}

function formatWeight(value, total) {
  const amount = toNumber(value);
  const denominator = toNumber(total);
  if (!Number.isFinite(amount) || !Number.isFinite(denominator) || denominator <= 0) {
    return "--";
  }
  return `${((amount / denominator) * 100).toFixed(1)}%`;
}

function formatPercent(value, base) {
  const numerator = toNumber(value);
  const denominator = toNumber(base);
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return "--";
  }
  const percent = (numerator / denominator) * 100;
  const prefix = percent > 0 ? "+" : "";
  return `${prefix}${percent.toFixed(2)}% of book`;
}

function formatSignedPercentValue(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(2)}%`;
}

function formatPercentValue(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return `${number.toFixed(2)}%`;
}

function formatSignedDecimal(value, decimals = 2) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(decimals)}`;
}

function formatImpliedVolatility(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const percent = Math.abs(number) <= 1 ? number * 100 : number;
  return `${percent.toFixed(1)}%`;
}

function formatPositionQuantity(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.NaN;
}

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = null, signal: providedSignal, ...requestOptions } = options;
  const controller = new AbortController();
  const signal = mergeAbortSignals(controller.signal, providedSignal);
  let timeoutId = null;
  if (timeoutMs !== null && timeoutMs !== undefined) {
    timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  }

  try {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(requestOptions.headers || {}),
      },
      ...requestOptions,
      signal,
    });

    if (!response.ok) {
      let detail = `Request failed: ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) {
          detail = payload.detail;
        }
      } catch {
        // ignore
      }
      throw new Error(detail);
    }

    return response.json();
  } catch (error) {
    if (error?.name === "AbortError" && timeoutMs !== null && timeoutMs !== undefined) {
      throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)}s.`);
    }
    throw error;
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  }
}

function mergeAbortSignals(...signals) {
  const activeSignals = signals.filter(Boolean);
  if (activeSignals.length === 0) {
    return undefined;
  }
  if (activeSignals.length === 1) {
    return activeSignals[0];
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  for (const signal of activeSignals) {
    if (signal.aborted) {
      controller.abort();
      return controller.signal;
    }
    signal.addEventListener("abort", abort, { once: true });
  }
  return controller.signal;
}

function setStatus(message, tone = "") {
  els.statusBanner.textContent = message;
  els.statusBanner.className = "status-banner";
  if (tone) {
    els.statusBanner.classList.add(tone);
  }
}

function formatCurrency(value, currency = "USD") {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(number);
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDateTime(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function buildOverlayStatus(kind, detail = "", reason = "") {
  return { kind, detail, reason };
}

function overlayStatusTone(kind) {
  if (kind === "live") {
    return "success";
  }
  if (kind === "loading" || kind === "timed_out" || kind === "stale" || kind === "partial") {
    return "warning";
  }
  if (kind === "circuit_open" || kind === "error") {
    return "error";
  }
  return "neutral";
}

function overlayStatusLabel(kind) {
  if (kind === "live") {
    return "Live";
  }
  if (kind === "loading") {
    return "Refreshing";
  }
  if (kind === "timed_out") {
    return "Timed Out";
  }
  if (kind === "circuit_open") {
    return "Circuit Open";
  }
  if (kind === "stale") {
    return "Stale";
  }
  if (kind === "partial") {
    return "Partial";
  }
  if (kind === "error") {
    return "Unavailable";
  }
  return "Idle";
}

function overlayLiveDetail(label, refreshedAt) {
  const formatted = formatDateTime(refreshedAt);
  if (formatted === "--") {
    return `${label} refreshed successfully.`;
  }
  return `${label} refreshed ${formatted}.`;
}

function classifyOverlayFailure(error, { label, stale = false, staleAt = null } = {}) {
  const reason = error?.message || `Unable to load ${label}.`;
  const normalized = reason.toLowerCase();
  let failureKind = "error";
  if (normalized.includes("timed out")) {
    failureKind = "timed_out";
  } else if (normalized.includes("skipping attempt")) {
    failureKind = "circuit_open";
  }

  if (stale) {
    return buildOverlayStatus(
      "stale",
      buildStaleOverlayDetail(label, failureKind, staleAt),
      reason
    );
  }

  return buildOverlayStatus(
    failureKind,
    buildOverlayFailureDetail(label, failureKind),
    reason
  );
}

function buildOverlayFailureDetail(label, kind) {
  const namedLabel = capitalizeLabel(label);
  if (kind === "timed_out") {
    return `${namedLabel} refresh timed out before fresh broker data loaded.`;
  }
  if (kind === "circuit_open") {
    return `${namedLabel} refresh is paused while the Longbridge circuit breaker cools down.`;
  }
  return `${namedLabel} refresh failed before fresh broker data loaded.`;
}

function buildStaleOverlayDetail(label, failureKind, staleAt) {
  let failureText = "failed";
  if (failureKind === "timed_out") {
    failureText = "timed out";
  } else if (failureKind === "circuit_open") {
    failureText = "hit the Longbridge circuit breaker";
  }
  const lastSuccess = staleAt ? ` Last success ${formatDateTime(staleAt)}.` : "";
  return `Showing the last successful ${label} while the latest refresh ${failureText}.${lastSuccess}`;
}

function renderOverlayReason(status) {
  if (!status?.reason || status.kind === "idle" || status.kind === "loading" || status.kind === "live") {
    return "";
  }
  return `<p class="overlay-reason">Latest refresh: ${escapeHtml(status.reason)}</p>`;
}

function capitalizeLabel(value) {
  const text = String(value || "");
  if (!text) {
    return "";
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatSyncHeadline(lastSyncedAt, lastAttemptAt) {
  if (lastSyncedAt) {
    return `Last success ${formatDateTime(lastSyncedAt)}`;
  }
  if (lastAttemptAt) {
    return `Last attempt ${formatDateTime(lastAttemptAt)}`;
  }
  return "Waiting for first run";
}

function formatSyncDetail(status, lastSyncedAt, lastAttemptAt, error) {
  if (status === "syncing") {
    return lastAttemptAt ? `Started ${formatDateTime(lastAttemptAt)}` : "Sync request is in progress.";
  }
  if (status === "error") {
    return error || "The latest sync failed.";
  }
  if (lastSyncedAt) {
    return `Updated ${formatDateTime(lastSyncedAt)}`;
  }
  if (lastAttemptAt) {
    return `Attempted ${formatDateTime(lastAttemptAt)}`;
  }
  return "No reconciliation run has completed yet.";
}

function reconciliationTone(status) {
  if (status === "success") {
    return "success";
  }
  if (status === "syncing") {
    return "warning";
  }
  if (status === "error") {
    return "error";
  }
  return "neutral";
}

function reconciliationLabel(status) {
  if (status === "success") {
    return "Success";
  }
  if (status === "syncing") {
    return "Syncing";
  }
  if (status === "error") {
    return "Error";
  }
  return "Idle";
}

function statusClass(status) {
  if (status === "filled") {
    return "success";
  }
  if (status === "canceled" || status === "rejected") {
    return "error";
  }
  if (status === "submitted" || status === "partially_filled") {
    return "warning";
  }
  return "neutral";
}

function strategyStatusClass(status) {
  if (status === "approved" || status === "executed" || status === "reviewed" || status === "suggested" || status === "low") {
    return "success";
  }
  if (status === "pending" || status === "planned" || status === "running" || status === "candidate" || status === "risk_check" || status === "medium") {
    return "warning";
  }
  if (status === "rejected" || status === "expired" || status === "failed" || status === "blocked" || status === "high") {
    return "error";
  }
  return "neutral";
}

function journalEntryTone(entryType) {
  if (entryType === "review") {
    return "warning";
  }
  if (entryType === "plan") {
    return "success";
  }
  return "neutral";
}

function spreadStatusClass(status) {
  if (status === "open" || status === "closed") {
    return "success";
  }
  if (
    status === "entry_pending_long" ||
    status === "entry_pending_short" ||
    status === "exit_pending_short" ||
    status === "exit_pending_long"
  ) {
    return "warning";
  }
  if (status === "entry_failed" || status === "rollback_failed") {
    return "error";
  }
  return "neutral";
}

function formatSpreadStatusLabel(status) {
  return String(status || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatStrategyStatusLabel(status) {
  return String(status || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSpreadExitReason(reason) {
  if (!reason) {
    return "--";
  }
  return String(reason)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSpreadStrike(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function formatSpreadDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function formatSessionDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatSpreadCredit(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  return `$${formatSpreadStrike(value)}`;
}

function formatMultilineText(value) {
  return escapeHtml(value).replaceAll("\n", "<br />");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
