'''Streamlit UI for the stock checker.

Two tabs:
  - Analyze: run all signals on a single ticker, show the blended verdict and the
    per-signal breakdown, optionally overlay the LLM judge's reasoning.
  - Scan: run the deterministic baseline across a watchlist and rank the results.

This is a thin presentation layer. All the actual logic lives in src/ — we reuse
run_signals / weighted_blend / blend_verdict from main.py rather than reimplementing
the pipeline, so the UI can never drift from the CLI's numbers.

Run with:  streamlit run app.py
'''

from dotenv import load_dotenv
load_dotenv()

import os, sys
# These inserts have to happen before the `import config` / `from main import ...` lines
# below, not just inside main.py. `import config` is resolved the moment Python reaches it
# here, so if src/ weren't already on the path that import would fail before main.py's own
# path setup ever runs. We mirror main.py's two-entry setup (see the note there on why
# src/signals/ is added separately) so the app and the CLI resolve modules identically.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "signals"))

import streamlit as st

import config
from get_data import MarketData
from main import run_signals, weighted_blend, blend_verdict
from judge import Judge

# Default watchlist for the scan tab — small/mid-cap names ($300M–$10B market cap)
# skewed toward growth sectors where upside potential is highest.
# The user can edit this freely in the UI.
DEFAULT_WATCHLIST = [
    # Tech / software (mid-cap)
    "GTLB", "DDOG", "BILL", "TOST", "SMAR", "MNDY", "DUOL", "HOOD", "RXRX",
    # Semiconductors / hardware (small-mid)
    "ACMR", "ONTO", "FORM", "AMBA", "WOLF",
    # Healthcare / biotech (small-mid)
    "RXRX", "AGIO", "DAWN", "IOVA", "FOLD",
    # Consumer / retail (mid-cap growth)
    "CAVA", "CELH", "SHAK", "BLMN", "XPOF",
    # Industrial / clean energy (small-mid)
    "RKLB", "JOBY", "ACHR", "STEM", "ARRY",
    # Fintech (small-mid)
    "AFRM", "OPEN", "INTU", "RELY", "PRCT",
]

VERDICT_COLOR = {"buy": "#16a34a", "sell": "#dc2626", "hold": "#6b7280"}


# Prices move during the day but not second-to-second, and yfinance is the slow part of
# every interaction. Cache the full signal computation per ticker for 15 minutes so
# re-running the LLM judge or flipping a checkbox doesn't re-hit the network each time.
# The 15-minute TTL is a deliberate freshness-vs-cost tradeoff, not an arbitrary number.
# Shorter would re-hit yfinance on every checkbox toggle for no real gain — intraday prices
# don't move enough in seconds to change a verdict. Much longer would risk showing a stale
# snapshot after the underlying bar has meaningfully shifted. 15 minutes keeps the UI snappy
# while staying current enough for a decision-support tool that scores the latest close.
@st.cache_data(ttl=900, show_spinner=False)
def analyze_ticker(ticker):
    '''Fetch data and run every signal for one ticker.

    The dict packs both representations of the signals on purpose. "signals" is a list of
    plain dicts (name/score/note/values) — JSON-friendly and all the UI needs to render the
    breakdown table. "_results" keeps the live SignalResult objects because the Judge reads
    them directly (r.name, r.values, ...) and the flattened dicts wouldn't satisfy it. Both
    survive st.cache_data's pickling — SignalResult holds only plain attributes — so a cache
    hit returns a working Judge input without another network round-trip.'''
    md        = MarketData(ticker)
    results   = run_signals(md)
    catalysts = md.get_catalysts()

    blended  = weighted_blend(results)
    baseline = blend_verdict(blended)

    return {
        "signals": [
            {"name": r.name, "score": r.score, "note": r.note, "values": r.values}
            for r in results
        ],
        "blended":   blended,
        "baseline":  baseline,
        "catalysts": catalysts,
        # Live SignalResult objects for the Judge — see the docstring for why both forms exist.
        "_results":  results,
    }


def verdict_badge(verdict, confidence=None):
    '''Render a coloured verdict pill with optional confidence.

    We hand-roll the pill instead of using st.success / st.error / st.info because those
    carry fixed semantics (green=good, red=bad) that don't map onto a three-way buy/hold/sell
    decision — "sell" isn't an error, and "hold" isn't a warning. Colouring by verdict via a
    single lookup keeps the badge meaning the same thing in both tabs and for both the
    baseline and the LLM verdict. Unknown verdicts fall back to neutral grey rather than
    raising, so a malformed LLM response degrades gracefully instead of crashing the render.'''
    color = VERDICT_COLOR.get(verdict, "#6b7280")
    conf  = f" &nbsp;·&nbsp; confidence {confidence:.2f}" if confidence is not None else ""
    st.markdown(
        f"<div style='display:inline-block;padding:6px 18px;border-radius:8px;"
        f"background:{color};color:white;font-size:20px;font-weight:700;'>"
        f"{verdict.upper()}{conf}</div>",
        unsafe_allow_html=True,
    )


def render_signal_breakdown(signals):
    '''Show each signal's score as a labelled bar plus its human-readable note.

    Scores live in [-1, +1]; st.progress wants [0, 1], so we remap with (score+1)/2.
    A neutral 0 sits at the half-way mark.'''
    for s in signals:
        weight = config.SIGNAL_WEIGHTS.get(s["name"], 0)
        left, right = st.columns([1, 3])
        with left:
            st.metric(label=f"{s['name']}  ({weight:.0%})", value=f"{s['score']:+.2f}")
        with right:
            st.progress((s["score"] + 1) / 2)
            st.caption(s["note"])


# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------
st.set_page_config(page_title="Stock Checker", page_icon="📈", layout="wide")
st.title("📈 Stock Checker")
st.caption(
    "Momentum · Volume · Fundamentals · Targets → weighted blend, with an optional LLM "
    "judge. Each run is a fresh point-in-time snapshot of the latest close."
)

analyze_tab, scan_tab = st.tabs(["Analyze a ticker", "Scan a watchlist"])

# --------------------------------------------------------------------------------------
# Analyze tab
# --------------------------------------------------------------------------------------
with analyze_tab:
    col_ticker, col_opts = st.columns([2, 1])
    with col_ticker:
        ticker = st.text_input("Ticker symbol", value="NVDA", key="analyze_ticker").upper().strip()
    with col_opts:
        use_llm = st.checkbox("Use LLM judge", value=False,
                              help="Overlay the LLM judge's verdict and reasoning on top of the baseline blend.")
        run = st.button("Analyze", type="primary", use_container_width=True)

    if run and ticker:
        try:
            with st.spinner(f"Fetching data and scoring {ticker}…"):
                data = analyze_ticker(ticker)
        except Exception as e:
            st.error(f"Could not analyze {ticker}: {type(e).__name__}: {e}")
        else:
            st.subheader(f"Baseline verdict — {ticker}")
            verdict_badge(data["baseline"])
            st.markdown(f"**Weighted blend:** `{data['blended']:+.3f}`  "
                        f"(buy ≥ {config.BUY_THRESHOLD}, sell ≤ {config.SELL_THRESHOLD})")

            st.divider()
            st.subheader("Signal breakdown")
            render_signal_breakdown(data["signals"])

            with st.expander("Raw signal values"):
                for s in data["signals"]:
                    st.markdown(f"**{s['name']}**")
                    st.json(s["values"])

            if use_llm:
                st.divider()
                st.subheader("LLM judge")
                try:
                    with st.spinner("Asking the LLM judge…"):
                        judge   = Judge()
                        verdict = judge.decide(ticker, data["_results"], catalysts=data["catalysts"])
                    verdict_badge(verdict.get("verdict", "hold"), verdict.get("confidence"))
                    st.markdown(f"> {verdict.get('reasoning', '')}")
                except Exception as e:
                    st.error(
                        f"LLM judge failed: {type(e).__name__}: {e}\n\n"
                        "Check that ANTHROPIC_API_KEY is set in your environment / .env."
                    )

# --------------------------------------------------------------------------------------
# Scan tab
# --------------------------------------------------------------------------------------
with scan_tab:
    st.caption(
        "Ranks the watchlist by the deterministic blended score. Optionally runs the LLM "
        "judge on the baseline buys only, so you get a second opinion on the candidates "
        "without paying for an API call on every name."
    )
    watchlist_text = st.text_area(
        "Watchlist (comma or whitespace separated)",
        value=", ".join(DEFAULT_WATCHLIST),
        height=80,
    )
    filter_col, judge_col = st.columns([2, 1])
    with filter_col:
        cap_filter = st.selectbox(
            "Market cap filter",
            options=["All", "Small cap (<$2B)", "Mid cap ($2B–$10B)", "Small+Mid (<$10B)"],
            index=3,
            help="Filter results to a specific market cap tier after scanning.",
        )
    with judge_col:
        judge_buys = st.checkbox(
            "Run LLM judge on buys", value=False,
            help="After ranking, run the LLM judge on the names the baseline flagged as 'buy' "
                 "and show its verdict/confidence alongside.",
        )
    scan = st.button("Run scan", type="primary")

    if scan:
        tickers = [t.strip().upper() for t in watchlist_text.replace(",", " ").split() if t.strip()]
        rows, errors = [], []
        progress = st.progress(0.0, text="Scanning…")

        for i, t in enumerate(tickers, start=1):
            progress.progress(i / len(tickers), text=f"Scanning {t} ({i}/{len(tickers)})")
            try:
                data = analyze_ticker(t)
                row = {"ticker": t, "blend": round(data["blended"], 3), "verdict": data["baseline"]}
                for s in data["signals"]:
                    row[s["name"]] = round(s["score"], 2)
                    if s["name"] == "targets":
                        row["upside_pct"] = s["values"].get("upside_pct")
                    if s["name"] == "fundamentals":
                        row["market_cap"] = s["values"].get("market_cap")
                rows.append(row)
            except Exception as e:
                errors.append(f"{t}: {type(e).__name__}: {e}")

        progress.empty()
        rows.sort(key=lambda r: -r["blend"])
        st.session_state["scan_rows"]   = rows
        st.session_state["scan_errors"] = errors

    # Streamlit re-runs the entire script on every interaction, so any local variable
    # computed inside `if scan:` is lost the moment the user switches tabs. Storing in
    # session_state is the only way to keep results visible when they come back.
    # Render from session state so results survive tab switches.
    rows   = st.session_state.get("scan_rows", [])
    errors = st.session_state.get("scan_errors", [])

    if rows:
        # Apply market cap filter. Rows without market_cap data pass through rather
        # than being silently dropped — unknown cap is better than a hidden miss.
        CAP_SMALL = 2e9
        CAP_MID   = 10e9
        if cap_filter == "Small cap (<$2B)":
            rows = [r for r in rows if r.get("market_cap") is None or r["market_cap"] < CAP_SMALL]
        elif cap_filter == "Mid cap ($2B–$10B)":
            rows = [r for r in rows if r.get("market_cap") is None or CAP_SMALL <= r["market_cap"] < CAP_MID]
        elif cap_filter == "Small+Mid (<$10B)":
            rows = [r for r in rows if r.get("market_cap") is None or r["market_cap"] < CAP_MID]

        buys = [r for r in rows if r["verdict"] == "buy"]

        # LLM overlay on the buys only. We re-call analyze_ticker (cache-hit, so no
        # extra network) to recover the live SignalResult objects and catalysts the
        # Judge needs. A single judge failure (e.g. missing API key) is reported once
        # and leaves the baseline scan fully intact.
        if judge_buys and buys and scan:
            judge = Judge()
            judge_error = None
            judge_progress = st.progress(0.0, text="Judging buys…")
            for i, r in enumerate(buys, start=1):
                judge_progress.progress(i / len(buys), text=f"Judging {r['ticker']} ({i}/{len(buys)})")
                try:
                    d = analyze_ticker(r["ticker"])
                    v = judge.decide(r["ticker"], d["_results"], catalysts=d["catalysts"])
                    r["llm"]      = v.get("verdict")
                    r["llm_conf"] = v.get("confidence")
                except Exception as e:
                    # Bail on the first failure rather than retrying every buy. Judge
                    # errors are almost always systemic — a missing/invalid API key, no
                    # network, a rate limit — so the remaining calls would fail the same
                    # way. Stopping shows one clear message instead of N identical ones,
                    # and avoids burning further API calls that can't succeed.
                    judge_error = f"{type(e).__name__}: {e}"
                    break
            judge_progress.empty()
            if judge_error:
                st.error(
                    f"LLM judge failed: {judge_error}\n\n"
                    "Check that ANTHROPIC_API_KEY is set in your environment / .env."
                )

        st.subheader(f"Results — {len(rows)} scored, {len(buys)} buys")

        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "blend":      st.column_config.NumberColumn(format="%+.3f"),
                "upside_pct": st.column_config.NumberColumn("Upside %", format="%.1f%%"),
                "market_cap": st.column_config.NumberColumn(
                    "Mkt cap", format="$%.0f", help="Market capitalisation in USD"
                ),
                "llm":        st.column_config.TextColumn("LLM verdict"),
                "llm_conf":   st.column_config.NumberColumn("LLM conf", format="%.2f"),
            },
        )

        if buys:
            def buy_label(r):
                base = f"{r['ticker']} ({r['blend']:+.3f})"
                if r.get("llm"):
                    base += f" · LLM {r['llm']}"
                return base
            st.success("Buys: " + ", ".join(buy_label(r) for r in buys))
        else:
            st.info("No buys — top 5 by blend: "
                    + ", ".join(f"{r['ticker']} ({r['blend']:+.3f})" for r in rows[:5]))

    if errors:
        with st.expander(f"{len(errors)} error(s)"):
            for e in errors:
                st.text(e)
