#!/usr/bin/env python3
"""
AgnesCode AGI Learning - 技能演化机制
Phase 4.3: 从成功经验中自动提炼和优化技能
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'reflection'))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from schema import init_database
from scorer import ReflectionScore
from config.settings_loader import get_learning_config


@dataclass
class SkillDraft:
    """技能草稿"""
    skill_name: str
    description: str
    trigger_pattern: str          # 触发关键词/正则
    action_template: str          # 行动模板（含占位符）
    parameters: Dict              # 参数定义
    examples: List[str]           # 使用示例
    
    source_task_id: str
    source_experience_id: int
    version: int = 1
    
    status: str = "draft"         # draft, approved, deprecated
    usage_count: int = 0
    success_rate: float = 0.0


@dataclass
class SkillEvolutionResult:
    """技能演化结果"""
    new_skills: List[SkillDraft] = field(default_factory=list)
    refined_skills: List[Dict] = field(default_factory=list)
    deprecated_skills: List[Dict] = field(default_factory=list)


class SkillEvolver:
    """
    技能演化器
    
    工作流程：
    1. 监控高分任务（quality_score >= 0.8）
    2. 分析执行步骤，提取通用模式
    3. 生成技能草稿（触发条件 + 行动模板）
    4. 人工审批后转为 approved 状态
    5. 基于使用反馈持续优化
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_conn = init_database(db_path)
        
        # 从配置加载质量阈值
        config = get_learning_config()
        self.quality_threshold = config.quality_threshold
        
        print(f"🔧 技能演化器已初始化（质量阈值: {self.quality_threshold}）")
    
    def analyze_and_extract_skills(
        self,
        task_id: str,
        task_description: str,
        result: Dict,
        score: ReflectionScore
    ) -> SkillEvolutionResult:
        """
        分析任务并提取技能
        
        Args:
            task_id: 任务ID
            task_description: 任务描述
            result: 执行结果
            score: 质量评分
            
        Returns:
            SkillEvolutionResult 演化结果
        """
        evolution = SkillEvolutionResult()
        
        # 检查是否达到技能提炼阈值
        if score.final_score < self.quality_threshold:
            print(f"⚠️  评分 {score.final_score:.2f} < {self.quality_threshold}，不提取技能")
            return evolution
        
        print(f"\n✨ 检测到高质量任务 (评分: {score.final_score:.2f})，开始提取技能...")
        
        # 获取经验ID
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT id FROM task_experiences WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        
        if not row:
            print(f"⚠️  未找到任务经验记录: {task_id}")
            return evolution
        
        experience_id = row[0]
        
        # 提取技能
        skill = self._extract_skill_from_experience(
            task_description,
            result,
            experience_id,
            task_id
        )
        
        if skill:
            # 保存到数据库
            skill_id = self._save_skill_draft(skill)
            evolution.new_skills.append(skill)
            
            print(f"✅ 新技能草稿已创建: {skill.skill_name} (ID: {skill_id})")
            print(f"   触发模式: {skill.trigger_pattern}")
            print(f"   行动模板: {skill.action_template[:50]}...")
        
        # 检查是否有需要优化的现有技能
        refinements = self._find_skills_needing_refinement(task_description, result)
        evolution.refined_skills.extend(refinements)
        
        # 检查是否有需要废弃的技能
        deprecations = self._find_deprecated_skills()
        evolution.deprecated_skills.extend(deprecations)
        
        return evolution
    
    def _extract_skill_from_experience(
        self,
        task_description: str,
        result: Dict,
        experience_id: int,
        task_id: str
    ) -> Optional[SkillDraft]:
        """从经验中提取技能"""
        steps = result.get("steps", [])
        
        if not steps:
            return None
        
        # 提取触发模式（从任务描述中提取关键词）
        trigger_keywords = self._extract_trigger_keywords(task_description)
        
        # 生成行动模板（从执行步骤中泛化）
        action_template = self._generalize_action_template(steps)
        
        if not action_template:
            return None
        
        # 生成技能名称
        skill_name = self._generate_skill_name(task_description)
        
        # 提取参数
        parameters = self._extract_parameters(steps, task_description)
        
        # 生成示例
        examples = [task_description]
        
        return SkillDraft(
            skill_name=skill_name,
            description=f"自动生成的技能：{task_description}",
            trigger_pattern="|".join(trigger_keywords),
            action_template=action_template,
            parameters=parameters,
            examples=examples,
            source_task_id=task_id,
            source_experience_id=experience_id
        )
    
    def _extract_trigger_keywords(self, task_description: str) -> List[str]:
        """提取触发关键词"""
        # 简单策略：提取动词和名词
        keywords = []
        
        # 常见动作词
        action_words = ["列出", "查找", "搜索", "统计", "安装", "删除", "移动", "复制", "分析"]
        for word in action_words:
            if word in task_description:
                keywords.append(word)
        
        # 如果没有匹配到预设词，使用前两个词
        if not keywords:
            words = task_description.split()
            keywords = [w for w in words if len(w) > 1][:2]
        
        return keywords if keywords else ["通用"]
    
    def _generalize_action_template(self, steps: List[str]) -> str:
        """泛化行动模板（将具体值替换为占位符）"""
        if not steps:
            return ""
        
        generalized_steps = []
        
        for step in steps:
            generalized = step
            
            # 替换文件名为占位符
            generalized = re.sub(r'[\w.-]+\.(?:py|txt|md|json)', '<filename>', generalized)
            
            # 替换数字为占位符
            generalized = re.sub(r'\b\d+\b', '<number>', generalized)
            
            # 替换路径
            generalized = re.sub(r'/[\w./-]+', '<path>', generalized)
            
            generalized_steps.append(generalized)
        
        return " && ".join(generalized_steps)
    
    def _generate_skill_name(self, task_description: str) -> str:
        """生成技能名称"""
        # 简单策略：取前几个词作为名称
        words = task_description.split()
        if len(words) <= 4:
            return "_".join(words)
        else:
            return "_".join(words[:4])
    
    def _extract_parameters(self, steps: List[str], task_description: str) -> Dict:
        """提取参数定义"""
        params = {}
        
        # 检测文件名参数
        if any(ext in task_description.lower() for ext in ['.py', '.txt', '.md']):
            params["filename"] = {
                "type": "string",
                "description": "目标文件名",
                "required": True
            }
        
        # 检测目录参数
        if "目录" in task_description or "文件夹" in task_description:
            params["directory"] = {
                "type": "string",
                "description": "目标目录",
                "default": "."
            }
        
        return params
    
    def _save_skill_draft(self, skill: SkillDraft) -> int:
        """保存技能草稿到数据库"""
        cursor = self.db_conn.cursor()
        
        cursor.execute("""
            INSERT INTO skill_drafts 
            (skill_name, description, source_task_id, source_experience_id,
             trigger_pattern, action_template, parameters, examples,
             status, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            skill.skill_name,
            skill.description,
            skill.source_task_id,
            skill.source_experience_id,
            skill.trigger_pattern,
            skill.action_template,
            json.dumps(skill.parameters),
            json.dumps(skill.examples),
            skill.status,
            skill.version
        ))
        
        self.db_conn.commit()
        return cursor.lastrowid
    
    def _find_skills_needing_refinement(
        self,
        task_description: str,
        result: Dict
    ) -> List[Dict]:
        """查找需要优化的技能"""
        # 简单策略：如果当前任务使用了某个技能但评分不高，该技能需要优化
        cursor = self.db_conn.cursor()
        
        # 查找匹配当前任务的技能
        keywords = task_description.split()
        skills_to_refine = []
        
        for kw in keywords:
            if len(kw) < 2:
                continue
            
            cursor.execute("""
                SELECT id, skill_name, usage_count, success_rate
                FROM skill_drafts
                WHERE status = 'approved' AND (
                    skill_name LIKE ? OR
                    description LIKE ?
                )
            """, (f"%{kw}%", f"%{kw}%"))
            
            for row in cursor.fetchall():
                skill_id, name, usage, rate = row
                
                # 如果使用次数多但成功率低，需要优化
                if usage >= 3 and rate < 0.7:
                    skills_to_refine.append({
                        "skill_id": skill_id,
                        "skill_name": name,
                        "reason": f"使用 {usage} 次，成功率仅 {rate:.0%}，需要优化",
                        "current_success_rate": rate
                    })
        
        return skills_to_refine
    
    def _find_deprecated_skills(self) -> List[Dict]:
        """查找需要废弃的技能"""
        cursor = self.db_conn.cursor()
        
        # 查找长期未使用且成功率低的技能
        cursor.execute("""
            SELECT id, skill_name, usage_count, success_rate, updated_at
            FROM skill_drafts
            WHERE status = 'approved'
              AND usage_count >= 5
              AND success_rate < 0.5
        """)
        
        deprecated = []
        for row in cursor.fetchall():
            deprecated.append({
                "skill_id": row[0],
                "skill_name": row[1],
                "reason": f"使用 {row[2]} 次，成功率仅 {row[3]:.0%}，建议废弃"
            })
        
        return deprecated
    
    def record_skill_usage(
        self,
        skill_id: int,
        task_id: str,
        success: bool,
        feedback: Optional[str] = None
    ):
        """记录技能使用情况"""
        cursor = self.db_conn.cursor()
        
        # 记录使用日志
        cursor.execute("""
            INSERT INTO skill_usage_logs (skill_id, task_id, success, feedback)
            VALUES (?, ?, ?, ?)
        """, (skill_id, task_id, success, feedback))
        
        # 更新技能统计
        cursor.execute("""
            UPDATE skill_drafts
            SET usage_count = usage_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (skill_id,))
        
        # 重新计算成功率
        cursor.execute("""
            SELECT COUNT(*) as total, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes
            FROM skill_usage_logs
            WHERE skill_id = ?
        """, (skill_id,))
        
        row = cursor.fetchone()
        if row and row[0] > 0:
            success_rate = row[1] / row[0]
            cursor.execute("""
                UPDATE skill_drafts
                SET success_rate = ?
                WHERE id = ?
            """, (success_rate, skill_id))
        
        self.db_conn.commit()
        print(f"📊 技能使用记录: ID={skill_id}, 成功={success}")
    
    def approve_skill(self, skill_id: int, note: str = ""):
        """审批技能（转为 approved 状态）"""
        cursor = self.db_conn.cursor()
        
        cursor.execute("""
            UPDATE skill_drafts
            SET status = 'approved', approval_note = ?
            WHERE id = ?
        """, (note, skill_id))
        
        self.db_conn.commit()
        print(f"✅ 技能已审批: ID={skill_id}")
    
    def get_approved_skills(self, limit: int = 10) -> List[Dict]:
        """获取已审批的技能"""
        cursor = self.db_conn.cursor()
        
        cursor.execute("""
            SELECT id, skill_name, description, trigger_pattern, action_template, 
                   parameters, usage_count, success_rate
            FROM skill_drafts
            WHERE status = 'approved'
            ORDER BY usage_count DESC
            LIMIT ?
        """, (limit,))
        
        skills = []
        for row in cursor.fetchall():
            skills.append({
                "id": row[0],
                "skill_name": row[1],
                "description": row[2],
                "trigger_pattern": row[3],
                "action_template": row[4],
                "parameters": json.loads(row[5]) if row[5] else {},
                "usage_count": row[6],
                "success_rate": row[7]
            })
        
        return skills
    
    def close(self):
        """关闭数据库连接"""
        if self.db_conn:
            self.db_conn.close()


def test_skill_evolution():
    """测试技能演化功能"""
    print("=" * 70)
    print("技能演化机制测试")
    print("=" * 70)
    
    # 先导入检索器并存储经验
    sys.path.insert(0, str(Path(__file__).parent))
    from retriever import ExperienceRetriever
    
    retriever = ExperienceRetriever()
    
    # 存储一条高分经验
    print("\n--- 准备: 存储高分经验 ---")
    
    mock_score = type('MockScore', (), {
        "final_score": 0.92,
        "completeness": 0.9,
        "accuracy": 0.95,
        "efficiency": 0.9,
        "safety": 1.0
    })()
    
    retriever.store_experience(
        task_id="skill_test_001",
        task_description="列出项目中的所有 Python 文件",
        task_type="file_operation",
        result={
            "success": True,
            "output": "main.py\ntest.py\nutils.py",
            "steps": ["ls -la", "find . -name '*.py'", "wc -l *.py"],
            "duration_seconds": 3.5
        },
        score=mock_score,
        tags=["python", "file", "listing"]
    )
    
    # 开始技能演化测试
    evolver = SkillEvolver()
    
    # 测试1：从高分任务提取技能
    print("\n--- 测试 1: 从高分任务提取技能 ---")
    
    task_result = {
        "success": True,
        "output": "main.py\ntest.py\nutils.py",
        "steps": ["ls -la", "find . -name '*.py'", "wc -l *.py"],
        "duration_seconds": 3.5
    }
    
    evolution = evolver.analyze_and_extract_skills(
        task_id="skill_test_001",
        task_description="列出项目中的所有 Python 文件",
        result=task_result,
        score=mock_score
    )
    
    print(f"\n提取结果:")
    print(f"  新技能: {len(evolution.new_skills)} 个")
    for skill in evolution.new_skills:
        print(f"    - {skill.skill_name}")
        print(f"      触发: {skill.trigger_pattern}")
        print(f"      模板: {skill.action_template[:60]}...")
    
    print(f"  需优化技能: {len(evolution.refined_skills)} 个")
    print(f"  需废弃技能: {len(evolution.deprecated_skills)} 个")
    
    # 测试2：审批技能
    print("\n--- 测试 2: 审批技能 ---")
    
    cursor = evolver.db_conn.cursor()
    cursor.execute("SELECT id FROM skill_drafts ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        skill_id = row[0]
        evolver.approve_skill(skill_id, "自动审批测试")
        
        # 验证审批
        skills = evolver.get_approved_skills()
        print(f"已审批技能数: {len(skills)}")
        for s in skills:
            rate = s['success_rate'] if s['success_rate'] is not None else 0.0
            print(f"  - {s['skill_name']} (使用 {s['usage_count']} 次, 成功率 {rate:.0%})")
    
    # 测试3：记录技能使用
    print("\n--- 测试 3: 记录技能使用 ---")
    
    if row:
        evolver.record_skill_usage(skill_id, "usage_test_001", success=True)
        evolver.record_skill_usage(skill_id, "usage_test_002", success=True)
        evolver.record_skill_usage(skill_id, "usage_test_003", success=False)
        
        # 查看更新后的统计
        cursor.execute("""
            SELECT usage_count, success_rate FROM skill_drafts WHERE id = ?
        """, (skill_id,))
        stats = cursor.fetchone()
        print(f"技能统计: 使用 {stats[0]} 次, 成功率 {stats[1]:.0%}")
    
    evolver.close()
    retriever.close()
    print("\n✅ 技能演化机制测试完成")


if __name__ == "__main__":
    test_skill_evolution()
