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
              </head>
              <body>
                <div class="shell">
                  <header class="topbar">
                    <div class="brand">
                      <div class="brand-mark">ST</div>
                      <div class="brand-copy">
                        <span class="eyebrow">Paper Trading Desk</span>
                        <h1>Stocks Tool Workbench</h1>
                      </div>
                    </div>
                    <div class="topbar-actions">
                      <div class="language-switch" aria-label="Language">
                        <button class="lang-option" type="button" data-lang-option="zh">中文</button>
                        <button class="lang-option" type="button" data-lang-option="en">EN</button>
                      </div>
                      <span class="mode-pill">Paper</span>
                      <a class="action-link" href="/docs">API Docs</a>
                    </div>
                  </header>

                  <nav class="workspace-nav" aria-label="Workbench sections">
                    <a href="#account-section">Account</a>
                    <a href="#strategy-section">Strategy</a>
                    <a href="#portfolio-section">Portfolio</a>
                    <a href="#execution-section">Execution</a>
                  </nav>

                  <main class="workspace">
                    <section id="account-section" class="band account-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Account</span>
                          <h2>Account Control</h2>
                        </div>
                        <button id="refresh-dashboard" class="icon-button" type="button">
                          <span class="icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" focusable="false">
                              <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                              <path d="M21 3v6h-6"/>
                            </svg>
                          </span>
                          <span>Refresh</span>
                        </button>
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

                      <div id="status-banner" class="status-banner">Ready</div>
                    </section>

                    <section id="strategy-section" class="band strategy-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Strategy</span>
                          <h2>Strategy Center</h2>
                        </div>
                      </div>

                      <div class="strategy-layout">
                        <section class="panel panel-span-2">
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
                              <p id="strategy-controls-hint" class="form-hint">Strategy controls apply to new bull put entries only. Existing spreads remain monitored.</p>
                              <div class="inline-actions">
                                <button id="save-strategy-controls" class="icon-button" type="submit">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M5 5h11l3 3v11H5z"/>
                                      <path d="M8 5v6h8"/>
                                      <path d="M8 19v-6h8v6"/>
                                    </svg>
                                  </span>
                                  <span>Save Controls</span>
                                </button>
                                <button id="run-strategy-scan" class="icon-button accent" type="button">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M3 12h18"/>
                                      <path d="m13 6 6 6-6 6"/>
                                    </svg>
                                  </span>
                                  <span>Run Scan</span>
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

                        <section class="panel panel-span-2">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Zero-DTE</span>
                              <h2>Lottery Strategy</h2>
                            </div>
                          </div>
                          <div id="zero-dte-lottery-strip" class="mini-metric-strip strategy-summary-strip">
                            <article class="mini-metric-tile">
                              <span class="metric-label">Auto Order</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">No runtime state loaded.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Max Premium</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">$150 default cap.</span>
                            </article>
                            <article class="mini-metric-tile">
                              <span class="metric-label">Scan Window</span>
                              <strong class="mini-metric-value">--</strong>
                              <span class="mini-metric-detail">Automation is off by default.</span>
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
                                <span>Auto Order</span>
                                <select id="zero-dte-lottery-auto-order">
                                  <option value="false">Disabled</option>
                                  <option value="true">Enabled</option>
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
                              <p id="zero-dte-lottery-hint" class="form-hint">Paper-only same-day long option. Auto-order is disabled by default and capped at $150.</p>
                              <div class="inline-actions">
                                <button id="save-zero-dte-lottery-controls" class="icon-button" type="submit">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M5 5h11l3 3v11H5z"/>
                                      <path d="M8 5v6h8"/>
                                      <path d="M8 19v-6h8v6"/>
                                    </svg>
                                  </span>
                                  <span>Save Lottery Controls</span>
                                </button>
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
                                <button id="run-zero-dte-lottery-scan" class="icon-button accent" type="button">
                                  <span class="icon" aria-hidden="true">
                                    <svg viewBox="0 0 24 24" focusable="false">
                                      <path d="M3 12h18"/>
                                      <path d="m13 6 6 6-6 6"/>
                                    </svg>
                                  </span>
                                  <span>Force Scan</span>
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

                        <section class="panel panel-span-2">
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

                        <section class="panel panel-span-2">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Experiment</span>
                              <h2>Strategy Experiment Bench</h2>
                            </div>
                          </div>
                          <div id="strategy-experiment-strip" class="mini-metric-strip strategy-summary-strip">
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
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Covered Calls</span>
                                <h3>Activity History</h3>
                              </div>
                              <div id="covered-call-activity-card" class="strategy-note-body empty">
                                No covered-call activity yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Proposals</span>
                                <h3>Strategy Proposals</h3>
                              </div>
                              <div id="strategy-proposals-card" class="strategy-note-body empty">
                                No strategy experiment proposals yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Runs</span>
                                <h3>Strategy Runs</h3>
                              </div>
                              <div id="strategy-runs-card" class="strategy-note-body empty">
                                No strategy runs recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Signals</span>
                                <h3>Signal Feed</h3>
                              </div>
                              <div id="strategy-signals-card" class="strategy-note-body empty">
                                No strategy signals recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card">
                              <div class="form-header">
                                <span class="section-kicker">Reviews</span>
                                <h3>Review Feed</h3>
                              </div>
                              <div id="strategy-reviews-card" class="strategy-note-body empty">
                                No strategy reviews recorded yet.
                              </div>
                            </article>
                            <article class="strategy-note-card advisor-note-card">
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
                            </article>
                          </div>
                        </section>

                        <section class="panel panel-span-2">
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

                        <section class="panel panel-span-2">
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

                    <section id="portfolio-section" class="band portfolio-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Portfolio</span>
                          <h2>Holdings Overview</h2>
                        </div>
                      </div>
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
                    </section>

                    <section id="execution-section" class="band execution-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Execution</span>
                          <h2>Execution Desk</h2>
                        </div>
                      </div>
                      <div class="trade-grid">
                        <section class="panel">
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
                              <p id="order-form-hint" class="form-hint"></p>
                              <button id="submit-order" class="icon-button accent" type="submit">
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

                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Workflow</span>
                              <h2>Selected Order</h2>
                            </div>
                          </div>
                          <div id="selected-order-card" class="selected-order empty">
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
                              <button class="icon-button" type="submit">
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

                      <section class="panel orders-panel">
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
                      </section>
                    </section>
                  </main>
                </div>

                <script src="{app_js_url}" defer></script>
              </body>
            </html>
            """
        )
    )
