# InfiAgent Hierarchy Manager - Core Logic
# Source: core/hierarchy_manager.py
# Demonstrates stack-based agent hierarchy management

class HierarchyManager:
    """Agent层级管理器"""

    def __init__(self, task_id: str):
        """
        初始化层级管理器

        Args:
            task_id: 任务ID
        """
        self.task_id = task_id
        self.lock = threading.Lock()

        # 文件路径 - 使用用户主目录（跨平台）
        conversations_dir = Path.home() / "mla_v3" / "conversations"
        conversations_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名：hash + 最后文件夹名
        task_hash = hashlib.md5(task_id.encode()).hexdigest()[:8]
        task_folder = Path(task_id).name if (os.sep in task_id or '/' in task_id or '\\' in task_id) else task_id
        task_name = f"{task_hash}_{task_folder}"

        self.stack_file = conversations_dir / f'{task_name}_stack.json'
        self.context_file = conversations_dir / f'{task_name}_share_context.json'

        self._initialize_files()

    def push_agent(self, agent_name: str, user_input: str) -> str:
        """
        Agent入栈操作

        Key insight: Uses stack-based model, not true DAG
        Parent is always current stack top
        """
        with self.lock:
            # 生成agent_id
            content_for_hash = f"{agent_name}|{self.task_id}|{user_input}"
            hash_object = hashlib.md5(content_for_hash.encode())
            agent_hash = hash_object.hexdigest()[:12]
            agent_id = f"{agent_name}_{agent_hash}"

            # 加载当前状态
            stack = self._load_stack()
            context = self._load_context()

            # 获取父Agent（栈顶）
            parent_id = None
            level = 0
            if stack:
                parent_id = stack[-1]["agent_id"]
                level = stack[-1]["level"] + 1

            # 创建Agent栈条目
            agent_entry = {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "parent_id": parent_id,
                "level": level,
                "user_input": user_input,
                "start_time": datetime.now().isoformat()
            }

            # 入栈
            stack.append(agent_entry)
            self._save_stack(stack)

            # 更新共享上下文
            if agent_id not in context["current"]["hierarchy"]:
                context["current"]["hierarchy"][agent_id] = {
                    "parent": parent_id,
                    "children": [],
                    "level": level
                }

            # 如果有父Agent，将当前Agent添加到父Agent的children列表
            if parent_id and parent_id in context["current"]["hierarchy"]:
                if agent_id not in context["current"]["hierarchy"][parent_id]["children"]:
                    context["current"]["hierarchy"][parent_id]["children"].append(agent_id)

            # 更新Agent状态
            context["current"]["agents_status"][agent_id] = {
                "agent_name": agent_name,
                "status": "running",
                "initial_input": user_input,
                "start_time": datetime.now().isoformat(),
                "parent_id": parent_id,
                "level": level,
                "latest_thinking": ""  # 只保留最新的thinking
            }

            self._save_context(context)
            return agent_id

    def pop_agent(self, agent_id: str, final_output: str = ""):
        """
        Agent出栈操作

        Key insight: Completion triggers hierarchy update
        When all agents complete, current moves to history
        """
        with self.lock:
            stack = self._load_stack()

            # 从栈中移除
            new_stack = [entry for entry in stack if entry["agent_id"] != agent_id]
            self._save_stack(new_stack)

            # 更新共享上下文中的Agent状态
            context = self._load_context()
            if agent_id in context["current"]["agents_status"]:
                context["current"]["agents_status"][agent_id]["status"] = "completed"
                context["current"]["agents_status"][agent_id]["final_output"] = final_output

            self._save_context(context)

            # 检查是否所有Agent都完成
            self._check_and_complete_if_all_done()

    def update_thinking(self, agent_id: str, thinking: str):
        """
        更新Agent的thinking（只保留最新的）

        Key insight: This is the consolidation state that persists
        """
        with self.lock:
            context = self._load_context()

            if agent_id in context["current"]["agents_status"]:
                context["current"]["agents_status"][agent_id]["latest_thinking"] = thinking
                context["current"]["agents_status"][agent_id]["thinking_updated_at"] = datetime.now().isoformat()
                self._save_context(context)
