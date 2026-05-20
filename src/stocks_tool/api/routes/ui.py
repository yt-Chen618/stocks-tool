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
                                </tr>
                              </thead>
                              <tbody id="orders-body">
                                <tr><td colspan="6" class="empty-row">No orders loaded.</td></tr>
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
                                  <th>Qty</th>
                                  <th>Avg Cost</th>
                                  <th>Market Value</th>
                                  <th>Unrealized PnL</th>
                                </tr>
                              </thead>
                              <tbody id="positions-body">
                                <tr><td colspan="5" class="empty-row">No positions in latest snapshot.</td></tr>
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
