import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def calculate_kelly_position(
    model_prob: float, 
    market_odds_yes: float, 
    bankroll: float, 
    kelly_fraction: float = 0.5
) -> Dict[str, Any]:
    """
    Computes the optimal Kelly Criterion sizing for a binary prediction contract.
    YES contract price is market_odds_yes (implies P_market).
    NO contract price is 1.0 - market_odds_yes.
    """
    p = model_prob
    m = market_odds_yes
    
    # Avoid division by zero
    m = max(0.01, min(0.99, m))
    
    # Kelly fraction calculations
    if p > m:
        # Edge on YES: we buy YES contracts
        # Kelly fraction: f* = (p - m) / (1 - m)
        raw_fraction = (p - m) / (1.0 - m)
        direction = "YES"
        odds_purchased = m
    elif p < m:
        # Edge on NO: we buy NO contracts (price is 1 - m, model probability is 1 - p)
        # Kelly fraction: f* = ((1 - p) - (1 - m)) / (1 - (1 - m)) = (m - p) / m
        raw_fraction = (m - p) / m
        direction = "NO"
        odds_purchased = round(1.0 - m, 4)
    else:
        raw_fraction = 0.0
        direction = "NONE"
        odds_purchased = 0.0
        
    # Apply fractional Kelly sizing (half-Kelly, etc.) and restrict bounds
    recommended_fraction = max(0.0, raw_fraction) * kelly_fraction
    recommended_fraction = min(0.25, recommended_fraction) # Max 25% allocation to prevent ruin
    
    wager_amount = recommended_fraction * bankroll
    
    return {
        "direction": direction,
        "raw_kelly_fraction": round(raw_fraction, 4),
        "recommended_fraction": round(recommended_fraction, 4),
        "wager_amount": round(wager_amount, 2),
        "entry_odds": odds_purchased
    }

def detect_arbitrage(polymarket: Dict[str, Any], kalshi: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks for risk-free arbitrage opportunities between Polymarket and Kalshi.
    Arbitrage exists if the YES price of one platform is lower than the YES price of the other,
    allowing us to buy YES on the cheaper and NO on the more expensive.
    """
    pm_yes = polymarket["yes_odds"]
    ks_yes = kalshi["yes_odds"]
    
    arb_detected = False
    details = ""
    profit_per_dollar = 0.0
    action = "NONE"
    
    if pm_yes < ks_yes:
        # Buy YES on Polymarket, Buy NO on Kalshi
        # Total cost for 1 YES + 1 NO contract: pm_yes + (1.0 - ks_yes) = 1.0 + pm_yes - ks_yes < 1.0
        cost = pm_yes + (1.0 - ks_yes)
        if cost < 0.99: # Include transaction fee buffers / threshold
            arb_detected = True
            profit_per_dollar = (1.0 - cost) / cost
            action = "BUY_YES_PM_BUY_NO_KS"
            details = f"Buy YES on Polymarket (${pm_yes:.2f}) and NO on Kalshi (${1.0-ks_yes:.2f}). Cost: ${cost:.2f}, Profit margin: {profit_per_dollar*100:.2f}%"
    elif ks_yes < pm_yes:
        # Buy YES on Kalshi, Buy NO on Polymarket
        cost = ks_yes + (1.0 - pm_yes)
        if cost < 0.99:
            arb_detected = True
            profit_per_dollar = (1.0 - cost) / cost
            action = "BUY_YES_KS_BUY_NO_PM"
            details = f"Buy YES on Kalshi (${ks_yes:.2f}) and NO on Polymarket (${1.0-pm_yes:.2f}). Cost: ${cost:.2f}, Profit margin: {profit_per_dollar*100:.2f}%"
            
    return {
        "arbitrage_detected": arb_detected,
        "action": action,
        "profit_margin": round(profit_per_dollar, 4),
        "details": details
    }

def evaluate_risk_and_wager(
    prediction: Dict[str, Any], 
    markets: Dict[str, Any], 
    bankroll: float, 
    kelly_fraction: float = 0.5
) -> Dict[str, Any]:
    """
    Integrates Kelly Criterion calculations and Arbitrage checking for an asset.
    """
    asset = prediction["symbol"]
    market_data = markets[asset]
    
    pm_market = market_data["polymarket"]
    ks_market = market_data["kalshi"]
    
    # 1. Kelly Position for Polymarket
    pm_kelly = calculate_kelly_position(prediction["probability_up"], pm_market["yes_odds"], bankroll, kelly_fraction)
    
    # 2. Kelly Position for Kalshi
    ks_kelly = calculate_kelly_position(prediction["probability_up"], ks_market["yes_odds"], bankroll, kelly_fraction)
    
    # 3. Arbitrage detection
    arb = detect_arbitrage(pm_market, ks_market)
    
    return {
        "asset": asset,
        "polymarket_kelly": pm_kelly,
        "kalshi_kelly": ks_kelly,
        "arbitrage": arb,
        "spot_price": market_data["spot_price"],
        "target_price": market_data["target_price"]
    }

if __name__ == "__main__":
    # Test execution
    pred = {"symbol": "BTC", "probability_up": 0.65}
    markets = {
        "BTC": {
            "spot_price": 95000.0,
            "target_price": 95010.0,
            "polymarket": {"yes_odds": 0.55, "no_odds": 0.45},
            "kalshi": {"yes_odds": 0.62, "no_odds": 0.38}
        }
    }
    risk = evaluate_risk_and_wager(pred, markets, 1000.0)
    import pprint
    pprint.pprint(risk)
