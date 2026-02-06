#!/usr/bin/env python3
"""Base classes for QEC codes (entanglement swapping)."""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np


@dataclass
class TimeAwareMeasurement:
    """Container for syndrome measurement results with timing metadata."""
    path_edges: List[Tuple[int, int]]
    histogram: np.ndarray
    duration: float
    latency_stats: Dict[str, Any]
    code_type: str = '513_ES'
