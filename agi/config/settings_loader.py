#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGI 配置加载器 - 从 YAML 文件加载集中化配置

职责：
1. 加载 agi_settings.yaml 配置文件
2. 提供类型安全的配置访问接口
3. 支持默认值回退（当配置文件缺失时）
4. 缓存配置避免重复读取磁盘

使用示例：
    from agi.config.settings_loader import load_settings
    
    settings = load_settings()
    threshold = settings.reflection.excellent_threshold
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    # 如果 PyYAML 未安装，使用简单的字典解析
    yaml = None


@dataclass
class ReflectionConfig:
    """Reflection 模块配置"""
    excellent_threshold: float = 0.8
    acceptable_threshold: float = 0.6
    max_retries: int = 3
    completeness_weight: float = 0.25
    accuracy_weight: float = 0.30
    efficiency_weight: float = 0.20
    safety_weight: float = 0.25


@dataclass
class PlanningConfig:
    """Planning 模块配置"""
    max_retries: int = 2
    react_max_iterations: int = 10
    action_cycle_detection_window: int = 3


@dataclass
class LearningConfig:
    """Learning 模块配置"""
    min_similarity: float = 0.6
    retrieval_top_k: int = 5
    quality_threshold: float = 0.8
    min_usage_count: int = 3
    success_rate_threshold: float = 0.7


@dataclass
class RouterConfig:
    """Router 模块配置"""
    quality_weight: float = 0.4
    cost_weight: float = 0.3
    latency_weight: float = 0.2
    match_weight: float = 0.1
    max_consecutive_failures: int = 3
    health_check_interval: int = 60
    max_retries: int = 2
    default_max_cost_per_million: float = 10.0


@dataclass
class MemoryConfig:
    """Memory 模块配置"""
    chromadb_dimension: int = 1024
    chromadb_collection_name: str = "agnes_experiences"
    sqlite_wal_mode: bool = True
    connection_timeout: int = 30
    autonomous_mode: bool = False
    auto_approve_threshold: float = 0.9


@dataclass
class MonitoringConfig:
    """监控配置"""
    log_level: str = "INFO"
    enable_metrics: bool = True
    metrics_export_interval: int = 300


@dataclass
class AGISettings:
    """AGI 全局配置"""
    reflection: ReflectionConfig = field(default_factory=ReflectionConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)


# 全局配置缓存
_global_settings: Optional[AGISettings] = None


def _parse_yaml_simple(content: str) -> Dict[str, Any]:
    """
    简单的 YAML 解析器（当 PyYAML 不可用时使用）
    
    注意：仅支持基本的键值对和嵌套结构，不支持复杂 YAML 特性
    """
    result = {}
    current_section = None
    
    for line in content.split('\n'):
        line = line.strip()
        
        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue
        
        # 检测节标题（如 "reflection:"）
        if line.endswith(':') and not ':' in line[:-1]:
            section_name = line[:-1].strip()
            current_section = {}
            result[section_name] = current_section
            continue
        
        # 解析键值对
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            # 移除行内注释
            if '#' in value:
                value = value.split('#')[0].strip()
            
            # 类型转换
            if value.lower() in ('true', 'yes'):
                value = True
            elif value.lower() in ('false', 'no'):
                value = False
            else:
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass  # 保持字符串
            
            # 添加到当前节或根级别
            if current_section is not None:
                current_section[key] = value
            else:
                result[key] = value
    
    return result


def _load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """加载 YAML 文件，优先使用 PyYAML，回退到简单解析器"""
    if not file_path.exists():
        return {}
    
    content = file_path.read_text(encoding='utf-8')
    
    if yaml is not None:
        return yaml.safe_load(content) or {}
    else:
        return _parse_yaml_simple(content)


def load_settings(config_path: Optional[str] = None, force_reload: bool = False) -> AGISettings:
    """
    加载 AGI 配置
    
    Args:
        config_path: 配置文件路径，默认为 ~/.agnes/config/agi_settings.yaml
        force_reload: 是否强制重新加载（忽略缓存）
    
    Returns:
        AGISettings 配置对象
    """
    global _global_settings
    
    # 如果已有缓存且不强制重载，直接返回
    if _global_settings is not None and not force_reload:
        return _global_settings
    
    # 确定配置文件路径
    if config_path is None:
        home = Path.home()
        config_path = str(home / '.agnes' / 'config' / 'agi_settings.yaml')
    
    config_file = Path(config_path)
    
    # 加载 YAML 配置
    raw_config = _load_yaml_file(config_file)
    
    # 如果没有配置文件，使用默认值
    if not raw_config:
        print(f"⚠️  配置文件不存在: {config_path}，使用默认配置")
        _global_settings = AGISettings()
        return _global_settings
    
    # 解析各模块配置
    reflection_data = raw_config.get('reflection', {})
    planning_data = raw_config.get('planning', {})
    learning_data = raw_config.get('learning', {})
    router_data = raw_config.get('router', {})
    memory_data = raw_config.get('memory', {})
    monitoring_data = raw_config.get('monitoring', {})
    
    # 构建配置对象
    _global_settings = AGISettings(
        reflection=ReflectionConfig(**{k: v for k, v in reflection_data.items() 
                                       if k in ReflectionConfig.__dataclass_fields__}),
        planning=PlanningConfig(**{k: v for k, v in planning_data.items() 
                                   if k in PlanningConfig.__dataclass_fields__}),
        learning=LearningConfig(**{k: v for k, v in learning_data.items() 
                                   if k in LearningConfig.__dataclass_fields__}),
        router=RouterConfig(**{k: v for k, v in router_data.items() 
                               if k in RouterConfig.__dataclass_fields__}),
        memory=MemoryConfig(**{k: v for k, v in memory_data.items() 
                               if k in MemoryConfig.__dataclass_fields__}),
        monitoring=MonitoringConfig(**{k: v for k, v in monitoring_data.items() 
                                       if k in MonitoringConfig.__dataclass_fields__})
    )
    
    print(f"✅ 配置已加载: {config_path}")
    return _global_settings


def get_reflection_config() -> ReflectionConfig:
    """获取 Reflection 模块配置"""
    return load_settings().reflection


def get_planning_config() -> PlanningConfig:
    """获取 Planning 模块配置"""
    return load_settings().planning


def get_learning_config() -> LearningConfig:
    """获取 Learning 模块配置"""
    return load_settings().learning


def get_router_config() -> RouterConfig:
    """获取 Router 模块配置"""
    return load_settings().router


def get_memory_config() -> MemoryConfig:
    """获取 Memory 模块配置"""
    return load_settings().memory


if __name__ == "__main__":
    # 测试配置加载
    settings = load_settings()
    
    print("\n=== AGI 配置预览 ===")
    print(f"Reflection 阈值:")
    print(f"  优秀: {settings.reflection.excellent_threshold}")
    print(f"  可接受: {settings.reflection.acceptable_threshold}")
    print(f"  最大重试: {settings.reflection.max_retries}")
    
    print(f"\nPlanning 策略:")
    print(f"  最大重试: {settings.planning.max_retries}")
    print(f"  ReAct 最大迭代: {settings.planning.react_max_iterations}")
    
    print(f"\nLearning 参数:")
    print(f"  最小相似度: {settings.learning.min_similarity}")
    print(f"  质量阈值: {settings.learning.quality_threshold}")
    
    print(f"\nRouter 权重:")
    print(f"  质量: {settings.router.quality_weight}")
    print(f"  成本: {settings.router.cost_weight}")
    print(f"  延迟: {settings.router.latency_weight}")
    print(f"  匹配: {settings.router.match_weight}")
