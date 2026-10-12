#!/usr/bin/env python3
"""
技能包导入导出模块

支持将学习到的经验序列化为可移植的技能包，包含：
- 序列化/反序列化（JSON/YAML）
- 版本管理
- 重复检测
- 完整性校验

使用场景：
- 跨机器迁移经验库
- 团队共享最佳实践
- 版本回滚与备份
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class SkillPackage:
    """技能包数据结构"""
    version: str = "1.0"
    created_at: float = field(default_factory=time.time)
    description: str = ""
    experiences: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "description": self.description,
            "experiences": self.experiences,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SkillPackage':
        """从字典创建"""
        return cls(
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", time.time()),
            description=data.get("description", ""),
            experiences=data.get("experiences", []),
            metadata=data.get("metadata", {})
        )
    
    def compute_checksum(self) -> str:
        """计算技能包校验和"""
        content = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()


class SkillPackageManager:
    """技能包管理器"""
    
    def __init__(self):
        self.packages_dir = Path.home() / ".agnes" / "skill_packages"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
    
    def export_package(self, experiences: List[Dict], 
                      output_path: Optional[Path] = None,
                      description: str = "",
                      metadata: Optional[Dict[str, str]] = None) -> Path:
        """
        导出技能包
        
        Args:
            experiences: 经验记录列表
            output_path: 输出文件路径（可选）
            description: 技能包描述
            metadata: 额外元数据
            
        Returns:
            生成的文件路径
        """
        package = SkillPackage(
            description=description,
            experiences=experiences,
            metadata=metadata or {}
        )
        
        if output_path is None:
            timestamp = int(package.created_at)
            output_path = self.packages_dir / f"skill_package_{timestamp}.json"
        
        # 添加校验和
        package.metadata["checksum"] = package.compute_checksum()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(package.to_dict(), f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def import_package(self, package_path: Path, 
                      merge_strategy: str = "skip_duplicates") -> Dict[str, int]:
        """
        导入技能包
        
        Args:
            package_path: 技能包文件路径
            merge_strategy: 合并策略
                - "skip_duplicates": 跳过重复项
                - "overwrite": 覆盖已有项
                - "fail_on_duplicate": 遇到重复则失败
                
        Returns:
            导入统计：{imported: N, skipped: N, failed: N}
        """
        if not package_path.exists():
            raise FileNotFoundError(f"技能包文件不存在: {package_path}")
        
        with open(package_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        package = SkillPackage.from_dict(data)
        
        # 验证校验和
        stored_checksum = package.metadata.pop("checksum", "")
        computed_checksum = package.compute_checksum()
        if stored_checksum and stored_checksum != computed_checksum:
            raise ValueError(f"技能包校验和不匹配！可能已损坏或被篡改")
        
        # 导入经验
        stats = {"imported": 0, "skipped": 0, "failed": 0}
        
        for exp in package.experiences:
            try:
                # 检查重复
                if self._is_duplicate(exp, merge_strategy):
                    if merge_strategy == "fail_on_duplicate":
                        stats["failed"] += 1
                        continue
                    elif merge_strategy == "skip_duplicates":
                        stats["skipped"] += 1
                        continue
                    # overwrite 策略会继续执行
                
                # 这里应该调用 ExperienceRetriever.store_experience
                # 但为避免循环依赖，我们返回统计数据由调用者处理
                stats["imported"] += 1
                
            except Exception as e:
                print(f"⚠️  导入经验失败: {e}")
                stats["failed"] += 1
        
        return stats
    
    def list_packages(self) -> List[Dict[str, Any]]:
        """列出所有可用的技能包"""
        packages = []
        for pkg_file in sorted(self.packages_dir.glob("skill_package_*.json")):
            try:
                with open(pkg_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                package = SkillPackage.from_dict(data)
                packages.append({
                    "file": pkg_file.name,
                    "path": str(pkg_file),
                    "version": package.version,
                    "created_at": package.created_at,
                    "description": package.description,
                    "experience_count": len(package.experiences),
                    "metadata": package.metadata
                })
            except Exception as e:
                print(f"⚠️  读取技能包失败 {pkg_file}: {e}")
        
        return packages
    
    def _is_duplicate(self, experience: Dict, strategy: str) -> bool:
        """
        检查经验记录是否重复
        
        基于 task_id 或任务描述判断
        """
        # 简化实现：实际应查询数据库
        # 这里假设调用者会提供完整的去重逻辑
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("技能包导入导出测试")
    print("=" * 70)
    
    manager = SkillPackageManager()
    
    # 模拟经验数据
    sample_experiences = [
        {
            "task_id": "test_001",
            "description": "测试任务 1",
            "type": "file_operation",
            "result": {"success": True, "output": "test output"},
            "score": {"final_score": 0.9},
            "tags": ["test", "demo"]
        },
        {
            "task_id": "test_002",
            "description": "测试任务 2",
            "type": "code_generation",
            "result": {"success": True, "code": "print('hello')"},
            "score": {"final_score": 0.85},
            "tags": ["python", "demo"]
        }
    ]
    
    # 导出技能包
    print("\n📦 导出技能包...")
    pkg_path = manager.export_package(
        experiences=sample_experiences,
        description="测试技能包示例",
        metadata={"author": "AGI System", "environment": "development"}
    )
    print(f"  ✅ 已导出到: {pkg_path}")
    
    # 列出技能包
    print("\n📋 可用技能包:")
    packages = manager.list_packages()
    for pkg in packages[-3:]:  # 显示最近 3 个
        print(f"  - {pkg['file']}: {pkg['description']} ({pkg['experience_count']} 条经验)")
    
    # 导入技能包
    print("\n📥 导入技能包...")
    stats = manager.import_package(pkg_path, merge_strategy="skip_duplicates")
    print(f"  导入统计: {stats}")
    
    # 验证校验和
    print("\n🔐 校验和验证...")
    import json
    with open(pkg_path, 'r') as f:
        data = json.load(f)
    original_checksum = data["metadata"]["checksum"]
    
    # 故意篡改数据
    data["experiences"][0]["description"] = "被篡改的描述"
    tampered_path = pkg_path.parent / "tampered_package.json"
    with open(tampered_path, 'w') as f:
        json.dump(data, f)
    
    try:
        manager.import_package(tampered_path)
        print("  ❌ 应该检测到篡改但未检测到！")
    except ValueError as e:
        print(f"  ✅ 正确检测到篡改: {e}")
    
    # 清理测试文件
    tampered_path.unlink(missing_ok=True)
    
    print(f"\n✅ 测试完成！")
