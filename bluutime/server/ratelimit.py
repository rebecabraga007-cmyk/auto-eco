"""Limite de taxa simples, em memória — sem Redis, sem dependência nova.

Só dois pontos usam isto (`/envio/teste` e o webhook de entrada do
WhatsApp), então uma janela fixa por chave já resolve; não precisa da
precisão de um sliding window pra essa escala. `_BALDES` é limpo por
inteiro a cada acerto que encontra uma janela vencida, então não cresce
sem limite mesmo num processo de vida longa.
"""
import time

_BALDES: dict[str, tuple[float, int]] = {}


def permitir(chave: str, limite: int, janela_segundos: float) -> bool:
    """True se `chave` ainda tem cota na janela atual; já conta a tentativa."""
    agora = time.monotonic()
    inicio, contagem = _BALDES.get(chave, (agora, 0))
    if agora - inicio >= janela_segundos:
        inicio, contagem = agora, 0
    contagem += 1
    _BALDES[chave] = (inicio, contagem)
    if len(_BALDES) > 10000:
        vencidas = [k for k, (i, _) in _BALDES.items() if agora - i >= janela_segundos]
        for k in vencidas:
            _BALDES.pop(k, None)
    return contagem <= limite
