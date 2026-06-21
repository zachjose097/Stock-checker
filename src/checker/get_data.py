import yfinance as yf
import pandas as pd
from datetime import date


def f(v):
    """Cast a yfinance value to float, returning None if it can't be converted."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MarketData:

    def __init__(self, ticker):
        self.ticker = ticker
        self.yf_obj = yf.Ticker(self.ticker)

    def get_bars(self):
        df_daily = self.yf_obj.history(period="6mo", interval="1d").reset_index()

        # Drop today's partial bar so signals are always based on the last completed close.
        # During market hours yfinance appends an in-progress bar for the current session,
        # whose OHLCV values change tick-by-tick and would cause signal scores to shift
        # throughout the day.
        if not df_daily.empty and pd.Timestamp(df_daily["Date"].iloc[-1]).date() >= date.today():
            df_daily = df_daily.iloc[:-1]

        df_hourly = self.yf_obj.history(period="1wk", interval="1h")

        return df_daily, df_hourly

    def roic(self):
        """Return on invested capital = NOPAT / invested capital, computed from the
        latest annual financials. NOPAT is EBIT taxed at the effective tax rate.
        Returns None if the required inputs aren't available."""
        try:
            income = self.yf_obj.income_stmt
            balance = self.yf_obj.balance_sheet
        except Exception:
            return None

        def latest(df, row):
            # yfinance statements are ordered most-recent-column-first.
            if df is None or row not in df.index:
                return None
            series = df.loc[row].dropna()
            return f(series.iloc[0]) if not series.empty else None

        ebit = latest(income, "EBIT")
        if ebit is None:
            ebit = latest(income, "Operating Income")

        invested_capital = latest(balance, "Invested Capital")

        if ebit is None or not invested_capital:
            return None

        tax_rate = latest(income, "Tax Rate For Calcs")
        if tax_rate is None:
            pretax = latest(income, "Pretax Income")
            tax_provision = latest(income, "Tax Provision")
            if pretax and tax_provision is not None:
                tax_rate = tax_provision / pretax
        if tax_rate is None or tax_rate < 0 or tax_rate > 1:
            tax_rate = 0.21  # fall back to a typical corporate rate

        nopat = ebit * (1 - tax_rate)
        return nopat / invested_capital

    def get_fundamentals(self):

        info = self.yf_obj.info

        valuation = {
            "trailing_pe": f(info.get("trailingPE")),
            "forward_pe":  f(info.get("forwardPE")),
            "price_to_book":  f(info.get("priceToBook")),
            "price_to_sales": f(info.get("priceToSalesTrailing12Months")),
            "ev_to_revenue":  f(info.get("enterpriseToRevenue")),
            "ev_to_ebitda":   f(info.get("enterpriseToEbitda")),
            "peg_ratio":      f(info.get("trailingPegRatio")),
            "market_cap":     f(info.get("marketCap")),
        }

        profitability = {
            "profit_margin":    f(info.get("profitMargins")),
            "gross_margin":     f(info.get("grossMargins")),
            "operating_margin": f(info.get("operatingMargins")),
            "return_on_equity": f(info.get("returnOnEquity")),
            "return_on_assets": f(info.get("returnOnAssets")),
            "return_on_invested_capital": self.roic(),
        }

        growth = {
            "revenue_growth":            f(info.get("revenueGrowth")),
            "earnings_growth":           f(info.get("earningsGrowth")),
            "earnings_quarterly_growth": f(info.get("earningsQuarterlyGrowth")),
        }

        health = {
            "debt_to_equity": f(info.get("debtToEquity")),
            "current_ratio":  f(info.get("currentRatio")),
            "quick_ratio":    f(info.get("quickRatio")),
            "total_debt":     f(info.get("totalDebt")),
            "total_cash":     f(info.get("totalCash")),
            "free_cashflow":  f(info.get("freeCashflow")),
        }

        dividends = {
            "dividend_yield": f(info.get("dividendYield")),
            "payout_ratio":   f(info.get("payoutRatio")),
            "ex_dividend_date": info.get("exDividendDate"),
        }

        context = {
            "long_name":        info.get("longName"),
            "sector":           info.get("sector"),
            "industry":         info.get("industry"),
            "business_summary": info.get("longBusinessSummary"),
            "country":          info.get("country"),
            "currency":         info.get("financialCurrency"),
        }

        return {
            "valuation":     valuation,
            "profitability": profitability,
            "growth":        growth,
            "health":        health,
            "dividends":     dividends,
            "context":       context,
            "beta": f(info.get("beta")),
        }


    def get_catalysts(self):

        cal = self.yf_obj.calendar

        earnings_date = cal.get("Earnings Date")
        catalysts = {
            "earnings_date": earnings_date[0] if earnings_date else None,
            "earnings_date_is_range": len(earnings_date) > 1 if earnings_date else False,
            "eps_estimate_high": cal.get("Earnings High"),
            "eps_estimate_low": cal.get("Earnings Low"),
            "eps_estimate_avg": cal.get("Earnings Average"),
            "revenue_estimate_avg": cal.get("Revenue Average"),
            "revenue_estimate_high": cal.get("Revenue High"),
            "revenue_estimate_low": cal.get("Revenue Low"),
            }

        return catalysts

    def get_price_targets(self):

        pt = self.yf_obj.analyst_price_targets

        price_targets = {
            "current_price": pt.get("current"),
            "high": pt.get("high"),
            "low": pt.get ("low"),
            "mean": pt.get("mean"),
            "median": pt.get("median")

        }

        return price_targets

    def get_insider_transactions(self, limit=10):
        """Insider activity: a 6-month net buy/sell summary plus the most recent
        individual transactions. Fields are None / empty when unavailable."""

        activity = {
            "purchase_shares":   None,
            "purchase_count":    None,
            "sale_shares":       None,
            "sale_count":        None,
            "net_shares":        None,
            "total_shares_held": None,
            "pct_net_shares":    None,
        }

        summary = self.yf_obj.insider_purchases
        if summary is not None and not summary.empty:
            # The label lives in the first column, whose header varies by ticker.
            label_col = summary.columns[0]
            rows = {str(r[label_col]): r for _, r in summary.iterrows()}

            def grab(label, field):
                row = rows.get(label)
                return f(row[field]) if row is not None else None

            activity["purchase_shares"]   = grab("Purchases", "Shares")
            activity["purchase_count"]    = grab("Purchases", "Trans")
            activity["sale_shares"]       = grab("Sales", "Shares")
            activity["sale_count"]        = grab("Sales", "Trans")
            activity["net_shares"]        = grab("Net Shares Purchased (Sold)", "Shares")
            activity["total_shares_held"] = grab("Total Insider Shares Held", "Shares")
            activity["pct_net_shares"]    = grab("% Net Shares Purchased (Sold)", "Shares")

        recent = []
        txns = self.yf_obj.insider_transactions
        if txns is not None and not txns.empty:
            for _, row in txns.head(limit).iterrows():
                recent.append({
                    "insider":     row.get("Insider"),
                    "position":    row.get("Position"),
                    "transaction": row.get("Transaction"),
                    "shares":      f(row.get("Shares")),
                    "value":       f(row.get("Value")),
                    "date":        row.get("Start Date"),
                    "ownership":   row.get("Ownership"),
                })

        return {
            "net_activity_6m":     activity,
            "recent_transactions": recent,
        }

    def get_fundamental_trends(self):

        fin = self.yf_obj.quarterly_income_stmt

        wanted = {
            "Total Revenue": "revenue",
            "Net Income": "net_income",
            "Gross Profit": "gross_profit",
            "Operating Income": "operating_income",
            "Research And Development": "rnd",
        }

        trends = {}

        for parameter, var_name in wanted.items():
            if parameter in fin.index:
                trends[var_name] = fin.loc[parameter].sort_index().tolist()
            else:
                trends[var_name] = None

        trends["Quarters"] = sorted(fin.columns.tolist())

        revenue = fin.loc["Total Revenue"].sort_index() if "Total Revenue" in fin.index else None

        if revenue is not None:

            if "Gross Profit" in fin.index and fin.loc["Gross Profit"] is not None:
                trends["gross_margin"] = (fin.loc["Gross Profit"].sort_index() / revenue).tolist()
            else:
                trends["gross_margin"] = None

            if "Operating Income" in fin.index:
                trends["operating_margin"] = (fin.loc["Operating Income"].sort_index() / revenue).tolist()
            else:
                trends["operating_margin"] = None

        else:
            trends["gross_margin"] = None
            trends["operating_margin"] = None


        return trends
