'''Streamlit UI for the stock checker.

Two tabs:
  - Analyze: run all signals on a single ticker, show the blended verdict and the
    per-signal breakdown, optionally overlay the LLM judge's reasoning.
  - Scan: run the deterministic baseline across a watchlist and rank the results.

This is a thin presentation layer. All the actual logic lives in src/ — we reuse
run_signals / weighted_blend / blend_verdict from run_checker.py rather than reimplementing
the pipeline, so the UI can never drift from the CLI's numbers.

Run with:  streamlit run app.py
'''

from dotenv import load_dotenv
load_dotenv()

import os
import json
from datetime import date

import streamlit as st
import streamlit.components.v1 as components

from src.checker import config
from src.checker.get_data import MarketData
from src.checker.run_checker import run_signals, weighted_blend, blend_verdict
from src.checker.judge import Judge
from src.screener.aggregator import Aggregator
from src.screener.scrapers.adanos import AdanosScraper
from src.notifier.notifier import Sell_decision

VERDICT_COLOR = {"buy": "#16a34a", "sell": "#dc2626", "hold": "#6b7280"}

POSITIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json_files", "positions.json")


def _get_exit_price(entry_price):
    exit_price = entry_price * 1.3
    ladder = [2, 5, 10, 20, 50, 100, 150, 200, 300, 500, 1000, 1500, 2000, 2500]
    for level in ladder:
        if level >= exit_price:
            return level
    return None


def _load_positions():
    if not os.path.exists(POSITIONS_PATH):
        return {}
    with open(POSITIONS_PATH) as f:
        return json.load(f)


def _delete_position(ticker):
    positions = _load_positions()
    positions.pop(ticker, None)
    with open(POSITIONS_PATH, "w") as f:
        json.dump(positions, f, indent=2)


@st.cache_data(ttl=900, show_spinner=False)
def check_sell_signal(ticker, entry_price, entry_date_str, last_trim_str, ever_above_ema20, exit_price):
    value_dict = {
        "entry_price": entry_price,
        "entry_date": entry_date_str,
        "last_trim": last_trim_str,
        "ever_above_ema20": ever_above_ema20,
        "exit_price": exit_price,
    }
    sd = Sell_decision(ticker, value_dict)
    df = sd.get_charts().reset_index()
    df.columns = df.columns.get_level_values(0)
    df = df.sort_values(by="Date", ascending=True)
    df["ema_4"] = sd.get_ema(df, 4, "High")
    df["ema_20"] = sd.get_ema(df, 20, "Close")
    action = sd.evaluate_rules(df)
    return {
        "action": action,
        "current_price": float(df.iloc[-1]["Close"]),
        "ema_20": float(df.iloc[-1]["ema_20"]),
        "ema_4": float(df.iloc[-1]["ema_4"]),
    }


def _save_position(ticker, entry_price, shares):
    positions = _load_positions()
    positions[ticker] = {
        "entry_price": float(entry_price),
        "entry_date": str(date.today()),
        "number_of_shares": float(shares),
        "last_trim": None,
        "ever_above_ema20": False,
        "exit_price": _get_exit_price(float(entry_price)),
    }
    os.makedirs(os.path.dirname(POSITIONS_PATH), exist_ok=True)
    with open(POSITIONS_PATH, "w") as f:
        json.dump(positions, f, indent=2)


@st.cache_data(ttl=3600, show_spinner=False)
def run_screener():
    agg = Aggregator("combined")
    top_reddit = agg.score_adanos_tickers(AdanosScraper("reddit").get_trending())
    top_x      = agg.score_adanos_tickers(AdanosScraper("x").get_trending())
    top_news   = agg.score_adanos_tickers(AdanosScraper("news").get_trending())
    return agg.combine_adanos_sources(top_reddit, top_x, top_news)


def fmt_market_cap(v):
    if v is None:
        return None
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:.0f}"


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

screen_tab, analyze_tab, notify_tab = st.tabs(["Screen & Buy", "Analyze a ticker", "Portfolio & Sell"])

# --------------------------------------------------------------------------------------
# Screen & Buy tab
# --------------------------------------------------------------------------------------
with screen_tab:
    st.caption(
        "Runs the social/news screener to find trending tickers, checks each one with the "
        "signal engine, and lets you log buys directly into the sell-notifier portfolio."
    )

    col_run, col_cap_screen, col_n = st.columns([1, 2, 2])
    with col_run:
        run_screen = st.button("Run screener", type="primary", width='stretch')
    with col_cap_screen:
        cap_filter_screen = st.selectbox(
            "Market cap filter",
            options=["All", "Micro (<$300M)", "Small ($300M–$2B)", "Mid ($2B–$10B)", "Large ($10B–$200B)", "Mega (≥$200B)"],
            index=0,
            key="screen_cap_filter",
            help="Filters screened tickers before checking — only tickers in the selected tier are analyzed.",
        )
    with col_n:
        top_n = st.slider("Tickers to check", min_value=5, max_value=30, value=15)

    if run_screen:
        run_screener.clear()
        st.session_state.pop("screen_check_rows", None)
        st.session_state.pop("screen_check_errors", None)
        st.session_state.pop("screen_cap_data", None)
        st.session_state.pop("screen_cap_tickers", None)
        with st.spinner("Running screener…"):
            try:
                screened = run_screener()
                st.session_state["screened_tickers"] = screened
            except Exception as e:
                st.error(f"Screener failed: {e}")
                screened = []
    else:
        screened = st.session_state.get("screened_tickers", [])

    if screened:
        tickers_screened = [t["ticker"] for t in screened]

        # Fetch market caps once per screener run; cache so filter changes don't re-fetch.
        if tickers_screened != st.session_state.get("screen_cap_tickers"):
            with st.spinner("Fetching market caps…"):
                cap_data = Aggregator("combined").get_market_cap_category(tickers_screened)
            st.session_state["screen_cap_data"]    = cap_data
            st.session_state["screen_cap_tickers"] = tickers_screened
        cap_data = st.session_state["screen_cap_data"]

        CAP_MICRO = 300_000_000
        CAP_SMALL = 2_000_000_000
        CAP_MID   = 10_000_000_000
        CAP_LARGE = 200_000_000_000

        def _cap_matches(ticker):
            cap = cap_data.get(ticker, {}).get("market_cap")
            if cap is None:
                return False
            if cap_filter_screen == "All":
                return True
            if cap_filter_screen == "Micro (<$300M)":
                return cap < CAP_MICRO
            if cap_filter_screen == "Small ($300M–$2B)":
                return CAP_MICRO <= cap < CAP_SMALL
            if cap_filter_screen == "Mid ($2B–$10B)":
                return CAP_SMALL <= cap < CAP_MID
            if cap_filter_screen == "Large ($10B–$200B)":
                return CAP_MID <= cap < CAP_LARGE
            if cap_filter_screen == "Mega (≥$200B)":
                return cap >= CAP_LARGE
            return True

        filtered_screened = [t for t in screened if _cap_matches(t["ticker"])]
        tickers_to_check  = [t["ticker"] for t in filtered_screened[:top_n]]

        st.subheader(f"Screener — {len(filtered_screened)} trending tickers (checking top {len(tickers_to_check)})")
        st.dataframe(
            [
                {
                    "ticker":     t["ticker"],
                    "sources":    t.get("source_count", 0),
                    "avg_buzz":   round(t.get("avg_buzz_score") or 0, 1),
                    "bull/bear":  round(t.get("bull_bear_ratio") or 0, 2),
                    "trend":      t.get("trend_direction", "unknown"),
                    "market_cap": fmt_market_cap(cap_data.get(t["ticker"], {}).get("market_cap")),
                }
                for t in filtered_screened
            ],
            hide_index=True,
            width='stretch',
            column_config={"market_cap": st.column_config.TextColumn("Mkt cap")},
        )

        col_analyze, col_llm_screen = st.columns([2, 1])
        with col_analyze:
            analyze_screen = st.button("Analyze these tickers", type="secondary", width='stretch')
        with col_llm_screen:
            use_llm_screen = st.checkbox(
                "Run LLM judge on buys", value=False,
                help="After checking, run the LLM judge on baseline buy candidates.",
                key="screen_llm_judge",
            )
        if analyze_screen or "screen_check_rows" in st.session_state:
            if analyze_screen or "screen_check_rows" not in st.session_state:
                rows, errors = [], []
                progress = st.progress(0.0, text="Checking…")
                for i, t in enumerate(tickers_to_check, 1):
                    progress.progress(i / len(tickers_to_check), text=f"Checking {t} ({i}/{len(tickers_to_check)})…")
                    try:
                        data = analyze_ticker(t)
                        price = next(
                            (s["values"].get("current_price") for s in data["signals"] if s["name"] == "targets"),
                            None,
                        )
                        market_cap = next(
                            (s["values"].get("market_cap") for s in data["signals"] if s["name"] == "fundamentals"),
                            None,
                        )
                        rows.append({"ticker": t, "verdict": data["baseline"], "blend": round(data["blended"], 3), "price": price, "market_cap": market_cap})
                    except Exception as e:
                        errors.append(f"{t}: {type(e).__name__}: {e}")
                progress.empty()
                st.session_state["screen_check_rows"] = rows
                st.session_state["screen_check_errors"] = errors

            rows   = st.session_state.get("screen_check_rows", [])
            errors = st.session_state.get("screen_check_errors", [])
            buys   = [r for r in rows if r["verdict"] == "buy"]

            if use_llm_screen and analyze_screen and buys:
                judge = Judge()
                judge_error = None
                judge_progress = st.progress(0.0, text="Judging buys…")
                for i, r in enumerate(buys, start=1):
                    judge_progress.progress(i / len(buys), text=f"Judging {r['ticker']} ({i}/{len(buys)})")
                    try:
                        d = analyze_ticker(r["ticker"])
                        v = judge.decide(r["ticker"], d["_results"], catalysts=d["catalysts"])
                        r["llm"]              = v.get("verdict")
                        r["llm_conf"]         = v.get("confidence")
                        r["llm_reasoning"]    = v.get("reasoning")
                        r["llm_nt_target"]    = v.get("near_term_target")
                        r["llm_nt_timeframe"] = v.get("near_term_timeframe")
                        r["llm_lt_target"]    = v.get("long_term_target")
                        r["llm_lt_timeframe"] = v.get("long_term_timeframe")
                    except Exception as e:
                        judge_error = f"{type(e).__name__}: {e}"
                        break
                judge_progress.empty()
                if judge_error:
                    st.error(
                        f"LLM judge failed: {judge_error}\n\n"
                        "Check that ANTHROPIC_API_KEY is set in your environment / .env."
                    )

            st.subheader(f"Checker results — {len(buys)} buy(s) from {len(rows)} checked")
            st.dataframe(
                [
                    {
                        "ticker":     r["ticker"],
                        "verdict":    r["verdict"],
                        "blend":      r["blend"],
                        "price":      f"${r['price']:.2f}" if r.get("price") else "N/A",
                        "market_cap": fmt_market_cap(r.get("market_cap")),
                    }
                    for r in sorted(rows, key=lambda x: -x["blend"])
                ],
                hide_index=True,
                width='stretch',
                column_config={
                    "blend":      st.column_config.NumberColumn(format="%+.3f"),
                    "market_cap": st.column_config.TextColumn("Mkt cap"),
                },
            )

            if buys:
                st.divider()
                st.subheader("Buy candidates — add to portfolio")
                positions      = _load_positions()
                recently_added = st.session_state.get("screen_added", set())

                for r in buys:
                    ticker        = r["ticker"]
                    default_price = float(r.get("price") or 0.0)
                    color         = VERDICT_COLOR["buy"]

                    col_info, col_form = st.columns([1, 2])
                    with col_info:
                        llm_html = ""
                        if r.get("llm"):
                            lc   = VERDICT_COLOR.get(r["llm"], "#6b7280")
                            conf = f" ({r['llm_conf']:.2f})" if r.get("llm_conf") else ""
                            llm_html = (
                                f"<div style='margin-top:4px;'>LLM &nbsp;"
                                f"<span style='color:{lc};font-weight:700;'>"
                                f"{r['llm'].upper()}{conf}</span></div>"
                            )
                        if st.button(
                            ticker,
                            key=f"deepdive_{ticker}",
                            help="Click to run a deep-dive analysis on this ticker",
                            use_container_width=True,
                        ):
                            st.session_state["analyze_ticker"] = ticker
                            st.session_state["auto_run_analyze"] = True
                            components.html(
                                """<script>
                                setTimeout(function(){
                                    var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                                    if (tabs && tabs.length > 1) tabs[1].click();
                                }, 150);
                                </script>""",
                                height=0,
                            )
                        st.markdown(
                            f"<div>blend &nbsp;<code>{r['blend']:+.3f}</code></div>"
                            f"<div>price &nbsp;<code>${default_price:.2f}</code></div>"
                            + llm_html,
                            unsafe_allow_html=True,
                        )
                        nt = r.get("llm_nt_target")
                        lt = r.get("llm_lt_target")
                        if nt is not None or lt is not None:
                            t_cols = st.columns(2)
                            if nt is not None:
                                t_cols[0].metric("Near-term target", f"${nt}", help=r.get("llm_nt_timeframe"))
                            if lt is not None:
                                t_cols[1].metric("Long-term target", f"${lt}", help=r.get("llm_lt_timeframe"))
                    with col_form:
                        if ticker in recently_added:
                            st.success("Added to portfolio this session.")
                        elif ticker in positions:
                            st.info("Already in your portfolio.")
                        else:
                            with st.form(key=f"form_{ticker}"):
                                ep = st.number_input(
                                    "Entry price ($)", value=max(default_price, 0.01), min_value=0.01, step=0.01,
                                )
                                sh = st.number_input("Shares", value=1, min_value=1, step=1)
                                if st.form_submit_button(f"Add {ticker} to portfolio", type="primary"):
                                    _save_position(ticker, ep, sh)
                                    st.session_state.setdefault("screen_added", set()).add(ticker)
                                    st.rerun()
                    if r.get("llm_reasoning"):
                        with st.expander("LLM reasoning"):
                            st.markdown(r["llm_reasoning"])
                    st.divider()

            if errors:
                with st.expander(f"{len(errors)} error(s)"):
                    for e in errors:
                        st.text(e)

# --------------------------------------------------------------------------------------
# Analyze tab
# --------------------------------------------------------------------------------------
with analyze_tab:
    auto_run = st.session_state.pop("auto_run_analyze", False)
    col_ticker, col_opts = st.columns([2, 1])
    with col_ticker:
        ticker = st.text_input("Ticker symbol", value="NVDA", key="analyze_ticker").upper().strip()
    with col_opts:
        use_llm = st.checkbox("Use LLM judge", value=False,
                              help="Overlay the LLM judge's verdict and reasoning on top of the baseline blend.")
        run = st.button("Analyze", type="primary", width='stretch') or auto_run

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
                    nt = verdict.get("near_term_target")
                    nt_tf = verdict.get("near_term_timeframe")
                    lt = verdict.get("long_term_target")
                    lt_tf = verdict.get("long_term_timeframe")
                    if nt is not None or lt is not None:
                        cols = st.columns(2)
                        if nt is not None:
                            cols[0].metric("Near-term target", f"${nt}", help=nt_tf)
                        if lt is not None:
                            cols[1].metric("Long-term target", f"${lt}", help=lt_tf)
                except Exception as e:
                    st.error(
                        f"LLM judge failed: {type(e).__name__}: {e}\n\n"
                        "Check that ANTHROPIC_API_KEY is set in your environment / .env."
                    )

# --------------------------------------------------------------------------------------
# Portfolio & Sell tab
# --------------------------------------------------------------------------------------
with notify_tab:
    st.caption(
        "Evaluates open positions against the three sell rules: "
        "20EMA break (exit all), round-number target (trim 20%), 4EMA-high break (trim 20%)."
    )

    _ACTION_COLORS = {"sell": "#dc2626", "trim": "#d97706", "hold": "#16a34a"}

    def _action_type(action_str):
        if "Sell all" in action_str:
            return "sell"
        if "Trim" in action_str:
            return "trim"
        return "hold"

    positions = _load_positions()

    col_check, col_clear = st.columns([2, 1])
    with col_check:
        run_notify = st.button("Check all positions", type="primary", width='stretch')
    with col_clear:
        if st.button("Clear cache & refresh", width='stretch'):
            check_sell_signal.clear()
            st.session_state.pop("notify_results", None)
            st.session_state.pop("notify_errors", None)
            st.rerun()

    if not positions:
        st.info("No positions yet. Add some from the Screen & Buy tab.")
    else:
        if run_notify:
            results, errors = {}, {}
            prog = st.progress(0.0, text="Checking positions…")
            items = list(positions.items())
            for i, (t, pos) in enumerate(items, 1):
                prog.progress(i / len(items), text=f"Checking {t} ({i}/{len(items)})…")
                try:
                    results[t] = check_sell_signal(
                        t,
                        pos["entry_price"],
                        pos["entry_date"],
                        pos.get("last_trim"),
                        pos.get("ever_above_ema20", False),
                        pos.get("exit_price"),
                    )
                except Exception as e:
                    errors[t] = f"{type(e).__name__}: {e}"
            prog.empty()
            st.session_state["notify_results"] = results
            st.session_state["notify_errors"] = errors

        results = st.session_state.get("notify_results", {})
        errors  = st.session_state.get("notify_errors", {})

        if results:
            summary_rows = []
            for t, pos in positions.items():
                r = results.get(t)
                if not r:
                    continue
                pnl = (r["current_price"] - pos["entry_price"]) / pos["entry_price"] * 100
                summary_rows.append({
                    "ticker":       t,
                    "action":       r["action"],
                    "_atype":       _action_type(r["action"]),
                    "entry ($)":    pos["entry_price"],
                    "current ($)":  round(r["current_price"], 2),
                    "P&L %":        round(pnl, 1),
                    "shares":       pos.get("number_of_shares", 0),
                })
            summary_rows.sort(key=lambda x: {"sell": 0, "trim": 1, "hold": 2}[x["_atype"]])

            st.subheader("Summary")
            st.dataframe(
                [{k: v for k, v in r.items() if k != "_atype"} for r in summary_rows],
                hide_index=True,
                width="stretch",
                column_config={
                    "P&L %":       st.column_config.NumberColumn(format="%.1f%%"),
                    "entry ($)":   st.column_config.NumberColumn(format="$%.2f"),
                    "current ($)": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
            st.divider()

        st.subheader("Positions")
        for t, pos in positions.items():
            with st.container(border=True):
                r = results.get(t)

                col_hdr, col_badge, col_del = st.columns([2, 4, 1])
                with col_hdr:
                    shares = pos.get("number_of_shares", 0)
                    st.markdown(f"### {t}")
                    st.caption(f"{shares:.0f} shares · entered {pos['entry_date']}")
                with col_badge:
                    if r:
                        at    = _action_type(r["action"])
                        color = _ACTION_COLORS[at]
                        st.markdown(
                            f"<div style='margin-top:10px;padding:8px 16px;border-radius:6px;"
                            f"background:{color};color:white;font-weight:700;"
                            f"display:inline-block;font-size:15px;'>{r['action']}</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("Not checked yet — click 'Check all positions'")
                with col_del:
                    if st.button("Remove", key=f"del_{t}", help=f"Remove {t} from portfolio"):
                        _delete_position(t)
                        st.session_state.get("notify_results", {}).pop(t, None)
                        st.rerun()

                if r:
                    entry   = pos["entry_price"]
                    current = r["current_price"]
                    pnl_pct = (current - entry) / entry * 100
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Entry",      f"${entry:.2f}")
                    m2.metric("Current",    f"${current:.2f}", delta=f"{pnl_pct:+.1f}%")
                    m3.metric("EMA 20",     f"${r['ema_20']:.2f}")
                    m4.metric("EMA 4-High", f"${r['ema_4']:.2f}")

        if errors:
            with st.expander(f"{len(errors)} error(s)"):
                for t, e in errors.items():
                    st.text(f"{t}: {e}")

