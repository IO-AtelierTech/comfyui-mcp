"""MCP Tools for ComfyUI.

Tools are organized by category:
- system: Server health and monitoring
- discovery: Node and model discovery
- workflow: Workflow management and creation
- execution: Workflow execution
"""

from .discovery import register_discovery_tools
from .execution import register_execution_tools
from .system import register_system_tools
from .workflow import register_workflow_tools

__all__ = [
    "register_system_tools",
    "register_discovery_tools",
    "register_workflow_tools",
    "register_execution_tools",
]


def register_all_tools(mcp):
    """Register all tools with the MCP server."""
    register_system_tools(mcp)
    register_discovery_tools(mcp)
    register_workflow_tools(mcp)
    register_execution_tools(mcp)
