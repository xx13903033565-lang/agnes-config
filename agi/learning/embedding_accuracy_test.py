#!/usr/bin/env python3
"""
向量检索准确率对比测试

对比关键词匹配与 BGE-M3 向量检索的准确率差异。

测试方法：
- 准备 20 个查询用例（覆盖不同任务类型）
- 分别运行关键词检索和向量检索
- 人工标注"期望结果集"
- 计算 Precision@K / Recall@K / MRR

目标：向量检索比关键词提升 ≥30%
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass


@dataclass
class TestCase:
    """测试用例"""
    query: str
    expected_ids: List[str]  # 期望返回的经验 ID
    task_type: str  # 查询类型


@dataclass
class RetrievalResult:
    """检索结果"""
    query_id: int
    method: str  # "keyword" or "vector"
    retrieved_ids: List[str]
    expected_ids: Set[str]
    
    @property
    def precision_at_5(self) -> float:
        """Precision@5"""
        top5 = self.retrieved_ids[:5]
        if not top5:
            return 0.0
        hits = sum(1 for rid in top5 if rid in self.expected_ids)
        return hits / len(top5)
    
    @property
    def recall_at_5(self) -> float:
        """Recall@5"""
        if not self.expected_ids:
            return 1.0
        top5 = set(self.retrieved_ids[:5])
        hits = len(top5 & self.expected_ids)
        return hits / len(self.expected_ids)
    
    @property
    def mrr(self) -> float:
        """Mean Reciprocal Rank"""
        for i, rid in enumerate(self.retrieved_ids[:10], 1):
            if rid in self.expected_ids:
                return 1.0 / i
        return 0.0


class EmbeddingAccuracyTester:
    """向量检索准确率测试器"""
    
    def __init__(self):
        # 导入检索器
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from learning.retriever import ExperienceRetriever
        
        self.retriever = ExperienceRetriever()
        
        # 测试数据集路径
        self.test_data_path = Path.home() / ".agnes" / "datasets" / "embedding_test_cases.json"
        self.test_cases: List[TestCase] = []
    
    def load_test_cases(self) -> int:
        """加载测试用例"""
        if not self.test_data_path.exists():
            print(f"⚠️  测试数据不存在，生成示例数据...")
            self._generate_test_cases()
        
        with open(self.test_data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.test_cases = [
            TestCase(**item) for item in data["test_cases"]
        ]
        
        print(f"✅ 已加载 {len(self.test_cases)} 个测试用例")
        return len(self.test_cases)
    
    def run_keyword_retrieval(self, query: str, top_k: int = 10) -> List[str]:
        """运行关键词检索（简化实现：基于 TF-IDF 风格）"""
        # ExperienceRetriever 只有向量检索，这里用简单的关键词匹配模拟
        import re
        keywords = [kw.strip() for kw in re.split(r'[\s,，]+', query) if len(kw.strip()) > 1]
        
        # 从数据库查询包含关键词的经验
        results = []
        try:
            cursor = self.retriever.db_conn.cursor()
            for kw in keywords[:3]:  # 取前 3 个关键词
                cursor.execute(
                    "SELECT task_id, description FROM task_experiences WHERE description LIKE ?",
                    (f"%{kw}%",)
                )
                rows = cursor.fetchall()
                for row in rows:
                    if row["task_id"] not in [r[0] for r in results]:
                        results.append(row)
                if len(results) >= top_k:
                    break
        except Exception:
            pass
        
        return [r["task_id"] for r in results[:top_k]]
    
    def run_vector_retrieval(self, query: str, top_k: int = 10) -> List[str]:
        """运行向量检索"""
        result = self.retriever.retrieve_similar(query, top_k=top_k)
        # RetrievalResult.similar_experiences 是 RetrievedExperience 列表
        return [exp.experience.task_id for exp in result.similar_experiences if exp.experience.task_id]
    
    def run_all_tests(self) -> Tuple[List[RetrievalResult], List[RetrievalResult]]:
        """
        运行所有测试
        
        Returns:
            (keyword_results, vector_results)
        """
        print(f"\n🔍 开始测试 {len(self.test_cases)} 个查询...")
        
        keyword_results = []
        vector_results = []
        
        start_time = time.time()
        
        for i, case in enumerate(self.test_cases, 1):
            print(f"  [{i}/{len(self.test_cases)}] 查询: {case.query[:40]}...", end=" ")
            
            expected_set = set(case.expected_ids)
            
            # 关键词检索
            kw_ids = self.run_keyword_retrieval(case.query)
            kw_result = RetrievalResult(
                query_id=i,
                method="keyword",
                retrieved_ids=kw_ids,
                expected_ids=expected_set
            )
            keyword_results.append(kw_result)
            
            # 向量检索
            vec_ids = self.run_vector_retrieval(case.query)
            vec_result = RetrievalResult(
                query_id=i,
                method="vector",
                retrieved_ids=vec_ids,
                expected_ids=expected_set
            )
            vector_results.append(vec_result)
            
            kw_p5 = f"{kw_result.precision_at_5:.2f}"
            vec_p5 = f"{vec_result.precision_at_5:.2f}"
            print(f"KW P@5={kw_p5}, Vec P@5={vec_p5}")
        
        elapsed = time.time() - start_time
        print(f"\n⏱️  测试完成！耗时: {elapsed:.2f}s")
        
        return keyword_results, vector_results
    
    def compute_metrics(self, results: List[RetrievalResult]) -> Dict[str, float]:
        """计算聚合指标"""
        if not results:
            return {}
        
        avg_p5 = sum(r.precision_at_5 for r in results) / len(results)
        avg_r5 = sum(r.recall_at_5 for r in results) / len(results)
        avg_mrr = sum(r.mrr for r in results) / len(results)
        
        return {
            "avg_precision_at_5": avg_p5,
            "avg_recall_at_5": avg_r5,
            "avg_mrr": avg_mrr
        }
    
    def generate_report(self, kw_results: List[RetrievalResult], 
                       vec_results: List[RetrievalResult],
                       output_path: Optional[Path] = None) -> Path:
        """生成对比报告"""
        kw_metrics = self.compute_metrics(kw_results)
        vec_metrics = self.compute_metrics(vec_results)
        
        # 计算提升比例
        improvements = {}
        for key in kw_metrics:
            kw_val = kw_metrics[key]
            vec_val = vec_metrics[key]
            if kw_val > 0:
                improvements[key] = (vec_val - kw_val) / kw_val * 100
            else:
                improvements[key] = 0.0 if vec_val == 0 else 100.0
        
        if output_path is None:
            timestamp = int(time.time())
            output_path = Path.home() / ".agnes" / "reports" / f"embedding_accuracy_{timestamp}.json"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        report = {
            "timestamp": time.time(),
            "num_test_cases": len(self.test_cases),
            "keyword_metrics": kw_metrics,
            "vector_metrics": vec_metrics,
            "improvements_percent": improvements,
            "target_improvement": 30.0,
            "meets_target": all(v >= 30.0 for v in improvements.values()),
            "detailed_results": [
                {
                    "query_id": kr.query_id,
                    "query": self.test_cases[kr.query_id - 1].query,
                    "keyword_p5": kr.precision_at_5,
                    "vector_p5": vr.precision_at_5,
                    "keyword_mrr": kr.mrr,
                    "vector_mrr": vr.mrr
                }
                for kr, vr in zip(kw_results, vec_results)
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 打印摘要
        print("\n" + "=" * 70)
        print("📊 向量检索准确率对比报告")
        print("=" * 70)
        print(f"\n关键词检索:")
        print(f"  Precision@5: {kw_metrics['avg_precision_at_5']:.3f}")
        print(f"  Recall@5:    {kw_metrics['avg_recall_at_5']:.3f}")
        print(f"  MRR:         {kw_metrics['avg_mrr']:.3f}")
        
        print(f"\n向量检索:")
        print(f"  Precision@5: {vec_metrics['avg_precision_at_5']:.3f}")
        print(f"  Recall@5:    {vec_metrics['avg_recall_at_5']:.3f}")
        print(f"  MRR:         {vec_metrics['avg_mrr']:.3f}")
        
        print(f"\n提升幅度:")
        print(f"  Precision@5: {improvements['avg_precision_at_5']:+.1f}%")
        print(f"  Recall@5:    {improvements['avg_recall_at_5']:+.1f}%")
        print(f"  MRR:         {improvements['avg_mrr']:+.1f}%")
        
        print(f"\n目标准升幅: ≥30%")
        if report["meets_target"]:
            print(f"  ✅ 全部达标！")
        else:
            failing = [k for k, v in improvements.items() if v < 30.0]
            print(f"  ❌ 未达标指标: {', '.join(failing)}")
        
        print(f"\n💾 详细报告: {output_path}")
        
        return output_path
    
    def _generate_test_cases(self):
        """生成示例测试用例"""
        test_cases = [
            TestCase(
                query="如何列出项目中的所有 Python 文件",
                expected_ids=[f"exp_{i:03d}" for i in range(1, 6)],
                task_type="file_operation"
            ),
            TestCase(
                query="安装依赖包的方法",
                expected_ids=[f"exp_{i:03d}" for i in range(6, 11)],
                task_type="package_management"
            ),
            TestCase(
                query="统计代码行数",
                expected_ids=[f"exp_{i:03d}" for i in range(11, 16)],
                task_type="code_analysis"
            ),
            TestCase(
                query="搜索特定函数定义",
                expected_ids=[f"exp_{i:03d}" for i in range(16, 21)],
                task_type="code_search"
            ),
            TestCase(
                query="生成 Markdown 目录",
                expected_ids=[f"exp_{i:03d}" for i in range(21, 26)],
                task_type="documentation"
            )
        ]
        
        data = {
            "version": "1.0",
            "created_at": time.time(),
            "description": "向量检索准确率测试用例（示例）",
            "test_cases": [tc.__dict__ for tc in test_cases]
        }
        
        self.test_data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.test_data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已生成示例测试用例: {self.test_data_path}")


if __name__ == "__main__":
    print("=" * 70)
    print("向量检索准确率对比测试")
    print("=" * 70)
    
    tester = EmbeddingAccuracyTester()
    
    # 加载测试用例
    tester.load_test_cases()
    
    # 运行测试
    kw_results, vec_results = tester.run_all_tests()
    
    # 生成报告
    report_path = tester.generate_report(kw_results, vec_results)
    
    print(f"\n✅ 测试完成！")
