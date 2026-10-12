#!/usr/bin/env python3
"""
AgnesCode AGI Router - 综合验证测试
Phase 5.4: 验证路由决策、负载分发、故障转移全流程
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from model_registry import ModelRegistry, ModelCapability
from model_router import SmartRouter


def test_end_to_end_routing():
    """测试端到端路由流程"""
    print("=" * 70)
    print("Phase 5 Multi-model Router - 综合验证")
    print("=" * 70)
    
    router = SmartRouter()
    
    # 场景1：日常代码任务（成本敏感）
    print("\n--- 场景 1: 日常代码生成（预算$2/M） ---")
    decision1 = router.route_request(
        task_type="code",
        max_cost_per_million=2.0,
        min_quality=0.8
    )
    print(f"选择: {decision1.selected_model.model_id}")
    print(f"原因: {decision1.reason}")
    
    assert decision1.selected_model.input_cost_per_million + decision1.selected_model.output_cost_per_million <= 2.0
    
    # 场景2：关键任务（质量优先）
    print("\n--- 场景 2: 关键架构设计（质量≥0.9） ---")
    decision2 = router.route_request(
        task_type="chat",
        min_quality=0.9
    )
    print(f"选择: {decision2.selected_model.model_id}")
    print(f"质量: {decision2.selected_model.quality_score:.2f}")
    
    assert decision2.selected_model.quality_score >= 0.9
    
    # 场景3：故障转移测试
    print("\n--- 场景 3: 主模型失败，自动切换备用 ---")
    
    fail_count = [0]
    
    def mock_execute_with_failures(model):
        if model.model_id == "gemini-2.0-flash":
            fail_count[0] += 1
            raise ConnectionError("API 超时")
        return {"success": True, "model": model.model_id}
    
    result = router.execute_with_fallback(decision1, mock_execute_with_failures)
    print(f"最终使用模型: {result['model']}")
    print(f"失败次数: {fail_count[0]}")
    
    assert result['success'] == True
    assert fail_count[0] > 0  # 确实发生了故障转移
    
    # 场景4：负载均衡统计
    print("\n--- 场景 4: 负载统计 ---")
    for model_id, health in router.load_balancer.health_status.items():
        success_rate = (
            (health.total_requests - health.failed_requests) / health.total_requests 
            if health.total_requests > 0 else 1.0
        )
        print(f"  {model_id}:")
        print(f"    总请求: {health.total_requests}")
        print(f"    成功率: {success_rate:.0%}")
        print(f"    健康状态: {'✅' if health.is_healthy else '❌'}")
    
    print("\n" + "=" * 70)
    print("✅ 所有验证通过！Phase 5 Multi-model Router 完成")
    print("=" * 70)
    
    return True


if __name__ == "__main__":
    success = test_end_to_end_routing()
    sys.exit(0 if success else 1)
