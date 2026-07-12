# config.py

PARAMS = {
    # Core
    "swingLen": 5,
    "rsiLen": 14,
    "atrLen": 14,
    "atrMult": 2.17,
    "consBuf": 1.0,

    # LR Channel
    "lrDevMult": 1.9,
    "lrMinR": 0.70,
    "lrMinLen": 20,
    "lrMaxLen": 500,
    "lrGrace": 12,
    "lrBandTol": 1.0,

    # Daily S/R (simplified but functional)
    "srPrd": 10,
    "srChannelW": 5,
    "srMinStrength": 1,
    "srMaxNum": 6,
    "srLoopback": 290,

    # Risk
    "riskMultiplier": 1.5,
}

# OANDA – replace with your actual demo credentials
OANDA_API_KEY = "YOUR_OANDA_API_KEY"
OANDA_ACCOUNT_ID = "YOUR_OANDA_ACCOUNT_ID"
OANDA_INSTRUMENT = "GBP_USD"   # OANDA format
OANDA_GRANULARITY = "H1"       # 1-hour

# Your Google Apps Script Webhook URL
GAS_WEBHOOK_URL = "https://script.google.com/macros/s/YOUR_WEB_APP_URL/exec"