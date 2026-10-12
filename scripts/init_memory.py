#!/usr/bin/env python3
"""
AgnesCode AGI Memory 系统初始化脚本
Phase 1: 创建 ChromaDB 向量库、SQLite 数据库、用户偏好配置
"""

import os
import sys
import json
import sqlite3
from pathlib import Path

def check_dependencies():
    """检查必要依赖"""
    required_packages = ['chromadb']
    missing = []
    
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    if missing:
        print(f"❌ 缺少依赖包: {', '.join(missing)}")
        print(f"请运行: pip install {' '.join(missing)}")
        return False
    
    print("✅ 依赖检查通过")
    return True

def create_directory_structure():
    """创建目录结构"""
    base_dir = Path.home() / '.agnes' / 'memory'
    dirs = [
        base_dir,
        base_dir / 'vector_store',
        base_dir / 'vector_store' / 'data',
        base_dir / 'skills_learned',
    ]
    
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"✅ 创建目录: {d}")
    
    return base_dir

def init_chromadb(memory_dir):
    """初始化 ChromaDB 向量库"""
    try:
        import chromadb
        
        db_path = memory_dir / 'vector_store'
        client = chromadb.PersistentClient(path=str(db_path))
        
        # 创建经验集合
        collection = client.get_or_create_collection(
            name="agnes_experiences",
            metadata={
                "description": "AgnesCode 任务执行经验向量存储",
                "embedding_model": "BGE-M3",
                "dimension": 1024
            }
        )
        
        # 创建任务历史集合
        task_collection = client.get_or_create_collection(
            name="agnes_task_history",
            metadata={
                "description": "AgnesCode 任务执行历史记录",
                "embedding_model": "BGE-M3",
                "dimension": 1024
            }
        )
        
        print(f"✅ ChromaDB 初始化完成: {db_path}")
        print(f"✅ 创建集合: agnes_experiences")
        print(f"✅ 创建集合: agnes_task_history")
        
        return True
    except Exception as e:
        print(f"❌ ChromaDB 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_sqlite_database(memory_dir):
    """创建 SQLite 任务历史数据库"""
    db_path = memory_dir / 'tasks.db'
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 创建任务表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            description TEXT,
            status TEXT CHECK(status IN ('pending', 'running', 'completed', 'failed')),
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_seconds REAL,
            tools_used TEXT,
            success_score REAL,
            reflection_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_id ON tasks(task_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)')
    
    # 创建经验表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS experiences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            pattern_name TEXT,
            success_count INTEGER DEFAULT 1,
            tools_sequence TEXT,
            parameters TEXT,
            pitfalls TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    ''')
    
    # 创建技能草稿表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skill_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT UNIQUE NOT NULL,
            description TEXT,
            yaml_content TEXT,
            status TEXT CHECK(status IN ('draft', 'reviewing', 'approved', 'rejected')),
            source_tasks TEXT,
            review_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    
    print(f"✅ SQLite 数据库创建完成: {db_path}")
    return True

def create_user_preferences(memory_dir):
    """创建用户偏好文件"""
    prefs_path = memory_dir / 'user_preferences.json'
    
    if not prefs_path.exists():
        preferences = {
            "version": "1.0",
            "language": "zh-CN",
            "autonomous_mode": False,
            "max_autonomous_steps": 10,
            "require_approval_for": [
                "write_operations",
                "network_requests",
                "skill_installation"
            ],
            "model_preferences": {
                "default": "agnes-3.0-flash",
                "planning": "agnes-2.5-pro",
                "reflection": "agnes-2.5-pro",
                "embedding": "BGE-M3"
            },
            "budget": {
                "daily_limit_usd": 5.0,
                "alert_at_percent": 80
            },
            "learning": {
                "auto_extract_patterns": True,
                "min_success_count_before_publish": 5,
                "review_before_publish": True
            },
            "memory": {
                "retention_days": 90,
                "max_vector_entries": 100000,
                "similarity_threshold": 0.7
            }
        }
        
        with open(prefs_path, 'w', encoding='utf-8') as f:
            json.dump(preferences, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 用户偏好文件创建: {prefs_path}")
    else:
        print(f"ℹ️  用户偏好文件已存在: {prefs_path}")

def update_main_config():
    """更新主配置文件——只出报告，⛔裸写正本（config.yaml 的写入必须走 agnes_config_guard.py）。"""
    config_path = Path.home() / '.agnes' / 'config' / 'config.yaml'

    if not config_path.exists():
        print("❌ 配置文件不存在: %s" % config_path)
        return False

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'agi_core:' in content:
        print("ℹ️  AGI 配置已存在，跳过")
        return True

    print("✅ 检测到 config.yaml 里尚无 agi_core 块；要加这块请走：")
    print("   python3 ~/.agnes/scripts/agnes_config_guard.py --write-from <含 agi_core 块的候选文件>")
    return True

def main():
    print("=" * 60)
    print("AgnesCode AGI Memory 系统初始化")
    print("Phase 1: 记忆系统搭建")
    print("=" * 60)
    print()
    
    # 1. 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 2. 创建目录结构
    print("\n📁 创建目录结构...")
    memory_dir = create_directory_structure()
    
    # 3. 初始化 ChromaDB
    print("\n🗄️  初始化向量数据库...")
    if not init_chromadb(memory_dir):
        print("⚠️  ChromaDB 初始化失败")
        sys.exit(1)
    
    # 4. 创建 SQLite 数据库
    print("\n💾 创建任务历史数据库...")
    create_sqlite_database(memory_dir)
    
    # 5. 创建用户偏好文件
    print("\n⚙️  创建用户偏好配置...")
    create_user_preferences(memory_dir)
    
    # 6. 更新主配置
    print("\n📝 更新主配置文件...")
    update_main_config()
    
    print("\n" + "=" * 60)
    print("✅ AGI Memory 初始化完成！")
    print("=" * 60)
    print()
    print("下一步:")
    print("1. 重启 AgnesCode 使配置生效")
    print("2. 测试语义检索功能")
    print("3. 开始 Phase 2: 反思器集成")
    print()

if __name__ == '__main__':
    main()
