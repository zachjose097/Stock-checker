# Zach's Rule-Based Exit System — v1

*Adapted from the Sharpe three-rule sell system, fitted to a UK-based thematic small-cap portfolio run on Trading 212 / HL ISA. Goal: no real-time emotional sell decisions, ever.*

---

## Step 0 — Classify Every Position at Entry (or Right Now, for Existing Holdings)

Every holding gets exactly one tier, written in the journal. The tier locks until the trade is closed.

| Tier | What it is | Chart & rules | Examples from current book |
|------|-----------|---------------|---------------------------|
| **A — Core thesis** | Multi-year structural rerate; entered off a weekly base breakout or held for the theme | **Weekly** chart, weekly closes | OUST core, BKSY, long-hold photonics names |
| **B — Tactical swing** | Catalyst pop, episodic pivot, breakout; expected hold 3 days–several weeks | **Daily** chart, daily closes | Earnings-reaction adds, breakout entries |
| **C — Speculative punt** | Binary/news-driven, low conviction, small size (SPACs, MRLN-type) | **Daily** chart + hard catalyst kill criteria | MRLN |

**Hard rule: the tier (and therefore timeframe) never changes mid-trade.** If you catch yourself wanting to "move it to weekly" while it's falling, that is the failure mode the rule exists to stop.

---

## The Three Exit Rules (applied on the tier's timeframe)

### Rule 1 — Round-Number Trim (20%)
At entry, place a GTC limit sell for **20% of the position** at the next round number **≥30% above entry**.

Ladder: $2 → $5 → $10 → $20 → $50 → $100 → $150 → $200 → $300 → $500 (then $1000, $1500…). For UK/EU listings use the equivalent £/€/SEK ladder.

- No qualifying level → skip Rule 1; Rule 2 becomes the first trim.
- Tier A positions: Rule 1 applies only to the first leg. Re-adds on weekly pullbacks don't get a new round-number order (avoids shaving the structural runner).

### Rule 2 — 4EMA-of-Highs Trim (20% of remaining)
Setup: EMA, length 4, **source = high**, on the tier's timeframe.

- Position must first spend **3+ closes above** the line.
- A close below it → sell **20% of what remains**, in the last 5 minutes of the session.
- The 3-above clock **resets after every trim**.
- **2-period cooldown** between any two trims (Rule 1 ↔ Rule 2). One trim per structural event.

### Rule 3 — 20 EMA Full Exit
Setup: EMA, length 20, **source = close**, same timeframe.

- Price below the 20 EMA at the close-check → **exit everything remaining** before the close.
- No second chances. No "see if it bounces." No dropping to a faster chart to justify holding, no jumping to a slower one to justify not selling.

---

## Stops

- **At entry:** stop = low of the entry day (Tier B/C) or low of the entry week (Tier A).
- **After the first trim fires:** move the stop to break-even (default). Leave it at original LOD only if pre-written in the journal at entry with a reason.
- A position repeatedly poking at the original stop = the setup isn't working. Honour the stop; don't widen it.

## Thesis Kill Criteria Override (your existing Commandments)

A **fundamental kill criterion** firing (thesis broken: lost flagship customer, dilutive raise that breaks the model, fraud, tech leapfrogged) **overrides the chart and exits the full position at the next close — any tier, any timeframe.** The chart rules manage price risk; the kill criteria manage thesis risk. Either one can end the trade.

---

## The Daily Routine (UK clock)

US cash close = 9:00pm UK (BST) / 9:30pm in winter (GMT).

1. **During the session: nothing.** No sells, no order-touching. Only pre-set GTC round-number limits may execute.
2. **8:50pm UK — the check (Tier B/C, daily):**
   - Below the 20 EMA? → market-sell the remainder now.
   - Else: closed below the 4EMA-high, 3+ days above, cooldown clear? → sell 20% of remaining now.
   - Else: do nothing.
3. **Friday 8:50pm UK — the weekly check (Tier A):** same two questions on the weekly chart. Tier A is touched at most once a week.
4. **After close:** one journal line per position — date, signal (or "none"), action taken, remaining size.
5. Walk away.

---

## Trading 212 / ISA Mechanics

- GTC = expiration **"Never"** on a limit order. Set the Rule 1 order the minute the entry fills.
- T212 can't attach a stop **and** a limit to the same shares — shares are reserved per order. **Split:** limit sell on the 20% trim tranche, stop order on the other 80%.
- Rule 2 / Rule 3 sells are manual market orders at the 8:50pm check — no special order type.
- Everything inside the ISA: trims have **zero CGT consequence**, so never let tax thinking delay a signal.
- HL positions: same rules; HL supports limit and stop orders on US stock too, just check FX fee drag on small trims — for HL, consider trimming in fewer, larger steps (e.g. one 36% trim instead of two 20% trims) to halve FX costs.

---

## Edge Cases

- **Gap-down below the 20 EMA at the open:** do **not** sell the open. Wait for the 8:50pm check and act on the near-final print.
- **Earnings mid-trade (Tier B/C):** trim to a small runner (~5% of original size as the default) before the print. Document the size and reason. Tier A: judgement call, but never carry a full-size Tier B position through a binary event.
- **Re-entry after a Rule 3 exit:** only with **a fresh fundamental catalyst AND a fresh technical setup, both**. A reclaim of the EMA alone is not a signal. Re-entry = brand-new trade: new tier, new stop, new round-number lookup.
- **Index filter:** SPX below its daily 20 EMA = no new Tier B entries. Exits always run regardless of tape.

---

## The Three Hard Rules

1. **No selling during market hours** — except pre-set round-number GTC orders and the thesis-kill override.
2. **No overriding signals.** "The market looks different today" is the signal talking you out of the rule.
3. **No switching timeframes/tiers mid-trade.**

Any sell outside this system is logged as a **rule violation**, whatever the P&L says.

---

## 90-Day Trial

Run it for one quarter. Log every signal, every action, and every violation. At the end, measure the gap between what the rules said and what you actually did. That gap — not the entry picking — is the edge being recovered.

*v1 — June 2026. Review after the first quarter; change rules only between trades, never during one.*
