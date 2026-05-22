from textwrap import dedent

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
def render_dashboard() -> HTMLResponse:
    return HTMLResponse(
        dedent(
            """\
            <!doctype html>
            <html lang="zh-CN">
              <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>Stocks Tool Workbench</title>
                <link rel="stylesheet" href="/static/app.css" />
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
                      <span class="mode-pill">Paper</span>
                      <a class="action-link" href="/docs">API Docs</a>
                    </div>
                  </header>

                  <main class="workspace">
                    <section class="band controls-band">
                      <div class="band-header">
                        <div>
                          <span class="section-kicker">Session</span>
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

                    <section class="band metrics-band">
                      <div class="metric-strip" id="metrics-strip">
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
                    </section>

                    <section class="band holdings-band">
                      <div class="holdings-grid">
                        <section class="panel">
                          <div class="panel-header">
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
                        </section>

                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Exposure</span>
                              <h2>Current Holdings</h2>
                            </div>
                          </div>
                          <div id="holdings-focus" class="holdings-focus">
                            <div class="holding-empty">No positions in latest snapshot.</div>
                          </div>
                        </section>
                      </div>
                    </section>

                    <section class="band insights-band">
                      <div class="panel-grid">
                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Broker</span>
                              <h2>Longbridge Status</h2>
                            </div>
                          </div>
                          <dl id="broker-status" class="status-list"></dl>
                        </section>

                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Quote</span>
                              <h2>Quick Quote</h2>
                            </div>
                          </div>
                          <form id="quote-form" class="quote-form">
                            <label class="field">
                              <span>Symbol</span>
                              <input id="quote-symbol" type="text" value="UNH.US" autocomplete="off" />
                            </label>
                            <button class="icon-button accent" type="submit">
                              <span class="icon" aria-hidden="true">
                                <svg viewBox="0 0 24 24" focusable="false">
                                  <circle cx="11" cy="11" r="7"/>
                                  <path d="m21 21-4.3-4.3"/>
                                </svg>
                              </span>
                              <span>Load Quote</span>
                            </button>
                          </form>
                          <div id="quote-card" class="quote-card empty">No quote loaded.</div>
                        </section>
                      </div>
                    </section>

                    <section class="band trade-band">
                      <div class="trade-grid">
                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Execution</span>
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
                    </section>

                    <section class="band data-band">
                      <div class="data-grid">
                        <section class="panel panel-span-2">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Execution</span>
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

                        <section class="panel">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Research</span>
                              <h2>Watchlists</h2>
                            </div>
                          </div>
                          <div id="watchlists-body" class="stack-list"></div>
                        </section>

                        <section class="panel panel-span-2">
                          <div class="panel-header">
                            <div>
                              <span class="section-kicker">Exposure</span>
                              <h2>Positions</h2>
                            </div>
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
                      </div>
                    </section>
                  </main>
                </div>

                <script src="/static/app.js" defer></script>
              </body>
            </html>
            """
        )
    )
