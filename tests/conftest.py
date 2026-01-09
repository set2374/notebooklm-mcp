"""Pytest fixtures for NotebookLM MCP tests."""

import pytest


@pytest.fixture
def sample_cookies() -> dict[str, str]:
    """Sample cookies for testing (not real credentials)."""
    return {
        "SID": "test_sid_value",
        "HSID": "test_hsid_value",
        "SSID": "test_ssid_value",
        "APISID": "test_apisid_value",
        "SAPISID": "test_sapisid_value",
    }


@pytest.fixture
def sample_cookie_header() -> str:
    """Sample cookie header string for testing."""
    return "SID=test_sid; HSID=test_hsid; SSID=test_ssid; APISID=test_apisid; SAPISID=test_sapisid"


@pytest.fixture
def sample_batchexecute_response() -> str:
    """Sample batchexecute response for parsing tests."""
    return """)]}'
123
[["wrb.fr","wXbhsf","[\\"Test Notebook\\",[[[\\"src-123\\"],\\"Source 1\\"]],\\"nb-uuid-123\\"]",null,null,null,"generic"]]
"""


@pytest.fixture
def sample_notebook_data() -> list:
    """Sample notebook data structure."""
    return [
        "Test Notebook",  # Title
        [  # Sources
            [["src-123"], "Source 1", [None, None, None, None, 1]],
            [["src-456"], "Source 2", [None, None, None, None, 4]],
        ],
        "nb-uuid-123",  # Notebook ID
        None,  # Emoji
        None,
        [1, False, True, None, None, [1704067200, 0], None, None, [1704067100, 0]],  # Metadata
    ]


@pytest.fixture
def sample_timestamp_array() -> list:
    """Sample timestamp array [seconds, nanoseconds]."""
    return [1704067200, 0]  # 2024-01-01 00:00:00 UTC
