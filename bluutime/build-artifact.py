"""Gera bluutime-app-artifact.html a partir de bluutime-mvp.html.

O publicador de Artifact envolve o arquivo em <!doctype html><head></head><body>,
então a cópia publicada não pode trazer esses wrappers.
"""
import re
from pathlib import Path

AQUI = Path(__file__).parent
src = (AQUI / "bluutime-mvp.html").read_text(encoding="utf-8")

corpo = src[src.index("<title>"):src.rindex("</body>")]
for tag in ("</head>", "<body>",
            '<meta charset="UTF-8" />',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'):
    corpo = corpo.replace(tag, "")
corpo = re.sub(r"\n{3,}", "\n\n", corpo)

destino = AQUI / "bluutime-app-artifact.html"
destino.write_text(corpo, encoding="utf-8")
print(f"{destino.name}: {corpo.count(chr(10))} linhas")
