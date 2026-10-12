#!/usr/bin/env python3
"""
AGI Orchestrator - 主模块

整合 P1-8 三件武装：
1. Memory（ChromaDB + SQLite tasks.db）
2. Reflection（自动评分 + 低分重试）
3. Subagent Sharing（跨代理经验共享）

使用方式：
    from agi.orchestrator import run_task_with_agility
    
    result = run_task_with_agility(
        task_description="选品：找抖音小店近7天销量Top10的家居用品",
        execute_fn=my_execution_function
    )
"""

from .cache_checker import ExperienceCacheChecker, check_task_cache, save_task_experience
from .subagent_sharing import SubagentExperienceSharer, search_shared_tasks, share_subagent_experience

# 导入反射器
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))
from reflector import ReflectionEngine


def run_task_with_agility(
    task_description: str,
    execute_fn,
    task_metadata: dict = None,
    enable_reflection: bool = True,
    enable_sharing: bool = True,
    max_retries: int = 3
) -> dict:
    """
    带 AGI 敏捷能力的任务执行器
    
    Args:
        task_description: 任务描述
        execute_fn: 执行函数，接收 task_dict 参数，返回结果字典
        task_metadata: 任务元数据（可选）
        enable_reflection: 是否启用反思器（默认开启）
        enable_sharing: 是否启用子代理共享（默认开启）
        max_retries: 最大重试次数（默认 3）
    
    Returns:
        执行结果字典，包含 output、quality_score、retried 等字段
    """
    # 步骤 1: 检查缓存（避免重复执行相同任务）
    print(f"🔍 检查任务缓存: {task_description[:50]}...")
    cached = check_task_cache(task_description)
    
    if cached:
        print(f"✓ 命中缓存 (质量: {cached['quality_score']}, 耗时: {cached['duration_seconds']}s)")
        
        # 计算 task_id（与 save_task_experience 保持一致）
        import hashlib
        task_id = hashlib.sha256(task_description.strip().lower().encode('utf-8')).hexdigest()[:16]
        
        return {
            'output': cached['output'],
            'steps_taken': cached['steps_taken'],
            'quality_score': cached['quality_score'],
            'from_cache': True,
            'cached_at': cached['cached_at'],
            'task_id': task_id
        }
    
    # 步骤 2: 搜索相似任务经验（子代理共享）
    shared_experiences = []
    if enable_sharing:
        print("🔍 搜索相似任务经验...")
        shared_experiences = search_shared_tasks(task_description, min_quality=0.7, limit=2)
        
        if shared_experiences:
            print(f"✓ 找到 {len(shared_experiences)} 条相似经验")
            for exp in shared_experiences:
                print(f"  - {exp['task_description'][:40]} (质量: {exp['quality_score']})")
    
    # 步骤 3: 执行任务
    print("\n▶ 执行任务...")
    start_time = __import__('time').time()
    
    try:
        task_dict = {
            'description': task_description,
            'metadata': task_metadata or {},
            'shared_experiences': shared_experiences
        }
        
        result = execute_fn(task_dict)
        duration = __import__('time').time() - start_time
        
        # 确保结果格式正确
        if not isinstance(result, dict):
            result = {'output': str(result)}
        
        result.setdefault('success', True)
        result.setdefault('duration_seconds', duration)
    
    except Exception as e:
        duration = __import__('time').time() - start_time
        result = {
            'success': False,
            'output': '',
            'error_message': str(e),
            'duration_seconds': duration
        }
    
    # 步骤 4: 反思评分（如果启用）
    quality_score = None
    if enable_reflection:
        print("\n📊 进行反思评分...")
        reflector = ReflectionEngine()
        
        reflection_result = reflector.reflect_and_act(
            task={'description': task_description},
            result=result,
            execute_fn=None,  # 不自动重试，由调用方决定
            retry_count=0
        )
        
        # reflection_result 可能是 dict 或包含 ReflectionScore 对象
        if isinstance(reflection_result, dict):
            score_obj = reflection_result.get('score')
            if hasattr(score_obj, 'final_score'):
                quality_score = score_obj.final_score
            elif isinstance(score_obj, dict):
                quality_score = score_obj.get('final_score')
            else:
                quality_score = None
        else:
            quality_score = None
        
        print(f"  质量评分: {quality_score}")
    
    # 步骤 5: 保存经验（供后续任务复用）
    print("\n💾 保存执行经验...")
    task_id = save_task_experience(
        task_description=task_description,
        success=result.get('success', False),
        output=result.get('output', ''),
        steps_taken=result.get('steps_taken'),
        quality_score=quality_score,
        duration_seconds=result.get('duration_seconds'),
        error_message=result.get('error_message')
    )
    
    # 同时分享到子代理全局库
    if enable_sharing:
        share_subagent_experience(
            task_description=task_description,
            success=result.get('success', False),
            output=result.get('output', ''),
            steps_taken=result.get('steps_taken'),
            quality_score=quality_score,
            duration_seconds=result.get('duration_seconds'),
            error_message=result.get('error_message'),
            tags=['auto-captured']
        )
    
    # 步骤 6: 返回结果
    result['task_id'] = task_id
    result['quality_score'] = quality_score
    result['from_cache'] = False
    
    if quality_score and quality_score < 0.6:
        print(f"\n⚠ 质量评分较低 ({quality_score})，建议人工复核或调整任务描述后重试")
    
    return result


__all__ = [
    'run_task_with_agility',
    'ExperienceCacheChecker',
    'check_task_cache',
    'save_task_experience',
    'SubagentExperienceSharer',
    'search_shared_tasks',
    'share_subagent_experience',
    'ReflectionEngine',
]
