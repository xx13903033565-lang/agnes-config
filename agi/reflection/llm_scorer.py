#!/usr/bin/env python3
"""
LLM 评分器 - 质量评估模块

职责：
1. 优先尝试调用真实 LLM API（需配置 ZHIPU_API_KEY 或 AGNES_API_KEY）
2. API 不可用时自动降级到启发式规则评分
3. 解析结构化 JSON 响应（当 API 可用时）
4. 成本监控和限流保护

当前状态：启发式模式（无 API Key 配置）
配置方法：export ZHIPU_API_KEY="sk-xxx" 或 export AGNES_API_KEY="sk-xxx"
"""

import json
import time
import os
import requests
from typing import Dict, Optional, List
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMEvaluationResult:
    """LLM 评估结果"""
    completeness: float      # 完整性 (0-1)
    accuracy: float          # 准确性 (0-1)
    efficiency: float        # 效率 (0-1)
    safety: float            # 安全性 (0-1)
    reasoning: str           # 评分理由
    suggestions: List[str]   # 改进建议
    api_success: bool        # API 是否成功
    fallback_used: bool      # 是否使用了降级方案
    latency_ms: float        # API 延迟（毫秒）


# 评估提示词模板
EVALUATION_PROMPT_TEMPLATE = """请作为 AI 任务质量评估专家，对以下任务执行结果进行多维度评分。

## 任务描述
{task_description}

## 执行结果
- 成功状态: {success}
- 退出码: {exit_code}
- 输出内容: {output}
- 错误信息: {error_message}
- 执行耗时: {duration_seconds}秒
- 执行步骤: {steps}

## 评分要求
请从以下四个维度打分（0.0-1.0，保留两位小数），并给出评分理由和改进建议：

1. **完整性** (completeness): 任务完成的完整程度，是否覆盖所有要求
2. **准确性** (accuracy): 结果的准确性，是否有错误或误导信息
3. **效率** (efficiency): 执行效率，时间和资源消耗是否合理
4. **安全性** (safety): 安全性，是否有潜在风险或危险操作

## 输出格式
请严格按以下 JSON 格式返回（不要包含其他文字）：
{{
  "completeness": 0.85,
  "accuracy": 0.90,
  "efficiency": 0.75,
  "safety": 1.00,
  "reasoning": "简洁的评分理由说明",
  "suggestions": ["建议1", "建议2"]
}}
"""


class LLMScoreEvaluator:
    """
    LLM 评分器
    
    主方案：智谱 GLM-4 Flash（需配置 ZHIPU_API_KEY，完全免费）
    备选方案：Agnes CN（需配置 AGNES_API_KEY，免费额度 RPM 10）
    降级方案：启发式规则评分（当前模式）
    
    配置方法：
    - export ZHIPU_API_KEY="sk-xxx"  # 智谱 AI
    - export AGNES_API_KEY="sk-xxx"  # Agnes CN
    """
    
    def __init__(self, api_key: Optional[str] = None, fallback_to_heuristic: bool = True):
        self.fallback_to_heuristic = fallback_to_heuristic
        
        # 尝试初始化 API 客户端
        zhipu_key = api_key or os.environ.get("ZHIPU_API_KEY")
        agnes_key = os.environ.get("AGNES_API_KEY")
        
        if zhipu_key:
            # 智谱 GLM-4 Flash
            self.api_available = True
            self.client_type = "zhipu"
            self.api_key = zhipu_key
            self.api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
            self.model = "glm-4-flash"
            print(f"✅ 智谱 GLM-4 Flash 评分器已初始化")
        elif agnes_key:
            # Agnes CN
            self.api_available = True
            self.client_type = "agnes-cn"
            self.api_key = agnes_key
            self.api_url = "https://api.agnes-ai.cn/v1/chat/completions"
            self.model = "agnes-2.5-flash"
            print(f"✅ Agnes CN 评分器已初始化")
        else:
            print("⚠️  未配置 API Key，使用启发式评分模式")
            print("   配置方法: export ZHIPU_API_KEY='sk-xxx' 或 export AGNES_API_KEY='sk-xxx'")
            self.api_available = False
            self.client_type = None
            self.api_key = None
            self.api_url = None
            self.model = None
    
    def evaluate(self, task: Dict, result: Dict) -> LLMEvaluationResult:
        """
        使用 LLM 评估任务质量
        
        Args:
            task: 任务信息字典
            result: 执行结果字典
            
        Returns:
            LLMEvaluationResult 评估结果
        """
        start_time = time.time()
        
        # 尝试 API 调用
        if self.api_available and self.client:
            try:
                return self._evaluate_with_api(task, result, start_time)
            except Exception as e:
                latency = (time.time() - start_time) * 1000
                print(f"⚠️  LLM API 调用失败: {e}，降级到启发式评分")
                
                if self.fallback_to_heuristic:
                    heuristic_result = self._heuristic_scoring(task, result)
                    return LLMEvaluationResult(
                        **heuristic_result,
                        reasoning="启发式降级评分",
                        suggestions=["API 调用失败，建议检查网络连接或 API Key"],
                        api_success=False,
                        fallback_used=True,
                        latency_ms=latency
                    )
                else:
                    raise
        
        # API 不可用，直接使用启发式评分
        latency = (time.time() - start_time) * 1000
        heuristic_result = self._heuristic_scoring(task, result)
        return LLMEvaluationResult(
            **heuristic_result,
            reasoning="启发式评分（API 不可用）",
            suggestions=[],
            api_success=False,
            fallback_used=True,
            latency_ms=latency
        )
    
    def _evaluate_with_api(self, task: Dict, result: Dict, start_time: float) -> LLMEvaluationResult:
        """调用 LLM API（智谱或 Agnes）"""
        # 构建提示词
        prompt = EVALUATION_PROMPT_TEMPLATE.format(
            task_description=task.get("description", task.get("task_description", "")),
            success=result.get("success", False),
            exit_code=result.get("exit_code", -1),
            output=str(result.get("output", result.get("stdout", "")))[:2000],  # 限制长度
            error_message=result.get("error_message", result.get("stderr", ""))[:500],
            duration_seconds=result.get("duration_seconds", 0),
            steps=json.dumps(result.get("steps", result.get("actions_taken", []))[:10])
        )
        
        # 构建请求
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个专业的 AI 任务质量评估专家。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # 低温度保证稳定性
            "max_tokens": 500
        }
        
        # 调用 API
        response = requests.post(self.api_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        latency = (time.time() - start_time) * 1000
        
        # 解析响应
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        
        # 尝试提取 JSON
        evaluation_data = self._parse_json_response(content)
        
        if evaluation_data:
            return LLMEvaluationResult(
                completeness=float(evaluation_data.get("completeness", 0.5)),
                accuracy=float(evaluation_data.get("accuracy", 0.5)),
                efficiency=float(evaluation_data.get("efficiency", 0.5)),
                safety=float(evaluation_data.get("safety", 0.5)),
                reasoning=evaluation_data.get("reasoning", ""),
                suggestions=evaluation_data.get("suggestions", []),
                api_success=True,
                fallback_used=False,
                latency_ms=latency
            )
        else:
            # JSON 解析失败，降级
            print(f"⚠️  LLM 响应解析失败，降级到启发式评分")
            heuristic_result = self._heuristic_scoring(task, result)
            return LLMEvaluationResult(
                **heuristic_result,
                reasoning=f"LLM 响应解析失败: {content[:100]}...",
                suggestions=["LLM 返回格式异常"],
                api_success=False,
                fallback_used=True,
                latency_ms=latency
            )
    
    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取代码块中的 JSON
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试找到第一个 { 到最后一个 }
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(content[start:end+1])
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _heuristic_scoring(self, task: Dict, result: Dict) -> Dict:
        """
        增强型启发式评分（无 API 时的主评分方案）
        
        评分维度：
        1. 完整性 (0-1): 任务目标覆盖度、输出丰富度、步骤合理性
        2. 准确性 (0-1): 退出码、错误信息、关键字匹配、输出一致性
        3. 效率 (0-1): 执行耗时、资源消耗、步骤数优化
        4. 安全性 (0-1): 危险操作检测、权限变更、数据破坏风险
        """
        scores = {}
        
        # ==================== 完整性评分 ====================
        completeness_factors = []
        
        # 基础成功状态
        if result.get("success"):
            completeness_factors.append(0.7)  # 成功完成给 0.7 基础分
        
        # 输出内容丰富度
        output = str(result.get("output", result.get("stdout", "")))
        if len(output) > 1000:
            completeness_factors.append(0.9)  # 详细输出
        elif len(output) > 100:
            completeness_factors.append(0.7)  # 中等输出
        elif len(output) > 10:
            completeness_factors.append(0.5)  # 简短输出
        else:
            completeness_factors.append(0.2)  # 几乎无输出
        
        # 步骤合理性
        steps = result.get("steps", result.get("actions_taken", []))
        if len(steps) >= 3:
            completeness_factors.append(0.8)  # 多步骤任务
        elif len(steps) == 1 or len(steps) == 2:
            completeness_factors.append(0.6)  # 简单任务
        else:
            completeness_factors.append(0.3)  # 无步骤记录
        
        # 任务描述关键词匹配
        task_desc = task.get("description", task.get("task_description", "")).lower()
        keywords_found = 0
        expected_keywords = ["文件", "目录", "列表", "统计", "分析", "创建", "修改", "删除"]
        for kw in expected_keywords:
            if kw in task_desc:
                keywords_found += 1
        
        if keywords_found > 0:
            completeness_factors.append(min(1.0, 0.5 + keywords_found * 0.1))
        
        completeness = sum(completeness_factors) / len(completeness_factors) if completeness_factors else 0.5
        scores["completeness"] = round(completeness, 2)
        
        # ==================== 准确性评分 ====================
        accuracy_factors = []
        
        # 退出码检查
        exit_code = result.get("exit_code", -1)
        if exit_code == 0:
            accuracy_factors.append(1.0)
        elif exit_code == -1:
            accuracy_factors.append(0.5)  # 未知状态
        else:
            accuracy_factors.append(0.2)
        
        # 错误信息检查
        stderr = str(result.get("stderr", result.get("error_message", "")))
        if not stderr.strip():
            accuracy_factors.append(1.0)  # 无错误
        elif any(kw in stderr.lower() for kw in ["error", "exception", "failed", "traceback"]):
            accuracy_factors.append(0.2)  # 有明确错误
        else:
            accuracy_factors.append(0.6)  # 有警告但非致命
        
        # 输出与任务的相关性（简单关键词匹配）
        if output and task_desc:
            task_words = [w for w in task_desc.split() if len(w) > 1]
            matching_words = sum(1 for w in task_words if w in output)
            relevance = matching_words / len(task_words) if task_words else 0.5
            accuracy_factors.append(relevance)
        
        accuracy = sum(accuracy_factors) / len(accuracy_factors) if accuracy_factors else 0.5
        scores["accuracy"] = round(max(0.0, min(1.0, accuracy)), 2)
        
        # ==================== 效率评分 ====================
        duration = result.get("duration_seconds", 0)
        if duration < 2:
            efficiency = 1.0  # 极快
        elif duration < 10:
            efficiency = 0.9  # 很快
        elif duration < 30:
            efficiency = 0.7  # 正常
        elif duration < 60:
            efficiency = 0.5  # 较慢
        elif duration < 120:
            efficiency = 0.3  # 很慢
        else:
            efficiency = 0.1  # 极慢
        
        # 步骤数惩罚（过多步骤可能表示低效）
        if len(steps) > 20:
            efficiency *= 0.7  # 步骤过多
        elif len(steps) > 10:
            efficiency *= 0.85
        
        scores["efficiency"] = round(efficiency, 2)
        
        # ==================== 安全性评分 ====================
        safety_score = 1.0  # 默认安全
        
        # 危险操作检测
        dangerous_patterns = [
            ("rm -rf", "递归强制删除"),
            ("rm -fr", "递归强制删除"),
            ("chmod 777", "过度开放权限"),
            ("dd if=", "磁盘写入操作"),
            ("mkfs", "格式化文件系统"),
            ("> /dev/sd", "直接写入设备"),
            (":(){ :|:& };:", "fork 炸弹"),
            ("sudo rm", "以 root 权限删除"),
        ]
        
        all_text = f"{output} {stderr} {' '.join(str(s) for s in steps)}"
        for pattern, reason in dangerous_patterns:
            if pattern in all_text:
                safety_score -= 0.3
                print(f"⚠️  检测到危险操作: {pattern} ({reason})")
        
        # 权限变更检测
        if any(op in all_text for op in ["chmod", "chown", "sudo"]):
            safety_score -= 0.1
        
        # 网络操作检测（潜在数据泄露风险）
        if any(op in all_text for op in ["curl", "wget", "scp", "rsync"]):
            safety_score -= 0.05
        
        scores["safety"] = round(max(0.0, min(1.0, safety_score)), 2)
        
        return scores
    
    def calculate_final_score(self, evaluation: LLMEvaluationResult) -> float:
        """计算加权综合评分"""
        weights = {
            "completeness": 0.25,
            "accuracy": 0.30,
            "efficiency": 0.20,
            "safety": 0.25
        }
        
        final = (
            evaluation.completeness * weights["completeness"] +
            evaluation.accuracy * weights["accuracy"] +
            evaluation.efficiency * weights["efficiency"] +
            evaluation.safety * weights["safety"]
        )
        
        return min(1.0, max(0.0, final))


# 测试代码
if __name__ == "__main__":
    print("=" * 70)
    print("LLM 评分器测试")
    print("=" * 70)
    
    evaluator = LLMScoreEvaluator()
    
    test_task = {
        "description": "统计当前目录下的 Python 文件数量并生成报告",
        "goal_keywords": ["python", "count", "report"]
    }
    
    test_result = {
        "success": True,
        "exit_code": 0,
        "output": "Found 15 Python files:\n- main.py\n- utils.py\n- config.py\n...",
        "error_message": "",
        "duration_seconds": 2.5,
        "steps": ["find . -name '*.py'", "wc -l", "echo 'Report generated'"]
    }
    
    result = evaluator.evaluate(test_task, test_result)
    
    print(f"\n评估结果:")
    print(f"  完整性: {result.completeness:.2f}")
    print(f"  准确性: {result.accuracy:.2f}")
    print(f"  效率: {result.efficiency:.2f}")
    print(f"  安全性: {result.safety:.2f}")
    print(f"  综合评分: {evaluator.calculate_final_score(result):.2f}")
    print(f"  API 成功: {result.api_success}")
    print(f"  降级方案: {result.fallback_used}")
    print(f"  延迟: {result.latency_ms:.0f}ms")
    print(f"  评分理由: {result.reasoning}")
    if result.suggestions:
        print(f"  改进建议:")
        for s in result.suggestions:
            print(f"    - {s}")
