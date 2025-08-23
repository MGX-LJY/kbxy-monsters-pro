# scripts/seed_from_export.py
from __future__ import annotations
import json, csv, sys, os
from pathlib import Path
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = PROJECT_ROOT / "exports"
DEFAULT_DST = PROJECT_ROOT / "seed"
DEFAULT_MAPPING = {
    "types": {
        "id": ["id", "type_id"],
        "name": ["name", "type_name"],
    },
    "monsters": {
        "id": ["id", "monster_id"],
        "name": ["name", "monster_name"],
        "type_id": ["type_id", "element_id", "category_id"],
        "rarity": ["rarity", "star", "stars"],
    },
    "skills": {
        "id": ["id", "skill_id"],
        "monster_id": ["monster_id"],
        "name": ["name", "skill_name"],
        "power": ["power", "atk", "attack"],
    },
    "collections": {
        "id": ["id", "collection_id"],
        "monster_id": ["monster_id"],
        "note": ["note", "remark", "memo"],
    },
}

DATASETS = ["types", "monsters", "skills", "collections"]

def load_mapping(mapping_path: Path | None) -> dict:
    if mapping_path and mapping_path.exists():
        with mapping_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_MAPPING

def _coerce_int(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return v

def normalize_row(row: dict, mapping: dict[str, list[str]], dataset: str) -> dict:
    out = {}
    for std_key, aliases in mapping.items():
        # 按优先级取第一个存在的列
        value = None
        for a in aliases:
            if a in row and row[a] not in (None, ""):
                value = row[a]
                break
        # 类型粗转换
        if std_key in ("id", "type_id", "monster_id", "power", "rarity"):
            value = _coerce_int(value)
        out[std_key] = value
    # 清理全空的键
    return {k: v for k, v in out.items() if v is not None}

def read_any_table(path: Path) -> list[dict]:
    # 支持 .csv / .json
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    elif path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # 允许顶层为 list 或 { data: [...] } 或 { items: [...] }
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("data", "items", "list", "rows"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # 否则尝试把 dict 视为单条
                return [data]
    else:
        raise SystemExit(f"Unsupported file type: {path}")
    return []

def find_source_file(src_dir: Path, name: str) -> Path | None:
    for ext in (".json", ".csv"):
        p = src_dir / f"{name}{ext}"
        if p.exists():
            return p
    return None

def main():
    ap = argparse.ArgumentParser(description="Generate seed JSON from exported CSV/JSON.")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="源导出目录（默认 ./exports）")
    ap.add_argument("--dst", default=str(DEFAULT_DST), help="输出种子目录（默认 ./seed）")
    ap.add_argument("--mapping", default=str(DEFAULT_DST / "mapping.json"),
                    help="字段映射 JSON（默认 ./seed/mapping.json；不存在则用内置默认映射）")
    args = ap.parse_args()

    src_dir = Path(args.src).resolve()
    dst_dir = Path(args.dst).resolve()
    mapping_path = Path(args.mapping).resolve()

    print(f"[seed-gen] src={src_dir}")
    print(f"[seed-gen] dst={dst_dir}")
    print(f"[seed-gen] mapping={mapping_path if mapping_path.exists() else 'DEFAULT'}")

    if not src_dir.exists():
        raise SystemExit(f"[seed-gen] ERROR: src directory not found: {src_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    mapping_all = load_mapping(mapping_path)

    generated = []
    for name in DATASETS:
        src_file = find_source_file(src_dir, name)
        if not src_file:
            print(f"[seed-gen] WARN: {name}.csv/json not found in {src_dir}, skip.")
            continue
        rows = read_any_table(src_file)
        norm = [normalize_row(r, mapping_all.get(name, {}), name) for r in rows]
        out_path = dst_dir / f"{name}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(norm, f, ensure_ascii=False, indent=2)
        generated.append(out_path)
        print(f"[seed-gen] wrote {out_path} ({len(norm)} rows)")

    if not generated:
        print("[seed-gen] No files generated. Place types/monsters/skills/collections as CSV/JSON in ./exports.")

if __name__ == "__main__":
    main()