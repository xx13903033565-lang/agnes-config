#!/usr/bin/env python3
"""
LLM 评分一致性验证工具

用于评估 LLM 评分器与人工标注的一致性，确保评分质量。

功能：
- 加载 50 项人工标注数据集
- 批量运行 LLM 评分器
- 计算一致性指标（准确率/Kappa 系数/相关系数）
- 生成验证报告

目标：≥85% 一致性
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ValidationSample:
    """验证样本"""
    task_id: str
    task_description: str
    task_type: str
    result_summary: str
    human_score: float  # 人工标注分数 (0-1)
    human_label: str    # 人工标签 (excellent/acceptable/poor)


@dataclass
class ValidationResult:
    """验证结果"""
    sample_id: str
    llm_score: float
    llm_label: str
    human_score: float
    human_label: str
    match: bool
    score_diff: float


class ScoringValidator:
    """评分一致性验证器"""
    
    def __init__(self, dataset_path: Optional[Path] = None):
        self.dataset_path = dataset_path or Path.home() / ".agnes" / "datasets" / "scoring_validation.json"
        self.samples: List[ValidationSample] = []
        
        # 从 reflection.scorer 导入
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from reflection.scorer import LLMScoreEvaluator
        self.evaluator = LLMScoreEvaluator()
    
    def load_dataset(self, dataset_path: Optional[Path] = None) -> int:
        """
        加载验证数据集
        
        Returns:
            加载的样本数量
        """
        path = dataset_path or self.dataset_path
        
        if not path.exists():
            print(f"⚠️  数据集不存在，生成示例数据集...")
            self._generate_sample_dataset(path)
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.samples = [
            ValidationSample(**item) for item in data["samples"]
        ]
        
        print(f"✅ 已加载 {len(self.samples)} 个验证样本")
        return len(self.samples)
    
    def run_validation(self, max_samples: Optional[int] = None) -> List[ValidationResult]:
        """
        运行验证
        
        Args:
            max_samples: 最大验证样本数（None 表示全部）
            
        Returns:
            验证结果列表
        """
        samples_to_test = self.samples[:max_samples] if max_samples else self.samples
        
        print(f"\n🔍 开始验证 {len(samples_to_test)} 个样本...")
        
        results = []
        start_time = time.time()
        
        for i, sample in enumerate(samples_to_test, 1):
            print(f"  [{i}/{len(samples_to_test)}] 验证 {sample.task_id}...", end=" ")
            
            # 构造简化的任务和结果
            task = {
                "task_id": sample.task_id,
                "description": sample.task_description,
                "type": sample.task_type
            }
            
            result = {
                "success": True,
                "output": sample.result_summary,
                "duration_seconds": 1.0
            }
            
            try:
                # 运行 LLM 评分器
                score_result = self.evaluator.evaluate(task, result)
                
                # 兼容 dict 和 dataclass 两种返回类型
                if isinstance(score_result, dict):
                    llm_score = score_result.get("final_score", 0.5)
                else:
                    llm_score = score_result.final_score
                
                llm_label = self._score_to_label(llm_score)
                
                # 判断是否一致（允许 ±0.15 误差）
                score_diff = abs(llm_score - sample.human_score)
                label_match = llm_label == sample.human_label
                score_match = score_diff <= 0.15
                
                is_match = label_match and score_match
                
                validation_result = ValidationResult(
                    sample_id=sample.task_id,
                    llm_score=llm_score,
                    llm_label=llm_label,
                    human_score=sample.human_score,
                    human_label=sample.human_label,
                    match=is_match,
                    score_diff=score_diff
                )
                
                results.append(validation_result)
                print(f"✅ LLM={llm_score:.2f}({llm_label}) vs Human={sample.human_score:.2f}({sample.human_label}) {'✓' if is_match else '✗'}")
                
            except Exception as e:
                print(f"❌ 错误: {e}")
                results.append(ValidationResult(
                    sample_id=sample.task_id,
                    llm_score=0.0,
                    llm_label="error",
                    human_score=sample.human_score,
                    human_label=sample.human_label,
                    match=False,
                    score_diff=1.0
                ))
        
        elapsed = time.time() - start_time
        print(f"\n⏱️  验证完成！耗时: {elapsed:.2f}s")
        
        return results
    
    def compute_metrics(self, results: List[ValidationResult]) -> Dict[str, float]:
        """
        计算一致性指标
        
        Returns:
            指标字典
        """
        if not results:
            return {}
        
        total = len(results)
        matches = sum(1 for r in results if r.match)
        
        # 准确率
        accuracy = matches / total if total > 0 else 0.0
        
        # 平均分数差异
        avg_score_diff = sum(r.score_diff for r in results) / total
        
        # Pearson 相关系数（简化计算）
        llm_scores = [r.llm_score for r in results if r.llm_label != "error"]
        human_scores = [r.human_score for r in results if r.llm_label != "error"]
        
        if len(llm_scores) > 1:
            correlation = self._pearson_correlation(llm_scores, human_scores)
        else:
            correlation = 0.0
        
        # Cohen's Kappa（简化版）
        kappa = self._compute_kappa(results)
        
        metrics = {
            "total_samples": total,
            "matches": matches,
            "accuracy": accuracy,
            "avg_score_diff": avg_score_diff,
            "pearson_correlation": correlation,
            "cohens_kappa": kappa,
            "target_accuracy": 0.85,
            "meets_target": accuracy >= 0.85
        }
        
        return metrics
    
    def generate_report(self, results: List[ValidationResult], 
                       output_path: Optional[Path] = None) -> Path:
        """
        生成验证报告
        
        Returns:
            报告文件路径
        """
        metrics = self.compute_metrics(results)
        
        if output_path is None:
            timestamp = int(time.time())
            output_path = Path.home() / ".agnes" / "reports" / f"validation_report_{timestamp}.json"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        report = {
            "timestamp": time.time(),
            "metrics": metrics,
            "results": [
                {
                    "sample_id": r.sample_id,
                    "llm_score": r.llm_score,
                    "llm_label": r.llm_label,
                    "human_score": r.human_score,
                    "human_label": r.human_label,
                    "match": r.match,
                    "score_diff": r.score_diff
                }
                for r in results
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 打印摘要
        print("\n" + "=" * 70)
        print("📊 验证报告摘要")
        print("=" * 70)
        print(f"  总样本数: {metrics['total_samples']}")
        print(f"  一致数量: {metrics['matches']}")
        print(f"  准确率: {metrics['accuracy']:.2%}")
        print(f"  平均分差: {metrics['avg_score_diff']:.3f}")
        print(f"  Pearson 相关: {metrics['pearson_correlation']:.3f}")
        print(f"  Cohen's Kappa: {metrics['cohens_kappa']:.3f}")
        print(f"  目标准确率: {metrics['target_accuracy']:.2%}")
        print(f"  ✅ 达标!" if metrics['meets_target'] else f"  ❌ 未达标")
        print(f"\n💾 详细报告: {output_path}")
        
        return output_path
    
    def _score_to_label(self, score: float) -> str:
        """将分数转换为标签"""
        if score >= 0.8:
            return "excellent"
        elif score >= 0.6:
            return "acceptable"
        else:
            return "poor"
    
    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """计算 Pearson 相关系数"""
        n = len(x)
        if n < 2:
            return 0.0
        
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        
        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
        denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
        
        if denom_x == 0 or denom_y == 0:
            return 0.0
        
        return numerator / (denom_x * denom_y)
    
    def _compute_kappa(self, results: List[ValidationResult]) -> float:
        """计算简化的 Cohen's Kappa"""
        # 构建混淆矩阵
        labels = ["excellent", "acceptable", "poor"]
        confusion = {l1: {l2: 0 for l2 in labels} for l1 in labels}
        
        for r in results:
            if r.llm_label in labels and r.human_label in labels:
                confusion[r.human_label][r.llm_label] += 1
        
        # 计算观察一致性
        total = sum(sum(row.values()) for row in confusion.values())
        observed_agreement = sum(confusion[l][l] for l in labels) / total if total > 0 else 0.0
        
        # 计算期望一致性（简化）
        if total == 0:
            return 0.0
        
        llm_marginals = {l: sum(confusion[l2][l] for l2 in labels) / total for l in labels}
        human_marginals = {l: sum(confusion[l][l2] for l2 in labels) / total for l in labels}
        expected_agreement = sum(llm_marginals[l] * human_marginals[l] for l in labels)
        
        if expected_agreement >= 1.0:
            return 0.0
        
        kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)
        return max(0.0, kappa)  # Kappa 不应为负
    
    def _generate_sample_dataset(self, output_path: Path):
        """生成示例验证数据集"""
        samples = [
            ValidationSample(
                task_id=f"val_{i:03d}",
                task_description=f"示例任务 {i}",
                task_type="code_generation" if i % 2 == 0 else "file_operation",
                result_summary=f"这是任务 {i} 的结果摘要",
                human_score=0.7 + (i % 10) * 0.03,
                human_label="acceptable" if i % 3 != 0 else "excellent"
            )
            for i in range(50)
        ]
        
        data = {
            "version": "1.0",
            "created_at": time.time(),
            "description": "LLM 评分一致性验证数据集（示例）",
            "samples": [s.__dict__ for s in samples]
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已生成示例数据集: {output_path}")


if __name__ == "__main__":
    print("=" * 70)
    print("LLM 评分一致性验证工具")
    print("=" * 70)
    
    validator = ScoringValidator()
    
    # 加载数据集
    validator.load_dataset()
    
    # 运行验证（限制 10 个样本以加快测试）
    results = validator.run_validation(max_samples=10)
    
    # 生成报告
    report_path = validator.generate_report(results)
    
    print(f"\n✅ 验证完成！")
