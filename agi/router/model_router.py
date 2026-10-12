#!/usr/bin/env python3
"""
AgnesCode AGI Router - 智能路由器
Phase 5.2-5.3: 智能路由策略 + 负载均衡与故障转移
"""

import sys
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))

from model_registry import ModelRegistry, ModelConfig, ModelCapability


@dataclass
class RoutingDecision:
    """路由决策结果"""
    selected_model: ModelConfig
    reason: str                    # 选择原因
    fallback_models: List[ModelConfig] = field(default_factory=list)  # 备用模型列表
    estimated_cost: float = 0.0    # 预估成本
    estimated_latency_ms: float = 0.0  # 预估延迟


@dataclass
class ModelHealth:
    """模型健康状态"""
    model_id: str
    is_healthy: bool = True
    last_check_time: float = 0.0
    consecutive_failures: int = 0
    avg_response_time_ms: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0


class LoadBalancer:
    """负载均衡器"""
    
    def __init__(self):
        self.health_status: Dict[str, ModelHealth] = {}
    
    def record_request(self, model_id: str, success: bool, response_time_ms: float):
        """记录请求结果"""
        if model_id not in self.health_status:
            self.health_status[model_id] = ModelHealth(model_id=model_id)
        
        health = self.health_status[model_id]
        health.total_requests += 1
        health.last_check_time = time.time()
        
        if success:
            health.consecutive_failures = 0
            # 更新平均响应时间（移动平均）
            alpha = 0.3
            health.avg_response_time_ms = (
                alpha * response_time_ms + 
                (1 - alpha) * health.avg_response_time_ms
            )
        else:
            health.consecutive_failures += 1
            health.failed_requests += 1
            
            # 连续失败3次标记为不健康
            if health.consecutive_failures >= 3:
                health.is_healthy = False
    
    def get_healthy_models(self, models: List[ModelConfig]) -> List[ModelConfig]:
        """获取健康模型列表"""
        healthy = []
        for model in models:
            health = self.health_status.get(model.model_id)
            if not health or health.is_healthy:
                healthy.append(model)
        return healthy
    
    def get_model_load(self, model_id: str) -> int:
        """获取模型当前负载（简化为总请求数）"""
        health = self.health_status.get(model_id)
        return health.total_requests if health else 0


class SmartRouter:
    """
    智能路由器
    
    核心功能：
    1. 根据任务需求选择最佳模型
    2. 考虑成本、延迟、质量、可用性
    3. 支持故障自动转移
    4. 负载均衡分发请求
    """
    
    def __init__(self, registry: Optional[ModelRegistry] = None):
        self.registry = registry or ModelRegistry()
        self.load_balancer = LoadBalancer()
        
        # 路由策略配置
        self.cost_weight = 0.3      # 成本权重
        self.quality_weight = 0.4   # 质量权重
        self.latency_weight = 0.3   # 延迟权重
        
        print(f"🔀 智能路由器已初始化")
    
    def route_request(
        self,
        task_type: str,
        max_cost_per_million: Optional[float] = None,
        min_quality: float = 0.0,
        max_latency_ms: Optional[float] = None,
        require_capability: Optional[ModelCapability] = None,
        prefer_provider: Optional[str] = None
    ) -> RoutingDecision:
        """
        路由请求到最佳模型
        
        Args:
            task_type: 任务类型
            max_cost_per_million: 最大成本预算
            min_quality: 最低质量要求
            max_latency_ms: 最大可接受延迟
            require_capability: 必需能力
            prefer_provider: 偏好提供商
            
        Returns:
            RoutingDecision 路由决策
        """
        # 步骤1：获取候选模型
        candidates = self.registry.list_models(enabled_only=True)
        
        # 过滤不满足要求的模型
        filtered = []
        for model in candidates:
            if not self._meets_requirements(model, task_type, max_cost_per_million, 
                                           min_quality, max_latency_ms, require_capability):
                continue
            filtered.append(model)
        
        if not filtered:
            raise ValueError("没有满足要求的可用模型")
        
        # 步骤2：获取健康模型
        healthy_models = self.load_balancer.get_healthy_models(filtered)
        if not healthy_models:
            # 如果所有模型都不健康，使用原始列表
            healthy_models = filtered
        
        # 步骤3：评分排序
        scored = [(self._score_model(m, task_type), m) for m in healthy_models]
        scored.sort(key=lambda x: x[0], reverse=True)
        
        if not scored:
            raise ValueError("无法评分任何模型")
        
        # 步骤4：选择最佳模型
        best_score, best_model = scored[0]
        
        # 步骤5：选择备用模型（前3个）
        fallbacks = [m for _, m in scored[1:4]]
        
        # 计算预估值
        estimated_cost = best_model.input_cost_per_million + best_model.output_cost_per_million
        estimated_latency = best_model.avg_latency_ms
        
        # 生成决策原因
        reason = self._explain_decision(best_model, task_type, best_score)
        
        return RoutingDecision(
            selected_model=best_model,
            reason=reason,
            fallback_models=fallbacks,
            estimated_cost=estimated_cost,
            estimated_latency_ms=estimated_latency
        )
    
    def _meets_requirements(
        self,
        model: ModelConfig,
        task_type: str,
        max_cost: Optional[float],
        min_quality: float,
        max_latency: Optional[float],
        require_capability: Optional[ModelCapability]
    ) -> bool:
        """检查模型是否满足要求"""
        # 检查能力
        if require_capability and require_capability not in model.capabilities:
            return False
        
        # 检查质量
        if model.quality_score < min_quality:
            return False
        
        # 检查成本
        if max_cost:
            total_cost = model.input_cost_per_million + model.output_cost_per_million
            if total_cost > max_cost:
                return False
        
        # 检查延迟
        if max_latency and model.avg_latency_ms > max_latency:
            return False
        
        return True
    
    def _score_model(self, model: ModelConfig, task_type: str) -> float:
        """评分模型（用于排序）"""
        # 基础分来自注册表的评分方法
        base_score = self.registry._calculate_model_score(model, task_type)
        
        # 考虑健康状态惩罚
        health = self.load_balancer.health_status.get(model.model_id)
        if health and not health.is_healthy:
            base_score *= 0.5  # 不健康模型分数减半
        
        # 考虑负载平衡（负载越高分越低）
        current_load = self.load_balancer.get_model_load(model.model_id)
        if current_load > 100:
            base_score *= 0.9  # 高负载轻微惩罚
        
        return base_score
    
    def _explain_decision(self, model: ModelConfig, task_type: str, score: float) -> str:
        """生成决策解释"""
        reasons = []
        
        if model.quality_score >= 0.9:
            reasons.append("高质量")
        elif model.quality_score >= 0.8:
            reasons.append("良好质量")
        
        total_cost = model.input_cost_per_million + model.output_cost_per_million
        if total_cost < 1.0:
            reasons.append("低成本")
        elif total_cost < 10.0:
            reasons.append("中等成本")
        
        if model.avg_latency_ms < 1000:
            reasons.append("低延迟")
        
        if task_type == "code" and ModelCapability.CODE in model.capabilities:
            reasons.append("代码优化")
        
        return f"选择 {model.model_id}: {', '.join(reasons)} (评分: {score:.2f})"
    
    def execute_with_fallback(
        self,
        decision: RoutingDecision,
        execute_fn,
        max_retries: Optional[int] = None
    ) -> Dict:
        """
        执行请求并支持故障转移
        
        Args:
            decision: 路由决策
            execute_fn: 执行函数，接收 model_config，返回结果
            max_retries: 最大重试次数（默认从配置读取）
            
        Returns:
            执行结果
        """
        # 从配置加载最大重试次数
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config.settings_loader import get_router_config
        
        config = get_router_config()
        
        if max_retries is None:
            max_retries = config.max_retries
        
        models_to_try = [decision.selected_model] + decision.fallback_models
        
        for attempt, model in enumerate(models_to_try[:max_retries+1]):
            try:
                start_time = time.time()
                result = execute_fn(model)
                response_time = (time.time() - start_time) * 1000
                
                # 记录成功
                self.load_balancer.record_request(model.model_id, success=True, response_time_ms=response_time)
                
                if attempt == 0:
                    print(f"✅ 主模型 {model.model_id} 执行成功 ({response_time:.0f}ms)")
                else:
                    print(f"✅ 备用模型 {model.model_id} 执行成功 ({response_time:.0f}ms)")
                
                return result
            
            except Exception as e:
                response_time = (time.time() - start_time) * 1000
                self.load_balancer.record_request(model.model_id, success=False, response_time_ms=response_time)
                
                print(f"⚠️  模型 {model.model_id} 失败: {e}")
                
                if attempt < len(models_to_try) - 1:
                    print(f"🔄 切换到备用模型...")
        
        raise RuntimeError(f"所有模型都执行失败，已尝试 {len(models_to_try)} 个模型")


def test_smart_router():
    """测试智能路由器"""
    print("=" * 70)
    print("智能路由器测试")
    print("=" * 70)
    
    router = SmartRouter()
    
    # 测试1：基本路由决策
    print("\n--- 测试 1: 基本路由决策 ---")
    
    scenarios = [
        {
            "name": "代码生成任务",
            "task_type": "code",
            "max_cost_per_million": 5.0,
            "min_quality": 0.8
        },
        {
            "name": "高质量聊天",
            "task_type": "chat",
            "min_quality": 0.9
        },
        {
            "name": "视觉分析",
            "task_type": "vision",
            "require_capability": ModelCapability.VISION
        }
    ]
    
    for scenario in scenarios:
        name = scenario.pop("name")
        decision = router.route_request(**scenario)
        print(f"\n{name}:")
        print(f"  选择: {decision.selected_model.model_id}")
        print(f"  原因: {decision.reason}")
        print(f"  预估成本: ${decision.estimated_cost:.2f}/M")
        print(f"  备用模型: {[m.model_id for m in decision.fallback_models[:2]]}")
    
    # 测试2：故障转移
    print("\n--- 测试 2: 故障转移 ---")
    
    decision = router.route_request(task_type="code", min_quality=0.8)
    
    call_count = [0]
    
    def mock_execute(model: ModelConfig) -> Dict:
        call_count[0] += 1
        
        # 第一个模型失败，第二个成功
        if call_count[0] == 1:
            raise ConnectionError("API 超时")
        else:
            return {"success": True, "output": "代码生成成功"}
    
    result = router.execute_with_fallback(decision, mock_execute)
    print(f"最终结果: {result}")
    
    # 测试3：负载均衡
    print("\n--- 测试 3: 负载统计 ---")
    
    for model_id, health in router.load_balancer.health_status.items():
        print(f"  {model_id}: 请求={health.total_requests}, 失败={health.failed_requests}, 健康={health.is_healthy}")
    
    print("\n✅ 智能路由器测试完成")


if __name__ == "__main__":
    test_smart_router()
