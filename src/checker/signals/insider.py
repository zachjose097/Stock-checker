from .base import Signal, SignalResult


class InsiderSignal(Signal):

    name = "insider"

    def evaluate(self, data):
        '''Score the stock on insider buying vs selling over the trailing 6 months.

        The asymmetry is the whole point of this signal. Insider *buying* is one of the
        cleanest bullish signals available — an officer or director putting their own money
        in has exactly one motive: they think the stock is cheap. Insider *selling* is far
        noisier: insiders sell for diversification, tax bills, divorce, a new house, or
        scheduled 10b5-1 plans — reasons that say nothing about the business. So buying is
        scored with conviction while selling is penalised more softly.

        This matters most for the small/mid-caps this scanner targets, where insiders own a
        large share of the float and sell-side coverage is thin — insider behaviour is often
        the best-informed read available on the name.

        Two inputs drive the score:
          - Buy ratio: purchase shares / (purchase + sale shares) over 6 months. The
            direction and conviction of net activity.
          - Breadth: the number of separate purchase (or sale) transactions. Several
            insiders independently buying (cluster buying) is a much stronger signal than
            one large block from a single person.
        '''

        activity = data.get("net_activity_6m", {}) if data else {}

        purchase_shares = activity.get("purchase_shares") or 0
        sale_shares     = activity.get("sale_shares") or 0
        purchase_count  = activity.get("purchase_count") or 0
        sale_count      = activity.get("sale_count") or 0

        total_shares = purchase_shares + sale_shares

        # No transactions in the window tells us nothing either way — stay neutral rather
        # than guessing. A zero score contributes nothing to the weighted blend.
        if total_shares <= 0:
            return SignalResult(name=self.name, score=0.0, values={},
                                note="no insider transactions in last 6m")

        # buy_ratio of 1.0 = all buying, 0.0 = all selling, 0.5 = balanced.
        buy_ratio = purchase_shares / total_shares

        # --- Direction & conviction (asymmetric) ---
        # Buying tiers reach a higher magnitude than the mirror-image selling tiers because
        # buying is the higher-signal event. Net selling lands a muted penalty.
        if buy_ratio >= 0.70:
            score = 0.70      # insiders overwhelmingly buying — strongest insider signal
        elif buy_ratio >= 0.55:
            score = 0.40      # net buyers
        elif buy_ratio > 0.45:
            score = 0.0       # roughly balanced — no edge
        elif buy_ratio > 0.30:
            score = -0.25     # net selling — softer penalty, selling is noisy
        else:
            score = -0.40     # heavy selling

        # --- Breadth / clustering ---
        # Three or more separate transactions in the dominant direction signals a pattern
        # rather than a one-off. Reward clustered buying more than clustered selling, in
        # keeping with the buy/sell asymmetry above.
        clustered_buying  = score > 0 and purchase_count >= 3
        clustered_selling = score < 0 and sale_count >= 3
        if clustered_buying:
            score += 0.20
        elif clustered_selling:
            score -= 0.10

        score = self.clamp(score)

        values = {
            "buy_ratio":         round(buy_ratio, 2),
            "purchase_shares":   purchase_shares,
            "sale_shares":       sale_shares,
            "purchase_count":    purchase_count,
            "sale_count":        sale_count,
            "net_shares":        activity.get("net_shares"),
            "total_shares_held": activity.get("total_shares_held"),
        }

        direction = "net buying" if buy_ratio > 0.5 else ("net selling" if buy_ratio < 0.5 else "balanced")
        note = (
            f"6m {direction}: {round(buy_ratio * 100)}% of share flow was buys "
            f"({purchase_count} buys / {sale_count} sells)"
        )

        return SignalResult(name=self.name, score=score, values=values, note=note)
