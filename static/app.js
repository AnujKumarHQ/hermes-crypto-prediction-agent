// Global state
let currentChartSymbol = "BTC";
let chart = null;
let candlestickSeries = null;
let ws = null;

// Initialize Charting
function initChart() {
    const container = document.getElementById("candlestick-chart");
    if (!container) return;
    
    // Clear previous content
    container.innerHTML = "";
    
    // Check if LightweightCharts is loaded
    if (typeof LightweightCharts === "undefined") {
        console.warn("TradingView Lightweight Charts library is not loaded. Displaying fallback message.");
        container.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: 280px; color: var(--text-secondary); flex-direction: column; gap: 10px; border: 1px dashed var(--border-color); border-radius: 8px; background: rgba(0,0,0,0.2);">
                <i class="fa-solid fa-circle-exclamation" style="font-size: 24px; color: var(--accent-gold);"></i>
                <span style="font-weight: 500;">Charting Library Offline / Blocked</span>
                <span style="font-size: 11px; color: var(--text-muted);">Ensure unpkg.com is accessible</span>
            </div>
        `;
        return;
    }
    
    try {
        // Create chart instance
        chart = LightweightCharts.createChart(container, {
            layout: {
                background: { type: 'solid', color: '#11182c' },
                textColor: '#9ca3af',
                fontFamily: "'Outfit', sans-serif",
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
                borderColor: 'rgba(255, 255, 255, 0.1)',
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
            }
        });
        
        // Add candlestick series
        candlestickSeries = chart.addCandlestickSeries({
            upColor: '#00ff88',
            downColor: '#ff4466',
            borderDownColor: '#ff4466',
            borderUpColor: '#00ff88',
            wickDownColor: '#ff4466',
            wickUpColor: '#00ff88',
        });
        
        // Fetch initial chart data
        loadChartData(currentChartSymbol);
        
        // Handle resizing
        const resizeObserver = new ResizeObserver(entries => {
            if (entries.length === 0 || entries[0].target !== container || !chart) return;
            const newRect = entries[0].contentRect;
            chart.resize(newRect.width, Math.max(newRect.height, 280));
        });
        resizeObserver.observe(container);
    } catch (e) {
        console.error("Error creating chart:", e);
    }
}

// Fetch historical bars for chart
function loadChartData(symbol) {
    if (typeof LightweightCharts === "undefined" || !candlestickSeries || !chart) {
        return;
    }
    fetch(`/api/chart/${symbol}`)
        .then(response => response.json())
        .then(res => {
            if (res.data && res.data.length > 0 && candlestickSeries && chart) {
                candlestickSeries.setData(res.data);
                chart.timeScale().fitContent();
            }
        })
        .catch(err => console.error("Error loading chart data:", err));
}

let pollInterval = null;

// Connect WebSocket for real-time updates, falling back to HTTP polling if unavailable
function connectWebSocket() {
    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/ws`;
    
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    
    try {
        ws = new WebSocket(wsUrl);
        
        ws.onopen = () => {
            console.log("WebSocket connection established");
            updateConnectionStatus("online", "Connected (Live)");
        };
        
        ws.onmessage = (event) => {
            const payload = JSON.parse(event.data);
            updateDashboardState(payload);
        };
        
        ws.onclose = () => {
            console.log("WebSocket connection closed. Switching to HTTP polling...");
            updateConnectionStatus("active", "Polling (Active)");
            startPolling();
        };
        
        ws.onerror = (err) => {
            console.warn("WebSocket error occurred, closing:", err);
            ws.close();
        };
    } catch (e) {
        console.warn("Failed to create WebSocket, starting polling:", e);
        updateConnectionStatus("active", "Polling (Active)");
        startPolling();
    }
}

function startPolling() {
    if (pollInterval) return;
    fetchStatus();
    pollInterval = setInterval(fetchStatus, 2000);
}

function fetchStatus() {
    fetch("/api/status")
        .then(response => response.json())
        .then(data => {
            updateDashboardState(data);
        })
        .catch(err => {
            console.error("Error polling status:", err);
            updateConnectionStatus("offline", "Server Offline");
        });
}

function updateConnectionStatus(status, text) {
    const indicator = document.getElementById("connection-status");
    const statusText = document.getElementById("connection-status-text");
    
    if (indicator && statusText) {
        indicator.className = `status-indicator ${status}`;
        statusText.innerText = text;
    }
}

// Update DOM elements with WebSocket state
function updateDashboardState(data) {
    // 1. Update active loop button & indicator
    const btnToggle = document.getElementById("btn-toggle-loop");
    const indicator = document.getElementById("connection-status");
    const statusText = document.getElementById("connection-status-text");
    
    if (data.is_running) {
        btnToggle.className = "btn btn-control stop";
        btnToggle.innerHTML = `<i class="fa-solid fa-square-full"></i> STOP AGENT LOOP`;
        if (indicator && statusText) {
            indicator.className = "status-indicator active";
            statusText.innerText = "Running Trading Loop";
        }
    } else {
        btnToggle.className = "btn btn-control start";
        btnToggle.innerHTML = `<i class="fa-solid fa-play"></i> START AGENT LOOP`;
        if (indicator && statusText) {
            indicator.className = "status-indicator online";
            statusText.innerText = "Connected Idle";
        }
    }
    
    // 2. Update stats cards
    document.getElementById("val-bankroll").innerText = `$${data.bankroll.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    const pnl = data.bankroll - 1000.0;
    const pnlText = pnl >= 0 ? `PnL: +$${pnl.toFixed(2)}` : `PnL: -$${Math.abs(pnl).toFixed(2)}`;
    const pnlEl = document.getElementById("val-pnl-lifetime");
    pnlEl.innerText = pnlText;
    pnlEl.className = pnl >= 0 ? "stat-desc text-green" : "stat-desc text-red";
    
    document.getElementById("val-win-rate").innerText = `${(data.stats.win_rate * 100).toFixed(1)}%`;
    document.getElementById("val-total-trades").innerText = `${data.stats.total_wagers} trades resolved`;
    
    // Active Arbitrage Summary
    const hasBTCArb = data.active_predictions.BTC?.arb_detected;
    const hasETHArb = data.active_predictions.ETH?.arb_detected;
    const arbValEl = document.getElementById("val-arb-status");
    const arbDescEl = document.getElementById("val-arb-details");
    
    if (hasBTCArb || hasETHArb) {
        arbValEl.innerText = "Arbitrage Opportunity!";
        arbValEl.className = "stat-value text-small text-green";
        arbDescEl.innerText = hasBTCArb ? "BTC Discrepancy Found" : "ETH Discrepancy Found";
    } else {
        arbValEl.innerText = "No Opportunities";
        arbValEl.className = "stat-value text-small";
        arbDescEl.innerText = "Scanning Polymarket vs Kalshi";
    }
    
    // 3. Update asset cards (BTC/ETH)
    for (const asset of ["BTC", "ETH"]) {
        const pred = data.active_predictions[asset];
        const card = document.getElementById(`card-${asset.toLowerCase()}`);
        
        if (pred && card) {
            // Update prices
            document.getElementById(`${asset.toLowerCase()}-spot`).innerText = `$${pred.spot.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
            document.getElementById(`${asset.toLowerCase()}-target`).innerText = `$${pred.target.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
            
            // Update odds
            document.getElementById(`${asset.toLowerCase()}-pm-yes`).innerText = pred.pm_yes.toFixed(2);
            document.getElementById(`${asset.toLowerCase()}-pm-no`).innerText = (1.0 - pred.pm_yes).toFixed(2);
            document.getElementById(`${asset.toLowerCase()}-ks-yes`).innerText = pred.ks_yes.toFixed(2);
            document.getElementById(`${asset.toLowerCase()}-ks-no`).innerText = (1.0 - pred.ks_yes).toFixed(2);
            
            // Gauge & Probabilities
            const fillWidth = pred.prob_up * 100;
            document.getElementById(`${asset.toLowerCase()}-gauge-fill`).style.width = `${fillWidth}%`;
            document.getElementById(`${asset.toLowerCase()}-prob-up`).innerText = `${(pred.prob_up * 100).toFixed(0)}%`;
            document.getElementById(`${asset.toLowerCase()}-prob-down`).innerText = `${((1.0 - pred.prob_up) * 100).toFixed(0)}%`;
            
            // Wager descriptions
            const pmWagerEl = document.getElementById(`${asset.toLowerCase()}-pm-wager`);
            const ksWagerEl = document.getElementById(`${asset.toLowerCase()}-ks-wager`);
            
            // Reset classes
            pmWagerEl.className = "wager-desc";
            ksWagerEl.className = "wager-desc";
            
            if (pred.pm_wager > 0) {
                pmWagerEl.innerText = `Kelly Bet: ${pred.pm_dir} $${pred.pm_wager.toFixed(2)}`;
                pmWagerEl.className = pred.pm_dir === "YES" ? "wager-desc yes-bet" : "wager-desc no-bet";
            } else {
                pmWagerEl.innerText = "Wager: Stand Aside";
            }
            
            if (pred.ks_wager > 0) {
                ksWagerEl.innerText = `Kelly Bet: ${pred.ks_dir} $${pred.ks_wager.toFixed(2)}`;
                ksWagerEl.className = pred.ks_dir === "YES" ? "wager-desc yes-bet" : "wager-desc no-bet";
            } else {
                ksWagerEl.innerText = "Wager: Stand Aside";
            }
            
            // Arbitrage display
            const arbBadge = document.getElementById(`${asset.toLowerCase()}-arb-badge`);
            const arbText = document.getElementById(`${asset.toLowerCase()}-arb-text`);
            
            if (pred.arb_detected) {
                card.classList.add("arb-alert");
                arbBadge.classList.remove("hidden");
                arbText.classList.remove("hidden");
                arbText.innerText = pred.arb_details;
            } else {
                card.classList.remove("arb-alert");
                arbBadge.classList.add("hidden");
                arbText.classList.add("hidden");
            }
        }
    }
    
    // 4. Update Logs Terminal
    const terminal = document.getElementById("log-terminal");
    if (terminal && data.logs && data.logs.length > 0) {
        terminal.innerHTML = "";
        data.logs.forEach(log => {
            // Determine class
            let tagClass = "sys";
            const tag = log.agent.toLowerCase();
            if (tag.includes("orchestrator")) tagClass = "orch";
            else if (tag.includes("search")) tagClass = "search";
            else if (tag.includes("data")) tagClass = "data";
            else if (tag.includes("predict")) tagClass = "pred";
            else if (tag.includes("risk")) tagClass = "risk";
            else if (tag.includes("feedback")) tagClass = "feedback";
            else if (tag.includes("error")) tagClass = "err";
            
            const row = document.createElement("div");
            row.className = `log-row ${tagClass}`;
            row.innerHTML = `
                <span class="log-time">[${log.timestamp}]</span>
                <span class="log-tag">[${log.agent}]</span>
                <span class="log-msg">${escapeHtml(log.message)}</span>
            `;
            terminal.appendChild(row);
        });
        // Scroll to bottom
        terminal.scrollTop = terminal.scrollHeight;
    }
    
    // 5. Update history table
    const tableBody = document.getElementById("history-table-body");
    if (tableBody) {
        if (data.stats.recent_history && data.stats.recent_history.length > 0) {
            tableBody.innerHTML = "";
            data.stats.recent_history.forEach(trade => {
                const tr = document.createElement("tr");
                
                let badgeClass = "badge-none";
                let outcomeStr = "Pending";
                if (trade.resolved) {
                    if (trade.wager_direction === "NONE") {
                        badgeClass = "badge-none";
                        outcomeStr = "N/A";
                    } else if (trade.is_win === 1) {
                        badgeClass = "badge-win";
                        outcomeStr = "WIN";
                    } else {
                        badgeClass = "badge-loss";
                        outcomeStr = "LOSS";
                    }
                }
                
                const pnlValue = trade.profit_loss;
                let pnlClass = "";
                let pnlStr = "$0.00";
                if (pnlValue > 0) {
                    pnlClass = "text-green";
                    pnlStr = `+$${pnlValue.toFixed(2)}`;
                } else if (pnlValue < 0) {
                    pnlClass = "text-red";
                    pnlStr = `-$${Math.abs(pnlValue).toFixed(2)}`;
                }
                
                tr.innerHTML = `
                    <td>${trade.timestamp}</td>
                    <td><strong>${trade.asset}</strong></td>
                    <td>$${trade.spot_price.toLocaleString()}</td>
                    <td>$${trade.target_price.toLocaleString()}</td>
                    <td>${(trade.model_probability * 100).toFixed(0)}% UP</td>
                    <td>${trade.wager_platform}</td>
                    <td>${trade.wager_direction} ${trade.wager_amount > 0 ? `$${trade.wager_amount.toFixed(2)}` : ''}</td>
                    <td><span class="${badgeClass}">${outcomeStr}</span></td>
                    <td class="${pnlClass}"><strong>${pnlStr}</strong></td>
                `;
                tableBody.appendChild(tr);
            });
        } else {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="9" class="text-center">No trades resolved yet. Start the agent loop to execute wagers.</td>
                </tr>
            `;
        }
    }
}

// Utility to escape HTML and prevent injection in logs
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

// Event Bindings
document.addEventListener("DOMContentLoaded", () => {
    // 1. Chart initialization
    initChart();
    
    // 2. WebSocket Connection
    connectWebSocket();
    
    // 3. Start/Stop Loop Button
    const btnToggle = document.getElementById("btn-toggle-loop");
    btnToggle.addEventListener("click", () => {
        fetch("/api/toggle", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                console.log("Trading loop status toggled. Running:", data.is_running);
            })
            .catch(err => console.error("Error toggling loop:", err));
    });
    
    // 4. Navigation Toggles
    const btnDashboard = document.getElementById("btn-nav-dashboard");
    const btnHistory = document.getElementById("btn-nav-history");
    const viewDashboard = document.getElementById("dashboard-view");
    const viewHistory = document.getElementById("history-view");
    
    btnDashboard.addEventListener("click", (e) => {
        e.preventDefault();
        btnDashboard.classList.add("active");
        btnHistory.classList.remove("active");
        viewDashboard.classList.remove("hidden");
        viewHistory.classList.add("hidden");
    });
    
    btnHistory.addEventListener("click", (e) => {
        e.preventDefault();
        btnHistory.classList.add("active");
        btnDashboard.classList.remove("active");
        viewHistory.classList.remove("hidden");
        viewDashboard.classList.add("hidden");
        // Reload websocket update to fill tables immediately
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send("refresh");
        }
    });
    
    // 5. Chart Toggles
    const btnChartBtc = document.getElementById("btn-chart-btc");
    const btnChartEth = document.getElementById("btn-chart-eth");
    
    btnChartBtc.addEventListener("click", () => {
        btnChartBtc.classList.add("active");
        btnChartEth.classList.remove("active");
        currentChartSymbol = "BTC";
        loadChartData("BTC");
    });
    
    btnChartEth.addEventListener("click", () => {
        btnChartEth.classList.add("active");
        btnChartBtc.classList.remove("active");
        currentChartSymbol = "ETH";
        loadChartData("ETH");
    });
});
