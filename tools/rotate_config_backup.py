#!/usr/bin/env python3
"""
B9 Fix: Implement config.yaml.bak rotation (max 5 files).

Root cause: Current backup mechanism creates unlimited .bak files with
timestamped names, leading to accumulation without cleanup.

Fix: After creating a new backup, check total count and remove oldest
files if exceeding MAX_BACKUPS threshold (default 5).

Usage:
    python3 rotate_config_backup.py [--max-backups N] [--dry-run]
"""

import glob
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".agnes" / "config"
MAX_BACKUPS = 5


def get_backup_files():
    """Get all config backup files sorted by modification time (oldest first)."""
    pattern = str(CONFIG_DIR / "config.yaml.bak*")
    backups = glob.glob(pattern)

    # Sort by mtime (oldest first)
    backups.sort(key=lambda f: os.path.getmtime(f))
    return backups


def rotate_backups(max_backups=MAX_BACKUPS, dry_run=False):
    """Remove oldest backups if count exceeds max_backups."""
    backups = get_backup_files()
    count = len(backups)

    print(f"Found {count} backup files (max allowed: {max_backups})")

    if count <= max_backups:
        print("✓ No rotation needed")
        return 0

    to_remove = backups[:count - max_backups]
    removed_count = 0

    for bak_file in to_remove:
        filename = os.path.basename(bak_file)
        mtime = os.path.getmtime(bak_file)
        from datetime import datetime
        date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

        if dry_run:
            print(f"  Would remove: {filename} ({date_str})")
        else:
            try:
                os.remove(bak_file)
                print(f"  Removed: {filename} ({date_str})")
                removed_count += 1
            except OSError as e:
                print(f"  ✗ Failed to remove {filename}: {e}")

    remaining = len(get_backup_files())
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Rotation complete: "
          f"{removed_count} removed, {remaining} remaining")

    return removed_count


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Rotate config.yaml backup files")
    parser.add_argument("--max-backups", type=int, default=MAX_BACKUPS,
                        help=f"Maximum number of backup files to keep (default: {MAX_BACKUPS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be removed without actually removing")

    args = parser.parse_args()

    if not CONFIG_DIR.exists():
        print(f"✗ Config directory not found: {CONFIG_DIR}")
        sys.exit(1)

    removed = rotate_backups(max_backups=args.max_backups, dry_run=args.dry_run)
    sys.exit(0)


if __name__ == "__main__":
    main()
