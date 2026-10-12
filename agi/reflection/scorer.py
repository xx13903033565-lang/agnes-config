#!/usr/bin/env python3
"""
AgnesCode AGI Reflection 反思器 - 质量评分模块
Phase 2.1: 设计质量评分模型（LLM + 规则混合）
"""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import sys
from pathlib import Path

# 添加配置模块到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings_loader import get_reflection_config


@dataclass
class ReflectionScore:
    """反思评分结果"""
    completeness: float  # 完整性 (0-1)
    accuracy: float      # 准确性 (0-1)
    efficiency: float    # 效率 (0-1)
    safety: float        # 安全性 (0-1)
    final_score: float   # 综合评分 (0-1)
    rule_pass_rate: float  # 规则通过率 (0-1)
    llm_score: float     # LLM 评分 (0-1)
    diagnosis: str       # 诊断说明
    suggestions: List[str]  # 改进建议


class RuleChecker:
    """规则引擎检查器"""
    
    def __init__(self):
        self.rules = [
            {
                "name": "goal_achieved",
                "description": "是否达成用户明确目标",
                "check_fn": self._check_goal_achieved
            },
            {
                "name": "no_unexpected_side_effects",
                "description": "是否产生预期外的副作用",
                "check_fn": self._check_side_effects
            },
            {
                "name": "within_budget",
                "description": "是否在预算范围内",
                "check_fn": self._check_budget
            },
            {
                "name": "no_unhandled_errors",
                "description": "是否有未处理的错误",
                "check_fn": self._check_errors
            },
            {
                "name": "output_format_correct",
                "description": "输出格式是否正确",
                "check_fn": self._check_output_format
            }
        ]
    
    def check_all(self, task: Dict, result: Dict) -> Dict[str, bool]:
        """执行所有规则检查"""
        results = {}
        for rule in self.rules:
            try:
                passed = rule["check_fn"](task, result)
                results[rule["name"]] = passed
            except (KeyError, TypeError, ValueError) as e:
                print(f"⚠️  规则检查失败: {rule['name']} - {e}")
                results[rule["name"]] = False
        
        return results
    
    def get_pass_rate(self, check_results: Dict[str, bool]) -> float:
        """计算规则通过率"""
        if not check_results:
            return 0.0
        passed = sum(1 for v in check_results.values() if v)
        return passed / len(check_results)
    
    def _check_goal_achieved(self, task: Dict, result: Dict) -> bool:
        """检查是否达成目标"""
        # 简单启发式：检查返回结果是否包含成功标记
        if result.get("success"):
            return True
        
        # 检查输出是否包含关键信息
        output = result.get("stdout", "") + result.get("stderr", "")
        goal_keywords = task.get("goal_keywords", [])
        
        if goal_keywords:
            return any(kw.lower() in output.lower() for kw in goal_keywords)
        
        # 默认认为成功（需要更智能的判断）
        return result.get("exit_code", -1) == 0
    
    def _check_side_effects(self, task: Dict, result: Dict) -> bool:
        """检查副作用"""
        # 检查是否有非预期的文件修改
        expected_actions = task.get("expected_actions", [])
        actual_actions = result.get("actions_taken", [])
        
        # 如果有未预期的操作，视为有副作用
        unexpected = set(actual_actions) - set(expected_actions)
        return len(unexpected) == 0
    
    def _check_budget(self, task: Dict, result: Dict) -> bool:
        """检查预算"""
        budget_limit = task.get("budget_limit_usd", 5.0)
        actual_cost = result.get("cost_usd", 0.0)
        return actual_cost <= budget_limit
    
    def _check_errors(self, task: Dict, result: Dict) -> bool:
        """检查错误"""
        stderr = result.get("stderr", "")
        exit_code = result.get("exit_code", -1)
        
        # 退码非零且有错误输出
        if exit_code != 0 and stderr.strip():
            return False
        
        # 检查是否有异常关键字
        error_keywords = ["error", "exception", "failed", "traceback"]
        if any(kw in stderr.lower() for kw in error_keywords):
            return False
        
        return True
    
    def _check_output_format(self, task: Dict, result: Dict) -> bool:
        """检查输出格式"""
        expected_format = task.get("expected_format")
        
        if not expected_format:
            return True  # 无格式要求
        
        output = result.get("stdout", "")
        
        if expected_format == "json":
            try:
                json.loads(output)
                return True
            except (json.JSONDecodeError, TypeError):
                return False
        elif expected_format == "markdown":
            return output.strip().startswith("#") or output.strip().startswith("-")
        
        return True


class LLMScoreEvaluator:
    """LLM 评分器（真实 LLM + 启发式降级）"""
    
    def __init__(self):
        # 尝试导入真实 LLM 评分器
        try:
            from .llm_scorer import LLMScoreEvaluator as RealLLMEvaluator
            self.real_evaluator = RealLLMEvaluator()
            print("✅ 使用真实 LLM 评分器（智谱 GLM-4 Flash）")
        except (ImportError, ModuleNotFoundError):
            self.real_evaluator = None
            print("⚠️  真实 LLM 评分器不可用，使用启发式规则")
        
        self.dimensions = [
            {
                "name": "completeness",
                "weight": 0.3,
                "description": "任务完成的完整程度，是否覆盖所有要求"
            },
            {
                "name": "accuracy",
                "weight": 0.3,
                "description": "结果的准确性，是否有错误或误导信息"
            },
            {
                "name": "efficiency",
                "weight": 0.2,
                "description": "执行效率，时间和资源消耗是否合理"
            },
            {
                "name": "safety",
                "weight": 0.2,
                "description": "安全性，是否有潜在风险或危险操作"
            }
        ]
    
    def evaluate(self, task: Dict, result: Dict) -> Dict[str, float]:
        """
        使用 LLM 评估任务质量
        
        优先使用真实 LLM（智谱 GLM-4 Flash），失败时降级到启发式规则
        """
        # 尝试真实 LLM
        if self.real_evaluator:
            try:
                llm_result = self.real_evaluator.evaluate(task, result)
                return {
                    "completeness": llm_result.completeness,
                    "accuracy": llm_result.accuracy,
                    "efficiency": llm_result.efficiency,
                    "safety": llm_result.safety
                }
            except Exception as e:
                print(f"⚠️  真实 LLM 评分失败: {e}，降级到启发式")
        
        # 降级到启发式
        return self._heuristic_scoring(task, result)
        
        return scores
    
    def _heuristic_scoring(self, task: Dict, result: Dict) -> Dict[str, float]:
        """启发式评分（临时实现，待 LLM 集成后替换）"""
        scores = {}
        
        # 完整性：基于目标关键词匹配
        completeness = 0.8 if result.get("success") else 0.4
        scores["completeness"] = completeness
        
        # 准确性：基于退出码和错误输出
        accuracy = 1.0 if result.get("exit_code", -1) == 0 else 0.3
        if result.get("stderr"):
            accuracy -= 0.2
        scores["accuracy"] = max(0.0, min(1.0, accuracy))
        
        # 效率：基于执行时间
        duration = result.get("duration_seconds", 0)
        if duration < 5:
            efficiency = 1.0
        elif duration < 30:
            efficiency = 0.8
        elif duration < 60:
            efficiency = 0.6
        else:
            efficiency = 0.4
        scores["efficiency"] = efficiency
        
        # 安全性：基于操作类型
        actions = result.get("actions_taken", [])
        dangerous_ops = ["rm -rf", "chmod 777", "dd if="]
        has_dangerous = any(op in str(actions) for op in dangerous_ops)
        scores["safety"] = 0.0 if has_dangerous else 1.0
        
        return scores
    
    def calculate_final_score(self, dimension_scores: Dict[str, float]) -> float:
        """计算加权综合评分"""
        total_weight = sum(d["weight"] for d in self.dimensions)
        weighted_sum = sum(
            dimension_scores.get(d["name"], 0.0) * d["weight"]
            for d in self.dimensions
        )
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def _build_evaluation_prompt(self, task: Dict, result: Dict) -> str:
        """构建 LLM 评估提示词"""
        return f"""
请评估以下任务执行的质量，从四个维度打分（0-1）：

**任务描述**: {task.get('description', '')}
**执行结果**: 
- 成功: {result.get('success', False)}
- 退出码: {result.get('exit_code', -1)}
- 输出: {result.get('stdout', '')[:500]}
- 错误: {result.get('stderr', '')[:500]}
- 耗时: {result.get('duration_seconds', 0)}秒

请按以下 JSON 格式返回评分：
{{
  "completeness": 0.8,
  "accuracy": 0.9,
  "efficiency": 0.7,
  "safety": 1.0,
  "reasoning": "评分理由..."
}}
"""


class ReflectionScorer:
    """反思评分器（混合方案：LLM + 规则）"""
    
    def __init__(self):
        self.rule_checker = RuleChecker()
        self.llm_evaluator = LLMScoreEvaluator()
        
        # 从配置加载权重和阈值
        config = get_reflection_config()
        self.llm_weight = config.accuracy_weight + config.completeness_weight  # 0.55
        self.rule_weight = config.efficiency_weight + config.safety_weight      # 0.45
        
        self.excellent_threshold = config.excellent_threshold
        self.acceptable_threshold = config.acceptable_threshold
        self.max_retries = config.max_retries
    
    def evaluate(self, task: Dict, result: Dict) -> ReflectionScore:
        """
        执行完整评分流程
        
        Args:
            task: 任务信息字典
            result: 执行结果字典
            
        Returns:
            ReflectionScore 评分结果
        """
        # 1. 规则检查
        rule_results = self.rule_checker.check_all(task, result)
        rule_pass_rate = self.rule_checker.get_pass_rate(rule_results)
        
        # 2. LLM 评分
        llm_scores = self.llm_evaluator.evaluate(task, result)
        llm_final = self.llm_evaluator.calculate_final_score(llm_scores)
        
        # 3. 混合评分
        final_score = (
            self.llm_weight * llm_final +
            self.rule_weight * rule_pass_rate
        )
        
        # 4. 生成诊断和建议
        diagnosis, suggestions = self._generate_feedback(
            task, result, rule_results, llm_scores, final_score
        )
        
        return ReflectionScore(
            completeness=llm_scores.get("completeness", 0.0),
            accuracy=llm_scores.get("accuracy", 0.0),
            efficiency=llm_scores.get("efficiency", 0.0),
            safety=llm_scores.get("safety", 0.0),
            final_score=final_score,
            rule_pass_rate=rule_pass_rate,
            llm_score=llm_final,
            diagnosis=diagnosis,
            suggestions=suggestions
        )
    
    def _generate_feedback(
        self,
        task: Dict,
        result: Dict,
        rule_results: Dict[str, bool],
        llm_scores: Dict[str, float],
        final_score: float
    ) -> tuple:
        """生成诊断说明和改进建议"""
        issues = []
        suggestions = []
        
        # 分析规则失败项
        failed_rules = [k for k, v in rule_results.items() if not v]
        if failed_rules:
            issues.append(f"规则检查失败: {', '.join(failed_rules)}")
            suggestions.append("检查任务执行是否符合预期规范")
        
        # 分析低分维度
        low_dimensions = [
            dim for dim, score in llm_scores.items()
            if score < 0.6
        ]
        if low_dimensions:
            issues.append(f"评分较低维度: {', '.join(low_dimensions)}")
            
            if "completeness" in low_dimensions:
                suggestions.append("确保覆盖任务的所有要求")
            if "accuracy" in low_dimensions:
                suggestions.append("验证结果准确性，避免错误信息")
            if "efficiency" in low_dimensions:
                suggestions.append("优化执行效率，减少不必要的操作")
            if "safety" in low_dimensions:
                suggestions.append("避免危险操作，增加安全检查")
        
        # 根据总分生成总体反馈
        if final_score >= self.excellent_threshold:
            diagnosis = f"优秀 (评分: {final_score:.2f})"
            if not suggestions:
                suggestions.append("保持当前执行方式")
        elif final_score >= self.acceptable_threshold:
            diagnosis = f"合格 (评分: {final_score:.2f})"
            if not suggestions:
                suggestions.append("可进一步优化细节")
        else:
            diagnosis = f"不合格 (评分: {final_score:.2f})"
            if not suggestions:
                suggestions.append("需要重新执行任务，检查执行策略")
        
        # 添加具体问题
        if issues:
            diagnosis += "\n问题: " + "; ".join(issues)
        
        return diagnosis, suggestions
    
    def should_retry(self, score: ReflectionScore, retry_count: int = 0) -> bool:
        """判断是否应该重试"""
        if retry_count >= self.max_retries:
            return False
        
        if score.final_score < self.acceptable_threshold:
            return True
        
        return False
    
    def needs_human_review(self, score: ReflectionScore) -> bool:
        """判断是否需要人工审核"""
        # 评分过低且已重试多次
        if score.final_score < 0.4:
            return True
        
        # 安全性评分低
        if score.safety < 0.5:
            return True
        
        return False


# 测试代码
if __name__ == "__main__":
    scorer = ReflectionScorer()
    
    # 模拟任务和结果
    test_task = {
        "description": "测试任务：列出目录文件",
        "goal_keywords": ["file", "directory"],
        "expected_actions": ["ls"],
        "budget_limit_usd": 0.01,
        "expected_format": None
    }
    
    test_result = {
        "success": True,
        "exit_code": 0,
        "stdout": "file1.txt\nfile2.txt\ndirectory1/",
        "stderr": "",
        "duration_seconds": 2.5,
        "actions_taken": ["ls"],
        "cost_usd": 0.001
    }
    
    # 执行评分
    score = scorer.evaluate(test_task, test_result)
    
    print("=" * 60)
    print("反思评分结果")
    print("=" * 60)
    print(f"完整性: {score.completeness:.2f}")
    print(f"准确性: {score.accuracy:.2f}")
    print(f"效率: {score.efficiency:.2f}")
    print(f"安全性: {score.safety:.2f}")
    print(f"规则通过率: {score.rule_pass_rate:.2f}")
    print(f"LLM 评分: {score.llm_score:.2f}")
    print(f"综合评分: {score.final_score:.2f}")
    print(f"\n诊断: {score.diagnosis}")
    print(f"\n建议:")
    for s in score.suggestions:
        print(f"  - {s}")
    print(f"\n应重试: {scorer.should_retry(score)}")
    print(f"需人工审核: {scorer.needs_human_review(score)}")
