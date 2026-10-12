#!/usr/bin/env python3
"""
AgnesCode AGI Memory - 初始化脚本
Phase 1: 创建 ChromaDB 向量库和 SQLite 数据库结构
"""

import sys
import sqlite3
from pathlib import Path
from typing import Optional


def init_chromadb(memory_dir: Path):
    """初始化 ChromaDB 向量数据库"""
    try:
        import chromadb
    except ImportError:
        print("⚠️  ChromaDB 未安装，跳过向量库初始化")
        print("   安装命令: pip install chromadb")
        return False
    
    db_path = memory_dir / "chromadb"
    db_path.mkdir(parents=True, exist_ok=True)
    
    client = chromadb.PersistentClient(path=str(db_path))
    
    # 创建任务经验集合
    collection = client.get_or_create_collection(
        name="agnes_experiences",
        metadata={
            "description": "AgnesCode 任务执行经验向量存储",
            "embedding_model": "BGE-M3",
            "dimension": 1024
        }
    )
    
    print(f"✅ ChromaDB 已初始化: {db_path}")
    print(f"   集合: {collection.name}")
    print(f"   维度: 1024 (BGE-M3)")
    
    return True


def init_sqlite(memory_dir: Path):
    """初始化 SQLite 数据库"""
    db_path = memory_dir / "tasks.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    
    cursor = conn.cursor()
    
    # 创建任务执行经验表
    cursor.execute("""
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
    
    # 创建经验向量索引表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS experience_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            chroma_id TEXT,
            embedding_model TEXT DEFAULT 'BGE-M3',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES task_experiences(task_id)
        )
    """)
    
    # 创建技能草稿表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            description TEXT,
            source_task_id TEXT,
            source_experience_id INTEGER,
            trigger_pattern TEXT,
            action_template TEXT,
            parameters TEXT,
            examples TEXT,
            version INTEGER DEFAULT 1,
            refined_from INTEGER,
            refinement_reason TEXT,
            status TEXT DEFAULT 'draft',
            approval_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usage_count INTEGER DEFAULT 0,
            success_rate REAL,
            FOREIGN KEY (source_experience_id) REFERENCES task_experiences(id)
        )
    """)
    
    # 创建技能使用日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id INTEGER NOT NULL,
            task_id TEXT,
            success BOOLEAN,
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (skill_id) REFERENCES skill_drafts(id)
        )
    """)
    
    # 创建失败案例库表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS failure_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            failure_type TEXT NOT NULL,
            error_message TEXT,
            root_cause TEXT,
            solution TEXT,
            prevention_tips TEXT,
            experience_id INTEGER,
            related_skill_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (experience_id) REFERENCES task_experiences(id),
            FOREIGN KEY (related_skill_id) REFERENCES skill_drafts(id)
        )
    """)
    
    # 创建学习统计汇总表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_date DATE NOT NULL,
            total_tasks INTEGER DEFAULT 0,
            successful_tasks INTEGER DEFAULT 0,
            failed_tasks INTEGER DEFAULT 0,
            avg_quality_score REAL,
            avg_duration_seconds REAL,
            skills_created INTEGER DEFAULT 0,
            skills_used INTEGER DEFAULT 0,
            UNIQUE(stat_date)
        )
    """)
    
    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON task_experiences(task_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_success ON task_experiences(success)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_created ON task_experiences(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_status ON skill_drafts(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_failure_type ON failure_cases(failure_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stat_date ON learning_stats(stat_date)")
    
    conn.commit()
    conn.close()
    
    print(f"✅ SQLite 数据库已初始化: {db_path}")
    print(f"   表: task_experiences, experience_embeddings, skill_drafts,")
    print(f"       skill_usage_logs, failure_cases, learning_stats")
    
    return True


def create_user_preferences(memory_dir: Path):
    """创建用户偏好配置"""
    prefs_path = memory_dir / "user_preferences.json"
    
    if not prefs_path.exists():
        import json
        
        default_prefs = {
            "version": "1.0",
            "autonomous_mode": False,
            "max_autonomous_steps": 10,
            "require_approval_for": [
                "write_operations",
                "network_requests",
                "skill_installation"
            ],
            "preferred_models": {
                "code": "deepseek-v3",
                "chat": "gpt-4o",
                "vision": "gemini-2.0-flash"
            },
            "cost_budget_per_day": 10.0,
            "quality_threshold": 0.8
        }
        
        with open(prefs_path, 'w', encoding='utf-8') as f:
            json.dump(default_prefs, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 用户偏好配置已创建: {prefs_path}")
    
    return True


def init_memory(memory_dir: Optional[Path] = None):
    """
    初始化完整的 Memory 系统
    
    Args:
        memory_dir: Memory 目录路径，默认为 ~/.agnes/memory
        
    Returns:
        bool: 是否成功
    """
    if memory_dir is None:
        memory_dir = Path.home() / '.agnes' / 'memory'
    
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("AgnesCode AGI Memory 系统初始化")
    print("=" * 70)
    
    success = True
    
    # 步骤1: 初始化 ChromaDB
    print("\n📦 步骤 1/3: 初始化 ChromaDB 向量库...")
    if not init_chromadb(memory_dir):
        print("⚠️  ChromaDB 初始化跳过（可选组件）")
    
    # 步骤2: 初始化 SQLite
    print("\n📦 步骤 2/3: 初始化 SQLite 数据库...")
    if not init_sqlite(memory_dir):
        print("❌ SQLite 初始化失败")
        success = False
    
    # 步骤3: 创建用户偏好
    print("\n📦 步骤 3/3: 创建用户偏好配置...")
    create_user_preferences(memory_dir)
    
    print("\n" + "=" * 70)
    if success:
        print("✅ Memory 系统初始化完成")
    else:
        print("❌ Memory 系统初始化部分失败")
    print("=" * 70)
    
    return success


def ensure_memory_initialized(db_path: Optional[Path] = None):
    """
    确保 Memory 系统已初始化（幂等操作）
    
    Args:
        db_path: 数据库文件路径，默认为 ~/.agnes/memory/tasks.db
    """
    if db_path is None:
        db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
    
    # 如果数据库文件不存在，运行完整初始化
    if not db_path.exists():
        memory_dir = db_path.parent
        init_memory(memory_dir)
        return
    
    # 如果数据库存在但表可能不完整，检查并创建缺失的表
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 检查关键表是否存在
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN (
            'task_experiences', 
            'experience_embeddings',
            'skill_drafts',
            'skill_usage_logs',
            'failure_cases',
            'learning_stats'
        )
    """)
    
    existing_tables = {row[0] for row in cursor.fetchall()}
    required_tables = {
        'task_experiences',
        'experience_embeddings', 
        'skill_drafts',
        'skill_usage_logs',
        'failure_cases',
        'learning_stats'
    }
    
    missing_tables = required_tables - existing_tables
    
    if missing_tables:
        print(f"⚠️  检测到缺失的表: {missing_tables}，正在创建...")
        conn.close()
        
        # 重新运行 SQLite 初始化（会创建缺失的表）
        memory_dir = db_path.parent
        init_sqlite(memory_dir)
    else:
        conn.close()


if __name__ == "__main__":
    success = init_memory()
    sys.exit(0 if success else 1)
