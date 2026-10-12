#!/usr/bin/env python3
"""
AgnesCode AGI Planning - Plan-and-Execute 全局规划器
Phase 3.2: 先制定完整计划，再顺序执行，支持失败回滚和重规划
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field


@dataclass
class PlanStep:
    """计划中的单个步骤"""
    step_id: int
    description: str          # 步骤描述
    action: str               # 要执行的行动
    expected_outcome: str     # 预期结果
    rollback_action: str = "" # 回滚行动（如果失败）
    success: bool = False
    actual_outcome: str = ""
    error: str = ""


@dataclass
class ExecutionPlan:
    """完整的执行计划"""
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    current_step: int = 0
    success: bool = False
    failed_at: Optional[int] = None
    error_message: str = ""


class PlanAndExecutePlanner:
    """
    Plan-and-Execute 规划器
    
    工作流程：
    1. 分析目标，生成完整计划
    2. 顺序执行每个步骤
    3. 某步失败时，尝试回滚并重试
    4. 多次失败后，触发重规划或升级人工
    """
    
    def __init__(
        self,
        max_retries: Optional[int] = None,
        reflection_engine=None
    ):
        # 从配置加载最大重试次数
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config.settings_loader import get_planning_config
        
        config = get_planning_config()
        self.max_retries = max_retries if max_retries is not None else config.max_retries
        
        self.reflection_engine = reflection_engine
    
    def create_plan(
        self,
        goal: str,
        context: Optional[Dict] = None
    ) -> ExecutionPlan:
        """
        创建执行计划
        
        Args:
            goal: 任务目标
            context: 额外上下文
            
        Returns:
            ExecutionPlan 执行计划
        """
        print(f"\n📋 制定计划")
        print(f"目标: {goal}")
        print("-" * 60)
        
        # 基于目标生成计划步骤
        steps = self._generate_steps(goal, context)
        
        plan = ExecutionPlan(
            goal=goal,
            steps=steps
        )
        
        print(f"✅ 计划已生成，共 {len(steps)} 个步骤")
        for i, step in enumerate(steps, 1):
            print(f"  {i}. {step.description}")
        
        return plan
    
    def execute_plan(
        self,
        plan: ExecutionPlan,
        execute_fn: Callable[[str], Dict],
        context: Optional[Dict] = None
    ) -> ExecutionPlan:
        """
        执行计划
        
        Args:
            plan: 执行计划
            execute_fn: 执行函数
            context: 额外上下文
            
        Returns:
            ExecutionPlan 更新后的计划
        """
        print(f"\n▶️  开始执行计划")
        print("-" * 60)
        
        for i, step in enumerate(plan.steps):
            plan.current_step = i + 1
            
            print(f"\n[步骤 {i+1}/{len(plan.steps)}]")
            print(f"📝 {step.description}")
            print(f"🔧 执行: {step.action}")
            
            # 执行步骤
            success, outcome, error = self._execute_step_with_retry(
                step, execute_fn
            )
            
            step.success = success
            step.actual_outcome = outcome
            step.error = error
            
            if success:
                print(f"✅ 步骤成功")
            else:
                print(f"❌ 步骤失败: {error}")
                plan.failed_at = i + 1
                plan.error_message = error
                
                # 尝试回滚
                if step.rollback_action:
                    print(f"🔄 执行回滚: {step.rollback_action}")
                    try:
                        rollback_result = execute_fn(step.rollback_action)
                        if rollback_result.get("success"):
                            print(f"✅ 回滚成功")
                        else:
                            print(f"⚠️  回滚失败")
                    except (RuntimeError, ConnectionError) as e:
                        print(f"⚠️  回滚异常: {e}")
                
                # 判断是否继续
                if not self._should_continue(plan, i):
                    print(f"\n⛔ 计划中止于步骤 {i+1}")
                    break
        
        # 检查整体成功
        plan.success = all(s.success for s in plan.steps)
        
        if plan.success:
            print(f"\n🎉 计划全部完成！")
        else:
            print(f"\n⚠️  计划未完成，失败于步骤 {plan.failed_at}")
        
        return plan
    
    def _execute_step_with_retry(
        self,
        step: PlanStep,
        execute_fn: Callable[[str], Dict]
    ) -> Tuple[bool, str, str]:
        """
        执行步骤并支持重试
        
        Returns:
            (success, outcome, error)
        """
        last_error = ""
        
        for attempt in range(1, self.max_retries + 2):  # 原始1次 + 重试max_retries次
            try:
                result = execute_fn(step.action)
                outcome = result.get("output", result.get("observation", ""))
                success = result.get("success", False)
                
                if success:
                    return True, outcome, ""
                else:
                    last_error = result.get("error", "未知错误")
                    if attempt <= self.max_retries:
                        print(f"  ⚠️  第{attempt}次尝试失败，准备重试...")
                        time.sleep(0.5)  # 短暂等待
                    
            except (RuntimeError, ConnectionError, TimeoutError) as e:
                last_error = str(e)
                if attempt <= self.max_retries:
                    print(f"  ⚠️  第{attempt}次尝试异常: {e}，准备重试...")
                    time.sleep(0.5)
        
        return False, "", last_error
    
    def _should_continue(self, plan: ExecutionPlan, failed_step_idx: int) -> bool:
        """判断失败后是否应该继续执行后续步骤"""
        # 关键步骤失败则停止
        critical_keywords = ["初始化", "登录", "认证", "连接"]
        failed_step = plan.steps[failed_step_idx]
        
        if any(kw in failed_step.description for kw in critical_keywords):
            print(f"  🔑 关键步骤失败，无法继续")
            return False
        
        # 连续失败超过2步则停止
        consecutive_failures = sum(
            1 for s in plan.steps[:failed_step_idx+1] 
            if not s.success
        )
        if consecutive_failures >= 2:
            print(f"  🛑 已连续失败 {consecutive_failures} 步，停止执行")
            return False
        
        return True
    
    def replan(
        self,
        original_plan: ExecutionPlan,
        failure_info: Dict,
        context: Optional[Dict] = None
    ) -> ExecutionPlan:
        """
        基于失败信息重新规划
        
        Args:
            original_plan: 原计划
            failure_info: 失败信息
            context: 额外上下文
            
        Returns:
            ExecutionPlan 新计划
        """
        print(f"\n🔄 重新规划")
        print(f"原计划失败于步骤: {original_plan.failed_at}")
        print(f"失败原因: {original_plan.error_message}")
        print("-" * 60)
        
        # 保留已成功的步骤
        completed_steps = [s for s in original_plan.steps if s.success]
        failed_step = original_plan.steps[original_plan.failed_at - 1] if original_plan.failed_at else None
        
        # 从失败点之后重新生成步骤
        new_steps = self._generate_replan_steps(
            original_plan.goal,
            failed_step,
            completed_steps,
            failure_info,
            context
        )
        
        # 构建新计划
        new_plan = ExecutionPlan(
            goal=original_plan.goal,
            steps=completed_steps + new_steps
        )
        
        print(f"✅ 新计划已生成，共 {len(new_plan.steps)} 个步骤")
        for i, step in enumerate(new_plan.steps, 1):
            status = "✅" if step.success else f"{i}"
            print(f"  {status}. {step.description}")
        
        return new_plan
    
    def _generate_steps(
        self,
        goal: str,
        context: Optional[Dict]
    ) -> List[PlanStep]:
        """生成计划步骤（启发式实现）"""
        goal_lower = goal.lower()
        steps = []
        step_id = 1
        
        # 场景1：文件操作类任务
        if any(kw in goal_lower for kw in ["文件", "目录", "列出", "搜索"]):
            steps.extend([
                PlanStep(
                    step_id=step_id,
                    description="探索当前工作目录结构",
                    action="ls -la",
                    expected_outcome="获取文件和目录列表",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 1,
                    description="筛选目标相关文件",
                    action="find . -type f -name '*.txt' -o -name '*.py'",
                    expected_outcome="找到相关文件列表",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 2,
                    description="读取并分析文件内容",
                    action="cat <target_file>",
                    expected_outcome="获取文件内容",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 3,
                    description="整理最终结果",
                    action="echo '任务完成，结果已整理'",
                    expected_outcome="输出最终答案",
                    rollback_action=""
                )
            ])
        
        # 场景2：安装配置类任务
        elif any(kw in goal_lower for kw in ["安装", "配置", "设置"]):
            steps.extend([
                PlanStep(
                    step_id=step_id,
                    description="检查当前环境状态",
                    action="which <command> || echo '未安装'",
                    expected_outcome="确认是否已安装",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 1,
                    description="执行安装或配置",
                    action="pip install <package>",
                    expected_outcome="安装成功",
                    rollback_action="pip uninstall <package>"
                ),
                PlanStep(
                    step_id=step_id + 2,
                    description="验证安装结果",
                    action="<command> --version",
                    expected_outcome="显示版本号",
                    rollback_action=""
                )
            ])
        
        # 场景3：通用任务（默认模板）
        else:
            steps.extend([
                PlanStep(
                    step_id=step_id,
                    description="分析任务需求和可用资源",
                    action="echo '开始分析任务'",
                    expected_outcome="明确任务范围",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 1,
                    description="执行核心操作",
                    action=f"echo '执行: {goal}'",
                    expected_outcome="完成任务主体",
                    rollback_action=""
                ),
                PlanStep(
                    step_id=step_id + 2,
                    description="验证结果并输出",
                    action="echo '任务完成'",
                    expected_outcome="输出最终结果",
                    rollback_action=""
                )
            ])
        
        return steps
    
    def _generate_replan_steps(
        self,
        goal: str,
        failed_step: Optional[PlanStep],
        completed_steps: List[PlanStep],
        failure_info: Dict,
        context: Optional[Dict]
    ) -> List[PlanStep]:
        """基于失败信息生成新的步骤"""
        # 简单策略：替换失败的步骤，使用更保守的方法
        if failed_step:
            return [
                PlanStep(
                    step_id=len(completed_steps) + 1,
                    description=f"替代方案：{failed_step.description}（修正版）",
                    action=failed_step.action + " --help" if "--help" not in failed_step.action else failed_step.action,
                    expected_outcome=failed_step.expected_outcome,
                    rollback_action=failed_step.rollback_action
                ),
                PlanStep(
                    step_id=len(completed_steps) + 2,
                    description="继续完成剩余任务",
                    action="echo '继续执行'",
                    expected_outcome="完成任务",
                    rollback_action=""
                )
            ]
        else:
            return self._generate_steps(goal, context)


def test_plan_and_execute():
    """测试 Plan-and-Execute 规划器"""
    print("=" * 60)
    print("Plan-and-Execute Planner 测试")
    print("=" * 60)
    
    planner = PlanAndExecutePlanner(max_retries=2)
    
    # 模拟执行函数
    def mock_execute(action: str) -> Dict:
        """模拟执行函数"""
        print(f"   [执行] {action}")
        
        # 模拟不同命令的结果
        if "ls" in action:
            return {"success": True, "output": "file1.txt\nfile2.txt\ndir1/"}
        elif "find" in action:
            return {"success": True, "output": "./file1.txt\n./file2.txt"}
        elif "cat" in action:
            return {"success": True, "output": "This is file content..."}
        elif "pip install" in action:
            return {"success": False, "error": "Permission denied"}
        else:
            return {"success": True, "output": "执行成功"}
    
    # 测试1：文件操作任务
    print("\n--- 测试 1: 列出并分析文件 ---")
    plan = planner.create_plan("列出当前目录下的所有 Python 文件并统计行数")
    result = planner.execute_plan(plan, mock_execute)
    
    print(f"\n结果:")
    print(f"  成功: {result.success}")
    print(f"  完成步骤: {sum(1 for s in result.steps if s.success)}/{len(result.steps)}")
    if result.failed_at:
        print(f"  失败于步骤: {result.failed_at}")
        print(f"  错误信息: {result.error_message}")
    
    # 测试2：需要重规划的任务
    print("\n--- 测试 2: 安装软件（会失败并重规划） ---")
    plan2 = planner.create_plan("安装一个新的 Python 包")
    result2 = planner.execute_plan(plan2, mock_execute)
    
    if not result2.success:
        print(f"\n🔄 触发重规划...")
        new_plan = planner.replan(
            result2,
            {"reason": "权限不足，需要使用 sudo"},
            context={"use_sudo": True}
        )
        result2_new = planner.execute_plan(new_plan, mock_execute)
        print(f"\n重规划后结果: {'成功' if result2_new.success else '仍失败'}")
    
    print("\n✅ Plan-and-Execute Planner 测试完成")


if __name__ == "__main__":
    test_plan_and_execute()
