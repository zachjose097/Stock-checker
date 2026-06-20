from .base import Signal, SignalResult


class TargetsSignal(Signal):

    name = "targets"

    def evaluate(self, data):
        '''Score the stock based on the gap between analyst price targets and current price.

        Analyst price targets represent the 12-month consensus view of sell-side analysts.
        A wide positive gap between the mean target and the current price signals that the
        market is trading below where analysts think fair value sits — either the market
        will catch up, or analysts will revise down. Both cases resolve over time.

        Upside thresholds: 30%+ is the conventional "strong buy" zone (analysts expect a
        significant re-rating). 15-30% is "buy". 0-15% is marginally bullish. Below zero
        means the stock is already above consensus — analysts expect it to fall.

        Conviction adjustment: the spread between high and low targets measures how much
        analysts agree with each other. A tight cluster around the mean is more reliable
        than a wide spread where analysts hold fundamentally different views of the business.
        Wide disagreement (spread > 40% of price) discounts the signal — the mean is less
        meaningful when it averages very different models.
        '''

        target_mean = data.get("target_mean")
        target_high = data.get("target_high")
        target_low  = data.get("target_low")
        current     = data.get("current_price")

        if target_mean is None or current is None or current <= 0:
            return SignalResult(name=self.name, score=0.0, values={},
                                note="no analyst targets available")

        # Upside = how far the mean target is above (or below) current price.
        # Positive means analysts expect the stock to appreciate over the next 12 months.
        upside = (target_mean - current) / current

        if upside >= 0.30:
            score = 1.0
        elif upside >= 0.15:
            score = 0.5
        elif upside >= 0:
            score = 0.2
        elif upside >= -0.15:
            score = -0.5
        else:
            score = -1.0

        # Target spread as a fraction of the current price tells us how widely analysts
        # disagree. A spread of 0.40 means analysts' high and low targets differ by 40% of
        # the stock's price — that's a lot of uncertainty baked into the consensus.
        # When spread is wide, scale the score toward neutral to reflect lower reliability.
        spread_pct   = None
        conviction_note = ""
        if target_high is not None and target_low is not None:
            spread_pct = (target_high - target_low) / current
            if spread_pct > 0.40:
                score *= 0.70    # wide disagreement — discount the consensus mean
                conviction_note = f", wide analyst spread ({round(spread_pct * 100, 0):.0f}% of price)"
            elif spread_pct < 0.15:
                conviction_note = ", tight analyst consensus"

        score = self.clamp(score)

        values = {
            "target_mean":   round(target_mean, 2),
            "target_high":   round(target_high, 2) if target_high is not None else None,
            "target_low":    round(target_low, 2) if target_low is not None else None,
            "current_price": round(current, 2),
            "upside_pct":    round(upside * 100, 1),
            "spread_pct":    round(spread_pct * 100, 1) if spread_pct is not None else None,
        }

        note = (
            f"mean target {round(target_mean, 2)} vs price {round(current, 2)} "
            f"= {round(upside * 100, 1)}% upside{conviction_note}"
        )

        return SignalResult(name=self.name, score=score, values=values, note=note)
