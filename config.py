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

OANDA_API_KEY = "YOUR_OANDA_API_KEY"
OANDA_ACCOUNT_ID = "YOUR_OANDA_ACCOUNT_ID"
OANDA_INSTRUMENT = "GBP_USD"
OANDA_GRANULARITY = "H1"

GAS_WEBHOOK_URL = "https://script.google.com/macros/s/YOUR_WEB_APP_URL/exec"