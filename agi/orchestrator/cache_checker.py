#!/usr/bin/env python3
"""
AGI Orchestrator - 经验缓存检查器
B15: 连跑同样指令时，第2、3次命中缓存不走LLM

工作原理：
1. 任务描述哈希化作为 task_id
2. 查 SQLite task_experiences 表找相同 task_description 且 success=true 的记录
3. 找到则直接返回缓存结果（output + steps_taken），跳过 LLM 调用
4. 未找到则正常走 LLM，完成后由调用方写入缓存
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any


class ExperienceCacheChecker:
    """经验缓存检查器"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
        
        self.db_path = db_path
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """确保数据库文件存在"""
        if not self.db_path.exists():
            # 如果数据库不存在，尝试初始化
            try:
                from ..learning.schema import init_database
                init_database(self.db_path)
            except ImportError:
                # learning 模块不可用时，创建空数据库
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
        """计算任务描述的哈希值作为 task_id"""
        # 归一化：去首尾空格、转小写
        normalized = task_description.strip().lower()
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]
    
    def check_cache(self, task_description: str) -> Optional[Dict[str, Any]]:
        """
        检查缓存中是否有相同任务的成功执行记录
        
        Args:
            task_description: 任务描述
            
        Returns:
            如果找到缓存则返回 {task_id, output, steps_taken, quality_score}，否则返回 None
        """
        task_id = self._compute_task_hash(task_description)
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 查找相同 task_description 且 success=true 的最新记录
            cursor.execute("""
                SELECT task_id, task_description, output, steps_taken, 
                       quality_score, duration_seconds, created_at
                FROM task_experiences
                WHERE task_description = ? AND success = 1
                ORDER BY created_at DESC
                LIMIT 1
            """, (task_description,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'hit': True,
                    'task_id': row['task_id'],
                    'output': row['output'],
                    'steps_taken': json.loads(row['steps_taken']) if row['steps_taken'] else [],
                    'quality_score': row['quality_score'],
                    'duration_seconds': row['duration_seconds'],
                    'cached_at': row['created_at']
                }
            
            return None
            
        except Exception as e:
            # 数据库查询失败时不阻断主流程，返回 None 让任务正常走 LLM
            print(f"⚠ 经验缓存查询失败: {e}")
            return None
    
    def save_experience(
        self,
        task_description: str,
        success: bool,
        output: str = "",
        steps_taken: list = None,
        quality_score: float = None,
        duration_seconds: float = None,
        error_message: str = None
    ) -> str:
        """
        保存任务执行经验到缓存
        
        Args:
            task_description: 任务描述
            success: 是否成功
            output: 输出结果
            steps_taken: 执行的步骤列表
            quality_score: 质量评分
            duration_seconds: 执行耗时
            error_message: 错误信息（失败时）
            
        Returns:
            task_id
        """
        task_id = self._compute_task_hash(task_description)
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # 检查是否已存在相同 task_id 的记录（更新而非插入）
            cursor.execute("SELECT id FROM task_experiences WHERE task_id = ?", (task_id,))
            existing = cursor.fetchone()
            
            if existing:
                # 更新已有记录
                cursor.execute("""
                    UPDATE task_experiences
                    SET output = ?, steps_taken = ?, success = ?,
                        quality_score = ?, duration_seconds = ?,
                        error_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """, (
                    output,
                    json.dumps(steps_taken, ensure_ascii=False) if steps_taken else None,
                    success,
                    quality_score,
                    duration_seconds,
                    error_message,
                    task_id
                ))
            else:
                # 插入新记录
                cursor.execute("""
                    INSERT INTO task_experiences
                        (task_id, task_description, success, output, steps_taken,
                         quality_score, duration_seconds, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_id,
                    task_description,
                    success,
                    output,
                    json.dumps(steps_taken, ensure_ascii=False) if steps_taken else None,
                    quality_score,
                    duration_seconds,
                    error_message
                ))
            
            conn.commit()
            conn.close()
            
            return task_id
            
        except Exception as e:
            print(f"⚠ 经验缓存保存失败: {e}")
            return task_id


# 便捷函数
_default_checker = None

def get_cache_checker() -> ExperienceCacheChecker:
    """获取全局缓存检查器实例（单例）"""
    global _default_checker
    if _default_checker is None:
        _default_checker = ExperienceCacheChecker()
    return _default_checker


def check_task_cache(task_description: str) -> Optional[Dict[str, Any]]:
    """检查任务缓存（便捷函数）"""
    return get_cache_checker().check_cache(task_description)


def save_task_experience(**kwargs) -> str:
    """保存任务经验（便捷函数）"""
    return get_cache_checker().save_experience(**kwargs)


if __name__ == "__main__":
    # 测试缓存功能
    checker = ExperienceCacheChecker()
    
    test_desc = "选品：找抖音小店近7天销量Top10的家居用品"
    
    # 第一次：应该没有缓存
    result = checker.check_cache(test_desc)
    print(f"第一次查询: {'命中' if result else '未命中'}")
    
    # 模拟保存经验
    task_id = checker.save_experience(
        task_description=test_desc,
        success=True,
        output="Top10: 1.收纳盒 2.毛巾...",
        steps_taken=["搜索商品", "按销量排序", "提取前10"],
        quality_score=0.85,
        duration_seconds=12.5
    )
    print(f"已保存经验: task_id={task_id}")
    
    # 第二次：应该命中缓存
    result = checker.check_cache(test_desc)
    print(f"第二次查询: {'命中' if result else '未命中'}")
    if result:
        print(f"  缓存输出: {result['output'][:50]}...")
        print(f"  质量评分: {result['quality_score']}")
        print(f"  缓存时间: {result['cached_at']}")
