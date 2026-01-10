# InfiAgent Agent Executor - Main Execution Loop
# Source: core/agent_executor.py
# Demonstrates the core execution loop with 10-step consolidation

class AgentExecutor:
    """Agent执行器 - 正确的XML上下文架构"""

    def __init__(self, agent_name, agent_config, config_loader, hierarchy_manager):
        # ... initialization ...

        # Key configuration
        self.max_turns = 10000000  # Essentially unlimited
        self.thinking_interval = 10  # *** THE MAGIC NUMBER ***
        self.tool_call_counter = 0

        # Two separate histories - critical for audit trail
        self.action_history = []      # For rendering (gets compressed/cleared)
        self.action_history_fact = [] # Complete trajectory (never compressed)

    def run(self, task_id: str, user_input: str) -> Dict:
        """执行Agent任务"""

        # Agent入栈
        self.agent_id = self.hierarchy_manager.push_agent(self.agent_name, user_input)

        # 首次thinking（初始规划）
        if start_turn == 0 and not self.first_thinking_done:
            thinking_result = self._trigger_thinking(task_id, user_input, is_first=True)
            if thinking_result:
                self.latest_thinking = thinking_result
                self.first_thinking_done = True
                self.hierarchy_manager.update_thinking(self.agent_id, thinking_result)

        # Main execution loop
        for turn in range(start_turn, self.max_turns):
            try:
                # Save state before each turn
                self._save_state(task_id, user_input, turn)

                # *** COMPRESSION CHECK ***
                # This may compress or clear action_history
                self._compress_action_history_if_needed()

                # Build full system prompt with XML context
                full_system_prompt = self.context_builder.build_context(
                    task_id,
                    self.agent_id,
                    self.agent_name,
                    user_input,
                    action_history=self.action_history
                )

                # Call LLM with forced tool use
                # Note: history is always just ONE message asking for next action
                history = [ChatMessage(role="user", content="<历史动作>是你之前已经执行的动作，不要重复<历史动作>内的动作！！请输出下一个动作")]

                llm_response = self.llm_client.chat(
                    history=history,
                    model=self.model_type,
                    system_prompt=full_system_prompt,
                    tool_list=self.available_tools,
                    tool_choice="required"  # Force tool call
                )

                # Execute all tool calls
                for tool_call in llm_response.tool_calls:
                    tool_result = self.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments,
                        task_id
                    )

                    action_record = {
                        "tool_name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "result": tool_result
                    }

                    # *** TWO HISTORIES ***
                    self.action_history_fact.append(action_record)  # Never cleared
                    self.action_history.append(action_record)        # May be cleared

                    # Increment counter
                    self.tool_call_counter += 1

                    # Check for completion
                    if tool_call.name == "final_output":
                        self.hierarchy_manager.pop_agent(self.agent_id, tool_result.get("output", ""))
                        return tool_result

                # *** THE 10-STEP CONSOLIDATION ***
                if self.tool_call_counter % self.thinking_interval == 0:
                    thinking_result = self._trigger_thinking(task_id, user_input, is_first=False)
                    if thinking_result:
                        self.latest_thinking = thinking_result
                        self.hierarchy_manager.update_thinking(self.agent_id, thinking_result)

                        # *** CRITICAL: CLEAR ACTION HISTORY ***
                        # This is the "bounded context" mechanism
                        self.action_history = []

            except Exception as e:
                # Error handling with thinking state preserved
                error_result = {
                    "status": "error",
                    "output": f"执行过程中出错\n\n目前进度:\n{self.latest_thinking}" if self.latest_thinking else "执行过程中出错"
                }
                self.hierarchy_manager.pop_agent(self.agent_id, str(error_result))
                return error_result

        # Max turns reached
        timeout_result = {
            "status": "error",
            "output": "执行超过最大轮次限制",
            "error_information": f"Max turns {self.max_turns} exceeded"
        }
        return timeout_result
