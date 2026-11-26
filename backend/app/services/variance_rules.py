"""Central operational heuristics for deterministic variance intelligence.

These are initial tunable defaults, not statistically validated business rules.
"""
from decimal import Decimal

BASELINE_PERIODS = 8
MIN_BASELINE_PERIODS = 4
MAX_BASELINE_DAYS = 730
MAD_MULTIPLIER = Decimal("3.5")
MIN_ABSOLUTE_VARIANCE = Decimal("1")
MIN_RELATIVE_VARIANCE_PERCENT = Decimal("10")
MIN_OPERATIONAL_RATE_POINT_CHANGE = Decimal("5")
MIN_BRANCH_PEERS = 3
SEVERITY_THRESHOLDS = (
    (Decimal("6"), 4, "CRITICAL"),
    (Decimal("3"), 3, "HIGH"),
    (Decimal("2"), 2, "MEDIUM"),
    (Decimal("1"), 1, "LOW"),
)

