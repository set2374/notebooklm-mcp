# InfiAgent Implementation Analysis

**Date:** January 10, 2026
**Repository:** https://github.com/ChenglinPoly/infiAgent
**License:** GPL-3.0
**Analyzed Commit:** Latest (cloned January 10, 2026)

---

## Repository Structure

```
infiAgent/
├── core/                        # Core agent logic
│   ├── agent_executor.py        # Main execution loop (562 lines)
│   ├── context_builder.py       # XML context construction (687 lines)
│   ├── hierarchy_manager.py     # Agent hierarchy management (412 lines)
│   ├── state_cleaner.py         # Pre-start state cleanup (196 lines)
│   └── tool_executor.py         # Tool execution via HTTP (341 lines)
├── services/
│   ├── action_compressor.py     # History compression (749 lines)
│   ├── llm_client.py            # LiteLLM client wrapper (863 lines)
│   └── thinking_agent.py        # Consolidation/planning agent (256 lines)
├── tool_server_lite/
│   └── tools/                   # 11 tool implementation files
│       ├── file_tools.py        # File I/O operations
│       ├── web_tools.py         # Web search/crawling
│       ├── document_tools.py    # Document parsing
│       ├── code_tools.py        # Code execution
│       └── ...
├── config/
│   ├── agent_library/Default/   # Agent configurations
│   │   ├── general_prompts.yaml # System prompts
│   │   ├── level_0_tools.yaml   # Base tools (678 lines)
│   │   ├── level_1_agents.yaml  # Sub-agents (35K lines)
│   │   ├── level_2_agents.yaml  # Level 2 agents
│   │   └── level_3_agents.yaml  # Level 3 agents
│   └── run_env_config/          # Runtime configuration
├── utils/                       # Utilities
│   ├── config_loader.py         # Configuration management
│   ├── cli_mode.py              # Interactive CLI
│   └── event_emitter.py         # JSONL event streaming
├── start.py                     # Entry point (340 lines)
├── requirements.txt             # Dependencies
└── README.md                    # Documentation
```

---

## Architecture Findings

### Hierarchy Manager (`core/hierarchy_manager.py`)

**Implementation approach:**
- Uses a **stack-based model** rather than a true DAG/tree
- Agent hierarchy stored in JSON files on disk (not in-memory graphs)
- Files stored in `~/mla_v3/conversations/` with task-specific naming

**Key data structures:**
```python
# Stack file: {task_hash}_stack.json
{
  "stack": [
    {"agent_id": "alpha_agent_abc123", "agent_name": "alpha_agent",
     "parent_id": null, "level": 0, "user_input": "..."},
    {"agent_id": "research_agent_def456", "agent_name": "research_agent",
     "parent_id": "alpha_agent_abc123", "level": 1, "user_input": "..."}
  ]
}

# Context file: {task_hash}_share_context.json
{
  "current": {
    "instructions": [...],
    "hierarchy": {"agent_id": {"parent": "...", "children": [...], "level": N}},
    "agents_status": {"agent_id": {"status": "running|completed", "latest_thinking": "..."}}
  },
  "history": [/* completed task snapshots */]
}
```

**Permission enforcement:**
- No runtime validation - permissions are implicit via tool availability
- Each agent level defines its `available_tools` in YAML config
- Sub-agents cannot call tools not in their config

**Call graph tracking:**
- Parent-child relationships tracked via `parent_id` in both stack and hierarchy
- `children` array in hierarchy allows traversal from parent to children
- Stack maintains current execution path (linear)

**How Alpha Agent invokes sub-agents:**
- Sub-agents are defined as `type: llm_call_agent` in YAML configs
- Parent calls sub-agent like any tool via `tool_executor.execute()`
- `ToolExecutor._execute_sub_agent()` recursively creates new `AgentExecutor`

---

### Agent Executor (`core/agent_executor.py`)

**Execution loop structure:**
```python
for turn in range(start_turn, self.max_turns):  # max_turns = 10,000,000
    # 1. Compress history if needed
    self._compress_action_history_if_needed()

    # 2. Build XML context (system prompt)
    full_system_prompt = self.context_builder.build_context(...)

    # 3. Call LLM with tool_choice="required"
    llm_response = self.llm_client.chat(
        history=[{"role": "user", "content": "请输出下一个动作"}],
        tool_list=self.available_tools,
        tool_choice="required"
    )

    # 4. Execute each tool call
    for tool_call in llm_response.tool_calls:
        tool_result = self.tool_executor.execute(tool_call.name, ...)
        self.action_history.append(action_record)

        # 5. Check for final_output → return
        if tool_call.name == "final_output":
            return tool_result

    # 6. Trigger thinking every N tool calls
    if self.tool_call_counter % self.thinking_interval == 0:
        self._trigger_thinking(...)
        self.action_history = []  # CLEAR history after thinking!
```

**Context reconstruction:**
- Built by `ContextBuilder.build_context()` each turn
- Combines: general prompts + user input + agent history + call info + thinking + action history
- Uses XML tags: `<用户最新输入>`, `<历史动作>`, `<当前进度思考>`, etc.

**Action window:**
- `thinking_interval = 10` (configurable in code, not config)
- After every 10 tool calls, `_trigger_thinking()` is called
- **Critical: `self.action_history = []` clears history after thinking!**
- Two histories maintained:
  - `action_history` - for rendering (gets compressed/cleared)
  - `action_history_fact` - complete trajectory (never compressed)

---

### Ten-Step Consolidation Mechanism

**Location:** `services/thinking_agent.py` + `core/agent_executor.py:310-323`

**Implementation details:**
- **10 steps IS hardcoded** in `agent_executor.py:84`: `self.thinking_interval = 10`
- Not exposed in YAML configuration

**How it works:**
1. Counter increments on each tool call (`self.tool_call_counter += 1`)
2. Every 10 calls: `if self.tool_call_counter % self.thinking_interval == 0`
3. `ThinkingAgent.analyze_first_thinking()` is called (same method for both initial and periodic)
4. LLM generates structured thinking in XML format:
   - `<todo_list>` - Task breakdown with status [done/ongoing/waiting]
   - `<有效文件描述>` - Valid files and their purposes
   - `<固化信息>` - Information to preserve (workspace state, rules, content)
   - `<next_n_steps>` - Concrete plan for next 10 tool calls

**State snapshot contents (from thinking_agent.py system prompt):**
```xml
<todo_list>
  1. Task item: [done]
  2. Task item: [ongoing:progress notes]
  3. Task item: [waiting]
</todo_list>

<有效文件描述>
  ./document_summary.md: [description and purpose]
  ./papers/X5.pdf: [to be analyzed]
</有效文件描述>

<固化信息>
  workspace:
    [dir] code_run
      [file] service.py [description]
  rules:
    1. All output must be in English
  content_need_next_steps:
    outline.txt: (relevant content)
</固化信息>

<next_n_steps>
  1. Use answer_from_one_paper tool on XX9.pdf
  2. Use file_read to read related files
  3. Use dir_list to check for naming conflicts
  4. Use file_write to create output
  5. Use final_output to complete
</next_n_steps>
```

**Critical observation:** After thinking completes, `self.action_history = []` clears the action history completely. The thinking output IS the state that persists across the "context boundary."

---

### Tool Architecture

**Tool count:** 34+ tools across 11 implementation files

**Registration pattern:**
- Tools defined in YAML configs (`level_0_tools.yaml`)
- Two types: `tool_call_agent` (HTTP tools) and `llm_call_agent` (sub-agents)
- Tool server runs separately via FastAPI (`tool_server_lite/server.py`)

**Key tool implementations:**

| Tool | Implementation | Description |
|------|----------------|-------------|
| `file_read` | file_tools.py | Reads files with line numbers, batch support |
| `file_write` | file_tools.py | Write/append with line replacement |
| `execute_code` | code_tools.py | Python execution in venv, background support |
| `crawl_page` | web_tools.py | Web crawling via crawl4ai |
| `parse_document` | document_tools.py | PDF/Word parsing via pdfplumber |
| `paper_analyze_tool` | paper_tools.py | LLM-powered paper analysis |

**Document query tools:**
- `paper_analyze_tool`: Parses document, sends content to LLM with question
- `answer_from_papers` (Level 1 agent): Multi-document Q&A workflow
- No dedicated "query-driven extraction" - documents are fully parsed then queried

**Batch file operations:**
- `file_read`: Accepts array of paths, returns combined JSON with line numbers
- `file_move`: Supports array of source paths

---

### Workspace Management

**Workspace creation:**
- `task_id` is an absolute path that serves as workspace root
- Default test workspace: `~/mla_v3/task_test/`
- Tools resolve relative paths: `workspace / relative_path`

**Workspace structure:**
```
{task_id}/
├── upload/           # User uploads
├── temp/             # Temporary files by category
│   ├── web_search/
│   ├── scholar_search/
│   ├── arxiv_search/
│   ├── crawl_page/
│   └── parse_document/
├── papers/           # Downloaded papers
├── code_run/         # Code execution workspace
├── reference.bib     # Shared bibliography
└── [user files]
```

**Metadata files (stored in `~/mla_v3/conversations/`):**
- `{hash}_stack.json` - Agent execution stack
- `{hash}_share_context.json` - Hierarchy and status
- `{hash}_{agent_id}_actions.json` - Per-agent action history

**State snapshotting:**
- Continuous saves via `_save_state()` after each tool call
- Supports resume on crash via `loaded_data = conversation_storage.load_actions()`

---

## Verification Status

| Paper Claim | Implementation | Notes |
|-------------|----------------|-------|
| File-centric state | ✅ **Verified** | Workspace as state, all outputs to files |
| 10-step consolidation | ✅ **Verified** | `thinking_interval=10`, clears history after |
| Bounded context | ✅ **Verified** | Action history cleared after thinking |
| Agent hierarchy (3 levels) | ✅ **Verified** | Configs define levels 0-3 |
| Batch file operations | ⚠️ **Partial** | file_read/move support arrays, not all tools |
| DAG structure | ❌ **Simplified** | Stack-based, not true DAG |
| Dual-audit mechanism | ❌ **Not Found** | `judge_agent` exists but optional, not systematic |

---

## Code Quality Assessment

**Documentation:**
- **Adequate** - Chinese comments throughout, some English
- README is comprehensive with Chinese/English versions
- No API documentation or docstrings in most functions

**Error handling:**
- **Adequate** - Try/catch blocks in critical paths
- Graceful degradation (e.g., encoding detection fallback)
- Retry logic in LLM client (3 retries with exponential backoff)
- JSON repair attempts for malformed tool calls

**Test coverage:**
- **Minimal** - Only `tests/test_file_tools.py` found
- No unit tests for core components
- Manual test scripts (`test_toolserver.sh`)

**Production readiness:**
- **Medium** - Functional but rough edges
- File-based state (not database) limits scalability
- No authentication/authorization on tool server
- Hardcoded intervals and paths in places

---

## Adaptation Potential

### Patterns Worth Adopting

1. **Workspace-as-State Abstraction**
   - Legal AI: Map to "matter folders" with standard structure
   - Benefits: Clear audit trail, file-based artifacts, resumability
   - Implementation: Straightforward directory structure pattern

2. **Periodic Consolidation (Thinking Module)**
   - Legal AI: Useful for long document review tasks
   - Benefits: Prevents context overflow, maintains coherence
   - Adaptation: Change interval based on task complexity, not fixed 10

3. **XML-Structured Context**
   - Legal AI: Clear section demarcation for legal reasoning
   - Benefits: LLM can reference specific sections
   - Note: Could use `<legal_research>`, `<case_facts>`, etc.

4. **Two-Track History (Render vs. Fact)**
   - Legal AI: Critical for compliance/audit
   - `action_history_fact` provides complete provenance
   - Essential for legal matter audit trails

5. **Agent Configuration via YAML**
   - Legal AI: Easy to define specialized legal agents
   - Pattern: `level_1: contract_analyzer`, `level_2: clause_extractor`
   - Clear tool permissions per agent level

### Patterns to Skip

1. **Stack-based Hierarchy**
   - Limitation: Linear execution path
   - Legal AI needs: Parallel research streams, async operations
   - Alternative: True task graph with parallel execution

2. **Hardcoded Intervals**
   - 10-step consolidation too rigid
   - Legal AI needs: Adaptive consolidation based on document complexity
   - Better: Token-count or semantic-change triggers

3. **File-based State Storage**
   - JSON files don't scale
   - Legal AI needs: Database for matter management
   - Alternative: PostgreSQL/SQLite with file artifacts

4. **Chinese-centric Prompts**
   - System prompts in Chinese reduce portability
   - Legal AI needs: English-first for legal terminology
   - Requires complete prompt translation

5. **Simplified Error Handling in Sub-agents**
   - Sub-agent failures bubble up as generic errors
   - Legal AI needs: Detailed failure analysis for compliance
   - Requires: Structured error taxonomy

### Integration Approach

**Recommended: Extract patterns, don't fork**

1. **Adopt the Consolidation Pattern**
   ```python
   # Configurable interval based on task type
   CONSOLIDATION_INTERVALS = {
       "document_review": 15,
       "contract_analysis": 8,
       "research_synthesis": 20
   }
   ```

2. **Implement Workspace Pattern**
   ```
   /matters/{matter_id}/
   ├── documents/       # Source documents
   ├── analysis/        # Generated analysis
   ├── correspondence/  # Client comms
   ├── research/        # Legal research
   └── matter.json      # Metadata
   ```

3. **Build on LiteLLM Integration**
   - InfiAgent's `SimpleLLMClient` is a good starting point
   - Add Claude/GPT support via same interface
   - Their retry/timeout handling is reasonable

4. **Skip the Tool Server**
   - HTTP overhead unnecessary for single-process use
   - Implement tools as direct Python functions
   - Use MCP for tool standardization instead

---

## Questions for Further Investigation

1. **Performance at Scale:**
   - How does file-based state perform with 1000+ agent calls?
   - Is there latency from constant JSON read/write?

2. **Model Sensitivity:**
   - Prompts optimized for Claude Sonnet - how do they perform with GPT-4?
   - Do Chinese prompts cause issues with English models?

3. **Consolidation Quality:**
   - How often does the thinking module lose critical information?
   - Is 10-step interval optimal or arbitrary?

4. **Recovery Robustness:**
   - How clean is crash recovery in practice?
   - Are there race conditions in multi-agent scenarios?

5. **Legal Adaptation:**
   - How to handle privileged information boundaries?
   - What modifications needed for matter confidentiality?

---

## Final Recommendation

**Recommendation: Adopt patterns only, do not fork**

**Rationale:**
- GPL-3.0 license creates distribution complications
- Implementation quality is adequate but not exceptional
- Core patterns are straightforward to reimplement
- Chinese-centric codebase requires significant localization

**Valuable takeaways:**
1. Workspace-as-state pattern (simple, effective)
2. Periodic consolidation mechanism (critical for long tasks)
3. Two-track history for audit trails
4. YAML-based agent configuration

**Not worth adopting:**
1. File-based JSON state management
2. Stack-based hierarchy model
3. HTTP tool server architecture
4. Specific prompt engineering (language-dependent)

**Estimated effort to reimplement core patterns:** 2-3 weeks for experienced Python developer

---

## Reference

- **Repository:** https://github.com/ChenglinPoly/infiAgent
- **Paper:** arXiv:2601.03204v1 "InfiAgent: An Infinite-Horizon Framework for General-Purpose Autonomous Agents"
- **Related:** arXiv:2509.22502 (InfiAgent Pyramid, September 2025)
