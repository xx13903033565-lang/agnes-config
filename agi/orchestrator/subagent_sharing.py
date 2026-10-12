#!/usr/bin/env python3
"""
AGI Orchestrator - 子代理经验共享机制

P1-8 第三件：让不同子代理之间共享执行经验，避免重复踩坑。

工作原理：
1. 子代理执行任务前，先查全局经验库（SQLite tasks.db）
2. 找到相似任务的成功记录，直接复用步骤和输出
3. 子代理执行完成后，将经验写入全局库供其他子代理使用
4. 支持跨会话、跨时间的经验复用

使用场景：
- 多个子代理处理相同类型的选品任务
- 不同时间段的相同操作（如每日数据读取）
- 相似问题的排查流程复用
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime


class SubagentExperienceSharer:
    """子代理经验共享器"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
        
        self.db_path = db_path
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """确保数据库存在且有必要的表结构"""
        if not self.db_path.exists():
            # 尝试初始化
            try:
                from ..learning.schema import init_database
                init_database(self.db_path)
            except ImportError:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.db_path))
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_experiences (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT UNIQUE NOT NULL,
                        task_description TEXT NOT NULL,
                        task_type TEXT,
                        execution_plan TEXT,
                        steps_taken TEXT,
                        success BOOLEAN NOT NULL,
                        output TEXT,
                        error_message TEXT,
                        duration_seconds REAL,
                        quality_score REAL,
                        completeness_score REAL,
                        accuracy_score REAL,
                        efficiency_score REAL,
                        safety_score REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        tags TEXT
                    )
                """)
                conn.commit()
                conn.close()
    
    def _compute_task_hash(self, task_description: str) -> str:
        """计算任务哈希"""
        normalized = task_description.strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]
    
    def search_similar_tasks(
        self, 
        task_description: str, 
        min_quality: float = 0.7,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        搜索相似任务的成功经验
        
        Args:
            task_description: 当前任务描述
            min_quality: 最低质量阈值（默认 0.7）
            limit: 返回数量限制
            
        Returns:
            相似任务列表（按质量降序）
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 模糊匹配：task_description 包含关键词
            keywords = task_description.lower().split()
            like_clauses = " OR ".join([f"task_description LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            
            cursor.execute(f"""
                SELECT task_id, task_description, steps_taken, output,
                       quality_score, duration_seconds, tags, created_at
                FROM task_experiences
                WHERE ({like_clauses}) AND success = 1 
                      AND quality_score >= ?
                ORDER BY quality_score DESC, created_at DESC
                LIMIT ?
            """, params + [min_quality, limit])
            
            rows = cursor.fetchall()
            conn.close()
            
            results = []
            for row in rows:
                results.append({
                    'task_id': row['task_id'],
                    'task_description': row['task_description'],
                    'steps_taken': json.loads(row['steps_taken']) if row['steps_taken'] else [],
                    'output': row['output'],
                    'quality_score': row['quality_score'],
                    'duration_seconds': row['duration_seconds'],
                    'tags': row['tags'].split(',') if row['tags'] else [],
                    'created_at': row['created_at']
                })
            
            return results
        
        except Exception as e:
            print(f"⚠ 相似任务搜索失败: {e}")
            return []
    
    def share_experience(
        self,
        task_description: str,
        success: bool,
        output: str = "",
        steps_taken: list = None,
        quality_score: float = None,
        duration_seconds: float = None,
        error_message: str = None,
        tags: list = None
    ) -> str:
        """
        分享子代理执行经验到全局库
        
        Args:
            task_description: 任务描述
            success: 是否成功
            output: 输出结果
            steps_taken: 执行步骤
            quality_score: 质量评分
            duration_seconds: 执行耗时
            error_message: 错误信息
            tags: 标签列表（用于分类检索）
            
        Returns:
            task_id
        """
        task_id = self._compute_task_hash(task_description)
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # 检查是否已存在
            cursor.execute("SELECT id FROM task_experiences WHERE task_id = ?", (task_id,))
            existing = cursor.fetchone()
            
            tags_str = ','.join(tags) if tags else None
            
            if existing:
                # 更新已有记录
                cursor.execute("""
                    UPDATE task_experiences
                    SET output = ?, steps_taken = ?, success = ?,
                        quality_score = ?, duration_seconds = ?,
                        error_message = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """, (
                    output,
                    json.dumps(steps_taken, ensure_ascii=False) if steps_taken else None,
                    success,
                    quality_score,
                    duration_seconds,
                    error_message,
                    tags_str,
                    task_id
                ))
            else:
                # 插入新记录
                cursor.execute("""
                    INSERT INTO task_experiences
                        (task_id, task_description, success, output, steps_taken,
                         quality_score, duration_seconds, error_message, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id,
                    task_description,
                    success,
                    output,
                    json.dumps(steps_taken, ensure_ascii=False) if steps_taken else None,
                    quality_score,
                    duration_seconds,
                    error_message,
                    tags_str
                ))
            
            conn.commit()
            conn.close()
            
            return task_id
        
        except Exception as e:
            print(f"⚠ 经验分享失败: {e}")
            return task_id
    
    def get_shared_stats(self) -> Dict[str, Any]:
        """获取全局经验库统计信息"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # 总记录数
            cursor.execute("SELECT COUNT(*) FROM task_experiences")
            total = cursor.fetchone()[0]
            
            # 成功记录数
            cursor.execute("SELECT COUNT(*) FROM task_experiences WHERE success = 1")
            success_count = cursor.fetchone()[0]
            
            # 平均质量分
            cursor.execute("SELECT AVG(quality_score) FROM task_experiences WHERE quality_score IS NOT NULL")
            avg_quality = cursor.fetchone()[0] or 0
            
            # 最近更新时间
            cursor.execute("SELECT MAX(created_at) FROM task_experiences")
            latest = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total_experiences': total,
                'successful_experiences': success_count,
                'success_rate': success_count / total if total > 0 else 0,
                'average_quality': round(avg_quality, 2),
                'latest_update': latest
            }
        
        except Exception as e:
            print(f"⚠ 统计信息查询失败: {e}")
            return {}


# 便捷函数
_default_sharer = None

def get_experience_sharer() -> SubagentExperienceSharer:
    """获取全局经验共享器实例（单例）"""
    global _default_sharer
    if _default_sharer is None:
        _default_sharer = SubagentExperienceSharer()
    return _default_sharer


def search_shared_tasks(task_description: str, **kwargs) -> List[Dict[str, Any]]:
    """搜索共享经验（便捷函数）"""
    return get_experience_sharer().search_similar_tasks(task_description, **kwargs)


def share_subagent_experience(**kwargs) -> str:
    """分享子代理经验（便捷函数）"""
    return get_experience_sharer().share_experience(**kwargs)


if __name__ == "__main__":
    # 测试共享功能
    sharer = SubagentExperienceSharer()
    
    # 模拟子代理 A 执行任务
    print("=== 子代理 A 执行选品任务 ===")
    task_a = "抖音小店近7天销量Top10家居用品选品"
    task_id_a = sharer.share_experience(
        task_description=task_a,
        success=True,
        output="Top10: 1.收纳盒(月销5万) 2.毛巾(月销3万)...",
        steps_taken=["访问抖店后台", "选择家居类目", "按7天销量排序", "提取前10"],
        quality_score=0.92,
        duration_seconds=45.2,
        tags=["选品", "抖音", "家居"]
    )
    print(f"✓ 子代理 A 分享经验: {task_id_a}")
    
    # 模拟子代理 B 执行类似任务
    print("\n=== 子代理 B 执行类似任务 ===")
    task_b = "找抖音家居用品热销榜"
    similar = sharer.search_similar_tasks(task_b, min_quality=0.8)
    
    if similar:
        print(f"✓ 找到 {len(similar)} 条相似经验:")
        for exp in similar:
            print(f"  - {exp['task_description']} (质量: {exp['quality_score']})")
            print(f"    步骤: {exp['steps_taken']}")
    else:
        print("✗ 未找到相似经验")
    
    # 查看统计
    print("\n=== 全局经验库统计 ===")
    stats = sharer.get_shared_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
