import pandas as pd
from .base import Signal, SignalResult
from ..config import high_beta, low_beta, small_cap_threshold, large_cap_threshold


class MomentumSignal(Signal):

    name = "momentum"

    def __init__(self, beta = None, market_cap = None):
        # beta and market_cap are optional. If not provided, all thresholds fall back
        # to standard market-beta defaults so the signal still works without fundamentals.
        self.beta = beta
        self.market_cap = market_cap

    def thresholds(self):
        '''Derive indicator parameters scaled to the stock's volatility and size profile'''

        beta = self.beta
        mc = self.market_cap

        # The rsi limits for overbought and oversold and adjusted based on beta. A high beta stop regularly
        # crosses rsi 70, so will always flag as overbought. So we use wider bands. Similar for low beta stocks
        if beta is None or beta < 1.5:
            rsi_ob, rsi_os = 70, 30       # standard market-beta stock
        else:
            rsi_ob, rsi_os = 78, 22       # high-beta: wider bands

        # Standard MACD uses 12-day and 26-day EMAs. For a high-beta stock the price swings
        # so fast, therefore we use shorter windows (8/17) to reduce that lag and give a more
        # accurate picture of acceleration/deceleration.
        macd_fast, macd_slow = (8, 17) if (beta is not None and beta > high_beta) else (12, 26)

        # For a small cap, a 50-day EMA lags so much that by the time it signals a crossover,
        # most of the move is already over. Shorter periods (10/30) sacrifice some smoothness to
        # catch the signal while there's still room to act.
        ema_fast, ema_slow = (10, 30) if (mc is not None and mc < small_cap_threshold) else (20, 50)

        # Relative volume = today's volume / 20-day average volume.
        if mc is None or mc >= large_cap_threshold:
            vol_threshold = 1.3           # large cap: 30% above average is significant
        elif mc < small_cap_threshold:
            vol_threshold = 1.8           # small cap: need 80% above average to matter
        else:
            vol_threshold = 1.5           # mid cap: middle ground

        return {
            "rsi_ob":        rsi_ob,
            "rsi_os":        rsi_os,
            "macd_fast":     macd_fast,
            "macd_slow":     macd_slow,
            "ema_fast":      ema_fast,
            "ema_slow":      ema_slow,
            "vol_threshold": vol_threshold,
        }

    def get_ema(self, df, span, source):
        '''Calculate the exponential moving average of a series.
        EMA gives more weight to recent values than older ones, making it more
        responsive to new price action than a simple moving average'''

        values = df[source].tolist()

        # k is the smoothing factor. Shorter span reacts faster to price changes.
        k = 2 / (span + 1)

        ema_values = [values[0]]

        for i in range(1, len(values)):
            # Each new EMA is a blend: today's price weighted by k, yesterday's EMA weighted
            # by (1-k). This creates an exponential decay where older prices contribute less
            # and less to the current value.
            ema_values.append(values[i] * k + ema_values[i - 1] * (1 - k))

        return pd.Series(ema_values, index=df.index)

    def get_rsi(self, df, span=14):
        '''Calculate relative strength index: Measures whether recent price action is
        dominated by profits or losses. Output is 0-100. Above 70 = overbought (too many
        gains, likely to revert), below 30 = oversold (too many losses, likely to bounce).'''

        # delta is the difference between two consecutive closing prices.
        # .diff() gives [NaN, close2-close1, close3-close2, ...]
        delta = df["Close"].diff()

        # gains: series of up-day moves, with 0 replacing any down-day.
        # .clip(lower=0) sets all negative values to 0.
        gains = delta.clip(lower=0)

        # losses: series of down-day moves as positive numbers, with 0 on up-days.
        losses = -delta.clip(upper=0)

        # Wilder's smoothing: a specific type of EMA with alpha = 1/span.
        # min_periods=span means the first valid average only appears after "span" bars,
        # preventing unreliable early readings from a small sample.
        avg_gain = gains.ewm(alpha=1 / span, min_periods=span).mean()
        avg_loss = losses.ewm(alpha=1 / span, min_periods=span).mean()

        # RS = ratio of average gains to average losses.
        # RS=3 means gains are 3x larger than losses on average over the window — bullish.
        rs = avg_gain / avg_loss

        # Scale RS to a 0-100 range. When RS is large (many gains),  RSI approaches 100.
        # When RS is near 0 (many losses), RSI approaches 0.
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def get_macd(self, df, fast, slow, signal=9):
        '''Calculate the MACD line, signal line, and histogram.
        MACD captures momentum by comparing a fast EMA to a slow EMA.
        When price rises quickly, the fast EMA pulls ahead of the slow one, the gap
        (MACD line) widens. When momentum stalls, the gap shrinks.'''

        ema_fast = self.get_ema(df, fast, "Close")
        ema_slow = self.get_ema(df, slow, "Close")

        # MACD line = fast EMA minus slow EMA.
        # Positive = fast EMA is above slow EMA = upward momentum.
        # Negative = fast EMA is below slow EMA = downward momentum.
        macd_line = ema_fast - ema_slow

        # Signal line = EMA of the MACD line itself (smoothed version of the MACD).
        # It lags the MACD line slightly, acting as a reference for crossovers.
        macd_df = pd.DataFrame({"Close": macd_line})
        signal_line = self.get_ema(macd_df, signal, "Close")

        # Histogram = MACD line minus signal line.
        # Positive and growing: momentum is accelerating upward.
        # Positive but shrinking: momentum is still up but starting to fade.
        # Negative and growing (more negative): momentum is accelerating downward.
        # Negative but shrinking: downward momentum is easing.
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def evaluate(self, data):
        df = data.copy()
        t = self.thresholds()

        df["ema_fast"] = self.get_ema(df, t["ema_fast"], "Close")
        df["ema_slow"] = self.get_ema(df, t["ema_slow"], "Close")
        df["rsi"] = self.get_rsi(df)
        macd_line, signal_line, histogram = self.get_macd(df, fast=t["macd_fast"],
                                                          slow=t["macd_slow"])

        # Snapshot of the most recent bar, which scores are based on
        close_latest    = df.iloc[-1]["Close"]
        ema_fast_latest = df.iloc[-1]["ema_fast"]
        ema_slow_latest = df.iloc[-1]["ema_slow"]
        rsi_latest      = df.iloc[-1]["rsi"]
        hist_latest     = histogram.iloc[-1]
        hist_prev       = histogram.iloc[-2]   # one bar ago, used to detect histogram direction

        # in_uptrend: price is above both EMAs AND the fast EMA is above the slow EMA —
        # meaning both short-term and medium-term momentum are pointing up.
        in_uptrend   = close_latest > ema_fast_latest > ema_slow_latest
        in_downtrend = close_latest < ema_fast_latest < ema_slow_latest

        # A boolean series: True on bars where ema_fast is above ema_slow.
        ema_cross_above = df["ema_fast"] > df["ema_slow"]

        # Golden cross: fast EMA just crossed above slow EMA within the last 5 bars.
        # Condition: currently above (iloc[-1] is True) but was NOT above 5 bars ago (iloc[-6]).
        # A golden cross signals that short-term momentum has just overtaken the medium-term
        # trend — the earliest stage of a new uptrend, before it becomes stale.
        recent_golden_cross = bool(ema_cross_above.iloc[-1] and not ema_cross_above.iloc[-6])

        # Death cross: fast EMA just crossed below slow EMA within the last 5 bars.
        recent_death_cross  = bool(not ema_cross_above.iloc[-1] and ema_cross_above.iloc[-6])

        # --- Relative volume ---
        # Compare today's volume to the 20-day average, excluding today so today's bar
        # doesn't inflate its own benchmark (e.g. a 5x volume day would raise the average
        # and make itself look less extreme than it is).
        avg_volume_20 = df["Volume"].iloc[-21:-1].mean()
        rel_volume    = df["Volume"].iloc[-1] / avg_volume_20 if avg_volume_20 > 0 else 1.0

        # High volume means the price move has broad participation — institutions are involved.
        # Low volume moves are easier to fade because they lack the buying/selling pressure
        # needed to sustain a directional move.
        high_volume = rel_volume >= t["vol_threshold"]

        # --- MACD histogram direction ---
        # Whether the histogram is growing or shrinking tells us if momentum is accelerating
        # or decelerating — more useful than just the sign alone.
        # hist_latest > hist_prev means the gap between MACD and signal is widening: accelerating.
        # hist_latest < hist_prev means the gap is narrowing: momentum is fading.
        hist_expanding = hist_latest > hist_prev

        score = 0.0

        # --- Trend scoring (±0.40) ---
        # EMA alignment is the primary filter. A fresh crossover gets a small bonus because
        # it marks the beginning of a trend, which tends to have the strongest momentum.
        if in_uptrend:
            score += 0.35
            if recent_golden_cross:
                score += 0.05
        elif in_downtrend:
            score -= 0.35
            if recent_death_cross:
                score -= 0.05

        # --- MACD scoring (±0.30) ---
        # We reward/penalise based on both sign AND direction.
        # Positive + expanding: momentum is building upward — full score.
        # Positive + contracting: upward move is losing steam — reduced score (warning sign).
        # Negative + still expanding downward (not contracting): momentum building downward — full penalty.
        # Negative + contracting: selling pressure is easing — reduced penalty.
        if hist_latest > 0:
            score += 0.30 if hist_expanding else 0.10
        else:
            score -= 0.30 if not hist_expanding else 0.10

        # --- RSI scoring (±0.20) ---
        # Oversold (RSI <= rsi_os) only scores positively in an uptrend. In a downtrend,
        # oversold just means the stock has been falling hard — buying it is catching a falling
        # knife. The uptrend condition ensures there's structural support for a bounce.
        if rsi_latest >= t["rsi_ob"]:
            score -= 0.20                              # overbought: likely to mean-revert down
        elif rsi_latest <= t["rsi_os"]:
            score += 0.15 if in_uptrend else 0.0      # oversold bounce only valid in uptrend
        elif rsi_latest > 50:
            score += 0.15                              # bullish momentum zone: gains dominating
        else:
            score -= 0.15                              # bearish momentum zone: losses dominating

        # --- Volume scoring (±0.10) ---
        # Volume only adjusts the score when we have a clear trend direction. High volume
        # on a mixed signal (price between EMAs) doesn't tell us much — direction matters.
        if high_volume:
            if in_uptrend:
                score += 0.10
            elif in_downtrend:
                score -= 0.10

        # Clamp to [-1, 1] as required by the Signal contract
        score = self.clamp(score)

        values = {
            "close":               round(close_latest, 2),
            "ema_fast":            round(ema_fast_latest, 2),
            "ema_slow":            round(ema_slow_latest, 2),
            "rsi":                 round(rsi_latest, 2),
            "rsi_ob_threshold":    t["rsi_ob"],
            "rsi_os_threshold":    t["rsi_os"],
            "macd_histogram":      round(hist_latest, 4),
            "macd_hist_expanding": hist_expanding,
            "recent_golden_cross": recent_golden_cross,
            "recent_death_cross":  recent_death_cross,
            "rel_volume":          round(rel_volume, 2),
            "vol_threshold":       t["vol_threshold"],
        }

        trend_str = "uptrend" if in_uptrend else ("downtrend" if in_downtrend else "mixed")
        note = (
            f"RSI {round(rsi_latest, 1)} (ob={t['rsi_ob']}/os={t['rsi_os']}), "
            f"MACD histogram {round(hist_latest, 3)} ({'expanding' if hist_expanding else 'contracting'}), "
            f"trend {trend_str}, rel vol {round(rel_volume, 2)}x (threshold {t['vol_threshold']}x)"
        )

        return SignalResult(name=self.name, score=score, values=values, note=note)
