"""Unit tests for NotebookLM API client."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from notebooklm_mcp.api_client import (
    ConversationTurn,
    NotebookLMClient,
    Notebook,
    extract_cookies_from_chrome_export,
    parse_timestamp,
    MAX_CONVERSATION_CACHE_SIZE,
    DEFAULT_USER_AGENT,
    IDX_ARTIFACT_STATUS,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
)


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_valid_timestamp(self, sample_timestamp_array):
        """Test parsing a valid timestamp."""
        result = parse_timestamp(sample_timestamp_array)
        assert result == "2024-01-01T00:00:00Z"

    def test_none_input(self):
        """Test with None input."""
        assert parse_timestamp(None) is None

    def test_empty_list(self):
        """Test with empty list."""
        assert parse_timestamp([]) is None

    def test_non_numeric_value(self):
        """Test with non-numeric value."""
        assert parse_timestamp(["not a number"]) is None

    def test_invalid_type(self):
        """Test with invalid type."""
        assert parse_timestamp("not a list") is None


class TestExtractCookies:
    """Tests for extract_cookies_from_chrome_export function."""

    def test_basic_extraction(self):
        """Test basic cookie extraction."""
        header = "SID=abc123; HSID=def456"
        result = extract_cookies_from_chrome_export(header)
        assert result == {"SID": "abc123", "HSID": "def456"}

    def test_with_spaces(self):
        """Test extraction with extra spaces."""
        header = "SID=abc123 ; HSID=def456"
        result = extract_cookies_from_chrome_export(header)
        assert result["SID"] == "abc123"
        assert result["HSID"] == "def456"

    def test_empty_string(self):
        """Test with empty string."""
        result = extract_cookies_from_chrome_export("")
        assert result == {}

    def test_complex_values(self):
        """Test with complex cookie values containing special chars."""
        header = "SID=abc=123; TOKEN=x/y/z"
        result = extract_cookies_from_chrome_export(header)
        assert result["SID"] == "abc=123"
        assert result["TOKEN"] == "x/y/z"


class TestNotebook:
    """Tests for Notebook dataclass."""

    def test_url_property(self):
        """Test URL generation."""
        nb = Notebook(
            id="test-uuid",
            title="Test",
            source_count=0,
            sources=[],
        )
        assert nb.url == "https://notebooklm.google.com/notebook/test-uuid"

    def test_ownership_owned(self):
        """Test ownership status for owned notebook."""
        nb = Notebook(
            id="test",
            title="Test",
            source_count=0,
            sources=[],
            is_owned=True,
        )
        assert nb.ownership == "owned"

    def test_ownership_shared(self):
        """Test ownership status for shared notebook."""
        nb = Notebook(
            id="test",
            title="Test",
            source_count=0,
            sources=[],
            is_owned=False,
        )
        assert nb.ownership == "shared_with_me"


class TestConversationTurn:
    """Tests for ConversationTurn dataclass."""

    def test_creation(self):
        """Test creating a conversation turn."""
        turn = ConversationTurn(
            query="What is X?",
            answer="X is Y.",
            turn_number=1,
        )
        assert turn.query == "What is X?"
        assert turn.answer == "X is Y."
        assert turn.turn_number == 1


class TestNotebookLMClientParsing:
    """Tests for NotebookLMClient response parsing methods."""

    @pytest.fixture
    def mock_client(self, sample_cookies):
        """Create a mock client that doesn't make real HTTP requests."""
        with patch.object(NotebookLMClient, '_refresh_auth_tokens'):
            client = NotebookLMClient(
                cookies=sample_cookies,
                csrf_token="test_csrf",
                session_id="test_session",
            )
        return client

    def test_parse_response_basic(self, mock_client, sample_batchexecute_response):
        """Test basic response parsing."""
        result = mock_client._parse_response(sample_batchexecute_response)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_parse_response_empty(self, mock_client):
        """Test parsing empty response."""
        result = mock_client._parse_response(")]}'")
        assert result == []

    def test_extract_rpc_result(self, mock_client):
        """Test extracting RPC result from parsed response."""
        parsed = [
            [["wrb.fr", "wXbhsf", '["Test Notebook"]', None, None, None, "generic"]]
        ]
        result = mock_client._extract_rpc_result(parsed, "wXbhsf")
        assert result == ["Test Notebook"]

    def test_extract_rpc_result_not_found(self, mock_client):
        """Test extracting non-existent RPC result."""
        parsed = [
            [["wrb.fr", "other_rpc", '["data"]', None, None, None, "generic"]]
        ]
        result = mock_client._extract_rpc_result(parsed, "wXbhsf")
        assert result is None

    def test_build_request_body(self, mock_client):
        """Test building request body."""
        body = mock_client._build_request_body("wXbhsf", [None, 1])
        assert "f.req=" in body
        assert "at=" in body
        assert body.endswith("&")

    def test_build_url(self, mock_client):
        """Test building URL with query params."""
        url = mock_client._build_url("wXbhsf", "/notebook/test")
        assert "rpcids=wXbhsf" in url
        assert "source-path=%2Fnotebook%2Ftest" in url
        assert "f.sid=test_session" in url


class TestConversationCache:
    """Tests for conversation caching with LRU eviction."""

    @pytest.fixture
    def mock_client(self, sample_cookies):
        """Create a mock client for cache testing."""
        with patch.object(NotebookLMClient, '_refresh_auth_tokens'):
            client = NotebookLMClient(
                cookies=sample_cookies,
                csrf_token="test_csrf",
                session_id="test_session",
            )
        return client

    def test_cache_conversation_turn(self, mock_client):
        """Test caching a conversation turn."""
        mock_client._cache_conversation_turn("conv-1", "Question?", "Answer.")
        assert "conv-1" in mock_client._conversation_cache
        assert len(mock_client._conversation_cache["conv-1"]) == 1

    def test_cache_multiple_turns(self, mock_client):
        """Test caching multiple turns in same conversation."""
        mock_client._cache_conversation_turn("conv-1", "Q1?", "A1.")
        mock_client._cache_conversation_turn("conv-1", "Q2?", "A2.")
        assert len(mock_client._conversation_cache["conv-1"]) == 2

    def test_lru_eviction(self, mock_client):
        """Test LRU eviction when cache exceeds max size."""
        # Fill cache beyond max size
        for i in range(MAX_CONVERSATION_CACHE_SIZE + 5):
            mock_client._cache_conversation_turn(f"conv-{i}", f"Q{i}?", f"A{i}.")

        # Cache should not exceed max size
        assert len(mock_client._conversation_cache) <= MAX_CONVERSATION_CACHE_SIZE

        # Oldest conversations should be evicted
        assert "conv-0" not in mock_client._conversation_cache

    def test_clear_conversation(self, mock_client):
        """Test clearing a specific conversation."""
        mock_client._cache_conversation_turn("conv-1", "Q?", "A.")
        mock_client._cache_conversation_turn("conv-2", "Q?", "A.")

        result = mock_client.clear_conversation("conv-1")
        assert result is True
        assert "conv-1" not in mock_client._conversation_cache
        assert "conv-2" in mock_client._conversation_cache

    def test_clear_nonexistent_conversation(self, mock_client):
        """Test clearing a conversation that doesn't exist."""
        result = mock_client.clear_conversation("nonexistent")
        assert result is False

    def test_build_conversation_history(self, mock_client):
        """Test building conversation history for follow-up."""
        mock_client._cache_conversation_turn("conv-1", "Q1?", "A1.")
        mock_client._cache_conversation_turn("conv-1", "Q2?", "A2.")

        history = mock_client._build_conversation_history("conv-1")
        assert history is not None
        assert len(history) == 4  # 2 turns x 2 entries each

    def test_build_conversation_history_empty(self, mock_client):
        """Test building history for nonexistent conversation."""
        history = mock_client._build_conversation_history("nonexistent")
        assert history is None


class TestUserAgentConfiguration:
    """Tests for User-Agent configuration."""

    def test_default_user_agent(self):
        """Test default User-Agent is used."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing NOTEBOOKLM_USER_AGENT
            os.environ.pop("NOTEBOOKLM_USER_AGENT", None)
            ua = NotebookLMClient._get_user_agent()
            assert ua == DEFAULT_USER_AGENT

    def test_custom_user_agent_from_env(self):
        """Test custom User-Agent from environment variable."""
        custom_ua = "CustomAgent/1.0"
        with patch.dict(os.environ, {"NOTEBOOKLM_USER_AGENT": custom_ua}):
            ua = NotebookLMClient._get_user_agent()
            assert ua == custom_ua

    def test_page_fetch_headers(self):
        """Test page fetch headers include User-Agent."""
        headers = NotebookLMClient._get_page_fetch_headers()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Sec-Fetch-Dest" in headers


class TestSourceTypeMapping:
    """Tests for source type mapping."""

    def test_google_docs_type(self):
        """Test Google Docs source type."""
        result = NotebookLMClient._get_source_type_name(1)
        assert result == "google_docs"

    def test_pasted_text_type(self):
        """Test pasted text source type."""
        result = NotebookLMClient._get_source_type_name(4)
        assert result == "pasted_text"

    def test_youtube_type(self):
        """Test YouTube source type."""
        result = NotebookLMClient._get_source_type_name(9)
        assert result == "youtube"

    def test_unknown_type(self):
        """Test unknown source type."""
        result = NotebookLMClient._get_source_type_name(999)
        assert result == "unknown"

    def test_none_type(self):
        """Test None source type."""
        result = NotebookLMClient._get_source_type_name(None)
        assert result == "unknown"


class TestAudioFormatMapping:
    """Tests for audio format mapping."""

    def test_deep_dive_format(self):
        """Test deep dive format mapping."""
        result = NotebookLMClient._get_audio_format_name(1)
        assert result == "deep_dive"

    def test_debate_format(self):
        """Test debate format mapping."""
        result = NotebookLMClient._get_audio_format_name(4)
        assert result == "debate"

    def test_unknown_format(self):
        """Test unknown format."""
        result = NotebookLMClient._get_audio_format_name(99)
        assert result == "unknown"


class TestConstants:
    """Tests for defined constants."""

    def test_artifact_indices(self):
        """Test artifact index constants are defined correctly."""
        assert IDX_ARTIFACT_STATUS == 4

    def test_status_codes(self):
        """Test status code constants."""
        assert STATUS_IN_PROGRESS == 1
        assert STATUS_COMPLETED == 3

    def test_max_cache_size(self):
        """Test max cache size is reasonable."""
        assert MAX_CONVERSATION_CACHE_SIZE > 0
        assert MAX_CONVERSATION_CACHE_SIZE <= 1000  # Reasonable upper bound
