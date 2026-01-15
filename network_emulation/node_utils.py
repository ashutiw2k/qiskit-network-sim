# ============================================================
# NODE DEFINITIONS & HELPER FUNCTIONS
# ============================================================
"""
Node definitions and utility functions for the quantum network emulation.

This module provides:
- Node enum for network node identifiers
- Helper functions for node/route name formatting
- Connection tuple generation
"""

import itertools
from enum import IntEnum
from typing import Dict, List, Tuple


class Node(IntEnum):
    """Enum for network node identifiers."""
    A = 0
    B = 1
    C = 2
    D = 3
    E = 4
    F = 5


# Lookup dictionaries for display
NODE_NAMES: Dict[int, str] = {n.value: n.name for n in Node}  # {0: 'A', 1: 'B', ...}
NODE_IDS: Dict[str, int] = {n.name: n.value for n in Node}    # {'A': 0, 'B': 1, ...}
NUM_NODES = len(Node)

# Initial states and labels
INITIAL_STATES = ['0', '1', '+', '-']
STATE_LABELS = {'0': '|0⟩', '1': '|1⟩', '+': '|+⟩', '-': '|−⟩'}

# Generate all connection tuples (source, sink pairs)
CONNECTION_TUPLES = list(itertools.permutations(range(NUM_NODES), 2))


def node_name(node_id: int) -> str:
    """
    Convert node ID to name.
    
    Args:
        node_id: Integer node identifier (0-5)
        
    Returns:
        Node name string (e.g., 0 -> 'A')
    """
    return NODE_NAMES.get(node_id, str(node_id))


def route_name(src: int, dst: int) -> str:
    """
    Format route as readable string with arrow.
    
    Args:
        src: Source node ID
        dst: Destination node ID
        
    Returns:
        Formatted route string (e.g., (0,1) -> 'A→B')
    """
    return f"{node_name(src)}→{node_name(dst)}"


def route_key(src: int, dst: int) -> str:
    """
    Format route as JSON-safe key string.
    
    Args:
        src: Source node ID
        dst: Destination node ID
        
    Returns:
        Route key string (e.g., (0,1) -> 'A->B')
    """
    return f"{node_name(src)}->{node_name(dst)}"


def get_connection_tuples(num_nodes: int = NUM_NODES) -> List[Tuple[int, int]]:
    """
    Generate all source-sink connection pairs.
    
    Args:
        num_nodes: Number of nodes in the network
        
    Returns:
        List of (source, sink) tuples for all permutations
    """
    return list(itertools.permutations(range(num_nodes), 2))
