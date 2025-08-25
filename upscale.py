#!/usr/bin/env python3
import os, io, subprocess, tempfile, argparse, sys, math
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageSequence

# —— 可选：云端 Real-ESRGAN（付费/按量） ——
USE_REPLICATE = False
try:
    import replicate  # pip install replicate
    USE_REPLICATE = True
except Exception:
    pass

# —— 可选：抠图（背景透明） ——
HAVE_REMBG = False
try:
    from rembg import remove as rembg_remove  # pip install rembg
    HAVE_REMBG = True
except Exception:
    pass

REPLICATE_MODEL = "nightmareai/real-esrgan"
REPLICATE_VERSION = None  # 用最新
IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def is_gif(p: Path) -> bool:
    return p.suffix.lower() == ".gif"

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def run_waifu2x(src: Path, dst_png: Path, scale: int, noise: int = -1,
                model: str = "models-cunet", jobs: str | None = None, tile: int | None = None):
    """调用 waifu2x-ncnn-vulkan，统一输出 PNG。"""
    cmd = ["waifu2x-ncnn-vulkan", "-i", str(src), "-o", str(dst_png), "-s", str(scale), "-n", str(noise), "-m", model, "-f", "png"]
    if jobs: cmd += ["-j", jobs]        # 例如 "2:2:2"
    if tile: cmd += ["-t", str(tile)]   # 例如 100 / 128
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("找不到 waifu2x-ncnn-vulkan，请先确保它在 PATH 里。", file=sys.stderr)
        sys.exit(1)

def replicate_upscale(pil_im: Image.Image, scale: int, face_enhance: bool = False) -> Image.Image:
    if not USE_REPLICATE:
        raise RuntimeError("未安装 replicate 或未设置 REPLICATE_API_TOKEN")
    buf = io.BytesIO(); pil_im.save(buf, format="PNG"); buf.seek(0)
    client = replicate.Client()
    inputs = {"image": buf, "scale": scale, "face_enhance": face_enhance}
    if REPLICATE_VERSION:
        out_url = client.run(f"{REPLICATE_MODEL}:{REPLICATE_VERSION}", input=inputs)
    else:
        out_url = client.run(f"{REPLICATE_MODEL}", input=inputs)
    import requests
    r = requests.get(out_url, timeout=180); r.raise_for_status()
    o = Image.open(io.BytesIO(r.content))
    return o.convert("RGBA" if pil_im.mode in ("RGBA", "P") else "RGB")

def integer_scale_for_sprite(w: int, h: int, target_scale: int, max_mul: int = 4) -> int:
    for mul in range(min(max_mul, target_scale), 1, -1):
        if target_scale % mul == 0:
            return mul
    return 2 if target_scale >= 2 else 1

def remove_bg_pil(img: Image.Image) -> Image.Image:
    if not HAVE_REMBG:
        return img
    try:
        buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
        out_bytes = rembg_remove(buf.getvalue())
        out = Image.open(io.BytesIO(out_bytes))
        return out.convert("RGBA")
    except Exception:
        return img

def read_gif_frames(p: Path) -> Tuple[List[Image.Image], List[int]]:
    im = Image.open(p)
    frames, durations = [], []
    for frame in ImageSequence.Iterator(im):
        frames.append(frame.convert("RGBA"))
        durations.append(frame.info.get("duration", 80))
    return frames, durations

def frame_entropy(img: Image.Image) -> float:
    hist = img.convert("L").histogram(); total = sum(hist)
    if total == 0: return 0.0
    import math
    ent = 0.0
    for c in hist:
        if c:
            p = c / total
            ent -= p * math.log2(p)
    return ent

def pick_best_frame(frames: List[Image.Image]) -> Image.Image:
    try:
        idx = max(range(len(frames)), key=lambda i: frame_entropy(frames[i]))
        return frames[idx]
    except Exception:
        return frames[0]

def upscale_image_still(src: Path, dst_png: Path, backend: str, scale: int, pixel_mode: bool,
                        remove_bg_flag: bool, waifu_jobs: str | None, waifu_tile: int | None):
    ensure_dir(dst_png.parent)
    if backend == "waifu2x":
        with tempfile.TemporaryDirectory() as td:
            tmp_in = Path(td) / "in.png"
            Image.open(src).save(tmp_in, "PNG")
            run_waifu2x(tmp_in, dst_png, scale=scale, noise=-1, model="models-cunet",
                        jobs=waifu_jobs, tile=waifu_tile)
            img = Image.open(dst_png).convert("RGBA")
    else:
        img = Image.open(src).convert("RGBA")
        if pixel_mode:
            mul = integer_scale_for_sprite(img.width, img.height, scale)
            if mul > 1:
                img = img.resize((img.width * mul, img.height * mul), resample=Image.NEAREST)
        img = replicate_upscale(img, scale=max(2, min(scale, 4)))
        img.save(dst_png, "PNG")
        img = Image.open(dst_png).convert("RGBA")

    if remove_bg_flag:
        img = remove_bg_pil(img)
        img.save(dst_png, "PNG")
    else:
        img.save(dst_png, "PNG")

def upscale_image_gif_to_still(src: Path, dst_png: Path, backend: str, scale: int, pixel_mode: bool,
                               remove_bg_flag: bool, waifu_jobs: str | None, waifu_tile: int | None):
    frames, _ = read_gif_frames(src)
    key = pick_best_frame(frames)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "key.png"
        key.save(tmp, "PNG")
        upscale_image_still(tmp, dst_png, backend, scale, pixel_mode, remove_bg_flag, waifu_jobs, waifu_tile)

def process_path(in_path: Path, out_dir: Path, backend: str, scale: int, pixel_mode: bool,
                 remove_bg_flag: bool, waifu_jobs: str | None, waifu_tile: int | None):
    if in_path.is_dir():
        files = [p for p in in_path.rglob("*") if p.suffix.lower() in IMG_EXTS]
        for p in files:
            rel = p.relative_to(in_path)
            dst = (out_dir / rel).with_suffix(".png")
            ensure_dir(dst.parent)
            if is_gif(p):
                upscale_image_gif_to_still(p, dst, backend, scale, pixel_mode, remove_bg_flag, waifu_jobs, waifu_tile)
            else:
                upscale_image_still(p, dst, backend, scale, pixel_mode, remove_bg_flag, waifu_jobs, waifu_tile)
    else:
        dst = out_dir / (in_path.stem + ".png")
        if is_gif(in_path):
            upscale_image_gif_to_still(in_path, dst, backend, scale, pixel_mode, remove_bg_flag, waifu_jobs, waifu_tile)
        else:
            upscale_image_still(in_path, dst, backend, scale, pixel_mode, remove_bg_flag, waifu_jobs, waifu_tile)

def main():
    ap = argparse.ArgumentParser(description="批量 AI 超分：去锐化；可抠图透明；GIF 输出单张高清 PNG")
    ap.add_argument("input", type=Path, help="输入文件或文件夹")
    ap.add_argument("output", type=Path, help="输出文件夹")
    ap.add_argument("--backend", choices=["waifu2x", "replicate"], default="waifu2x")
    ap.add_argument("--scale", type=int, default=2, choices=[2,3,4], help="放大倍率")
    ap.add_argument("--pixel", action="store_true", help="像素风优先：先做整数倍最近邻，边缘更利落")
    ap.add_argument("--remove-bg", action="store_true", help="抠图：去背景为透明（需要 rembg）")
    ap.add_argument("--waifu-j", type=str, default=None, help="waifu2x -j，例如 2:2:2")
    ap.add_argument("--waifu-tile", type=int, default=None, help="waifu2x -t tilesize，例如 100/128 防 OOM")
    args = ap.parse_args()

    process_path(args.input, args.output, backend=args.backend, scale=args.scale, pixel_mode=args.pixel,
                 remove_bg_flag=args.remove_bg, waifu_jobs=args.waifu_j, waifu_tile=args.waifu_tile)
    print("✅ 完成！输出在：", args.output)

if __name__ == "__main__":
    main()