import yfinance as yf


class MarketData:

    def __init__(self, ticker):
        self.ticker = ticker
        self.yf_obj = yf.Ticker(self.ticker)

    def get_bars(self):

        df_daily = self.yf_obj.history(period = "6mo", interval = "1d").reset_index()
        df_hourly = self.yf_obj.history(period = "1wk", interval = "1h")
        
        return df_daily, df_hourly
        
    def get_fundamentals(self):

        info = self.yf_obj.info

        valuation = {
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "peg_ratio": info.get("trailingPegRatio"),
            "market_cap": info.get("marketCap"),
        }

        profitability = {
            "profit_margin": info.get("profitMargins"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
        }

        growth = {
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
        }

        health = {
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "free_cashflow": info.get("freeCashflow"),
        }

        dividends = {
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "ex_dividend_date": info.get("exDividendDate"),
        }

        context = {
            "long_name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "business_summary": info.get("longBusinessSummary"),
            "country": info.get("country"),
            "currency": info.get("financialCurrency"),
        }

        return {
            "valuation": valuation,
            "profitability": profitability,
            "growth": growth,
            "health": health,
            "dividends": dividends,
            "context": context,
            "beta": info.get("beta"),
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