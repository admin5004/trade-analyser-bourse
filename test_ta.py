import pandas as pd
import pandas_ta as ta
import numpy as np

try:
    df = pd.DataFrame({"close": np.random.randn(300)})
    df.ta.sma(length=20, append=True)
    print("Columns after SMA 20:", df.columns.tolist())
    if "SMA_20" in df.columns:
        print("SUCCESS: SMA_20 found")
    else:
        print("FAILURE: SMA_20 NOT found")
except Exception as e:
    print(f"CRASH: {e}")
