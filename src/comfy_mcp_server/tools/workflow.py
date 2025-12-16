"""Workflow management and creation tools.

Impact: High (core functionality for automation)
Complexity: Medium (file operations, template management)
"""

import json
from pathlib import Path

from coolname import generate_slug
from mcp.server.fastmcp import Context
from pydantic import Field

from ..layout import compute_workflow_layout
from ..models import (
    ErrorResponse,
    SerialisableLLink,
    UINode,
    UINodeFlags,
    UINodeSlot,
    UIWorkflow,
    UIWorkflowExtra,
    UIWorkflowState,
)
from ..settings import settings

# === Format Conversion ===

# Default node sizes by type pattern
NODE_SIZES = {
    "RemoteCheckpointLoader": (350, 100),
    "SaveImage": (350, 270),
    "StringInput": (400, 100),
    "IntegerInput": (220, 60),
    "FloatInput": (220, 60),
    "BooleanInput": (180, 60),
    "LoadImage": (320, 320),
    "default": (300, 80),
}


def get_node_size(class_type: str) -> tuple[float, float]:
    """Get default size for a node type."""
    for pattern, size in NODE_SIZES.items():
        if pattern in class_type:
            return size
    return NODE_SIZES["default"]


def api_to_ui_workflow(api_workflow: dict) -> dict:
    """Convert API format workflow to SerialisableGraph format (version 1).

    API format: { "node_id": {"class_type": "...", "inputs": {...}}, ... }
    UI format: { "version": 1, "nodes": [...], "links": [...], ... }

    Based on: ComfyUI_frontend/src/lib/litegraph/src/types/serialisation.ts

    Args:
        api_workflow: Workflow in API format

    Returns:
        Workflow in SerialisableGraph format compatible with ComfyUI editor
    """
    ui_nodes: list[UINode] = []
    ui_links: list[SerialisableLLink] = []

    # Map string node IDs to integer IDs
    node_id_map: dict[str, int] = {}
    for idx, node_id in enumerate(api_workflow.keys(), start=1):
        node_id_map[node_id] = idx

    # Track link ID
    link_id = 0

    # Compute node sizes for layout
    node_sizes = {
        node_id: get_node_size(data.get("class_type", "")) for node_id, data in api_workflow.items()
    }

    # Graph-aware layout using topological layers
    positions = compute_workflow_layout(api_workflow, node_sizes)

    for idx, (node_id, node_data) in enumerate(api_workflow.items()):
        int_id = node_id_map[node_id]
        class_type = node_data.get("class_type", "Unknown")
        inputs = node_data.get("inputs", {})

        # Get position from graph layout
        pos_x, pos_y = positions.get(node_id, (100, 100))
        size = node_sizes[node_id]

        # Separate connection inputs from widget values
        node_inputs: list[UINodeSlot] = []
        node_outputs: list[UINodeSlot] = []
        widgets_values: list = []

        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                # This is a connection: [source_node_id, output_index]
                source_node_str = str(value[0])
                source_slot = value[1]

                if source_node_str in node_id_map:
                    link_id += 1
                    source_int_id = node_id_map[source_node_str]

                    # Add input slot
                    node_inputs.append(
                        UINodeSlot(
                            name=input_name,
                            type="*",  # Wildcard type
                            link=link_id,
                            slot_index=len(node_inputs),
                        )
                    )

                    # Add link (object format for SerialisableGraph)
                    ui_links.append(
                        SerialisableLLink(
                            id=link_id,
                            origin_id=source_int_id,
                            origin_slot=source_slot,
                            target_id=int_id,
                            target_slot=len(node_inputs) - 1,
                            type="*",
                        )
                    )
            else:
                # This is a widget value
                widgets_values.append(value)

        # Add a default output for nodes that might be sources
        # (detected by checking if other nodes reference them)
        has_outgoing = any(
            isinstance(inp, list) and len(inp) == 2 and str(inp[0]) == node_id
            for n in api_workflow.values()
            for inp in n.get("inputs", {}).values()
        )
        if has_outgoing or "SaveImage" not in class_type:
            node_outputs.append(UINodeSlot(name="output", type="*", links=[], slot_index=0))

        # Create UI node
        ui_node = UINode(
            id=int_id,
            type=class_type,
            pos=(pos_x, pos_y),
            size=size,
            flags=UINodeFlags(),
            order=idx,
            mode=0,
            inputs=node_inputs,
            outputs=node_outputs,
            properties={"Node name for S&R": class_type},
            widgets_values=widgets_values if widgets_values else None,
        )
        ui_nodes.append(ui_node)

    # Update output links on source nodes
    for link in ui_links:
        for node in ui_nodes:
            if node.id == link.origin_id and node.outputs:
                if node.outputs[link.origin_slot].links is None:
                    node.outputs[link.origin_slot].links = []
                node.outputs[link.origin_slot].links.append(link.id)

    # Build UI workflow (SerialisableGraph version 1 format)
    max_node_id = max(node_id_map.values()) if node_id_map else 0
    ui_workflow = UIWorkflow(
        version=1,
        state=UIWorkflowState(
            lastNodeId=max_node_id,
            lastLinkId=link_id,
            lastGroupId=0,
            lastRerouteId=0,
        ),
        nodes=ui_nodes,
        links=ui_links,
        groups=[],
        extra=UIWorkflowExtra(),
    )

    return ui_workflow.to_dict()


# === Workflow Templates ===
TEMPLATES = {
    "empty": {},
    "fal-flux-dev": {
        "1": {
            "class_type": "RemoteCheckpointLoader_fal",
            "inputs": {"ckpt_name": "fal-ai/flux/dev"},
        },
        "2": {"class_type": "StringInput_fal", "inputs": {"text": "A beautiful landscape"}},
        "3": {"class_type": "IntegerInput_fal", "inputs": {"value": 1024}},
        "4": {"class_type": "IntegerInput_fal", "inputs": {"value": 1024}},
        "5": {"class_type": "IntegerInput_fal", "inputs": {"value": 28}},
        "6": {"class_type": "FloatInput_fal", "inputs": {"value": 3.5}},
        "7": {
            "class_type": "SaveImage_fal",
            "inputs": {"filename_prefix": "flux_output", "images": ["1", 0]},
        },
    },
    "fal-flux-schnell": {
        "1": {
            "class_type": "RemoteCheckpointLoader_fal",
            "inputs": {"ckpt_name": "fal-ai/flux/schnell"},
        },
        "2": {"class_type": "StringInput_fal", "inputs": {"text": "A beautiful landscape"}},
        "3": {
            "class_type": "SaveImage_fal",
            "inputs": {"filename_prefix": "flux_schnell", "images": ["1", 0]},
        },
    },
}


def register_workflow_tools(mcp):
    """Register workflow management tools."""

    @mcp.tool()
    def list_workflows(ctx: Context = None) -> list:
        """List available workflow files.

        Returns list of workflow JSON files in the configured workflows directory.
        Use run_workflow() to execute a saved workflow.
        """
        if not settings.workflows_dir:
            return ["Error: COMFY_WORKFLOWS_DIR not configured"]

        if ctx:
            ctx.info(f"Listing workflows in: {settings.workflows_dir}")

        path = Path(settings.workflows_dir)
        if not path.exists():
            return []
        return sorted([f.name for f in path.glob("*.json")])

    @mcp.tool()
    def load_workflow(
        workflow_name: str = Field(description="Workflow filename"),
        ctx: Context = None,
    ) -> dict:
        """Load a workflow file for inspection or modification.

        Args:
            workflow_name: Workflow filename (e.g., 'my-workflow.json')

        Returns the workflow dict that can be modified and executed.
        """
        if not settings.workflows_dir:
            return ErrorResponse.not_configured("COMFY_WORKFLOWS_DIR").model_dump()

        wf_path = Path(settings.workflows_dir) / workflow_name
        if not wf_path.exists():
            return ErrorResponse.not_found(
                f"Workflow '{workflow_name}'",
                suggestion="Use list_workflows() to see available workflows",
            ).model_dump()

        if ctx:
            ctx.info(f"Loading workflow: {workflow_name}")

        with open(wf_path) as f:
            return json.load(f)

    @mcp.tool()
    def save_workflow(
        workflow: dict = Field(description="Workflow to save"),
        name: str = Field(
            default=None,
            description="Filename (without .json). If not provided, generates a funny name.",
        ),
        format: str = Field(
            default="ui",
            description="Output format: 'api' (execution) or 'ui' (editor-compatible)",
        ),
        ctx: Context = None,
    ) -> str:
        """Save a workflow to the workflows directory.

        Args:
            workflow: Workflow dict to save (in API format)
            name: Filename (with or without .json extension).
                  If not provided, generates a random funny name like 'cosmic-penguin'.
            format: Output format:
                - 'api': Raw API format for execution (flat dict)
                - 'ui': Litegraph format for ComfyUI editor (default)

        Returns path to saved file or error message.
        """
        # Determine target directory based on format
        if format == "ui":
            target_dir = settings.workflows_ui_dir or settings.workflows_dir
        else:
            target_dir = settings.workflows_dir

        if not target_dir:
            return "Error: COMFY_WORKFLOWS_DIR not configured"

        # Auto-generate funny name if not provided
        if not name:
            name = generate_slug(2)

        if not name.endswith(".json"):
            name = f"{name}.json"

        path = Path(target_dir) / name

        if ctx:
            ctx.info(f"Saving to: {path} (format: {format})")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to UI format if requested
            output_data = api_to_ui_workflow(workflow) if format == "ui" else workflow

            with open(path, "w") as f:
                json.dump(output_data, f, indent=2)
            return f"Saved: {path}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    def create_workflow(ctx: Context = None) -> dict:
        """Create an empty workflow structure.

        Returns an empty dict that you can populate with add_node().
        """
        if ctx:
            ctx.info("Creating new workflow")
        return {}

    @mcp.tool()
    def generate_workflow_name(
        words: int = Field(default=2, description="Number of words (2-4)"),
        ctx: Context = None,
    ) -> str:
        """Generate a random funny workflow name.

        Args:
            words: Number of words in the name (2-4, default: 2)

        Returns a slug like 'cosmic-penguin' or 'mighty-purple-narwhal'.
        Use this when saving new workflows for creative naming.
        """
        if ctx:
            ctx.info(f"Generating {words}-word workflow name")

        words = max(2, min(4, words))  # Clamp to valid range
        return generate_slug(words)

    @mcp.tool()
    def add_node(
        workflow: dict = Field(description="Workflow dict to modify"),
        node_id: str = Field(description="Unique node ID (e.g., '1', 'prompt')"),
        node_type: str = Field(description="Node class name"),
        inputs: dict = Field(description="Node inputs"),
        ctx: Context = None,
    ) -> dict:
        """Add a node to a workflow.

        Args:
            workflow: Existing workflow dict
            node_id: Unique identifier for this node
            node_type: Node class name (use list_nodes() to find)
            inputs: Input values. For connections use ["source_node_id", output_index].

        Examples:
            # Simple value input
            add_node(wf, "1", "StringInput_fal", {"text": "a cat"})

            # Connection to another node
            add_node(wf, "2", "CLIPTextEncode", {
                "text": "prompt",
                "clip": ["1", 0]  # Connect to node "1" output 0
            })

        Returns the modified workflow dict.
        """
        if ctx:
            ctx.info(f"Adding node {node_id}: {node_type}")

        workflow[node_id] = {"class_type": node_type, "inputs": inputs}
        return workflow

    @mcp.tool()
    def remove_node(
        workflow: dict = Field(description="Workflow dict to modify"),
        node_id: str = Field(description="Node ID to remove"),
        ctx: Context = None,
    ) -> dict:
        """Remove a node from a workflow.

        Args:
            workflow: Workflow dict to modify
            node_id: ID of node to remove

        Warning: This doesn't update connections from other nodes.
        """
        if ctx:
            ctx.info(f"Removing node: {node_id}")

        if node_id in workflow:
            del workflow[node_id]
        return workflow

    @mcp.tool()
    def update_node_input(
        workflow: dict = Field(description="Workflow dict to modify"),
        node_id: str = Field(description="Node ID to update"),
        input_name: str = Field(description="Input name to update"),
        value: str = Field(description="New value (or JSON for complex values)"),
        ctx: Context = None,
    ) -> dict:
        """Update a specific input on a node.

        Args:
            workflow: Workflow dict to modify
            node_id: Node ID to update
            input_name: Name of the input to update
            value: New value (use JSON string for lists/dicts)

        Returns the modified workflow dict.
        """
        if ctx:
            ctx.info(f"Updating {node_id}.{input_name}")

        if node_id not in workflow:
            return workflow

        # Try to parse as JSON for complex values
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value

        workflow[node_id]["inputs"][input_name] = parsed_value
        return workflow

    @mcp.tool()
    def get_workflow_template(
        template_name: str = Field(
            description="Template: 'fal-flux-dev', 'fal-flux-schnell', 'empty'"
        ),
        ctx: Context = None,
    ) -> dict:
        """Get a pre-built workflow template.

        Args:
            template_name: One of:
                - 'empty': Empty workflow
                - 'fal-flux-dev': Flux Dev via fal.ai (higher quality)
                - 'fal-flux-schnell': Flux Schnell via fal.ai (faster)

        Returns a workflow dict that can be modified and executed.
        """
        if ctx:
            ctx.info(f"Loading template: {template_name}")

        if template_name not in TEMPLATES:
            return ErrorResponse.not_found(
                f"Template '{template_name}'",
                suggestion=f"Available: {list(TEMPLATES.keys())}",
            ).model_dump()

        # Return a copy to avoid modifying the original
        return json.loads(json.dumps(TEMPLATES[template_name]))

    @mcp.tool()
    def list_templates(ctx: Context = None) -> list:
        """List available workflow templates.

        Returns list of template names for get_workflow_template().
        """
        if ctx:
            ctx.info("Listing templates")
        return list(TEMPLATES.keys())

    @mcp.tool()
    def validate_workflow(
        workflow: dict = Field(description="Workflow to validate"),
        ctx: Context = None,
    ) -> dict:
        """Validate a workflow structure.

        Args:
            workflow: Workflow dict to validate

        Returns validation result with any issues found.
        """
        if ctx:
            ctx.info("Validating workflow")

        issues = []
        node_ids = set(workflow.keys())

        for node_id, node in workflow.items():
            # Check required fields
            if "class_type" not in node:
                issues.append(f"Node {node_id}: missing class_type")
            if "inputs" not in node:
                issues.append(f"Node {node_id}: missing inputs")

            # Check connections reference valid nodes
            if "inputs" in node:
                for input_name, value in node["inputs"].items():
                    if isinstance(value, list) and len(value) == 2:
                        ref_node = str(value[0])
                        if ref_node not in node_ids:
                            issues.append(
                                f"Node {node_id}.{input_name}: "
                                f"references non-existent node {ref_node}"
                            )

        return {
            "valid": len(issues) == 0,
            "node_count": len(workflow),
            "issues": issues,
        }

    @mcp.tool()
    def convert_workflow_to_ui(
        workflow: dict = Field(description="Workflow in API format"),
        ctx: Context = None,
    ) -> dict:
        """Convert an API format workflow to UI/Litegraph format.

        Args:
            workflow: Workflow in API format (flat dict with class_type/inputs)

        Returns:
            Workflow in UI format compatible with ComfyUI editor.
            This format includes node positions, visual links, and metadata
            required for the workflow to be displayed and edited in the UI.

        The conversion:
        - Assigns integer IDs to nodes
        - Places nodes in a grid layout
        - Creates visual links from input connections
        - Sets appropriate node sizes based on type
        """
        if ctx:
            ctx.info("Converting workflow to UI format")

        return api_to_ui_workflow(workflow)
