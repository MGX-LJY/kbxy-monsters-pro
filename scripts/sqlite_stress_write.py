# scripts/sqlite_stress_write.py
from __future__ import annotations
import os, sqlite3, time, random, string, argparse, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from server.app.config import settings  # noqa

def rand_text(n=16) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))

def worker(db_path: Path, writes: int, busy_ms: int, connect_timeout_s: float) -> dict:
    ok = locked = other = 0
    latencies = []
    conn = sqlite3.connect(str(db_path), timeout=connect_timeout_s, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute(f"PRAGMA busy_timeout={int(busy_ms)};")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stress_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.commit()
    for _ in range(writes):
        t0 = time.perf_counter()
        try:
            cur.execute("INSERT INTO stress_log (ts, payload) VALUES (?, ?)", (time.time(), rand_text()))
            conn.commit()
            ok += 1
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                locked += 1
            else:
                other += 1
            # 稍作退避
            time.sleep(0.002 + random.random() * 0.003)
        finally:
            latencies.append((time.perf_counter() - t0) * 1000.0)
    try:
        cur.close(); conn.close()
    except Exception:
        pass
    return {"ok": ok, "locked": locked, "other": other, "p95": percentile(latencies, 95), "p99": percentile(latencies, 99), "avg": mean(latencies)}

def percentile(data, p):
    if not data:
        return 0.0
    data = sorted(data)
    k = int(round((p/100.0) * (len(data)-1)))
    return float(data[k])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8, help="并发线程数")
    ap.add_argument("--writes", type=int, default=500, help="每线程写入次数")
    ap.add_argument("--busy-ms", type=int, default=int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "4000")), help="每连接 busy_timeout（毫秒）")
    ap.add_argument("--connect-timeout", type=float, default=float(os.getenv("SQLITE_CONNECT_TIMEOUT_S", "5")), help="sqlite3.connect 超时（秒）")
    args = ap.parse_args()

    db_path = settings.resolved_local_db_path()
    print(f"[stress] DB: {db_path}")
    print(f"[stress] workers={args.workers} writes/worker={args.writes} busy_ms={args.busy_ms} connect_timeout_s={args.connect_timeout}")

    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(worker, db_path, args.writes, args.busy_ms, args.connect_timeout) for _ in range(args.workers)]
        for f in as_completed(futs):
            results.append(f.result())
    elapsed = time.perf_counter() - t0

    total_ok = sum(r["ok"] for r in results)
    total_locked = sum(r["locked"] for r in results)
    total_other = sum(r["other"] for r in results)
    all_avg = mean([r["avg"] for r in results])
    all_p95 = mean([r["p95"] for r in results])
    all_p99 = mean([r["p99"] for r in results])

    print("\n=== STRESS SUMMARY ===")
    print(f"elapsed: {elapsed:.2f}s")
    print(f"attempts: {args.workers*args.writes}, ok: {total_ok}, locked: {total_locked}, other: {total_other}")
    print(f"latency avg(ms): {all_avg:.2f}  p95(ms): {all_p95:.2f}  p99(ms): {all_p99:.2f}")
    print("======================")

if __name__ == "__main__":
    main()