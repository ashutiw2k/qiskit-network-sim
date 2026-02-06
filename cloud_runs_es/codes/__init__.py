#!/usr/bin/env python3
"""QEC codes package for cloud runs (entanglement swapping)."""

from .base import TimeAwareMeasurement
from .code_513 import Code513
from .code_713 import Code713
from .code_823 import Code823
from .code_913 import Code913

AVAILABLE_CODES = {
    '513': Code513,
    '713': Code713,
    '823': Code823,
    '913': Code913,
}

__all__ = [
    'TimeAwareMeasurement',
    'Code513',
    'Code713',
    'Code823',
    'Code913',
    'AVAILABLE_CODES',
]
