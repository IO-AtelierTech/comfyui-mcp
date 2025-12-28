"""ComfyUI MCP Server - Enhanced version with workflow automation capabilities.

This server provides comprehensive ComfyUI integration for Claude Code:
- System monitoring and queue management
- Node and model discovery
- Workflow execution and creation
- Full workflow automation capabilities

Version: 0.2.2
"""

__version__ = "0.2.2"

import logging

from mcp.server.fastmcp import FastMCP

from .api import check_connection
from .settings import settings
from .tools import register_all_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Server instructions for Claude Code
SERVER_INSTRUCTIONS = """
## ComfyUI MCP Server - Workflow Guide

### Workflow Formats (CRITICAL)
- **API format**: `{"node_id": {"class_type": "...", "inputs": {...}}}` - For MCP execution
- **UI format**: `{"nodes": [...], "links": [...], "version": ...}` - For ComfyUI editor only
- **IMPORTANT**: Only API format can be executed. UI format will be rejected with an error.

### Creating Workflows (Step-by-Step)

1. **CREATE** - Start empty or from template:
   ```
   wf = create_workflow()
   # Or: wf = get_workflow_template("fal-flux-dev")
   ```

2. **DISCOVER** - Find nodes and parameters:
   ```
   list_nodes(filter="Luma")     # Find node names
   get_node_info("LumaImageToVideoNode")  # Get required inputs
   ```

3. **BUILD** - Add nodes with connections:
   ```
   wf = add_node(wf, "1", "LoadImage", {"image": "input.jpg"})
   wf = add_node(wf, "2", "SomeNode", {
       "param": "value",
       "input_image": ["1", 0]  # Connect to node "1", output 0
   })
   ```

4. **VALIDATE** - Check before saving:
   ```
   validation = validate_workflow(wf)
   # Check validation["valid"] and validation["errors"]
   ```

5. **SAVE** - Choose format by purpose:
   ```
   save_workflow(wf, "name", format="api")  # → workflows-api/ (execution)
   save_workflow(wf, "name", format="ui")   # → workflows-ui/ (editor)
   ```

### Execution
- `run_workflow("name.json", inputs={...})` - Run saved API workflow
- `execute_workflow(wf, output_node_id="9")` - Run workflow dict directly
- `generate_image("prompt")` - Simple interface with default workflow

### Common Errors
- "UI format detected": Use API format for execution
- "Unknown node type": Check with list_nodes()
- "Missing required input": Check with get_node_info()

### Node Connections Format
Connections are `["source_node_id", output_index]`:
- `"image": ["1", 0]` connects to node "1", first output (index 0)
"""

# Initialize MCP server with instructions
mcp = FastMCP("Comfy MCP Server", instructions=SERVER_INSTRUCTIONS)

# Register all tools
register_all_tools(mcp)


def run_server():
    """Start the MCP server."""
    print(f"Starting Comfy MCP Server v{__version__}...")
    print(f"  ComfyUI URL: {settings.comfy_url}")
    print(f"  Workflows: {settings.workflows_dir or 'Not configured'}")
    print(f"  Output mode: {settings.output_mode}")
    print(f"  Poll timeout: {settings.poll_timeout}s")

    # Test connection
    connected, version = check_connection(timeout=5)
    if connected:
        print(f"  Connected to ComfyUI {version}")
    else:
        print("  Warning: Cannot connect to ComfyUI")

    mcp.run()


# Export key components for testing
__all__ = [
    "__version__",
    "mcp",
    "run_server",
    "settings",
]


if __name__ == "__main__":
    run_server()
