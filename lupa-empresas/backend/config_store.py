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
    """Grava a configuracao de forma ATOMICA.

    Escrevia direto no arquivo final. Este arquivo guarda os tokens da
    Meetime -- o do grupo e os de cada usuario -- e as credenciais de
    servico; uma queda no meio do `json.dump` deixaria o JSON truncado, e
    `load()` devolve `{}` quando nao consegue ler. Ou seja: TODA a
    configuracao sumiria de uma vez, em silencio, e a unica pista seria a
    Meetime parar de deduplicar.

    Gravar em temporario e renomear resolve: renomear e atomico, entao o
    arquivo ou esta inteiro (novo ou antigo) ou nao muda.
    """
    with _LOCK:
        cfg = load()
        cfg.update({k: v for k, v in updates.items() if v is not None})
        alvo = _path()
        tmp = alvo + ".parcial"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())     # o rename so vale se os bytes sairam
        os.replace(tmp, alvo)
        return cfg
