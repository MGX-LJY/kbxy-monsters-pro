#!/usr/bin/env python3
from server.app.db import Base, engine, SessionLocal
from server.app.models import Monster
from server.app.services.monsters_service import upsert_tags, apply_scores

Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    m1 = Monster(name_final="雷霆狼", element="火", role="主攻",
                 base_offense=130, base_survive=95, base_control=60, base_tempo=110, base_pp=62)
    m1.tags = upsert_tags(db, ["PP压制","速攻"]); apply_scores(m1)
    m2 = Monster(name_final="坚岩龟", element="土", role="肉盾",
                 base_offense=80, base_survive=140, base_control=55, base_tempo=80, base_pp=50)
    m2.tags = upsert_tags(db, ["耐久"]); apply_scores(m2)
    m3 = Monster(name_final="清泉灵", element="水", role="辅助",
                 base_offense=75, base_survive=110, base_control=120, base_tempo=95, base_pp=65)
    m3.tags = upsert_tags(db, ["控场"]); apply_scores(m3)
    db.add_all([m1, m2, m3]); db.commit()
    print("Seed data inserted.")
finally:
    db.close()
