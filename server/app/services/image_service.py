# server/app/services/image_service.py
from __future__ import annotations
import os, re
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from difflib import SequenceMatcher

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def normalize_name(s: str) -> str:
    """
    做轻量归一化：去空白、去常见标点、全小写，仅保留中英文数字。
    """
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[\\/:*?\"<>|()\[\]{}·—\-_.\s]+", "", s)
    # 仅保留中英文和数字（中文范围 \u4e00-\u9fa5 够用）
    s = re.sub(r"[^a-z0-9\u4e00-\u9fa5]", "", s)
    return s

class ImageResolver:
    def __init__(self, dir_path: Path, public_mount: str = "/media/monsters"):
        self.dir_path = Path(dir_path)
        self.public_mount = public_mount.rstrip("/")
        self._index: Dict[str, str] = {}  # key=normalized base name, val=relative file name (with ext)

    def reindex(self) -> int:
        """
        扫描目录建立索引：文件名（去扩展名）-> 文件相对名（含扩展名）
        """
        self._index.clear()
        if not self.dir_path.exists():
            self.dir_path.mkdir(parents=True, exist_ok=True)

        for p in self.dir_path.glob("*"):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in ALLOWED_EXTS:
                continue
            base = p.stem
            key = normalize_name(base)
            if not key:
                continue
            # 后写覆盖前写：让你手工替换图片时，以最新为准
            self._index[key] = p.name
        return len(self._index)

    def _score(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def resolve_by_names(self, names: List[str]) -> Optional[str]:
        """
        尝试多种候选名（Monster.name、别名等）找到最佳图片。
        返回可直接给前端用的 URL（/media/monsters/xxx.jpg），找不到返回 None。
        """
        if not self._index:
            self.reindex()

        # 1) 先精确（归一化后完全一致）
        norm_candidates = [normalize_name(n) for n in names if n]
        for nc in norm_candidates:
            if nc in self._index:
                return f"{self.public_mount}/{self._index[nc]}"

        # 2) 再包含匹配（名字包含于文件名，或文件名包含于名字）
        for nc in norm_candidates:
            # 文件名包含名字
            hits = [fname for k, fname in self._index.items() if nc and nc in k]
            if hits:
                # 长度越接近越好，或默认取第一个
                best = sorted(hits, key=lambda x: abs(len(Path(x).stem) - len(nc)))[0]
                return f"{self.public_mount}/{best}"

            # 名字包含文件名（较少见）
            hits = [fname for k, fname in self._index.items() if k and k in nc]
            if hits:
                best = sorted(hits, key=lambda x: -len(Path(x).stem))[0]
                return f"{self.public_mount}/{best}"

        # 3) 模糊相似度（阈值可调）
        best: Tuple[float, Optional[str]] = (0.0, None)
        for nc in norm_candidates:
            for k, fname in self._index.items():
                sc = self._score(nc, k)
                if sc > best[0]:
                    best = (sc, fname)
        if best[0] >= 0.72 and best[1]:
            return f"{self.public_mount}/{best[1]}"

        return None

# ---- 单例获取 ----
_resolver: Optional[ImageResolver] = None

def get_image_resolver() -> ImageResolver:
    global _resolver
    if _resolver is None:
        base = os.getenv("KBXY_IMAGES_DIR")
        if base:
            dir_path = Path(base)
        else:
            # 默认：项目根/server/images/monsters
            here = Path(__file__).resolve().parents[2]
            dir_path = here / "images" / "monsters"
        _resolver = ImageResolver(dir_path)
        _resolver.reindex()
    return _resolver