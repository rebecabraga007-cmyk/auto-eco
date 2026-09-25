# -*- coding: utf-8 -*-
"""Estado das trocas temporárias de fornecedor ("contingências").

Uma contingência é um interruptor: enquanto ligado, as chamadas a um
fornecedor fora do ar são atendidas por outro. Quem liga pode ser o admin
(painel) ou o vigia automático (`vigia_apis.py`), e ISSO IMPORTA na hora de
desligar: o vigia só desliga o que ele mesmo ligou. Se o admin ligou à mão,
foi uma decisão humana -- talvez por um motivo que a sonda não vê (resposta
lenta, dado errado) -- e desfazê-la sozinho seria atropelar essa decisão.

| api          | fornecedor fora do ar             | quem responde no lugar                 |
|--------------|-----------------------------------|----------------------------------------|
| workapi      | WorkAPI (CPF, telefone, nome)     | Assertiva (workapi_suspensa.py)        |
| brightdata   | Bright Data Web Scraper (ao vivo) | Bright Data Search nas bases (url)     |

O estado mora no `capiblu_config.json` (config_store), relido a cada `_TTL`
segundos: o serviço de dados e o Bluutime (que monta o CapiBLU no mesmo
processo dele) leem o mesmo arquivo, e o vigia roda num terceiro processo.
"""
import time
from typing import Any

import config_store

CHAVES = {
    "workapi": "workapi_suspenso",
    "brightdata": "brightdata_scraper_suspenso",
}
_TTL = 5.0
_lido: dict[str, tuple[float, dict]] = {}


def estado(api: str) -> dict[str, Any]:
    """{ativo, desde, por, auto, motivo}."""
    agora = time.time()
    t, v = _lido.get(api, (0.0, {}))
    if agora - t > _TTL:
        bruto = config_store.get(CHAVES[api]) or {}
        v = bruto if isinstance(bruto, dict) else {"ativo": bool(bruto)}
        _lido[api] = (agora, v)
    return dict(v)


def ativo(api: str) -> bool:
    return bool(estado(api).get("ativo"))


def definir(api: str, ligar: bool, usuario: str = "", auto: bool = False,
            motivo: str = "") -> dict[str, Any]:
    novo = {"ativo": bool(ligar), "desde": int(time.time()), "por": usuario or "",
            "auto": bool(auto), "motivo": motivo or ""}
    config_store.set_many({CHAVES[api]: novo})
    _lido[api] = (time.time(), novo)
    return novo
