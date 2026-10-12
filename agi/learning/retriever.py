#!/usr/bin/env python3
"""
AgnesCode AGI Learning - 经验检索器
Phase 4.2: 基于向量相似度的历史经验检索
"""

import sys
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))

import sqlite3
import chromadb
from schema import init_database
from scorer import ReflectionScore


@dataclass
class ExperienceRecord:
    """经验记录"""
    task_id: str
    task_description: str
    task_type: str
    success: bool
    output: str
    quality_score: float
    steps_taken: List[str] = field(default_factory=list)
    error_message: str = ""
    duration_seconds: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class RetrievedExperience:
    """检索到的经验（带相似度）"""
    experience: ExperienceRecord
    similarity: float  # 0-1，越高越相似
    relevance_reason: str = ""  # 相关性说明


@dataclass
class RetrievalResult:
    """检索结果"""
    similar_experiences: List[RetrievedExperience] = field(default_factory=list)
    related_skills: List[Dict] = field(default_factory=list)
    failure_cases: List[Dict] = field(default_factory=list)
    total_matches: int = 0


class ExperienceRetriever:
    """
    经验检索器
    
    工作流程：
    1. 新任务到来时，提取任务描述
    2. 使用 BGE-M3 生成任务描述的向量
    3. 在 ChromaDB 中检索相似任务
    4. 从 SQLite 获取完整经验详情
    5. 返回相似经验、相关技能、失败案例
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        chroma_path: Optional[Path] = None,
        embedding_model_name: str = "BGE-M3"
    ):
        # 确保 Phase 1 Memory 已初始化（创建所有必需表）
        import sys
        from pathlib import Path as P
        sys.path.insert(0, str(P(__file__).parent.parent / 'memory'))
        from init_memory import ensure_memory_initialized
        
        if db_path is None:
            db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
        
        # 确保数据库和表已创建
        ensure_memory_initialized(db_path)
        
        # 初始化 SQLite
        self.db_conn = init_database(db_path)
        
        # 初始化 ChromaDB
        if chroma_path is None:
            chroma_path = Path.home() / '.agnes' / 'memory' / 'chromadb'
        
        self.chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        self.collection = self.chroma_client.get_or_create_collection(
            name="task_experiences",
            metadata={"description": "任务执行经验向量索引"}
        )
        
        self.embedding_model_name = embedding_model_name
        
        print(f"📚 经验检索器已初始化")
        print(f"  SQLite: {self.db_conn}")
        print(f"  ChromaDB collection: {self.collection.name}")
    
    def store_experience(
        self,
        task_id: str,
        task_description: str,
        task_type: str,
        result: Dict,
        score: Optional[ReflectionScore] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        存储任务执行经验
        
        Args:
            task_id: 任务唯一标识
            task_description: 任务描述
            task_type: 任务类型
            result: 执行结果字典
            score: 反思评分（可选）
            tags: 标签列表
            
        Returns:
            task_id 任务ID
        """
        cursor = self.db_conn.cursor()
        
        # 提取评分
        quality_score = score.final_score if score else 0.0
        completeness = score.completeness if score else 0.0
        accuracy = score.accuracy if score else 0.0
        efficiency = score.efficiency if score else 0.0
        safety = score.safety if score else 0.0
        
        # 提取步骤
        steps_taken = json.dumps(result.get("steps", []))
        
        # 插入经验记录
        cursor.execute("""
            INSERT OR REPLACE INTO task_experiences 
            (task_id, task_description, task_type, execution_plan, steps_taken,
             success, output, error_message, duration_seconds,
             quality_score, completeness_score, accuracy_score, 
             efficiency_score, safety_score, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            task_description,
            task_type,
            json.dumps(result.get("plan", {})),
            steps_taken,
            result.get("success", False),
            result.get("output", ""),
            result.get("error", ""),
            result.get("duration_seconds", 0.0),
            quality_score,
            completeness,
            accuracy,
            efficiency,
            safety,
            ",".join(tags) if tags else ""
        ))
        
        # 生成向量并存储到 ChromaDB
        try:
            embedding = self._generate_embedding(task_description)
            chroma_id = f"exp_{task_id}"
            
            self.collection.upsert(
                ids=[chroma_id],
                embeddings=[embedding],
                metadatas=[{
                    "task_id": task_id,
                    "task_type": task_type,
                    "success": result.get("success", False),
                    "quality_score": quality_score
                }],
                documents=[task_description]
            )
            
            # 记录向量索引关联
            cursor.execute("""
                INSERT OR REPLACE INTO experience_embeddings 
                (task_id, chroma_id, embedding_model)
                VALUES (?, ?, ?)
            """, (task_id, chroma_id, self.embedding_model_name))
            
        except Exception as e:
            print(f"⚠️  向量存储失败: {e}")
        
        self.db_conn.commit()
        print(f"💾 经验已存储: {task_id[:8]}... ({task_description[:30]}...)")
        
        return task_id
    
    def retrieve_similar(
        self,
        task_description: str,
        top_k: Optional[int] = None,
        min_similarity: Optional[float] = None,
        filter_success: bool = True
    ) -> RetrievalResult:
        """
        检索相似经验
        
        Args:
            task_description: 当前任务描述
            top_k: 返回最相似的 K 条经验（默认从配置读取）
            min_similarity: 最小相似度阈值（默认从配置读取）
            filter_success: 是否只返回成功的经验
            
        Returns:
            RetrievalResult 检索结果
        """
        # 从配置加载默认值
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config.settings_loader import get_learning_config
        
        config = get_learning_config()
        
        if top_k is None:
            top_k = config.retrieval_top_k
        if min_similarity is None:
            min_similarity = config.min_similarity
        print(f"\n🔍 检索相似经验: {task_description[:50]}...")
        
        # 生成查询向量
        query_embedding = self._generate_embedding(task_description)
        
        # 在 ChromaDB 中搜索
        where_clause = {}
        if filter_success:
            where_clause["success"] = True
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2,  # 多取一些，后续过滤
            where=where_clause if where_clause else None
        )
        
        # 处理检索结果
        retrieved = RetrievalResult()
        
        if results["ids"] and results["ids"][0]:
            for i, chroma_id in enumerate(results["ids"][0]):
                # ChromaDB 默认使用 L2 距离，转换为相似度
                distance = results["distances"][0][i] if results["distances"] else float('inf')
                
                # L2 距离转相似度：对于归一化向量，L2 ∈ [0, 2]
                # 使用公式: similarity = max(0, 1 - distance / 2)
                similarity = max(0.0, 1.0 - distance / 2.0)
                
                # 过滤低相似度
                if similarity < min_similarity:
                    continue
                
                # 从 SQLite 获取完整信息
                task_id = chroma_id.replace("exp_", "")
                experience = self._get_experience_by_task_id(task_id)
                
                if experience:
                    retrieved.similar_experiences.append(
                        RetrievedExperience(
                            experience=experience,
                            similarity=similarity,
                            relevance_reason=self._explain_relevance(
                                task_description, experience.task_description
                            )
                        )
                    )
        
        # 获取相关技能
        retrieved.related_skills = self._get_related_skills(task_description)
        
        # 获取相关失败案例
        retrieved.failure_cases = self._get_failure_cases(task_description)
        
        retrieved.total_matches = len(retrieved.similar_experiences)
        
        print(f"✅ 找到 {retrieved.total_matches} 条相似经验")
        if retrieved.related_skills:
            print(f"   相关技能: {len(retrieved.related_skills)} 个")
        if retrieved.failure_cases:
            print(f"   失败案例: {len(retrieved.failure_cases)} 个")
        
        return retrieved
    
    def _generate_embedding(self, text: str) -> List[float]:
        """
        生成文本向量
        
        优先使用真实 BGE-M3 API（硅基流动），降级到本地模型或关键词加权
        """
        # 尝试使用真实 Embedding 生成器
        try:
            from .embedder import EmbeddingGenerator
            
            # 单例模式：避免重复初始化
            if not hasattr(self, '_embedder'):
                self._embedder = EmbeddingGenerator()
            
            result = self._embedder.generate(text)
            
            # 如果维度不匹配 ChromaDB（1024），需要填充或截断
            target_dim = 1024
            vector = result.vector
            
            if len(vector) < target_dim:
                # 填充到 1024 维
                vector = vector + [0.0] * (target_dim - len(vector))
            elif len(vector) > target_dim:
                # 截断到 1024 维
                vector = vector[:target_dim]
            
            return vector
            
        except (ImportError, ModuleNotFoundError, Exception) as e:
            print(f"️  真实 Embedding 不可用: {e}，使用关键词加权降级")
        
        # 降级方案：改进的模拟实现（基于字符 n-gram 频率）
        import math
        
        # 使用字符级别的 bigram 作为特征（简化版）
        text_lower = text.lower()
        
        # 预定义一些常见关键词的权重（模拟词汇表）
        keyword_weights = {
            'python': 0.9, '文件': 0.8, '目录': 0.7, '列出': 0.7,
            '搜索': 0.8, '查找': 0.8, '安装': 0.9, '统计': 0.7,
            '分析': 0.7, '代码': 0.6, '行数': 0.6, '依赖': 0.7,
            '包': 0.6, 'pip': 0.8, '项目': 0.6, '所有': 0.5,
            '源文件': 0.7, '报告': 0.6, '生成': 0.5
        }
        
        # 初始化 1024 维向量
        embedding = [0.0] * 1024
        
        # 前 20 维：关键词匹配
        keywords = list(keyword_weights.keys())
        for i, kw in enumerate(keywords[:20]):
            if kw in text_lower:
                embedding[i] = keyword_weights[kw]
        
        # 中间 100 维：字符 bigram 频率
        bigrams = {}
        for i in range(len(text_lower) - 1):
            bg = text_lower[i:i+2]
            bigrams[bg] = bigrams.get(bg, 0) + 1
        
        for i, (bg, count) in enumerate(sorted(bigrams.items())):
            if i >= 100:
                break
            # 使用哈希确定位置
            pos = hash(bg) % 100 + 20
            embedding[pos] = min(count / 3.0, 1.0)  # 归一化
        
        # 剩余维度：文本长度、词数等统计特征
        embedding[120] = min(len(text) / 100.0, 1.0)  # 文本长度
        embedding[121] = min(len(text.split()) / 20.0, 1.0)  # 词数
        embedding[122] = 1.0 if 'python' in text_lower else 0.0  # 是否包含 python
        embedding[123] = 1.0 if any(c in text for c in ['文件', '目录']) else 0.0  # 是否文件相关
        embedding[124] = 1.0 if any(c in text for c in ['安装', '依赖', '包']) else 0.0  # 是否安装相关
        
        # 归一化
        norm = sum(x**2 for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]
        
        return embedding
    
    def _get_experience_by_task_id(self, task_id: str) -> Optional[ExperienceRecord]:
        """从 SQLite 获取完整经验记录"""
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT * FROM task_experiences WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        # 解析字段（根据表结构）
        columns = [desc[0] for desc in cursor.description]
        row_dict = dict(zip(columns, row))
        
        return ExperienceRecord(
            task_id=row_dict["task_id"],
            task_description=row_dict["task_description"],
            task_type=row_dict["task_type"],
            success=bool(row_dict["success"]),
            output=row_dict["output"] or "",
            quality_score=row_dict["quality_score"] or 0.0,
            steps_taken=json.loads(row_dict["steps_taken"]) if row_dict["steps_taken"] else [],
            error_message=row_dict["error_message"] or "",
            duration_seconds=row_dict["duration_seconds"] or 0.0,
            tags=row_dict["tags"].split(",") if row_dict["tags"] else []
        )
    
    def _get_related_skills(self, task_description: str) -> List[Dict]:
        """获取相关技能"""
        cursor = self.db_conn.cursor()
        
        # 简单关键词匹配（实际应使用向量检索）
        keywords = task_description.lower().split()
        patterns = [f"%{kw}%" for kw in keywords if len(kw) > 2]
        
        skill_list = []
        for pattern in patterns:
            cursor.execute("""
                SELECT id, skill_name, description, trigger_pattern, action_template, usage_count, success_rate
                FROM skill_drafts
                WHERE status = 'approved' AND (
                    skill_name LIKE ? OR 
                    description LIKE ? OR
                    trigger_pattern LIKE ?
                )
                ORDER BY usage_count DESC
                LIMIT 3
            """, (pattern, pattern, pattern))
            
            for row in cursor.fetchall():
                skill_list.append({
                    "id": row[0],
                    "skill_name": row[1],
                    "description": row[2],
                    "trigger_pattern": row[3],
                    "action_template": row[4],
                    "usage_count": row[5],
                    "success_rate": row[6]
                })
        
        # 去重
        seen_ids = set()
        unique_skills = []
        for skill in skill_list:
            if skill["id"] not in seen_ids:
                seen_ids.add(skill["id"])
                unique_skills.append(skill)
        
        return unique_skills[:5]
    
    def _get_failure_cases(self, task_description: str) -> List[Dict]:
        """获取相关失败案例"""
        cursor = self.db_conn.cursor()
        
        # 关键词匹配
        keywords = [kw for kw in task_description.lower().split() if len(kw) > 2]
        
        failure_list = []
        for kw in keywords:
            cursor.execute("""
                SELECT task_id, failure_type, error_message, root_cause, solution, prevention_tips
                FROM failure_cases
                WHERE resolved = 0 AND (
                    failure_type LIKE ? OR
                    error_message LIKE ? OR
                    root_cause LIKE ?
                )
                LIMIT 3
            """, (f"%{kw}%", f"%{kw}%", f"%{kw}%"))
            
            for row in cursor.fetchall():
                failure_list.append({
                    "task_id": row[0],
                    "failure_type": row[1],
                    "error_message": row[2],
                    "root_cause": row[3],
                    "solution": row[4],
                    "prevention_tips": row[5]
                })
        
        return failure_list[:5]
    
    def _explain_relevance(self, query: str, experience_desc: str) -> str:
        """解释相关性（简单启发式）"""
        query_words = set(query.lower().split())
        exp_words = set(experience_desc.lower().split())
        
        common_words = query_words & exp_words
        if len(common_words) > 0:
            return f"共享关键词: {', '.join(list(common_words)[:3])}"
        else:
            return "向量相似度匹配"
    
    def close(self):
        """关闭数据库连接"""
        if self.db_conn:
            self.db_conn.close()


def test_experience_retrieval():
    """测试经验检索功能"""
    print("=" * 70)
    print("经验检索器测试")
    print("=" * 70)
    
    retriever = ExperienceRetriever()
    
    # 测试1：存储几条经验
    print("\n--- 测试 1: 存储经验 ---")
    
    experiences = [
        {
            "task_id": "test_001",
            "description": "列出当前目录下的所有 Python 文件",
            "type": "file_operation",
            "result": {
                "success": True,
                "output": "main.py\ntest.py\nutils.py",
                "steps": ["ls -la", "find . -name '*.py'"],
                "duration_seconds": 2.5
            },
            "score": type('MockScore', (), {
                "final_score": 0.9,
                "completeness": 0.9,
                "accuracy": 0.95,
                "efficiency": 0.85,
                "safety": 1.0
            })(),
            "tags": ["python", "file", "listing"]
        },
        {
            "task_id": "test_002",
            "description": "统计代码行数并生成报告",
            "type": "analysis",
            "result": {
                "success": True,
                "output": "Total: 1234 lines",
                "steps": ["wc -l *.py", "echo 'Report generated'"],
                "duration_seconds": 5.0
            },
            "score": type('MockScore', (), {
                "final_score": 0.85,
                "completeness": 0.8,
                "accuracy": 0.9,
                "efficiency": 0.8,
                "safety": 1.0
            })(),
            "tags": ["analysis", "statistics"]
        },
        {
            "task_id": "test_003",
            "description": "安装 Python 依赖包",
            "type": "installation",
            "result": {
                "success": False,
                "error": "Permission denied",
                "steps": ["pip install requests"],
                "duration_seconds": 10.0
            },
            "score": type('MockScore', (), {
                "final_score": 0.3,
                "completeness": 0.4,
                "accuracy": 0.3,
                "efficiency": 0.2,
                "safety": 1.0
            })(),
            "tags": ["installation", "pip"]
        }
    ]
    
    for exp in experiences:
        retriever.store_experience(
            task_id=exp["task_id"],
            task_description=exp["description"],
            task_type=exp["type"],
            result=exp["result"],
            score=exp["score"],
            tags=exp["tags"]
        )
    
    # 测试2：检索相似经验
    print("\n--- 测试 2: 检索相似经验 ---")
    
    query = "查找项目中的所有 Python 源文件"
    result = retriever.retrieve_similar(query, top_k=3, min_similarity=0.5)
    
    print(f"\n检索结果:")
    for i, exp in enumerate(result.similar_experiences, 1):
        print(f"  {i}. [{exp.similarity:.2f}] {exp.experience.task_description}")
        print(f"     成功: {exp.experience.success}, 评分: {exp.experience.quality_score:.2f}")
        print(f"     相关性: {exp.relevance_reason}")
    
    # 测试3：检索不同任务
    print("\n--- 测试 3: 检索安装类任务 ---")
    
    query2 = "如何安装新的软件包"
    result2 = retriever.retrieve_similar(query2, top_k=3, min_similarity=0.3, filter_success=False)
    
    print(f"\n检索结果:")
    for i, exp in enumerate(result2.similar_experiences, 1):
        print(f"  {i}. [{exp.similarity:.2f}] {exp.experience.task_description}")
        print(f"     成功: {exp.experience.success}, 评分: {exp.experience.quality_score:.2f}")
    
    if result2.failure_cases:
        print(f"\n  ⚠️  相关失败案例:")
        for fc in result2.failure_cases:
            print(f"     - {fc['failure_type']}: {fc['error_message']}")
    
    retriever.close()
    print("\n✅ 经验检索器测试完成")


if __name__ == "__main__":
    test_experience_retrieval()
