import asyncio
import threading
import logging
import os
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

import config
from agents.search_agent import fetch_prediction_markets
from agents.data_agent import fetch_historical_bars
from agents.predictor_agent import predict_next_move
from agents.risk_agent import evaluate_risk_and_wager
from agents.feedback_agent import log_prediction, resolve_pending_predictions, get_feedback_stats, get_loop_feedback_prompt

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI Server Setup
app = FastAPI(title="CrowdWisdomTrading Agent Platform")

# In-memory global state
global_state = {
    "is_running": False,
    "bankroll": config.BANKROLL,
    "loop_interval": config.TRADING_LOOP_INTERVAL,
    "recent_logs": [],
    "active_predictions": {},
    "last_update": None
}

# WebSocket connections list
connected_clients = set()

# Helper to log messages to memory and stdout
def add_agent_log(agent_name: str, message: str):
    log_entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "agent": agent_name,
        "message": message
    }
    global_state["recent_logs"].append(log_entry)
    # Keep only the last 100 log entries
    if len(global_state["recent_logs"]) > 100:
        global_state["recent_logs"].pop(0)
    logger.info(f"[{agent_name}] {message}")
    
    # Broadcast to websocket clients
    if loop is not None:
        asyncio.run_coroutine_threadsafe(broadcast_state_update(), loop)

async def broadcast_state_update():
    """Broadcasts current state and logs to all connected WebSocket clients."""
    if not connected_clients:
        return
        
    stats = get_feedback_stats()
    payload = {
        "is_running": global_state["is_running"],
        "bankroll": round(global_state["bankroll"], 2),
        "loop_interval": global_state["loop_interval"],
        "logs": global_state["recent_logs"][-15:], # Send last 15 logs
        "active_predictions": global_state["active_predictions"],
        "stats": {
            "total_wagers": stats["total_wagers"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "model_stats": stats["model_stats"],
            "recent_history": stats["recent_history"][:10]
        },
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Send to all clients
    disconnected = set()
    for client in connected_clients:
        try:
            await client.send_json(payload)
        except WebSocketDisconnect:
            disconnected.add(client)
        except Exception as e:
            logger.error(f"Error sending websocket payload: {e}")
            disconnected.add(client)
            
    for client in disconnected:
        connected_clients.remove(client)

# Main Background Agent Execution Loop
def run_agent_loop_sync():
    """Synchronous agent loop wrapper that executes in a background thread."""
    add_agent_log("System", "Agent execution thread started.")
    
    while global_state["is_running"]:
        try:
            add_agent_log("Orchestrator", "=== Starting Agent Loop Iteration ===")
            
            # Step 1: Fetch loop feedback context
            feedback_prompt = get_loop_feedback_prompt()
            add_agent_log("Feedback Agent", f"Injected feedback stats: PnL: ${global_state['bankroll'] - config.BANKROLL:.2f}")
            
            # Step 2: Scrape markets / pricing
            add_agent_log("Search Agent", "Querying Polymarket and Kalshi APIs for BTC/ETH contracts...")
            markets = fetch_prediction_markets()
            is_sim = any(m["is_simulated"] for m in markets.values())
            
            if is_sim:
                add_agent_log("Search Agent", "APIs restricted/geoblocked. Running Fallback: real-time Binance spot + simulated prediction contract spreads.")
            else:
                add_agent_log("Search Agent", "Successfully queried live contract prices from Polymarket & Kalshi.")
            
            # Extract current spot prices for resolving past trades
            current_prices = {asset: data["spot_price"] for asset, data in markets.items()}
            
            # Step 3: Resolve pending predictions
            add_agent_log("Feedback Agent", "Checking database for unresolved predictions...")
            resolved_trades = resolve_pending_predictions(current_prices, is_simulated=is_sim)
            
            # Adjust bankroll based on trade resolution PnL
            for trade in resolved_trades:
                pnl = trade["profit_loss"]
                global_state["bankroll"] += pnl
                result_str = f"WIN (+${pnl:.2f})" if trade["is_win"] == 1 else f"LOSS (-${abs(pnl):.2f})"
                add_agent_log("Feedback Agent", f"Trade Resolution: Asset {trade['asset']} on {trade['wager_platform']} resolved as {result_str}. Spot at expiry was ${trade['expiry_price']:.2f}")

            # Step 4: Fetch historical bars and predict
            predictions = {}
            wagers = {}
            
            for asset in ["BTC", "ETH"]:
                add_agent_log("Data Agent", f"Fetching historical bars (1000 bars) for {asset}...")
                df = fetch_historical_bars(asset, limit=1000)
                add_agent_log("Data Agent", f"Historical bars retrieved. Shape: {df.shape}")
                
                # Step 5: Run predictions
                target_price = markets[asset]["target_price"]
                add_agent_log("Predictor Agent", f"Generating next move prediction for {asset} (target: ${target_price})...")
                pred = predict_next_move(asset, df, target_price)
                predictions[asset] = pred
                
                # Step 6: Risk management position sizing
                add_agent_log("Risk Agent", f"Evaluating position sizing and arbitrage for {asset}...")
                risk_evaluation = evaluate_risk_and_wager(pred, markets, global_state["bankroll"], config.KELLY_FRACTION)
                wagers[asset] = risk_evaluation
                
                # Check for arbitrage
                arb = risk_evaluation["arbitrage"]
                if arb["arbitrage_detected"]:
                    add_agent_log("Risk Agent", f"🚨 ARBITRAGE DETECTED for {asset}: {arb['details']}")
                
                # Deduct wager amount from bankroll if a trade is logged
                pm_kelly = risk_evaluation["polymarket_kelly"]
                ks_kelly = risk_evaluation["kalshi_kelly"]
                
                # Choose active wager
                active_wager = 0.0
                if arb["arbitrage_detected"]:
                    active_wager = max(pm_kelly["wager_amount"], ks_kelly["wager_amount"], 10.0)
                elif pm_kelly["wager_amount"] > 0:
                    active_wager = pm_kelly["wager_amount"]
                elif ks_kelly["wager_amount"] > 0:
                    active_wager = ks_kelly["wager_amount"]
                    
                if active_wager > 0:
                    global_state["bankroll"] -= active_wager
                    add_agent_log("Risk Agent", f"Allocated and deducted ${active_wager:.2f} from bankroll for {asset} wager.")
                else:
                    add_agent_log("Risk Agent", f"No edge found for {asset}. Standing aside.")
                
                # Log predictions & wagers in DB
                log_prediction(pred, markets, risk_evaluation)
                
            # Update global state for dashboard UI
            global_state["active_predictions"] = {
                "BTC": {
                    "spot": markets["BTC"]["spot_price"],
                    "target": markets["BTC"]["target_price"],
                    "prob_up": predictions["BTC"]["probability_up"],
                    "pm_yes": markets["BTC"]["polymarket"]["yes_odds"],
                    "ks_yes": markets["BTC"]["kalshi"]["yes_odds"],
                    "pm_wager": wagers["BTC"]["polymarket_kelly"]["wager_amount"],
                    "pm_dir": wagers["BTC"]["polymarket_kelly"]["direction"],
                    "ks_wager": wagers["BTC"]["kalshi_kelly"]["wager_amount"],
                    "ks_dir": wagers["BTC"]["kalshi_kelly"]["direction"],
                    "arb_detected": wagers["BTC"]["arbitrage"]["arbitrage_detected"],
                    "arb_details": wagers["BTC"]["arbitrage"]["details"]
                },
                "ETH": {
                    "spot": markets["ETH"]["spot_price"],
                    "target": markets["ETH"]["target_price"],
                    "prob_up": predictions["ETH"]["probability_up"],
                    "pm_yes": markets["ETH"]["polymarket"]["yes_odds"],
                    "ks_yes": markets["ETH"]["kalshi"]["yes_odds"],
                    "pm_wager": wagers["ETH"]["polymarket_kelly"]["wager_amount"],
                    "pm_dir": wagers["ETH"]["polymarket_kelly"]["direction"],
                    "ks_wager": wagers["ETH"]["kalshi_kelly"]["wager_amount"],
                    "ks_dir": wagers["ETH"]["kalshi_kelly"]["direction"],
                    "arb_detected": wagers["ETH"]["arbitrage"]["arbitrage_detected"],
                    "arb_details": wagers["ETH"]["arbitrage"]["details"]
                }
            }
            
            add_agent_log("Orchestrator", f"Iteration complete. Bankroll: ${global_state['bankroll']:.2f}. Sleeping for {global_state['loop_interval']}s...")
            
        except Exception as e:
            add_agent_log("System Error", f"Exception in agent loop: {e}")
            logger.exception("Agent loop exception")
            
        # Thread sleep interval (non-blocking chunked checks to respond immediately to stop request)
        for _ in range(global_state["loop_interval"]):
            if not global_state["is_running"]:
                break
            time.sleep(1)
            
    add_agent_log("System", "Agent execution thread stopped.")

# FastAPI Routes
@app.get("/api/status")
def get_api_status():
    stats = get_feedback_stats()
    return {
        "is_running": global_state["is_running"],
        "bankroll": round(global_state["bankroll"], 2),
        "loop_interval": global_state["loop_interval"],
        "logs": global_state["recent_logs"],
        "active_predictions": global_state["active_predictions"],
        "stats": {
            "total_wagers": stats["total_wagers"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "model_stats": stats["model_stats"],
            "recent_history": stats["recent_history"]
        }
    }

@app.post("/api/toggle")
def toggle_agent_loop():
    """Starts or stops the background trading loop."""
    if global_state["is_running"]:
        global_state["is_running"] = False
        add_agent_log("Orchestrator", "Stop request received. Halting trading loop.")
    else:
        global_state["is_running"] = True
        add_agent_log("Orchestrator", "Start request received. Launching agent execution thread.")
        # Start background thread
        thread = threading.Thread(target=run_agent_loop_sync, daemon=True)
        thread.start()
        
    return {"is_running": global_state["is_running"]}

@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str):
    """Fetches recent historical data points for plotting on the chart."""
    df = fetch_historical_bars(symbol, limit=100)
    # Convert dataframe to list of dicts for JSON
    chart_points = []
    for _, row in df.iterrows():
        chart_points.append({
            "time": int(row["timestamp"].timestamp()),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"]
        })
    return {"symbol": symbol, "data": chart_points}

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    # Send initial state immediately
    stats = get_feedback_stats()
    payload = {
        "is_running": global_state["is_running"],
        "bankroll": round(global_state["bankroll"], 2),
        "loop_interval": global_state["loop_interval"],
        "logs": global_state["recent_logs"],
        "active_predictions": global_state["active_predictions"],
        "stats": {
            "total_wagers": stats["total_wagers"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "model_stats": stats["model_stats"],
            "recent_history": stats["recent_history"]
        },
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    await websocket.send_json(payload)
    
    try:
        while True:
            # Keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)

# Mount Static Files
static_dir = os.path.join(config.BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# Async Loop handler
loop = None

@app.on_event("startup")
async def startup_event():
    global loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

if __name__ == "__main__":
    # Ensure feedback database exists
    from agents.feedback_agent import init_db
    import time
    init_db()
    
    add_agent_log("System", "Starting FastAPI web server on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
