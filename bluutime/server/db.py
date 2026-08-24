from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _liga_chave_estrangeira(dbapi_connection, _record):
    """O SQLite ignora `ondelete=CASCADE` se este PRAGMA não for ligado.

    Ele é por conexão, não por banco — daí o hook. Sem isto os modelos declaram
    cascata e o banco não cumpre: apagar uma conversa deixava as mensagens dela
    apontando para um id que não existe mais.
    """
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
