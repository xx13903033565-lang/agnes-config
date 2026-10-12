#!/usr/bin/env python3
"""
B7 Workaround: Custom memory extractor for global memory generation.

Engine bug: Global memory shows 0 sessions, runs.jsonl eligible_sessions=0.
Root cause: Engine's eligibility conditions too strict (non-empty + new messages + session ended/threshold).

Solution: External extractor reads runs.jsonl, extracts key decisions/learnings,
writes to ~/.agnes/memories/custom/ directory as structured markdown files.
ChromaDB embedding happens automatically on next AgnesCode startup.

Usage:
    # Manual run
    python3 ~/.agnes/scripts/custom_memory_extractor.py
    
    # LaunchAgent will run this hourly via ~/Library/LaunchAgents/com.agnes.custom-memory-extractor.plist
"""

import json
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


MEMORY_DIR = Path.home() / ".agnes" / "memories" / "custom"
SESSIONS_DB = Path.home() / ".agnes" / "data" / "sessions" / "sessions.db"
# 引擎自有状态文件：⛔本机脚本代写（名册由 agnes_config_guard.py --audit 现扫）
ENGINE_OWNED = {Path.home() / ".agnes" / "memories" / "processed_sessions.json"}
# 本脚本的侧车文件
PROCESSED_FILE = MEMORY_DIR / "extractor_processed.json"


def load_processed_sessions() -> set:
    """Load set of already processed session IDs（从本脚本自己的侧车文件读，⛔碰引擎状态文件）。"""
    if PROCESSED_FILE.exists():
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("session_ids", []))
        except (json.JSONDecodeError, KeyError):
            pass
    return set()


def save_processed_session(session_id: str):
    """Mark session as processed to avoid duplicates——写本脚本自己的侧车文件。"""
    processed = load_processed_sessions()
    processed.add(session_id)

    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump({"session_ids": list(processed), "last_updated": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


def extract_key_decisions_from_messages(messages: list) -> list:
    """Extract key decisions and learnings from session messages."""
    decisions = []
    
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        # Skip tool responses (they contain raw JSON structures, not decisions)
        if role == "tool" or (isinstance(content, dict) and content.get("type") == "toolResponse"):
            continue
        
        # Extract text content from structured message format
        if isinstance(content, list):
            # Handle array of content parts
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)
        elif isinstance(content, dict):
            # Handle single content object
            if content.get("type") == "text":
                content = content.get("text", "")
            else:
                continue  # Skip non-text content
        
        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)
        
        # Skip system/turn-context messages (not actual decisions or corrections)
        if "<turn-context>" in content or content.strip().startswith("<"):
            continue
        
        # Extract assistant responses with decisions
        if role == "assistant" and content:
            # Look for decision markers
            decision_keywords = [
                "决定", "决策", "结论", "方案", "选择",
                "decision", "conclusion", "solution", "choose"
            ]
            
            has_decision = any(kw in content.lower() for kw in decision_keywords)
            
            if has_decision and len(content) > 50:  # Filter out trivial responses
                decisions.append({
                    "timestamp": msg.get("created_at", ""),
                    "content": content[:500],  # Truncate long responses
                    "type": "decision"
                })
        
        # Extract user feedback/corrections
        elif role == "user" and content:
            correction_keywords = [
                "不对", "错误", "修正", "更正", "改正",
                "wrong", "error", "fix", "correct"
            ]
            
            has_correction = any(kw in content.lower() for kw in correction_keywords)
            
            if has_correction:
                decisions.append({
                    "timestamp": msg.get("created_at", ""),
                    "content": content[:300],
                    "type": "correction"
                })
    
    return decisions


def load_sessions_from_db() -> list:
    """Load sessions from SQLite database."""
    if not SESSIONS_DB.exists():
        print(f"Sessions DB not found: {SESSIONS_DB}")
        return []
    
    sessions = []
    try:
        conn = sqlite3.connect(str(SESSIONS_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all sessions with messages
        cursor.execute("""
            SELECT id, name, created_at, updated_at
            FROM sessions
            WHERE session_type = 'user' AND archived_at IS NULL
            ORDER BY created_at DESC
            LIMIT 50
        """)
        
        for row in cursor.fetchall():
            session_id = row["id"]
            
            # Load messages for this session
            cursor.execute("""
                SELECT role, content_json, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY created_timestamp ASC
            """, (session_id,))
            
            messages = []
            for msg_row in cursor.fetchall():
                try:
                    content_data = json.loads(msg_row["content_json"])
                    
                    # Handle different content formats
                    if isinstance(content_data, dict):
                        # Try to extract text from structured format
                        if "text" in content_data:
                            content = content_data["text"]
                        elif "parts" in content_data:
                            # Handle multi-part content
                            parts = content_data["parts"]
                            text_parts = []
                            for part in parts:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif isinstance(part, str):
                                    text_parts.append(part)
                            content = "\n".join(text_parts)
                        else:
                            content = json.dumps(content_data, ensure_ascii=False)
                    elif isinstance(content_data, list):
                        # Handle array of content parts
                        text_parts = []
                        for part in content_data:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                text_parts.append(part)
                        content = "\n".join(text_parts)
                    else:
                        content = str(content_data)
                        
                except (json.JSONDecodeError, TypeError):
                    content = str(msg_row["content_json"])
                
                messages.append({
                    "role": msg_row["role"],
                    "content": content,
                    "created_at": msg_row["timestamp"]
                })
            
            sessions.append({
                "id": session_id,
                "title": row["name"] or f"Session {session_id[:8]}",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": len(messages),
                "messages": messages
            })
        
        conn.close()
    except Exception as e:
        print(f"ERROR reading sessions DB: {e}", file=sys.stderr)
    
    return sessions


def write_memory_file(session_id: str, decisions: list, session_meta: dict):
    """Write extracted decisions to custom memory file."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{session_id}_{timestamp}.md"
    filepath = MEMORY_DIR / filename
    
    session_title = session_meta.get("title", "未命名会话")
    session_date = session_meta.get("created_at", datetime.now().isoformat())
    
    content = f"""---
name: {session_id}
source: custom_extractor
extracted_at: {datetime.now().isoformat()}
session_date: {session_date}
---

# {session_title}

**提取时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**原始会话 ID**: `{session_id}`

## 关键决策与学习点

"""
    
    if not decisions:
        content += "*本次会话未检测到明确决策或修正*\n"
    else:
        for i, decision in enumerate(decisions, 1):
            dtype = "决策" if decision["type"] == "decision" else "修正"
            content += f"### {i}. [{dtype}]\n\n"
            content += f"**时间**: {decision['timestamp']}\n\n"
            content += f"{decision['content']}\n\n"
    
    content += "---\n*此记忆由自定义提取器自动生成，将在下次 AgnesCode 启动时自动加载到 ChromaDB*\n"
    
    filepath.write_text(content, encoding="utf-8")
    return filepath


def process_sessions():
    """Process sessions from database and extract memories."""
    sessions = load_sessions_from_db()
    if not sessions:
        print("No sessions found in database")
        return 0
    
    processed_sessions = load_processed_sessions()
    extracted_count = 0
    
    for session in sessions:
        session_id = session["id"]
        
        if session_id in processed_sessions:
            continue
        
        # Skip sessions with too few messages
        if session["message_count"] < 2:
            save_processed_session(session_id)
            continue
        
        # Extract decisions
        decisions = extract_key_decisions_from_messages(session["messages"])
        
        # Write memory file
        meta = {
            "title": session["title"],
            "created_at": session["created_at"]
        }
        
        filepath = write_memory_file(session_id, decisions, meta)
        save_processed_session(session_id)
        extracted_count += 1
        
        print(f"Extracted: {session_id[:12]}... → {filepath.name} ({len(decisions)} decisions)")
    
    return extracted_count


def main():
    """Main entry point."""
    print(f"=== Custom Memory Extractor ===")
    print(f"Sessions DB: {SESSIONS_DB}")
    print(f"Output dir: {MEMORY_DIR}")
    print()
    
    try:
        count = process_sessions()
        print(f"\n=== Extraction complete: {count} sessions processed ===")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
