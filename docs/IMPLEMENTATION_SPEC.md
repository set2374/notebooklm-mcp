# NotebookLM MCP Server - Implementation Specification

**Version:** 2.0
**Last Updated:** January 2026
**Target User:** Law practice with Google AI Ultra subscription
**Use Case:** Legal research, client file management, case document analysis

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Environment & Prerequisites](#environment--prerequisites)
3. [Implementation Phases](#implementation-phases)
4. [Phase 1: Reliability Hardening](#phase-1-reliability-hardening-completed)
5. [Phase 2: Ultra Feature Support](#phase-2-ultra-feature-support)
6. [Phase 3: Legal Research Tools](#phase-3-legal-research-tools)
7. [Phase 4: Skill & Configuration](#phase-4-skill--configuration)
8. [API Reference Updates](#api-reference-updates)
9. [Design Decisions](#design-decisions)

---

## Executive Summary

### Objective

Optimize the NotebookLM MCP server for a law practice use case with:
- Google AI Ultra subscription (highest tier limits)
- 300GB+ case document library
- Claude Code v2.1 with on-demand tool loading
- Proprietary skill and system instruction (not in repo)

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| **Keep 32 existing tools** | `ENABLE_TOOL_SEARCH=true` handles context; explicit names reduce legal work errors |
| **Add new tools (not consolidate)** | Non-breaking; preserves confirmation requirements |
| **Add Ultra-specific features** | Watermark removal, long slide decks |
| **Add batch_query + export** | Essential for legal research workflows |

### Google AI Ultra Limits (Reference)

| Feature | Ultra Limit |
|---------|-------------|
| Sources per notebook | 600 |
| Daily chats | 5,000 |
| Audio/Video Overviews | 200/day |
| Deep Research sessions | 200/day |
| Reports/Flashcards/Quizzes | 1,000/day |
| Notebooks | 500 |
| Words per source | 500,000 |

---

## Environment & Prerequisites

### Claude Code Configuration

```json
// ~/.claude/settings.json
{
  "environment": {
    "ENABLE_TOOL_SEARCH": "true",
    "MAX_MCP_OUTPUT_TOKENS": "50000"
  }
}
```

**Why `ENABLE_TOOL_SEARCH=true`:**
- Reduces context overhead from ~20,000 tokens to near-zero for unused tools
- Tools loaded on-demand when Claude determines they're needed
- Eliminates the need for tool consolidation

### MCP Server Registration

```bash
claude mcp add --scope user notebooklm-mcp notebooklm-mcp
```

### Authentication

```bash
# Initial setup
notebooklm-mcp-auth

# Verify before work sessions
# Use auth_status tool in Claude Code
```

---

## Implementation Phases

```
Phase 1: Reliability Hardening     [COMPLETED]
    ├── Retry logic with exponential backoff
    ├── Structured error responses
    └── auth_status tool

Phase 2: Ultra Feature Support     [COMPLETED]
    ├── Slide deck "long" length option
    ├── Watermark removal for infographics/slides
    └── API codes need verification via live testing

Phase 3: Legal Research Tools      [COMPLETED]
    ├── batch_query tool
    ├── export tool
    └── High-volume query support

Phase 4: Skill & Configuration     [USER-PROVIDED]
    ├── Proprietary legal research skill
    ├── System instruction
    └── Claude Code settings
```

---

## Phase 1: Reliability Hardening [COMPLETED]

### 1.1 Retry Logic with Exponential Backoff

**File:** `src/notebooklm_mcp/api_client.py`

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

class RetryableError(Exception):
    """Errors that should trigger retry (rate limits, server errors, network issues)."""
    pass

class AuthExpiredError(Exception):
    """Authentication has expired, requires manual re-auth."""
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(RetryableError),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_rpc(self, rpc_id: str, params: Any, ...) -> Any:
    """Execute RPC with automatic retry on transient failures."""
```

**Retry behavior:**
- 3 attempts maximum
- Exponential backoff: 2s, 4s, 8s (capped at 10s)
- Retries on: 429 (rate limit), 500/502/503/504 (server errors), network timeouts
- Does NOT retry: 401/403 (auth expired - raises `AuthExpiredError`)

### 1.2 Structured Error Responses

**File:** `src/notebooklm_mcp/server.py`

```python
class ErrorResponse(BaseModel):
    """Structured error response for actionable error messages."""
    status: Literal["error"]
    error: str
    action: str | None = None      # What the user should do
    details: str | None = None     # Additional context

def make_error(error: str, action: str | None = None, details: str | None = None) -> dict:
    """Create consistent, actionable error response."""
```

**Example output:**
```json
{
  "status": "error",
  "error": "Authentication expired",
  "action": "Run 'notebooklm-mcp-auth' to refresh credentials",
  "details": "Test request failed with auth error. Google session cookies have expired."
}
```

### 1.3 auth_status Tool

**File:** `src/notebooklm_mcp/server.py`

```python
@mcp.tool()
def auth_status() -> dict[str, Any]:
    """Check authentication status and cookie validity.

    Returns current auth state including:
    - Whether credentials exist
    - Approximate cookie age (if determinable)
    - Whether a test request succeeds

    Use this before starting work to verify NotebookLM access is working.
    """
```

**Success response:**
```json
{
  "status": "success",
  "authenticated": true,
  "notebook_count": 42,
  "cookie_age_days": 5,
  "warning": null,
  "cache_path": "/home/user/.notebooklm-mcp/auth.json"
}
```

**Warning response (cookies aging):**
```json
{
  "status": "success",
  "authenticated": true,
  "notebook_count": 42,
  "cookie_age_days": 9,
  "warning": "Cookies are 9 days old. They may expire soon.",
  "cache_path": "/home/user/.notebooklm-mcp/auth.json"
}
```

---

## Phase 2: Ultra Feature Support

### 2.1 Slide Deck Long Length Option

**Current state:** Only `short` and `default` lengths available
**Change:** Add `long` length option (Ultra-exclusive feature)

**File:** `src/notebooklm_mcp/api_client.py`

```python
# Add new constant
SLIDE_DECK_LENGTH_SHORT = 1
SLIDE_DECK_LENGTH_DEFAULT = 3
SLIDE_DECK_LENGTH_LONG = 4      # NEW - Ultra only

# Update _get_slide_deck_length_name()
@staticmethod
def _get_slide_deck_length_name(length_code: int) -> str:
    lengths = {
        1: "short",
        3: "default",
        4: "long",  # NEW
    }
    return lengths.get(length_code, "unknown")
```

**File:** `src/notebooklm_mcp/server.py`

```python
@mcp.tool()
def slide_deck_create(
    notebook_id: str,
    source_ids: list[str] | None = None,
    format: str = "detailed_deck",
    length: str = "default",        # Updated: now accepts "short", "default", "long"
    language: str = "en",
    focus_prompt: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate slide deck. Requires confirm=True after user approval.

    Args:
        notebook_id: Notebook UUID
        source_ids: Source IDs (default: all)
        format: detailed_deck|presenter_slides
        length: short|default|long (long requires Ultra subscription)
        language: BCP-47 code (en, es, fr, de, ja)
        focus_prompt: Optional focus text
        confirm: Must be True after user approval
    """
    # Map length string to code
    length_codes = {
        "short": 1,
        "default": 3,
        "long": 4,      # NEW
    }
```

**Note:** The actual API code for "long" (assumed to be 4) needs verification against the live API. This may require network capture during slide deck creation with the "long" option selected.

### 2.2 Watermark Removal Option

**Current state:** No watermark removal option
**Change:** Add `remove_watermark` parameter for infographics and slide decks (Ultra-exclusive)

**File:** `src/notebooklm_mcp/api_client.py`

```python
def create_infographic(
    self,
    notebook_id: str,
    source_ids: list[str],
    orientation_code: int = 1,
    detail_level_code: int = 2,
    language: str = "en",
    focus_prompt: str = "",
    remove_watermark: bool = False,     # NEW
) -> dict | None:
    """Create an infographic from notebook sources.

    Args:
        ...
        remove_watermark: Remove watermark (requires Ultra subscription)
    """
    # The API parameter structure for watermark removal needs to be
    # determined via network capture. Likely an additional field in
    # the options array.

def create_slide_deck(
    self,
    notebook_id: str,
    source_ids: list[str],
    format_code: int = 1,
    length_code: int = 3,
    language: str = "en",
    focus_prompt: str = "",
    remove_watermark: bool = False,     # NEW
) -> dict | None:
    """Create a slide deck from notebook sources.

    Args:
        ...
        remove_watermark: Remove watermark (requires Ultra subscription)
    """
```

**File:** `src/notebooklm_mcp/server.py`

```python
@mcp.tool()
def infographic_create(
    notebook_id: str,
    source_ids: list[str] | None = None,
    orientation: str = "landscape",
    detail_level: str = "standard",
    language: str = "en",
    focus_prompt: str = "",
    remove_watermark: bool = False,     # NEW
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate infographic. Requires confirm=True after user approval.

    Args:
        ...
        remove_watermark: Remove watermark (requires Ultra subscription)
        confirm: Must be True after user approval
    """

@mcp.tool()
def slide_deck_create(
    notebook_id: str,
    source_ids: list[str] | None = None,
    format: str = "detailed_deck",
    length: str = "default",
    language: str = "en",
    focus_prompt: str = "",
    remove_watermark: bool = False,     # NEW
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate slide deck. Requires confirm=True after user approval.

    Args:
        ...
        remove_watermark: Remove watermark (requires Ultra subscription)
        confirm: Must be True after user approval
    """
```

**Implementation Note:** The exact API parameter for watermark removal needs to be captured from the NotebookLM web interface. This requires:
1. Open Chrome DevTools Network tab
2. Create a slide deck or infographic with watermark removal enabled
3. Capture the batchexecute request body
4. Identify the parameter position for the watermark flag

---

## Phase 3: Legal Research Tools

### 3.1 batch_query Tool

**Purpose:** Query multiple notebooks or run multiple queries efficiently. Essential for cross-referencing case law across client files.

**File:** `src/notebooklm_mcp/server.py`

```python
@mcp.tool()
def batch_query(
    queries: list[dict],
    continue_on_error: bool = True,
) -> dict[str, Any]:
    """Run multiple queries across notebooks sequentially.

    Useful for legal research across multiple case files or running
    a series of related queries against a single notebook.

    Args:
        queries: List of query objects, each with:
            - notebook_id: str (required)
            - query: str (required)
            - source_ids: list[str] | None (optional, defaults to all)
        continue_on_error: If True, continue with remaining queries on failure

    Returns:
        {
            "status": "success" | "partial" | "error",
            "total": int,
            "succeeded": int,
            "failed": int,
            "results": [
                {
                    "notebook_id": str,
                    "query": str,
                    "status": "success" | "error",
                    "answer": str | None,
                    "error": str | None
                },
                ...
            ]
        }

    Example:
        batch_query(queries=[
            {"notebook_id": "abc123", "query": "What are the key findings?"},
            {"notebook_id": "def456", "query": "Summarize the plaintiff's arguments"},
            {"notebook_id": "abc123", "query": "List all cited precedents"}
        ])
    """
    try:
        client = get_client()
        results = []
        succeeded = 0
        failed = 0

        for q in queries:
            notebook_id = q.get("notebook_id")
            query_text = q.get("query")
            source_ids = q.get("source_ids")

            if not notebook_id or not query_text:
                results.append({
                    "notebook_id": notebook_id,
                    "query": query_text,
                    "status": "error",
                    "answer": None,
                    "error": "Missing required field: notebook_id or query"
                })
                failed += 1
                continue

            try:
                result = client.query(
                    notebook_id,
                    query_text=query_text,
                    source_ids=source_ids,
                )

                if result:
                    results.append({
                        "notebook_id": notebook_id,
                        "query": query_text,
                        "status": "success",
                        "answer": result.get("answer", ""),
                        "error": None
                    })
                    succeeded += 1
                else:
                    results.append({
                        "notebook_id": notebook_id,
                        "query": query_text,
                        "status": "error",
                        "answer": None,
                        "error": "Query returned no result"
                    })
                    failed += 1

            except AuthExpiredError as e:
                # Auth errors should stop everything
                return make_error(
                    error="Authentication expired during batch query",
                    action="Run 'notebooklm-mcp-auth' to refresh credentials",
                    details=f"Failed at query {len(results) + 1} of {len(queries)}"
                )

            except Exception as e:
                results.append({
                    "notebook_id": notebook_id,
                    "query": query_text,
                    "status": "error",
                    "answer": None,
                    "error": str(e)
                })
                failed += 1

                if not continue_on_error:
                    break

        # Determine overall status
        if failed == 0:
            status = "success"
        elif succeeded == 0:
            status = "error"
        else:
            status = "partial"

        return {
            "status": status,
            "total": len(queries),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    except Exception as e:
        return make_error(
            error="Batch query failed",
            action="Check query format and try again",
            details=str(e)
        )
```

### 3.2 export Tool

**Purpose:** Bulk extract content from notebooks for case file compilation, discovery responses, or client deliverables.

**File:** `src/notebooklm_mcp/server.py`

```python
@mcp.tool()
def export(
    notebook_id: str,
    format: str = "markdown",
    include_sources: bool = True,
    include_summary: bool = True,
) -> dict[str, Any]:
    """Export notebook content for external use.

    Extracts source content and optionally notebook summary for
    case file compilation or client deliverables.

    Args:
        notebook_id: Notebook UUID
        format: Output format - "markdown" | "json" | "text"
        include_sources: Include full source content (default: True)
        include_summary: Include AI-generated notebook summary (default: True)

    Returns:
        {
            "status": "success",
            "notebook_id": str,
            "title": str,
            "format": str,
            "summary": str | None,
            "sources": [
                {
                    "id": str,
                    "title": str,
                    "type": str,
                    "content": str,
                    "char_count": int
                },
                ...
            ],
            "total_chars": int,
            "source_count": int
        }
    """
    try:
        client = get_client()

        # Get notebook details
        notebook_data = client.get_notebook(notebook_id)
        if not notebook_data:
            return make_error(
                error="Notebook not found",
                action="Verify the notebook_id is correct",
                details=f"No notebook found with ID: {notebook_id}"
            )

        # Extract title and sources from notebook data
        # notebook_data structure: [title, sources_list, id, emoji, ...]
        title = notebook_data[0] if notebook_data else "Untitled"
        sources_raw = notebook_data[1] if len(notebook_data) > 1 else []

        result = {
            "status": "success",
            "notebook_id": notebook_id,
            "title": title,
            "format": format,
            "summary": None,
            "sources": [],
            "total_chars": 0,
            "source_count": 0,
        }

        # Get notebook summary if requested
        if include_summary:
            try:
                summary_result = client.get_notebook_summary(notebook_id)
                if summary_result:
                    result["summary"] = summary_result.get("summary", "")
            except Exception:
                # Summary is optional, continue without it
                pass

        # Extract source content if requested
        if include_sources and sources_raw:
            for source in sources_raw:
                # source structure varies, extract ID
                source_id = None
                source_title = "Unknown"

                if isinstance(source, list) and len(source) > 0:
                    source_id = source[0]
                    if len(source) > 1:
                        source_title = source[1] or "Untitled"

                if source_id:
                    try:
                        content_result = client.get_source_fulltext(source_id)
                        if content_result:
                            source_entry = {
                                "id": source_id,
                                "title": content_result.get("title", source_title),
                                "type": content_result.get("source_type", "unknown"),
                                "content": content_result.get("content", ""),
                                "char_count": content_result.get("char_count", 0),
                            }
                            result["sources"].append(source_entry)
                            result["total_chars"] += source_entry["char_count"]
                    except Exception as e:
                        # Log but continue with other sources
                        result["sources"].append({
                            "id": source_id,
                            "title": source_title,
                            "type": "error",
                            "content": f"Failed to extract: {str(e)}",
                            "char_count": 0,
                        })

        result["source_count"] = len(result["sources"])

        # Format output based on requested format
        if format == "markdown":
            result["formatted_output"] = _format_export_markdown(result)
        elif format == "text":
            result["formatted_output"] = _format_export_text(result)
        # JSON format is the default dict structure

        return result

    except AuthExpiredError:
        return make_error(
            error="Authentication expired",
            action="Run 'notebooklm-mcp-auth' to refresh credentials",
            details="Export failed due to auth error"
        )
    except Exception as e:
        return make_error(
            error="Export failed",
            action="Check notebook_id and try again",
            details=str(e)
        )


def _format_export_markdown(data: dict) -> str:
    """Format export data as markdown."""
    lines = [f"# {data['title']}", ""]

    if data.get("summary"):
        lines.extend(["## Summary", "", data["summary"], ""])

    if data.get("sources"):
        lines.extend(["## Sources", ""])
        for source in data["sources"]:
            lines.extend([
                f"### {source['title']}",
                f"*Type: {source['type']} | Characters: {source['char_count']:,}*",
                "",
                source["content"],
                "",
                "---",
                ""
            ])

    return "\n".join(lines)


def _format_export_text(data: dict) -> str:
    """Format export data as plain text."""
    lines = [data['title'], "=" * len(data['title']), ""]

    if data.get("summary"):
        lines.extend(["SUMMARY:", data["summary"], ""])

    if data.get("sources"):
        lines.append("SOURCES:")
        for i, source in enumerate(data["sources"], 1):
            lines.extend([
                f"\n[{i}] {source['title']} ({source['type']})",
                "-" * 40,
                source["content"],
                ""
            ])

    return "\n".join(lines)
```

---

## Phase 4: Skill & Configuration

### 4.1 Claude Code Settings

**File:** `~/.claude/settings.json`

```json
{
  "environment": {
    "ENABLE_TOOL_SEARCH": "true",
    "MAX_MCP_OUTPUT_TOKENS": "50000"
  },
  "permissions": {
    "allow": ["Skill"]
  }
}
```

### 4.2 Skill Structure (User-Provided)

The skill file is proprietary and not included in this repository. Expected location:

```
~/.claude/skills/notebooklm-legal-research/
├── SKILL.md                    # Core workflows and patterns
├── scripts/                    # Optional utility scripts
│   └── ...
└── references/                 # Detailed documentation
    └── ...
```

**SKILL.md frontmatter example:**

```yaml
---
name: NotebookLM Legal Research
description: Legal research workflows using NotebookLM for case management
---
```

### 4.3 System Instruction (User-Provided)

The system instruction is proprietary and configured separately in Claude Code.

---

## API Reference Updates

### New RPC Codes to Verify

| Feature | Suspected Code | Status |
|---------|---------------|--------|
| Slide Deck Long length | `4` | Needs verification |
| Watermark removal | Unknown | Needs capture |

### Network Capture Instructions

To verify API codes for Ultra features:

1. Open Chrome DevTools → Network tab
2. Navigate to notebooklm.google.com
3. Create content with the Ultra feature enabled
4. Find the `batchexecute` request
5. Examine the `f.req` parameter for the option structure
6. Update `api_client.py` with verified codes

---

## Design Decisions

### Why Not Consolidate Tools?

The original spec proposed reducing 32 tools to 8 consolidated tools. This was **not implemented** for these reasons:

1. **Claude Code v2.1 `ENABLE_TOOL_SEARCH`** - On-demand tool loading eliminates context overhead concern
2. **Breaking changes** - Would break existing workflows without migration path
3. **Confirmation requirements** - Consolidated tools risked losing safety checks for destructive operations
4. **Legal use case** - Explicit tool names (`notebook_delete` vs `notebook(action="delete")`) reduce errors in high-stakes work
5. **Skill layer handles orchestration** - The proprietary skill teaches when to use each tool

### Why Add batch_query and export?

1. **Legal research workflow** - Cross-referencing across case notebooks is a core need
2. **Ultra limits support it** - 5,000 chats/day makes batch operations practical
3. **Non-breaking** - New tools don't affect existing functionality
4. **Export for deliverables** - Case file compilation, discovery responses

### Error Handling Philosophy

All tools follow this pattern:
- **Success**: `{"status": "success", ...data...}`
- **Error**: `{"status": "error", "error": str, "action": str, "details": str}`
- **Partial**: `{"status": "partial", ...}` for batch operations with mixed results

The `action` field tells Claude (and the user) exactly what to do to resolve the error.

---

## Testing Checklist

### Phase 1 (Completed)
- [x] Retry logic triggers on 429, 500-504
- [x] AuthExpiredError raised on 401, 403
- [x] auth_status returns correct structure
- [x] auth_status detects missing credentials
- [x] auth_status warns on old cookies

### Phase 2 (Implemented - Needs Live Testing)
- [ ] Slide deck "long" option works
- [ ] Verify long length API code (assumed code 4)
- [ ] Watermark removal works for infographics
- [ ] Watermark removal works for slide decks
- [ ] Verify watermark API parameter position

### Phase 3 (Implemented - Needs Live Testing)
- [ ] batch_query processes multiple queries
- [ ] batch_query handles errors gracefully
- [ ] batch_query stops on auth errors
- [ ] export retrieves all source content
- [ ] export formats as markdown correctly
- [ ] export formats as text correctly
- [ ] export handles missing sources gracefully

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial Phase 1 implementation |
| 2.0 | Jan 2026 | Complete spec with Phases 2-4 |
| 2.1 | Jan 2026 | Phase 2 & 3 implemented, ready for live testing |
