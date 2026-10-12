#!/usr/bin/env python3
"""
AgnesCode AGI Reflection 反思器 - 主模块
Phase 2.2-2.4: 自动诊断、执行流程集成、低分重试机制
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, Optional

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from scorer import ReflectionScorer, ReflectionScore
from config.settings_loader import get_reflection_config


class ReflectionEngine:
    """反思引擎：集成评分、诊断、重试全流程"""
    
    def __init__(self, memory_db_path: Optional[str] = None):
        self.scorer = ReflectionScorer()
        
        # 从配置加载最大重试次数
        config = get_reflection_config()
        self.max_retries = config.max_retries
        
        # 初始化 Memory 连接
        if memory_db_path:
            self.memory_db = Path(memory_db_path)
        else:
            self.memory_db = Path.home() / '.agnes' / 'memory' / 'tasks.db'
    
    def reflect_and_act(
        self,
        task: Dict,
        result: Dict,
        execute_fn=None,
        retry_count: int = 0
    ) -> Dict:
        """
        完整的反思-行动循环
        
        Args:
            task: 任务信息
            result: 执行结果
            execute_fn: 重新执行的函数（可选）
            retry_count: 当前重试次数
            
        Returns:
            包含评分和后续行动的字典
        """
        # 1. 评分
        score = self.scorer.evaluate(task, result)
        
        # 2. 记录到 Memory
        self._save_to_memory(task, result, score)
        
        # 3. 判断下一步行动
        action = self._decide_next_action(score, retry_count)
        
        # 4. 如果需要重试且有执行函数
        if action["action"] == "retry" and execute_fn:
            print(f"\n🔄 评分过低 ({score.final_score:.2f})，准备第 {retry_count + 1} 次重试...")
            print(f"诊断: {score.diagnosis}")
            print(f"建议: {', '.join(score.suggestions)}")
            
            # 应用修正建议
            corrected_task = self._apply_corrections(task, score.suggestions)
            
            # 等待一下再重试
            time.sleep(2)
            
            # 重新执行
            new_result = execute_fn(corrected_task)
            
            # 递归反思
            return self.reflect_and_act(
                corrected_task,
                new_result,
                execute_fn,
                retry_count + 1
            )
        
        # 5. 如果需要人工审核
        elif action["action"] == "escalate":
            print(f"\n⚠️  需要人工审核")
            print(f"原因: {action['reason']}")
            print(f"评分: {score.final_score:.2f}")
            print(f"诊断: {score.diagnosis}")
        
        # 6. 返回结果
        return {
            "score": score,
            "action": action,
            "retry_count": retry_count,
            "task": task,
            "result": result
        }
    
    def _decide_next_action(
        self,
        score: ReflectionScore,
        retry_count: int
    ) -> Dict:
        """决定下一步行动"""
        
        # 先检查是否需要人工审核（优先级最高）
        if self.scorer.needs_human_review(score):
            return {
                "action": "escalate",
                "reason": "评分过低或安全性问题，需要人工审核",
                "details": score.diagnosis
            }
        
        # 检查是否应该重试（未达最大次数且评分低）
        if score.final_score < self.scorer.acceptable_threshold and retry_count < self.max_retries:
            return {
                "action": "retry",
                "reason": f"评分过低 ({score.final_score:.2f} < {self.scorer.acceptable_threshold})",
                "retry_count": retry_count + 1
            }
        
        # 重试次数用尽仍未通过，升级
        if score.final_score < self.scorer.acceptable_threshold and retry_count >= self.max_retries:
            return {
                "action": "escalate",
                "reason": f"重试 {self.max_retries} 次后仍未通过 (评分: {score.final_score:.2f})",
                "details": score.diagnosis
            }
        
        # 成功完成
        return {
            "action": "complete",
            "reason": f"评分合格 ({score.final_score:.2f})",
            "quality": "excellent" if score.final_score >= self.scorer.excellent_threshold else "acceptable"
        }
    
    def _apply_corrections(self, task: Dict, suggestions: list) -> Dict:
        """根据建议修正任务参数"""
        corrected = task.copy()
        
        for suggestion in suggestions:
            if "覆盖任务的所有要求" in suggestion:
                corrected["check_completeness"] = True
            elif "验证结果准确性" in suggestion:
                corrected["validate_output"] = True
            elif "优化执行效率" in suggestion:
                corrected["optimize_for_speed"] = True
            elif "避免危险操作" in suggestion:
                corrected["strict_safety_check"] = True
        
        return corrected
    
    def _save_to_memory(
        self,
        task: Dict,
        result: Dict,
        score: ReflectionScore
    ):
        """保存评分结果到 Memory"""
        try:
            import sqlite3
            
            conn = sqlite3.connect(str(self.memory_db))
            cursor = conn.cursor()
            
            # 插入或更新任务经验记录（使用 Phase 1 schema）
            cursor.execute('''
                INSERT OR REPLACE INTO task_experiences 
                (task_id, task_description, success, output, error_message,
                 duration_seconds, quality_score, completeness_score, 
                 accuracy_score, efficiency_score, safety_score, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.get("task_id", "unknown"),
                task.get("description", ""),
                result.get("success", False),
                result.get("output", ""),
                result.get("error", ""),
                result.get("duration_seconds", 0),
                score.final_score,
                score.completeness,
                score.accuracy,
                score.efficiency,
                score.safety,
                ",".join(score.suggestions[:3]) if score.suggestions else ""
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"⚠️  保存到 Memory 失败: {e}")


def create_execute_wrapper(original_fn):
    """
    创建执行函数包装器，自动集成反思器
    
    Usage:
        @create_execute_wrapper
        def my_task_executor(task):
            # 执行逻辑
            return result
    """
    engine = ReflectionEngine()
    
    def wrapper(task: Dict) -> Dict:
        # 执行原始函数
        result = original_fn(task)
        
        # 自动反思
        reflection_result = engine.reflect_and_act(task, result)
        
        # 将评分信息添加到结果中
        result["reflection"] = {
            "score": reflection_result["score"].final_score,
            "diagnosis": reflection_result["score"].diagnosis,
            "action": reflection_result["action"]["action"]
        }
        
        return result
    
    return wrapper


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Reflection Engine 测试")
    print("=" * 60)
    
    engine = ReflectionEngine()
    
    # 测试 1: 高分任务
    print("\n--- 测试 1: 高分任务 ---")
    test_task_1 = {
        "task_id": "test_001",
        "description": "列出目录文件",
        "goal_keywords": ["file"],
        "expected_actions": ["ls"],
        "budget_limit_usd": 0.01
    }
    
    test_result_1 = {
        "success": True,
        "exit_code": 0,
        "stdout": "file1.txt\nfile2.txt",
        "stderr": "",
        "duration_seconds": 2.0,
        "actions_taken": ["ls"],
        "cost_usd": 0.001
    }
    
    result_1 = engine.reflect_and_act(test_task_1, test_result_1)
    print(f"评分: {result_1['score'].final_score:.2f}")
    print(f"行动: {result_1['action']['action']}")
    print(f"诊断: {result_1['score'].diagnosis}")
    
    # 测试 2: 低分任务（触发重试）
    print("\n--- 测试 2: 低分任务 ---")
    test_task_2 = {
        "task_id": "test_002",
        "description": "执行危险命令",
        "goal_keywords": [],
        "expected_actions": [],
        "budget_limit_usd": 0.01
    }
    
    test_result_2 = {
        "success": False,
        "exit_code": 1,
        "stdout": "",
        "stderr": "Error: Permission denied",
        "duration_seconds": 120.0,
        "actions_taken": ["rm -rf /tmp/test"],
        "cost_usd": 0.005
    }
    
    result_2 = engine.reflect_and_act(test_task_2, test_result_2)
    print(f"评分: {result_2['score'].final_score:.2f}")
    print(f"行动: {result_2['action']['action']}")
    print(f"诊断: {result_2['score'].diagnosis}")
    print(f"建议: {', '.join(result_2['score'].suggestions)}")
    
    print("\n✅ Reflection Engine 测试完成")
