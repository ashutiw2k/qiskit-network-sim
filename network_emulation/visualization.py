# ============================================================
# VISUALIZATION & RESULTS FUNCTIONS
# ============================================================
"""
Visualization and results export functions for network experiments.

This module provides:
- Heatmap plotting for syndrome matrices
- Comparison plots across initial states
- Bar charts for average fidelities
- Text summaries and JSON export
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .node_utils import (
    NODE_NAMES, STATE_LABELS, NUM_NODES,
    node_name, route_name, route_key
)


# ============================================================
# PLOTTING FUNCTIONS
# ============================================================

def plot_syndrome_matrix(
    matrix: np.ndarray,
    title: str = "Syndrome '00' Matrix",
    state_label: str = "",
    figsize: Tuple[int, int] = (10, 8),
    show: bool = True,
    dark_theme: bool = True
) -> plt.Figure:
    """
    Plot a syndrome matrix as a heatmap.
    
    Creates a color-coded visualization where:
    - Green = high syndrome '00' rate (good fidelity)
    - Red = low syndrome '00' rate (poor fidelity)
    - Gray '-' = diagonal (no self-routes)
    
    Args:
        matrix: NxN numpy array of syndrome percentages (NaN on diagonal)
        title: Main plot title
        state_label: Initial state label for subtitle (e.g., '|0⟩')
        figsize: Figure size as (width, height) tuple
        show: Whether to call plt.show() after plotting
        dark_theme: Whether to use dark background theme
        
    Returns:
        matplotlib Figure object
        
    Example:
        >>> fig = plot_syndrome_matrix(
        ...     matrix, title="Transport Fidelity",
        ...     state_label="|0⟩"
        ... )
        >>> fig.savefig("fidelity_matrix.png", dpi=300)
    """
    fig, ax = plt.subplots(figsize=figsize)
    
    if dark_theme:
        fig.patch.set_facecolor('#1a1a2e')
        ax.set_facecolor('#1a1a2e')
        text_color = 'white'
    else:
        text_color = 'black'
    
    # Create heatmap
    im = ax.imshow(matrix, cmap='RdYlGn', vmin=0, vmax=100)
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Syndrome '00' (%)", color=text_color, fontsize=12)
    cbar.ax.yaxis.set_tick_params(color=text_color)
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color=text_color)
    
    # Add text annotations
    num_nodes = matrix.shape[0]
    for src in range(num_nodes):
        for dst in range(num_nodes):
            if not np.isnan(matrix[src, dst]):
                val = matrix[src, dst]
                cell_text_color = 'white' if val < 50 else 'black'
                ax.text(dst, src, f'{val:.1f}%', ha='center', va='center',
                       fontsize=10, fontweight='bold', color=cell_text_color)
            else:
                ax.text(dst, src, '-', ha='center', va='center',
                       fontsize=12, color='gray')
    
    # Labels
    ax.set_xticks(range(num_nodes))
    ax.set_yticks(range(num_nodes))
    ax.set_xticklabels([f'Node {node_name(i)}' for i in range(num_nodes)], 
                       color=text_color, fontsize=11)
    ax.set_yticklabels([f'Node {node_name(i)}' for i in range(num_nodes)], 
                       color=text_color, fontsize=11)
    ax.set_xlabel('Destination (Sink)', color=text_color, fontsize=14)
    ax.set_ylabel('Source', color=text_color, fontsize=14)
    
    full_title = title
    if state_label:
        full_title += f"\nInitial State: {state_label}"
    ax.set_title(full_title, color=text_color, fontsize=16, fontweight='bold')
    
    plt.tight_layout()
    if show:
        plt.show()
    return fig


def plot_all_states_comparison(
    all_matrices: Dict[str, np.ndarray],
    state_labels: Dict[str, str] = STATE_LABELS,
    figsize: Tuple[int, int] = (14, 12),
    show: bool = True
) -> plt.Figure:
    """
    Plot 2x2 grid of heatmaps comparing all initial states.
    
    Creates a side-by-side comparison of transport fidelity
    for different initial states.
    
    Args:
        all_matrices: Dictionary mapping state -> syndrome matrix
        state_labels: Dictionary mapping state -> display label
        figsize: Figure size tuple
        show: Whether to display the figure
        
    Returns:
        matplotlib Figure object
    """
    states = list(all_matrices.keys())
    fig, axes = plt.subplots(2, 2, figsize=figsize)
    fig.patch.set_facecolor('#1a1a2e')
    
    for ax, state in zip(axes.flatten(), states):
        ax.set_facecolor('#1a1a2e')
        matrix = all_matrices[state]
        num_nodes = matrix.shape[0]
        
        im = ax.imshow(matrix, cmap='RdYlGn', vmin=0, vmax=100)
        
        # Add text annotations
        for src in range(num_nodes):
            for dst in range(num_nodes):
                if not np.isnan(matrix[src, dst]):
                    val = matrix[src, dst]
                    text_color = 'white' if val < 50 else 'black'
                    ax.text(dst, src, f'{val:.0f}', ha='center', va='center',
                           fontsize=9, fontweight='bold', color=text_color)
                else:
                    ax.text(dst, src, '-', ha='center', va='center',
                           fontsize=10, color='gray')
        
        ax.set_xticks(range(num_nodes))
        ax.set_yticks(range(num_nodes))
        ax.set_xticklabels([node_name(i) for i in range(num_nodes)], color='white')
        ax.set_yticklabels([node_name(i) for i in range(num_nodes)], color='white')
        ax.set_xlabel('Destination', color='white', fontsize=11)
        ax.set_ylabel('Source', color='white', fontsize=11)
        
        avg = np.nanmean(matrix)
        ax.set_title(f"State: {state_labels[state]}\nAvg: {avg:.1f}%",
                     color='white', fontsize=13, fontweight='bold')
    
    # Add colorbar
    fig.subplots_adjust(right=0.85)
    cbar_ax = fig.add_axes([0.88, 0.15, 0.03, 0.7])
    cbar = fig.colorbar(im, cax=cbar_ax)
    cbar.set_label("Syndrome '00' (%)", color='white', fontsize=12)
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
    
    fig.suptitle("Transport Fidelity Comparison Across Initial States",
                 color='white', fontsize=16, fontweight='bold', y=0.98)
    plt.tight_layout(rect=[0, 0, 0.85, 0.95])
    
    if show:
        plt.show()
    return fig


def plot_state_averages_bar(
    all_matrices: Dict[str, np.ndarray],
    state_labels: Dict[str, str] = STATE_LABELS,
    show: bool = True
) -> plt.Figure:
    """
    Plot bar chart comparing average fidelity across states.
    
    Args:
        all_matrices: Dictionary of state -> syndrome matrix
        state_labels: Dictionary of state -> display label
        show: Whether to display the figure
        
    Returns:
        matplotlib Figure object
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
    
    states = list(all_matrices.keys())
    averages = [np.nanmean(all_matrices[s]) for s in states]
    labels = [state_labels[s] for s in states]
    colors = ['#3498db', '#e74c3c', '#2ecc71', '#9b59b6']
    
    bars = ax.bar(labels, averages, color=colors[:len(states)], 
                  edgecolor='white', linewidth=2)
    
    for bar, avg in zip(bars, averages):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{avg:.1f}%', ha='center', va='bottom', color='white',
                fontsize=14, fontweight='bold')
    
    ax.set_ylabel("Average Syndrome '00' Rate (%)", color='white', fontsize=14)
    ax.set_xlabel("Initial State", color='white', fontsize=14)
    ax.set_title("Average Transport Fidelity by Initial State",
                 color='white', fontsize=16, fontweight='bold')
    ax.tick_params(colors='white', labelsize=12)
    ax.set_ylim(0, 100)
    ax.grid(axis='y', alpha=0.3, color='white')
    
    plt.tight_layout()
    if show:
        plt.show()
    return fig


# ============================================================
# TEXT DISPLAY FUNCTIONS
# ============================================================

def print_matrix_summary(
    matrix: np.ndarray,
    title: str = "Matrix Summary"
) -> None:
    """
    Print formatted summary of a syndrome matrix.
    
    Args:
        matrix: NxN numpy array of syndrome percentages
        title: Title for the summary output
    """
    print(f"\n{title}")
    print("-"*50)
    
    # Header
    header = "      " + "    ".join([f"→{node_name(i)}" for i in range(matrix.shape[0])])
    print(header)
    
    # Rows
    for src in range(matrix.shape[0]):
        row_str = f"{node_name(src)}:   "
        for dst in range(matrix.shape[1]):
            if np.isnan(matrix[src, dst]):
                row_str += "  -  "
            else:
                row_str += f"{matrix[src, dst]:5.1f}"
        print(row_str)
    
    # Statistics
    print(f"\nStatistics:")
    print(f"  Average: {np.nanmean(matrix):.1f}%")
    best_idx = np.unravel_index(np.nanargmax(matrix), matrix.shape)
    worst_idx = np.unravel_index(np.nanargmin(matrix), matrix.shape)
    print(f"  Best:    {route_name(*best_idx)} = {np.nanmax(matrix):.1f}%")
    print(f"  Worst:   {route_name(*worst_idx)} = {np.nanmin(matrix):.1f}%")


def print_full_comparison(
    all_matrices: Dict[str, np.ndarray],
    state_labels: Dict[str, str] = STATE_LABELS
) -> None:
    """
    Print comprehensive comparison table for all states.
    
    Args:
        all_matrices: Dictionary of state -> syndrome matrix
        state_labels: Dictionary of state -> display label
    """
    print("="*80)
    print("SYNDROME '00' PERCENTAGE - COMPARISON ACROSS ALL STATES")
    print("="*80)
    
    print("\nSUMMARY:")
    print("-"*80)
    print(f"{'State':<10} {'Average':>10} {'Best Route':>15} {'Best %':>10} "
          f"{'Worst Route':>15} {'Worst %':>10}")
    print("-"*80)
    
    for state, matrix in all_matrices.items():
        avg = np.nanmean(matrix)
        best_idx = np.unravel_index(np.nanargmax(matrix), matrix.shape)
        worst_idx = np.unravel_index(np.nanargmin(matrix), matrix.shape)
        print(f"{state_labels[state]:<10} {avg:>10.1f}% {route_name(*best_idx):>15} "
              f"{np.nanmax(matrix):>9.1f}% {route_name(*worst_idx):>15} "
              f"{np.nanmin(matrix):>9.1f}%")
    print("-"*80)


# ============================================================
# EXPORT FUNCTIONS
# ============================================================

def save_results_to_json(
    all_matrices: Dict[str, np.ndarray],
    backend_name: str,
    num_shots: int,
    output_dir: Path,
    connection_tuples: List[Tuple[int, int]],
    state_labels: Dict[str, str] = STATE_LABELS,
    num_nodes: int = NUM_NODES,
    additional_metadata: Optional[dict] = None
) -> Path:
    """
    Save experiment results to JSON file.
    
    Creates a structured JSON file with:
    - Experiment metadata (timestamp, backend, parameters)
    - Full matrices for each initial state
    - Per-route breakdown for each state
    
    Args:
        all_matrices: Dictionary of state -> syndrome matrix
        backend_name: Name of backend used
        num_shots: Shots per circuit
        output_dir: Directory to save file (will be created if needed)
        connection_tuples: List of tested routes
        state_labels: State display labels
        num_nodes: Number of network nodes
        additional_metadata: Optional extra metadata to include
        
    Returns:
        Path to saved file
        
    Example:
        >>> path = save_results_to_json(
        ...     all_matrices, backend_name="fake_fez",
        ...     num_shots=4096, output_dir=Path("./outputs"),
        ...     connection_tuples=CONNECTIONS
        ... )
        >>> print(f"Saved to: {path}")
    """
    output_dir.mkdir(exist_ok=True, parents=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = output_dir / f'syndrome_results_{timestamp}.json'
    
    results = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'backend': backend_name,
            'num_shots': num_shots,
            'num_nodes': num_nodes,
            'num_routes': len(connection_tuples),
            'initial_states': list(all_matrices.keys()),
            'state_labels': state_labels,
            'node_names': NODE_NAMES
        },
        'matrices': {},
        'by_route': {},
        'summary': {}
    }
    
    # Add additional metadata if provided
    if additional_metadata:
        results['metadata'].update(additional_metadata)
    
    # Convert matrices (NaN -> None for JSON)
    for state, matrix in all_matrices.items():
        results['matrices'][state] = [
            [None if np.isnan(v) else round(v, 2) for v in row]
            for row in matrix
        ]
        
        results['by_route'][state] = {
            route_key(src, dst): round(matrix[src, dst], 2) 
            if not np.isnan(matrix[src, dst]) else None
            for src, dst in connection_tuples
        }
        
        # Add summary statistics
        results['summary'][state] = {
            'average': round(np.nanmean(matrix), 2),
            'min': round(np.nanmin(matrix), 2),
            'max': round(np.nanmax(matrix), 2),
            'std': round(np.nanstd(matrix), 2)
        }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"Results saved to: {output_file}")
    print(f"File size: {output_file.stat().st_size / 1024:.1f} KB")
    
    return output_file


def load_results_from_json(filepath: Path) -> dict:
    """
    Load previously saved experiment results from JSON.
    
    Args:
        filepath: Path to the JSON results file
        
    Returns:
        Dictionary with results data (matrices as lists, not numpy arrays)
        
    Note:
        Use results_to_matrices() to convert loaded matrices back to numpy.
    """
    with open(filepath, 'r') as f:
        return json.load(f)


def results_to_matrices(results: dict) -> Dict[str, np.ndarray]:
    """
    Convert loaded JSON results back to numpy matrices.
    
    Args:
        results: Results dictionary loaded from JSON
        
    Returns:
        Dictionary of state -> np.ndarray matrices
    """
    matrices = {}
    for state, matrix_list in results['matrices'].items():
        matrix = np.array([
            [np.nan if v is None else v for v in row]
            for row in matrix_list
        ])
        matrices[state] = matrix
    return matrices
