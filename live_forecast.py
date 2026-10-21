import sys
sys.path.insert(0, ".")
from test_btc_5min import fetch_candles, p_up
from model import Kronos, KronosTokenizer, KronosPredictor

df = fetch_candles(600)
tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
predictor = KronosPredictor(model, tok, device="cpu", max_context=512)
p = p_up(predictor, df, len(df), pred_len=1)
last = df.iloc[-1]
print(f"Latest BTC candle: {last['timestamps']} UTC, close ${last['close']:,.2f}")
print(f"Kronos next-5-min P(up) = {p:.2f}")
