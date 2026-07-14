"""
Document Intake node — validates incoming page references.

Checks:
    - at least one page provided
    - file type is in the allowed whitelist
    - page references are not raw binaries (storage_key not base64 blob)

Does NOT perform file size checks here (enforced at upload endpoint).
Does NOT access the file system (storage_key is a path reference only).
"""
from __future__ import annotations

from services.gateway.ai.copilot.state import SchoolOSAIState, finish_node, start_node

_ALLOWED_TYPES = {"pdf", "png", "jpg", "jpeg", "docx", "txt"}


async def document_intake_node(state: SchoolOSAIState) -> SchoolOSAIState:
    started = start_node(state, "document_intake")

    inp = state.get("structured_input", {})
    pages: list[dict] = inp.get("pages", [])
    errors: list[str] = state.get("errors", [])

    if not pages:
        # Single-submission mode with no pages — still valid (answer entered manually)
        inp["pages_validated"] = False
        inp["intake_warnings"] = ["no_pages_provided"]
        state["structured_input"] = inp
        finish_node(state, "document_intake", started)
        return state

    valid_pages: list[dict] = []
    intake_warnings: list[str] = []

    for page in pages:
        storage_key: str = page.get("storage_key", "")
        file_type = storage_key.rsplit(".", 1)[-1].lower() if "." in storage_key else "unknown"

        # Reject raw binary blobs in state
        if len(storage_key) > 1000 or storage_key.startswith("data:"):
            intake_warnings.append(f"page_{page.get('page_number', '?')}_raw_binary_rejected")
            continue

        if file_type not in _ALLOWED_TYPES and storage_key:
            intake_warnings.append(f"page_{page.get('page_number', '?')}_unsupported_type_{file_type}")

        valid_pages.append(page)

    inp["pages"] = valid_pages
    inp["pages_validated"] = True
    inp["intake_warnings"] = intake_warnings
    state["structured_input"] = inp

    if intake_warnings:
        state["errors"] = errors + intake_warnings

    finish_node(state, "document_intake", started)
    return state
