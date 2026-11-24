from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import get_settings
import os

class Base(DeclarativeBase): pass
url=get_settings().database_url
if url.startswith('sqlite'):
    os.makedirs('data',exist_ok=True)
    engine=create_engine(url,connect_args={"check_same_thread":False})
else:
    engine=create_engine(url,pool_pre_ping=True,pool_size=10,max_overflow=20)
SessionLocal=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()
