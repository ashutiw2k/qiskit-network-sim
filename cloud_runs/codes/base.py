#!/usr/bin/env python3
"""Base classes and data containers for QEC codes."""

from __future__ import annotations


class TimeAwareMeasurement:
    """Container for syndrome measurement results."""

    def __init__(self, path_edges, histogram, duration, latency_stats=None, code_type='513'):
        """
        Container for syndrome measurement results.

        :param path_edges: List of tuples representing the path, e.g., [(0,1), (1,2)]
        :param histogram: Numpy array of syndrome counts.
        :param duration: The duration or average latency of this measurement (seconds).
        :param latency_stats: A dictionary with 'max', 'std', 'count'.
        :param code_type: String indicating the code type, e.g., '513', '713'.
        """
        self.path_edges = path_edges
        self.histogram = histogram
        self.duration = duration
        self.latency_stats = latency_stats
        self.code_type = code_type
