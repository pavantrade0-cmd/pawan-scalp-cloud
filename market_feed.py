import yfinance as yf
import pandas as pd

class MarketFeed:
    @staticmethod
    def get_latest_candles(symbol: str = "^NSEI", timeframe: str = "5m") -> pd.DataFrame:
        try:
            # yf.download is 3x faster than Ticker().history()
            df = yf.download(
                tickers=symbol,
                period="3d",       # 3 days is enough for 5m indicators and loads instantly
                interval=timeframe,
                progress=False,
                auto_adjust=True
            )
            
            if df.empty:
                return pd.DataFrame()

            # Flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume"
            })
            return df[['open', 'high', 'low', 'close', 'volume']].dropna()
        except Exception as e:
            print(f"[DATA FEED ERROR]: {e}")
            return pd.DataFrame()