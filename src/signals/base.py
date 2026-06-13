class SignalResult:
    '''Immutable result from a single signal evaluation.

    score is the primary output: a float in [-1.0, +1.0] where -1 is maximum bearish
    conviction, 0 is neutral, and +1 is maximum bullish conviction. The scale is enforced
    here rather than in each signal so violations are caught at the source — a score outside
    the range is always a bug in the signal's arithmetic, not a valid edge case.

    values holds the intermediate numbers that produced the score (RSI level, PE ratio,
    upside % etc.) so the LLM judge and any downstream consumer can reason over the raw
    inputs, not just the summary score. A signal at -0.4 means very different things when
    RSI is 28 (oversold bounce candidate) vs when every sub-metric is negative.
    '''

    def __init__(self, name, score, values=None, note=""):
        self.name   = name
        self.score  = score
        self.values = values if values else {}
        self.note   = note

        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"{self.name}: score {self.score} is outside [-1.0, 1.0]")


class Signal:
    '''Base class for all signals.

    A signal takes market data (a price DataFrame or a fundamentals dict) and returns
    a SignalResult. The -1 to +1 score contract is the only thing all signals must agree
    on — the internal implementation (which indicators, which thresholds) is entirely up
    to the subclass.

    Subclasses must override name and implement evaluate(). Calling evaluate() on the base
    class raises NotImplementedError so a forgotten implementation surfaces immediately
    rather than silently returning a neutral score.
    '''

    name = "unnamed"

    def evaluate(self, data):
        raise NotImplementedError(f"{self.name}: evaluate() not implemented")

    def clamp(self, value, low=-1.0, high=1.0):
        '''Constrain a raw score accumulator to the valid SignalResult range.

        Signal scoring is additive — each sub-component adds or subtracts a partial score.
        Rounding and edge cases can push the running total slightly past ±1.0. clamp() is
        the last step before constructing the SignalResult. Calling it unconditionally is
        cheaper than debugging a contract violation caused by an unusual combination of
        sub-scores that looked fine individually.
        '''
        return max(low, min(high, value))
