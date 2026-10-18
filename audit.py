"""Registro permanente (em arquivo) de cada uso da conexão com a central, com data e hora.

Fica em logs/conexoes.log, uma linha por evento, só acrescentando (nunca reescreve):
    2026-10-17 22:45:16-03:00 | CONECTAR_OK | 192.168.0.10:35000 | ELM327 v1.5 | protocolo 6
Não grava VIN nem dados do veículo, só quando, onde e o que foi feito.
"""
import os
import threading
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "conexoes.log")
_LOCK = threading.Lock()


def _clean(v):
    return str(v).replace("\r", " ").replace("\n", " ").replace(" | ", " / ").strip()


def record(event, *details):
    """Acrescenta uma linha ao log. Nunca levanta erro: falha de disco não pode derrubar o diagnóstico."""
    stamp = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
    line = " | ".join([stamp, event] + [_clean(d) for d in details if d not in (None, "")])
    try:
        with _LOCK:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass
    return line


def tail(limit=200):
    """Últimos eventos, do mais recente para o mais antigo."""
    try:
        with _LOCK, open(LOG_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines[-limit:]):
        parts = ln.split(" | ")
        out.append({"when": parts[0], "event": parts[1] if len(parts) > 1 else "", "details": parts[2:]})
    return out
