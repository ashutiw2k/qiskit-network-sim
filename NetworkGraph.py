"""
NetworkGraph.py - Quantum Network Graph Definition and Pathfinding

This module provides the QuantumNetworkGraph class for representing quantum networks
where each node is a multi-qubit register connected by quantum channels (edges).
"""

import json
from typing import List, Tuple, Dict, Optional, Union
from pathlib import Path

import rustworkx as rx
from rustworkx.visualization import mpl_draw
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


class QuantumNetworkGraph:
    """
    Represents a quantum network where each node is a multi-qubit register.
    
    Nodes are connected by edges representing quantum channels. Each edge
    has an associated error rate for SWAP operations. When transporting
    quantum states between nodes, ALL qubits in the register are swapped
    in parallel (q0↔q0, q1↔q1, ...).
    
    Example JSON config:
    {
        "qubits_per_node": 3,
        "nodes": ["SOURCE", "A", "SINK", "E", "D", "C"],
        "source": "SOURCE",
        "sink": "SINK",
        "edges": [
            ["SOURCE", "A", 0.06],
            ["A", "SINK", 0.06],
            ["SOURCE", "E", 0.01]
        ]
    }
    """
    
    def __init__(
        self,
        nodes: List[str],
        edges: List[Tuple[str, str, float]],
        source: str,
        sink: str,
        qubits_per_node: int = 1
    ):
        """
        Initialize a quantum network graph.
        
        Args:
            nodes: List of node names (index becomes node ID)
            edges: List of (from_name, to_name, error_rate) tuples
            source: Name of the source node
            sink: Name of the sink node
            qubits_per_node: Number of qubits per register/node
        """
        self._qubits_per_node = qubits_per_node
        self._node_names = list(nodes)
        self._name_to_id = {name: idx for idx, name in enumerate(nodes)}
        
        # Validate source and sink
        if source not in self._name_to_id:
            raise ValueError(f"Source node '{source}' not found in nodes")
        if sink not in self._name_to_id:
            raise ValueError(f"Sink node '{sink}' not found in nodes")
        
        self._source_id = self._name_to_id[source]
        self._sink_id = self._name_to_id[sink]
        
        # Build the directed graph with bidirectional edges
        self._graph = rx.PyDiGraph()
        self._graph.add_nodes_from(list(range(len(nodes))))
        
        # Store edge info and add to graph
        self._edge_errors: Dict[Tuple[int, int], float] = {}
        
        for edge in edges:
            from_name, to_name, error_rate = edge
            
            if from_name not in self._name_to_id:
                raise ValueError(f"Edge references unknown node '{from_name}'")
            if to_name not in self._name_to_id:
                raise ValueError(f"Edge references unknown node '{to_name}'")
            
            from_id = self._name_to_id[from_name]
            to_id = self._name_to_id[to_name]
            
            # Add bidirectional edges
            self._graph.add_edge(from_id, to_id, error_rate)
            self._graph.add_edge(to_id, from_id, error_rate)
            
            # Store error rates (both directions)
            self._edge_errors[(from_id, to_id)] = error_rate
            self._edge_errors[(to_id, from_id)] = error_rate
    
    # =========================================================================
    # Construction Methods
    # =========================================================================
    
    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "QuantumNetworkGraph":
        """
        Load a quantum network from a JSON file.
        
        Args:
            path: Path to the JSON configuration file
            
        Returns:
            QuantumNetworkGraph instance
        """
        with open(path, 'r') as f:
            config = json.load(f)
        return cls.from_dict(config)
    
    @classmethod
    def from_dict(cls, config: dict) -> "QuantumNetworkGraph":
        """
        Create a quantum network from a dictionary configuration.
        
        Args:
            config: Dictionary with keys: nodes, edges, source, sink, qubits_per_node
            
        Returns:
            QuantumNetworkGraph instance
        """
        return cls(
            nodes=config["nodes"],
            edges=[tuple(e) for e in config["edges"]],
            source=config["source"],
            sink=config["sink"],
            qubits_per_node=config.get("qubits_per_node", 1)
        )
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def qubits_per_node(self) -> int:
        """Number of qubits in each register/node."""
        return self._qubits_per_node
    
    @property
    def num_nodes(self) -> int:
        """Total number of nodes (registers) in the network."""
        return len(self._node_names)
    
    @property
    def num_edges(self) -> int:
        """Number of unique edges (undirected count)."""
        return len(self._edge_errors) // 2
    
    @property
    def total_qubits(self) -> int:
        """Total number of physical qubits across all registers."""
        return self.num_nodes * self._qubits_per_node
    
    @property
    def source_node(self) -> int:
        """Node ID of the source."""
        return self._source_id
    
    @property
    def sink_node(self) -> int:
        """Node ID of the sink."""
        return self._sink_id
    
    @property
    def source_name(self) -> str:
        """Name of the source node."""
        return self._node_names[self._source_id]
    
    @property
    def sink_name(self) -> str:
        """Name of the sink node."""
        return self._node_names[self._sink_id]
    
    @property
    def graph(self) -> rx.PyDiGraph:
        """Raw rustworkx directed graph (for advanced usage)."""
        return self._graph
    
    # =========================================================================
    # Node Information
    # =========================================================================
    
    def get_node_name(self, node_id: int) -> str:
        """Get the name of a node by its ID."""
        if node_id < 0 or node_id >= len(self._node_names):
            raise ValueError(f"Invalid node ID: {node_id}")
        return self._node_names[node_id]
    
    def get_node_id(self, name: str) -> int:
        """Get the ID of a node by its name."""
        if name not in self._name_to_id:
            raise ValueError(f"Unknown node name: {name}")
        return self._name_to_id[name]
    
    def get_node_qubits(self, node_id: int) -> List[int]:
        """
        Get the physical qubit indices for a node's register.
        
        Args:
            node_id: The node/register ID
            
        Returns:
            List of physical qubit indices [start, start+1, ..., start+qubits_per_node-1]
        """
        if node_id < 0 or node_id >= len(self._node_names):
            raise ValueError(f"Invalid node ID: {node_id}")
        start = node_id * self._qubits_per_node
        return list(range(start, start + self._qubits_per_node))
    
    def get_all_nodes(self) -> List[Dict]:
        """
        Get information about all nodes.
        
        Returns:
            List of dicts with keys: id, name, qubits, is_source, is_sink
        """
        nodes = []
        for node_id, name in enumerate(self._node_names):
            nodes.append({
                "id": node_id,
                "name": name,
                "qubits": self.get_node_qubits(node_id),
                "is_source": node_id == self._source_id,
                "is_sink": node_id == self._sink_id
            })
        return nodes
    
    # =========================================================================
    # Edge Information
    # =========================================================================
    
    def get_edge_error_rate(self, from_node: int, to_node: int) -> float:
        """
        Get the error rate for a specific edge.
        
        Args:
            from_node: Source node ID
            to_node: Target node ID
            
        Returns:
            Error rate (depolarizing probability) for SWAPs on this edge
        """
        key = (from_node, to_node)
        if key not in self._edge_errors:
            raise ValueError(f"No edge from node {from_node} to {to_node}")
        return self._edge_errors[key]
    
    def get_edge_swap_pairs(self, from_node: int, to_node: int) -> List[Tuple[int, int]]:
        """
        Get the physical qubit pairs that would be swapped for an edge.
        
        Args:
            from_node: Source node ID
            to_node: Target node ID
            
        Returns:
            List of (from_qubit, to_qubit) pairs for parallel SWAPs
        """
        from_qubits = self.get_node_qubits(from_node)
        to_qubits = self.get_node_qubits(to_node)
        return list(zip(from_qubits, to_qubits))
    
    def get_all_edges(self) -> List[Dict]:
        """
        Get information about all unique edges.
        
        Returns:
            List of dicts with keys: from_id, to_id, from_name, to_name, error_rate
        """
        edges = []
        seen = set()
        
        for (from_id, to_id), error_rate in self._edge_errors.items():
            # Only include each edge once (avoid duplicates from bidirectional)
            edge_key = (min(from_id, to_id), max(from_id, to_id))
            if edge_key not in seen:
                edges.append({
                    "from_id": from_id,
                    "to_id": to_id,
                    "from_name": self._node_names[from_id],
                    "to_name": self._node_names[to_id],
                    "error_rate": error_rate
                })
                seen.add(edge_key)
        
        return edges
    
    def get_neighbors(self, node_id: int) -> List[int]:
        """Get IDs of all nodes connected to the given node."""
        return list(self._graph.neighbors(node_id))
    
    def has_edge(self, from_node: int, to_node: int) -> bool:
        """Check if an edge exists between two nodes."""
        return (from_node, to_node) in self._edge_errors
    
    # =========================================================================
    # Pathfinding
    # =========================================================================
    
    def find_all_paths(self, source: Optional[int] = None, sink: Optional[int] = None) -> List[List[int]]:
        """
        Find all simple paths from source to sink.
        
        Args:
            source: Source node ID (defaults to network source)
            sink: Sink node ID (defaults to network sink)
            
        Returns:
            List of paths, where each path is a list of node IDs
        """
        if source is None:
            source = self._source_id
        if sink is None:
            sink = self._sink_id
        
        return rx.all_simple_paths(self._graph, source, sink)
    
    def get_path_info(self, path: List[int]) -> Dict:
        """
        Get detailed information about a path.
        
        Args:
            path: List of node IDs forming the path
            
        Returns:
            Dict with keys: path_names, num_hops, total_swaps, edges, 
                           total_error, expected_fidelity
        """
        path_names = [self._node_names[nid] for nid in path]
        num_hops = len(path) - 1
        total_swaps = num_hops * self._qubits_per_node
        
        edges = []
        total_error = 0.0
        fidelity_product = 1.0
        
        for i in range(len(path) - 1):
            from_id, to_id = path[i], path[i + 1]
            error_rate = self._edge_errors[(from_id, to_id)]
            edges.append({
                "from_id": from_id,
                "to_id": to_id,
                "from_name": self._node_names[from_id],
                "to_name": self._node_names[to_id],
                "error_rate": error_rate
            })
            total_error += error_rate
            fidelity_product *= (1 - error_rate)
        
        return {
            "path": path,
            "path_names": path_names,
            "num_hops": num_hops,
            "total_swaps": total_swaps,
            "edges": edges,
            "sum_error_rates": total_error,
            "expected_per_qubit_fidelity": fidelity_product
        }
    
    def get_shortest_path(self) -> List[int]:
        """Get the path with fewest hops from source to sink."""
        all_paths = self.find_all_paths()
        if not all_paths:
            raise ValueError("No path exists from source to sink")
        return min(all_paths, key=len)
    
    def get_lowest_error_path(self) -> List[int]:
        """Get the path with lowest cumulative error rate from source to sink."""
        all_paths = self.find_all_paths()
        if not all_paths:
            raise ValueError("No path exists from source to sink")
        
        def path_error(path):
            return sum(
                self._edge_errors[(path[i], path[i + 1])]
                for i in range(len(path) - 1)
            )
        
        return min(all_paths, key=path_error)
    
    # =========================================================================
    # Visualization
    # =========================================================================
    
    def draw(
        self,
        ax: Optional[plt.Axes] = None,
        show_qubits: bool = True,
        highlight_path: Optional[List[int]] = None,
        figsize: Tuple[int, int] = (12, 8)
    ) -> plt.Axes:
        """
        Draw the network graph.
        
        Args:
            ax: Matplotlib axes (creates new figure if None)
            show_qubits: Whether to show qubit indices in node labels
            highlight_path: Path to highlight (list of node IDs)
            figsize: Figure size if creating new figure
            
        Returns:
            Matplotlib axes
        """
        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        
        # Define node colors
        node_colors = []
        for i in range(self.num_nodes):
            if highlight_path and i in highlight_path:
                node_colors.append('#f39c12')  # Orange for highlighted
            elif i == self._source_id:
                node_colors.append('#2ecc71')  # Green for source
            elif i == self._sink_id:
                node_colors.append('#e74c3c')  # Red for sink
            else:
                node_colors.append('#3498db')  # Blue for others
        
        # Node label function
        def node_label_fn(node_data):
            name = self._node_names[node_data]
            if show_qubits:
                qubits = self.get_node_qubits(node_data)
                return f"{name}\n(reg {node_data})\nq{qubits[0]}-q{qubits[-1]}"
            return f"{name}\n(reg {node_data})"
        
        # Edge label function
        def edge_label_fn(edge_data):
            return f"{edge_data*100:.1f}%\n({self._qubits_per_node} SWAPs)"
        
        # Draw
        mpl_draw(
            self._graph,
            ax=ax,
            with_labels=True,
            labels=node_label_fn,
            node_color=node_colors,
            node_size=2000,
            font_size=9,
            font_weight='bold',
            edge_labels=edge_label_fn,
            arrows=True
        )
        
        ax.set_title(
            f"Quantum Network Topology\n"
            f"({self.num_nodes} nodes × {self._qubits_per_node} qubits = {self.total_qubits} total qubits)",
            fontsize=14
        )
        
        # Legend
        legend_elements = [
            Patch(facecolor='#2ecc71', label=f'Source ({self.source_name})'),
            Patch(facecolor='#e74c3c', label=f'Sink ({self.sink_name})'),
            Patch(facecolor='#3498db', label='Intermediate'),
        ]
        if highlight_path:
            legend_elements.append(Patch(facecolor='#f39c12', label='Highlighted path'))
        ax.legend(handles=legend_elements, loc='upper left')
        
        return ax
    
    def summary(self) -> str:
        """Get a printable summary of the network."""
        lines = [
            "=" * 60,
            "QUANTUM NETWORK SUMMARY",
            "=" * 60,
            f"Nodes (registers): {self.num_nodes}",
            f"Qubits per node: {self._qubits_per_node}",
            f"Total qubits: {self.total_qubits}",
            f"Edges: {self.num_edges}",
            f"Source: {self.source_name} (node {self._source_id})",
            f"Sink: {self.sink_name} (node {self._sink_id})",
            "",
            "Node → Qubit mapping:",
        ]
        
        for node in self.get_all_nodes():
            suffix = ""
            if node["is_source"]:
                suffix = " [SOURCE]"
            elif node["is_sink"]:
                suffix = " [SINK]"
            lines.append(f"  {node['name']:10} (reg {node['id']}) → qubits {node['qubits']}{suffix}")
        
        lines.append("")
        lines.append("Edge error rates:")
        
        for edge in self.get_all_edges():
            quality = "Good" if edge["error_rate"] <= 0.015 else (
                "Medium" if edge["error_rate"] <= 0.04 else "High"
            )
            lines.append(
                f"  {edge['from_name']:10} ↔ {edge['to_name']:10}: "
                f"{edge['error_rate']*100:.1f}% ({quality})"
            )
        
        lines.append("")
        all_paths = self.find_all_paths()
        lines.append(f"Paths from {self.source_name} to {self.sink_name}: {len(all_paths)}")
        
        lines.append("=" * 60)
        return "\n".join(lines)
    
    # =========================================================================
    # Export
    # =========================================================================
    
    def to_dict(self) -> Dict:
        """Export the network configuration as a dictionary."""
        edges = []
        seen = set()
        
        for (from_id, to_id), error_rate in self._edge_errors.items():
            edge_key = (min(from_id, to_id), max(from_id, to_id))
            if edge_key not in seen:
                edges.append([
                    self._node_names[from_id],
                    self._node_names[to_id],
                    error_rate
                ])
                seen.add(edge_key)
        
        return {
            "qubits_per_node": self._qubits_per_node,
            "nodes": self._node_names.copy(),
            "source": self.source_name,
            "sink": self.sink_name,
            "edges": edges
        }
    
    def to_json(self, path: Union[str, Path]) -> None:
        """Export the network configuration to a JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def __repr__(self) -> str:
        return (
            f"QuantumNetworkGraph(nodes={self.num_nodes}, "
            f"qubits_per_node={self._qubits_per_node}, "
            f"edges={self.num_edges}, "
            f"source='{self.source_name}', sink='{self.sink_name}')"
        )


# =============================================================================
# Convenience function for quick testing
# =============================================================================

def create_example_network() -> QuantumNetworkGraph:
    """Create an example 6-node quantum network for testing."""
    config = {
        "qubits_per_node": 3,
        "nodes": ["SOURCE", "A", "SINK", "E", "D", "C"],
        "source": "SOURCE",
        "sink": "SINK",
        "edges": [
            ["SOURCE", "A", 0.06],
            ["A", "SINK", 0.06],
            ["SOURCE", "E", 0.01],
            ["E", "D", 0.01],
            ["D", "C", 0.01],
            ["C", "SINK", 0.01],
            ["A", "D", 0.04]
        ]
    }
    return QuantumNetworkGraph.from_dict(config)


if __name__ == "__main__":
    # Demo usage
    network = create_example_network()
    print(network.summary())
    
    print("\nAll paths:")
    for i, path in enumerate(network.find_all_paths()):
        info = network.get_path_info(path)
        print(f"  Path {i+1}: {' → '.join(info['path_names'])}")
        print(f"           Hops: {info['num_hops']}, SWAPs: {info['total_swaps']}")
        print(f"           Expected fidelity: {info['expected_per_qubit_fidelity']*100:.1f}%")
    
    print(f"\nShortest path: {[network.get_node_name(n) for n in network.get_shortest_path()]}")
    print(f"Lowest error path: {[network.get_node_name(n) for n in network.get_lowest_error_path()]}")
    
    # Visualize
    network.draw()
    plt.tight_layout()
    plt.show()
