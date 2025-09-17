#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import threading
import subprocess
import shlex
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import shutil

APP_TITLE = "批量超分前端 · UpScaler GUI"
HERE = Path(__file__).resolve().parent
CLI_SCRIPT = HERE / "upscale_batch.py"
SETTINGS_FILE = HERE / "gui_settings.json"

def which(cmd: str) -> str | None:
    return shutil.which(cmd)

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_settings(d: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x640")
        self.minsize(820, 640)

        self.proc: subprocess.Popen | None = None
        self.running = False

        self.settings = load_settings()

        self.create_widgets()
        self.restore_settings()
        self.update_waifu2x_status()

    # ---------- UI ----------
    def create_widgets(self):
        pad = {"padx": 8, "pady": 6}

        # 路径区域
        frm_paths = ttk.LabelFrame(self, text="路径")
        frm_paths.pack(fill="x", **pad)

        # 输入类型（文件 / 文件夹）
        self.input_kind = tk.StringVar(value="dir")
        rb_file = ttk.Radiobutton(frm_paths, text="单个文件", variable=self.input_kind, value="file")
        rb_dir  = ttk.Radiobutton(frm_paths, text="文件夹",   variable=self.input_kind, value="dir")
        rb_file.grid(row=0, column=0, sticky="w", **pad)
        rb_dir.grid(row=0, column=1, sticky="w", **pad)

        # 输入路径
        ttk.Label(frm_paths, text="输入路径：").grid(row=1, column=0, sticky="e", **pad)
        self.in_path_var = tk.StringVar()
        ent_in = ttk.Entry(frm_paths, textvariable=self.in_path_var, width=80)
        ent_in.grid(row=1, column=1, sticky="we", **pad, columnspan=3)
        btn_in = ttk.Button(frm_paths, text="选择…", command=self.choose_input)
        btn_in.grid(row=1, column=4, **pad)

        # 输出文件夹
        ttk.Label(frm_paths, text="输出文件夹：").grid(row=2, column=0, sticky="e", **pad)
        self.out_path_var = tk.StringVar()
        ent_out = ttk.Entry(frm_paths, textvariable=self.out_path_var, width=80)
        ent_out.grid(row=2, column=1, sticky="we", **pad, columnspan=3)
        btn_out = ttk.Button(frm_paths, text="选择…", command=self.choose_output)
        btn_out.grid(row=2, column=4, **pad)

        frm_paths.columnconfigure(1, weight=1)
        frm_paths.columnconfigure(2, weight=1)
        frm_paths.columnconfigure(3, weight=1)

        # 选项区域
        frm_opts = ttk.LabelFrame(self, text="参数")
        frm_opts.pack(fill="x", **pad)

        # backend
        ttk.Label(frm_opts, text="后端：").grid(row=0, column=0, sticky="e", **pad)
        self.backend_var = tk.StringVar(value="waifu2x")
        cb_backend = ttk.Combobox(frm_opts, textvariable=self.backend_var, values=["waifu2x", "replicate"], state="readonly", width=12)
        cb_backend.grid(row=0, column=1, sticky="w", **pad)
        cb_backend.bind("<<ComboboxSelected>>", lambda e: self.on_backend_changed())

        # scale
        ttk.Label(frm_opts, text="倍率：").grid(row=0, column=2, sticky="e", **pad)
        self.scale_var = tk.IntVar(value=2)
        frm_scale = ttk.Frame(frm_opts)
        frm_scale.grid(row=0, column=3, sticky="w", **pad)
        for s in (2, 3, 4):
            ttk.Radiobutton(frm_scale, text=str(s), value=s, variable=self.scale_var).pack(side="left")

        # pixel / remove-bg
        self.pixel_var = tk.BooleanVar(value=False)
        self.rembg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opts, text="像素风优先（--pixel）", variable=self.pixel_var).grid(row=1, column=0, sticky="w", **pad, columnspan=2)
        ttk.Checkbutton(frm_opts, text="抠图去背景（--remove-bg）", variable=self.rembg_var).grid(row=1, column=2, sticky="w", **pad, columnspan=2)

        # waifu2x 高级参数
        ttk.Label(frm_opts, text="waifu -j：").grid(row=2, column=0, sticky="e", **pad)
        self.waifu_j_var = tk.StringVar(value="")
        ttk.Entry(frm_opts, textvariable=self.waifu_j_var, width=16).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(frm_opts, text="waifu -t：").grid(row=2, column=2, sticky="e", **pad)
        self.waifu_t_var = tk.StringVar(value="")
        ttk.Entry(frm_opts, textvariable=self.waifu_t_var, width=16).grid(row=2, column=3, sticky="w", **pad)

        # replicate token（可选）
        ttk.Label(frm_opts, text="REPLICATE_API_TOKEN：").grid(row=3, column=0, sticky="e", **pad)
        self.replicate_token_var = tk.StringVar(value=os.environ.get("REPLICATE_API_TOKEN", ""))
        ent_tok = ttk.Entry(frm_opts, textvariable=self.replicate_token_var, width=50, show="•")
        ent_tok.grid(row=3, column=1, sticky="w", **pad, columnspan=2)
        ttk.Button(frm_opts, text="应用到环境", command=self.apply_replicate_token).grid(row=3, column=3, sticky="w", **pad)

        # waifu2x 检测
        self.waifu_status_var = tk.StringVar(value="")
        lbl_waifu = ttk.Label(frm_opts, textvariable=self.waifu_status_var, foreground="#666")
        lbl_waifu.grid(row=4, column=0, sticky="w", **pad, columnspan=4)

        for i in range(4):
            frm_opts.columnconfigure(i, weight=1)

        # 操作区域
        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", **pad)
        self.btn_run = ttk.Button(frm_actions, text="开始处理", command=self.on_run, style="Success.TButton")
        self.btn_run.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(frm_actions, text="停止", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_open_out = ttk.Button(frm_actions, text="打开输出文件夹", command=self.open_output)
        self.btn_open_out.pack(side="left", padx=4)

        self.prog = ttk.Progressbar(frm_actions, mode="indeterminate")
        self.prog.pack(side="right", fill="x", expand=True, padx=4)

        # 日志
        frm_log = ttk.LabelFrame(self, text="日志")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log = ScrolledText(frm_log, height=18)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_insert("💡 准备就绪。\n")

    # ---------- helpers ----------
    def log_insert(self, s: str):
        self.log.insert("end", s)
        self.log.see("end")

    def choose_input(self):
        if self.input_kind.get() == "file":
            path = filedialog.askopenfilename(
                title="选择输入文件",
                filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.gif"), ("All files", "*.*")]
            )
        else:
            path = filedialog.askdirectory(title="选择输入文件夹")
        if path:
            self.in_path_var.set(path)

    def choose_output(self):
        path = filedialog.askdirectory(title="选择输出文件夹")
        if path:
            self.out_path_var.set(path)

    def apply_replicate_token(self):
        token = self.replicate_token_var.get().strip()
        if token:
            os.environ["REPLICATE_API_TOKEN"] = token
            self.log_insert("✅ 已设置 REPLICATE_API_TOKEN（仅当前进程）。\n")
        else:
            if "REPLICATE_API_TOKEN" in os.environ:
                del os.environ["REPLICATE_API_TOKEN"]
            self.log_insert("ℹ️ 已清空 REPLICATE_API_TOKEN。\n")

    def open_output(self):
        out_dir = self.out_path_var.get().strip()
        if not out_dir:
            messagebox.showinfo("提示", "请先选择输出文件夹")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", out_dir])
        elif os.name == "nt":
            os.startfile(out_dir)  # type: ignore
        else:
            subprocess.run(["xdg-open", out_dir])

    def on_backend_changed(self):
        backend = self.backend_var.get()
        if backend == "waifu2x":
            self.update_waifu2x_status()
        else:
            self.waifu_status_var.set("使用 replicate（云端 Real-ESRGAN）。需要有效的 REPLICATE_API_TOKEN。")

    def update_waifu2x_status(self):
        path = which("waifu2x-ncnn-vulkan")
        if path:
            self.waifu_status_var.set(f"waifu2x-ncnn-vulkan 已找到：{path}")
        else:
            self.waifu_status_var.set("⚠️ 未检测到 waifu2x-ncnn-vulkan（请先安装并加入 PATH）。")

    # ---------- run/stop ----------
    def set_running(self, flag: bool):
        self.running = flag
        state = "disabled" if flag else "normal"
        for w in (self.btn_run,):
            w.config(state=("disabled" if flag else "normal"))
        self.btn_stop.config(state=("normal" if flag else "disabled"))
        if flag:
            self.prog.start(10)
        else:
            self.prog.stop()
        # 禁用表单控件
        controls = [
            self.backend_var, self.scale_var, self.pixel_var, self.rembg_var,
            self.waifu_j_var, self.waifu_t_var, self.input_kind, self.in_path_var, self.out_path_var
        ]
        # 通过遍历窗口内所有控件更稳妥
        def set_children_state(parent, st):
            for child in parent.winfo_children():
                try:
                    child.configure(state=st)
                except tk.TclError:
                    pass
                set_children_state(child, st)
        set_children_state(self, "disabled" if flag else "normal")
        # 但仍把日志和停止按钮恢复为可用
        self.log.configure(state="normal")
        self.btn_stop.configure(state=("normal" if flag else "disabled"))

    def assemble_cmd(self) -> list[str]:
        in_path = self.in_path_var.get().strip()
        out_dir = self.out_path_var.get().strip()
        if not in_path or not out_dir:
            raise ValueError("请输入/选择 输入路径 与 输出文件夹。")
        if not Path(in_path).exists():
            raise ValueError("输入路径不存在。")
        if not Path(out_dir).exists():
            try:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"无法创建输出文件夹：{e}")

        backend = self.backend_var.get()
        scale = str(self.scale_var.get())
        args = [sys.executable, str(CLI_SCRIPT), in_path, out_dir, "--backend", backend, "--scale", scale]
        if self.pixel_var.get():
            args.append("--pixel")
        if self.rembg_var.get():
            args.append("--remove-bg")
        j = self.waifu_j_var.get().strip()
        if j:
            args += ["--waifu-j", j]
        t = self.waifu_t_var.get().strip()
        if t:
            args += ["--waifu-tile", t]
        return args

    def on_run(self):
        if not CLI_SCRIPT.exists():
            messagebox.showerror("错误", f"未找到处理脚本：{CLI_SCRIPT}")
            return
        try:
            cmd = self.assemble_cmd()
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return

        # 保存设置
        self.save_current_settings()

        self.log_insert("\n▶️ 开始执行：\n" + " ".join(shlex.quote(x) for x in cmd) + "\n")
        self.set_running(True)

        def worker():
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                assert self.proc.stdout is not None
                for line in self.proc.stdout:
                    self.log_insert(line)
                code = self.proc.wait()
                if code == 0:
                    self.log_insert("✅ 处理完成。\n")
                else:
                    self.log_insert(f"❌ 处理失败，退出码：{code}\n")
            except Exception as e:
                self.log_insert(f"❌ 运行异常：{e}\n")
            finally:
                self.set_running(False)
                self.proc = None

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self):
        if self.proc and self.running:
            try:
                self.proc.terminate()
                self.log_insert("🛑 已发送终止信号。\n")
            except Exception as e:
                self.log_insert(f"❌ 终止失败：{e}\n")

    # ---------- settings ----------
    def restore_settings(self):
        s = self.settings
        self.in_path_var.set(s.get("in_path", ""))
        self.out_path_var.set(s.get("out_path", ""))
        self.input_kind.set(s.get("input_kind", "dir"))
        self.backend_var.set(s.get("backend", "waifu2x"))
        self.scale_var.set(int(s.get("scale", 2)))
        self.pixel_var.set(bool(s.get("pixel", False)))
        self.rembg_var.set(bool(s.get("remove_bg", False)))
        self.waifu_j_var.set(s.get("waifu_j", ""))
        self.waifu_t_var.set(s.get("waifu_tile", ""))
        tok = s.get("replicate_token", "")
        if tok and not os.environ.get("REPLICATE_API_TOKEN"):
            self.replicate_token_var.set(tok)

    def save_current_settings(self):
        s = {
            "in_path": self.in_path_var.get().strip(),
            "out_path": self.out_path_var.get().strip(),
            "input_kind": self.input_kind.get(),
            "backend": self.backend_var.get(),
            "scale": int(self.scale_var.get()),
            "pixel": bool(self.pixel_var.get()),
            "remove_bg": bool(self.rembg_var.get()),
            "waifu_j": self.waifu_j_var.get().strip(),
            "waifu_tile": self.waifu_t_var.get().strip(),
            "replicate_token": self.replicate_token_var.get().strip(),
        }
        save_settings(s)

if __name__ == "__main__":
    app = App()
    try:
        # mac 上默认 ttk 按钮样式微调（可选）
        style = ttk.Style()
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Success.TButton", font=("Helvetica", 12, "bold"))
    except Exception:
        pass
    app.mainloop()