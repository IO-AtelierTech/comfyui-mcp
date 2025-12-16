"""Node and model discovery tools.

Impact: High (essential for workflow building)
Complexity: Low-Medium (caching, filtering)
"""

from urllib.error import HTTPError

from mcp.server.fastmcp import Context
from pydantic import Field

from ..api import clear_node_cache, comfy_get, get_cached_nodes, get_embeddings
from ..models import ErrorResponse, NodeInfo


def register_discovery_tools(mcp):
    """Register discovery tools."""

    @mcp.tool()
    def list_nodes(
        filter: str = Field(default=None, description="Filter by name (e.g., 'fal', 'image')"),
        category: str = Field(default=None, description="Filter by category"),
        ctx: Context = None,
    ) -> list:
        """List available ComfyUI nodes.

        Args:
            filter: Optional string to match node names (case-insensitive)
            category: Optional category filter (exact match)

        Returns a sorted list of node class names.
        Use this to discover available nodes for workflow building.
        """
        if ctx:
            ctx.info(f"Listing nodes{' matching: ' + filter if filter else ''}...")

        try:
            nodes = get_cached_nodes()
            result = []

            for name, info in nodes.items():
                if filter and filter.lower() not in name.lower():
                    continue
                if category and info.get("category", "").lower() != category.lower():
                    continue
                result.append(name)

            return sorted(result)
        except Exception as e:
            return [f"Error: {e}"]

    @mcp.tool()
    def get_node_info(
        node_name: str = Field(description="Exact node class name"),
        ctx: Context = None,
    ) -> dict:
        """Get detailed info about a node.

        Args:
            node_name: Node class name (e.g., 'RemoteCheckpointLoader_fal')

        Returns node information including:
        - input: Required and optional inputs with types
        - output: Output types
        - category: Node category
        - description: What the node does

        Use this to understand how to configure a node in a workflow.
        """
        if ctx:
            ctx.info(f"Fetching info for: {node_name}")

        try:
            result = comfy_get(f"/object_info/{node_name}")
            if node_name in result:
                data = result[node_name]
                data["name"] = node_name  # Ensure name is set
                info = NodeInfo(**data)
                return info.model_dump()
            return ErrorResponse.not_found(
                f"Node '{node_name}'",
                suggestion="Use list_nodes() to see available nodes",
            ).model_dump()
        except Exception as e:
            return ErrorResponse.unavailable(str(e)).model_dump()

    @mcp.tool()
    def list_models(
        folder: str = Field(
            default="checkpoints",
            description="Model folder: checkpoints, loras, vae, embeddings",
        ),
        ctx: Context = None,
    ) -> list:
        """List available models in a folder.

        Args:
            folder: Model folder name. Options:
                - checkpoints: Full model checkpoints
                - loras: LoRA fine-tuning files
                - vae: VAE decoders
                - embeddings: Text embeddings
                - controlnet: ControlNet models
                - upscale_models: Upscaling models
                - clip_vision: CLIP vision encoders

        Returns list of model filenames in the folder.
        """
        if ctx:
            ctx.info(f"Listing models in: {folder}")
        try:
            return comfy_get(f"/models/{folder}")
        except HTTPError as e:
            if e.code == 404:
                return []
            return [f"Error: {e}"]
        except Exception as e:
            return [f"Error: {e}"]

    @mcp.tool()
    def list_model_folders(ctx: Context = None) -> list:
        """List available model folder types.

        Returns a list of valid folder names for list_models().
        """
        if ctx:
            ctx.info("Listing model folders...")
        try:
            return comfy_get("/models")
        except Exception as e:
            return [f"Error: {e}"]

    @mcp.tool()
    def list_embeddings(ctx: Context = None) -> list:
        """List available text embeddings.

        Returns list of embedding names that can be used in prompts.
        """
        if ctx:
            ctx.info("Listing embeddings...")
        try:
            return get_embeddings()
        except Exception as e:
            return [f"Error: {e}"]

    @mcp.tool()
    def list_extensions(ctx: Context = None) -> list:
        """List loaded ComfyUI extensions.

        Returns list of installed extension names (custom node packs).
        Use this to verify which custom nodes are available (e.g., fal.ai connector).
        """
        if ctx:
            ctx.info("Listing extensions...")
        try:
            return comfy_get("/extensions")
        except Exception as e:
            return [f"Error: {e}"]

    @mcp.tool()
    def refresh_nodes(ctx: Context = None) -> str:
        """Refresh the node cache.

        Call this after installing new custom nodes to see them in list_nodes().
        """
        if ctx:
            ctx.info("Refreshing node cache...")
        clear_node_cache()
        try:
            nodes = get_cached_nodes()
            return f"Cache refreshed. {len(nodes)} nodes available."
        except Exception as e:
            return f"Error refreshing cache: {e}"

    @mcp.tool()
    def search_nodes(
        query: str = Field(description="Search query"),
        ctx: Context = None,
    ) -> list:
        """Search for nodes by name, category, or description.

        Args:
            query: Search string (searches name, category, description)

        Returns matching nodes sorted by relevance.
        """
        if ctx:
            ctx.info(f"Searching for: {query}")

        try:
            nodes = get_cached_nodes()
            query_lower = query.lower()
            results = []

            for name, info in nodes.items():
                score = 0
                # Name match (highest priority)
                if query_lower in name.lower():
                    score += 10
                # Category match
                if query_lower in info.get("category", "").lower():
                    score += 5
                # Description match
                if query_lower in info.get("description", "").lower():
                    score += 3

                if score > 0:
                    results.append((name, score))

            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            return [name for name, _ in results[:50]]  # Limit to 50 results

        except Exception as e:
            return [f"Error: {e}"]
