#!/usr/bin/env python3
"""
AgnesCode AGI Learning - 数据库 Schema 定义
Phase 4.1: 经验存储结构设计
"""

import sqlite3
from pathlib import Path
from typing import Optional


# 数据库版本
DB_VERSION = "1.0"


def create_tables(conn: sqlite3.Connection):
    """创建所有数据表"""
    cursor = conn.cursor()
    
    # 1. 任务执行经验表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,           -- 任务唯一标识
            task_description TEXT NOT NULL,          -- 任务描述
            task_type TEXT,                          -- 任务类型（file_operation, installation, analysis, etc.）
            
            -- 执行过程
            execution_plan TEXT,                     -- 执行计划（JSON）
            steps_taken TEXT,                        -- 实际执行的步骤（JSON数组）
            
            -- 结果信息
            success BOOLEAN NOT NULL,                -- 是否成功
            output TEXT,                             -- 输出结果
            error_message TEXT,                      -- 错误信息（如果失败）
            duration_seconds REAL,                   -- 执行耗时（秒）
            
            -- 质量评估
            quality_score REAL,                      -- 综合评分（0-1）
            completeness_score REAL,                 -- 完整性评分
            accuracy_score REAL,                     -- 准确性评分
            efficiency_score REAL,                   -- 效率评分
            safety_score REAL,                       -- 安全性评分
            
            -- 元数据
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tags TEXT                                -- 标签（逗号分隔）
        )
    """)
    
    # 2. 经验向量索引表（与 ChromaDB 关联）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS experience_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,            -- 关联 task_experiences.task_id
            chroma_id TEXT,                          -- ChromaDB 中的文档ID
            embedding_model TEXT DEFAULT 'BGE-M3',   -- 使用的嵌入模型
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES task_experiences(task_id)
        )
    """)
    
    # 3. 技能草稿表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,                -- 技能名称
            description TEXT,                        -- 技能描述
            source_task_id TEXT,                     -- 来源任务ID
            source_experience_id INTEGER,            -- 来源经验ID
            
            -- 技能内容
            trigger_pattern TEXT,                    -- 触发模式（关键词/正则）
            action_template TEXT,                    -- 行动模板
            parameters TEXT,                         -- 参数定义（JSON）
            examples TEXT,                           -- 使用示例（JSON数组）
            
            -- 演化信息
            version INTEGER DEFAULT 1,               -- 版本号
            refined_from INTEGER,                    -- 从哪个技能演化而来（自引用）
            refinement_reason TEXT,                  -- 演化原因
            
            -- 状态
            status TEXT DEFAULT 'draft',             -- 状态：draft, approved, deprecated
            approval_note TEXT,                      -- 审批备注
            
            -- 元数据
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usage_count INTEGER DEFAULT 0,           -- 使用次数
            success_rate REAL,                       -- 成功率
            
            FOREIGN KEY (source_experience_id) REFERENCES task_experiences(id)
        )
    """)
    
    # 4. 技能使用日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id INTEGER NOT NULL,               -- 关联 skill_drafts.id
            task_id TEXT,                            -- 使用该技能的任务ID
            success BOOLEAN,                         -- 是否成功
            feedback TEXT,                           -- 用户反馈
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (skill_id) REFERENCES skill_drafts(id)
        )
    """)
    
    # 5. 失败案例库表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS failure_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,            -- 关联 task_experiences.task_id
            failure_type TEXT NOT NULL,              -- 失败类型（permission_error, timeout, invalid_input, etc.）
            error_message TEXT,                      -- 错误信息
            root_cause TEXT,                         -- 根因分析
            solution TEXT,                           -- 解决方案（如果已解决）
            prevention_tips TEXT,                    -- 预防建议
            
            -- 关联经验
            experience_id INTEGER,                   -- 关联的經驗ID
            related_skill_id INTEGER,                -- 相关技能ID
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved BOOLEAN DEFAULT FALSE,          -- 是否已解决
            
            FOREIGN KEY (experience_id) REFERENCES task_experiences(id),
            FOREIGN KEY (related_skill_id) REFERENCES skill_drafts(id)
        )
    """)
    
    # 6. 学习统计汇总表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_date DATE NOT NULL,                 -- 统计日期
            total_tasks INTEGER DEFAULT 0,           -- 总任务数
            successful_tasks INTEGER DEFAULT 0,      -- 成功任务数
            failed_tasks INTEGER DEFAULT 0,          -- 失败任务数
            avg_quality_score REAL,                  -- 平均质量评分
            avg_duration_seconds REAL,               -- 平均执行时间
            skills_created INTEGER DEFAULT 0,        -- 新增技能数
            skills_used INTEGER DEFAULT 0,           -- 技能使用次数
            
            UNIQUE(stat_date)
        )
    """)
    
    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON task_experiences(task_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_success ON task_experiences(success)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_created ON task_experiences(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_status ON skill_drafts(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_trigger ON skill_drafts(trigger_pattern)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_failure_type ON failure_cases(failure_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stat_date ON learning_stats(stat_date)")
    
    conn.commit()
    print("✅ 数据库表创建完成")


def init_database(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    初始化数据库
    
    Args:
        db_path: 数据库文件路径，默认为 ~/.agnes/memory/tasks.db
        
    Returns:
        SQLite 连接对象
    """
    if db_path is None:
        db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
    
    # 确保目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 连接数据库
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发性能
    conn.execute("PRAGMA foreign_keys=ON")   # 启用外键约束
    
    # 创建表
    create_tables(conn)
    
    print(f"📦 数据库已初始化: {db_path}")
    return conn


if __name__ == "__main__":
    # 测试数据库初始化
    conn = init_database()
    
    # 验证表创建
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"\n已创建的表: {', '.join(tables)}")
    
    expected_tables = [
        'task_experiences',
        'experience_embeddings',
        'skill_drafts',
        'skill_usage_logs',
        'failure_cases',
        'learning_stats'
    ]
    
    missing = set(expected_tables) - set(tables)
    if missing:
        print(f"❌ 缺少表: {missing}")
    else:
        print("✅ 所有表创建成功")
    
    conn.close()
