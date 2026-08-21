"""Migração leve de esquema.

`Base.metadata.create_all` cria tabela nova, mas nunca acrescenta coluna a uma
tabela existente — e recriar o banco custaria a operação já importada do
Meetime. Aqui comparamos o modelo com o que o SQLite tem e emitimos os
`ALTER TABLE ... ADD COLUMN` que faltam.
"""
from sqlalchemy import inspect, text

from .db import Base, engine

# Tipos SQLAlchemy → tipos SQLite, com o default que o ALTER exige.
_SQL_DEFAULT = {"VARCHAR": "''", "TEXT": "''", "INTEGER": "0",
                "FLOAT": "0", "BOOLEAN": "0", "DATETIME": "NULL", "DATE": "NULL"}


def run() -> list[str]:
    Base.metadata.create_all(engine)
    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                kind = column.type.compile(engine.dialect)
                base_kind = kind.split("(")[0].upper()
                default = _SQL_DEFAULT.get(base_kind, "NULL")
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                    f"{kind} DEFAULT {default}"))
                applied.append(f"{table.name}.{column.name}")
    return applied
