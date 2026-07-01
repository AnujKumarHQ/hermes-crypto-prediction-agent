import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")

# Risk Management
BANKROLL = float(os.getenv("BANKROLL", "1000.0"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.5"))

# Execution
TRADING_LOOP_INTERVAL = int(os.getenv("TRADING_LOOP_INTERVAL", "15"))

# LLM Config
# Default to a free model on OpenRouter
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "google/gemini-2.5-flash") # Or "meta-llama/llama-3-8b-instruct:free"

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

def is_ready():
    """Checks if the minimum configuration is met for live trading, otherwise uses fallbacks."""
    return bool(OPENROUTER_API_KEY)
