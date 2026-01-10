# InfiAgent Consolidation Mechanism (Thinking Agent)
# Source: services/thinking_agent.py
# Demonstrates the "thinking module" for state consolidation

class ThinkingAgent:
    """思考Agent - 用于分析任务进展"""

    def __init__(self):
        self.llm_client = SimpleLLMClient()

        # *** THE CRITICAL SYSTEM PROMPT ***
        # This defines the structure of consolidation output
        self.system_prompt = """你是一个agent行动的上下文管理专家，这个 agent 每次在清除动作历史之前会请你进行上下文整理。
        上下文中包括你上次清理的成果在<当前进度思考>标签内。按照下面格式返回整理后的上下文，如果<当前进度思考>标签内没有内容证明是首次进行构造，你的输出不需要包含<当前进度思考>标签。你必须要考虑到十步后，历史动作会被立刻舍弃，因此
        你规划的<next_n_steps>必须足够具体，同时增量工作！

        '''Output Format'''
        <todo_list>
        # Task breakdown with status tracking
        # [done] - Completed tasks
        # [ongoing:notes] - In progress with details
        # [waiting] - Not yet started

        例子：
        1. 使用 XXX 工具总结 X1 文档保存在 document_summary.md:[done]
        2. 使用 XXX 工具总结 X2 文档保存在 document_summary.md:[done]
        3. 使用 XXX 工具总结 X3 文档保存在 document_summary.md:[ongoing：已经知道 X3.pdf的位置为 ./papers/XX3.pdf]
        4. 使用 XXX 工具总结 X4 文档保存在 document_summary.md:[waiting]
        ...
        10. 分析document_summary.md，构造文章大纲保存在 outline.md:[waiting]
        </todo_list>

        <有效文件描述>
        # File paths and descriptions for future use
        # Key for workspace state preservation

        例子：
        ./document_summary.md:[正在进行文档总结的中间结果，全部总计完毕后，通过读取可以用于研究计划的产生]
        user_requirement.md: [作者对实验的结构要求，在第十步时候用于读取使用]
        web_content.md: [网页内容，实验大纲的经验性博客，用于第十步读取，进行参考]
        X5.pdf: [马上要进行分析的文献]
        </有效文件描述>

        <固化信息>
        # *** CRITICAL SECTION ***
        # Information that MUST survive the context clear
        # "下十步任需使用的信息，你应该保留在这里"

        workspace（必须包含！）:
            [dir] code_run
                [file] service.py [实验环境生成服务...]
            [dir] documents
              [file] outline.txt:[上一步的生成的实验大纲]
        rules:
             1.用户要求所有作图，写作必须英文。
             2.目前依据实验大纲进行到第二步。
        content_need_next_steps:
            outline.txt:(部分内容，或者全部内容)
            reference.bib:(样例用于格式对齐)
        </固化信息>

        <next_n_steps>
        # *** CONCRETE 10-STEP PLAN ***
        # Each step is tool-level specific
        # Must be concrete enough to execute without history

        例子：
        1. 使用 answer_from_one_paper工具分析 XX9.pdf，并保存在XX.md文件。
        2. 使用 file_read工具一次性复数读取所有相关文件
        3. dir_list 确保要写入的 md 名称不冲突
        4. file_write 写入xxx.md文件
        5. final_out输出完成情况
        </next_n_steps>
        """

    def analyze_first_thinking(self, task_description: str, agent_system_prompt: str,
                               available_tools: List[str], tools_config: dict = None) -> str:
        """
        Consolidation analysis - called both initially and periodically

        Key insight: Same method used for initial planning AND periodic consolidation
        The agent_system_prompt already contains <历史动作> context
        """
        try:
            tools_info = self._format_tools_info(available_tools, tools_config)

            analysis_request = f"""当前被分析 agent 的提示词
{agent_system_prompt}
agent可以调用的所有工具和参数信息
{tools_info}
按照被分析提示词中<用户最新输入>的语言使用对应语言输出
如果是初始阶段，请你构造新的<当前进度思考>上下文，否则请你更新<当前进度思考>。只需要输出<当前进度思考>内的内容即可！
"""

            history = [ChatMessage(role="user", content=analysis_request)]

            # Call LLM WITHOUT tools - pure text generation
            response = self.llm_client.chat(
                history=history,
                model=self.llm_client.models[0],
                system_prompt=self.system_prompt,
                tool_list=[],  # No tools
                tool_choice="none"  # Explicit no-tool mode
            )

            if response.status == "success":
                return f"[🤖 初始规划]\n\n{response.output}"
            else:
                return f"[初始规划失败: {response.error_information}]"

        except Exception as e:
            return f"[初始规划失败: {str(e)}]"


# How it's called from agent_executor.py:
#
# if self.tool_call_counter % self.thinking_interval == 0:  # Every 10 calls
#     thinking_result = self._trigger_thinking(task_id, user_input, is_first=False)
#     if thinking_result:
#         self.latest_thinking = thinking_result
#         self.hierarchy_manager.update_thinking(self.agent_id, thinking_result)
#         self._save_state(task_id, user_input, turn)
#
#         # *** THE CRITICAL LINE ***
#         self.action_history = []  # Clear after consolidation
