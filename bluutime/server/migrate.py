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
        # Índices das colunas que a fila, a lista de leads e as estatísticas
        # filtram a toda hora. `index=True` no modelo não cria índice em tabela
        # que já existe, por isso vão aqui, idempotentes.
        for nome, tabela, colunas in _INDICES:
            if tabela in existing_tables or tabela in Base.metadata.tables:
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{nome}" ON "{tabela}" ({colunas})'))
    return applied


_INDICES = [
    ("ix_lead_status_sdr", "lead", "status, sdr_id"),
    ("ix_lead_sdr_status", "lead", "sdr_id, status"),
    ("ix_lead_cadence", "lead", "cadence_id"),
    ("ix_lead_base", "lead", "lead_base_id"),
    ("ix_lead_reprospect", "lead", "reprospect_at"),
    ("ix_la_status_sched", "lead_activity", "status, scheduled_at"),
    ("ix_la_user_status_done", "lead_activity", "user_id, status, done_at"),
    ("ix_la_lead", "lead_activity", "lead_id"),
    ("ix_call_user_started", "call", "user_id, started_at"),
    ("ix_call_lead", "call", "lead_id"),
    ("ix_delivery_token", "delivery", "tracking_token"),
]
