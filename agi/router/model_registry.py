#!/usr/bin/env python3
"""
AgnesCode AGI Router - 模型注册表
Phase 5.1: 定义模型元数据结构，支持多提供商
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class ModelProvider(Enum):
    """模型提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    GEMINI = "gemini"
    HUNYUAN = "hunyuan"
    KIMI = "kimi"
    LOCAL = "local"  # 本地部署模型


class ModelCapability(Enum):
    """模型能力标签"""
    CHAT = "chat"                    # 对话
    CODE = "code"                    # 代码生成
    VISION = "vision"                # 图像理解
    TOOL_USE = "tool_use"            # 工具调用
    LONG_CONTEXT = "long_context"    # 长上下文
    FUNCTION_CALLING = "function_calling"  # 函数调用


@dataclass
class ModelConfig:
    """模型配置"""
    model_id: str                    # 唯一标识，如 "gpt-4o", "claude-3.5-sonnet"
    provider: ModelProvider          # 提供商
    display_name: str                # 显示名称
    
    # 能力标签
    capabilities: List[ModelCapability] = field(default_factory=list)
    
    # 性能指标
    max_context_length: int = 4096   # 最大上下文长度（token）
    max_output_tokens: int = 2048    # 最大输出长度
    
    # 成本信息（每百万 token，美元）
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    
    # 性能基准（毫秒，基于标准测试）
    avg_latency_ms: float = 1000.0
    tokens_per_second: float = 50.0
    
    # 质量评分（0-1，基于综合评测）
    quality_score: float = 0.7
    
    # API 配置
    api_endpoint: str = ""           # API 端点
    requires_api_key: bool = True    # 是否需要 API Key
    
    # 状态
    enabled: bool = True             # 是否启用
    priority: int = 0                # 优先级（越高越优先）
    
    # 元数据
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        data = asdict(self)
        data['provider'] = self.provider.value
        data['capabilities'] = [c.value for c in self.capabilities]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ModelConfig':
        """从字典创建"""
        data = data.copy()
        data['provider'] = ModelProvider(data['provider'])
        data['capabilities'] = [ModelCapability(c) for c in data.get('capabilities', [])]
        return cls(**data)


class ModelRegistry:
    """
    模型注册表
    
    管理所有可用模型的元数据，支持：
    - 注册新模型
    - 查询模型列表
    - 按条件筛选模型
    - 加载/保存配置
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.models: Dict[str, ModelConfig] = {}
        self.config_path = config_path or Path.home() / '.agnes' / 'config' / 'models.json'
        
        # 加载预定义模型
        self._register_builtin_models()
        
        # 尝试从配置文件加载
        if self.config_path.exists():
            self.load_from_file()
        
        print(f"📦 模型注册表已初始化，共 {len(self.models)} 个模型")
    
    def register_model(self, config: ModelConfig):
        """注册模型"""
        self.models[config.model_id] = config
        print(f"✅ 模型已注册: {config.model_id} ({config.display_name})")
    
    def unregister_model(self, model_id: str):
        """注销模型"""
        if model_id in self.models:
            del self.models[model_id]
            print(f"❌ 模型已注销: {model_id}")
    
    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        """获取模型配置"""
        return self.models.get(model_id)
    
    def list_models(
        self,
        enabled_only: bool = True,
        provider: Optional[ModelProvider] = None,
        capability: Optional[ModelCapability] = None
    ) -> List[ModelConfig]:
        """
        列出模型
        
        Args:
            enabled_only: 只列出启用的模型
            provider: 按提供商过滤
            capability: 按能力过滤
            
        Returns:
            模型配置列表
        """
        models = list(self.models.values())
        
        if enabled_only:
            models = [m for m in models if m.enabled]
        
        if provider:
            models = [m for m in models if m.provider == provider]
        
        if capability:
            models = [m for m in models if capability in m.capabilities]
        
        # 按优先级排序
        models.sort(key=lambda m: m.priority, reverse=True)
        
        return models
    
    def find_best_model(
        self,
        task_type: str,
        max_cost_per_million: Optional[float] = None,
        min_quality: float = 0.0,
        require_capability: Optional[ModelCapability] = None
    ) -> Optional[ModelConfig]:
        """
        根据任务需求找到最佳模型
        
        Args:
            task_type: 任务类型（chat, code, vision, etc.）
            max_cost_per_million: 最大可接受成本（每百万 token）
            min_quality: 最低质量要求
            require_capability: 必需的能力
            
        Returns:
            最佳模型配置，如果没有满足条件的返回 None
        """
        candidates = self.list_models(enabled_only=True)
        
        # 过滤不满足要求的模型
        filtered = []
        for model in candidates:
            # 检查能力
            if require_capability and require_capability not in model.capabilities:
                continue
            
            # 检查质量
            if model.quality_score < min_quality:
                continue
            
            # 检查成本
            if max_cost_per_million:
                total_cost = model.input_cost_per_million + model.output_cost_per_million
                if total_cost > max_cost_per_million:
                    continue
            
            filtered.append(model)
        
        if not filtered:
            return None
        
        # 评分排序：综合考虑质量、成本、延迟
        scored_models = []
        for model in filtered:
            score = self._calculate_model_score(model, task_type)
            scored_models.append((score, model))
        
        # 按分数降序
        scored_models.sort(key=lambda x: x[0], reverse=True)
        
        return scored_models[0][1] if scored_models else None
    
    def _calculate_model_score(self, model: ModelConfig, task_type: str) -> float:
        """
        计算模型评分（用于排序）
        
        综合考虑：
        - 质量（40%）
        - 成本效益（30%）
        - 延迟（20%）
        - 任务匹配度（10%）
        """
        # 质量分（0-1）
        quality_score = model.quality_score
        
        # 成本效益分（成本越低分越高）
        total_cost = model.input_cost_per_million + model.output_cost_per_million
        if total_cost > 0:
            cost_score = max(0, 1.0 - (total_cost / 100.0))  # 假设 $100/M 为上限
        else:
            cost_score = 1.0  # 免费模型
        
        # 延迟分（延迟越低分越高）
        latency_score = max(0, 1.0 - (model.avg_latency_ms / 5000.0))  # 假设 5s 为上限
        
        # 任务匹配分
        task_match_score = 0.5  # 默认中等匹配
        if task_type == "code" and ModelCapability.CODE in model.capabilities:
            task_match_score = 1.0
        elif task_type == "vision" and ModelCapability.VISION in model.capabilities:
            task_match_score = 1.0
        elif task_type == "chat":
            task_match_score = 0.8
        
        # 加权总分
        total_score = (
            quality_score * 0.4 +
            cost_score * 0.3 +
            latency_score * 0.2 +
            task_match_score * 0.1
        )
        
        return total_score
    
    def save_to_file(self, path: Optional[Path] = None):
        """保存配置到文件"""
        save_path = path or self.config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "version": "1.0",
            "models": {mid: m.to_dict() for mid, m in self.models.items()}
        }
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 模型配置已保存: {save_path}")
    
    def load_from_file(self, path: Optional[Path] = None):
        """从文件加载配置"""
        load_path = path or self.config_path
        
        if not load_path.exists():
            print(f"⚠️  配置文件不存在: {load_path}")
            return
        
        try:
            with open(load_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for model_id, model_data in data.get("models", {}).items():
                try:
                    config = ModelConfig.from_dict(model_data)
                    self.models[model_id] = config
                except Exception as e:
                    print(f"⚠️  加载模型 {model_id} 失败: {e}")
            
            print(f"📂 已从 {load_path} 加载 {len(data.get('models', {}))} 个模型")
        
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}")
    
    def _register_builtin_models(self):
        """注册预定义模型"""
        builtin_models = [
            # OpenAI
            ModelConfig(
                model_id="gpt-4o",
                provider=ModelProvider.OPENAI,
                display_name="GPT-4o",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.VISION, ModelCapability.TOOL_USE],
                max_context_length=128000,
                max_output_tokens=4096,
                input_cost_per_million=5.0,
                output_cost_per_million=15.0,
                avg_latency_ms=1500,
                tokens_per_second=80,
                quality_score=0.95,
                api_endpoint="https://api.openai.com/v1/chat/completions",
                priority=100
            ),
            ModelConfig(
                model_id="gpt-4o-mini",
                provider=ModelProvider.OPENAI,
                display_name="GPT-4o Mini",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.TOOL_USE],
                max_context_length=128000,
                max_output_tokens=4096,
                input_cost_per_million=0.15,
                output_cost_per_million=0.6,
                avg_latency_ms=1000,
                tokens_per_second=100,
                quality_score=0.85,
                api_endpoint="https://api.openai.com/v1/chat/completions",
                priority=90
            ),
            
            # Anthropic
            ModelConfig(
                model_id="claude-3.5-sonnet",
                provider=ModelProvider.ANTHROPIC,
                display_name="Claude 3.5 Sonnet",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.LONG_CONTEXT],
                max_context_length=200000,
                max_output_tokens=8192,
                input_cost_per_million=3.0,
                output_cost_per_million=15.0,
                avg_latency_ms=2000,
                tokens_per_second=60,
                quality_score=0.93,
                api_endpoint="https://api.anthropic.com/v1/messages",
                priority=95
            ),
            
            # DeepSeek
            ModelConfig(
                model_id="deepseek-v3",
                provider=ModelProvider.DEEPSEEK,
                display_name="DeepSeek V3",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE],
                max_context_length=64000,
                max_output_tokens=8192,
                input_cost_per_million=0.14,
                output_cost_per_million=0.28,
                avg_latency_ms=1200,
                tokens_per_second=90,
                quality_score=0.88,
                api_endpoint="https://api.deepseek.com/v1/chat/completions",
                priority=85
            ),
            
            # Qwen
            ModelConfig(
                model_id="qwen-max",
                provider=ModelProvider.QWEN,
                display_name="Qwen Max",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.FUNCTION_CALLING],
                max_context_length=32000,
                max_output_tokens=8192,
                input_cost_per_million=0.4,
                output_cost_per_million=1.2,
                avg_latency_ms=1500,
                tokens_per_second=70,
                quality_score=0.87,
                api_endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                priority=80
            ),
            
            # Gemini
            ModelConfig(
                model_id="gemini-2.0-flash",
                provider=ModelProvider.GEMINI,
                display_name="Gemini 2.0 Flash",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.VISION],
                max_context_length=1000000,
                max_output_tokens=8192,
                input_cost_per_million=0.1,
                output_cost_per_million=0.4,
                avg_latency_ms=800,
                tokens_per_second=120,
                quality_score=0.86,
                api_endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                priority=82
            ),
            
            # 本地模型（免费但需要自部署）
            ModelConfig(
                model_id="llama-3.1-70b-local",
                provider=ModelProvider.LOCAL,
                display_name="Llama 3.1 70B (Local)",
                capabilities=[ModelCapability.CHAT, ModelCapability.CODE],
                max_context_length=8192,
                max_output_tokens=4096,
                input_cost_per_million=0.0,
                output_cost_per_million=0.0,
                avg_latency_ms=3000,
                tokens_per_second=30,
                quality_score=0.82,
                api_endpoint="http://localhost:8080/v1/chat/completions",
                requires_api_key=False,
                priority=50
            )
        ]
        
        for model in builtin_models:
            self.register_model(model)


def test_model_registry():
    """测试模型注册表"""
    print("=" * 70)
    print("模型注册表测试")
    print("=" * 70)
    
    registry = ModelRegistry()
    
    # 测试1：列出所有模型
    print("\n--- 测试 1: 列出所有模型 ---")
    all_models = registry.list_models()
    print(f"总模型数: {len(all_models)}")
    for m in all_models[:3]:
        print(f"  - {m.model_id}: {m.display_name} (质量: {m.quality_score:.2f}, 成本: ${m.input_cost_per_million + m.output_cost_per_million:.2f}/M)")
    
    # 测试2：按提供商过滤
    print("\n--- 测试 2: 按提供商过滤 ---")
    openai_models = registry.list_models(provider=ModelProvider.OPENAI)
    print(f"OpenAI 模型数: {len(openai_models)}")
    for m in openai_models:
        print(f"  - {m.model_id}")
    
    # 测试3：查找最佳模型
    print("\n--- 测试 3: 查找最佳模型 ---")
    
    # 场景1：代码任务，预算有限
    best_code_model = registry.find_best_model(
        task_type="code",
        max_cost_per_million=5.0,
        min_quality=0.8
    )
    if best_code_model:
        print(f"代码任务（预算$5/M）: {best_code_model.model_id} (质量: {best_code_model.quality_score:.2f})")
    
    # 场景2：高质量聊天，不限成本
    best_chat_model = registry.find_best_model(
        task_type="chat",
        min_quality=0.9
    )
    if best_chat_model:
        print(f"高质量聊天: {best_chat_model.model_id} (质量: {best_chat_model.quality_score:.2f})")
    
    # 场景3：视觉任务
    best_vision_model = registry.find_best_model(
        task_type="vision",
        require_capability=ModelCapability.VISION
    )
    if best_vision_model:
        print(f"视觉任务: {best_vision_model.model_id} (质量: {best_vision_model.quality_score:.2f})")
    
    # 测试4：保存和加载配置
    print("\n--- 测试 4: 保存和加载配置 ---")
    registry.save_to_file()
    
    # 新建一个注册表并加载
    registry2 = ModelRegistry()
    loaded_models = registry2.list_models()
    print(f"加载后模型数: {len(loaded_models)}")
    
    print("\n✅ 模型注册表测试完成")


if __name__ == "__main__":
    test_model_registry()
