# ============================================================
# CONFIGURATION LOADING FUNCTIONS
# ============================================================
"""
Functions for loading network configuration from JSON files.

This module provides:
- Node configuration loading (qubit assignments)
- Route configuration loading (transport paths)
"""

import json
from pathlib import Path
from typing import Dict, Tuple


def load_nodes_config(filepath: Path) -> Dict[int, dict]:
    """
    Load nodes configuration from JSON file.
    
    The nodes config file should have the format:
    {
        "0": {"data": [76], "encoding": [61, 81], "ancilla": [62, 82]},
        "1": {"data": [77], "encoding": [65, 85], "ancilla": [66, 86]},
        ...
    }
    
    Args:
        filepath: Path to the nodes JSON file
        
    Returns:
        Dictionary mapping node_id (int) to qubit assignments:
        {
            0: {"data": [76], "encoding": [61, 81], "ancilla": [62, 82]},
            ...
        }
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    with open(filepath, 'r') as f:
        nodes_raw = json.load(f)
    # Convert string keys to integers
    return {int(k): v for k, v in nodes_raw.items()}


def load_routes_config(filepath: Path) -> Dict[Tuple[int, int], dict]:
    """
    Load transport routes configuration from JSON file.
    
    The routes config file should have the format:
    {
        "0,1": {"movements": [[61,62,63,...], [76,77,...], [81,82,...]]},
        "0,2": {"movements": [[...], [...], [...]]},
        ...
    }
    
    Args:
        filepath: Path to the routes JSON file
        
    Returns:
        Dictionary mapping (src, dst) tuples to route information:
        {
            (0, 1): {"movements": [[...], [...], [...]]},
            ...
        }
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    with open(filepath, 'r') as f:
        routes_raw = json.load(f)
    # Convert "src,dst" string keys to (src, dst) tuple keys
    routes = {}
    for key, value in routes_raw.items():
        src, dst = map(int, key.split(','))
        routes[(src, dst)] = value
    return routes


def load_all_configs(
    nodes_file: Path, 
    routes_file: Path
) -> Tuple[Dict[int, dict], Dict[Tuple[int, int], dict]]:
    """
    Load both nodes and routes configurations.
    
    Convenience function to load all network configuration at once.
    
    Args:
        nodes_file: Path to the nodes JSON file
        routes_file: Path to the routes JSON file
        
    Returns:
        Tuple of (nodes_config, routes_config)
    """
    nodes = load_nodes_config(nodes_file)
    routes = load_routes_config(routes_file)
    return nodes, routes


def print_config_summary(
    nodes: Dict[int, dict], 
    routes: Dict[Tuple[int, int], dict]
) -> None:
    """
    Print a summary of loaded configurations.
    
    Args:
        nodes: Loaded nodes configuration
        routes: Loaded routes configuration
    """
    from .node_utils import get_node_name
    
    print("="*60)
    print("LOADED CONFIGURATIONS")
    print("="*60)
    print(f"\nNodes ({len(nodes)} total):")
    for node_id, qubits in nodes.items():
        print(f"  Node {get_node_name(node_id)}: data={qubits['data']}, "
              f"encoding={qubits['encoding']}, ancilla={qubits['ancilla']}")
    print(f"\nRoutes ({len(routes)} total)")
