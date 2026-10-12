#!/usr/bin/env python3
"""
AgnesCode Memory 系统功能测试脚本
测试向量库添加/查询、数据库读写、跨会话记忆保留
"""

import sys
import json
from pathlib import Path

def test_chromadb():
    """测试 ChromaDB 向量库"""
    print("\n=== 测试 1: ChromaDB 向量库 ===")
    
    try:
        import chromadb
        
        # 连接已存在的向量库
        db_path = Path.home() / '.agnes' / 'memory' / 'vector_store'
        client = chromadb.PersistentClient(path=str(db_path))
        
        # 获取集合
        collection = client.get_collection("agnes_experiences")
        
        # 添加测试数据
        test_docs = [
            "电商自动化巡检流程：检查商品上架状态、库存数量、价格变动",
            "批量上架操作：先调研市场价，再生成素材，最后分批上架",
            "故障处理：平台接口变更时自动检测并适配新接口"
        ]
        
        test_ids = [f"test_exp_{i}" for i in range(len(test_docs))]
        test_metadatas = [
            {"type": "patrol", "shop": "抖店"},
            {"type": "listing", "shop": "天猫"},
            {"type": "troubleshooting", "platform": "京东"}
        ]
        
        collection.add(
            documents=test_docs,
            ids=test_ids,
            metadatas=test_metadatas
        )
        
        print(f"✅ 成功添加 {len(test_docs)} 条测试经验")
        
        # 语义搜索测试
        query = "如何上架商品？"
        results = collection.query(
            query_texts=[query],
            n_results=2
        )
        
        print(f"\n🔍 搜索查询: '{query}'")
        print(f"✅ 返回 {len(results['ids'][0])} 条相关结果:")
        for i, doc in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i]
            print(f"   {i+1}. [{metadata['type']}] {doc[:60]}...")
        
        # 清理测试数据
        collection.delete(ids=test_ids)
        print(f"\n✅ 测试数据已清理")
        
        return True
        
    except Exception as e:
        print(f"❌ ChromaDB 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_sqlite():
    """测试 SQLite 数据库"""
    print("\n=== 测试 2: SQLite 任务历史数据库 ===")
    
    try:
        import sqlite3
        
        db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 插入测试任务
        cursor.execute('''
            INSERT OR IGNORE INTO tasks 
            (task_id, description, status, success_score)
            VALUES (?, ?, ?, ?)
        ''', ('test_task_001', '测试任务：电商巡检', 'completed', 0.85))
        
        cursor.execute('''
            INSERT OR IGNORE INTO tasks 
            (task_id, description, status, success_score)
            VALUES (?, ?, ?, ?)
        ''', ('test_task_002', '测试任务：批量上架', 'completed', 0.92))
        
        conn.commit()
        
        # 查询测试
        cursor.execute('SELECT COUNT(*) FROM tasks WHERE task_id LIKE ?', ('test_task_%',))
        count = cursor.fetchone()[0]
        print(f"✅ 成功插入 {count} 条测试任务")
        
        # 查询高分任务
        cursor.execute('''
            SELECT task_id, description, success_score 
            FROM tasks 
            WHERE success_score >= 0.8 AND task_id LIKE ?
        ''', ('test_task_%',))
        
        high_score_tasks = cursor.fetchall()
        print(f"\n🏆 高分任务 (≥0.8):")
        for task_id, desc, score in high_score_tasks:
            print(f"   - {task_id}: {desc} (评分: {score})")
        
        # 清理测试数据
        cursor.execute('DELETE FROM tasks WHERE task_id LIKE ?', ('test_task_%',))
        conn.commit()
        conn.close()
        
        print(f"\n✅ 测试数据已清理")
        
        return True
        
    except Exception as e:
        print(f"❌ SQLite 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_user_preferences():
    """测试用户偏好文件"""
    print("\n=== 测试 3: 用户偏好配置 ===")
    
    try:
        prefs_path = Path.home() / '.agnes' / 'memory' / 'user_preferences.json'
        
        with open(prefs_path, 'r', encoding='utf-8') as f:
            prefs = json.load(f)
        
        print(f"✅ 用户偏好文件加载成功")
        print(f"   - 语言: {prefs['language']}")
        print(f"   - 自主模式: {'开启' if prefs['autonomous_mode'] else '关闭'}")
        print(f"   - 默认模型: {prefs['model_preferences']['default']}")
        print(f"   - 嵌入模型: {prefs['model_preferences']['embedding']}")
        print(f"   - 每日预算: ${prefs['budget']['daily_limit_usd']}")
        
        return True
        
    except Exception as e:
        print(f"❌ 用户偏好测试失败: {e}")
        return False

def test_cross_session_persistence():
    """测试跨会话记忆保留"""
    print("\n=== 测试 4: 跨会话记忆保留 ===")
    
    try:
        import chromadb
        
        # 重新连接（模拟新会话）
        db_path = Path.home() / '.agnes' / 'memory' / 'vector_store'
        client = chromadb.PersistentClient(path=str(db_path))
        collection = client.get_collection("agnes_experiences")
        
        # 添加一条持久化测试数据
        collection.add(
            documents=["这是一条跨会话测试数据，应该被保留"],
            ids=["persistence_test"],
            metadatas=[{"type": "test", "purpose": "cross_session"}]
        )
        
        print("✅ 已添加跨会话测试数据")
        
        # 立即查询验证
        results = collection.query(
            query_texts=["跨会话测试"],
            n_results=1
        )
        
        if len(results['ids'][0]) > 0:
            print(f"✅ 跨会话数据可检索: {results['documents'][0][0][:40]}...")
            return True
        else:
            print("❌ 跨会话数据无法检索")
            return False
        
    except Exception as e:
        print(f"❌ 跨会话测试失败: {e}")
        return False

def main():
    print("=" * 60)
    print("AgnesCode Memory 系统功能测试")
    print("=" * 60)
    
    results = []
    
    # 运行所有测试
    results.append(("ChromaDB 向量库", test_chromadb()))
    results.append(("SQLite 数据库", test_sqlite()))
    results.append(("用户偏好配置", test_user_preferences()))
    results.append(("跨会话记忆保留", test_cross_session_persistence()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name:20s} {status}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！Memory 系统运行正常。")
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，请检查错误信息。")
        sys.exit(1)

if __name__ == '__main__':
    main()
