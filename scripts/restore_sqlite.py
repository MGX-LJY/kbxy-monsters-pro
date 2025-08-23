# scripts/restore_sqlite.py
from __future__ import annotations
import os, shutil, sys, re, json
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.app.config import settings  # noqa

# ----------------- 通用恢复逻辑（CLI / UI 共用） -----------------

ENV_DB_FILENAMES = {"dev": "kbxy-dev.db", "test": "kbxy-test.db"}

def target_db_path_for_env(env: str) -> Path:
    """
    计算指定 env 的本地 SQLite 绝对路径：
    - 若设置了 KBXY_DB_PATH：将优先使用（注意：两个环境会指向同一文件）
    - 否则使用 <project>/data/kbxy-<env>.db
    """
    raw = os.getenv("KBXY_DB_PATH")
    if raw:
        p = Path(os.path.expanduser(raw))
        if not p.is_absolute():
            p = PROJECT_ROOT / "data" / p
        return p.resolve()
    filename = ENV_DB_FILENAMES.get(env, ENV_DB_FILENAMES["dev"])
    return (PROJECT_ROOT / "data" / filename).resolve()

def restore_from_backup(backup: Path, env: str) -> Tuple[Path, Optional[Path]]:
    """从备份文件恢复到 env 对应的目标库；返回 (target, bak_path_or_None)"""
    if not backup.exists():
        raise SystemExit(f"[restore] ERROR: backup file not found: {backup}")

    target = target_db_path_for_env(env)
    target.parent.mkdir(parents=True, exist_ok=True)

    bak_path: Optional[Path] = None
    if target.exists():
        bak_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, bak_path)
        print(f"[restore] current db saved as: {bak_path}")

    shutil.copy2(backup, target)
    print(f"[restore] restored -> {target}")
    return target, bak_path

# ----------------- 解析备份文件信息 -----------------

_TS_PATTERNS = [
    # kbxy-<env>-chg-YYYYMMDD-HHMMSS(-####).db
    re.compile(r"^kbxy-(?P<env>dev|test)-chg-(?P<date>\d{8})-(?P<time>\d{6})(?:-\d{4})?\.db$"),
    # kbxy-<env>-day-YYYYMMDD.db
    re.compile(r"^kbxy-(?P<env>dev|test)-day-(?P<date>\d{8})\.db$"),
    # kbxy-<env>-YYYYMMDD-HHMMSS.db  (手动备份)
    re.compile(r"^kbxy-(?P<env>dev|test)-(?P<date>\d{8})-(?P<time>\d{6})\.db$"),
]

def parse_backup_meta(p: Path) -> Optional[dict]:
    name = p.name
    tag = "manual"
    ts: Optional[datetime] = None
    matched_env: Optional[str] = None

    for pat in _TS_PATTERNS:
        m = pat.match(name)
        if not m:
            continue
        matched_env = m.group("env")
        if "time" in m.groupdict():
            ts = datetime.strptime(m.group("date") + m.group("time"), "%Y%m%d%H%M%S")
        else:
            ts = datetime.strptime(m.group("date"), "%Y%m%d")
            tag = "day"
        if "chg" in name:
            tag = "chg"
        break

    if matched_env is None:
        return None

    # 读取校验和（若存在）
    sha = None
    sha_file = p.with_suffix(".db.sha256")
    if sha_file.exists():
        try:
            sha = sha_file.read_text().strip()
        except Exception:
            sha = None

    return {
        "path": str(p),
        "env": matched_env,
        "name": name,
        "tag": tag,
        "ts": ts.isoformat() if ts else None,
        "size": p.stat().st_size,
        "sha256": sha,
        "mtime": p.stat().st_mtime,
    }

def scan_backups(env: str) -> List[dict]:
    backups_dir = PROJECT_ROOT / "backups"
    backups_dir.mkdir(exist_ok=True)
    items: List[dict] = []
    for p in backups_dir.glob(f"kbxy-{env}-*.db"):
        meta = parse_backup_meta(p)
        if meta:
            items.append(meta)
    # 按时间倒序（优先 ts，其次 mtime）
    items.sort(key=lambda x: (x.get("ts") or "", x["mtime"]), reverse=True)
    return items

# ----------------- CLI 模式 -----------------

def cli_main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--ui", "-u"):
        return False  # 进入 UI
    backup = Path(sys.argv[1]).resolve()
    env = os.getenv("APP_ENV", settings.app_env if settings.app_env in ("dev", "test") else "dev")
    print(f"[restore] APP_ENV={env}")
    print(f"[restore] from: {backup}")
    target = target_db_path_for_env(env)
    print(f"[restore] to:   {target}")
    restore_from_backup(backup, env)
    print("[restore] done. Please restart your server if it is running.")
    return True

# ----------------- UI 模式（tkinter） -----------------

def ui_main():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
    except Exception as e:
        raise SystemExit(f"tkinter is required for UI mode. {e}")

    root = tk.Tk()
    root.title("KBXY · 恢复数据库（SQLite）")

    # 环境选择
    current_env = tk.StringVar(value=os.getenv("APP_ENV", settings.app_env if settings.app_env in ("dev", "test") else "dev"))
    kbxy_path_note = tk.StringVar(value="")

    def update_target_label(*_):
        target = target_db_path_for_env(current_env.get())
        note = ""
        if os.getenv("KBXY_DB_PATH"):
            note = "（已设置 KBXY_DB_PATH，dev/test 指向同一文件）"
        kbxy_path_note.set(f"目标 DB：{target} {note}")

    # 顶部：环境 + 操作按钮
    frm_top = ttk.Frame(root, padding=10); frm_top.pack(fill="x")
    ttk.Label(frm_top, text="环境：").pack(side="left")
    env_combo = ttk.Combobox(frm_top, textvariable=current_env, values=["dev", "test"], width=8, state="readonly")
    env_combo.pack(side="left", padx=(0,10))
    btn_refresh = ttk.Button(frm_top, text="刷新列表")
    btn_open_dir = ttk.Button(frm_top, text="打开备份目录")
    btn_pick_file = ttk.Button(frm_top, text="选择本地文件…")
    btn_refresh.pack(side="left", padx=5)
    btn_open_dir.pack(side="left", padx=5)
    btn_pick_file.pack(side="left", padx=5)

    # 目标路径提示
    lbl_target = ttk.Label(root, textvariable=kbxy_path_note, padding=(10,2)); lbl_target.pack(anchor="w")
    update_target_label()
    env_combo.bind("<<ComboboxSelected>>", update_target_label)

    # 表格
    cols = ("when", "tag", "name", "size", "sha")
    tree = ttk.Treeview(root, columns=cols, show="headings", height=14)
    tree.pack(fill="both", expand=True, padx=10, pady=(5,5))
    headings = {
        "when": "时间",
        "tag": "类型",
        "name": "文件",
        "size": "大小",
        "sha": "SHA256(前10)"
    }
    for k in cols:
        tree.heading(k, text=headings[k])
        tree.column(k, width=160 if k=="name" else 110, anchor="w")
    tree.column("name", width=360)

    # 底部按钮
    frm_bottom = ttk.Frame(root, padding=10); frm_bottom.pack(fill="x")
    btn_verify = ttk.Button(frm_bottom, text="校验选中 SHA256")
    btn_restore = ttk.Button(frm_bottom, text="恢复到目标环境")
    btn_close = ttk.Button(frm_bottom, text="关闭", command=root.destroy)
    btn_verify.pack(side="left")
    btn_restore.pack(side="right")
    btn_close.pack(side="right", padx=(0,10))

    # 状态栏
    status_var = tk.StringVar(value="")
    status = ttk.Label(root, textvariable=status_var, padding=(10,5))
    status.pack(fill="x")

    # 数据集
    current_items: List[dict] = []

    def human_size(n: int) -> str:
        for unit in ("B","KB","MB","GB","TB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.0f} PB"

    def fmt_when(meta: dict) -> str:
        if meta.get("ts"):
            try:
                dt = datetime.fromisoformat(meta["ts"])
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        # 兜底用 mtime
        return datetime.fromtimestamp(meta["mtime"]).strftime("%Y-%m-%d %H:%M:%S")

    def load_table(env: str):
        nonlocal current_items
        tree.delete(*tree.get_children())
        current_items = scan_backups(env)
        for meta in current_items:
            sha = meta["sha256"][:10] + "…" if meta.get("sha256") else ""
            tree.insert("", "end", values=(fmt_when(meta), meta["tag"], meta["name"], human_size(meta["size"]), sha))
        status_var.set(f"共 {len(current_items)} 个备份（环境：{env}）")

    def get_selected_meta() -> Optional[dict]:
        sel = tree.selection()
        if not sel:
            return None
        idx = tree.index(sel[0])
        if idx < 0 or idx >= len(current_items):
            return None
        return current_items[idx]

    def on_refresh():
        load_table(current_env.get())
        update_target_label()

    def on_open_dir():
        backups_dir = PROJECT_ROOT / "backups"
        backups_dir.mkdir(exist_ok=True)
        # 尝试用系统文件管理器打开
        if sys.platform.startswith("darwin"):
            os.system(f'open "{backups_dir}"')
        elif os.name == "nt":
            os.startfile(str(backups_dir))  # type: ignore[attr-defined]
        else:
            os.system(f'xdg-open "{backups_dir}" || true')

    def on_pick_file():
        path = filedialog.askopenfilename(
            title="选择本地备份文件",
            initialdir=str(PROJECT_ROOT / "backups"),
            filetypes=[("SQLite backup", "*.db"), ("All files","*.*")]
        )
        if not path:
            return
        p = Path(path)
        meta = parse_backup_meta(p) or {
            "path": str(p),
            "env": current_env.get(),
            "name": p.name,
            "tag": "manual",
            "ts": None,
            "size": p.stat().st_size,
            "sha256": None,
            "mtime": p.stat().st_mtime,
        }
        # 临时插到表格顶部
        current_items.insert(0, meta)
        tree.insert("", 0, values=(fmt_when(meta), meta["tag"], meta["name"], human_size(meta["size"]), ""))
        status_var.set(f"已选择自定义文件：{p.name}")

    def on_verify_sha():
        meta = get_selected_meta()
        if not meta:
            messagebox.showwarning("提示", "请先选择一条备份。")
            return
        p = Path(meta["path"])
        sha_file = p.with_suffix(".db.sha256")
        if not sha_file.exists():
            messagebox.showinfo("校验", "未找到同名 .sha256 文件。")
            return
        expect = sha_file.read_text().strip()
        # 计算实际 SHA
        import hashlib
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual == expect:
            messagebox.showinfo("校验成功", f"SHA256 一致：\n{actual}")
        else:
            messagebox.showerror("校验失败", f"期望：{expect}\n实际：{actual}")

    def on_restore():
        meta = get_selected_meta()
        if not meta:
            messagebox.showwarning("提示", "请先选择一条备份。")
            return
        env = current_env.get()
        backup = Path(meta["path"]).resolve()
        target = target_db_path_for_env(env)

        warn = ""
        if os.getenv("DATABASE_URL"):
            warn = "\n⚠️ 检测到 DATABASE_URL 已设置：当前脚本只支持本地 SQLite 文件的恢复。"

        ok = messagebox.askyesno(
            "请确认恢复",
            f"将把以下备份覆盖到 {env} 环境的数据库：\n\n"
            f"备份文件：{backup}\n"
            f"目标文件：{target}\n{warn}\n\n"
            f"建议已停止后端服务再恢复。确定继续吗？"
        )
        if not ok:
            return
        try:
            target2, bak = restore_from_backup(backup, env)
            msg = f"恢复完成：\n目标：{target2}"
            if bak:
                msg += f"\n已留当前库备份：{bak}"
            msg += "\n\n请重启你的后端服务。"
            messagebox.showinfo("完成", msg)
        except Exception as e:
            messagebox.showerror("失败", f"恢复失败：\n{e}")

    btn_refresh.configure(command=on_refresh)
    btn_open_dir.configure(command=on_open_dir)
    btn_pick_file.configure(command=on_pick_file)
    btn_verify.configure(command=on_verify_sha)
    btn_restore.configure(command=on_restore)

    # 初次载入
    on_refresh()
    root.mainloop()

# ----------------- 入口 -----------------

def main():
    # CLI 有路径参数则走命令行；否则进入 UI（或 --ui 明确指定）
    if not cli_main():
        ui_main()

if __name__ == "__main__":
    main()