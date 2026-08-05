# config.py

PARAMS = {
    "swingLen": 5,
    "rsiLen": 14,
    "atrLen": 14,
    "atrMult": 2.17,
    "consBuf": 1.0,
    "lrDevMult": 1.9,
    "lrMinR": 0.70,
    "lrMinLen": 20,
    "lrMaxLen": 500,
    "lrGrace": 12,
    "lrBandTol": 1.0,
    "srPrd": 10,
    "srChannelW": 5,
    "srMinStrength": 1,
    "srMaxNum": 6,
    "srLoopback": 290,
    "riskMultiplier": 1.5,
}

OANDA_API_KEY = "6e08cf1005e4acba3bbbbab1c8b6da07-c330b49378d0e7bd6c636604ef622cf9"
OANDA_ACCOUNT_ID = "101-003-39782402-001"
GAS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzMGfJzI9pMQI7PEOw8R7W7exZscqJkXzd0DqWHS1TH8My5HJipRl8kJSb1E-RGn2CtGQ/exec"
OANDA_API_URL = "https://api-fxpractice.oanda.com"   # Demo endpoint
OANDA_INSTRUMENT = "GBP_USD"
OANDA_GRANULARITY = "H1"

# DXY symbol (US Dollar Index)
OANDA_DXY_INSTRUMENT = "USD_INDEX"

# ─── MULTI-INSTRUMENT CONFIG ──────────────────────────────────────────────────
INSTRUMENTS = [
    {
        "name": "GBP_USD",
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
    {
        "name": "GBP_JPY",
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
    {
        "name": "XAU_USD",
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
    {
        "name": "NZD_USD",
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
    {
        "name": "EUR_USD",
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
    {
        "name": "USD_JPY",  # ✅ ADDED
        "granularity": "H1",
        "webhook": GAS_WEBHOOK_URL
    },
]