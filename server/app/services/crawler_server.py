# server/app/services/crawler_server.py
from __future__ import annotations

import re
import time
import random
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Generator, Iterable, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse

from DrissionPage import SessionPage

# --- 尝试引入项目内的数据库会话 ---
try:
    # 按你的工程结构：server/app/db.py 内一般会有 SessionLocal / Base / engine
    from ..db import SessionLocal, Base  # type: ignore
    _DB_AVAILABLE = True
except Exception:
    # 允许脚本独立运行（无数据库模式）
    SessionLocal = None  # type: ignore
    Base = None          # type: ignore
    _DB_AVAILABLE = False

# 如果项目内没有 declarative_base，可在无 DB 模式降级为本地 Base
if not _DB_AVAILABLE:
    try:
        from sqlalchemy.orm import declarative_base  # type: ignore
        Base = declarative_base()  # type: ignore
    except Exception:
        Base = None  # type: ignore

# --- 仅当可用 SQLAlchemy 时，声明 ORM ---
try:
    from sqlalchemy import (
        Column, Integer, String, Text, ForeignKey, UniqueConstraint
    )
    from sqlalchemy.orm import relationship, Session
    _SA_AVAILABLE = True
except Exception:
    _SA_AVAILABLE = False


log = logging.getLogger(__name__)


# ---------- 数据模型（抓取侧） ----------
@dataclass
class SkillRow:
    name: str
    level: Optional[int]
    element: str
    kind: str         # 物理 / 法术 / 特殊
    power: Optional[int]
    pp: Optional[int]
    description: str

@dataclass
class MonsterRow:
    name: str
    element: Optional[str]  # 妖怪系别（风系/火系/.../复合系/机械）
    hp: int
    speed: int
    attack: int
    defense: int
    magic: int
    resist: int
    source_url: str
    img_url: Optional[str] = None
    series_names: List[str] = field(default_factory=list)            # 同页多形态名字
    skills: List[SkillRow] = field(default_factory=list)             # 全量技能
    recommended_names: List[str] = field(default_factory=list)       # “推荐配招”解析出的技能名
    selected_skills: List[Dict[str, str]] = field(default_factory=list)  # 依据推荐筛出的技能（仅 name/description）


# ---------- ORM（存储侧） ----------
if _SA_AVAILABLE and Base is not None:
    class Monster4399(Base):  # type: ignore
        __tablename__ = "monsters_4399"
        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(128), index=True, nullable=False)
        element = Column(String(32))
        hp = Column(Integer, default=0)
        speed = Column(Integer, default=0)
        attack = Column(Integer, default=0)
        defense = Column(Integer, default=0)
        magic = Column(Integer, default=0)
        resist = Column(Integer, default=0)
        source_url = Column(String(512), nullable=False, unique=True, index=True)
        img_url = Column(String(512))
        # 直接把推荐名和精选技能以 JSON 文本存储，读库时可直接还原
        recommended_names_json = Column(Text, default="[]")
        selected_skills_json = Column(Text, default="[]")

        skills = relationship(
            "MonsterSkill4399",
            back_populates="monster",
            cascade="all, delete-orphan",
            lazy="selectin",
        )

        __table_args__ = (
            UniqueConstraint("source_url", name="uq_monsters_4399_source_url"),
        )

    class MonsterSkill4399(Base):  # type: ignore
        __tablename__ = "monster_skills_4399"
        id = Column(Integer, primary_key=True, autoincrement=True)
        monster_id = Column(Integer, ForeignKey("monsters_4399.id", ondelete="CASCADE"), index=True)
        name = Column(String(128), index=True, nullable=False)
        level = Column(Integer)
        element = Column(String(32))
        kind = Column(String(32))
        power = Column(Integer)
        pp = Column(Integer)
        description = Column(Text, default="")

        monster = relationship("Monster4399", back_populates="skills")


# ---------- 工具 ----------
_INT = re.compile(r"-?\d+")
_WS = re.compile(r"\s+")
def _to_int(s: str | None) -> Optional[int]:
    if not s:
        return None
    m = _INT.search(s)
    return int(m.group()) if m else None

def _clean(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", s).strip()

def _abs(base: str, href: str) -> str:
    return urljoin(base, href)

def _is_detail_link(href: str) -> bool:
    # /kabuxiyou/yaoguaidaquan/<slug>/YYYYMM-??-ID.html 或 /.../ID.html
    return bool(href) and '/kabuxiyou/yaoguaidaquan/' in href and href.endswith('.html')


# ---------- 爬虫主体 ----------
class Kabu4399Crawler:
    """
    4399【卡布西游-妖怪大全】爬虫（requests 模式）
    - 列表页：抽取 ul#dq_list 下 li > a 的详情链接
    - 详情页：解析两张表：
        1) “资料/种族值”表 => 可能多行（同页多形态），最终仅保留“最高形态”
        2) “技能表” => 解析为 SkillRow 列表
    - 额外：解析“推荐配招”（精选技能），并识别“妖怪系别 element”
    - DB 缓存：优先读库（按 source_url），无则抓取并入库
    """
    BASE = "https://news.4399.com"
    ROOT = "/kabuxiyou/yaoguaidaquan/"
    CANDIDATE_SLUGS = [
        "huoxi","jinxi","muxi","shuixi","tuxi","yixi","guaixi",
        "moxi","yaoxi","fengxi","duxi","leixi","huanxi",
        "bing","lingxi","jixie","huofengxi","mulingxi",
        "shengxi","tuhuanxi","shuiyaoxi","yinxi",
    ]

    # URL 目录到“系别中文”的映射（常见+复合）
    SLUG2ELEM: Dict[str, str] = {
        "huoxi": "火系", "jinxi": "金系", "muxi": "木系", "shuixi": "水系", "tuxi": "土系",
        "yixi": "翼系", "guaixi": "怪系", "moxi": "魔系", "yaoxi": "妖系", "fengxi": "风系",
        "duxi": "毒系", "leixi": "雷系", "huanxi": "幻系", "bing": "冰系", "lingxi": "灵系",
        "jixie": "机械",
        "huofengxi": "火风系", "mulingxi": "木灵系", "tuhuanxi": "土幻系",
        "shuiyaoxi": "水妖系", "yinxi": "音系", "shengxi": "圣系",
    }

    # 技能表里的“技能属性”常见取值（用于投票推断）
    ELEM_TOKENS: Dict[str, str] = {
        "风": "风系", "火": "火系", "水": "水系", "土": "土系", "金": "金系",
        "冰": "冰系", "毒": "毒系", "雷": "雷系", "幻": "幻系", "妖": "妖系",
        "翼": "翼系", "怪": "怪系", "灵": "灵系", "音": "音系", "圣": "圣系",
        # 技能里一般不会写“机械”，但留作兜底
        "机": "机械", "械": "机械",
    }

    def __init__(
        self,
        *,
        throttle_range: Tuple[float, float] = (0.6, 1.2),
        max_retries: int = 3,
        timeout: float = 15.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.sp = SessionPage()
        self.sp.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if headers:
            self.sp.session.headers.update(headers)
        self.throttle_range = throttle_range
        self.max_retries = max_retries
        self.timeout = timeout
        self.seen_urls: Set[str] = set()

    # ---- 基础 GET（带重试 + 随机节流）----
    def _get(self, url: str) -> bool:
        for i in range(self.max_retries):
            try:
                self.sp.get(url, timeout=self.timeout)
                if self.sp.response and self.sp.response.ok:
                    return True
            except Exception as e:
                log.warning("GET fail (%s/%s) %s -> %s", i+1, self.max_retries, url, e)
            time.sleep(random.uniform(*self.throttle_range))
        return False

    # ---- 列表页：抽取详情链接 ----
    def _extract_detail_links_from_list(self, page_url: str) -> List[str]:
        links: List[str] = []
        for a in self.sp.eles('t:ul@@id=dq_list t:a'):
            href = a.attr('href') or ""
            if _is_detail_link(href):
                links.append(_abs(self.BASE, href))
        if not links:
            for a in self.sp.eles('t:a'):
                href = a.attr('href') or ""
                if _is_detail_link(href):
                    links.append(_abs(self.BASE, href))
        out, seen = [], set()
        for u in links:
            if u not in seen:
                seen.add(u); out.append(u)
        log.info("list[%s] -> %d detail links", page_url, len(out))
        return out

    def iter_list_pages(self) -> Iterable[str]:
        yield _abs(self.BASE, self.ROOT)
        for slug in self.CANDIDATE_SLUGS:
            yield _abs(self.BASE, f"{self.ROOT}{slug}/")

    def iter_detail_urls(self) -> Generator[str, None, None]:
        for list_url in self.iter_list_pages():
            if not self._get(list_url):
                continue
            for u in self._extract_detail_links_from_list(list_url):
                if u not in self.seen_urls:
                    self.seen_urls.add(u)
                    yield u

    # ---- 系别识别 ----
    def _infer_element_from_url(self, page_url: str) -> Optional[str]:
        """优先依据 URL 目录（/yaoguaidaquan/<slug>/...）推断系别。"""
        try:
            path = urlparse(page_url).path.strip("/")
            parts = path.split("/")
            # 形如 kabuxiyou / yaoguaidaquan / <slug> / ...
            if len(parts) >= 3 and parts[1] == "yaoguaidaquan":
                slug = parts[2]
                return self.SLUG2ELEM.get(slug)
        except Exception:
            pass
        return None

    def _infer_element_from_breadcrumb(self) -> Optional[str]:
        """从面包屑/导航里的链接文字中提取“XX系 / 机械”等。"""
        for a in self.sp.eles('t:div@@class=dq t:a'):
            txt = (_clean(a.text) or "").strip()
            if not txt:
                continue
            # 常见：风系 / 火系 / 机械
            if txt.endswith("系") or txt == "机械":
                return txt
        return None

    def _infer_element_from_skills(self, skills: List[SkillRow]) -> Optional[str]:
        """对技能表的“技能属性”做投票推断（忽略 无 / 特殊）。"""
        counter: Dict[str, int] = {}
        for s in skills or []:
            raw = (_clean(s.element) or "")
            if not raw or raw in {"无", "特殊"}:
                continue
            for ch in raw:
                if ch in self.ELEM_TOKENS:
                    elem = self.ELEM_TOKENS[ch]
                    counter[elem] = counter.get(elem, 0) + 1
                    break
        if not counter:
            return None
        return max(counter.items(), key=lambda kv: kv[1])[0]

    def _infer_element(self, page_url: str, skills: List[SkillRow]) -> Optional[str]:
        """综合 URL -> 面包屑 -> 技能属性 三层推断。"""
        return (
            self._infer_element_from_url(page_url)
            or self._infer_element_from_breadcrumb()
            or self._infer_element_from_skills(skills)
        )

    # ---- 详情页解析 ----
    def _pick_page_title_name(self) -> Optional[str]:
        h1 = self.sp.ele('t:h1')
        if not h1:
            return None
        txt = _clean(h1.text)
        m = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·]+", txt)
        return m[-1] if m else None

    def _parse_stats_table(self, page_url: str) -> List[MonsterRow]:
        results: List[MonsterRow] = []
        target_tables = []
        for tbl in self.sp.eles('t:table'):
            txt = _clean(tbl.text)
            if ("种族值" in txt) or ("资料" in txt and "体力" in txt and "攻击" in txt):
                target_tables.append(tbl)
        if not target_tables:
            return results

        tbl = target_tables[-1]
        rows = tbl.eles('t:tr')
        if len(rows) < 3:
            return results

        header_idx = None
        for i, tr in enumerate(rows[:6]):
            t = _clean(tr.text)
            if all(k in t for k in ("体力", "速度", "攻击", "防御", "法术", "抗性")):
                header_idx = i
                break
        if header_idx is None:
            return results

        title_name = self._pick_page_title_name()
        img_ele = self.sp.ele('t:img')
        page_img = img_ele.attr('src') if img_ele else None
        if page_img and page_img.startswith('//'):
            page_img = _abs(self.BASE, page_img)

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                continue
            vals = [_clean(td.text) for td in tds]
            if len(vals) >= 8:
                name = vals[0] or vals[1]
                cols = vals[2:8]
            else:
                name = vals[0]
                cols = vals[1:7]
            if len(cols) != 6:
                continue
            m = MonsterRow(
                name=_clean(name),
                element=None,  # 先占位，稍后统一推断
                hp=_to_int(cols[0]) or 0,
                speed=_to_int(cols[1]) or 0,
                attack=_to_int(cols[2]) or 0,
                defense=_to_int(cols[3]) or 0,
                magic=_to_int(cols[4]) or 0,
                resist=_to_int(cols[5]) or 0,
                source_url=page_url,
                img_url=page_img,
            )
            results.append(m)

        if title_name:
            for r in results:
                r.series_names = [rr.name for rr in results]
        return results

    def _parse_skills_table(self) -> List[SkillRow]:
        skills: List[SkillRow] = []
        target_tbl = None
        for tbl in self.sp.eles('t:table'):
            if "技能表" in _clean(tbl.text):
                target_tbl = tbl
        if not target_tbl:
            return skills

        rows = target_tbl.eles('t:tr')
        if len(rows) <= 2:
            return skills

        header_idx = None
        for i, tr in enumerate(rows[:6]):
            t = _clean(tr.text)
            if all(k in t for k in ("技能名称", "等级", "技能属性", "类型", "威力", "PP", "技能描述")):
                header_idx = i
                break
        if header_idx is None:
            header_idx = 0

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                continue
            vals = [_clean(td.text) for td in tds[:7]]
            name = vals[0]
            if not name or name == "无":
                continue
            level = _to_int(vals[1])
            element = vals[2]
            kind = vals[3]
            power = _to_int(vals[4])
            pp = _to_int(vals[5])
            desc = vals[6]
            skills.append(SkillRow(name, level, element, kind, power, pp, desc))
        return skills

    # ---- 推荐配招：解析 + 精选 ----
    def _parse_recommended_names(self) -> List[str]:
        for tbl in self.sp.eles('t:table'):
            for tr in tbl.eles('t:tr'):
                tds = tr.eles('t:td')
                if not tds:
                    continue
                first = _clean(tds[0].text)
                if "推荐配招" in first or "推荐技能" in first:
                    raw = _clean(" ".join((td.text or "") for td in tds[1:])) if len(tds) > 1 else _clean(tr.text)
                    raw = raw.replace("：", " ").replace("&nbsp;", " ").replace("\u3000", " ")
                    parts = re.split(r"[+＋、/，,；;|\s]+", raw)
                    names, seen = [], set()
                    for p in parts:
                        n = _clean(p)
                        if (not n) or (n == "无") or ("推荐" in n) or ("配招" in n):
                            continue
                        if n not in seen:
                            seen.add(n); names.append(n)
                    return names
        return []

    def _select_skills_from_recommend(self, rec_names: List[str], skills: List[SkillRow]) -> List[Dict[str, str]]:
        """按推荐名在已解析技能中匹配，返回 [{name, description}, ...]（不含 PP）。"""
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "")

        skill_map = {norm(s.name): s for s in skills}
        out: List[Dict[str, str]] = []
        for rec in rec_names:
            key = norm(rec)
            s = skill_map.get(key)
            if not s:
                for cand in skills:
                    n = norm(cand.name)
                    if key and (key in n or n in key):
                        s = cand
                        break
            if s:
                out.append({"name": s.name, "description": s.description})
            else:
                out.append({"name": rec, "description": ""})
        return out

    @staticmethod
    def _six_sum(m: MonsterRow) -> int:
        return int(m.hp + m.speed + m.attack + m.defense + m.magic + m.resist)

    @staticmethod
    def _all_skills_as_selected(skills: List[SkillRow]) -> List[Dict[str, str]]:
        """把全量技能压缩成 selected_skills（仅 name/description），过滤空名与“无”"""
        out = []
        for s in skills or []:
            n = (s.name or "").strip()
            if not n or n == "无":
                continue
            out.append({"name": n, "description": (s.description or "").strip()})
        return out

    # ---------- DB <-> 抓取模型 互转 ----------
    def _to_db_model(self, m: MonsterRow) -> Dict[str, object]:
        return {
            "name": m.name,
            "element": m.element,
            "hp": m.hp,
            "speed": m.speed,
            "attack": m.attack,
            "defense": m.defense,
            "magic": m.magic,
            "resist": m.resist,
            "source_url": m.source_url,
            "img_url": m.img_url,
            "recommended_names_json": json.dumps(m.recommended_names, ensure_ascii=False),
            "selected_skills_json": json.dumps(m.selected_skills, ensure_ascii=False),
        }

    def _from_db_model(self, db_m: "Monster4399") -> MonsterRow:  # type: ignore
        skills = [
            SkillRow(
                name=s.name, level=s.level, element=s.element or "", kind=s.kind or "",
                power=s.power, pp=s.pp, description=s.description or ""
            )
            for s in getattr(db_m, "skills", []) or []
        ]
        try:
            rec_names = json.loads(db_m.recommended_names_json or "[]")
        except Exception:
            rec_names = []
        try:
            selected = json.loads(db_m.selected_skills_json or "[]")
        except Exception:
            selected = []

        return MonsterRow(
            name=db_m.name,
            element=db_m.element,
            hp=db_m.hp, speed=db_m.speed, attack=db_m.attack, defense=db_m.defense,
            magic=db_m.magic, resist=db_m.resist,
            source_url=db_m.source_url,
            img_url=db_m.img_url,
            series_names=[],  # 页面信息，不入库
            skills=skills,
            recommended_names=rec_names,
            selected_skills=selected or self._all_skills_as_selected(skills),  # 兜底
        )

    # ---------- DB 读写 ----------
    def _db_load(self, sess: Session, url: str) -> Optional[MonsterRow]:
        if not (_DB_AVAILABLE and _SA_AVAILABLE and Base is not None):
            return None
        db_m = sess.query(Monster4399).filter(Monster4399.source_url == url).first()
        if db_m:
            log.info("CACHE HIT %s", url)
            return self._from_db_model(db_m)
        return None

    def _db_upsert(self, sess: Session, m: MonsterRow) -> None:
        if not (_DB_AVAILABLE and _SA_AVAILABLE and Base is not None):
            return
        data = self._to_db_model(m)
        db_m = sess.query(Monster4399).filter(Monster4399.source_url == m.source_url).first()
        if db_m is None:
            db_m = Monster4399(**data)  # type: ignore
            sess.add(db_m)
            sess.flush()
        else:
            for k, v in data.items():
                setattr(db_m, k, v)

        # 覆盖写技能
        # 用 delete-orphan 级联，简单做法是清空再写入
        db_m.skills[:] = []  # type: ignore
        for s in m.skills or []:
            db_s = MonsterSkill4399(  # type: ignore
                name=s.name, level=s.level, element=s.element, kind=s.kind,
                power=s.power, pp=s.pp, description=s.description
            )
            db_m.skills.append(db_s)  # type: ignore
        sess.commit()

    # ---------- 对外：按 URL 读库或抓取 ----------
    def get_or_fetch(self, url: str, sess: Optional["Session"] = None) -> Optional[MonsterRow]:  # type: ignore
        """
        优先读库，库里没有则抓取并入库，最后返回 MonsterRow。
        若项目未配置数据库，则回退为直接抓取。
        """
        close_after = False
        if _DB_AVAILABLE and _SA_AVAILABLE and Base is not None and sess is None and SessionLocal is not None:
            sess = SessionLocal()  # type: ignore
            close_after = True

        try:
            if sess is not None:
                cached = self._db_load(sess, url)
                if cached:
                    return cached

            fetched = self.fetch_detail(url)
            if fetched and sess is not None:
                self._db_upsert(sess, fetched)
            return fetched
        finally:
            if close_after and sess is not None:
                sess.close()

    # ---- 页面抓取（不触库，内部使用）----
    def fetch_detail(self, url: str) -> Optional[MonsterRow]:
        """
        仅抓取解析，不访问数据库；返回“最高形态” MonsterRow：
        - 以六维和的最大值为最高形态
        - 解析推荐配招，并在技能表中筛选出对应技能（仅 name/description）
        - 若没有“推荐配招”或匹配结果为空，则回退为“所有技能”列表
        - 识别妖怪“系别 element”
        """
        if not self._get(url):
            return None

        monsters = self._parse_stats_table(url)
        if not monsters:
            return None

        skills = self._parse_skills_table()
        rec_names = self._parse_recommended_names()
        selected = self._select_skills_from_recommend(rec_names, skills) if rec_names else []

        # ---- 回退策略：没有推荐配招（或匹配不上） => 使用全量技能 ----
        if not selected:
            selected = self._all_skills_as_selected(skills)

        # 仅保留最高形态
        best = max(monsters, key=self._six_sum)

        # 系别识别（URL -> 面包屑 -> 技能表）
        elem = self._infer_element(url, skills)
        best.element = elem

        best.skills = skills
        best.recommended_names = rec_names
        best.selected_skills = selected
        return best

    # ---- 顶层 API：遍历列表，读库或抓取 ----
    def crawl_all(
        self,
        *,
        persist: Optional[callable] = None,
        use_db_cache: bool = True,
    ) -> Generator[MonsterRow, None, None]:
        """
        遍历所有详情页：
        - use_db_cache=True 时，优先从库按 source_url 命中返回；
          未命中则抓取 → 入库 → 返回
        - persist 回调仍然可用（例如打印日志）
        """
        sess: Optional["Session"] = None  # type: ignore
        if use_db_cache and _DB_AVAILABLE and SessionLocal is not None:
            sess = SessionLocal()  # type: ignore
        try:
            for detail_url in self.iter_detail_urls():
                m: Optional[MonsterRow] = None
                if use_db_cache and sess is not None:
                    m = self._db_load(sess, detail_url)
                    if m:
                        if persist:
                            try:
                                persist(m)
                            except Exception as e:
                                log.exception("persist error (cache): %s", e)
                        yield m
                        time.sleep(random.uniform(*self.throttle_range))
                        continue

                # 抓取 + 入库
                m = self.fetch_detail(detail_url)
                if not m:
                    continue
                if use_db_cache and sess is not None:
                    try:
                        self._db_upsert(sess, m)
                    except Exception as e:
                        log.exception("db upsert error: %s", e)
                if persist:
                    try:
                        persist(m)
                    except Exception as e:
                        log.exception("persist error: %s", e)
                yield m
                time.sleep(random.uniform(*self.throttle_range))
        finally:
            if sess is not None:
                sess.close()


# ---------- 示例持久化（可接你自己的入库逻辑） ----------
def example_persist(mon: MonsterRow) -> None:
    log.info(
        "PERSIST %s [%s] hp=%s atk=%s spd=%s rec=%d sel=%d skills=%d",
        mon.name, mon.element or "-", mon.hp, mon.attack, mon.speed,
        len(mon.recommended_names), len(mon.selected_skills), len(mon.skills)
    )


# ---------- 输出裁剪 ----------
def _to_public_json(m: MonsterRow) -> Dict[str, object]:
    """
    仅保留：
      - 最高形态：name, element, hp, speed, attack, defense, magic, resist
      - selected_skills: [{name, description}]
    """
    return {
        "name": m.name,
        "element": m.element,
        "hp": m.hp,
        "speed": m.speed,
        "attack": m.attack,
        "defense": m.defense,
        "magic": m.magic,
        "resist": m.resist,
        "selected_skills": m.selected_skills,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = Kabu4399Crawler()

    # 收集前 10 个角色（最高形态）并输出 JSON
    N = 10
    out: List[Dict[str, object]] = []

    if _DB_AVAILABLE and SessionLocal is not None:
        # 有数据库：优先读库，无则抓取并入库
        with SessionLocal() as sess:  # type: ignore
            for item in crawler.crawl_all(persist=example_persist, use_db_cache=True):
                out.append(_to_public_json(item))
                if len(out) >= N:
                    break
    else:
        # 无数据库环境：纯抓取（不入库）
        for item in crawler.crawl_all(persist=example_persist, use_db_cache=False):
            out.append(_to_public_json(item))
            if len(out) >= N:
                break

    print(json.dumps(out, ensure_ascii=False, indent=2))