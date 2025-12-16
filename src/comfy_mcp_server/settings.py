"""Configuration settings for ComfyUI MCP Server.

Settings are loaded from environment variables with sensible defaults.
Looks for .env files in current directory and parent directory.
"""

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _find_env_files() -> list[Path]:
    """Find .env files in current and parent directories."""
    env_files = []
    cwd = Path.cwd()

    # Check current directory
    if (cwd / ".env").exists():
        env_files.append(cwd / ".env")

    # Check parent directory (for when running from mcp/ submodule)
    if (cwd.parent / ".env").exists():
        env_files.append(cwd.parent / ".env")

    # Check two levels up (for src/comfy_mcp_server/)
    if (cwd.parent.parent / ".env").exists():
        env_files.append(cwd.parent.parent / ".env")

    return env_files if env_files else [Path(".env")]


class Settings(BaseSettings):
    """Server configuration loaded from environment variables.

    Environment Variables:
        COMFY_URL: ComfyUI server URL (default: http://localhost:8188)
        COMFY_URL_EXTERNAL: External URL for image retrieval
        COMFY_WORKFLOWS_DIR: Directory containing workflow JSON files
        COMFY_WORKFLOW_JSON_FILE: Default workflow file for generate_image
        PROMPT_NODE_ID: Default prompt node ID
        OUTPUT_NODE_ID: Default output node ID
        OUTPUT_MODE: Output mode - 'file' or 'url' (default: file)
        POLL_TIMEOUT: Max seconds to wait for workflow (default: 60)
        POLL_INTERVAL: Seconds between polls (default: 1.0)
    """

    comfy_url: str = Field(default="http://localhost:8188", description="ComfyUI server URL")
    comfy_url_external: str | None = Field(
        default=None, description="External URL for image retrieval"
    )
    workflows_dir: str | None = Field(
        default=None,
        alias="comfy_workflows_dir",
        description="Directory containing API format workflow JSON files",
    )
    workflows_ui_dir: str | None = Field(
        default=None,
        alias="comfy_workflows_ui_dir",
        description="Directory containing UI format workflow JSON files",
    )
    workflow_json_file: str | None = Field(
        default=None,
        alias="comfy_workflow_json_file",
        description="Default workflow file for generate_image",
    )
    prompt_node_id: str | None = Field(default=None, description="Default prompt node ID")
    output_node_id: str | None = Field(default=None, description="Default output node ID")
    output_mode: str = Field(
        default="file", description="Output mode: 'file' (Image) or 'url' (string URL)"
    )
    poll_timeout: int = Field(
        default=60, ge=1, le=300, description="Max seconds to wait for workflow completion"
    )
    poll_interval: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Seconds between status polls"
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        env_file=_find_env_files(),
        env_file_encoding="utf-8",
    )

    @field_validator("comfy_url_external", mode="before")
    @classmethod
    def set_external_url(cls, v, info):
        """Default external URL to comfy_url if not set."""
        return v or info.data.get("comfy_url", "http://localhost:8188")

    @field_validator("output_mode")
    @classmethod
    def validate_output_mode(cls, v):
        """Ensure output_mode is valid."""
        v = v.lower()
        if v not in ("file", "url"):
            raise ValueError("output_mode must be 'file' or 'url'")
        return v


def load_settings() -> Settings:
    """Load and validate settings from environment."""
    try:
        settings = Settings()

        # Derive workflows_dir from workflow file if not set
        if settings.workflows_dir is None and settings.workflow_json_file:
            settings.workflows_dir = str(Path(settings.workflow_json_file).parent)

        return settings
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        # Return defaults on error
        return Settings()


# Global settings instance
settings = load_settings()


def reload_settings() -> Settings:
    """Reload settings from environment (useful for testing)."""
    global settings
    settings = load_settings()
    return settings
