#!/usr/bin/env python3
"""
B8 Fix: Improve mutation.lock format with pid + timestamp + expiry check.

Root cause: Current lock files are 0-byte markers with no metadata, making it
impossible to detect stale locks or identify which process holds the lock.

Fix: Write structured JSON with pid, timestamp, hostname, and expiry TTL.
Add automatic expiry detection (default 1 hour) for crash recovery.

Usage:
    python3 fix_mutation_lock.py --acquire config.yaml.mutation.lock
    python3 fix_mutation_lock.py --check config.yaml.mutation.lock
    python3 fix_mutation_lock.py --release config.yaml.mutation.lock
"""

import json
import os
import sys
import time
import socket
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TTL_SECONDS = 3600  # 1 hour


def get_lock_data():
    """Generate lock metadata."""
    return {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": datetime.fromtimestamp(
            time.time() + DEFAULT_TTL_SECONDS, tz=timezone.utc
        ).isoformat(),
        "ttl_seconds": DEFAULT_TTL_SECONDS,
    }


def is_expired(lock_data):
    """Check if lock has expired."""
    try:
        expires_at = datetime.fromisoformat(lock_data["expires_at"])
        return datetime.now(timezone.utc) > expires_at
    except (KeyError, ValueError):
        # If we can't parse the expiry, assume it's valid (conservative)
        return False


def acquire_lock(lock_path):
    """Acquire a lock file with metadata."""
    lock_file = Path(lock_path)

    # Check if lock exists and is not expired
    if lock_file.exists() and lock_file.stat().st_size > 0:
        try:
            with open(lock_file, 'r') as f:
                existing = json.load(f)
            if not is_expired(existing):
                print(f"✗ Lock already held by PID {existing.get('pid', '?')} "
                      f"(expires {existing.get('expires_at', '?')})")
                return False
            else:
                print(f"⚠ Existing lock expired (PID {existing.get('pid', '?')}), taking over")
        except (json.JSONDecodeError, IOError):
            print("⚠ Corrupt lock file, overwriting")

    # Write new lock
    lock_data = get_lock_data()
    with open(lock_file, 'w') as f:
        json.dump(lock_data, f, indent=2)

    print(f"✓ Lock acquired: PID={lock_data['pid']}, "
          f"expires={lock_data['expires_at']}")
    return True


def check_lock(lock_path):
    """Check lock status without acquiring."""
    lock_file = Path(lock_path)

    if not lock_file.exists():
        print("✓ No lock present")
        return True

    if lock_file.stat().st_size == 0:
        print("⚠ Empty lock file (legacy format)")
        return True

    try:
        with open(lock_file, 'r') as f:
            lock_data = json.load(f)

        expired = is_expired(lock_data)
        status = "EXPIRED" if expired else "ACTIVE"
        print(f"{status} lock: PID={lock_data.get('pid', '?')}, "
              f"acquired={lock_data.get('acquired_at', '?')}, "
              f"expires={lock_data.get('expires_at', '?')}")

        if expired:
            print("  → Safe to remove or overwrite")
            return False
        return True

    except (json.JSONDecodeError, IOError) as e:
        print(f"✗ Corrupt lock file: {e}")
        return False


def release_lock(lock_path):
    """Release a lock file if we own it."""
    lock_file = Path(lock_path)

    if not lock_file.exists():
        print("✓ No lock to release")
        return True

    if lock_file.stat().st_size == 0:
        print("⚠ Legacy empty lock, removing")
        lock_file.unlink()
        return True

    try:
        with open(lock_file, 'r') as f:
            lock_data = json.load(f)

        if lock_data.get("pid") == os.getpid():
            lock_file.unlink()
            print(f"✓ Lock released (was held by us, PID {os.getpid()})")
            return True
        else:
            print(f"⚠ Lock held by different PID {lock_data.get('pid', '?')}, "
                  f"not releasing")
            return False

    except (json.JSONDecodeError, IOError):
        print("⚠ Corrupt lock, removing anyway")
        lock_file.unlink()
        return True


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    lock_path = sys.argv[2]

    if action == "--acquire":
        success = acquire_lock(lock_path)
        sys.exit(0 if success else 1)
    elif action == "--check":
        valid = check_lock(lock_path)
        sys.exit(0 if valid else 1)
    elif action == "--release":
        success = release_lock(lock_path)
        sys.exit(0 if success else 1)
    else:
        print(f"Unknown action: {action}")
        print("Use --acquire, --check, or --release")
        sys.exit(1)


if __name__ == "__main__":
    main()
