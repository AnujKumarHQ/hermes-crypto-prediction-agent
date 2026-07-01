import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
import config

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(config.DATA_DIR, "feedback.db")

def init_db():
    """Initializes the feedback database and creates tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            asset TEXT NOT NULL,
            spot_price REAL NOT NULL,
            target_price REAL NOT NULL,
            model_probability REAL NOT NULL,
            model_used TEXT NOT NULL,
            pm_yes_odds REAL,
            ks_yes_odds REAL,
            wager_platform TEXT,
            wager_direction TEXT,
            wager_amount REAL,
            resolved INTEGER DEFAULT 0,
            actual_expiry_price REAL,
            resolution_outcome TEXT,
            is_win INTEGER DEFAULT -1,
            profit_loss REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

def log_prediction(
    prediction: Dict[str, Any], 
    markets: Dict[str, Any], 
    risk: Dict[str, Any]
) -> int:
    """Logs a new prediction and wager recommendation to the SQLite database."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    asset = prediction["symbol"]
    market_data = markets[asset]
    
    # Choose platform with better Kelly recommendation or arbitrage
    pm_wager = risk["polymarket_kelly"]["wager_amount"]
    ks_wager = risk["kalshi_kelly"]["wager_amount"]
    
    if risk["arbitrage"]["arbitrage_detected"]:
        # If arbitrage is detected, log it as a special arbitrage trade
        platform = "ARBITRAGE"
        direction = risk["arbitrage"]["action"]
        wager_amount = max(pm_wager, ks_wager, 10.0) # Allocate some funds to arb
    elif pm_wager >= ks_wager and pm_wager > 0:
        platform = "Polymarket"
        direction = risk["polymarket_kelly"]["direction"]
        wager_amount = pm_wager
    elif ks_wager > pm_wager and ks_wager > 0:
        platform = "Kalshi"
        direction = risk["kalshi_kelly"]["direction"]
        wager_amount = ks_wager
    else:
        platform = "NONE"
        direction = "NONE"
        wager_amount = 0.0

    cursor.execute("""
        INSERT INTO predictions (
            timestamp, asset, spot_price, target_price, model_probability, model_used,
            pm_yes_odds, ks_yes_odds, wager_platform, wager_direction, wager_amount, resolved
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        asset,
        market_data["spot_price"],
        market_data["target_price"],
        prediction["probability_up"],
        prediction["model_used"],
        market_data["polymarket"]["yes_odds"],
        market_data["kalshi"]["yes_odds"],
        platform,
        direction,
        wager_amount
    ))
    
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    logger.info(f"Logged prediction for {asset} (ID: {trade_id}): Wager {wager_amount} on {platform} {direction}")
    return trade_id

def resolve_pending_predictions(current_spot_prices: Dict[str, float], is_simulated: bool = True) -> List[Dict[str, Any]]:
    """
    Checks the database for unresolved predictions, evaluates them against current spot prices,
    resolves them as win/loss, and computes PnL.
    In simulation mode, resolves trades older than 15 seconds. In live mode, resolves trades older than 5 minutes.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Fetch pending trades
    cursor.execute("SELECT * FROM predictions WHERE resolved = 0")
    pending = cursor.fetchall()
    
    resolved_trades = []
    
    for trade in pending:
        trade_id = trade["id"]
        asset = trade["asset"]
        timestamp_str = trade["timestamp"]
        target_price = trade["target_price"]
        wager_amount = trade["wager_amount"]
        wager_direction = trade["wager_direction"]
        wager_platform = trade["wager_platform"]
        
        # Parse timestamp
        trade_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        time_elapsed = datetime.now() - trade_time
        
        # Decide resolution threshold: 15s for simulation/demo, 5m for live
        threshold = timedelta(seconds=15) if is_simulated else timedelta(minutes=5)
        
        if time_elapsed >= threshold:
            current_price = current_spot_prices.get(asset)
            if not current_price:
                continue
                
            # Determine actual outcome: Did it end ABOVE target_price?
            outcome = "YES" if current_price > target_price else "NO"
            
            # Resolve win/loss
            is_win = 0
            pnl = -wager_amount # Default is losing the wager amount
            
            if wager_platform == "ARBITRAGE":
                # Arbitrage is a guaranteed win if resolved
                is_win = 1
                # Arbitrage profit is calculated based on spreads (e.g. 5% profit)
                pnl = wager_amount * 0.05
            elif wager_direction == outcome and wager_direction != "NONE":
                is_win = 1
                # Winnings: return wager + profit based on entry odds
                # If odds were $0.60, payout is $1.00 per contract. Profit = wager * (1 - odds) / odds
                entry_odds = trade["pm_yes_odds"] if wager_platform == "Polymarket" else trade["ks_yes_odds"]
                if wager_direction == "NO":
                    entry_odds = 1.0 - entry_odds
                
                entry_odds = max(0.01, min(0.99, entry_odds))
                pnl = wager_amount * (1.0 - entry_odds) / entry_odds
            elif wager_direction == "NONE":
                is_win = -1 # No trade resolution
                pnl = 0.0
                
            # Update SQLite database row
            cursor.execute("""
                UPDATE predictions 
                SET resolved = 1, actual_expiry_price = ?, resolution_outcome = ?, is_win = ?, profit_loss = ?
                WHERE id = ?
            """, (current_price, outcome, is_win, pnl, trade_id))
            
            resolved_trades.append({
                "id": trade_id,
                "asset": asset,
                "wager_platform": wager_platform,
                "wager_direction": wager_direction,
                "wager_amount": wager_amount,
                "is_win": is_win,
                "profit_loss": pnl,
                "target_price": target_price,
                "expiry_price": current_price
            })
            
            logger.info(f"Resolved trade ID {trade_id} ({asset}): Price {current_price} vs Target {target_price}. Outcome: {outcome}. PnL: ${pnl:.2f}")
            
    conn.commit()
    conn.close()
    return resolved_trades

def get_feedback_stats() -> Dict[str, Any]:
    """Computes stats from the resolved prediction and trade history."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Win / Loss stats (exclude NONE wagers)
    cursor.execute("SELECT COUNT(*), SUM(is_win) FROM predictions WHERE resolved = 1 AND wager_direction != 'NONE'")
    total_wagers, total_wins = cursor.fetchone()
    total_wagers = total_wagers or 0
    total_wins = total_wins or 0
    
    win_rate = (total_wins / total_wagers) if total_wagers > 0 else 0.0
    
    # Profit & Loss
    cursor.execute("SELECT SUM(profit_loss) FROM predictions WHERE resolved = 1")
    total_pnl = cursor.fetchone()[0] or 0.0
    
    # Model breakdown
    cursor.execute("SELECT model_used, COUNT(*), SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) FROM predictions WHERE resolved = 1 AND wager_direction != 'NONE' GROUP BY model_used")
    model_stats = []
    for model, count, wins in cursor.fetchall():
        model_stats.append({
            "model": model,
            "total_trades": count,
            "wins": wins,
            "win_rate": wins / count if count > 0 else 0.0
        })
        
    # Get last 10 wagers for recent history
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT 10")
    recent_history = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "total_wagers": total_wagers,
        "total_wins": total_wins,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "model_stats": model_stats,
        "recent_history": recent_history
    }

def get_loop_feedback_prompt() -> str:
    """
    Generates a natural language performance summary of the feedback loop.
    This prompt is injected back into the Hermes Agent prediction loop to shape future decisions.
    """
    stats = get_feedback_stats()
    recent = stats["recent_history"]
    
    if stats["total_wagers"] == 0:
        return "System Feedback: No trading history recorded yet. Maintain conservative Kelly sizing (fraction = 0.5)."
        
    recent_resolved = [t for t in recent if t["resolved"] == 1 and t["wager_direction"] != "NONE"]
    if not recent_resolved:
        return f"System Feedback: Total PnL: ${stats['total_pnl']:.2f}. Pending trades in execution. Maintain risk controls."
        
    recent_wins = sum(1 for t in recent_resolved[:5] if t["is_win"] == 1)
    recent_total = len(recent_resolved[:5])
    recent_win_rate = recent_wins / recent_total if recent_total > 0 else 0.0
    
    feedback = f"System Feedback Loop:\n"
    feedback += f"- Lifetime Trading PnL: ${stats['total_pnl']:.2f}\n"
    feedback += f"- Lifetime Trade Count: {stats['total_wagers']} (Win Rate: {stats['win_rate']*100:.1f}%)\n"
    feedback += f"- Recent 5 Trades Win Rate: {recent_win_rate*100:.1f}%\n"
    
    # Self-improving adaptive risk sizing recommendation
    if recent_win_rate >= 0.8:
        feedback += "- Performance Alert: High accuracy. Suggest expanding the Kelly scaling fraction (e.g. increase fraction from 0.5 to 0.7) for higher capitalization."
    elif recent_win_rate <= 0.4:
        feedback += "- Performance Alert: Underperforming. Recommend tightening Kelly sizing (decrease fraction from 0.5 to 0.25) and checking prediction drift."
    else:
        feedback += "- Performance Alert: Steady state. Maintain current parameters."
        
    return feedback

if __name__ == "__main__":
    init_db()
    print("Feedback DB initialized.")
    print(get_loop_feedback_prompt())
