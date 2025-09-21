# server/app/dependencies.py
from typing import Generator
from sqlalchemy.orm import Session
from .db import SessionLocal
import logging

logger = logging.getLogger("kbxy.dependencies")

def get_db() -> Generator[Session, None, None]:
    """
    统一的数据库会话依赖注入
    
    用法:
        from fastapi import Depends
        from .dependencies import get_db
        
        def some_route(db: Session = Depends(get_db)):
            # 使用数据库会话
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def get_db_readonly() -> Generator[Session, None, None]:
    """
    只读数据库会话 - 用于查询密集型操作
    不执行commit/rollback，减少锁竞争
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()