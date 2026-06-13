# Central config - all the tunable knobs live here, not scattered in the signals

# Weight of each signal in the blended score - should sum to 1.0
# Fundamentals weighted up for small/mid-cap focus — growth story matters more than
# analyst consensus, which is sparse or absent for smaller names.
SIGNAL_WEIGHTS = {"momentum": 0.35,
                  "volume": 0.20,
                  "fundamentals": 0.40,
                  "targets": 0.05}

# Score thresholds for the final verdict
# Blended score runs -1 (strong sell) to +1 (strong buy)
BUY_THRESHOLD = 0.25
SELL_THRESHOLD = -0.25

# LLM judge settings
JUDGE_MODEL = "claude-sonnet-4-6"
JUDGE_TEMPERATURE = 0.2
JUDGE_MAX_TOKENS = 1000

# ntfy channel for notifications, matching the sell_notifier setup
NTFY_URL = "https://ntfy.sh/zach-sell-notifier"