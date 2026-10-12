#!/usr/bin/env python3
"""
AgnesCode AGI Planning - 反思器集成层
Phase 3.3: 将 Reflection 引擎集成到 ReAct 和 Plan-and-Execute 流程中
"""

import sys
import json
from pathlib import Path
from typing import Dict, Optional, Callable
from dataclasses import dataclass

# 添加路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from scorer import ReflectionScorer, ReflectionScore
from reflector import ReflectionEngine
from config.settings_loader import get_planning_config


@dataclass
class PlanningResult:
    """规划执行结果（带反思评分）"""
    success: bool
    output: str
    score: Optional[ReflectionScore] = None
    needs_retry: bool = False
    needs_human_review: bool = False
    diagnosis: str = ""
    suggestions: list = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class ReflectionIntegratedPlanner:
    """
    集成反思器的规划器
    
    在每次执行后自动进行质量评估，根据评分决定：
    - ≥0.8: 优秀，直接完成
    - 0.6-0.8: 可接受，给出改进建议
    - <0.6: 需要重试
    - 安全性违规或多次重试失败: 升级人工审核
    """
    
    def __init__(
        self,
        reflection_engine: Optional[ReflectionEngine] = None,
        auto_retry: bool = True,
        max_retries: Optional[int] = None
    ):
        self.reflection_engine = reflection_engine or ReflectionEngine()
        self.auto_retry = auto_retry
        
        # 从配置加载最大重试次数
        config = get_planning_config()
        self.max_retries = max_retries if max_retries is not None else config.max_retries
        
        self.retry_count = 0
    
    def execute_with_reflection(
        self,
        task: Dict,
        execute_fn: Callable[[Dict], Dict],
        context: Optional[Dict] = None
    ) -> PlanningResult:
        """
        执行任务并自动进行反思评分
        
        Args:
            task: 任务信息，包含 description 等字段
            execute_fn: 执行函数，接收 task，返回结果字典
            context: 额外上下文
            
        Returns:
            PlanningResult 带评分的执行结果
        """
        print(f"\n🎯 开始执行任务（带反思评估）")
        print(f"任务: {task.get('description', 'N/A')}")
        print("-" * 60)
        
        last_result = None
        last_score = None
        
        while self.retry_count <= self.max_retries:
            # 执行任务
            if self.retry_count > 0:
                print(f"\n🔄 第 {self.retry_count} 次重试...")
            
            result_data = execute_fn(task)
            last_result = result_data
            
            # 反思评分
            print(f"\n📊 进行质量评估...")
            score = self.reflection_engine.scorer.evaluate(task, result_data)
            last_score = score
            
            print(f"  综合评分: {score.final_score:.2f}")
            print(f"  完整性: {score.completeness:.2f}")
            print(f"  准确性: {score.accuracy:.2f}")
            print(f"  效率: {score.efficiency:.2f}")
            print(f"  安全性: {score.safety:.2f}")
            
            if score.diagnosis:
                print(f"  诊断: {score.diagnosis}")
            
            # 判断下一步行动
            decision = self.reflection_engine._decide_next_action(score, self.retry_count)
            
            if decision["action"] == "complete":
                print(f"\n✅ 任务通过质量检查")
                return PlanningResult(
                    success=True,
                    output=result_data.get("output", ""),
                    score=score,
                    diagnosis=score.diagnosis,
                    suggestions=score.suggestions
                )
            
            elif decision["action"] == "retry":
                self.retry_count += 1
                print(f"\n⚠️  评分未达标 ({score.final_score:.2f} < 0.6)，准备重试")
                if score.suggestions:
                    print(f"  改进建议:")
                    for i, sug in enumerate(score.suggestions[:3], 1):
                        print(f"    {i}. {sug}")
                
                # 根据建议调整任务
                task = self._adjust_task_based_on_suggestions(task, score.suggestions)
            
            elif decision["action"] == "escalate":
                print(f"\n🚨 需要人工审核")
                print(f"  原因: {decision.get('reason', '未知')}")
                return PlanningResult(
                    success=False,
                    output=result_data.get("output", ""),
                    score=score,
                    needs_human_review=True,
                    diagnosis=decision.get('reason', ''),
                    suggestions=score.suggestions
                )
        
        # 重试次数用尽
        print(f"\n❌ 重试 {self.max_retries} 次后仍未通过")
        return PlanningResult(
            success=False,
            output=last_result.get("output", "") if last_result else "",
            score=last_score,
            needs_retry=True,
            diagnosis=f"重试 {self.max_retries} 次后评分仍低于阈值",
            suggestions=last_score.suggestions if last_score else []
        )
    
    def _adjust_task_based_on_suggestions(
        self,
        task: Dict,
        suggestions: list
    ) -> Dict:
        """基于改进建议调整任务参数"""
        adjusted_task = task.copy()
        
        # 简单策略：将建议添加到任务描述中
        if suggestions and isinstance(suggestions, list):
            original_desc = adjusted_task.get("description", "")
            adjusted_task["description"] = (
                f"{original_desc}\n\n"
                f"改进要求:\n" + 
                "\n".join(f"- {s}" for s in suggestions[:3])
            )
        
        return adjusted_task


def test_reflection_integration():
    """测试反思器集成"""
    print("=" * 60)
    print("反思器集成测试")
    print("=" * 60)
    
    # 创建集成规划器
    planner = ReflectionIntegratedPlanner(
        auto_retry=True,
        max_retries=2
    )
    
    # 模拟执行函数（第一次低分，第二次高分）
    call_count = [0]
    
    def mock_execute(task: Dict) -> Dict:
        call_count[0] += 1
        
        print(f"   [执行] 任务调用 #{call_count[0]}")
        
        # 第一次调用：模拟低质量结果
        if call_count[0] == 1:
            return {
                "success": True,
                "output": "部分结果，不完整",
                "exit_code": 0,
                "duration_seconds": 45,  # 较慢
                "stderr": "警告: 某些操作未完成"
            }
        # 第二次及之后：模拟高质量结果
        else:
            return {
                "success": True,
                "output": "完整且准确的结果，包含所有必要信息",
                "exit_code": 0,
                "duration_seconds": 3,  # 快速
                "stderr": ""
            }
    
    # 测试任务
    task = {
        "description": "统计当前目录下的 Python 文件数量",
        "type": "file_analysis"
    }
    
    # 执行带反思的任务
    result = planner.execute_with_reflection(task, mock_execute)
    
    print(f"\n最终结果:")
    print(f"  成功: {result.success}")
    print(f"  输出: {result.output[:50]}...")
    print(f"  评分: {result.score.final_score if result.score else 'N/A':.2f}")
    print(f"  需要重试: {result.needs_retry}")
    print(f"  需要人工审核: {result.needs_human_review}")
    print(f"  诊断: {result.diagnosis}")
    
    if result.suggestions:
        print(f"  改进建议:")
        for i, sug in enumerate(result.suggestions[:3], 1):
            print(f"    {i}. {sug}")
    
    print("\n✅ 反思器集成测试完成")


if __name__ == "__main__":
    test_reflection_integration()
