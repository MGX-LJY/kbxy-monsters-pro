# scripts/backup_sqlite.py
from __future__ import annotations
import os, sys, time, sqlite3, hashlib, argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List

# 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.app.config import settings  # noqa


# ---------- 工具函数 ----------

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_backups_dir() -> Path:
    d = PROJECT_ROOT / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def src_db_path() -> Path:
    # 仅支持本地 SQLite；如果你用的是外部数据库，此脚本不适用
    return settings.resolved_local_db_path()


def backup_filename(app_env: str, tag: str, when: datetime, counter: int | None = None) -> str:
    """
    tag:
      - manual: 手动一次性
      - chg   : 变更触发
      - day   : 每日备份（按日去重）
    """
    if tag == "manual":
        return f"kbxy-{app_env}-{when.strftime('%Y%m%d-%H%M%S')}.db"
    elif tag == "chg":
        suffix = f"-{counter:04d}" if counter is not None else ""
        return f"kbxy-{app_env}-chg-{when.strftime('%Y%m%d-%H%M%S')}{suffix}.db"
    elif tag == "day":
        # 每日备份：按“日”命名，天然去重
        return f"kbxy-{app_env}-day-{when.strftime('%Y%m%d')}.db"
    else:
        raise ValueError(f"unknown tag: {tag}")


def do_sqlite_backup(src: Path, dst: Path) -> str:
    with sqlite3.connect(str(src)) as conn_src:
        with sqlite3.connect(str(dst)) as conn_dst:
            conn_src.backup(conn_dst)
    digest = sha256_file(dst)
    (dst.with_suffix(".db.sha256")).write_text(digest)
    return digest


def prune_daily_by_age(backups_dir: Path, app_env: str, retention_days: int) -> int:
    """删除超过 N 天的每日备份（tag=day）"""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for f in sorted(backups_dir.glob(f"kbxy-{app_env}-day-*.db")):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            try:
                f.unlink(missing_ok=True)
                (f.with_suffix(".db.sha256")).unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    return removed


def prune_change_keep_max(backups_dir: Path, app_env: str, keep_max: int) -> int:
    """只保留最近 keep_max 份“变更备份”（tag=chg）"""
    files = sorted(backups_dir.glob(f"kbxy-{app_env}-chg-*.db"), key=lambda p: p.stat().st_mtime)
    removed = 0
    if keep_max > 0 and len(files) > keep_max:
        for f in files[: len(files) - keep_max]:
            try:
                f.unlink(missing_ok=True)
                (f.with_suffix(".db.sha256")).unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    return removed


def list_files(backups_dir: Path, pattern: str) -> List[Path]:
    return sorted(backups_dir.glob(pattern), key=lambda p: p.stat().st_mtime)


def today_daily_exists(backups_dir: Path, app_env: str) -> bool:
    name = backup_filename(app_env, "day", datetime.now())
    return (backups_dir / name).exists()


def get_data_version(conn: sqlite3.Connection) -> int:
    try:
        cur = conn.execute("PRAGMA data_version;")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def open_ro_connection(path: Path) -> sqlite3.Connection | None:
    # 只读连接，安全轮询 data_version
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    except Exception:
        return None


# ---------- 主逻辑 ----------

def run_once_manual(app_env: str, retention_days: int):
    src = src_db_path()
    backups_dir = ensure_backups_dir()
    if not src.exists():
        raise SystemExit(f"[backup] ERROR: source DB not found: {src}")

    now = datetime.now()
    dst = backups_dir / backup_filename(app_env, "manual", now)
    print(f"[backup] APP_ENV={app_env}")
    print(f"[backup] source: {src}")
    print(f"[backup] target: {dst}")
    digest = do_sqlite_backup(src, dst)
    print(f"[backup] done. sha256={digest}")

    # 每日保留策略只作用于每日备份，不清理手动备份
    removed = prune_daily_by_age(backups_dir, app_env, retention_days)
    if removed:
        print(f"[backup] pruned {removed} daily backup(s) older than {retention_days} days.")


def run_watch(app_env: str,
              poll_interval: float,
              change_keep_max: int,
              daily_retention_days: int,
              min_change_interval_sec: float):
    """
    守护监控模式：
    - 监听 PRAGMA data_version 变化 → 立即做“变更备份”（仅保留最近 change_keep_max 份）
    - 每日备份：每天 1 份（若当天尚未生成，启动时会先补一份），保留 daily_retention_days 天
    """
    backups_dir = ensure_backups_dir()
    src = src_db_path()

    print(f"[watch] APP_ENV={app_env}")
    print(f"[watch] src={src}")
    print(f"[watch] backups_dir={backups_dir}")
    print(f"[watch] poll_interval={poll_interval}s, change_keep_max={change_keep_max}, "
          f"daily_retention_days={daily_retention_days}, min_change_interval={min_change_interval_sec}s")

    # 等待 DB 文件出现
    while not src.exists():
        print("[watch] waiting for database to be created ...")
        time.sleep(1.5)

    conn = open_ro_connection(src)
    while conn is None:
        print("[watch] cannot open read-only connection, retry ...")
        time.sleep(2)
        conn = open_ro_connection(src)

    last_ver = get_data_version(conn)
    last_change_backup_ts = 0.0
    chg_counter = 0

    # 启动即补当日备份（若不存在）
    if not today_daily_exists(backups_dir, app_env):
        dst = backups_dir / backup_filename(app_env, "day", datetime.now())
        digest = do_sqlite_backup(src, dst)
        print(f"[watch] daily(bootstrap) => {dst.name} sha256={digest}")
        prune_daily_by_age(backups_dir, app_env, daily_retention_days)

    last_daily_date = date.today()

    try:
        while True:
            # 1) 监听 data_version
            ver = get_data_version(conn)
            if ver == -1:
                # 连接出错，尝试重连
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(1.5)
                conn = open_ro_connection(src)
                continue

            if last_ver != -1 and ver != last_ver:
                now_ts = time.time()
                if now_ts - last_change_backup_ts >= min_change_interval_sec:
                    chg_counter += 1
                    now = datetime.now()
                    dst = backups_dir / backup_filename(app_env, "chg", now, chg_counter)
                    digest = do_sqlite_backup(src, dst)
                    print(f"[watch] change => {dst.name} sha256={digest}")
                    last_change_backup_ts = now_ts
                    # 变更备份按“份数”保留
                    removed = prune_change_keep_max(backups_dir, app_env, change_keep_max)
                    if removed:
                        print(f"[watch] pruned {removed} old change backup(s) (keep_max={change_keep_max})")
                last_ver = ver

            # 2) 每日备份（跨天即备份）
            today = date.today()
            if today != last_daily_date:
                # 新的一天；若当天还没有 daily，就创建
                if not today_daily_exists(backups_dir, app_env):
                    dst = backups_dir / backup_filename(app_env, "day", datetime.now())
                    digest = do_sqlite_backup(src, dst)
                    print(f"[watch] daily => {dst.name} sha256={digest}")
                    pruned = prune_daily_by_age(backups_dir, app_env, daily_retention_days)
                    if pruned:
                        print(f"[watch] pruned {pruned} daily backup(s) older than {daily_retention_days} days.")
                last_daily_date = today

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("[watch] stopped by user.")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="SQLite backup tool (manual or watch mode).")
    parser.add_argument("--watch", action="store_true", help="守护监控模式：变更即备份 + 每日自动备份")
    parser.add_argument("--poll-interval", type=float, default=float(os.getenv("BACKUP_POLL_INTERVAL", "2.0")),
                        help="变更轮询间隔秒，默认 2.0")
    parser.add_argument("--change-keep-max", type=int, default=int(os.getenv("BACKUP_CHANGE_KEEP_MAX", "20")),
                        help="仅保留最近 N 份“变更备份”，默认 20")
    parser.add_argument("--daily-retention-days", type=int, default=int(os.getenv("BACKUP_RETENTION_DAYS", "30")),
                        help="每日备份保留天数，默认 30")
    parser.add_argument("--min-change-interval", type=float, default=float(os.getenv("BACKUP_MIN_CHANGE_INTERVAL", "2.0")),
                        help="两次“变更备份”之间的最小间隔秒，默认 2 秒（防抖）")
    args = parser.parse_args()

    app_env = os.getenv("APP_ENV", settings.app_env)

    if args.watch:
        run_watch(
            app_env=app_env,
            poll_interval=args.poll_interval,
            change_keep_max=args.change_keep_max,
            daily_retention_days=args.daily_retention_days,
            min_change_interval_sec=args.min_change_interval,
        )
    else:
        # 兼容旧用法：一次性备份 + 清理过期“每日备份”
        run_once_manual(app_env=app_env, retention_days=args.daily_retention_days)


if __name__ == "__main__":
    main()