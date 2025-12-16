"""Graph-based workflow layout using NetworkX.

Provides layered DAG layout for ComfyUI workflows, placing nodes
in columns based on their dependencies (inputs → processing → outputs).
Uses reverse placement with proportional spacing.
"""

import networkx as nx


def compute_workflow_layout(
    nodes: dict[str, dict],
    node_sizes: dict[str, tuple[float, float]],
    h_spacing: float = 100,
    v_spacing: float = 50,
    start_pos: tuple[float, float] = (100, 100),
) -> dict[str, tuple[float, float]]:
    """Compute node positions using layered DAG layout."""
    if not nodes:
        return {}

    # Build directed graph
    G = nx.DiGraph()
    for node_id in nodes:
        G.add_node(node_id)

    for node_id, data in nodes.items():
        for value in data.get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2:
                source = str(value[0])
                if source in nodes:
                    G.add_edge(source, node_id)

    # Compute topological layers
    try:
        layers = [list(layer) for layer in nx.topological_generations(G)]
    except nx.NetworkXUnfeasible:
        try:
            cycles = list(nx.simple_cycles(G))
            for cycle in cycles:
                if len(cycle) >= 2:
                    G.remove_edge(cycle[-1], cycle[0])
            layers = [list(layer) for layer in nx.topological_generations(G)]
        except Exception:
            layers = [list(G.nodes())]

    # Handle disconnected nodes
    all_layered = set()
    for layer in layers:
        all_layered.update(layer)
    disconnected = set(nodes.keys()) - all_layered
    if disconnected:
        if layers:
            layers[0] = list(disconnected) + layers[0]
        else:
            layers = [list(disconnected)]

    # Apply barycenter ordering
    layers = _barycenter_ordering(G, layers, iterations=4)

    # Compute X positions
    layer_x = {}
    x = start_pos[0]
    for layer_idx, layer_nodes in enumerate(layers):
        if not layer_nodes:
            continue
        max_width = max(node_sizes.get(n, (300, 80))[0] for n in layer_nodes)
        layer_x[layer_idx] = x
        x += max_width + h_spacing

    # Compute total height needed for each layer
    layer_heights = {}
    for layer_idx, layer_nodes in enumerate(layers):
        if not layer_nodes:
            continue
        total = sum(node_sizes.get(n, (300, 80))[1] + v_spacing for n in layer_nodes)
        layer_heights[layer_idx] = total - v_spacing  # Remove trailing spacing

    # Find the maximum height (this determines the vertical range)
    max_height = max(layer_heights.values()) if layer_heights else 0

    # Compute Y positions with proportional spacing
    positions = _compute_proportional_positions(
        G, layers, layer_x, node_sizes, v_spacing, start_pos[1], max_height
    )

    return positions


def _compute_proportional_positions(
    G: nx.DiGraph,
    layers: list[list[str]],
    layer_x: dict[int, float],
    node_sizes: dict[str, tuple[float, float]],
    v_spacing: float,
    start_y: float,
    max_height: float,
) -> dict[str, tuple[float, float]]:
    """Place nodes with proportional spacing based on successors."""
    positions = {}
    node_y = {}

    # Place last layer first, spread across max_height
    last_layer_idx = len(layers) - 1
    if last_layer_idx >= 0 and layers[last_layer_idx]:
        layer_nodes = layers[last_layer_idx]
        x = layer_x.get(last_layer_idx, 100)

        # Calculate spacing to spread nodes across max_height
        n = len(layer_nodes)
        if n == 1:
            # Center single node
            node_y[layer_nodes[0]] = start_y + max_height / 2
            positions[layer_nodes[0]] = (x, node_y[layer_nodes[0]])
        else:
            # Spread nodes evenly
            total_node_height = sum(node_sizes.get(nid, (300, 80))[1] for nid in layer_nodes)
            available_space = max_height - total_node_height
            gap = available_space / (n - 1) if n > 1 else 0

            y = start_y
            for node_id in layer_nodes:
                height = node_sizes.get(node_id, (300, 80))[1]
                node_y[node_id] = y
                positions[node_id] = (x, y)
                y += height + gap

    # Work backwards: align each layer with successors
    for layer_idx in range(len(layers) - 2, -1, -1):
        layer_nodes = layers[layer_idx]
        if not layer_nodes:
            continue

        x = layer_x.get(layer_idx, 100)

        # Compute target Y based on successors
        target_y = {}
        for node_id in layer_nodes:
            succs = list(G.successors(node_id))
            if succs:
                # Target = average Y of successors (use center of node)
                succ_centers = []
                for s in succs:
                    s_y = node_y.get(s, start_y)
                    s_h = node_sizes.get(s, (300, 80))[1]
                    succ_centers.append(s_y + s_h / 2)
                target_center = sum(succ_centers) / len(succ_centers)
                # Adjust to top of node
                my_height = node_sizes.get(node_id, (300, 80))[1]
                target_y[node_id] = target_center - my_height / 2
            else:
                target_y[node_id] = start_y

        # Sort by target Y
        sorted_nodes = sorted(layer_nodes, key=lambda n: target_y[n])

        # Resolve overlaps
        _resolve_overlaps(sorted_nodes, target_y, node_y, node_sizes, v_spacing, start_y)

        # Assign positions
        for node_id in sorted_nodes:
            positions[node_id] = (x, node_y[node_id])

    return positions


def _resolve_overlaps(
    sorted_nodes: list[str],
    target_y: dict[str, float],
    node_y: dict[str, float],
    node_sizes: dict[str, tuple[float, float]],
    v_spacing: float,
    start_y: float,
):
    """Resolve overlaps while keeping nodes close to targets."""
    min_y = start_y

    for node_id in sorted_nodes:
        height = node_sizes.get(node_id, (300, 80))[1]
        ideal_y = target_y[node_id]
        actual_y = max(ideal_y, min_y)
        node_y[node_id] = actual_y
        min_y = actual_y + height + v_spacing


def _barycenter_ordering(
    G: nx.DiGraph,
    layers: list[list[str]],
    iterations: int = 4,
) -> list[list[str]]:
    """Order nodes within layers to minimize edge crossings."""
    if len(layers) <= 1:
        return layers

    node_pos = {}
    for layer in layers:
        for idx, node_id in enumerate(layer):
            node_pos[node_id] = idx

    for _ in range(iterations):
        for layer_idx in range(1, len(layers)):
            layer = layers[layer_idx]
            barycenters = []
            for node_id in layer:
                preds = list(G.predecessors(node_id))
                if preds:
                    avg = sum(node_pos.get(p, 0) for p in preds) / len(preds)
                else:
                    avg = node_pos.get(node_id, 0)
                barycenters.append((avg, node_id))
            barycenters.sort(key=lambda x: (x[0], x[1]))
            layers[layer_idx] = [node_id for _, node_id in barycenters]
            for idx, node_id in enumerate(layers[layer_idx]):
                node_pos[node_id] = idx

        for layer_idx in range(len(layers) - 2, -1, -1):
            layer = layers[layer_idx]
            barycenters = []
            for node_id in layer:
                succs = list(G.successors(node_id))
                if succs:
                    avg = sum(node_pos.get(s, 0) for s in succs) / len(succs)
                else:
                    avg = node_pos.get(node_id, 0)
                barycenters.append((avg, node_id))
            barycenters.sort(key=lambda x: (x[0], x[1]))
            layers[layer_idx] = [node_id for _, node_id in barycenters]
            for idx, node_id in enumerate(layers[layer_idx]):
                node_pos[node_id] = idx

    return layers
