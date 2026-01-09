"""Unit tests for NotebookLM authentication module."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from notebooklm_mcp.auth import (
    AuthTokens,
    get_cache_path,
    validate_cookies,
    parse_cookies_from_chrome_format,
    extract_csrf_from_page_source,
    extract_session_id_from_page,
    REQUIRED_COOKIES,
)


class TestAuthTokens:
    """Tests for AuthTokens dataclass."""

    def test_creation(self, sample_cookies):
        """Test creating AuthTokens."""
        tokens = AuthTokens(
            cookies=sample_cookies,
            csrf_token="test_csrf",
            session_id="test_session",
            extracted_at=time.time(),
        )
        assert tokens.cookies == sample_cookies
        assert tokens.csrf_token == "test_csrf"
        assert tokens.session_id == "test_session"

    def test_to_dict(self, sample_cookies):
        """Test converting to dictionary."""
        extracted_at = time.time()
        tokens = AuthTokens(
            cookies=sample_cookies,
            csrf_token="csrf",
            session_id="sid",
            extracted_at=extracted_at,
        )
        result = tokens.to_dict()
        assert result["cookies"] == sample_cookies
        assert result["csrf_token"] == "csrf"
        assert result["session_id"] == "sid"
        assert result["extracted_at"] == extracted_at

    def test_from_dict(self, sample_cookies):
        """Test creating from dictionary."""
        data = {
            "cookies": sample_cookies,
            "csrf_token": "csrf",
            "session_id": "sid",
            "extracted_at": 12345.0,
        }
        tokens = AuthTokens.from_dict(data)
        assert tokens.cookies == sample_cookies
        assert tokens.csrf_token == "csrf"
        assert tokens.session_id == "sid"
        assert tokens.extracted_at == 12345.0

    def test_from_dict_missing_optional(self, sample_cookies):
        """Test from_dict with missing optional fields."""
        data = {
            "cookies": sample_cookies,
        }
        tokens = AuthTokens.from_dict(data)
        assert tokens.csrf_token == ""
        assert tokens.session_id == ""

    def test_is_expired_false(self, sample_cookies):
        """Test is_expired returns False for fresh tokens."""
        tokens = AuthTokens(
            cookies=sample_cookies,
            extracted_at=time.time(),
        )
        assert tokens.is_expired() is False

    def test_is_expired_true(self, sample_cookies):
        """Test is_expired returns True for old tokens."""
        # Set extracted_at to 2 weeks ago
        old_time = time.time() - (2 * 7 * 24 * 3600)
        tokens = AuthTokens(
            cookies=sample_cookies,
            extracted_at=old_time,
        )
        assert tokens.is_expired() is True

    def test_is_expired_custom_max_age(self, sample_cookies):
        """Test is_expired with custom max_age."""
        # 2 hours ago
        tokens = AuthTokens(
            cookies=sample_cookies,
            extracted_at=time.time() - 7200,
        )
        # Default 168 hours - should not be expired
        assert tokens.is_expired() is False
        # 1 hour max - should be expired
        assert tokens.is_expired(max_age_hours=1) is True

    def test_cookie_header_property(self, sample_cookies):
        """Test cookie_header property."""
        tokens = AuthTokens(cookies=sample_cookies)
        header = tokens.cookie_header
        assert "SID=test_sid_value" in header
        assert "HSID=test_hsid_value" in header
        assert "; " in header


class TestGetCachePath:
    """Tests for get_cache_path function."""

    def test_returns_path(self):
        """Test that function returns a Path object."""
        path = get_cache_path()
        assert isinstance(path, Path)

    def test_path_in_home_directory(self):
        """Test path is in home directory."""
        path = get_cache_path()
        assert ".notebooklm-mcp" in str(path)
        assert path.name == "auth.json"


class TestValidateCookies:
    """Tests for validate_cookies function."""

    def test_valid_cookies(self, sample_cookies):
        """Test validation with all required cookies."""
        assert validate_cookies(sample_cookies) is True

    def test_missing_required_cookie(self):
        """Test validation with missing required cookie."""
        cookies = {
            "SID": "value",
            "HSID": "value",
            # Missing SSID, APISID, SAPISID
        }
        assert validate_cookies(cookies) is False

    def test_empty_cookies(self):
        """Test validation with empty cookies."""
        assert validate_cookies({}) is False

    def test_extra_cookies_ok(self, sample_cookies):
        """Test validation with extra cookies is still valid."""
        cookies = {**sample_cookies, "EXTRA": "value"}
        assert validate_cookies(cookies) is True


class TestParseCookiesFromChromeFormat:
    """Tests for parse_cookies_from_chrome_format function."""

    def test_basic_parsing(self):
        """Test basic cookie parsing."""
        cookies_list = [
            {"name": "SID", "value": "abc"},
            {"name": "HSID", "value": "def"},
        ]
        result = parse_cookies_from_chrome_format(cookies_list)
        assert result == {"SID": "abc", "HSID": "def"}

    def test_empty_list(self):
        """Test with empty list."""
        result = parse_cookies_from_chrome_format([])
        assert result == {}

    def test_missing_name(self):
        """Test with missing name field."""
        cookies_list = [
            {"value": "abc"},  # Missing name
            {"name": "HSID", "value": "def"},
        ]
        result = parse_cookies_from_chrome_format(cookies_list)
        assert result == {"HSID": "def"}

    def test_empty_name(self):
        """Test with empty name."""
        cookies_list = [
            {"name": "", "value": "abc"},
            {"name": "HSID", "value": "def"},
        ]
        result = parse_cookies_from_chrome_format(cookies_list)
        assert "HSID" in result
        assert "" not in result


class TestExtractCsrfFromPageSource:
    """Tests for extract_csrf_from_page_source function."""

    def test_snlm0e_pattern(self):
        """Test extracting CSRF from SNlM0e pattern."""
        html = '''<script>window.WIZ_global_data = {"SNlM0e":"test_csrf_token_123"}</script>'''
        result = extract_csrf_from_page_source(html)
        assert result == "test_csrf_token_123"

    def test_at_pattern(self):
        """Test extracting CSRF from at= pattern."""
        html = '''<form>at=another_csrf_token&other=value</form>'''
        result = extract_csrf_from_page_source(html)
        assert result == "another_csrf_token"

    def test_no_match(self):
        """Test when no CSRF token is found."""
        html = '''<html><body>No tokens here</body></html>'''
        result = extract_csrf_from_page_source(html)
        assert result is None


class TestExtractSessionIdFromPage:
    """Tests for extract_session_id_from_page function."""

    def test_fdrfje_pattern(self):
        """Test extracting session ID from FdrFJe pattern."""
        html = '''<script>{"FdrFJe":"1234567890"}</script>'''
        result = extract_session_id_from_page(html)
        assert result == "1234567890"

    def test_fsid_pattern(self):
        """Test extracting session ID from f.sid pattern."""
        html = '''<script>f.sid=9876543210</script>'''
        result = extract_session_id_from_page(html)
        assert result == "9876543210"

    def test_no_match(self):
        """Test when no session ID is found."""
        html = '''<html><body>No session here</body></html>'''
        result = extract_session_id_from_page(html)
        assert result is None


class TestRequiredCookies:
    """Tests for REQUIRED_COOKIES constant."""

    def test_required_cookies_defined(self):
        """Test that required cookies are defined."""
        assert len(REQUIRED_COOKIES) > 0
        assert "SID" in REQUIRED_COOKIES
        assert "HSID" in REQUIRED_COOKIES
        assert "SSID" in REQUIRED_COOKIES
