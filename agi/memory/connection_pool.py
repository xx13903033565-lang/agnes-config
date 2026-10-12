#!/usr/bin/env python3
"""
SQLite 连接池管理器 - 线程安全 + 并发写入保护

职责：
1. 管理 SQLite 数据库连接的创建和复用
2. 提供线程安全的写入操作（互斥锁）
3. WAL 模式验证和优化
4. 写入超时重试机制
5. 连接健康检查和自动重连
"""

import sqlite3
import threading
import time
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class ConnectionConfig:
    """连接配置"""
    db_path: Path
    wal_mode: bool = True                    # 启用 WAL 模式
    timeout: float = 30.0                    # 锁等待超时（秒）
    max_retries: int = 3                     # 写入失败最大重试次数
    retry_delay: float = 0.1                 # 重试间隔（秒）
    check_same_thread: bool = False          # 允许跨线程使用
    journal_size_limit: int = 64 * 1024 * 1024  # WAL 文件大小限制（64MB）
    cache_size: int = -2000                  # 页面缓存大小（负数表示 KB）
    synchronous: str = "NORMAL"              # 同步模式（NORMAL 平衡性能和安全）


@dataclass
class ConnectionStats:
    """连接统计信息"""
    total_connections: int = 0               # 总连接数
    active_connections: int = 0              # 活跃连接数
    total_queries: int = 0                   # 总查询数
    failed_writes: int = 0                   # 写入失败数
    retried_writes: int = 0                  # 重试写入数
    lock_wait_time_ms: float = 0.0           # 锁等待总时间（毫秒）


class SQLiteConnectionPool:
    """
    SQLite 连接池管理器
    
    特性：
    - 线程安全（互斥锁保护写入）
    - WAL 模式优化并发读
    - 写入超时重试
    - 连接健康检查
    - 统计信息收集
    """
    
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._lock = threading.Lock()          # 全局互斥锁
        self._write_lock = threading.Lock()    # 写入专用锁
        self._connections: Dict[int, sqlite3.Connection] = {}  # 线程 ID -> 连接
        self._stats = ConnectionStats()
        
        # 确保数据库目录存在
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_database()
        
        print(f"✅ SQLite 连接池已初始化")
        print(f"  数据库: {config.db_path}")
        print(f"  WAL 模式: {config.wal_mode}")
        print(f"  超时: {config.timeout}s")
    
    def _init_database(self):
        """初始化数据库配置"""
        conn = self._create_connection()
        try:
            cursor = conn.cursor()
            
            # 启用 WAL 模式（提升并发读性能）
            if self.config.wal_mode:
                cursor.execute("PRAGMA journal_mode=WAL")
                mode = cursor.fetchone()[0]
                if mode.upper() != "WAL":
                    print(f"️  WAL 模式启用失败，当前模式: {mode}")
                else:
                    print(f"  ✅ WAL 模式已启用")
            
            # 设置 WAL 文件大小限制
            cursor.execute(f"PRAGMA wal_autocheckpoint=1000")  # 每 1000 页自动 checkpoint
            
            # 设置缓存大小
            cursor.execute(f"PRAGMA cache_size={self.config.cache_size}")
            
            # 设置同步模式
            cursor.execute(f"PRAGMA synchronous={self.config.synchronous}")
            
            # 启用外键约束
            cursor.execute("PRAGMA foreign_keys=ON")
            
            # 设置 busy timeout
            cursor.execute(f"PRAGMA busy_timeout={int(self.config.timeout * 1000)}")
            
            conn.commit()
        finally:
            conn.close()
    
    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接"""
        conn = sqlite3.connect(
            str(self.config.db_path),
            timeout=self.config.timeout,
            check_same_thread=self.config.check_same_thread
        )
        
        # 配置连接
        conn.row_factory = sqlite3.Row  # 支持字典式访问
        
        self._stats.total_connections += 1
        return conn
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（线程本地存储）"""
        thread_id = threading.get_ident()
        
        with self._lock:
            if thread_id not in self._connections:
                self._connections[thread_id] = self._create_connection()
                self._stats.active_connections += 1
            
            conn = self._connections[thread_id]
            
            # 健康检查：尝试简单查询
            try:
                conn.execute("SELECT 1")
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                # 连接损坏，重新创建
                print(f"⚠️  连接损坏，重新创建（线程 {thread_id}）")
                conn.close()
                self._connections[thread_id] = self._create_connection()
            
            return self._connections[thread_id]
    
    @contextmanager
    def get_cursor(self):
        """
        获取游标上下文管理器（自动提交/回滚）
        
        用法：
            with pool.get_cursor() as cursor:
                cursor.execute("INSERT ...")
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            yield cursor
            conn.commit()
            self._stats.total_queries += 1
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
    
    @contextmanager
    def safe_write(self):
        """
        线程安全的写入上下文管理器（带重试）
        
        用法：
            with pool.safe_write() as cursor:
                cursor.execute("INSERT ...")
        """
        start_time = time.time()
        
        # 获取写入锁
        self._write_lock.acquire()
        
        try:
            lock_wait_time = (time.time() - start_time) * 1000
            self._stats.lock_wait_time_ms += lock_wait_time
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 重试循环
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    yield cursor
                    conn.commit()
                    self._stats.total_queries += 1
                    return  # 成功，退出
                    
                except sqlite3.OperationalError as e:
                    error_msg = str(e).lower()
                    
                    # 判断是否可重试
                    is_retryable = any(keyword in error_msg for keyword in [
                        "locked", "busy", "database is locked"
                    ])
                    
                    if is_retryable and attempt < self.config.max_retries:
                        self._stats.retried_writes += 1
                        print(f"⚠️  写入锁定，第 {attempt} 次重试...")
                        time.sleep(self.config.retry_delay * attempt)  # 指数退避
                        conn.rollback()
                    else:
                        # 不可重试或已达最大重试次数
                        self._stats.failed_writes += 1
                        conn.rollback()
                        raise
                
                except Exception:
                    # 非 OperationalError，不重试
                    conn.rollback()
                    raise
        
        finally:
            self._write_lock.release()
    
    def execute_read(self, sql: str, params: tuple = ()) -> List[Dict]:
        """
        执行只读查询（无需锁）
        
        Args:
            sql: SQL 语句
            params: 参数
            
        Returns:
            结果列表（字典形式）
        """
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """
        执行写入操作（线程安全 + 重试）
        
        Args:
            sql: SQL 语句
            params: 参数
            
        Returns:
            影响的行数
        """
        with self.safe_write() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount
    
    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """
        批量写入操作（线程安全 + 重试）
        
        Args:
            sql: SQL 语句
            params_list: 参数列表
            
        Returns:
            影响的总行数
        """
        total_rows = 0
        with self.safe_write() as cursor:
            cursor.executemany(sql, params_list)
            total_rows = cursor.rowcount
        return total_rows
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        return {
            "total_connections": self._stats.total_connections,
            "active_connections": self._stats.active_connections,
            "total_queries": self._stats.total_queries,
            "failed_writes": self._stats.failed_writes,
            "retried_writes": self._stats.retried_writes,
            "lock_wait_time_ms": round(self._stats.lock_wait_time_ms, 2)
        }
    
    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for thread_id, conn in self._connections.items():
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
            self._stats.active_connections = 0
            print("✅ 所有数据库连接已关闭")
    
    def __del__(self):
        """析构时关闭连接"""
        try:
            self.close_all()
        except Exception:
            pass


# 全局单例
_global_pool: Optional[SQLiteConnectionPool] = None


def get_connection_pool(db_path: Optional[Path] = None, force_new: bool = False) -> SQLiteConnectionPool:
    """
    获取全局连接池单例
    
    Args:
        db_path: 数据库路径，默认 ~/.agnes/memory/tasks.db
        force_new: 是否强制创建新实例
        
    Returns:
        SQLiteConnectionPool 实例
    """
    global _global_pool
    
    if _global_pool is not None and not force_new:
        return _global_pool
    
    if db_path is None:
        db_path = Path.home() / '.agnes' / 'memory' / 'tasks.db'
    
    config = ConnectionConfig(db_path=db_path)
    _global_pool = SQLiteConnectionPool(config)
    return _global_pool


# 压力测试
if __name__ == "__main__":
    import random
    
    print("=" * 70)
    print("SQLite 连接池压力测试")
    print("=" * 70)
    
    # 创建测试数据库
    test_db = Path.home() / '.agnes' / 'memory' / 'test_concurrent.db'
    pool = get_connection_pool(test_db, force_new=True)
    
    # 初始化测试表
    with pool.get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    # 并发写入测试
    errors = []
    success_counts = {"value": 0}
    success_lock = threading.Lock()
    
    def worker(thread_id: int, num_writes: int):
        local_success = 0
        for i in range(num_writes):
            try:
                with pool.safe_write() as cursor:
                    cursor.execute(
                        "INSERT INTO test_table (thread_id, value) VALUES (?, ?)",
                        (thread_id, f"Thread-{thread_id}-Item-{i}")
                    )
                local_success += 1
            except Exception as e:
                errors.append(f"Thread-{thread_id}: {e}")
        with success_lock:
            success_counts["value"] += local_success
    
    # 启动 10 个并发线程
    num_threads = 10
    writes_per_thread = 20
    threads = []
    
    start_time = time.time()
    
    for tid in range(num_threads):
        t = threading.Thread(target=worker, args=(tid, writes_per_thread))
        threads.append(t)
        t.start()
    
    # 等待所有线程完成
    for t in threads:
        t.join()
    
    elapsed = time.time() - start_time
    
    # 验证结果
    with pool.get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM test_table")
        actual_count = cursor.fetchone()["count"]
    
    expected_count = num_threads * writes_per_thread
    
    print(f"\n测试结果:")
    print(f"  线程数: {num_threads}")
    print(f"  每线程写入: {writes_per_thread}")
    print(f"  预期总数: {expected_count}")
    print(f"  实际总数: {actual_count}")
    print(f"  成功写入: {success_counts['value']}")
    print(f"  错误数: {len(errors)}")
    print(f"  耗时: {elapsed:.2f}s")
    print(f"  吞吐量: {actual_count / elapsed:.1f} ops/s")
    
    if errors:
        print(f"\n错误详情:")
        for err in errors[:5]:  # 只显示前 5 个
            print(f"  - {err}")
    
    # 连接池统计
    stats = pool.get_stats()
    print(f"\n连接池统计:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    # 清理
    pool.close_all()
    test_db.unlink(missing_ok=True)
    
    # 判断测试是否通过
    if actual_count == expected_count and len(errors) == 0:
        print(f"\n✅ 压力测试通过！{actual_count}/{expected_count} 条记录完整")
    else:
        print(f"\n❌ 压力测试失败！丢失 {expected_count - actual_count} 条记录")
