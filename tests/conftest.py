"""Shared fictional run data; tests do not assert real model measurements."""

import pytest


@pytest.fixture
def run_record() -> dict:
    """A current-format successful run, copied afresh for each requesting test.

    The status and values are controlled test data. Unknown environment facts
    remain None, and the fictional model is never downloaded or run.
    """
    return {
        "schema_version": 1,
        "plan_id": "plan_0099",
        "run_id": "run_extract_0001",
        "stage": "extractor",
        "purpose": "development",
        "input_run_id": None,
        "retry_of_run_id": None,
        "source_path": "data/processed/plan_0099/preparation_02/preparation.json",
        "status": "succeeded",
        "started_at": "2026-11-03T12:00:00Z",
        "ended_at": "2026-11-03T12:00:01+00:00",
        "elapsed_seconds": 1.0,
        "settings": {
            "name": "fictional_extractor",
            "stage": "extractor",
            "model": {
                "name": "fictional-model",
                "execution_mode": "local",
                "endpoint": "http://localhost:11434",
                "api_service": None,
                "provider": None
            },
            "generation": {
                "temperature": 0,
                "top_p": None,
                "seed": None,
                "max_output_tokens": 8192
            },
            "context_limit": 32768,
            "prompt_paths": [
                "prompts/extractor.md",
                "prompts/shared.md"
            ],
            "max_tool_calls": 10,
            "model_timeout_seconds": 600,
            "image_input_enabled": False,
            "document_tools": {
                "ocr_enabled": False,
                "ocr_engine": None,
                "ocr_language": None,
                "image_render_dpi": 150,
                "tool_timeout_seconds": 120
            },
            "prompt_texts": [
                "Extract heat adaptation records.",
                "Preserve exact quotations."
            ],
            "environment": {
                "model_revision": None,
                "runtime": None,
                "runtime_version": None,
                "quantization": None,
                "hardware": None,
                "code_commit": None,
                "python_version": None,
                "model_client_version": None,
                "preparation_version": None,
                "tools_version": None,
                "ocr_version": None,
                "code_dirty": False,
                "model_loaded_at_start": None
            }
        },
        "model_calls": [
            {
                "input_tokens": 7,
                "output_tokens": 9,
                "finish_reason": "stop",
                "truncated": False,
                "response_path": "runs/plan_0099/run_extract_0001/responses/response_01.json"
            }
        ],
        "tool_log_path": None,
        "error": None,
        "plan_data": {
            "metadata": {
                "plan_title": "Fictional heat plan",
                "jurisdiction_name": None,
                "country": None,
                "plan_scale": None,
                "plan_type": None,
                "publication_year": None,
                "lead_agencies": [],
                "source_url": "https://example.org/plan.pdf",
                "date_accessed": "2026-11-03",
                "language": "English"
            },
            "actions": [
                {
                    "action_id": "action_0001",
                    "action": "Plant 20 trees.",
                    "action_type": [
                        "nature-based"
                    ],
                    "action_status": "planned",
                    "action_location": None,
                    "action_recipient": None,
                    "action_cost": None,
                    "action_benefit": None,
                    "evidence": [
                        {
                            "quote": "We will plant 20 trees.",
                            "page_numbers": [
                                1
                            ]
                        }
                    ]
                }
            ]
        },
        "plan_issues": {
            "issues": []
        }
    }
