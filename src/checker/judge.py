import json
from datetime import date, datetime
import anthropic

from . import config


class Judge:
    '''LLM-powered overlay that synthesises the signal scores into a final verdict.

    The deterministic signals (momentum, volume, fundamentals, targets) each produce a
    score in [-1, +1] that gets combined via a fixed weighted average in main.py. The
    Judge's role is complementary: it reasons over all signals simultaneously, notices
    where they agree or conflict, and can weigh context that fixed weights can't capture —
    particularly upcoming earnings, which can invalidate any technical or fundamental setup
    regardless of how strong the signal scores look.
    '''

    def __init__(self):
        # Client reads ANTHROPIC_API_KEY from the environment automatically
        self.client = anthropic.Anthropic()

    def build_summary(self, ticker, results, catalysts=None):
        '''Serialise signal results and catalyst context into a plain dict for the model.

        We include the full values dict from each signal (not just the score) so the model
        sees the actual numbers — RSI level, PE ratio, upside % — rather than just a
        summarised score. This lets it reason about conflicts: a momentum score of -0.3
        driven by a recent death cross is very different from one driven by an overbought RSI,
        and the model needs that texture to weight the signals sensibly.

        catalysts (earnings date, EPS estimates) are included so the "respect upcoming
        earnings" instruction in the prompt is backed by real data, not a hollow reminder.
        '''
        summary = {
            "ticker":    ticker,
            "signals":   {},
            "catalysts": catalysts or {},
        }

        for r in results:
            summary["signals"][r.name] = {
                "score":  round(r.score, 3),
                "values": r.values,
                "note":   r.note,
            }

        return summary

    # An earnings report only invalidates a setup if it lands before the trade has time
    # to play out. A report tomorrow is real binary risk; one 6+ weeks away usually isn't —
    # the position can be reassessed long before then. We only escalate to a hard caution
    # inside this window (calendar days).
    EARNINGS_CAUTION_DAYS = 10

    def _days_to_earnings(self, catalysts):
        '''Return calendar days until the next earnings date, or None if unknown/past-parsing.

        yfinance hands back the date as a date/datetime/Timestamp/string depending on the
        path; we coerce defensively and return None rather than raising if it is unparseable.
        '''
        raw = (catalysts or {}).get("earnings_date")
        if raw is None:
            return None
        try:
            if isinstance(raw, datetime):
                d = raw.date()
            elif isinstance(raw, date):
                d = raw
            else:
                d = datetime.fromisoformat(str(raw)[:10]).date()
        except (ValueError, TypeError):
            return None
        return (d - date.today()).days

    def build_prompt(self, summary):
        '''Build the instruction + data prompt for the model.

        Design choices:
        - Earnings caution scales with proximity. Rather than treating any future earnings
          date as a blanket reason to hold, we compute days-to-earnings and only escalate to
          a hard caution inside EARNINGS_CAUTION_DAYS. A catalyst weeks out is noted but not
          allowed to veto an otherwise strong, aligned setup — the position can be revisited
          well before the report.
        - We frame "hold" as the verdict for genuinely mixed or weak signals, not as a default
          hedge against the ordinary uncertainty that every position carries. Without this the
          model reflexively holds anything with any risk attached, which is almost everything.
        - We ask for a strict JSON-only response so parse_verdict can load it directly.
          Any surrounding text (preamble, chain-of-thought) would break the parse.
        - Temperature is set low in config (0.2) to keep verdicts stable across runs on
          the same input — this is a decision-support tool, not a creative one.
        '''
        today = date.today().isoformat()
        days = self._days_to_earnings(summary.get("catalysts"))

        if days is not None and 0 <= days <= self.EARNINGS_CAUTION_DAYS:
            earnings_guidance = (
                f"Earnings are imminent — about {days} day(s) away. This is real binary risk: "
                "even a strong setup can reverse sharply on a miss, so let it weigh heavily "
                "against initiating a new position now."
            )
        elif days is not None and days > self.EARNINGS_CAUTION_DAYS:
            earnings_guidance = (
                f"The next earnings date is roughly {days} days out — far enough that the "
                "position can be reassessed well before then. Note it as background risk, but "
                "do NOT let a distant earnings date by itself downgrade an otherwise strong, "
                "aligned setup to a hold."
            )
        else:
            earnings_guidance = (
                "No upcoming earnings date is in play, so do not factor earnings risk in."
            )

        instructions = (
            f"Today's date is {today}. "
            "You are a decisive equity analyst who acts on the weight of the evidence. Below "
            "is a JSON summary of signal scores for one stock. Each signal score runs from -1 "
            "(strong sell) to +1 (strong buy), with the raw numbers behind it.\n\n"
            "Weigh the signals and note where they agree or conflict. When the signals point "
            "the same way, the aggregate edge is meaningfully strong (not merely positive or "
            "negative), and there is no strong contradicting signal, commit to that direction "
            "— a buy or a sell. Reserve 'hold' for cases where the signals genuinely conflict, "
            "are uniformly weak, or agree only marginally; do not use it as a hedge against the "
            "ordinary risk that every position carries.\n\n"
            f"{earnings_guidance}\n\n"
            "In addition to your verdict, provide realistic price targets grounded in the "
            "signal data (analyst targets, momentum, fundamentals). For each target:\n"
            "- near_term_target: a price the stock could reach in the near term (weeks to ~3 months), "
            "expressed as a number. Use null if the setup does not support a directional target.\n"
            "- near_term_timeframe: plain-English timeframe to reach it, e.g. '3-6 weeks'.\n"
            "- long_term_target: a price achievable over a longer horizon (6-18 months), as a number. "
            "Use null if there is insufficient basis to project.\n"
            "- long_term_timeframe: plain-English timeframe, e.g. '9-12 months'.\n"
            "Base targets on the analyst mean/high from the targets signal and the stock's "
            "momentum and fundamental trajectory. Do not invent figures — if the data is too "
            "thin, set the target to null and omit the timeframe.\n\n"
            "Respond ONLY with a JSON object, no other text, in this exact shape:\n"
            '{"verdict": "buy" | "hold" | "sell", '
            '"confidence": <number 0 to 1>, '
            '"reasoning": "<two or three sentences>", '
            '"near_term_target": <number or null>, '
            '"near_term_timeframe": "<e.g. 4-6 weeks or null>", '
            '"long_term_target": <number or null>, '
            '"long_term_timeframe": "<e.g. 9-12 months or null>"}\n\n'
            "Here is the data:\n"
        )

        return instructions + json.dumps(summary, indent=2, default=str)

    def parse_verdict(self, text):
        '''Parse the model's JSON response into a dict.

        The model is instructed to return bare JSON, but code fences (```json ... ```) can
        appear anyway — particularly if the model's system prompt or a prior turn nudged it
        toward markdown formatting. We strip them defensively rather than assuming perfect
        compliance.

        On a parse failure we return a neutral hold with confidence 0.0 rather than raising.
        A parse error is a recoverable edge case; crashing the caller over a formatting
        quirk would be worse than returning a conservative "hold" signal.
        '''
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lstrip().startswith("json"):
                cleaned = cleaned.lstrip()[4:]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "verdict":    "hold",
                "confidence": 0.0,
                "reasoning":  "could not parse model response: " + text[:200],
            }

    def decide(self, ticker, results, catalysts=None):
        '''Run the LLM judge and return a verdict dict with keys verdict, confidence, reasoning.

        catalysts (optional dict from MarketData.get_catalysts()) is forwarded into the
        summary so the model can factor in earnings dates and estimate revisions.
        '''
        summary = self.build_summary(ticker, results, catalysts=catalysts)
        prompt  = self.build_prompt(summary)

        message = self.client.messages.create(
            model       = config.JUDGE_MODEL,
            max_tokens  = config.JUDGE_MAX_TOKENS,
            temperature = config.JUDGE_TEMPERATURE,
            messages    = [{"role": "user", "content": prompt}],
        )

        text    = message.content[0].text
        verdict = self.parse_verdict(text)

        return verdict
