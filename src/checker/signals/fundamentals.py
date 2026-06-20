from .base import Signal, SignalResult


# Growth sectors: the market pays premium multiples because earnings are expected to compound.
# A tech stock at PE=40 isn't automatically expensive — it may be pricing in 30% annual growth.
GROWTH_SECTORS = {"Technology", "Communication Services", "Consumer Cyclical"}

# Value sectors: stable but slow-growing businesses. The market applies lower multiples
# because earnings predictability matters more than growth rate here.
VALUE_SECTORS = {"Financials", "Energy", "Utilities", "Real Estate", "Basic Materials"}


class FundamentalsSignal(Signal):

    name = "fundamentals"

    def _sector_type(self, sector):
        '''Classify the sector to determine which valuation benchmarks apply.
        A PE of 30 means very different things for a semiconductor company vs a utility.'''
        if sector in GROWTH_SECTORS:
            return "growth"
        if sector in VALUE_SECTORS:
            return "value"
        return "standard"

    def _score_valuation(self, valuation, sector_type):
        '''Score the stock's valuation using the most appropriate multiple for its sector.

        Growth stocks: PEG ratio is the primary metric because it accounts for what you're
        paying relative to the growth rate. PEG = PE / annual earnings growth rate.
          PEG < 1: paying less than 1x your growth rate — widely considered undervalued.
          PEG > 2: paying a heavy premium for that growth — needs perfect execution.
        If PEG isn't available, fall back to PE with wider "acceptable" bands.

        Value stocks: PE with tighter bands. A utility at PE=25 is expensive. EV/EBITDA
        is used as fallback because it accounts for debt differences across capital structures.

        Forward PE vs trailing PE: forward PE divides the current price by the next 12 months'
        expected EPS (analyst consensus). If forward PE < trailing PE, earnings are expected to
        grow — a bullish signal on top of the base valuation score.
        '''
        score = 0.0
        used = []

        peg         = valuation.get("peg_ratio")
        forward_pe  = valuation.get("forward_pe")
        trailing_pe = valuation.get("trailing_pe")
        ev_ebitda   = valuation.get("ev_to_ebitda")

        # Prefer forward PE as it prices in expected earnings rather than last year's results
        pe = forward_pe if (forward_pe and forward_pe > 0) else trailing_pe

        if sector_type == "growth":
            if peg is not None and peg > 0:
                # PEG is the most informative signal for growth stocks — use it as primary
                if peg < 1.0:
                    score += 0.35    # paying less than your growth rate — undervalued
                elif peg < 1.5:
                    score += 0.20    # fairly priced for growth
                elif peg < 2.0:
                    score += 0.05    # slightly expensive but justifiable
                else:
                    score -= 0.20    # heavy growth premium — needs perfect execution
                used.append("peg")
            elif pe is not None and pe > 0:
                # Growth sector PE benchmarks: 30-50 is normal for a quality tech commpany
                if pe < 25:
                    score += 0.25    # cheap even by growth standards
                elif pe < 45:
                    score += 0.10    # fairly valued
                elif pe < 65:
                    score -= 0.10    # expensive, limited margin of safety
                else:
                    score -= 0.25    # very expensive
                used.append("pe")

        elif sector_type == "value":
            if pe is not None and pe > 0:
                # Value sector PE bands are tighter — slow earnings growth doesn't justify
                # the same multiples that growth companies command
                if pe < 12:
                    score += 0.35    # cheap
                elif pe < 18:
                    score += 0.15    # fairly valued
                elif pe < 25:
                    score -= 0.10    # slightly expensive for a slow-growth business
                else:
                    score -= 0.30    # expensive
                used.append("pe")
            elif ev_ebitda is not None and ev_ebitda > 0:
                # EV/EBITDA is useful for energy and financials where capital structures
                # vary widely — it levels the playing field across different debt levels.
                # Below 8 is cheap, above 15 is expensive for value sectors.
                if ev_ebitda < 8:
                    score += 0.25
                elif ev_ebitda < 12:
                    score += 0.10
                elif ev_ebitda < 18:
                    score -= 0.10
                else:
                    score -= 0.25
                used.append("ev_ebitda")

        else:  # standard sectors (Healthcare, Industrials, etc.)
            if pe is not None and pe > 0:
                if pe < 15:
                    score += 0.30
                elif pe < 25:
                    score += 0.10
                elif pe < 40:
                    score -= 0.15
                else:
                    score -= 0.30
                used.append("pe")

        # Forward earnings direction: compare forward PE to trailing PE.
        # ratio < 0.85 means earnings are expected to grow >15% — a forward-looking tailwind.
        # ratio > 1.10 means earnings are expected to shrink — a headwind on top of valuation.
        if forward_pe and trailing_pe and forward_pe > 0 and trailing_pe > 0:
            ratio = forward_pe / trailing_pe
            if ratio < 0.85:
                score += 0.05    # earnings expected to grow significantly
            elif ratio > 1.10:
                score -= 0.05    # earnings expected to shrink
            used.append("fwd_vs_trailing")

        return score, used

    def _score_growth(self, growth):
        '''Score revenue and earnings growth rates independently.

        Revenue growth: how fast the top line is expanding. A company can cut costs to
        grow earnings temporarily, but revenue growth reflects real demand for the product.

        Earnings growth: how fast net income is expanding. High earnings growth with flat
        revenue often means margin improvement or one-time items — less durable than
        revenue-led growth.

        Both matter: the strongest signal is both growing together.
        '''
        score = 0.0
        used = []

        rev_growth  = growth.get("revenue_growth")
        earn_growth = growth.get("earnings_growth")
        earn_qtr    = growth.get("earnings_quarterly_growth")

        if rev_growth is not None:
            # YoY change in total revenue. Small/mid caps at 40%+ are in hypergrowth territory.
            if rev_growth >= 0.40:
                score += 0.25    # hypergrowth — exceptional for any size company
            elif rev_growth >= 0.25:
                score += 0.15    # strong top-line expansion
            elif rev_growth >= 0.10:
                score += 0.08    # healthy growth
            elif rev_growth >= 0:
                score += 0.0     # flat but not shrinking
            else:
                score -= 0.15    # revenue contraction is a serious red flag
            used.append("revenue_growth")

        if earn_growth is not None:
            # YoY change in net income
            if earn_growth >= 0.40:
                score += 0.25    # hypergrowth earnings
            elif earn_growth >= 0.25:
                score += 0.15
            elif earn_growth >= 0.10:
                score += 0.08
            elif earn_growth >= 0:
                score += 0.0
            else:
                score -= 0.15
            used.append("earnings_growth")

        # Quarterly earnings growth is a more recent signal — use it as a fallback
        # only when annual earnings growth isn't available
        if earn_growth is None and earn_qtr is not None:
            if earn_qtr >= 0.15:
                score += 0.10
            elif earn_qtr >= 0:
                score += 0.0
            else:
                score -= 0.10
            used.append("earnings_quarterly_growth")

        return score, used

    def _score_profitability(self, profitability):
        '''Score profit quality across three dimensions:

        Net margin: percentage of revenue that becomes profit after ALL costs (taxes, interest,
        depreciation). High net margin means the business is not just growing but capturing value.

        Operating margin: profit before interest and taxes. A cleaner view of the core business's
        efficiency because it excludes financing decisions (debt levels) and tax treatment.
        Two companies can have the same revenue/costs but very different net margins if one
        is heavily leveraged — operating margin shows what the business itself earns.

        ROE (return on equity): net income / shareholder equity. Measures how efficiently
        management uses the capital shareholders have invested. ROE > 15% is strong.
        Very high ROE (>50%) can be misleading — it sometimes reflects heavy debt financing
        rather than genuine efficiency (borrowed money amplifies ROE mathematically).
        '''
        score = 0.0
        used = []

        profit_margin    = profitability.get("profit_margin")
        operating_margin = profitability.get("operating_margin")
        roe              = profitability.get("return_on_equity")

        if profit_margin is not None:
            if profit_margin >= 0.20:
                score += 0.07    # high quality business
            elif profit_margin >= 0.10:
                score += 0.03    # healthy
            elif profit_margin >= 0:
                score += 0.0     # marginal but not loss-making
            else:
                score -= 0.10    # losing money on every sale — significant penalty
            used.append("profit_margin")

        if operating_margin is not None:
            if operating_margin >= 0.20:
                score += 0.07
            elif operating_margin >= 0.10:
                score += 0.03
            elif operating_margin >= 0:
                score += 0.0
            else:
                score -= 0.05    # core operations are unprofitable
            used.append("operating_margin")

        if roe is not None:
            # Cap the reward for very high ROE — above 50% likely means leverage-driven returns
            if 0.15 <= roe <= 0.50:
                score += 0.06    # strong, genuine capital efficiency
            elif roe > 0.50:
                score += 0.03    # high but could be financial engineering
            elif roe >= 0.05:
                score += 0.0     # mediocre but acceptable
            else:
                score -= 0.05    # poor use of shareholder capital
            used.append("roe")

        return score, used

    def _score_health(self, health, market_cap):
        '''Score financial health through liquidity and leverage.

        Current ratio = current assets / current liabilities.
        Measures whether the company can pay its bills over the next 12 months.
          > 2: comfortable liquidity buffer
          1-2: adequate
          < 1: current liabilities exceed current assets — short-term solvency risk

        Debt/equity: how much of the business is funded by debt.
        Debt amplifies returns in good times but is dangerous in a downturn.
        Small caps are penalised more harshly for high debt because they have less
        access to credit markets to refinance when conditions tighten.

        Free cash flow: cash left over after capital expenditure. Positive FCF means the
        business is self-funding. Negative FCF means it must raise debt or equity to survive —
        this is normal for early-stage growth companies but a risk flag for mature ones.
        '''
        score = 0.0
        used = []

        current_ratio  = health.get("current_ratio")
        debt_to_equity = health.get("debt_to_equity")
        free_cashflow  = health.get("free_cashflow")
        is_small_cap   = market_cap is not None and market_cap < 2e9

        if current_ratio is not None:
            if current_ratio >= 2.0:
                score += 0.05    # strong liquidity buffer
            elif current_ratio >= 1.5:
                score += 0.03    # healthy
            elif current_ratio >= 1.0:
                score += 0.0     # adequate
            else:
                score -= 0.05    # can't cover short-term obligations
            used.append("current_ratio")

        if debt_to_equity is not None:
            # Small caps get harsher penalties for high leverage — limited refinancing access
            if debt_to_equity <= 0.3:
                score += 0.05    # low leverage, conservative balance sheet
            elif debt_to_equity <= 1.0:
                score += 0.02    # moderate leverage
            elif debt_to_equity <= 2.0:
                score -= (0.05 if is_small_cap else 0.02)
            else:
                score -= (0.10 if is_small_cap else 0.05)   # high leverage
            used.append("debt_to_equity")

        if free_cashflow is not None:
            if free_cashflow <= 0:
                # Burning cash — not necessarily terminal for growth companies but worth flagging
                score -= 0.03
            used.append("free_cashflow")

        return score, used

    def _score_trends(self, trends):
        '''Score the direction of key metrics over recent quarters using get_fundamental_trends() data.

        Current-period metrics (PE, margins) are a snapshot in time. Trends reveal trajectory:
        a company with 15% operating margins that has been expanding them for 4 quarters is
        a very different business from one with 15% margins that have been contracting.

        Revenue Q/Q direction: compare the most recent quarter to the prior quarter.
        A >5% sequential increase suggests the business is accelerating.

        Operating margin direction: is the business becoming more or less efficient quarter
        over quarter? Expanding margins mean the company is gaining pricing power or cutting
        costs faster than it is growing — a quality signal. Contracting margins signal cost
        pressure, pricing weakness, or investments that haven't yet paid off.
        '''
        if trends is None:
            return 0.0, []

        score = 0.0
        used = []

        revenue    = trends.get("revenue")
        op_margins = trends.get("operating_margin")

        # Revenue Q/Q direction — compare last two quarters
        # We use abs() in the denominator to handle cases where the prior quarter was negative
        if revenue and len(revenue) >= 2 and revenue[-2] and revenue[-2] != 0:
            rev_qoq = (revenue[-1] - revenue[-2]) / abs(revenue[-2])
            if rev_qoq > 0.05:
                score += 0.03    # revenue accelerating quarter-on-quarter
            elif rev_qoq < -0.05:
                score -= 0.03    # revenue contracting quarter-on-quarter
            used.append("revenue_trend")

        # Operating margin direction — 1 percentage point change is the threshold
        # (smaller changes are within normal quarterly noise)
        if op_margins and len(op_margins) >= 2 and op_margins[-2] is not None:
            margin_change = op_margins[-1] - op_margins[-2]
            if margin_change > 0.01:
                score += 0.02    # margin expanding — efficiency improving
            elif margin_change < -0.01:
                score -= 0.02    # margin contracting — cost pressure or pricing weakness
            used.append("margin_trend")

        return score, used

    def evaluate(self, data, trends=None):
        '''Score the stock on fundamentals.
        data   = dict from get_fundamentals()
        trends = dict from get_fundamental_trends() — optional, adds quarterly trend signals
        '''

        valuation     = data.get("valuation", {})
        profitability = data.get("profitability", {})
        growth        = data.get("growth", {})
        health        = data.get("health", {})
        context       = data.get("context", {})
        market_cap    = valuation.get("market_cap")
        sector        = context.get("sector")

        sector_type = self._sector_type(sector)

        val_score,    val_used    = self._score_valuation(valuation, sector_type)
        grow_score,   grow_used   = self._score_growth(growth)
        prof_score,   prof_used   = self._score_profitability(profitability)
        health_score, health_used = self._score_health(health, market_cap)
        trend_score,  trend_used  = self._score_trends(trends)

        all_used = val_used + grow_used + prof_used + health_used + trend_used

        if not all_used:
            return SignalResult(name=self.name, score=0.0, values={},
                                note="no fundamental data available")

        score = self.clamp(val_score + grow_score + prof_score + health_score + trend_score)

        values = {
            "sector":           sector,
            "sector_type":      sector_type,
            "market_cap":       market_cap,
            "forward_pe":       valuation.get("forward_pe"),
            "trailing_pe":      valuation.get("trailing_pe"),
            "peg_ratio":        valuation.get("peg_ratio"),
            "revenue_growth":   growth.get("revenue_growth"),
            "earnings_growth":  growth.get("earnings_growth"),
            "profit_margin":    profitability.get("profit_margin"),
            "operating_margin": profitability.get("operating_margin"),
            "roe":              profitability.get("return_on_equity"),
            "current_ratio":    health.get("current_ratio"),
            "debt_to_equity":   health.get("debt_to_equity"),
            "metrics_used":     len(all_used),
        }

        note = (
            f"{sector or 'unknown sector'} ({sector_type}), "
            f"scored on {len(all_used)} metrics: {', '.join(all_used)}"
        )

        return SignalResult(name=self.name, score=score, values=values, note=note)
