"""Workflow execution tools.

Impact: Critical (core functionality)
Complexity: High (polling, error handling, image retrieval)
"""

import json
import urllib
from pathlib import Path

from mcp.server.fastmcp import Context, Image
from pydantic import Field

from ..api import comfy_get, comfy_post, get_file_url, poll_for_result
from ..models import ErrorResponse
from ..settings import settings


def is_ui_format(workflow: dict) -> bool:
    """Detect if workflow is in UI format (has nodes/links) vs API format (has class_type/inputs)."""
    return "nodes" in workflow or "version" in workflow


def register_execution_tools(mcp):
    """Register workflow execution tools."""

    @mcp.tool()
    def run_workflow(
        workflow_name: str = Field(description="Workflow filename"),
        inputs: dict = Field(default=None, description="Node input overrides"),
        output_node_id: str = Field(default=None, description="Output node ID"),
        ctx: Context = None,
    ) -> Image | str:
        """Execute a saved workflow file.

        Args:
            workflow_name: Workflow filename (e.g., 'flux-dev.json')
            inputs: Optional input overrides, e.g., {"6": {"text": "new prompt"}}
            output_node_id: Node ID to get output from (uses default if not set)

        Returns the generated image or error message.
        """
        if not settings.workflows_dir:
            return "Error: COMFY_WORKFLOWS_DIR not configured"

        wf_path = Path(settings.workflows_dir) / workflow_name
        if not wf_path.exists():
            return f"Error: Workflow '{workflow_name}' not found"

        if ctx:
            ctx.info(f"Loading workflow: {workflow_name}")

        with open(wf_path) as f:
            workflow = json.load(f)

        # Check for UI format workflows
        if is_ui_format(workflow):
            return (
                f"Error: Workflow '{workflow_name}' is in UI format (has nodes/widgets_values). "
                "UI format uses positional arrays that can cause parameter misalignment errors. "
                "Please re-export the workflow from ComfyUI using 'Export (API Format)' or use "
                "convert_workflow_to_ui() to create a UI version from an API format workflow."
            )

        # Apply input overrides
        if inputs:
            for node_id, values in inputs.items():
                if node_id in workflow:
                    if isinstance(values, dict):
                        workflow[node_id]["inputs"].update(values)
                    else:
                        # Simple value - try to set text input
                        if "text" in workflow[node_id]["inputs"]:
                            workflow[node_id]["inputs"]["text"] = values

        out_node = output_node_id or settings.output_node_id
        if not out_node:
            return "Error: No output_node_id specified"

        return _execute_workflow(workflow, out_node, ctx)

    @mcp.tool()
    def execute_workflow(
        workflow: dict = Field(description="Complete workflow dict"),
        output_node_id: str = Field(description="Node ID to get output from"),
        ctx: Context = None,
    ) -> Image | str:
        """Execute an arbitrary workflow dict.

        Args:
            workflow: Workflow dict in ComfyUI API format
            output_node_id: Node ID that outputs the final image

        Returns the generated image or error message.
        Use this for programmatically built workflows.
        """
        # Check for UI format workflows
        if is_ui_format(workflow):
            return (
                "Error: Workflow is in UI format (has nodes/widgets_values). "
                "UI format uses positional arrays that can cause parameter misalignment errors. "
                "Please provide workflow in API format with explicit 'class_type' and 'inputs'."
            )

        if ctx:
            ctx.info("Executing custom workflow...")
        return _execute_workflow(workflow, output_node_id, ctx)

    @mcp.tool()
    def generate_image(
        prompt: str = Field(description="Text prompt for image generation"),
        ctx: Context = None,
    ) -> Image | str:
        """Generate an image using the default workflow.

        This is a simplified interface for quick image generation.
        Requires COMFY_WORKFLOW_JSON_FILE, PROMPT_NODE_ID, and OUTPUT_NODE_ID
        to be configured.

        For more control, use run_workflow() or execute_workflow().

        Args:
            prompt: Text description of the image to generate
        """
        if not settings.workflow_json_file:
            return "Error: COMFY_WORKFLOW_JSON_FILE not configured"
        if not settings.prompt_node_id:
            return "Error: PROMPT_NODE_ID not configured"
        if not settings.output_node_id:
            return "Error: OUTPUT_NODE_ID not configured"

        with open(settings.workflow_json_file) as f:
            workflow = json.load(f)

        workflow[settings.prompt_node_id]["inputs"]["text"] = prompt

        if ctx:
            ctx.info(f"Generating: {prompt[:50]}...")

        return _execute_workflow(workflow, settings.output_node_id, ctx)

    @mcp.tool()
    def submit_workflow(
        workflow: dict = Field(description="Workflow to submit"),
        ctx: Context = None,
    ) -> dict:
        """Submit a workflow without waiting for completion.

        Args:
            workflow: Workflow dict to execute

        Returns the prompt_id for tracking.
        Use get_history() or get_prompt_status() to check completion.
        """
        if ctx:
            ctx.info("Submitting workflow...")

        status, resp = comfy_post("/prompt", {"prompt": workflow})

        if status != 200:
            return ErrorResponse(
                error=f"Submit failed: status {status}",
                code="SUBMIT_FAILED",
                details=resp,
            ).model_dump()

        return {
            "prompt_id": resp.get("prompt_id"),
            "number": resp.get("number"),
            "node_errors": resp.get("node_errors", {}),
        }

    @mcp.tool()
    def get_prompt_status(
        prompt_id: str = Field(description="Prompt ID to check"),
        ctx: Context = None,
    ) -> dict:
        """Get the status of a submitted prompt.

        Args:
            prompt_id: The prompt ID from submit_workflow()

        Returns status information including completion state.
        """
        if ctx:
            ctx.info(f"Checking status: {prompt_id}")

        try:
            history = comfy_get(f"/history/{prompt_id}")
            if prompt_id not in history:
                return {"status": "pending", "completed": False}

            entry = history[prompt_id]
            status = entry.get("status", {})
            return {
                "status": status.get("status_str", "unknown"),
                "completed": status.get("completed", False),
                "messages": status.get("messages", []),
                "has_outputs": len(entry.get("outputs", {})) > 0,
            }
        except Exception as e:
            return ErrorResponse.unavailable(str(e)).model_dump()

    @mcp.tool()
    def get_result_image(
        prompt_id: str = Field(description="Prompt ID"),
        output_node_id: str = Field(description="Output node ID"),
        ctx: Context = None,
    ) -> Image | str:
        """Get the result image from a completed prompt.

        Args:
            prompt_id: The prompt ID from submit_workflow()
            output_node_id: Node ID that produced the image

        Returns the image if available, or error message.
        """
        if ctx:
            ctx.info(f"Getting result: {prompt_id}")

        try:
            history = comfy_get(f"/history/{prompt_id}")
            if prompt_id not in history:
                return "Prompt not found in history"

            entry = history[prompt_id]
            status = entry.get("status", {})

            if not status.get("completed"):
                return "Prompt not yet completed"

            outputs = entry.get("outputs", {})
            if output_node_id not in outputs:
                return f"No output from node {output_node_id}"

            images = outputs[output_node_id].get("images", [])
            if not images:
                return "No images in output"

            # Download image
            url = get_file_url(settings.comfy_url, images[0])
            from ..api import download_file

            image_data = download_file(url)
            if image_data:
                return Image(data=image_data, format="png")
            return "Failed to download image"

        except Exception as e:
            return f"Error: {e}"


def _execute_workflow(workflow: dict, output_node_id: str, ctx: Context | None) -> Image | str:
    """Internal function to execute workflow and return result."""
    # Submit workflow
    status, resp_data = comfy_post("/prompt", {"prompt": workflow})

    if status != 200:
        error_msg = resp_data.get("error", f"status {status}")
        return f"Failed to submit workflow: {error_msg}"

    prompt_id = resp_data.get("prompt_id")
    if not prompt_id:
        node_errors = resp_data.get("node_errors", {})
        if node_errors:
            return f"Workflow validation failed:\n{json.dumps(node_errors, indent=2)}"
        return "Failed to get prompt_id from response"

    if ctx:
        ctx.info(f"Submitted: {prompt_id}")

    # Poll callback for progress logging
    def on_poll(attempt: int, max_attempts: int):
        if ctx and attempt % 5 == 0:
            ctx.info(f"Waiting... ({attempt}/{max_attempts})")

    # Poll for result
    image_data = poll_for_result(prompt_id, output_node_id, on_poll=on_poll)

    if image_data:
        if ctx:
            ctx.info("Image generated successfully")

        if settings.output_mode.lower() == "url":
            # Return URL instead of image data
            history = comfy_get(f"/history/{prompt_id}")
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if output_node_id in outputs:
                    images = outputs[output_node_id].get("images", [])
                    if images:
                        url_values = urllib.parse.urlencode(images[0])
                        return get_file_url(settings.comfy_url_external, url_values)

        return Image(data=image_data, format="png")

    return "Failed to generate image. Use get_queue_status() and get_history() to debug."
