import pandas as pd
from base import Signal, SignalResult


class VolumeSignal(Signal):

    name = "volume"

    def __init__(self, market_cap=None):
        # market_cap is optional. Without it, the volume spike threshold falls back to a
        # large-cap default. Providing it lets the signal scale the threshold to the stock's
        # liquidity profile — a 1.5x spike means different things for Apple vs a $500M micro-cap.
        self.market_cap = market_cap

    def _rel_volume_threshold(self):
        '''Return the relative-volume threshold for a "significant" spike.

        Relative volume = today's volume / 20-day average volume. The threshold for calling
        a spike "significant" depends on how much daily noise the stock normally has.

        For a mega-cap like Apple (50M+ shares/day), 1.3x means roughly 15M extra shares
        traded — that's real institutional conviction. For a $500M small-cap, 1.3x might
        just be one fund rebalancing a position. We set a higher bar for small caps to avoid
        treating ordinary daily noise as a meaningful volume confirmation.
        '''
        mc = self.market_cap
        if mc is None or mc >= 10e9:
            return 1.3    # large cap: 30% above average is significant
        elif mc < 2e9:
            return 1.8    # small cap: need 80% above average to matter
        else:
            return 1.5    # mid cap: middle ground

    def _get_obv(self, df):
        '''Calculate on-balance volume (OBV).

        OBV is a running total of volume that adds volume on up-days and subtracts it on
        down-days. The idea is that volume precedes price: when buyers are aggressive enough
        to push price up on high volume, they are willing to pay up — a bullish sign. When
        price falls on high volume, sellers are motivated — bearish.

        The absolute OBV level is meaningless on its own (it depends on the starting bar).
        What matters is the direction of the OBV line: is it trending up (money flowing in)
        or down (money flowing out)?
        '''
        close  = df["Close"].tolist()
        volume = df["Volume"].tolist()

        obv_values = [0]

        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv_values.append(obv_values[i - 1] + volume[i])
            elif close[i] < close[i - 1]:
                obv_values.append(obv_values[i - 1] - volume[i])
            else:
                # Unchanged close — volume is neutral, neither added nor subtracted
                obv_values.append(obv_values[i - 1])

        return pd.Series(obv_values, index=df.index)

    def evaluate(self, data):

        df  = data.copy()
        vol_threshold = self._rel_volume_threshold()

        df["obv"] = self._get_obv(df)

        # Exclude today from the average so a spike day doesn't inflate its own benchmark.
        # A 5x volume day would raise the 20-day average and make itself look less extreme.
        avg_volume    = df["Volume"].iloc[-21:-1].mean()
        volume_latest = df.iloc[-1]["Volume"]
        rel_volume    = volume_latest / avg_volume if avg_volume > 0 else 1.0

        # OBV trend over 20 days: compare the latest OBV value to where it was 20 bars ago.
        # Rising OBV means volume has been flowing into up-days more than down-days —
        # institutional accumulation. Falling OBV means distribution is dominating.
        obv_latest = df.iloc[-1]["obv"]
        obv_past   = df["obv"].iloc[-20]
        obv_rising = obv_latest > obv_past

        score = 0.0

        # OBV direction is the primary piece — it captures sustained buying/selling pressure
        # over 20 days, not just today's number.
        if obv_rising:
            score += 0.5
        else:
            score -= 0.5

        # High relative volume adds conviction to the OBV direction. A strong volume spike
        # on an OBV uptrend means institutions are actively buying, not just drifting higher
        # on thin volume. The same spike on an OBV downtrend intensifies the distribution signal.
        if rel_volume >= vol_threshold:
            if obv_rising:
                score += 0.3
            else:
                score -= 0.3

        score = self.clamp(score)

        values = {
            "volume_latest":    int(volume_latest),
            "avg_volume_20d":   int(avg_volume),
            "rel_volume":       round(rel_volume, 2),
            "vol_threshold":    vol_threshold,
            "obv_rising":       obv_rising,
            "obv_latest":       int(obv_latest),
            "obv_20d_ago":      int(obv_past),
        }

        note = (
            f"OBV {'rising' if obv_rising else 'falling'} over 20 days, "
            f"rel volume {round(rel_volume, 2)}x (threshold {vol_threshold}x)"
        )

        return SignalResult(name=self.name, score=score, values=values, note=note)
