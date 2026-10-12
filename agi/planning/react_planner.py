#!/usr/bin/env python3
"""
AgnesCode AGI Planning 规划器 - ReAct 实时规划循环
Phase 3.1: Thought-Action-Observation 循环
"""

import sys
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class ReActStep:
    """ReAct 单步记录"""
    iteration: int
    thought: str        # 思考：下一步该做什么
    action: str         # 行动：具体执行什么
    observation: str    # 观察：执行结果如何
    success: bool       # 是否成功


@dataclass
class ReActResult:
    """ReAct 执行结果"""
    steps: List[ReActStep] = field(default_factory=list)
    final_answer: str = ""
    success: bool = False
    total_iterations: int = 0
    goal_achieved: bool = False


class ReActPlanner:
    """
    ReAct 实时规划器
    
    工作流程:
    1. Thought: 基于当前状态思考下一步
    2. Action: 执行具体行动
    3. Observation: 观察执行结果
    4. 重复直到目标达成或达到最大迭代次数
    """
    
    def __init__(
        self,
        max_iterations: Optional[int] = None,
        reflection_engine=None
    ):
        # 从配置加载最大迭代次数
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config.settings_loader import get_planning_config
        
        config = get_planning_config()
        self.max_iterations = max_iterations if max_iterations is not None else config.react_max_iterations
        
        self.reflection_engine = reflection_engine  # 可选的反思器集成
    
    def plan_and_execute(
        self,
        goal: str,
        execute_fn: Callable[[str], Dict],
        context: Optional[Dict] = None
    ) -> ReActResult:
        """
        执行 ReAct 循环
        
        Args:
            goal: 任务目标描述
            execute_fn: 执行函数，接收 action 字符串，返回结果字典
            context: 额外上下文信息
            
        Returns:
            ReActResult 执行结果
        """
        result = ReActResult()
        history = []
        
        print(f"\n🎯 ReAct 规划开始")
        print(f"目标: {goal}")
        print(f"最大迭代次数: {self.max_iterations}")
        print("-" * 60)
        
        for iteration in range(1, self.max_iterations + 1):
            # Step 1: Thought - 思考下一步
            thought = self._generate_thought(goal, history, context)
            
            # Step 2: Action - 决定行动
            action = self._decide_action(thought, goal, history)
            
            print(f"\n[迭代 {iteration}]")
            print(f"💭 思考: {thought}")
            print(f"🔧 行动: {action}")
            
            # 检查是否是最终答案
            if self._is_final_answer(action):
                result.final_answer = self._extract_answer(action)
                result.success = True
                result.goal_achieved = True
                result.total_iterations = iteration
                print(f"✅ 达成目标: {result.final_answer}")
                break
            
            # Step 3: Execute - 执行行动
            try:
                observation_data = execute_fn(action)
                observation = self._format_observation(observation_data)
                success = observation_data.get("success", False)
            except (RuntimeError, ConnectionError, TimeoutError) as e:
                observation = f"执行失败: {str(e)}"
                observation_data = {"success": False, "error": str(e)}
                success = False
            
            print(f"👁️  观察: {observation[:100]}...")
            
            # Step 4: Reflection (可选) - 反思评分
            if self.reflection_engine:
                score = self._reflect_on_step(
                    {"description": action},
                    observation_data
                )
                print(f"📊 评分: {score:.2f}")
                
                # 如果评分过低，调整策略
                if score < 0.6:
                    print(f"⚠️  评分过低，调整策略")
            
            # 记录步骤
            step = ReActStep(
                iteration=iteration,
                thought=thought,
                action=action,
                observation=observation,
                success=success
            )
            result.steps.append(step)
            history.append({
                "thought": thought,
                "action": action,
                "observation": observation,
                "success": success
            })
            
            # 检查是否达成目标
            if self._check_goal_achieved(goal, observation, history):
                result.final_answer = observation
                result.success = True
                result.goal_achieved = True
                result.total_iterations = iteration
                print(f"\n✅ 目标达成！")
                break
            
            # 如果连续失败，提前退出
            if not success and iteration >= 3:
                recent_failures = sum(1 for h in history[-3:] if not h["success"])
                if recent_failures >= 3:
                    print(f"\n❌ 连续失败 3 次，停止重试")
                    break
        
        if not result.goal_achieved:
            result.total_iterations = len(result.steps)
            print(f"\n⚠️  未达到目标，已执行 {result.total_iterations} 次迭代")
        
        return result
    
    def _generate_thought(
        self,
        goal: str,
        history: List[Dict],
        context: Optional[Dict]
    ) -> str:
        """
        生成思考（基于当前状态和历史）
        
        注：实际使用时应接入 LLM 或由人类提供思考指导
        当前实现为启发式规则，用于演示 ReAct 循环结构
        """
        if not history:
            # 第一步：分析目标，拆解关键要素
            keywords = self._extract_keywords(goal)
            return f"目标涉及关键词: {', '.join(keywords)}。需要先探索可用资源和方法"
        
        last_step = history[-1]
        
        # 检查是否在行动循环中（至少需要3步历史）
        if len(history) >= 3:
            recent_actions = [h["action"] for h in history[-3:]]
            if len(set(recent_actions)) == 1:
                return f"⚠️ 检测到行动循环（连续3次执行相同行动: {recent_actions[0]}），必须改变策略"
        
        if last_step["success"]:
            # 成功：基于观察结果决定下一步
            obs = last_step["observation"]
            
            # 如果已经获取了足够信息
            if len(history) >= 3 and all(h["success"] for h in history[-2:]):
                return f"已收集多步信息，现在需要整合答案并完成任务"
            
            if "file" in obs.lower() or "目录" in obs:
                return f"已获取文件列表，接下来需要筛选出与目标相关的文件"
            elif "content" in obs.lower():
                return f"已读取内容，需要分析是否满足目标要求"
            else:
                return f"上一步成功获得信息，需要整合到最终答案中"
        else:
            # 失败：分析失败原因并调整策略
            error_msg = last_step["observation"][:80]
            if "not found" in error_msg.lower() or "不存在" in error_msg:
                return f"路径或文件不存在，需要尝试其他路径或创建新文件"
            elif "permission" in error_msg.lower():
                return f"权限不足，需要使用 sudo 或更换操作路径"
            else:
                return f"上一步失败 ({error_msg}...)，需要换一种方法或检查命令语法"
    
    def _decide_action(
        self,
        thought: str,
        goal: str,
        history: List[Dict]
    ) -> str:
        """
        决定下一步行动
        
        注：实际使用时应接入 LLM 生成具体行动
        当前实现为启发式规则，用于演示 ReAct 循环结构
        """
        # 提取目标关键词
        goal_lower = goal.lower()
        
        if not history:
            # 第一步：根据目标类型选择探索策略
            return self._suggest_first_action(goal)
        
        last_step = history[-1]
        failed_actions = [h["action"] for h in history if not h["success"]]
        
        if failed_actions and len(failed_actions) >= 2:
            # 多次失败：尝试完全不同的方法
            return self._suggest_drastic_alternative(goal, failed_actions)
        
        if failed_actions:
            # 单次失败：调整参数或换命令
            return self._suggest_alternative_action(goal, failed_actions[-1])
        
        # 成功：基于上一步观察结果推进
        return self._suggest_next_action(goal, history, last_step["observation"])
    
    def _suggest_first_action(self, goal: str) -> str:
        """建议第一步行动"""
        goal_lower = goal.lower()
        
        if "文件" in goal_lower or "目录" in goal_lower or "列出" in goal_lower:
            return "ls -la"
        elif "搜索" in goal_lower or "查找" in goal_lower:
            if "内容" in goal_lower or "包含" in goal_lower:
                return "grep -r '关键词' ."
            else:
                return "find . -name '*'"
        elif "统计" in goal_lower or "计数" in goal_lower:
            return "wc -l *"
        elif "安装" in goal_lower:
            return "pip install <package>"
        elif "读取" in goal_lower or "查看" in goal_lower:
            return "cat <filename>"
        else:
            return f"echo '开始执行: {goal}'"
    
    def _suggest_alternative_action(
        self,
        goal: str,
        failed_action: str
    ) -> str:
        """建议替代行动（避免重复失败）"""
        # 简单策略：修改命令或添加参数
        if "ls" in failed_action:
            return "find . -maxdepth 1 -type f"
        elif "find" in failed_action:
            return "ls -R"
        elif "cat" in failed_action:
            return "head -n 20 <filename>"
        elif "grep" in failed_action:
            return "rg '关键词' ."  # ripgrep 更快
        elif "--help" in failed_action:
            return "man <command>"  # 查看手册
        else:
            # 移除可能的错误参数
            base_cmd = failed_action.split()[0] if failed_action else "echo"
            return f"{base_cmd} --version"
    
    def _suggest_drastic_alternative(
        self,
        goal: str,
        failed_actions: List[str]
    ) -> str:
        """多次失败后的激进替代方案"""
        # 完全换一种思路
        if "文件" in goal.lower():
            return "python3 -c \"import os; print(os.listdir('.'))\""
        elif "搜索" in goal.lower():
            return "python3 -c \"import glob; print(glob.glob('*'))\""
        else:
            return "echo '需要人工介入或更换工具'"
    
    def _suggest_next_action(
        self,
        goal: str,
        history: List[Dict],
        observation: str
    ) -> str:
        """基于上一步观察结果建议下一步"""
        obs_lower = observation.lower()
        
        # 检查最近是否在行动循环（至少需要3步历史）
        if len(history) >= 3:
            recent_actions = [h["action"] for h in history[-3:]]
            if len(set(recent_actions)) == 1 and recent_actions[0] == "cat <first_file>":
                return "echo '已读取多个文件，现在整合答案'"
        
        # 如果观察到文件列表
        if "file" in obs_lower or ".txt" in obs_lower or ".py" in obs_lower:
            # 提取第一个文件名
            import re
            files = re.findall(r'[\w.-]+\.(?:txt|py|md|json|yaml)', observation)
            if files:
                return f"cat {files[0]}"
            return "cat <first_file>"
        
        # 如果观察到目录
        if "dir" in obs_lower or "/" in observation:
            dirs = re.findall(r'[\w./-]+/', observation)
            if dirs:
                return f"ls -la {dirs[0]}"
            return "ls -la <subdir>"
        
        # 如果已经读取了内容
        if "content" in obs_lower or len(observation) > 100:
            return "echo '分析完成，整理最终答案'"
        
        # 默认：继续深入探索
        last_action = history[-1]["action"]
        if "ls" in last_action:
            return "find . -maxdepth 2 -type f"
        elif "find" in last_action:
            return "grep -r '.' . 2>/dev/null | head -20"
        else:
            return "echo '继续处理...'"
    
    def _is_final_answer(self, action: str) -> bool:
        """检查是否是最终答案"""
        return action.startswith("FinalAnswer:") or action.startswith("答案:")
    
    def _extract_answer(self, action: str) -> str:
        """提取最终答案"""
        if action.startswith("FinalAnswer:"):
            return action[len("FinalAnswer:"):].strip()
        elif action.startswith("答案:"):
            return action[len("答案:"):].strip()
        return action
    
    def _format_observation(self, data: Dict) -> str:
        """格式化观察结果"""
        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")
        
        if stdout:
            return stdout.strip()[:200]
        elif stderr:
            return f"错误: {stderr.strip()[:200]}"
        else:
            return "无输出"
    
    def _check_goal_achieved(
        self,
        goal: str,
        observation: str,
        history: List[Dict]
    ) -> bool:
        """
        检查目标是否达成
        
        注：实际使用时应接入 LLM 判断目标完成度
        当前实现为启发式规则
        """
        goal_lower = goal.lower()
        
        # 特殊场景1：列出文件
        if any(kw in goal_lower for kw in ["列出", "目录", "文件"]):
            if "搜索" not in goal_lower and "查找" not in goal_lower and "包含" not in goal_lower:
                # 纯列出任务，不涉及搜索
                if observation and len(observation) > 10:
                    lines = [l.strip() for l in observation.split('\n') if l.strip()]
                    has_extensions = any('.' in line for line in lines[:5])
                    if len(lines) >= 2 and (has_extensions or '/' in observation):
                        return True
        
        # 特殊场景2：搜索包含特定内容的文件
        if ("搜索" in goal_lower or "查找" in goal_lower) and "包含" in goal_lower:
            # 需要检查文件内容，不能只看文件列表
            if "python" in goal_lower:
                # 观察中应该包含 python 相关内容
                if "python" in observation.lower() or ".py" in observation:
                    # 还需要确认是内容匹配，不只是文件名
                    if "grep" in str(history) or "content" in observation.lower():
                        return True
        
        # 通用匹配：观察中包含目标关键词
        goal_keywords = self._extract_keywords(goal)
        obs_lower = observation.lower()
        
        matched = sum(1 for kw in goal_keywords if kw in obs_lower)
        
        # 如果匹配超过 50% 的关键词，认为目标达成
        return matched >= max(2, len(goal_keywords) * 0.6)
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单分词：按空格和常见标点分割
        import re
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text)
        # 过滤停用词
        stopwords = {"的", "是", "在", "了", "和", "与", "或", "the", "is", "in", "to"}
        return [w for w in words if w not in stopwords and len(w) > 1]
    
    def _reflect_on_step(self, task: Dict, result: Dict) -> float:
        """对单步进行反思评分（如果集成了反思器）"""
        if not self.reflection_engine:
            return 1.0  # 无反思器时默认满分
        
        try:
            score = self.reflection_engine.scorer.evaluate(task, result)
            return score.final_score
        except (AttributeError, TypeError):
            return 0.5  # 出错时给中等分数


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("ReAct Planner 测试")
    print("=" * 60)
    
    planner = ReActPlanner(max_iterations=5)
    
    # 模拟执行函数
    def mock_execute(action: str) -> Dict:
        print(f"   [执行] {action}")
        
        if "ls" in action:
            return {
                "success": True,
                "stdout": "file1.txt\nfile2.txt\ndir1/",
                "stderr": ""
            }
        elif "cat" in action:
            return {
                "success": True,
                "stdout": "This is file content",
                "stderr": ""
            }
        else:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Unknown command"
            }
    
    # 测试 1: 简单任务
    print("\n--- 测试 1: 列出目录文件 ---")
    result = planner.plan_and_execute(
        goal="列出当前目录下的所有文件",
        execute_fn=mock_execute
    )
    
    print(f"\n结果:")
    print(f"  成功: {result.success}")
    print(f"  迭代次数: {result.total_iterations}")
    print(f"  目标达成: {result.goal_achieved}")
    print(f"  最终答案: {result.final_answer[:50] if result.final_answer else 'N/A'}")
    
    # 测试 2: 复杂任务
    print("\n--- 测试 2: 查找特定文件 ---")
    result2 = planner.plan_and_execute(
        goal="查找包含 Python 的文件",
        execute_fn=mock_execute
    )
    
    print(f"\n结果:")
    print(f"  成功: {result2.success}")
    print(f"  迭代次数: {result2.total_iterations}")
    
    print("\n✅ ReAct Planner 测试完成")
