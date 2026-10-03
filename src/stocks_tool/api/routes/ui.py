from pathlib import Path
from textwrap import dedent

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
STATIC_DIR = Path(__file__).resolve().parents[2] / "ui" / "static"


def _asset_url(filename: str) -> str:
    asset_path = STATIC_DIR / filename
    version = asset_path.stat().st_mtime_ns
    return f"/static/{filename}?v={version}"


@router.get("/", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
def render_dashboard() -> HTMLResponse:
    app_css_url = _asset_url("app.css")
    workspace_css_url = _asset_url("workspace.css")
    workbench_redesign_css_url = _asset_url("workbench-redesign.css")
    lifecycle_warning_js_url = _asset_url("lifecycle-warning.js")
    api_client_js_url = _asset_url("api-client.js")
    formatters_js_url = _asset_url("formatters.js")
    i18n_js_url = _asset_url("i18n.js")
    state_js_url = _asset_url("state.js")
    chart_vendor_js_url = _asset_url("vendor/lightweight-charts-5.2.0.standalone.production.js")
    chart_view_js_url = _asset_url("chart-view.js")
    research_view_js_url = _asset_url("research-view.js")
    watchlist_view_js_url = _asset_url("watchlist-view.js")
    account_loader_js_url = _asset_url("account-loader.js")
    bull_put_view_js_url = _asset_url("bull-put-view.js")
    strategy_view_js_url = _asset_url("strategy-view.js")
    advisor_view_js_url = _asset_url("advisor-view.js")
    orders_view_js_url = _asset_url("orders-view.js")
    operations_recovery_js_url = _asset_url("operations-recovery-view.js")
    trading_safety_js_url = _asset_url("trading-safety.js")
    operations_recovery_css_url = _asset_url("operations-recovery-view.css")
    execution_drawer_js_url = _asset_url("execution-drawer.js")
    workspace_shell_js_url = _asset_url("workspace-shell.js")
    workbench_ui_js_url = _asset_url("workbench-ui.js")
    research_case_js_url = _asset_url("research-case-view.js")
    portfolio_workbench_js_url = _asset_url("portfolio-workbench.js")
    market_timeline_js_url = _asset_url("market-timeline-view.js")
    strategy_backtest_js_url = _asset_url("strategy-backtest-view.js")
    strategy_readiness_js_url = _asset_url("strategy-readiness-view.js")
    advisor_audit_js_url = _asset_url("advisor-audit-view.js")
    app_js_url = _asset_url("app.js")
    return HTMLResponse(
        dedent(
            f"""\
            <!doctype html>
            <html lang="zh-CN">
              <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>Stocks Tool Workbench</title>
                <link rel="stylesheet" href="{app_css_url}" />
                    <link rel="stylesheet" href="{workspace_css_url}" />
                    <link rel="stylesheet" href="{operations_recovery_css_url}" />
                    <link rel="stylesheet" href="{workbench_redesign_css_url}" />
              </head>
              <body data-workspace="research" data-sidebar-collapsed="false">
                <div id="app-shell" class="workbench-shell">
                  <aside id="workspace-sidebar" class="workspace-sidebar" aria-label="研究工作区">
                    <div class="sidebar-brand">
                      <div class="brand-mark">ST</div>
                      <div class="sidebar-brand-copy">
                        <span class="eyebrow">Paper Research</span>
                        <strong>Stocks Tool</strong>
                      </div>
                      <button id="sidebar-toggle" class="sidebar-toggle" type="button" aria-label="Collapse sidebar" aria-controls="workspace-nav" aria-expanded="true">
                        <span aria-hidden="true">&#8249;</span>
                      </button>
                    </div>
                    <nav id="workspace-nav" class="workspace-nav" aria-label="工作区列表" role="tablist" aria-orientation="vertical">
                      <button id="research-workspace-tab" type="button" role="tab" data-workspace-option="research" aria-label="研究" aria-controls="research-section" aria-selected="true"><span class="nav-glyph" aria-hidden="true">R</span><span class="sidebar-label" data-label-zh="研究">Research Desk</span></button>
                      <button id="strategy-workspace-tab" type="button" role="tab" data-workspace-option="strategy" aria-label="策略" aria-controls="strategy-section" aria-selected="false"><span class="nav-glyph" aria-hidden="true">S</span><span class="sidebar-label" data-label-zh="策略">Strategy Lab</span></button>
                      <button id="macro-workspace-tab" type="button" role="tab" data-workspace-option="macro" aria-label="市场" aria-controls="macro-section" aria-selected="false"><span class="nav-glyph" aria-hidden="true">M</span><span class="sidebar-label" data-label-zh="市场">Macro &amp; Events</span></button>
                      <button id="portfolio-workspace-tab" type="button" role="tab" data-workspace-option="portfolio" aria-label="持仓" aria-controls="portfolio-section" aria-selected="false"><span class="nav-glyph" aria-hidden="true">P</span><span class="sidebar-label" data-label-zh="持仓">Portfolio</span></button>
                      <button id="operations-workspace-tab" type="button" role="tab" data-workspace-option="operations" aria-label="运行与安全" aria-controls="account-section" aria-selected="false"><span class="nav-glyph" aria-hidden="true">O</span><span class="sidebar-label" data-label-zh="状态">Operations</span></button>
                    </nav>
                    <div class="sidebar-foot"><span class="mode-pill">Paper First</span><span class="sidebar-label">LBPT10087357</span></div>
                  </aside>

                  <div class="workbench-main">
                  <header class="workspace-topbar">
                    <div class="topbar-context" aria-label="账户和市场数据上下文">
                      <label class="topbar-account-picker"><span>Account</span><select id="topbar-account-select" aria-label="Select broker account"><option value="LBPT10087357">LBPT10087357 / USD</option></select></label>
                      <strong id="topbar-account-context" class="topbar-account-context">LBPT10087357</strong>
                      <span id="topbar-mode-context" class="mode-pill">Paper / Simulated</span>
                      <span class="context-item"><span>Data</span><time id="topbar-data-time">Waiting</time></span>
                      <span id="topbar-reason-context" class="topbar-reason" data-tone="warning">Select an account to begin.</span>
                    </div>
                    <div id="status-banner" class="status-banner topbar-status" role="status" aria-live="polite" aria-atomic="true">Ready</div>
                    <div class="topbar-actions">
                      <div class="language-switch" aria-label="语言">
                        <button class="lang-option" type="button" data-lang-option="zh">中文</button>
                        <button class="lang-option" type="button" data-lang-option="en">EN</button>
                      </div>
                      <button id="refresh-dashboard" class="icon-button" type="button" aria-label="Refresh dashboard">Refresh</button>
                      <a class="action-link" href="/docs">API Docs</a>
                      <button id="open-execution-drawer" class="icon-button accent" type="button" aria-haspopup="dialog" aria-controls="execution-drawer" aria-expanded="false">Execution</button>
                    </div>
                  </header>

                  <main class="workspace">
                    <div id="desktop-trading-notice" class="desktop-trading-notice" role="note">
                      Broker-writing actions are disabled on screens 780px wide or smaller. The execution drawer remains available for read-only review.
                    </div>
                    <div id="demo-data-banner" role="note">演示数据：以下内容来自本地模拟数据，不代表当前纸账户或券商实时证据。</div>
                    <section id="research-section" class="band research-band" data-workspace-panel="research" role="tabpanel" aria-labelledby="research-workspace-tab">
                      <div class="band-header research-header">
                        <div>
                          <span class="section-kicker">Shared Symbol Context</span>
                          <h1>Research Desk</h1>
                           <p class="section-summary">先看标的和证据，再看解释与下一步；数据不完整时直接标出。</p>
                        </div>
                        <div class="segmented-control" role="tablist" aria-label="Research view">
                          <button id="research-table-tab" type="button" role="tab" data-research-view="table" aria-selected="true" aria-controls="research-table-view">Screener</button>
                          <button id="research-chart-tab" type="button" role="tab" data-research-view="chart" aria-selected="false" aria-controls="research-chart-view">Chart</button>
                        </div>
                      </div>

                      <div class="research-toolbar" aria-label="Research controls">
                        <label class="field research-search-field"><span>Symbol Search</span><input id="research-search" type="search" autocomplete="off" placeholder="Search symbol" /></label>
                        <label class="field"><span>Watchlist</span><select id="research-watchlist-select"><option value="">Default universe</option></select></label>
                        <button id="manage-watchlist-button" class="icon-button" type="button" aria-haspopup="dialog" aria-controls="watchlist-dialog">Manage Watchlist</button>
                        <label class="field"><span>Source</span><select id="research-source-filter"><option value="">All Sources</option></select></label>
                        <label class="field"><span>Event Window</span><select id="research-event-filter"><option value="">Any Event Window</option><option value="7">Next 7 Days</option><option value="30">Next 30 Days</option><option value="none">No Upcoming Event</option></select></label>
                         <label class="field compact-field"><span>Position</span><select id="research-held-filter"><option value="">All</option><option value="held">Held</option><option value="not-held">Not Held</option></select><small id="research-held-filter-status" class="research-filter-status" hidden></small></label>
                        <label class="field compact-field"><span>Strategy</span><select id="research-strategy-filter"><option value="">All</option><option value="active">Active</option><option value="none">None</option></select></label>
                      </div>

                      <details class="research-filters">
                        <summary>Technical Filters</summary>
                        <div class="research-filter-grid">
                          <label class="field"><span>Min Day Change %</span><input id="research-min-day-change" type="number" step="0.1" /></label>
                          <label class="field"><span>Min 20D Return %</span><input id="research-min-return20" type="number" step="0.1" data-technical-filter /></label>
                          <label class="field"><span>Min 60D Return %</span><input id="research-min-return60" type="number" step="0.1" data-technical-filter /></label>
                          <label class="field"><span>Max 20D Volatility %</span><input id="research-max-volatility" type="number" min="0" step="0.1" data-technical-filter /></label>
                          <label class="field"><span>Min Avg Turnover</span><input id="research-min-turnover" type="number" min="0" step="1000" data-technical-filter /></label>
                          <label class="check-field"><input id="research-trend-close-sma20" type="checkbox" data-technical-filter /><span>Close above SMA20</span></label>
                          <label class="check-field"><input id="research-trend-sma20-sma50" type="checkbox" data-technical-filter /><span>SMA20 above SMA50</span></label>
                          <button id="research-reset-filters" class="icon-button" type="button">Reset Filters</button>
                        </div>
                      </details>

                      <div class="research-table-controls">
                        <div class="segmented-control" role="group" aria-label="Research column group">
                          <button type="button" data-research-columns="overview" aria-pressed="true">Overview</button>
                          <button type="button" data-research-columns="momentum" aria-pressed="false">Momentum</button>
                          <button type="button" data-research-columns="strategy" aria-pressed="false">Strategy</button>
                        </div>
                        <div class="research-load-state"><span id="research-progress" role="status" aria-live="polite">Waiting for universe</span><span id="research-status" role="status" aria-live="polite"></span></div>
                      </div>

                      <div id="research-table-view" class="research-view" role="tabpanel" aria-labelledby="research-table-tab">
                        <div class="table-shell research-table-shell">
                          <table class="data-table research-table">
                            <thead>
                              <tr>
                                <th><button type="button" data-research-sort="symbol">Symbol</button></th>
                                <th data-column-group="overview"><button type="button" data-research-sort="quote.last">Last</button></th>
                                <th data-column-group="overview"><button type="button" data-research-sort="quote.change_pct">Day %</button></th>
                                <th data-column-group="overview">Sources</th>
                                <th data-column-group="overview"><button type="button" data-research-sort="position_market_value">Position</button></th>
                                <th data-column-group="momentum"><button type="button" data-research-sort="return_20d_pct">20D</button></th>
                                <th data-column-group="momentum"><button type="button" data-research-sort="return_60d_pct">60D</button></th>
                                <th data-column-group="momentum"><button type="button" data-research-sort="realized_volatility_20d_pct">Vol 20D</button></th>
                                <th data-column-group="momentum"><button type="button" data-research-sort="average_turnover_20d">Avg Turnover</button></th>
                                <th data-column-group="momentum">Trend</th>
                                <th data-column-group="strategy"><button type="button" data-research-sort="next_event">Next Event</button></th>
                                <th data-column-group="strategy">Strategy State</th>
                                <th class="research-action-cell">Action</th>
                              </tr>
                            </thead>
                            <tbody id="research-table-body"><tr><td colspan="13" class="empty-row">Loading research universe...</td></tr></tbody>
                          </table>
                        </div>
                      </div>

                      <div id="research-chart-view" class="research-view research-chart-view" role="tabpanel" aria-labelledby="research-chart-tab" hidden>
                        <aside class="research-symbol-rail" aria-label="Research symbols"><div id="research-symbol-list" role="listbox"></div></aside>
                        <section class="research-chart-workspace">
                          <div class="chart-toolbar">
                            <div class="segmented-control" role="group" aria-label="Chart range"><button type="button" data-chart-range="3m" aria-pressed="false">3M</button><button type="button" data-chart-range="6m" aria-pressed="true">6M</button><button type="button" data-chart-range="1y" aria-pressed="false">1Y</button></div>
                            <button id="research-prepare-order" class="icon-button accent" type="button">Prepare Order</button>
                          </div>
                          <div id="research-chart-container" class="research-chart" aria-label="Daily candlestick chart"></div>
                          <div id="research-chart-summary" class="chart-summary" role="status" aria-live="polite">Select a symbol to load history.</div>
                          <div class="research-evidence-grid">
                            <article><span class="section-kicker">Events</span><div id="research-selected-events">No event selected.</div></article>
                            <article><span class="section-kicker">Strategy Evidence</span><div id="research-selected-strategies">No strategy selected.</div></article>
                            <article><span class="section-kicker">Watchlist Notes</span><div id="research-selected-notes">No notes.</div></article>
                          </div>
                        </section>
                      </div>
                      <aside id="research-explanation-panel" class="workbench-explanation research-explanation-panel" aria-live="polite">
                        <div class="workbench-explanation-header">
                          <div><span class="section-kicker">证据解释</span><h2 id="research-explanation-title">请选择一个标的</h2></div>
                          <span id="research-explanation-status" class="workbench-status-chip" data-tone="warning">等待选择</span>
                        </div>
                        <div class="workbench-explanation-body">
                          <p id="research-explanation-summary" class="workbench-explanation-summary">研究表和图表共享同一标的。选择一行后，这里会解释数据、证据缺口和下一步。</p>
                          <dl id="research-explanation-facts" class="workbench-facts"></dl>
                          <ul id="research-explanation-reasons" class="workbench-explanation-list"><li>没有标的就没有策略判断。</li></ul>
                        </div>
                        <details class="research-case-controls workbench-raw-details">
                          <summary>保存、加载与比较</summary>
                        <div class="workbench-inline-form">
                          <label class="field"><span>筛选名称</span><input id="research-screen-name" type="text" maxlength="80" placeholder="例如：趋势观察" /></label>
                          <label class="field"><span>档案标题</span><input id="research-case-title-input" type="text" maxlength="120" placeholder="例如：QQQ 研究档案" /></label>
                          <label class="field field-wide"><span>研究假设</span><input id="research-case-thesis-input" type="text" maxlength="240" placeholder="写下你要验证的事实" /></label>
                          <label class="field"><span>已保存筛选</span><select id="research-screen-select"><option value="">暂无已保存筛选</option></select></label>
                          <label class="field"><span>已保存档案</span><select id="research-case-select"><option value="">暂无已保存档案</option></select></label>
                          <label class="field field-wide"><span>候选对比</span><input id="research-compare-symbols" type="text" maxlength="200" placeholder="QQQ.US, SMH.US" /></label>
                        </div>
                        <div class="workbench-task-row">
                          <button id="research-save-screen" class="table-action" type="button" data-research-case-action="screen">保存筛选</button>
                          <button id="research-save-case" class="table-action" type="button" data-research-case-action="case">保存研究档案</button>
                          <button id="research-load-screen" class="table-action" type="button">加载筛选</button>
                          <button id="research-load-case" class="table-action" type="button">加载档案</button>
                          <button id="research-load-more-screens" class="table-action" type="button" hidden>加载更多筛选</button>
                          <button id="research-load-more-cases" class="table-action" type="button" hidden>加载更多档案</button>
                          <button id="research-compare-button" class="table-action" type="button">比较候选</button>
                          <button id="research-evaluate-strategy" class="table-action primary" type="button" data-research-case-action="evaluate">打开策略评估</button>
                        </div>
                        <div id="research-compare-result" class="workbench-research-case-status" role="status" aria-live="polite"></div>
                        <p id="research-case-status" class="workbench-research-case-status" role="status" aria-live="polite"></p>
                        </details>
                      </aside>
                      <section id="research-immutable-case-panel" class="workbench-card" hidden aria-live="polite">
                        <header class="workbench-card-header"><div><span class="section-kicker">历史证据</span><h2>已保存研究档案</h2><p>这是保存时的不可变快照，不会随当前行情刷新。</p></div><button id="research-close-case" class="table-action" type="button">返回实时研究</button></header>
                        <div class="workbench-explanation-body"><p id="research-immutable-case-summary" class="workbench-explanation-summary"></p><div id="research-immutable-case-chart" class="workbench-chart"><div class="workbench-chart-empty">选择档案后查看保存时历史图表。</div></div><dl id="research-immutable-case-facts" class="workbench-facts"></dl><ul id="research-immutable-case-warnings" class="workbench-explanation-list"></ul></div>
                      </section>
                    </section>

                    <section id="account-section" class="band account-band" data-workspace-panel="operations" role="tabpanel" aria-labelledby="operations-workspace-tab" hidden>
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Account</span>
                          <h2>Account Control</h2>
                        </div>
                      </div>

                      <div class="controls-grid">
                        <label class="field field-wide">
                          <span>Broker Account</span>
                          <select id="account-select"></select>
                        </label>
                        <button id="sync-account" class="icon-button accent" type="button">
                          <span class="icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" focusable="false">
                              <path d="M3 12a9 9 0 0 1 15.55-6.36"/>
                              <path d="M21 12a9 9 0 0 1-15.55 6.36"/>
                              <path d="M18 2v6h-6"/>
                              <path d="M6 22v-6h6"/>
                            </svg>
                          </span>
                          <span>Sync Account</span>
                        </button>
                        <button id="sync-orders" class="icon-button" type="button">
                          <span class="icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" focusable="false">
                              <path d="M8 6h13"/>
                              <path d="M8 12h13"/>
                              <path d="M8 18h13"/>
                              <path d="M3 6h.01"/>
                              <path d="M3 12h.01"/>
                              <path d="M3 18h.01"/>
                            </svg>
                          </span>
                          <span>Sync Orders</span>
                        </button>
                      </div>

                      <div id="metrics-strip" class="metric-strip account-metrics">
                        <article class="metric-tile">
                          <span class="metric-label">Cash Balance</span>
                          <strong class="metric-value">--</strong>
                        </article>
                        <article class="metric-tile">
                          <span class="metric-label">Net Liquidation</span>
                          <strong class="metric-value">--</strong>
                        </article>
                        <article class="metric-tile">
                          <span class="metric-label">Buying Power</span>
                          <strong class="metric-value">--</strong>
                        </article>
                        <article class="metric-tile">
                          <span class="metric-label">Latest Snapshot</span>
                          <strong class="metric-value">--</strong>
                        </article>
                      </div>

                      <div id="reconciliation-strip" class="reconciliation-strip">
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
                      </div>

                      <section class="panel operations-recovery-panel-shell" aria-labelledby="operations-recovery-title">
                        <div id="operations-recovery-panel" data-operations-recovery aria-live="polite"></div>
                      </section>

                    </section>

                    <section id="strategy-section" class="band strategy-band" data-workspace-panel="strategy" role="tabpanel" aria-labelledby="strategy-workspace-tab" hidden>
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Strategy</span>
                          <h2>Strategy Center</h2>
                        </div>
                        <div class="segmented-control strategy-tabs" role="tablist" aria-label="Strategy category">
                          <button type="button" role="tab" data-strategy-tab="bull-put" aria-selected="true">Bull Put</button>
                          <button type="button" role="tab" data-strategy-tab="covered-call" aria-selected="false">Covered Call</button>
                          <button type="button" role="tab" data-strategy-tab="zero-dte" aria-selected="false">Zero-DTE</button>
                          <button type="button" role="tab" data-strategy-tab="experiments" aria-selected="false">Experiments / Advisor</button>
                        </div>
                      </div>

                      <section class="strategy-workbench-grid workbench-hero" aria-label="策略风险与解释">
                        <article class="workbench-card">
                          <header class="workbench-card-header">
                            <div><span class="section-kicker">风险预算</span><h2>策略占用与余量</h2><p>只读汇总当前持仓、策略和未解决意图；不授权订单。</p></div>
                            <span id="strategy-risk-status" class="workbench-status-chip" data-tone="warning">等待数据</span>
                          </header>
                          <div id="strategy-risk-bars" class="workbench-bar-list"><div class="workbench-blocked"><div><strong>暂未计算</strong><br />选择账户后加载策略风险预算。</div></div></div>
                        </article>
                        <aside id="strategy-explanation-panel" class="workbench-explanation">
                          <div class="workbench-explanation-header"><div><span class="section-kicker">策略解释</span><h2 id="strategy-explanation-title">等待策略评估</h2></div><span id="strategy-explanation-status" class="workbench-status-chip" data-tone="warning">等待数据</span></div>
                          <div class="workbench-explanation-body"><p id="strategy-explanation-summary" class="workbench-explanation-summary">这里会说明当前为什么可以继续、为什么被阻塞，以及使用了哪些数据。</p><dl id="strategy-explanation-facts" class="workbench-facts"></dl><ul id="strategy-explanation-reasons" class="workbench-explanation-list"><li>风险预算和回测都不会自动提交订单。</li></ul></div>
                          <div class="workbench-task-row"><label class="field"><span>评估标的</span><input id="strategy-evaluation-symbol" type="text" maxlength="32" placeholder="QQQ.US" /></label><button id="strategy-readiness-button" class="table-action" type="button">运行只读评估</button><button id="strategy-canary-button" class="table-action" type="button" disabled>申请纸账户 Canary</button></div>
                          <p id="strategy-evaluation-status" class="workbench-backtest-status" role="status" aria-live="polite"></p>
                        </aside>
                      </section>
                      <section id="strategy-backtest-panel" class="workbench-card" aria-label="历史回测">
                        <header class="workbench-card-header"><div><span class="section-kicker">历史回测</span><h2>完整可用历史</h2><p>使用本地可用数据；覆盖不足时明确显示，不用估算值填补。</p></div><span id="backtest-status" class="workbench-status-chip" data-tone="warning">等待运行</span></header>
                        <div class="workbench-inline-form"><label class="field"><span>策略 / Strategy</span><select id="backtest-strategy"><option value="bull_put">牛市看跌 / Bull Put</option><option value="covered_call">备兑看涨 / Covered Call</option><option value="zero_dte">零日期权（仅预览） / Zero-DTE</option></select></label><label class="field"><span>数据集</span><select id="backtest-dataset"><option value="">正在读取已注册数据集…</option></select></label><label class="field"><span>标的</span><input id="backtest-symbols" type="text" value="QQQ" placeholder="QQQ,SPY" /></label><label class="field"><span>开始日期</span><input id="backtest-start-date" type="date" value="2020-01-01" /></label><label class="field"><span>结束日期</span><input id="backtest-end-date" type="date" value="2026-09-30" /></label><label class="field"><span>数据分段</span><select id="backtest-period-segment"><option value="composite">组合区间（跨样本外需冻结）</option><option value="development">开发</option><option value="validation">验证</option><option value="holdout">留出（需冻结）</option></select></label><label class="field"><span>验证冻结来源</span><select id="backtest-freeze-source-run-id"><option value="">无（仅适用于不含样本外的区间）</option></select></label><label class="field"><span>初始资金</span><input id="backtest-initial-cash" type="number" min="1" step="1000" value="100000" /></label><label class="field"><span>每合约费用</span><input id="backtest-fee-per-contract" type="number" min="0" step="0.01" value="0" /></label><label class="field"><span>滑点（基点）</span><input id="backtest-slippage-bps" type="number" min="0" step="0.1" value="0" /></label><label class="field backtest-covered-call-field"><span>初始股票批次</span><input id="backtest-initial-stock-symbol" type="text" placeholder="Covered Call 标的" /></label><label class="field backtest-covered-call-field"><span>初始股数</span><input id="backtest-initial-stock-quantity" type="number" min="0" step="1" placeholder="例如 100" /></label><label class="field backtest-covered-call-field"><span>取得价格</span><input id="backtest-initial-stock-price" type="number" min="0" step="0.01" placeholder="每股成本" /></label><label class="field backtest-covered-call-field"><span>取得费用</span><input id="backtest-initial-stock-fee" type="number" min="0" step="0.01" value="0" placeholder="默认 0，仅在明确确认时使用" /></label><button id="backtest-run-button" class="table-action primary" type="button">创建历史回测</button><button id="backtest-start-button" class="table-action" type="button" disabled>开始运行选中任务</button><button id="backtest-cancel-button" class="table-action" type="button" disabled>取消选中任务</button><button id="backtest-compare-button" class="table-action" type="button" disabled>比较两次运行</button></div>
                        <p class="workbench-backtest-status">日期、标的、费用和滑点都会写入回测清单；系统不会自动缩短日期范围。</p>
                        <div class="table-shell"><table class="workbench-data-table"><thead><tr><th>运行</th><th>策略</th><th>数据集</th><th>状态</th><th>时间</th><th>结果</th></tr></thead><tbody id="backtest-runs-body"><tr><td colspan="6" class="empty-row">没有历史回测记录。先选择数据集并显式运行。</td></tr></tbody></table></div>
                        <aside id="backtest-explanation-panel" class="workbench-explanation" style="margin: 0 18px 18px;"><div class="workbench-explanation-header"><div><span class="section-kicker">回测解释</span><h3>结果边界与表现</h3></div><span id="backtest-explanation-status" class="workbench-status-chip" data-tone="warning">等待选择</span></div><div class="workbench-explanation-body"><p id="backtest-explanation-summary" class="workbench-explanation-summary">回测结果只使用明确选择的数据集和参数。</p><div id="backtest-result-chart" class="workbench-chart"><div class="workbench-chart-empty">选择一条回测运行后查看净值曲线。</div></div><dl id="backtest-explanation-facts" class="workbench-facts"></dl></div></aside>
                      </section>

                      <div class="strategy-layout">
                        <section class="panel panel-span-2" data-strategy-category="bull-put">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Bull Put</span>
                              <h2>Bull Put Strategy</h2>
                            </div>
                          </div>
                          <div id="strategy-runtime-strip" class="mini-metric-strip strategy-summary-strip">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Entry Status</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No runtime state loaded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Daily Entries</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">Waiting for first scan.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Daily Realized PnL</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No spread closes recorded today.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Next Action</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">Waiting for first bull put scan.</span>
                            </article>
                          </div>

                          <form id="strategy-controls-form" class="ticket-form">
                            <div class="ticket-grid">
                              <label class="field">
                                <span>Auto Entry</span>
                                <select id="strategy-auto-entry">
                                  <option value="true">Enabled</option>
                                  <option value="false">Disabled</option>
                                </select>
                              </label>
                              <label class="field">
                                <span>Manual Pause</span>
                                <select id="strategy-manual-pause">
                                  <option value="false">Running</option>
                                  <option value="true">Paused</option>
                                </select>
                              </label>
                              <label class="field">
                                <span>Kill Switch</span>
                                <select id="strategy-kill-switch">
                                  <option value="false">Off</option>
                                  <option value="true">On</option>
                                </select>
                              </label>
                              <label class="field field-span-2">
                                <span>Paused Symbols</span>
                                <input id="strategy-paused-symbols" type="text" maxlength="160" placeholder="QQQ.US, SMH.US" />
                              </label>
                            </div>
                            <div class="form-foot">
                              <p id="strategy-controls-hint" class="form-hint" role="status" aria-live="polite">Strategy controls apply to new bull put entries only. Existing spreads remain monitored.</p>
                              <div class="inline-actions">
                                <button id="save-strategy-controls" class="icon-button" type="submit" data-broker-mutation="true" data-action-key="bull-put-controls">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M5 5h11l3 3v11H5z"/>
                                      <path d="M8 5v6h8"/>
                                      <path d="M8 19v-6h8v6"/>
                                    </svg>
                                  </span>
                                  <span>Save Controls</span>
                                </button>
                                <button id="run-strategy-scan" class="icon-button accent" type="button" data-broker-mutation="true" data-action-key="bull-put-force-scan">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M3 12h18"/>
                                      <path d="m13 6 6 6-6 6"/>
                                    </svg>
                                  </span>
                                  <span>Execute Preview</span>
                                </button>
                                <button id="run-strategy-review" class="icon-button" type="button">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M4 5h16v14H4z"/>
                                      <path d="M8 9h8"/>
                                      <path d="M8 13h6"/>
                                      <path d="M8 17h5"/>
                                    </svg>
                                  </span>
                                  <span>Run Review</span>
                                </button>
                              </div>
                            </div>
                          </form>

                          <div class="strategy-notes-grid">
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Last Skip</span>
                                <h3>Latest Skip Reason</h3>
                              </div>
                              <div id="strategy-skip-card" class="strategy-note-body empty">
                                No bull put scan has been skipped yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Review</span>
                                <h3>Latest Review</h3>
                              </div>
                              <div id="strategy-review-card" class="strategy-note-body empty">
                                No bull put strategy review has been generated yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Journal</span>
                                <h3>Recent Strategy Notes</h3>
                              </div>
                              <div id="strategy-journal-feed" class="strategy-note-body empty">
                                No bull put strategy notes for this account yet.
                              </div>
                            </article>
                          </div>
                        </section>

                        <section class="panel panel-span-2" data-strategy-category="zero-dte" hidden>
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Zero-DTE</span>
                              <h2>Lottery Strategy</h2>
                            </div>
                          </div>
                          <div id="zero-dte-lottery-strip" class="mini-metric-strip strategy-summary-strip">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Execution</span>
                              <strong class="mini-metric-value">Preview Only</strong>
                              <span class="mini-metric-detail">Zero-DTE ordering is disabled.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Max Premium</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">$150 default cap.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Scan Window</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">Read-only candidate evaluation.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Daily Cap</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">One lottery order per session.</span>
                            </article>
                          </div>

                          <form id="zero-dte-lottery-controls-form" class="ticket-form">
                            <div class="ticket-grid">
                              <label class="field">
                                <span>Execution</span>
                                <select id="zero-dte-lottery-auto-order" disabled aria-disabled="true">
                                  <option value="false">Preview Only</option>
                                </select>
                              </label>
                              <label class="field">
                                <span>Symbol</span>
                                <input id="zero-dte-lottery-symbol" type="text" maxlength="32" value="QQQ.US" />
                              </label>
                              <label class="field">
                                <span>Direction</span>
                                <select id="zero-dte-lottery-direction">
                                  <option value="auto">Auto</option>
                                  <option value="call">Call</option>
                                  <option value="put">Put</option>
                                </select>
                              </label>
                            </div>
                            <div class="form-foot">
                              <p id="zero-dte-lottery-hint" class="form-hint">Preview only. Zero-DTE execution and automatic ordering stay disabled until the expiry lifecycle is implemented.</p>
                              <div class="inline-actions">
                                <button id="preview-zero-dte-lottery" class="icon-button" type="button">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M4 5h16v14H4z"/>
                                      <path d="M8 9h8"/>
                                      <path d="M8 13h6"/>
                                      <path d="M8 17h5"/>
                                    </svg>
                                  </span>
                                  <span>Preview Lottery</span>
                                </button>
                              </div>
                            </div>
                          </form>

                          <div class="strategy-notes-grid experiment-grid">
                            <article class="strategy-note-card lottery-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Candidate</span>
                                <h3>Lottery Preview / Scan</h3>
                              </div>
                              <div id="zero-dte-lottery-result-card" class="strategy-note-body empty">
                                No zero-DTE lottery preview loaded yet.
                              </div>
                            </article>
                          </div>
                        </section>

                        <section class="panel panel-span-2" data-workspace-relocate="macro">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Risk Calendar</span>
                              <h2>Market Event Calendar</h2>
                            </div>
                          </div>
                          <div class="strategy-notes-grid experiment-grid">
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Events</span>
                                <h3>Upcoming Events</h3>
                              </div>
                              <div id="market-events-card" class="strategy-note-body empty">
                                No market events loaded yet.
                              </div>
                            </article>
                          </div>
                        </section>

                        <section class="panel panel-span-2" data-strategy-category="covered-call experiments" hidden>
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Experiment</span>
                              <h2>Strategy Experiment Bench</h2>
                            </div>
                          </div>
                          <div id="strategy-experiment-strip" class="mini-metric-strip strategy-summary-strip" data-strategy-subcategory="experiments">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Active Proposals</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No strategy proposals loaded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Latest Run</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No strategy runs recorded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Signals</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No strategy signals recorded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Reviews</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No strategy reviews recorded.</span>
                            </article>
                          </div>
                          <div class="strategy-notes-grid experiment-grid">
                            <article class="strategy-note-card" data-strategy-subcategory="covered-call">
                              <div class="form-header">
                                <span class="section-kicker">Covered Calls</span>
                                <h3>Activity History</h3>
                              </div>
                              <p id="covered-call-action-status" class="form-hint local-action-status" role="status" aria-live="polite"></p>
                              <div id="covered-call-activity-card" class="strategy-note-body empty">
                                No covered-call activity yet.
                              </div>
                            </article>
                            <article class="strategy-note-card" data-strategy-subcategory="experiments">
                              <div class="form-header">
                                <span class="section-kicker">Proposals</span>
                                <h3>Strategy Proposals</h3>
                              </div>
                              <div id="strategy-proposals-card" class="strategy-note-body empty">
                                No strategy experiment proposals yet.
                              </div>
                            </article>
                            <article class="strategy-note-card" data-strategy-subcategory="experiments">
                              <div class="form-header">
                                <span class="section-kicker">Runs</span>
                                <h3>Strategy Runs</h3>
                              </div>
                              <div id="strategy-runs-card" class="strategy-note-body empty">
                                No strategy runs recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card" data-strategy-subcategory="experiments">
                              <div class="form-header">
                                <span class="section-kicker">Signals</span>
                                <h3>Signal Feed</h3>
                              </div>
                              <div id="strategy-signals-card" class="strategy-note-body empty">
                                No strategy signals recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card" data-strategy-subcategory="experiments">
                              <div class="form-header">
                                <span class="section-kicker">Reviews</span>
                                <h3>Review Feed</h3>
                              </div>
                              <div id="strategy-reviews-card" class="strategy-note-body empty">
                                No strategy reviews recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card advisor-note-card" data-strategy-subcategory="experiments">
                              <div class="form-header">
                                <span class="section-kicker">Advisor</span>
                                <h3>DeepSeek Dry Run</h3>
                              </div>
                              <div class="inline-actions">
                                <button id="load-advisor-context" class="table-action" type="button">Load Context</button>
                                <button id="run-deepseek-advisor" class="table-action primary" type="button">Run DeepSeek</button>
                                <button id="record-advisor-response" class="table-action" type="button" disabled>Record Output</button>
                              </div>
                              <div id="advisor-output-card" class="strategy-note-body empty">
                                Advisor context is available on demand. DeepSeek dry-run sends the selected account context outside the local app.
                              </div>
                              <section id="advisor-audit-panel" class="workbench-card" aria-label="Advisor 审计" style="margin-top: 14px;">
                                <header class="workbench-card-header"><div><span class="section-kicker">审计证据</span><h3>Advisor 运行复核</h3><p>读取本地审计记录，不会再次调用模型。</p></div><button id="advisor-audit-load" class="table-action" type="button">查看审计</button></header>
                                <p id="advisor-audit-status" class="workbench-advisor-status" role="status" aria-live="polite"></p>
                                <div class="advisor-audit-layout"><div id="advisor-audit-list" class="advisor-audit-list"><div class="workbench-blocked"><div><strong>等待读取</strong><br />点击“查看审计”加载本地记录。</div></div></div><div id="advisor-audit-detail" class="advisor-audit-detail"></div></div>
                              </section>
                            </article>
                          </div>
                        </section>

                        <section class="panel panel-span-2" data-strategy-category="bull-put">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Spreads</span>
                              <h2>Bull Put Monitor</h2>
                            </div>
                          </div>
                          <div id="spread-summary-strip" class="mini-metric-strip strategy-summary-strip">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Active Spreads</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No spread data loaded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Monitor Mark</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No spread data loaded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">P/L</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No monitor snapshot.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Last Monitor</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No open or exit-pending spreads are being monitored.</span>
                            </article>
                          </div>
                          <div class="table-shell">
                            <table class="data-table">
                              <thead>
                                <tr>
                                  <th>Underlying</th>
                                  <th>Expiry</th>
                                  <th>Status</th>
                                  <th>Entry / Risk</th>
                                  <th>Monitor Mark</th>
                                  <th>PnL / Exit Distance</th>
                                  <th>Last Monitor</th>
                                  <th>Actions</th>
                                </tr>
                              </thead>
                              <tbody id="spreads-body">
                                <tr><td colspan="8" class="empty-row">No bull put spreads loaded.</td></tr>
                              </tbody>
                            </table>
                          </div>
                        </section>

                        <section class="panel panel-span-2 bull-put-history-panel" data-strategy-category="bull-put">
                          <details id="bull-put-history-panel">
                            <summary class="panel-header bull-put-history-summary">
                              <div>
                                <span class="section-kicker">History</span>
                                <h2>Bull Put History</h2>
                              </div>
                              <span id="bull-put-history-status" class="form-hint" role="status" aria-live="polite">Expand to load completed Bull Put spreads.</span>
                            </summary>
                            <div class="table-shell">
                              <table class="data-table bull-put-history-table">
                                <thead>
                                  <tr><th>Underlying</th><th>Expiry</th><th>Status</th><th>Updated</th><th>Details</th></tr>
                                </thead>
                                <tbody id="bull-put-history-body">
                                  <tr><td colspan="5" class="empty-row">Expand to load Bull Put history.</td></tr>
                                </tbody>
                              </table>
                            </div>
                            <div class="table-footer"><button id="bull-put-history-load-more" class="table-action" type="button" hidden>Load more history</button></div>
                          </details>
                        </section>

                        <section class="panel panel-span-2" data-workspace-relocate="macro">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Live Macro</span>
                              <h2>Real-time Macro Board</h2>
                            </div>
                            <div class="panel-actions">
                              <button id="load-preopen-board" class="icon-button" type="button">
                                <span class="icon" aria-hidden="true">
                                  <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                                    <path d="M21 3v6h-6"/>
                                  </svg>
                                </span>
                                <span>Load Live Macro</span>
                              </button>
                              <button id="load-preopen-overlays" class="icon-button" type="button">
                                <span class="icon" aria-hidden="true">
                                  <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M4 7h16"/>
                                    <path d="M7 12h10"/>
                                    <path d="M10 17h4"/>
                                  </svg>
                                </span>
                                <span>Load Option Overlays</span>
                              </button>
                              <button id="save-preopen-board" class="icon-button" type="button" disabled>
                                <span class="icon" aria-hidden="true">
                                  <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                                    <path d="M17 21v-8H7v8"/>
                                    <path d="M7 3v5h8"/>
                                  </svg>
                                </span>
                                <span>Save Current Board</span>
                              </button>
                            </div>
                          </div>
                          <div id="preopen-summary-strip" class="mini-metric-strip">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Downside Score</span>
                              <strong class="mini-metric-value">--</strong>
                            </article>
                          </div>
                          <div class="preopen-grid">
                            <div id="preopen-assessment-card" class="strategy-note-body empty">
                              Loading pre-open assessment...
                            </div>
                            <div class="preopen-stack">
                              <section>
                                <div class="compact-header">
                                  <span class="section-kicker">Signals</span>
                                  <h3>Risk Proxies</h3>
                                </div>
                                <div id="preopen-signals" class="holdings-focus">
                                  <div class="holding-empty">Waiting for market proxy signals.</div>
                                </div>
                              </section>
                              <section>
                                <div class="compact-header">
                                  <span class="section-kicker">Options</span>
                                  <h3>QQQ / SPY Put Check</h3>
                                </div>
                                <div id="preopen-puts" class="holdings-focus">
                                  <div class="holding-empty">Waiting for directional put snapshots.</div>
                                </div>
                              </section>
                            </div>
                          </div>
                          <div class="preopen-grid secondary">
                            <section>
                              <div class="compact-header">
                                <span class="section-kicker">Surface</span>
                                <h3>Option Chain Analysis</h3>
                              </div>
                              <div id="preopen-chain-analysis" class="holdings-focus">
                                <div class="holding-empty">Waiting for front and next-expiry option chain analysis.</div>
                              </div>
                            </section>
                              <section>
                                <div class="compact-header">
                                  <span class="section-kicker">Stored Review</span>
                                  <h3>Stored Opening Follow-through</h3>
                                </div>
                              <div id="preopen-run-review" class="strategy-note-body empty">
                                Select a broker account to load the latest pre-open capture and opening review.
                              </div>
                            </section>
                          </div>
                        </section>
                      </div>
                    </section>

                    <section id="macro-section" class="band macro-band" data-workspace-panel="macro" role="tabpanel" aria-labelledby="macro-workspace-tab" hidden>
                      <div class="band-header">
                        <div><span class="section-kicker">On Demand</span><h2>Macro &amp; Event Board</h2></div>
                        <p class="section-summary">Market events and option overlays load only when requested.</p>
                      </div>
                      <section class="market-workbench-grid workbench-hero" aria-label="市场事件时间线">
                        <article class="workbench-card"><header class="workbench-card-header"><div><span class="section-kicker">事件时间线</span><h2>市场催化剂</h2><p>按时间查看已保存的事件和来源。</p></div><button id="market-timeline-refresh" class="table-action" type="button">刷新时间线</button></header><div id="market-event-timeline" class="workbench-timeline"><div class="workbench-blocked"><div><strong>暂未加载</strong><br />选择账户后读取事件时间线。</div></div></div></article>
                        <aside id="market-explanation-panel" class="workbench-explanation"><div class="workbench-explanation-header"><div><span class="section-kicker">市场解释</span><h2>为什么现在值得看</h2></div><span id="market-explanation-status" class="workbench-status-chip" data-tone="warning">等待数据</span></div><div class="workbench-explanation-body"><p id="market-explanation-summary" class="workbench-explanation-summary">事件是背景证据，不会自动变成交易建议。</p><dl id="market-explanation-facts" class="workbench-facts"></dl></div><div class="workbench-task-row"><button id="market-load-preopen-board" class="table-action primary" type="button">加载实时市场板</button><button id="market-load-preopen-overlays" class="table-action" type="button">加载期权叠加层</button><button id="market-save-preopen-board" class="table-action" type="button" disabled>保存当前板面</button></div></aside>
                      </section>
                      <div id="macro-workspace-grid" class="strategy-layout"></div>
                    </section>

                    <section id="portfolio-section" class="band portfolio-band" data-workspace-panel="portfolio" role="tabpanel" aria-labelledby="portfolio-workspace-tab" hidden>
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Portfolio</span>
                          <h2>Holdings Overview</h2>
                        </div>
                      </div>
                      <section class="portfolio-workbench-grid workbench-hero" aria-label="持仓表现与解释">
                        <article class="workbench-card">
                          <header class="workbench-card-header"><div><span class="section-kicker">历史表现</span><h2>净清算值曲线</h2><p>按保存的账户快照绘制，日期缺口会直接标出。</p></div><span class="workbench-data-badge" data-quality="unknown">等待数据</span></header>
                          <div id="portfolio-equity-chart" class="workbench-chart"><div class="workbench-chart-empty">选择账户后加载历史净值。</div></div>
                        </article>
                        <aside id="portfolio-explanation-panel" class="workbench-explanation">
                          <div class="workbench-explanation-header"><div><span class="section-kicker">持仓解释</span><h2>当前组合发生了什么</h2></div><span id="portfolio-explanation-status" class="workbench-status-chip" data-tone="warning">等待数据</span></div>
                          <div class="workbench-explanation-body"><p id="portfolio-explanation-summary" class="workbench-explanation-summary">这里会解释净值、盈亏、回撤和数据时间，不会用估算值填补缺口。</p><dl id="portfolio-explanation-facts" class="workbench-facts"></dl></div>
                          <div class="workbench-task-row"><button class="table-action" type="button" id="portfolio-refresh-analytics">刷新组合分析</button><button class="table-action" type="button" id="portfolio-open-research">打开持仓研究</button></div>
                        </aside>
                      </section>
                      <section class="portfolio-workbench-grid workbench-two-column" aria-label="持仓风险">
                        <article class="workbench-card"><header class="workbench-card-header"><div><span class="section-kicker">持仓分布</span><h2>当前持仓与权重</h2></div></header><div class="table-shell"><table class="workbench-data-table"><thead><tr><th>标的</th><th>类型</th><th>数量</th><th>市值</th><th>权重</th></tr></thead><tbody id="portfolio-analytics-body"><tr><td colspan="5" class="empty-row">暂无持仓证据。</td></tr></tbody></table></div></article>
                        <article class="workbench-card"><header class="workbench-card-header"><div><span class="section-kicker">组合风险</span><h2>集中度与策略暴露</h2><p>缺少明确分母时显示无法计算；策略暴露单独列出。</p></div></header><div id="portfolio-risk-bars" class="workbench-bar-list"><div class="workbench-blocked"><div><strong>缺少风险数据</strong><br />选择账户后读取。</div></div></div><div class="workbench-explanation-body"><h3>策略暴露</h3><div id="portfolio-strategy-exposures" class="workbench-bar-list"></div></div><div id="portfolio-linked-review" class="workbench-explanation-body"><p class="workbench-explanation-summary">关联策略、订单和日志会显示在这里。</p><ul id="portfolio-linked-review-list" class="workbench-explanation-list"></ul></div></article>
                      </section>
                       <details id="portfolio-raw-snapshot" class="workbench-raw-details">
                        <summary>查看原始持仓快照</summary>
                       <div id="positions-summary-strip" class="mini-metric-strip">
                        <article class="mini-metric-tile">
                          <span class="metric-label">Open Positions</span>
                          <strong class="mini-metric-value">--</strong>
                        </article>
                        <article class="mini-metric-tile">
                          <span class="metric-label">Gross Market Value</span>
                          <strong class="mini-metric-value">--</strong>
                        </article>
                        <article class="mini-metric-tile">
                          <span class="metric-label">Unrealized PnL</span>
                          <strong class="mini-metric-value">--</strong>
                        </article>
                        <article class="mini-metric-tile">
                          <span class="metric-label">Largest Holding</span>
                          <strong class="mini-metric-value">--</strong>
                        </article>
                      </div>
                       <div class="table-shell">
                        <table class="data-table">
                          <thead>
                            <tr>
                              <th>Symbol</th>
                              <th>Type</th>
                              <th>Qty</th>
                              <th>Avg Cost</th>
                              <th>Market Value</th>
                              <th>Unrealized PnL</th>
                              <th>Weight</th>
                            </tr>
                          </thead>
                          <tbody id="positions-body">
                            <tr><td colspan="7" class="empty-row">No positions in latest snapshot.</td></tr>
                          </tbody>
                        </table>
                       </div>
                       </details>
                    </section>

                  </main>

                  <dialog id="execution-drawer" class="execution-drawer" aria-labelledby="execution-drawer-title">
                    <div class="execution-drawer-shell">
                      <header class="execution-drawer-header">
                        <div><span class="section-kicker">Paper First</span><h2 id="execution-drawer-title">Execution Desk</h2></div>
                        <button id="close-execution-drawer" class="icon-button" type="button" aria-label="Close execution drawer">Close</button>
                      </header>
                      <div class="execution-mobile-readonly" role="note">Read-only on screens 780px wide or smaller. Broker-writing controls remain locked.</div>
                      <div class="segmented-control execution-tabs" role="tablist" aria-label="Execution views">
                        <button type="button" data-execution-tab="ticket" aria-selected="true">Ticket</button>
                        <button type="button" data-execution-tab="orders" aria-selected="false">Orders</button>
                        <button type="button" data-execution-tab="detail" aria-selected="false">Order Detail</button>
                        <button type="button" data-execution-tab="journal" aria-selected="false">Journal</button>
                      </div>
                    <section id="execution-section" class="execution-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Execution</span>
                          <h2>Execution Desk</h2>
                        </div>
                      </div>
                      <div class="trade-grid">
                        <section class="panel" data-execution-panel="ticket">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Ticket</span>
                              <h2>Order Ticket</h2>
                            </div>
                          </div>
                          <form id="order-ticket-form" class="ticket-form">
                            <div class="ticket-grid">
                              <label class="field">
                                <span>Symbol</span>
                                <input id="order-symbol" type="text" value="UNH.US" autocomplete="off" />
                              </label>
                              <label class="field">
                                <span>Side</span>
                                <select id="order-side">
                                  <option value="buy">Buy</option>
                                  <option value="sell">Sell</option>
                                </select>
                              </label>
                              <label class="field">
                                <span>Quantity</span>
                                <input id="order-quantity" type="number" min="1" step="1" value="1" />
                              </label>
                              <label class="field">
                                <span>Order Type</span>
                                <select id="order-type">
                                  <option value="market">Market</option>
                                  <option value="limit">Limit</option>
                                  <option value="stop">Stop</option>
                                </select>
                              </label>
                              <label class="field">
                                <span>Time In Force</span>
                                <select id="order-time-in-force">
                                  <option value="day">DAY</option>
                                  <option value="gtc">GTC</option>
                                  <option value="ioc">IOC</option>
                                </select>
                              </label>
                              <label id="order-limit-field" class="field">
                                <span>Limit Price</span>
                                <input id="order-limit-price" type="number" min="0" step="0.01" placeholder="Optional for stop" />
                              </label>
                              <label id="order-stop-field" class="field">
                                <span>Stop Price</span>
                                <input id="order-stop-price" type="number" min="0" step="0.01" placeholder="Required for stop" />
                              </label>
                              <label class="field field-span-2">
                                <span>Remark</span>
                                <input id="order-remark" type="text" maxlength="64" placeholder="Optional broker note" />
                              </label>
                            </div>
                            <div class="form-foot">
                              <div>
                                <p id="order-form-hint" class="form-hint"></p>
                                <p id="order-action-status" class="form-hint local-action-status" role="status" aria-live="polite"></p>
                              </div>
                              <button id="submit-order" class="icon-button accent" type="submit" data-broker-mutation="true" data-action-key="order-submit">
                                <span class="icon" aria-hidden="true">
                                  <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M12 5v14"/>
                                    <path d="M5 12h14"/>
                                  </svg>
                                </span>
                                <span>Submit Order</span>
                              </button>
                            </div>
                          </form>
                        </section>

                        <section class="panel" data-execution-panel="detail journal" hidden>
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Workflow</span>
                              <h2>Selected Order</h2>
                            </div>
                          </div>
                          <div id="selected-order-card" class="selected-order empty" tabindex="-1">
                            Select an order from the table to manage it.
                          </div>
                          <section class="selected-order-execution-shell">
                            <div class="form-header">
                              <span class="section-kicker">Execution Summary</span>
                              <h3>Latest Fill Snapshot</h3>
                            </div>
                            <div id="selected-order-execution" class="selected-order-execution empty">
                              No fills recorded for this order yet.
                            </div>
                            <button id="executions-load-more" class="table-action" type="button" hidden>Load more fills</button>
                          </section>
                          <section class="selected-order-journal-shell">
                            <div class="form-header">
                              <span class="section-kicker">Journal</span>
                              <h3>Review Workflow</h3>
                            </div>
                            <form id="journal-entry-form" class="ticket-form">
                              <div class="ticket-grid">
                                <label class="field">
                                  <span>Entry Type</span>
                                  <select id="journal-entry-type">
                                    <option value="review">Review</option>
                                    <option value="plan">Plan</option>
                                    <option value="note">Note</option>
                                  </select>
                                </label>
                                <label class="field field-span-2">
                                  <span>Title</span>
                                  <input id="journal-title" type="text" maxlength="120" placeholder="Post-trade review headline" />
                                </label>
                                <label class="field field-span-2">
                                  <span>Tags</span>
                                  <input id="journal-tags" type="text" maxlength="160" placeholder="discipline, entry, risk" />
                                </label>
                                <label class="field field-span-2">
                                  <span>Notes</span>
                                  <textarea id="journal-notes" rows="4" placeholder="What happened, what was learned, and what changes next time."></textarea>
                                </label>
                              </div>
                              <div class="form-foot">
                                <p id="journal-form-hint" class="form-hint">Select an order to save a plan note or post-trade review.</p>
                                <button id="submit-journal" class="icon-button" type="submit">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M12 5v14"/>
                                      <path d="M5 12h14"/>
                                    </svg>
                                  </span>
                                  <span>Save Entry</span>
                                </button>
                              </div>
                            </form>
                            <div id="selected-order-journal" class="selected-order-journal empty">
                              Select an order to load journal entries.
                            </div>
                            <button id="journals-load-more" class="table-action" type="button" hidden>Load more journal entries</button>
                          </section>
                          <form id="replace-order-form" class="ticket-form hidden">
                            <div class="form-header">
                              <span class="section-kicker">Replace</span>
                              <h3>Update Working Order</h3>
                            </div>
                            <div class="ticket-grid">
                              <label class="field">
                                <span>Quantity</span>
                                <input id="replace-quantity" type="number" min="1" step="1" />
                              </label>
                              <label id="replace-limit-field" class="field">
                                <span>Limit Price</span>
                                <input id="replace-limit-price" type="number" min="0" step="0.01" placeholder="Optional for stop" />
                              </label>
                              <label id="replace-stop-field" class="field">
                                <span>Stop Price</span>
                                <input id="replace-stop-price" type="number" min="0" step="0.01" placeholder="Required for stop" />
                              </label>
                              <label class="field field-span-2">
                                <span>Remark</span>
                                <input id="replace-remark" type="text" maxlength="64" placeholder="Optional replace note" />
                              </label>
                            </div>
                            <div class="form-foot">
                              <p id="replace-form-hint" class="form-hint"></p>
                              <button class="icon-button" type="submit" data-broker-mutation="true" data-action-key="order-replace">
                                <span class="icon" aria-hidden="true">
                                  <svg viewBox="0 0 24 24" focusable="false">
                                    <path d="M20 7H9"/>
                                    <path d="M14 17H4"/>
                                    <path d="m17 4 3 3-3 3"/>
                                    <path d="m7 14-3 3 3 3"/>
                                  </svg>
                                </span>
                                <span>Replace Order</span>
                              </button>
                            </div>
                          </form>
                        </section>
                      </div>

                      <section class="panel orders-panel" data-execution-panel="orders" hidden>
                        <div class="panel-header">
                          <div>
                            <span class="section-kicker">Orders</span>
                            <h2>Orders</h2>
                          </div>
                        </div>
                        <div class="table-shell">
                          <table class="data-table">
                            <thead>
                              <tr>
                                <th>Symbol</th>
                                <th>Side</th>
                                <th>Qty</th>
                                <th>Status</th>
                                <th>Limit</th>
                                <th>Updated</th>
                                <th>Actions</th>
                              </tr>
                            </thead>
                            <tbody id="orders-body">
                              <tr><td colspan="7" class="empty-row">No orders loaded.</td></tr>
                            </tbody>
                          </table>
                        </div>
                        <div class="table-footer"><button id="orders-load-more" class="table-action" type="button" hidden>Load more orders</button></div>
                      </section>
                    </section>
                    </div>
                  </dialog>
                  </div>
                </div>

                <dialog id="watchlist-dialog" class="watchlist-dialog" aria-labelledby="watchlist-dialog-title">
                  <div class="watchlist-dialog-shell">
                    <header class="execution-drawer-header">
                      <div><span class="section-kicker">Research Universe</span><h2 id="watchlist-dialog-title">Manage Watchlist</h2></div>
                      <button id="close-watchlist-dialog" class="icon-button" type="button">Close</button>
                    </header>
                    <form id="watchlist-form" class="ticket-form">
                      <div class="ticket-grid">
                        <label class="field"><span>Name</span><input id="watchlist-name" type="text" maxlength="120" required /></label>
                        <label class="field field-span-2"><span>Description</span><input id="watchlist-description" type="text" maxlength="500" /></label>
                        <label class="check-field"><input id="watchlist-default" type="checkbox" /><span>Default watchlist</span></label>
                      </div>
                      <div class="form-foot"><span class="form-hint">Default changes affect research context only.</span><button id="watchlist-save" class="icon-button accent" type="submit">Save Watchlist</button></div>
                    </form>
                    <form id="watchlist-item-form" class="ticket-form">
                      <div class="ticket-grid">
                        <label class="field"><span>Symbol</span><input id="watchlist-symbol" type="text" maxlength="32" placeholder="AAPL.US" required /></label>
                        <label class="field"><span>Type</span><select id="watchlist-asset-type"><option value="stock">Stock</option><option value="etf">ETF</option><option value="option">Option</option></select></label>
                        <label class="field field-span-2"><span>Notes</span><input id="watchlist-notes" type="text" maxlength="1000" /></label>
                      </div>
                      <div class="form-foot"><span class="form-hint">Symbols are normalized to uppercase.</span><button id="watchlist-add-item" class="icon-button" type="submit">Add Symbol</button></div>
                    </form>
                    <div class="table-shell watchlist-items-shell">
                      <table class="data-table"><thead><tr><th>Symbol</th><th>Type</th><th>Notes</th><th>Actions</th></tr></thead><tbody id="watchlist-items-body"><tr><td colspan="4" class="empty-row">Select a watchlist.</td></tr></tbody></table>
                    </div>
                  </div>
                </dialog>

                <dialog id="trade-confirm-dialog" class="trade-confirm-dialog" aria-labelledby="trade-confirm-title">
                  <form method="dialog" class="trade-confirm-shell">
                    <div class="trade-confirm-head">
                      <div>
                        <span class="section-kicker">Paper Trading Confirmation</span>
                        <h2 id="trade-confirm-title">Confirm broker action</h2>
                      </div>
                      <span class="mode-pill">Paper</span>
                    </div>
                    <p id="trade-confirm-summary" class="trade-confirm-summary"></p>
                    <dl id="trade-confirm-details" class="trade-confirm-details"></dl>
                    <p class="trade-confirm-warning">Review every value. Closing this dialog cancels the action and sends no request.</p>
                    <div class="inline-actions trade-confirm-actions">
                      <button id="trade-confirm-cancel" class="icon-button" type="submit" value="cancel">Cancel</button>
                      <button id="trade-confirm-accept" class="icon-button accent" type="submit" value="confirm">Confirm Paper Action</button>
                    </div>
                  </form>
                </dialog>

                <script src="{lifecycle_warning_js_url}" defer></script>
                <script src="{api_client_js_url}" defer></script>
                <script src="{formatters_js_url}" defer></script>
                <script src="{i18n_js_url}" defer></script>
                <script src="{state_js_url}" defer></script>
                <script src="{chart_vendor_js_url}" defer></script>
                <script src="{chart_view_js_url}" defer></script>
                <script src="{research_view_js_url}" defer></script>
                <script src="{watchlist_view_js_url}" defer></script>
                <script src="{account_loader_js_url}" defer></script>
                <script src="{bull_put_view_js_url}" defer></script>
                <script src="{strategy_view_js_url}" defer></script>
                <script src="{advisor_view_js_url}" defer></script>
                <script src="{orders_view_js_url}" defer></script>
                <script src="{operations_recovery_js_url}" defer></script>
                <script src="{trading_safety_js_url}" defer></script>
                <script src="{execution_drawer_js_url}" defer></script>
                <script src="{workspace_shell_js_url}" defer></script>
                <script src="{workbench_ui_js_url}" defer></script>
                <script src="{research_case_js_url}" defer></script>
                <script src="{portfolio_workbench_js_url}" defer></script>
                <script src="{market_timeline_js_url}" defer></script>
                <script src="{strategy_backtest_js_url}" defer></script>
                <script src="{strategy_readiness_js_url}" defer></script>
                <script src="{advisor_audit_js_url}" defer></script>
                <script src="{app_js_url}" defer></script>
              </body>
            </html>
            """
        )
    )
