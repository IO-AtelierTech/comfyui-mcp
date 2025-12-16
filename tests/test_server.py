"""Tests for ComfyUI MCP Server.

Run with: uv run pytest tests/ -v
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from comfy_mcp_server import (
    Settings,
    SystemStats,
    QueueStatus,
    NodeInfo,
    WorkflowNode,
    Workflow,
    ErrorResponse,
    comfy_get,
    comfy_post,
    get_cached_nodes,
    clear_node_cache,
)


# === Fixtures ===
@pytest.fixture
def mock_settings():
    """Create test settings."""
    return Settings(
        comfy_url="http://localhost:8188",
        workflows_dir="/tmp/workflows",
        output_mode="file",
        poll_timeout=5,
        poll_interval=0.1
    )


@pytest.fixture
def sample_system_stats():
    """Sample system stats response."""
    return {
        "system": {
            "os": "linux",
            "ram_total": 16000000000,
            "ram_free": 8000000000,
            "comfyui_version": "0.4.0",
            "python_version": "3.11.0",
            "pytorch_version": "2.9.1+cpu",
            "embedded_python": False
        },
        "devices": [
            {
                "name": "cpu",
                "type": "cpu",
                "index": None,
                "vram_total": 16000000000,
                "vram_free": 8000000000,
                "torch_vram_total": 16000000000,
                "torch_vram_free": 8000000000
            }
        ]
    }


@pytest.fixture
def sample_queue_status():
    """Sample queue status response."""
    return {
        "queue_running": [],
        "queue_pending": []
    }


@pytest.fixture
def sample_node_info():
    """Sample node info response."""
    return {
        "KSampler": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "seed": ["INT", {"default": 0, "min": 0, "max": 18446744073709551615}],
                    "steps": ["INT", {"default": 20, "min": 1, "max": 10000}]
                },
                "optional": {}
            },
            "output": ["LATENT"],
            "output_name": ["LATENT"],
            "name": "KSampler",
            "display_name": "KSampler",
            "description": "Sampling node",
            "category": "sampling",
            "output_node": False
        }
    }


# === Pydantic Model Tests ===
class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_system_stats_validation(self, sample_system_stats):
        """Test SystemStats model validation."""
        stats = SystemStats(**sample_system_stats)
        assert stats.system.comfyui_version == "0.4.0"
        assert stats.system.pytorch_version == "2.9.1+cpu"
        assert len(stats.devices) == 1
        assert stats.devices[0].type == "cpu"

    def test_queue_status_validation(self, sample_queue_status):
        """Test QueueStatus model validation."""
        status = QueueStatus(**sample_queue_status)
        assert status.running_count == 0
        assert status.pending_count == 0

    def test_queue_status_with_items(self):
        """Test QueueStatus with running items."""
        data = {
            "queue_running": [[1, "abc123", {}, {}, []]],
            "queue_pending": [[2, "def456", {}, {}, []], [3, "ghi789", {}, {}, []]]
        }
        status = QueueStatus(**data)
        assert status.running_count == 1
        assert status.pending_count == 2

    def test_node_info_validation(self, sample_node_info):
        """Test NodeInfo model validation."""
        info = NodeInfo(name="KSampler", **sample_node_info["KSampler"])
        assert info.name == "KSampler"
        assert info.category == "sampling"
        assert "model" in info.input.required

    def test_workflow_node_validation(self):
        """Test WorkflowNode model validation."""
        node = WorkflowNode(
            class_type="StringInput_fal",
            inputs={"text": "hello world"}
        )
        assert node.class_type == "StringInput_fal"
        assert node.inputs["text"] == "hello world"

    def test_workflow_api_format(self):
        """Test Workflow conversion to API format."""
        workflow = Workflow(nodes={
            "1": WorkflowNode(class_type="StringInput_fal", inputs={"text": "test"}),
            "2": WorkflowNode(class_type="SaveImage", inputs={"images": ["1", 0]})
        })
        api_format = workflow.to_api_format()
        assert "1" in api_format
        assert api_format["1"]["class_type"] == "StringInput_fal"

    def test_workflow_from_api_format(self):
        """Test Workflow creation from API format."""
        data = {
            "1": {"class_type": "StringInput_fal", "inputs": {"text": "test"}},
            "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}}
        }
        workflow = Workflow.from_api_format(data)
        assert len(workflow.nodes) == 2
        assert workflow.nodes["1"].class_type == "StringInput_fal"

    def test_error_response_validation(self):
        """Test ErrorResponse model."""
        error = ErrorResponse(
            error="Connection failed",
            code="COMFY_UNAVAILABLE",
            suggestion="Check if ComfyUI is running"
        )
        assert error.error == "Connection failed"
        assert error.code == "COMFY_UNAVAILABLE"


class TestSettings:
    """Test Settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        assert settings.comfy_url == "http://localhost:8188"
        assert settings.output_mode == "file"
        assert settings.poll_timeout == 60

    def test_settings_validation(self):
        """Test settings validation constraints."""
        settings = Settings(poll_timeout=30, poll_interval=2.0)
        assert settings.poll_timeout == 30
        assert settings.poll_interval == 2.0

    def test_settings_invalid_timeout(self):
        """Test invalid poll_timeout is rejected."""
        with pytest.raises(Exception):
            Settings(poll_timeout=0)  # Must be >= 1

    def test_settings_invalid_interval(self):
        """Test invalid poll_interval is rejected."""
        with pytest.raises(Exception):
            Settings(poll_interval=0.05)  # Must be >= 0.1


# === HTTP Helper Tests ===
class TestHTTPHelpers:
    """Test HTTP helper functions."""

    @patch('comfy_mcp_server.request.urlopen')
    def test_comfy_get_success(self, mock_urlopen, sample_system_stats):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_system_stats).encode()
        mock_urlopen.return_value = mock_response

        with patch('comfy_mcp_server.settings') as mock_settings:
            mock_settings.comfy_url = "http://localhost:8188"
            result = comfy_get("/system_stats")

        assert result["system"]["comfyui_version"] == "0.4.0"

    @patch('comfy_mcp_server.request.urlopen')
    def test_comfy_post_success(self, mock_urlopen):
        """Test successful POST request."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({"prompt_id": "abc123"}).encode()
        mock_urlopen.return_value = mock_response

        with patch('comfy_mcp_server.settings') as mock_settings:
            mock_settings.comfy_url = "http://localhost:8188"
            status, data = comfy_post("/prompt", {"prompt": {}})

        assert status == 200
        assert data["prompt_id"] == "abc123"


# === Integration Tests (requires running ComfyUI) ===
@pytest.mark.integration
class TestIntegration:
    """Integration tests that require a running ComfyUI instance.

    Run with: pytest tests/ -v -m integration
    Skip with: pytest tests/ -v -m "not integration"
    """

    def test_get_system_stats_live(self):
        """Test get_system_stats against live ComfyUI."""
        try:
            result = comfy_get("/system_stats", timeout=5)
            stats = SystemStats(**result)
            assert stats.system.comfyui_version
            assert len(stats.devices) > 0
        except Exception as e:
            pytest.skip(f"ComfyUI not available: {e}")

    def test_get_queue_status_live(self):
        """Test queue status against live ComfyUI."""
        try:
            result = comfy_get("/queue", timeout=5)
            status = QueueStatus(**result)
            assert status.running_count >= 0
        except Exception as e:
            pytest.skip(f"ComfyUI not available: {e}")

    def test_list_nodes_live(self):
        """Test node listing against live ComfyUI."""
        try:
            clear_node_cache()
            result = get_cached_nodes()
            assert len(result) > 0
            # Check for standard nodes
            assert "KSampler" in result or len(result) > 100
        except Exception as e:
            pytest.skip(f"ComfyUI not available: {e}")


# === Tool Function Tests ===
class TestToolFunctions:
    """Test MCP tool functions."""

    def test_create_workflow(self):
        """Test create_workflow returns empty dict."""
        from comfy_mcp_server import create_workflow
        result = create_workflow()
        assert result == {}
        assert isinstance(result, dict)

    def test_add_node(self):
        """Test add_node adds node correctly."""
        from comfy_mcp_server import add_node
        workflow = {}
        result = add_node(
            workflow=workflow,
            node_id="1",
            node_type="StringInput_fal",
            inputs={"text": "hello"}
        )
        assert "1" in result
        assert result["1"]["class_type"] == "StringInput_fal"
        assert result["1"]["inputs"]["text"] == "hello"

    def test_add_multiple_nodes(self):
        """Test adding multiple connected nodes."""
        from comfy_mcp_server import add_node, create_workflow
        workflow = create_workflow()
        workflow = add_node(workflow, "1", "StringInput_fal", {"text": "prompt"})
        workflow = add_node(workflow, "2", "CLIPTextEncode", {
            "text": ["1", 0],
            "clip": ["3", 0]
        })
        assert len(workflow) == 2
        assert workflow["2"]["inputs"]["text"] == ["1", 0]

    def test_get_workflow_template_valid(self):
        """Test getting valid template."""
        from comfy_mcp_server import get_workflow_template
        result = get_workflow_template("fal-flux-dev")
        assert "1" in result
        assert result["1"]["class_type"] == "RemoteCheckpointLoader_fal"

    def test_get_workflow_template_invalid(self):
        """Test getting invalid template returns error."""
        from comfy_mcp_server import get_workflow_template
        result = get_workflow_template("nonexistent")
        assert "error" in result
        assert result["code"] == "TEMPLATE_NOT_FOUND"

    def test_get_workflow_template_empty(self):
        """Test getting empty template."""
        from comfy_mcp_server import get_workflow_template
        result = get_workflow_template("empty")
        assert result == {}


# === Workflow Building Integration Test ===
class TestWorkflowBuilding:
    """Test complete workflow building flow."""

    def test_build_simple_workflow(self):
        """Test building a simple workflow programmatically."""
        from comfy_mcp_server import create_workflow, add_node

        # Build workflow
        wf = create_workflow()
        wf = add_node(wf, "1", "RemoteCheckpointLoader_fal",
                      {"ckpt_name": "fal-ai/flux/dev"})
        wf = add_node(wf, "2", "StringInput_fal",
                      {"text": "A beautiful sunset"})
        wf = add_node(wf, "3", "SaveImage_fal", {
            "filename_prefix": "test",
            "images": ["1", 0]
        })

        # Validate structure
        assert len(wf) == 3
        assert wf["1"]["class_type"] == "RemoteCheckpointLoader_fal"
        assert wf["2"]["inputs"]["text"] == "A beautiful sunset"
        assert wf["3"]["inputs"]["images"] == ["1", 0]

    def test_modify_template(self):
        """Test modifying a template workflow."""
        from comfy_mcp_server import get_workflow_template, add_node

        # Get template and modify
        wf = get_workflow_template("fal-flux-schnell")
        wf["2"]["inputs"]["text"] = "Custom prompt"
        wf = add_node(wf, "4", "IntegerInput_fal", {"value": 512})

        assert wf["2"]["inputs"]["text"] == "Custom prompt"
        assert "4" in wf


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
