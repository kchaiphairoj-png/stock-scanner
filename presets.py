"""Preset ticker lists. Big static lists kept here to keep app.py readable."""

MAGNIFICENT_7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

DOW_30 = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
]

NASDAQ_100 = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN",
    "AMZN", "ANSS", "APP", "ARM", "ASML", "AVGO", "AXON", "AZN", "BIIB", "BKNG",
    "BKR", "CCEP", "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD",
    "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR", "DXCM", "EA",
    "EXC", "FANG", "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON",
    "IDXX", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU",
    "MAR", "MCHP", "MDB", "MDLZ", "MELI", "META", "MNST", "MRVL", "MSFT", "MSTR",
    "MU", "NFLX", "NVDA", "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR",
    "PDD", "PEP", "PLTR", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SNPS",
    "TEAM", "TMUS", "TSLA", "TTD", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY",
    "XEL", "ZS",
]

# US Mega-cap tech / AI / semis (high-interest names beyond N100)
AI_SEMI = [
    "NVDA", "AMD", "AVGO", "TSM", "ASML", "MU", "QCOM", "AMAT", "LRCX", "KLAC",
    "MRVL", "ARM", "INTC", "SMCI", "ANET", "CDNS", "SNPS", "ON", "MCHP", "PLTR",
    "CRWD", "PANW", "FTNT", "ZS", "NET", "DDOG", "MDB", "SNOW", "AI", "PATH",
]

# Thai SET50 (Yahoo uses .BK suffix). Adjust list as needed.
SET50 = [
    "ADVANC.BK", "AOT.BK", "AWC.BK", "BANPU.BK", "BBL.BK", "BCP.BK", "BDMS.BK",
    "BEM.BK", "BGRIM.BK", "BH.BK", "BTS.BK", "CBG.BK", "CENTEL.BK", "COM7.BK",
    "CPALL.BK", "CPF.BK", "CPN.BK", "CRC.BK", "DELTA.BK", "EA.BK", "EGCO.BK",
    "GLOBAL.BK", "GPSC.BK", "GULF.BK", "HMPRO.BK", "INTUCH.BK", "IVL.BK",
    "KBANK.BK", "KCE.BK", "KTB.BK", "KTC.BK", "LH.BK", "MINT.BK", "MTC.BK",
    "OR.BK", "OSP.BK", "PTT.BK", "PTTEP.BK", "PTTGC.BK", "RATCH.BK", "SAWAD.BK",
    "SCB.BK", "SCC.BK", "SCGP.BK", "TIDLOR.BK", "TISCO.BK", "TOP.BK", "TRUE.BK",
    "TTB.BK", "WHA.BK",
]

# S&P 500 — ดึงรายชื่อสดจาก GitHub-hosted CSV (เสถียรกว่า Wikipedia, ไม่ block UA)
def get_sp500() -> list[str]:
    import urllib.request
    sources = [
        # Primary: GitHub-maintained CSV ของ datasets community
        ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv", "csv"),
        # Fallback: Wikipedia (ส่ง UA จริงเพื่อเลี่ยง 403)
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "html"),
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for url, kind in sources:
        try:
            req = urllib.request.Request(url, headers=headers)
            text = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            if kind == "csv":
                lines = text.strip().split("\n")[1:]  # skip header
                symbols = [line.split(",")[0].strip() for line in lines]
            else:
                import pandas as pd
                from io import StringIO
                tables = pd.read_html(StringIO(text))
                symbols = tables[0]["Symbol"].astype(str).tolist()
            symbols = [s.replace(".", "-") for s in symbols if s]
            if len(symbols) >= 400:  # sanity check — S&P 500 มี ~500 ตัว
                return symbols
        except Exception as e:
            print(f"[warn] get_sp500 from {url[:50]}... failed: {e}")
    # Last resort
    print("[warn] all S&P 500 sources failed — falling back to Nasdaq 100 + Dow 30")
    return sorted(set(NASDAQ_100 + DOW_30))


PRESETS = {
    "Magnificent 7": MAGNIFICENT_7,
    "Dow 30": DOW_30,
    "Nasdaq 100": NASDAQ_100,
    "AI / Semiconductor": AI_SEMI,
    "S&P 500 (live from Wikipedia)": "sp500",  # special: ดึงตอนรัน
    "Thai SET50": SET50,
}
