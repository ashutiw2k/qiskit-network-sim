# =============================================================================
# Quantum Error Correction Codes
# =============================================================================
"""
This subpackage contains implementations of various quantum error correction codes.

Available codes:
- code_513: [[5,1,3]] perfect code (corrects any single-qubit error)
"""

from .code_513 import (
    STABILIZERS_513,
    SYNDROME_TO_CORRECTION_513,
    apply_encoding_513,
    apply_decoding_513,
    apply_syndrome_extraction_513,
    apply_syndrome_measurement_513,
    apply_classical_correction_513,
)

__all__ = [
    'STABILIZERS_513',
    'SYNDROME_TO_CORRECTION_513',
    'apply_encoding_513',
    'apply_decoding_513',
    'apply_syndrome_extraction_513',
    'apply_syndrome_measurement_513',
    'apply_classical_correction_513',
]
