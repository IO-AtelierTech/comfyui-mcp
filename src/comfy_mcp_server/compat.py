"""Compatibility layer for ComfyUI API changes.

This module handles differences between ComfyUI versions and provides
graceful degradation when APIs change.
"""

import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Version constants
MCP_SERVER_VERSION = "0.2.0"
MIN_COMFYUI_VERSION = "0.3.0"  # Minimum tested version
MAX_COMFYUI_VERSION = "0.4.x"  # Maximum tested version


class ComfyUIVersion(BaseModel):
    """Parsed ComfyUI version."""

    major: int
    minor: int
    patch: int
    raw: str

    @classmethod
    def parse(cls, version_str: str) -> "ComfyUIVersion":
        """Parse version string like '0.4.0' or '0.4.0-beta'."""
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str)
        if match:
            return cls(
                major=int(match.group(1)),
                minor=int(match.group(2)),
                patch=int(match.group(3)),
                raw=version_str,
            )
        return cls(major=0, minor=0, patch=0, raw=version_str)

    def __ge__(self, other: "ComfyUIVersion") -> bool:
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)

    def __le__(self, other: "ComfyUIVersion") -> bool:
        return (self.major, self.minor, self.patch) <= (other.major, other.minor, other.patch)


class APIFeature(Enum):
    """Features that may vary by ComfyUI version."""

    HISTORY_MAX_ITEMS = "history_max_items"  # Query param support
    QUEUE_PRIORITY = "queue_priority"  # Priority in queue
    INTERRUPT_PROMPT_ID = "interrupt_prompt_id"  # Target specific prompt
    MODEL_FOLDERS = "model_folders"  # /models endpoint
    OBJECT_INFO_NODE = "object_info_node"  # /object_info/{node}


class CompatibilityInfo(BaseModel):
    """Information about API compatibility."""

    server_version: str = MCP_SERVER_VERSION
    comfyui_version: str | None = None
    comfyui_parsed: ComfyUIVersion | None = None
    is_compatible: bool = True
    warnings: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)


def check_compatibility(comfyui_version: str) -> CompatibilityInfo:
    """Check compatibility between MCP server and ComfyUI version.

    Args:
        comfyui_version: Version string from ComfyUI /system_stats

    Returns:
        CompatibilityInfo with warnings and unsupported features
    """
    info = CompatibilityInfo(comfyui_version=comfyui_version)
    parsed = ComfyUIVersion.parse(comfyui_version)
    info.comfyui_parsed = parsed

    min_ver = ComfyUIVersion.parse(MIN_COMFYUI_VERSION)

    if parsed.major == 0 and parsed.minor == 0:
        info.warnings.append(f"Could not parse ComfyUI version: {comfyui_version}")
        return info

    if not (parsed >= min_ver):
        info.is_compatible = False
        info.warnings.append(
            f"ComfyUI {comfyui_version} is older than minimum tested version {MIN_COMFYUI_VERSION}"
        )

    # Version-specific feature detection
    if parsed.major == 0 and parsed.minor < 4:
        info.unsupported_features.append(APIFeature.INTERRUPT_PROMPT_ID.value)
        info.warnings.append("Interrupt with specific prompt_id may not work in older versions")

    return info


def safe_get_nested(data: dict, *keys, default: Any = None) -> Any:
    """Safely get nested dictionary values.

    Handles missing keys gracefully for forward/backward compatibility.

    Example:
        safe_get_nested(resp, "status", "completed", default=False)
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


def normalize_history_response(history: dict, prompt_id: str) -> dict:
    """Normalize history response across ComfyUI versions.

    Different versions may structure the response differently.
    This ensures consistent access patterns.
    """
    if prompt_id not in history:
        return {}

    entry = history[prompt_id]

    # Ensure consistent structure
    normalized = {
        "prompt_id": prompt_id,
        "status": {
            "completed": safe_get_nested(entry, "status", "completed", default=False),
            "status_str": safe_get_nested(entry, "status", "status_str", default="unknown"),
            "messages": safe_get_nested(entry, "status", "messages", default=[]),
        },
        "outputs": safe_get_nested(entry, "outputs", default={}),
        "prompt": safe_get_nested(entry, "prompt", default=[]),
    }

    return normalized


def normalize_node_info(node_data: dict) -> dict:
    """Normalize node info response across versions.

    Some fields may be added or renamed in different versions.
    """
    return {
        "name": node_data.get("name", ""),
        "display_name": node_data.get("display_name", node_data.get("name", "")),
        "description": node_data.get("description", ""),
        "category": node_data.get("category", ""),
        "input": {
            "required": safe_get_nested(node_data, "input", "required", default={}),
            "optional": safe_get_nested(node_data, "input", "optional", default={}),
        },
        "output": node_data.get("output", []),
        "output_name": node_data.get("output_name", node_data.get("output", [])),
        "output_node": node_data.get("output_node", False),
        # Handle potential future fields gracefully
        "deprecated": node_data.get("deprecated", False),
        "experimental": node_data.get("experimental", False),
    }


class APIError(Exception):
    """Base exception for ComfyUI API errors."""

    def __init__(self, message: str, code: str, details: dict = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ConnectionError(APIError):
    """ComfyUI is not reachable."""

    def __init__(self, message: str = "Cannot connect to ComfyUI"):
        super().__init__(message, "COMFY_UNAVAILABLE")


class WorkflowError(APIError):
    """Error in workflow execution."""

    def __init__(self, message: str, node_errors: dict = None):
        super().__init__(message, "WORKFLOW_ERROR", {"node_errors": node_errors or {}})


class ValidationError(APIError):
    """Invalid input parameters."""

    def __init__(self, message: str, field: str = None):
        super().__init__(message, "VALIDATION_ERROR", {"field": field})


class VersionMismatchError(APIError):
    """ComfyUI version incompatibility."""

    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"ComfyUI version {actual} is not compatible (expected {expected})",
            "VERSION_MISMATCH",
            {"expected": expected, "actual": actual},
        )


def log_api_call(endpoint: str, method: str, status: int, duration_ms: float):
    """Log API calls for debugging and monitoring."""
    level = logging.INFO if status == 200 else logging.WARNING
    logger.log(level, f"[{method}] {endpoint} -> {status} ({duration_ms:.1f}ms)")


def log_tool_call(tool_name: str, args: dict, success: bool, error: str = None):
    """Log MCP tool calls."""
    if success:
        logger.info(f"Tool {tool_name} called successfully")
    else:
        logger.error(f"Tool {tool_name} failed: {error}")
