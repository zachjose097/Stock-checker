# Central config - all the tunable knobs live here, not scattered in the signals
small_cap_threshold = 2e9
large_cap_threshold = 10e9
high_beta = 1.5
low_beta = 0.8

# Weight of each signal in the blended score - should sum to 1.0
# Fundamentals weighted up for small/mid-cap focus — growth story matters more than
# analyst consensus, which is sparse or absent for smaller names.
# Insider activity earns a meaningful weight for the same reason: for thinly-covered
# small/mid-caps, insider buying is often the best-informed read on the name. It scores
# neutral (0) when there's no insider activity, so the weight only bites when there's signal.
SIGNAL_WEIGHTS = {"momentum": 0.25,
                  "volume": 0.15,
                  "fundamentals": 0.35,
                  "insider": 0.15,
                  "targets": 0.10}

# Score thresholds for the final verdict
# Blended score runs -1 (strong sell) to +1 (strong buy)
BUY_THRESHOLD = 0.25
SELL_THRESHOLD = -0.25

# LLM judge settings
JUDGE_MODEL = "claude-sonnet-4-6"
JUDGE_TEMPERATURE = 0
JUDGE_MAX_TOKENS = 1500

# ntfy channel for notifications, matching the sell_notifier setup
NTFY_URL = "https://ntfy.sh/zach-sell-notifier"
