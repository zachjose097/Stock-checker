# Stock Checker

A multi-signal stock scoring tool with a Streamlit UI and optional LLM judge.

## How it works

Four signals each produce a score from -1 (strong sell) to +1 (strong buy):

| Signal | Weight | What it measures |
|---|---|---|
| Momentum | 35% | RSI, moving average crossovers, trend strength |
| Fundamentals | 30% | PE, revenue growth, margins, debt |
| Volume | 20% | Volume trend and spike vs. 20-day average |
| Targets | 15% | Upside/downside to analyst price targets |

These are blended into a weighted score. A score above **+0.25** is a buy, below **-0.25** is a sell, and everything in between is a hold.

An optional LLM judge (Claude) can overlay qualitative reasoning on top of the baseline — useful for catching signal conflicts and flagging imminent earnings risk.

## Setup

```bash
pip install -r requirements.txt
```

Add your Anthropic API key to a `.env` file if you want the LLM judge:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

**Streamlit UI**
```bash
streamlit run app.py
```

**CLI**
```bash
python main.py           # prompts for ticker and whether to use the LLM judge
python main.py --llm     # run with LLM judge enabled
```

The UI has two tabs:
- **Analyze** — score a single ticker with a signal breakdown and optional LLM verdict
- **Scan** — rank a watchlist by blended score, with optional LLM overlay on the buys
