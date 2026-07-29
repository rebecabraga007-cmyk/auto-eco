"""Config de integrações editável pelo admin (persistida em JSON no serviço de dados).

Fica NO SERVIÇO DE DADOS local (onde as chaves devem morar), não no Render.
Guarda coisas como o token da Meetime. Tem prioridade sobre variáveis de ambiente
para as chaves que o admin definir pela interface.
"""
import json
import os
import threading

_LOCK = threading.Lock()


def _path() -> str:
    base = r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "capiblu_config.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def get(key: str, default=None):
    return load().get(key, default)


def set_many(updates: dict) -> dict:
    with _LOCK:
        cfg = load()
        cfg.update({k: v for k, v in updates.items() if v is not None})
        with open(_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1)
        return cfg
