"""Pydantic models for ComfyUI MCP Server.

These models provide structured data validation for ComfyUI API responses
and MCP tool parameters.

Workflow Formats:
- API Format: Flat dict used for execution via /prompt endpoint
- UI Format (Litegraph): Visual format with node positions, links, used by ComfyUI editor
  Schema: https://docs.comfy.org/specs/workflow_json
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# === ComfyUI Response Models ===


class DeviceInfo(BaseModel):
    """Device information from ComfyUI /system_stats."""

    name: str
    type: str
    index: int | None = None
    vram_total: int
    vram_free: int
    torch_vram_total: int
    torch_vram_free: int


class SystemInfo(BaseModel):
    """System information from ComfyUI /system_stats."""

    os: str
    ram_total: int
    ram_free: int
    comfyui_version: str
    python_version: str
    pytorch_version: str
    embedded_python: bool
    # Optional fields that may not exist in all versions
    required_frontend_version: str | None = None
    installed_templates_version: str | None = None


class SystemStats(BaseModel):
    """Complete system statistics from /system_stats."""

    system: SystemInfo
    devices: list[DeviceInfo]


class QueueStatus(BaseModel):
    """Queue status from /queue endpoint."""

    queue_running: list[list[Any]] = Field(default_factory=list)
    queue_pending: list[list[Any]] = Field(default_factory=list)

    @property
    def running_count(self) -> int:
        return len(self.queue_running)

    @property
    def pending_count(self) -> int:
        return len(self.queue_pending)

    @property
    def is_empty(self) -> bool:
        return self.running_count == 0 and self.pending_count == 0


class NodeInput(BaseModel):
    """Node input specification."""

    required: dict[str, Any] = Field(default_factory=dict)
    optional: dict[str, Any] = Field(default_factory=dict)


class NodeInfo(BaseModel):
    """Information about a ComfyUI node from /object_info."""

    name: str
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    input: NodeInput = Field(default_factory=NodeInput)
    output: list[str] = Field(default_factory=list)
    output_name: list[str] = Field(default_factory=list)
    output_node: bool = False
    deprecated: bool = False
    experimental: bool = False


# === Workflow Models ===


class WorkflowNode(BaseModel):
    """A node in a ComfyUI workflow."""

    class_type: str = Field(description="Node class name")
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="Node inputs (values or connections)"
    )


class Workflow(BaseModel):
    """A ComfyUI workflow structure (API format)."""

    nodes: dict[str, WorkflowNode] = Field(default_factory=dict)

    def to_api_format(self) -> dict:
        """Convert to ComfyUI API format."""
        return {k: v.model_dump() for k, v in self.nodes.items()}

    @classmethod
    def from_api_format(cls, data: dict) -> "Workflow":
        """Create from ComfyUI API format."""
        nodes = {}
        for node_id, node_data in data.items():
            nodes[node_id] = WorkflowNode(**node_data)
        return cls(nodes=nodes)

    def add_node(self, node_id: str, class_type: str, inputs: dict) -> "Workflow":
        """Add a node to the workflow."""
        self.nodes[node_id] = WorkflowNode(class_type=class_type, inputs=inputs)
        return self


# === UI Workflow Models (Litegraph format) ===
# Based on: https://docs.comfy.org/specs/workflow_json


class UINodeFlags(BaseModel):
    """Visual flags for a node."""

    collapsed: bool = False
    pinned: bool = False
    allow_interaction: bool = True
    horizontal: bool = False
    skip_repeated_outputs: bool = False


class UINodeSlot(BaseModel):
    """Input or output slot on a node."""

    name: str
    type: str | list[str]
    link: int | None = None  # For inputs: link ID
    links: list[int] | None = None  # For outputs: list of link IDs
    slot_index: int | None = None


class UINode(BaseModel):
    """A node in Litegraph/UI format."""

    id: int
    type: str
    pos: tuple[float, float] | dict[str, float]
    size: tuple[float, float] | dict[str, float]
    flags: UINodeFlags = Field(default_factory=UINodeFlags)
    order: int = 0
    mode: int = 0
    inputs: list[UINodeSlot] = Field(default_factory=list)
    outputs: list[UINodeSlot] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    widgets_values: list[Any] | dict[str, Any] | None = None
    title: str | None = None
    color: str | None = None
    bgcolor: str | None = None


class UIWorkflowExtra(BaseModel):
    """Extra workflow metadata."""

    ds: dict[str, Any] | None = Field(default_factory=lambda: {"scale": 1, "offset": [0, 0]})


class SerialisableLLink(BaseModel):
    """A link in the SerialisableGraph format (object-based, version 1).

    Based on: ComfyUI_frontend/src/platform/workflow/validation/schemas/workflowSchema.ts
    zComfyLinkObject schema.
    """

    id: int = Field(description="Link ID")
    origin_id: int = Field(description="Output node ID")
    origin_slot: int = Field(description="Output slot index")
    target_id: int = Field(description="Input node ID")
    target_slot: int = Field(description="Input slot index")
    type: str = Field(description="Data type of the link")
    parentId: int | None = Field(default=None, description="Reroute parent ID")


class UIWorkflowState(BaseModel):
    """State tracking for version 1 workflows.

    Based on: zGraphState in workflowSchema.ts
    """

    lastNodeId: int = 0
    lastLinkId: int = 0
    lastGroupId: int = 0
    lastRerouteId: int = 0


class UIWorkflow(BaseModel):
    """ComfyUI workflow in SerialisableGraph format (version 1).

    Based on: ComfyUI_frontend/src/platform/workflow/validation/schemas/workflowSchema.ts
    zComfyWorkflow1 schema.

    Version 1 format uses:
    - `state` object instead of `last_node_id`/`last_link_id`
    - Object-based links instead of array-based
    """

    version: Literal[1] = 1
    state: UIWorkflowState = Field(default_factory=UIWorkflowState)
    nodes: list[UINode] = Field(default_factory=list)
    links: list[SerialisableLLink] = Field(default_factory=list)
    groups: list[dict] = Field(default_factory=list)
    extra: UIWorkflowExtra | None = Field(default_factory=UIWorkflowExtra)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return self.model_dump(exclude_none=True)


# === Error Models ===


class ErrorResponse(BaseModel):
    """Structured error response for MCP tools."""

    error: str
    code: str
    details: dict | None = None
    suggestion: str | None = None

    @classmethod
    def unavailable(cls, message: str = "ComfyUI is not reachable") -> "ErrorResponse":
        return cls(
            error=message,
            code="COMFY_UNAVAILABLE",
            suggestion="Ensure ComfyUI is running at the configured URL",
        )

    @classmethod
    def not_found(cls, resource: str, suggestion: str = None) -> "ErrorResponse":
        return cls(error=f"{resource} not found", code="NOT_FOUND", suggestion=suggestion)

    @classmethod
    def validation_error(cls, message: str, field: str = None) -> "ErrorResponse":
        return cls(
            error=message, code="VALIDATION_ERROR", details={"field": field} if field else None
        )

    @classmethod
    def not_configured(cls, setting: str) -> "ErrorResponse":
        return cls(
            error=f"{setting} not configured",
            code="NOT_CONFIGURED",
            suggestion=f"Set the {setting} environment variable",
        )


# === History Models ===


class HistoryStatus(BaseModel):
    """Status of a completed workflow."""

    status_str: str = "unknown"
    completed: bool = False
    messages: list[Any] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    """A history entry from /history endpoint."""

    prompt: list[Any] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    status: HistoryStatus | None = None
