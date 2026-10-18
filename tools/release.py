"""Publica uma nova versão: atualiza version.py e CHANGELOG.md, faz commit e cria a etiqueta vX.Y.Z.

Uso:
    python tools/release.py patch "correção de X"
    python tools/release.py minor "nova função Y" [--push]
Antes de rodar, descreva as mudanças em CHANGELOG.md na seção "## [Não publicado]" (opcional);
se ela não existir, o resumo informado vira a entrada da versão. Só envia ao GitHub com --push.
"""
import os
import re
import subprocess
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PY = os.path.join(ROOT, "version.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    push = "--push" in sys.argv
    if len(args) < 2 or args[0] not in ("major", "minor", "patch"):
        sys.exit(__doc__)
    level, note = args[0], " ".join(args[1:])

    with open(VERSION_PY, encoding="utf-8") as f:
        src = f.read()
    cur = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', src)
    ma, mi, pa = (int(x) for x in cur.groups())
    ma, mi, pa = {"major": (ma + 1, 0, 0), "minor": (ma, mi + 1, 0), "patch": (ma, mi, pa + 1)}[level]
    new = f"{ma}.{mi}.{pa}"

    if git("status", "--porcelain") == "":
        sys.exit("Nada para publicar: não há alterações no repositório.")
    if git("tag", "--list", f"v{new}"):
        sys.exit(f"A etiqueta v{new} já existe.")

    with open(VERSION_PY, "w", encoding="utf-8") as f:
        f.write(src.replace(cur.group(0), f'__version__ = "{new}"'))

    with open(CHANGELOG, encoding="utf-8") as f:
        log = f.read()
    head = f"## [{new}] - {date.today().isoformat()}"
    if "## [Não publicado]" in log:
        log = log.replace("## [Não publicado]", head, 1)
    else:
        entry = f"{head}\n- {note}\n\n"
        i = log.find("## [")
        log = log[:i] + entry + log[i:] if i >= 0 else log + "\n" + entry
    with open(CHANGELOG, "w", encoding="utf-8") as f:
        f.write(log)

    git("add", "-A")
    git("commit", "-m", f"v{new}: {note}")
    git("tag", "-a", f"v{new}", "-m", note)
    print(f"Versão {new} criada (commit + etiqueta v{new}).")
    if push:
        git("push", "origin", "HEAD", "--follow-tags")
        print("Enviado ao GitHub.")
    else:
        print("Para enviar: git push origin HEAD --follow-tags")


if __name__ == "__main__":
    main()
