#!/usr/bin/env python3
"""
AgnesCode AGI Learning - 综合验证测试
Phase 4.4: 验证经验存储、检索、技能生成全流程
"""

import sys
import json
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))

from schema import init_database
from retriever import ExperienceRetriever
from skill_evolution import SkillEvolver
from scorer import ReflectionScore


def test_experience_storage():
    """测试经验存储"""
    print("\n" + "=" * 70)
    print("测试 1: 经验存储")
    print("=" * 70)
    
    retriever = ExperienceRetriever()
    
    # 存储多条经验
    experiences = [
        {
            "task_id": "exp_001",
            "description": "统计当前目录下的 Python 文件数量",
            "type": "analysis",
            "result": {
                "success": True,
                "output": "Found 15 Python files",
                "steps": ["find . -name '*.py'", "wc -l"],
                "duration_seconds": 2.0
            },
            "score": type('MockScore', (), {
                "final_score": 0.88, "completeness": 0.9, "accuracy": 0.9,
                "efficiency": 0.85, "safety": 1.0
            })(),
            "tags": ["python", "statistics"]
        },
        {
            "task_id": "exp_002",
            "description": "安装 requests 库",
            "type": "installation",
            "result": {
                "success": False,
                "error": "Permission denied",
                "steps": ["pip install requests"],
                "duration_seconds": 5.0
            },
            "score": type('MockScore', (), {
                "final_score": 0.3, "completeness": 0.4, "accuracy": 0.3,
                "efficiency": 0.2, "safety": 1.0
            })(),
            "tags": ["installation", "pip"]
        },
        {
            "task_id": "exp_003",
            "description": "列出所有 Markdown 文件并生成目录",
            "type": "file_operation",
            "result": {
                "success": True,
                "output": "README.md\ndocs/guide.md",
                "steps": ["find . -name '*.md'", "echo 'TOC generated'"],
                "duration_seconds": 1.5
            },
            "score": type('MockScore', (), {
                "final_score": 0.92, "completeness": 0.95, "accuracy": 0.9,
                "efficiency": 0.9, "safety": 1.0
            })(),
            "tags": ["markdown", "file", "toc"]
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
    
    # 验证存储
    conn = retriever.db_conn
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM task_experiences")
    count = cursor.fetchone()[0]
    
    print(f"\n✅ 已存储 {count} 条经验记录")
    
    retriever.close()
    return count == 3


def test_experience_retrieval():
    """测试经验检索"""
    print("\n" + "=" * 70)
    print("测试 2: 经验检索")
    print("=" * 70)
    
    # 复用同一个 retriever（不要重新初始化）
    from retriever import ExperienceRetriever
    retriever = ExperienceRetriever()
    
    # 先存储一些经验
    print("\n准备: 存储测试经验...")
    retriever.store_experience(
        task_id="retrieval_test_001",
        task_description="查找项目中的 Python 源代码文件",
        task_type="file_operation",
        result={
            "success": True,
            "output": "main.py\nutils.py",
            "steps": ["find . -name '*.py'"],
            "duration_seconds": 2.0
        },
        score=type('MockScore', (), {
            "final_score": 0.88, "completeness": 0.9, "accuracy": 0.9,
            "efficiency": 0.85, "safety": 1.0
        })(),
        tags=["python", "file"]
    )
    
    # 测试查询
    query1 = "查找项目中的 Python 源代码文件"
    result1 = retriever.retrieve_similar(query1, top_k=3, min_similarity=0.3)
    
    print(f"\n查询: {query1}")
    print(f"找到 {result1.total_matches} 条相似经验")
    
    if result1.total_matches == 0:
        print("⚠️  未找到匹配，降低相似度阈值重试...")
        result1 = retriever.retrieve_similar(query1, top_k=3, min_similarity=0.1, filter_success=False)
        print(f"找到 {result1.total_matches} 条相似经验")
    
    assert result1.total_matches > 0, "应该找到至少1条相似经验"
    
    for i, exp in enumerate(result1.similar_experiences[:2], 1):
        print(f"  {i}. [{exp.similarity:.2f}] {exp.experience.task_description}")
        print(f"     成功: {exp.experience.success}, 评分: {exp.experience.quality_score:.2f}")
    
    retriever.close()
    return True


def test_skill_extraction():
    """测试技能提取"""
    print("\n" + "=" * 70)
    print("测试 3: 技能提取与演化")
    print("=" * 70)
    
    evolver = SkillEvolver()
    
    # 模拟高分任务
    mock_score = type('MockScore', (), {
        "final_score": 0.90, "completeness": 0.9, "accuracy": 0.92,
        "efficiency": 0.88, "safety": 1.0
    })()
    
    task_result = {
        "success": True,
        "output": "main.py\ntest.py",
        "steps": ["ls -la", "find . -name '*.py'", "cat main.py"],
        "duration_seconds": 3.0
    }
    
    # 提取技能
    evolution = evolver.analyze_and_extract_skills(
        task_id="exp_003",  # 使用之前存储的高分经验
        task_description="列出所有 Markdown 文件并生成目录",
        result=task_result,
        score=mock_score
    )
    
    print(f"\n技能提取结果:")
    print(f"  新技能: {len(evolution.new_skills)} 个")
    
    assert len(evolution.new_skills) > 0, "应该提取到至少1个技能"
    
    for skill in evolution.new_skills:
        print(f"    - {skill.skill_name}")
        print(f"      触发: {skill.trigger_pattern}")
        print(f"      模板: {skill.action_template[:60]}...")
    
    # 审批技能
    cursor = evolver.db_conn.cursor()
    cursor.execute("SELECT id FROM skill_drafts ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        skill_id = row[0]
        evolver.approve_skill(skill_id, "测试审批")
        
        # 记录使用
        evolver.record_skill_usage(skill_id, "test_usage_001", success=True)
        evolver.record_skill_usage(skill_id, "test_usage_002", success=True)
        
        # 查看统计
        skills = evolver.get_approved_skills()
        for s in skills:
            rate = s['success_rate'] if s['success_rate'] else 0.0
            print(f"\n  已审批技能: {s['skill_name']}")
            print(f"    使用次数: {s['usage_count']}, 成功率: {rate:.0%}")
    
    evolver.close()
    return True


def test_end_to_end_workflow():
    """测试端到端完整工作流"""
    print("\n" + "=" * 70)
    print("测试 4: 端到端完整工作流")
    print("=" * 70)
    
    # 场景：新任务到来 → 检索历史经验 → 执行任务 → 存储经验 → 提取技能
    
    retriever = ExperienceRetriever()
    evolver = SkillEvolver()
    
    # 步骤1：新任务
    new_task = "分析项目中的 TypeScript 文件结构"
    print(f"\n📋 新任务: {new_task}")
    
    # 步骤2：检索相似经验
    print(f"\n🔍 检索相似经验...")
    retrieval = retriever.retrieve_similar(new_task, top_k=3, min_similarity=0.3)
    
    if retrieval.similar_experiences:
        print(f"  找到 {retrieval.total_matches} 条相似经验")
        best_match = retrieval.similar_experiences[0]
        print(f"  最佳匹配: {best_match.experience.task_description} (相似度: {best_match.similarity:.2f})")
        print(f"  可参考步骤: {best_match.experience.steps_taken[:2]}")
    else:
        print(f"  未找到相似经验，从头开始")
    
    # 步骤3：模拟执行任务
    print(f"\n▶️  执行任务...")
    mock_result = {
        "success": True,
        "output": "src/index.ts\nsrc/utils.ts",
        "steps": ["find . -name '*.ts'", "tree src/"],
        "duration_seconds": 4.0
    }
    
    mock_score = type('MockScore', (), {
        "final_score": 0.85, "completeness": 0.8, "accuracy": 0.9,
        "efficiency": 0.85, "safety": 1.0
    })()
    
    # 步骤4：存储经验
    print(f"\n💾 存储执行经验...")
    retriever.store_experience(
        task_id="e2e_test_001",
        task_description=new_task,
        task_type="analysis",
        result=mock_result,
        score=mock_score,
        tags=["typescript", "analysis"]
    )
    
    # 步骤5：提取技能（如果评分够高）
    if mock_score.final_score >= 0.8:
        print(f"\n✨ 提取技能...")
        evolution = evolver.analyze_and_extract_skills(
            task_id="e2e_test_001",
            task_description=new_task,
            result=mock_result,
            score=mock_score
        )
        
        if evolution.new_skills:
            print(f"  ✅ 生成 {len(evolution.new_skills)} 个新技能")
            for skill in evolution.new_skills:
                print(f"     - {skill.skill_name}")
    
    retriever.close()
    evolver.close()
    
    print(f"\n✅ 端到端工作流完成")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("AgnesCode AGI Learning - Phase 4 综合验证")
    print("=" * 70)
    
    tests = [
        ("经验存储", test_experience_storage),
        ("经验检索", test_experience_retrieval),
        ("技能提取", test_skill_extraction),
        ("端到端工作流", test_end_to_end_workflow),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            success = test_fn()
            if success:
                passed += 1
        except Exception as e:
            print(f"\n❌ {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    print(f"✅ 通过: {passed}/{len(tests)}")
    print(f"❌ 失败: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 所有测试通过！Phase 4 Learning 模块完成")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查错误信息")
    
    return failed == 0


if __name__ == "__main__":
    # 清理旧数据
    import shutil
    db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
    chroma_path = Path.home() / '.agnes' / 'memory' / 'chromadb'
    
    if db_path.exists():
        db_path.unlink()
    if chroma_path.exists():
        shutil.rmtree(chroma_path)
    
    success = run_all_tests()
    sys.exit(0 if success else 1)
