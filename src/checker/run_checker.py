from dotenv import load_dotenv
load_dotenv()

import argparse, sys

from src.checker import config
from src.checker.get_data import MarketData
from src.checker.signals.momentum import MomentumSignal
from src.checker.signals.volume import VolumeSignal
from src.checker.signals.fundamentals import FundamentalsSignal
from src.checker.signals.targets import TargetsSignal
from src.checker.signals.insider import InsiderSignal
from src.checker.judge import Judge


def run_signals(md):
    '''Fetch all market data and evaluate every signal.

    Signals that accept context (market_cap, beta) receive it so their thresholds scale
    to the stock's size and volatility profile — a small-cap needs different RSI bands
    and volume spike thresholds than a mega-cap. See MomentumSignal and VolumeSignal.

    FundamentalsSignal.evaluate() accepts an optional trends dict for quarterly direction
    signals (revenue Q/Q, margin expansion) on top of the point-in-time fundamentals.

    get_price_targets() returns keys "mean"/"high"/"low"; TargetsSignal expects "target_*".
    We remap here so get_data stays clean and the signal's interface stays self-describing.
    '''
    fundamentals  = md.get_fundamentals()
    trends        = md.get_fundamental_trends()
    price_targets = md.get_price_targets()
    insider       = md.get_insider_transactions()

    market_cap = fundamentals.get("valuation", {}).get("market_cap")
    beta       = fundamentals.get("beta")

    targets_data = {
        "target_mean":   price_targets.get("mean"),
        "target_high":   price_targets.get("high"),
        "target_low":    price_targets.get("low"),
        "current_price": price_targets.get("current_price"),
    }

    df_daily, _ = md.get_bars()

    return [
        MomentumSignal(beta=beta, market_cap=market_cap).evaluate(df_daily),
        VolumeSignal(market_cap=market_cap).evaluate(df_daily),
        FundamentalsSignal().evaluate(fundamentals, trends=trends),
        TargetsSignal().evaluate(targets_data),
        InsiderSignal().evaluate(insider),
    ]


def weighted_blend(results):
    '''Compute the deterministic baseline score as a weighted average of all signals.

    This is our rule-based fallback: fast, reproducible, zero inference cost. Weights
    are set in config.SIGNAL_WEIGHTS and sum to 1.0. The LLM judge reasons over the
    same data and can diverge from this baseline — having both lets you compare the
    systematic score against the model's qualitative read.

    Value-dislocation adjustment: when fundamentals and analyst targets both strongly
    disagree with weak momentum, that pattern is most likely a temporary price dislocation
    rather than a deteriorating business. In that case we halve momentum's negative
    contribution so the pattern can score as a buy rather than stalling at the hold
    boundary. The condition is deliberately tight — all three must clear a meaningful
    threshold — so the adjustment only fires on genuine value setups, not marginal cases.
    '''
    scores = {r.name: r.score for r in results}
    blended = 0.0
    for r in results:
        weight = config.SIGNAL_WEIGHTS.get(r.name, 0)
        score  = r.score
        if (r.name == "momentum" and score < -0.2
                and scores.get("fundamentals", 0) > 0.3
                and scores.get("targets", 0) > 0.3):
            score *= 0.5
        blended += score * weight
    return blended


def blend_verdict(blended):
    '''Map the continuous blended score to a discrete buy / hold / sell verdict.

    The dead zone between SELL_THRESHOLD and BUY_THRESHOLD (±0.25 in config) is the whole
    point of this function. A blended score of +0.05 is not a weak buy — it's noise: a few
    signals leaning marginally positive with no real aggregate edge. Requiring the score to
    clear ±0.25 before committing keeps "hold" as the honest answer for marginal setups, and
    stops the verdict from flip-flopping on the small day-to-day score wobble that every
    stock produces. The band is symmetric because we have no prior that longs are safer than
    shorts at the margin — the bar for conviction should be the same in both directions.
    '''
    if blended >= config.BUY_THRESHOLD:
        return "buy"
    elif blended <= config.SELL_THRESHOLD:
        return "sell"
    else:
        return "hold"


def main(use_llm=None):
    ticker = input("Ticker symbol: ").upper().strip()
    # use_llm=None means "the caller didn't decide" — only then do we prompt interactively.
    # This is distinct from an explicit False: a programmatic caller (a test, the UI) passes
    # a real bool to suppress the prompt entirely, while the bare CLI passes None so the
    # human at the terminal gets asked. Defaulting to False instead would silently skip the
    # judge for interactive users who never opted out.
    if use_llm is None:
        use_llm = input("Use LLM judge? (y/n): ").strip().lower() in ("y", "yes", "1", "true")

    md        = MarketData(ticker)
    results   = run_signals(md)
    catalysts = md.get_catalysts()

    # The deterministic baseline is always computed, even when the LLM judge will run below.
    # The two are complementary, not either/or: the baseline is the reproducible systematic
    # score, the judge is a qualitative overlay. Showing them side by side is what makes the
    # output useful — agreement is reassurance, divergence is a flag worth investigating.
    blended  = weighted_blend(results)
    baseline = blend_verdict(blended)

    print(f"\n--- Signals for {ticker} ---")
    for r in results:
        print(f"  {r.name:13} score {round(r.score, 2):>5}  |  {r.note}")

    print(f"\nWeighted blend: {round(blended, 3)}  ->  {baseline}")

    if use_llm:
        judge   = Judge()
        verdict = judge.decide(ticker, results, catalysts=catalysts)

        print(f"\n--- LLM verdict ---")
        print(f"  verdict:    {verdict.get('verdict')}")
        print(f"  confidence: {verdict.get('confidence')}")
        print(f"  reasoning:  {verdict.get('reasoning')}")

        nt = verdict.get('near_term_target')
        nt_tf = verdict.get('near_term_timeframe')
        lt = verdict.get('long_term_target')
        lt_tf = verdict.get('long_term_timeframe')
        if nt is not None:
            print(f"  near-term target:  ${nt}  ({nt_tf})")
        if lt is not None:
            print(f"  long-term target:  ${lt}  ({lt_tf})")

        return verdict

    # Return the same dict shape whether or not the LLM ran, so callers (scan.py, the UI)
    # can read verdict / confidence / reasoning uniformly without branching on which path
    # produced the result. With no LLM there is genuinely no confidence or reasoning to
    # report, so those are explicitly None rather than omitted — an absent key would force
    # every caller to guard each access with .get(), which is exactly the friction this avoids.
    return {"verdict": baseline, "confidence": None, "reasoning": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="run the LLM judge for a verdict with reasoning")
    args = parser.parse_args()
    main(use_llm=args.llm or None)
