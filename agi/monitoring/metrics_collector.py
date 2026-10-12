#!/usr/bin/env python3
"""
AGI 监控指标收集器

负责采集系统运行指标并导出为 JSONL/Prometheus 格式。
支持实时监控、性能分析和故障排查。

核心指标：
- LLM API 调用次数/延迟/成功率
- 向量检索命中率/延迟
- 任务执行成功率/耗时
- 内存使用量
- 数据库操作统计
"""

import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class MetricPoint:
    """单个指标数据点"""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_prometheus(self) -> str:
        """转换为 Prometheus 格式"""
        tag_str = ",".join(f'{k}="{v}"' for k, v in self.tags.items())
        if tag_str:
            return f"{self.name}{{{tag_str}}} {self.value} {int(self.timestamp * 1000)}"
        return f"{self.name} {self.value} {int(self.timestamp * 1000)}"
    
    def to_jsonl(self) -> str:
        """转换为 JSONL 格式"""
        return json.dumps({
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
            "tags": self.tags
        }, ensure_ascii=False)


class MetricsCollector:
    """监控指标收集器"""
    
    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or Path.home() / ".agnes" / "metrics"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.Lock()
        self._metrics: List[MetricPoint] = []
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        
        # 启动时间
        self._start_time = time.time()
        
        # 自动保存线程
        self._save_interval = 60  # 每 60 秒保存一次
        self._running = True
        self._save_thread = threading.Thread(target=self._auto_save, daemon=True)
        self._save_thread.start()
    
    def increment_counter(self, name: str, value: float = 1.0, tags: Optional[Dict[str, str]] = None):
        """增加计数器"""
        with self._lock:
            key = self._make_key(name, tags)
            self._counters[key] = self._counters.get(key, 0) + value
            
            # 同时记录到指标列表
            point = MetricPoint(name=name, value=self._counters[key], tags=tags or {})
            self._metrics.append(point)
    
    def set_gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """设置仪表盘值"""
        with self._lock:
            key = self._make_key(name, tags)
            self._gauges[key] = value
            
            point = MetricPoint(name=name, value=value, tags=tags or {})
            self._metrics.append(point)
    
    def observe_histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """记录直方图观测值"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            
            point = MetricPoint(name=name, value=value, tags=tags or {})
            self._metrics.append(point)
    
    def record_api_call(self, api_name: str, success: bool, latency_ms: float, 
                       error_type: Optional[str] = None):
        """记录 API 调用指标"""
        tags = {"api": api_name, "success": str(success).lower()}
        if error_type:
            tags["error_type"] = error_type
        
        self.increment_counter("agi_api_calls_total", tags=tags)
        self.observe_histogram("agi_api_latency_ms", latency_ms, tags={"api": api_name})
    
    def record_task_execution(self, task_type: str, success: bool, duration_ms: float):
        """记录任务执行指标"""
        tags = {"task_type": task_type, "success": str(success).lower()}
        self.increment_counter("agi_tasks_total", tags=tags)
        self.observe_histogram("agi_task_duration_ms", duration_ms, tags={"task_type": task_type})
    
    def record_embedding_retrieval(self, found: bool, similarity: float, latency_ms: float):
        """记录向量检索指标"""
        tags = {"found": str(found).lower()}
        self.increment_counter("agi_embedding_retrievals_total", tags=tags)
        self.observe_histogram("agi_embedding_similarity", similarity, tags={})
        self.observe_histogram("agi_embedding_retrieval_latency_ms", latency_ms, tags={})
    
    def get_uptime_seconds(self) -> float:
        """获取运行时长（秒）"""
        return time.time() - self._start_time
    
    def get_summary(self) -> Dict[str, Any]:
        """获取指标摘要"""
        with self._lock:
            summary = {
                "uptime_seconds": self.get_uptime_seconds(),
                "total_metrics": len(self._metrics),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {}
            }
            
            # 计算直方图统计
            for name, values in self._histograms.items():
                if values:
                    summary["histograms"][name] = {
                        "count": len(values),
                        "sum": sum(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values)
                    }
            
            return summary
    
    def export_to_jsonl(self, output_path: Optional[Path] = None) -> Path:
        """导出为 JSONL 格式"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_dir / f"metrics_{timestamp}.jsonl"
        
        with self._lock:
            with open(output_path, 'w', encoding='utf-8') as f:
                for metric in self._metrics:
                    f.write(metric.to_jsonl() + "\n")
        
        return output_path
    
    def export_to_prometheus(self, output_path: Optional[Path] = None) -> Path:
        """导出为 Prometheus 文本格式"""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_dir / f"metrics_{timestamp}.prom"
        
        with self._lock:
            lines = []
            
            # 导出计数器
            for key, value in self._counters.items():
                name = key.split("{")[0] if "{" in key else key
                tags = {}
                if "{" in key:
                    tag_part = key[key.index("{")+1:key.index("}")]
                    for pair in tag_part.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            tags[k.strip()] = v.strip('"')
                
                point = MetricPoint(name=name, value=value, tags=tags)
                lines.append(f"# TYPE {name} counter")
                lines.append(point.to_prometheus())
            
            # 导出仪表盘
            for key, value in self._gauges.items():
                name = key.split("{")[0] if "{" in key else key
                tags = {}
                if "{" in key:
                    tag_part = key[key.index("{")+1:key.index("}")]
                    for pair in tag_part.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            tags[k.strip()] = v.strip('"')
                
                point = MetricPoint(name=name, value=value, tags=tags)
                lines.append(f"# TYPE {name} gauge")
                lines.append(point.to_prometheus())
            
            # 导出直方图统计
            for name, values in self._histograms.items():
                if values:
                    lines.append(f"# TYPE {name}_count counter")
                    lines.append(f"{name}_count {len(values)} {int(time.time() * 1000)}")
                    lines.append(f"# TYPE {name}_sum counter")
                    lines.append(f"{name}_sum {sum(values)} {int(time.time() * 1000)}")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
        
        return output_path
    
    def _auto_save(self):
        """自动保存后台线程"""
        while self._running:
            time.sleep(self._save_interval)
            try:
                self.export_to_jsonl()
            except Exception as e:
                print(f"⚠️  自动保存失败: {e}")
    
    def shutdown(self):
        """关闭收集器"""
        self._running = False
        if self._save_thread.is_alive():
            self._save_thread.join(timeout=5)
        # 最后保存一次
        try:
            self.export_to_jsonl()
        except Exception:
            pass
    
    @staticmethod
    def _make_key(name: str, tags: Optional[Dict[str, str]] = None) -> str:
        """生成指标键"""
        if not tags:
            return name
        tag_str = ",".join(f'{k}="{v}"' for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"


# 全局单例
_global_collector: Optional[MetricsCollector] = None

def get_metrics_collector(storage_dir: Optional[Path] = None) -> MetricsCollector:
    """获取全局指标收集器单例"""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector(storage_dir)
    return _global_collector


if __name__ == "__main__":
    print("=" * 70)
    print("AGI 监控指标收集器测试")
    print("=" * 70)
    
    collector = MetricsCollector(Path("/tmp/test_metrics"))
    
    # 模拟各种指标
    print("\n📊 模拟指标采集...")
    
    # API 调用
    for i in range(10):
        collector.record_api_call(
            api_name="zhipu_llm",
            success=i % 3 != 0,  # 模拟 30% 失败率
            latency_ms=100 + i * 10,
            error_type="timeout" if i % 3 == 0 else None
        )
    
    # 任务执行
    for i in range(20):
        collector.record_task_execution(
            task_type="reflection",
            success=True,
            duration_ms=500 + i * 50
        )
    
    # 向量检索
    for i in range(15):
        collector.record_embedding_retrieval(
            found=i < 12,  # 80% 命中率
            similarity=0.7 + i * 0.02,
            latency_ms=20 + i * 2
        )
    
    # 设置仪表盘值
    collector.set_gauge("memory_usage_mb", 256.5)
    collector.set_gauge("active_threads", 5)
    
    print(f"  ✅ 已记录 {len(collector._metrics)} 个指标点")
    
    # 获取摘要
    summary = collector.get_summary()
    print(f"\n📈 指标摘要:")
    print(f"  运行时长: {summary['uptime_seconds']:.2f}s")
    print(f"  总指标数: {summary['total_metrics']}")
    print(f"  计数器: {len(summary['counters'])} 个")
    print(f"  仪表盘: {len(summary['gauges'])} 个")
    print(f"  直方图: {len(summary['histograms'])} 个")
    
    # 导出
    jsonl_path = collector.export_to_jsonl()
    prom_path = collector.export_to_prometheus()
    
    print(f"\n💾 导出文件:")
    print(f"  JSONL: {jsonl_path}")
    print(f"  Prometheus: {prom_path}")
    
    # 显示部分 JSONL 内容
    print(f"\n📄 JSONL 样例（前 3 行）:")
    with open(jsonl_path, 'r') as f:
        for i, line in enumerate(f):
            if i >= 3:
                break
            print(f"  {line.strip()}")
    
    collector.shutdown()
    print(f"\n✅ 测试完成！")
