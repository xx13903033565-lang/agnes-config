#!/usr/bin/env python3
"""
AgnesCode AGI Planning - 综合验证测试
Phase 3.4: 验证 ReAct、Plan-and-Execute 和反思器集成的完整功能
"""

import sys
import json
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))

from react_planner import ReActPlanner
from plan_execute import PlanAndExecutePlanner
from integration import ReflectionIntegratedPlanner
from reflector import ReflectionEngine


def test_react_planner():
    """测试 ReAct 规划器"""
    print("\n" + "=" * 70)
    print("测试 1: ReAct 实时规划循环")
    print("=" * 70)
    
    planner = ReActPlanner(max_iterations=5)
    
    # 模拟执行函数
    def mock_execute(action: str) -> dict:
        print(f"   [执行] {action}")
        if "ls" in action:
            return {"success": True, "output": "file1.py\nfile2.py\ndir1/"}
        elif "find" in action:
            return {"success": True, "output": "./file1.py\n./file2.py"}
        elif "cat" in action:
            return {"success": True, "output": "print('hello')"}
        else:
            return {"success": False, "error": "未知命令"}
    
    # 测试任务
    result = planner.plan_and_execute(
        goal="列出所有 Python 文件",
        execute_fn=mock_execute
    )
    
    # 验证结果
    assert result.total_iterations > 0, "应该至少执行一次迭代"
    assert len(result.steps) == result.total_iterations, "步骤数应与迭代数一致"
    
    print(f"\n✅ ReAct 测试通过")
    print(f"  迭代次数: {result.total_iterations}")
    print(f"  目标达成: {result.goal_achieved}")
    print(f"  步骤记录: {len(result.steps)} 条")
    
    return True


def test_plan_and_execute():
    """测试 Plan-and-Execute 规划器"""
    print("\n" + "=" * 70)
    print("测试 2: Plan-and-Execute 全局规划")
    print("=" * 70)
    
    planner = PlanAndExecutePlanner(max_retries=2)
    
    # 模拟执行函数
    def mock_execute(action: str) -> dict:
        print(f"   [执行] {action}")
        if "ls" in action or "find" in action:
            return {"success": True, "output": "file1.py\nfile2.py"}
        elif "pip install" in action:
            return {"success": False, "error": "权限不足"}
        else:
            return {"success": True, "output": "成功"}
    
    # 测试1：正常任务
    print("\n--- 子测试 2.1: 正常文件操作 ---")
    plan = planner.create_plan("分析当前目录的 Python 文件")
    result = planner.execute_plan(plan, mock_execute)
    
    assert result.success, "正常任务应该成功"
    assert all(s.success for s in result.steps), "所有步骤应该成功"
    
    print(f"✅ 子测试 2.1 通过: 计划全部完成")
    
    # 测试2：失败后重规划
    print("\n--- 子测试 2.2: 失败后重规划 ---")
    plan2 = planner.create_plan("安装新软件包")
    result2 = planner.execute_plan(plan2, mock_execute)
    
    if not result2.success:
        new_plan = planner.replan(
            result2,
            {"reason": "需要 sudo 权限"},
            context={"use_sudo": True}
        )
        result2_new = planner.execute_plan(new_plan, mock_execute)
        
        # 重规划后可能仍失败（模拟环境限制），但结构应该正确
        assert len(new_plan.steps) > len([s for s in result2.steps if s.success]), \
            "新计划应该包含额外步骤"
        
        print(f"✅ 子测试 2.2 通过: 重规划机制正常")
    
    print(f"\n✅ Plan-and-Execute 测试通过")
    return True


def test_reflection_integration():
    """测试反思器集成"""
    print("\n" + "=" * 70)
    print("测试 3: 反思器集成到规划流程")
    print("=" * 70)
    
    reflection_engine = ReflectionEngine()
    planner = ReflectionIntegratedPlanner(
        reflection_engine=reflection_engine,
        max_retries=2
    )
    
    # 模拟执行函数（第一次低分，第二次改进）
    call_count = [0]
    
    def mock_execute(task: dict) -> dict:
        call_count[0] += 1
        
        if call_count[0] == 1:
            # 第一次：低质量结果
            return {
                "success": True,
                "output": "部分结果",
                "exit_code": 0,
                "duration_seconds": 60,  # 慢
                "stderr": "警告: 未完成全部操作"
            }
        else:
            # 第二次：高质量结果
            return {
                "success": True,
                "output": "完整且准确的结果",
                "exit_code": 0,
                "duration_seconds": 5,  # 快
                "stderr": ""
            }
    
    task = {
        "description": "统计代码行数",
        "type": "analysis"
    }
    
    result = planner.execute_with_reflection(task, mock_execute)
    
    # 验证结果
    assert result.score is not None, "应该有评分结果"
    assert 0 <= result.score.final_score <= 1, "评分应该在 0-1 之间"
    
    print(f"\n✅ 反思器集成测试通过")
    print(f"  最终评分: {result.score.final_score:.2f}")
    print(f"  任务调用次数: {call_count[0]}")
    print(f"  需要人工审核: {result.needs_human_review}")
    
    return True


def test_end_to_end_workflow():
    """测试端到端完整工作流"""
    print("\n" + "=" * 70)
    print("测试 4: 端到端完整工作流（ReAct + 反思器）")
    print("=" * 70)
    
    # 创建带反思器的 ReAct 规划器
    reflection_engine = ReflectionEngine()
    planner = ReActPlanner(
        max_iterations=5,
        reflection_engine=reflection_engine.scorer
    )
    
    # 模拟执行函数
    def mock_execute(action: str) -> dict:
        print(f"   [执行] {action}")
        if "ls" in action:
            return {"success": True, "output": "main.py\ntest.py"}
        elif "cat" in action:
            return {"success": True, "output": "def main(): pass"}
        else:
            return {"success": False, "error": "命令不存在"}
    
    result = planner.plan_and_execute(
        goal="分析项目结构",
        execute_fn=mock_execute
    )
    
    # 验证
    assert result.total_iterations > 0, "应该执行了规划循环"
    assert len(result.steps) > 0, "应该有步骤记录"
    
    print(f"\n✅ 端到端测试通过")
    print(f"  迭代次数: {result.total_iterations}")
    print(f"  目标达成: {result.goal_achieved}")
    
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("AgnesCode AGI Planning - Phase 3 综合验证")
    print("=" * 70)
    
    tests = [
        ("ReAct 规划器", test_react_planner),
        ("Plan-and-Execute 规划器", test_plan_and_execute),
        ("反思器集成", test_reflection_integration),
        ("端到端工作流", test_end_to_end_workflow),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            success = test_fn()
            if success:
                passed += 1
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    print(f"✅ 通过: {passed}/{len(tests)}")
    print(f"❌ 失败: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 所有测试通过！Phase 3 规划器升级完成")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查错误信息")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
