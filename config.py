# ─────────────────────────────────────────────────────────────
#  config.py  –  Central configuration for the news-monitor system
# ─────────────────────────────────────────────────────────────

# ── RSS News Sources ──────────────────────────────────────────
NEWS_FEEDS = {
    "Economic Times Markets":   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Economic Times Stocks":    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "Moneycontrol Markets":     "https://www.moneycontrol.com/rss/marketreports.xml",
    "Moneycontrol Business":    "https://www.moneycontrol.com/rss/business.xml",
    "Business Standard Markets":"https://www.business-standard.com/rss/markets-106.rss",
    "Business Standard Economy":"https://www.business-standard.com/rss/economy-policy-102.rss",
    "Mint Markets":             "https://www.livemint.com/rss/markets",
    "Financial Express":        "https://www.financialexpress.com/market/feed/",
    "Reuters Business":         "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Markets":          "https://feeds.reuters.com/reuters/UKmarkets",
    "CNBC Markets":             "https://www.cnbc.com/id/20910258/device/rss/rss.html",
}

# ── Impact Thresholds ─────────────────────────────────────────
IMPACT_THRESHOLDS = {
    "EXTREME": 0.8,
    "HIGH":    0.6,
    "MEDIUM":  0.35,
    "LOW":     0.1,
}

# ── Underreaction Detection Parameters ───────────────────────
UNDERREACTION = {
    "min_expected_move_pct": 3.0,   # News warrants ≥3% move
    "max_actual_move_pct":   1.5,   # But stock moved <1.5%
    "volume_threshold":      1.3,   # Volume ratio below 1.3x avg
}

# ── Signal Engine Parameters ──────────────────────────────────
RISK_REWARD_MIN = 1.5       # Minimum R:R to generate a signal
CONFIDENCE_FLOOR = 40       # Minimum confidence score (0-100)

# ── Stock Universe: NSE Symbols → metadata ────────────────────
# Format: "NSE_SYMBOL": {"name": "...", "sector": "...", "keywords": [...]}
STOCK_UNIVERSE = {
    # Banking & Finance
    "HDFCBANK":  {"name": "HDFC Bank",         "sector": "Banking",        "keywords": ["hdfc bank", "hdfcbank", "hdfc"]},
    "ICICIBANK": {"name": "ICICI Bank",         "sector": "Banking",        "keywords": ["icici bank", "icicibank", "icici"]},
    "SBIN":      {"name": "State Bank of India","sector": "Banking",        "keywords": ["sbi", "state bank", "sbin", "state bank of india"]},
    "KOTAKBANK": {"name": "Kotak Mahindra Bank","sector": "Banking",        "keywords": ["kotak", "kotak bank", "kotak mahindra"]},
    "AXISBANK":  {"name": "Axis Bank",          "sector": "Banking",        "keywords": ["axis bank", "axisbank"]},
    "INDUSINDBK":{"name": "IndusInd Bank",      "sector": "Banking",        "keywords": ["indusind", "indusind bank"]},
    "BAJFINANCE":{"name": "Bajaj Finance",      "sector": "NBFC",           "keywords": ["bajaj finance", "bajajfinance"]},
    "BAJAJFINSV":{"name": "Bajaj Finserv",      "sector": "NBFC",           "keywords": ["bajaj finserv", "bajajfinserv"]},
    "HDFCLIFE":  {"name": "HDFC Life",          "sector": "Insurance",      "keywords": ["hdfc life", "hdfclife"]},
    "SBILIFE":   {"name": "SBI Life",           "sector": "Insurance",      "keywords": ["sbi life", "sbilife"]},
    "ICICIGI":   {"name": "ICICI Lombard",      "sector": "Insurance",      "keywords": ["icici lombard", "icicigi"]},

    # IT / Technology
    "TCS":       {"name": "TCS",                "sector": "IT",             "keywords": ["tcs", "tata consultancy", "tata consultancy services"]},
    "INFY":      {"name": "Infosys",            "sector": "IT",             "keywords": ["infosys", "infy"]},
    "WIPRO":     {"name": "Wipro",              "sector": "IT",             "keywords": ["wipro"]},
    "HCLTECH":   {"name": "HCL Technologies",   "sector": "IT",             "keywords": ["hcl tech", "hcltech", "hcl technologies"]},
    "TECHM":     {"name": "Tech Mahindra",      "sector": "IT",             "keywords": ["tech mahindra", "techm"]},
    "LTIM":      {"name": "LTIMindtree",        "sector": "IT",             "keywords": ["ltimindtree", "ltim", "mindtree"]},
    "MPHASIS":   {"name": "Mphasis",            "sector": "IT",             "keywords": ["mphasis"]},
    "PERSISTENT":{"name": "Persistent Systems", "sector": "IT",             "keywords": ["persistent", "persistent systems"]},

    # Pharmaceuticals
    "SUNPHARMA": {"name": "Sun Pharma",         "sector": "Pharma",         "keywords": ["sun pharma", "sunpharma", "sun pharmaceutical"]},
    "DRREDDY":   {"name": "Dr. Reddy's",        "sector": "Pharma",         "keywords": ["dr reddy", "drreddy", "dr. reddy"]},
    "CIPLA":     {"name": "Cipla",              "sector": "Pharma",         "keywords": ["cipla"]},
    "DIVISLAB":  {"name": "Divi's Laboratories","sector": "Pharma",         "keywords": ["divis", "divi's", "divislab"]},
    "APOLLOHOSP":{"name": "Apollo Hospitals",   "sector": "Healthcare",     "keywords": ["apollo hospital", "apollohosp"]},

    # Energy / Oil & Gas
    "RELIANCE":  {"name": "Reliance Industries","sector": "Energy/Conglomerate","keywords": ["reliance", "ril", "reliance industries", "jio", "mukesh ambani"]},
    "ONGC":      {"name": "ONGC",               "sector": "Oil & Gas",      "keywords": ["ongc", "oil and natural gas"]},
    "BPCL":      {"name": "BPCL",               "sector": "Oil & Gas",      "keywords": ["bpcl", "bharat petroleum"]},
    "IOC":       {"name": "Indian Oil",         "sector": "Oil & Gas",      "keywords": ["ioc", "indian oil", "indianoil"]},
    "NTPC":      {"name": "NTPC",               "sector": "Power",          "keywords": ["ntpc", "national thermal power"]},
    "POWERGRID": {"name": "Power Grid",         "sector": "Power",          "keywords": ["power grid", "powergrid"]},
    "ADANIPOWER":{"name": "Adani Power",        "sector": "Power",          "keywords": ["adani power", "adanipower"]},
    "ADANIENT":  {"name": "Adani Enterprises",  "sector": "Conglomerate",   "keywords": ["adani", "adani enterprises", "gautam adani"]},
    "ADANIPORTS":{"name": "Adani Ports",        "sector": "Infrastructure", "keywords": ["adani ports", "adaniports"]},

    # Automobile
    "MARUTI":    {"name": "Maruti Suzuki",      "sector": "Automobile",     "keywords": ["maruti", "maruti suzuki", "suzuki"]},
    "TATAMOTORS":{"name": "Tata Motors",        "sector": "Automobile",     "keywords": ["tata motors", "tatamotors", "jaguar", "jlr"]},
    "M&M":       {"name": "Mahindra & Mahindra","sector": "Automobile",     "keywords": ["mahindra", "m&m", "mahindra mahindra"]},
    "BAJAJ-AUTO":{"name": "Bajaj Auto",         "sector": "Automobile",     "keywords": ["bajaj auto", "bajaj-auto"]},
    "HEROMOTOCO":{"name": "Hero MotoCorp",      "sector": "Automobile",     "keywords": ["hero moto", "hero motocorp", "heromotoco"]},
    "EICHERMOT": {"name": "Eicher Motors",      "sector": "Automobile",     "keywords": ["eicher", "royal enfield", "eichermot"]},

    # Metals & Mining
    "TATASTEEL": {"name": "Tata Steel",         "sector": "Metals",         "keywords": ["tata steel", "tatasteel"]},
    "JSWSTEEL":  {"name": "JSW Steel",          "sector": "Metals",         "keywords": ["jsw steel", "jswsteel"]},
    "HINDALCO":  {"name": "Hindalco",           "sector": "Metals",         "keywords": ["hindalco", "novelis"]},
    "VEDL":      {"name": "Vedanta",            "sector": "Metals/Mining",  "keywords": ["vedanta", "vedl", "vedanta resources"]},
    "COALINDIA": {"name": "Coal India",         "sector": "Mining",         "keywords": ["coal india", "coalindia"]},

    # Consumer / FMCG
    "HINDUNILVR":{"name": "Hindustan Unilever", "sector": "FMCG",           "keywords": ["hul", "hindustan unilever", "hindunilvr", "unilever india"]},
    "ITC":       {"name": "ITC",                "sector": "FMCG/Conglomerate","keywords": ["itc"]},
    "NESTLEIND": {"name": "Nestle India",       "sector": "FMCG",           "keywords": ["nestle", "nestleind", "nestle india"]},
    "BRITANNIA": {"name": "Britannia",          "sector": "FMCG",           "keywords": ["britannia"]},
    "DABUR":     {"name": "Dabur",              "sector": "FMCG",           "keywords": ["dabur"]},
    "MARICO":    {"name": "Marico",             "sector": "FMCG",           "keywords": ["marico", "parachute"]},

    # Infrastructure / Real Estate
    "LT":        {"name": "L&T",               "sector": "Infrastructure", "keywords": ["l&t", "larsen", "larsen and toubro", "larsen & toubro"]},
    "DLF":       {"name": "DLF",               "sector": "Real Estate",    "keywords": ["dlf", "dlf limited"]},
    "GODREJPROP":{"name": "Godrej Properties", "sector": "Real Estate",    "keywords": ["godrej properties", "godrejprop"]},

    # Telecom
    "BHARTIARTL":{"name": "Bharti Airtel",     "sector": "Telecom",        "keywords": ["airtel", "bharti airtel", "bhartiartl"]},
    "IDEA":      {"name": "Vodafone Idea",     "sector": "Telecom",        "keywords": ["vodafone idea", "vi ", "idea cellular"]},

    # Global Majors (for correlation)
    "AAPL":      {"name": "Apple",             "sector": "Tech (US)",      "keywords": ["apple", "aapl", "iphone", "tim cook"]},
    "MSFT":      {"name": "Microsoft",         "sector": "Tech (US)",      "keywords": ["microsoft", "msft", "azure", "satya nadella"]},
    "NVDA":      {"name": "NVIDIA",            "sector": "Tech (US)",      "keywords": ["nvidia", "nvda", "gpu", "jensen huang"]},
    "AMZN":      {"name": "Amazon",            "sector": "Tech (US)",      "keywords": ["amazon", "amzn", "aws", "jeff bezos"]},
    "GOOGL":     {"name": "Alphabet/Google",   "sector": "Tech (US)",      "keywords": ["google", "alphabet", "googl", "gemini ai"]},
}

# ── Sector → Stocks mapping (for indirect impact) ─────────────
SECTOR_STOCKS = {}
for sym, meta in STOCK_UNIVERSE.items():
    sec = meta["sector"]
    SECTOR_STOCKS.setdefault(sec, []).append(sym)

# ── Macro Keywords → Sector Impact Map ────────────────────────
MACRO_SECTOR_MAP = {
    "interest rate":    ["Banking", "NBFC", "Real Estate", "Insurance"],
    "repo rate":        ["Banking", "NBFC", "Real Estate"],
    "inflation":        ["FMCG", "Banking", "Automobile"],
    "crude oil":        ["Oil & Gas", "Automobile", "Airlines", "Chemicals"],
    "rupee":            ["IT", "Pharma", "Oil & Gas"],
    "rbi":              ["Banking", "NBFC", "Insurance"],
    "sebi":             ["Banking", "NBFC"],
    "gdp":              ["Banking", "Infrastructure", "Automobile"],
    "iip":              ["Metals", "Infrastructure", "Power"],
    "fii":              ["Banking", "IT", "Metals"],
    "dii":              ["Banking", "IT", "FMCG"],
    "us fed":           ["IT", "Banking", "Metals"],
    "federal reserve":  ["IT", "Banking", "Metals"],
    "china":            ["Metals", "Pharma", "Chemicals"],
    "monsoon":          ["FMCG", "Agriculture", "Automobile"],
    "budget":           ["Banking", "Infrastructure", "FMCG", "Automobile"],
    "gst":              ["FMCG", "Automobile", "Real Estate"],
    "semiconductor":    ["IT", "Tech (US)", "Automobile"],
    "ai":               ["IT", "Tech (US)"],
    "tariff":           ["Metals", "IT", "Automobile", "Pharma"],
    "earnings":         [],  # handled separately
}

# ── Category Detection Keywords ───────────────────────────────
CATEGORY_KEYWORDS = {
    "Earnings":    ["q1", "q2", "q3", "q4", "quarterly", "results", "profit", "revenue", "earnings", "net profit", "ebitda", "pat"],
    "Macro":       ["rbi", "fed", "gdp", "inflation", "repo rate", "interest rate", "cpi", "iip", "fiscal", "monetary policy"],
    "Geopolitical":["war", "conflict", "sanction", "tension", "geopolitical", "ukraine", "russia", "china", "taiwan", "middle east"],
    "Sector":      ["sector", "industry", "auto sales", "pmi", "capacity", "output", "production"],
    "Company":     ["acquisition", "merger", "buyback", "dividend", "deal", "contract", "order", "launch", "ipo", "stake"],
    "Regulatory":  ["sebi", "cci", "penalty", "fine", "nclat", "court", "regulatory", "ban", "approval", "licence"],
}

# ── Historical Reaction Patterns (avg % move per event type) ──
HISTORICAL_REACTIONS = {
    ("Earnings", "Positive", "HIGH"):   +6.5,
    ("Earnings", "Positive", "MEDIUM"): +3.2,
    ("Earnings", "Negative", "HIGH"):   -7.0,
    ("Earnings", "Negative", "MEDIUM"): -3.5,
    ("Macro",    "Positive", "HIGH"):   +2.5,
    ("Macro",    "Negative", "HIGH"):   -2.8,
    ("Company",  "Positive", "HIGH"):   +5.0,
    ("Company",  "Negative", "HIGH"):   -5.5,
    ("Regulatory","Negative","HIGH"):   -4.5,
    ("Regulatory","Positive","HIGH"):   +3.0,
    ("Geopolitical","Negative","EXTREME"): -3.5,
    ("Sector",   "Positive", "MEDIUM"): +2.0,
}
