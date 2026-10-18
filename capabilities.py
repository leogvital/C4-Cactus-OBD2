"""Diagnóstico de capacidades: sonda, SOMENTE LEITURA, o que cada central do carro responde.

Serviços usados (nenhum altera nada na central):
  OBD-II modos 01, 02, 03, 06, 07, 09, 0A  |  UDS 0x22 (ler DID), 0x19 (ler DTC), 0x3E (tester present)
Não envia: 04 (apagar), 11 (reset), 10 (trocar sessão), 27 (segurança), 2E/2F/31 (escrita/atuação).
"""
import time

import elm327
import pids
from elm327 import ELMError, decode_dtc

HEX = set("0123456789ABCDEF")
CHAIN_STEP = 0x20

UDS_DIDS = {
    "F190": "VIN", "F187": "Nº de peça (fabricante)", "F18A": "Fornecedor do sistema",
    "F18C": "Nº de série da ECU", "F191": "Versão de hardware", "F193": "Versão de hardware (fornecedor)",
    "F194": "Nº do software (fornecedor)", "F195": "Versão do software (fornecedor)",
    "F197": "Nome do sistema", "F19E": "ASAM/ODX file ID",
}
NRC = {
    0x10: "recusado (geral)", 0x11: "serviço não suportado", 0x12: "subfunção não suportada",
    0x13: "formato incorreto", 0x22: "condições incorretas", 0x31: "DID/parâmetro fora do alcance (não existe)",
    0x33: "acesso negado (precisa de autenticação)", 0x7E: "subfunção não suportada na sessão",
    0x7F: "serviço não suportado na sessão atual",
}


# ---------- ISO-TP com cabeçalhos (ATH1) ----------
def frames(raw):
    """Reagrupa as linhas hex 'IDD<dados>' (ATH1, ATS0) em mensagens ISO-TP por ID."""
    state, out = {}, []
    for line in raw.split("\n"):
        h = line.replace(" ", "").upper()
        if len(h) < 5 or len(h) % 2 == 0 or not all(c in HEX for c in h):
            continue
        cid, b = h[:3], bytes.fromhex(h[3:])
        t = b[0] >> 4
        if t == 0:
            out.append({"id": cid, "data": bytes(b[1:1 + (b[0] & 0xF)]), "complete": True})
            state.pop(cid, None)
        elif t == 1 and len(b) >= 2:
            m = {"id": cid, "total": ((b[0] & 0xF) << 8) | b[1], "data": bytearray(b[2:])}
            state[cid] = m
            out.append(m)
        elif t == 2 and cid in state:
            state[cid]["data"].extend(b[1:])
    res = []
    for m in out:
        if "total" in m:
            d = bytes(m["data"][: m["total"]])
            res.append({"id": m["id"], "data": d, "complete": len(d) >= m["total"]})
        else:
            res.append(m)
    return res


def _ascii(b):
    s = "".join(chr(c) for c in b if 32 <= c < 127).strip()
    return s


class Scanner:
    def __init__(self, elm, prog):
        self.elm, self.prog = elm, prog
        self.resp = ""   # ID de resposta (7E8...)

    # envia e devolve (payload da central-alvo ou None, texto cru)
    def ask(self, cmd, wait=2.5):
        raw = self.elm.send(cmd, wait=wait)
        mine = [f for f in frames(raw) if f["id"] == self.resp]
        for f in reversed(mine):  # ignora "resposta pendente" (7F xx 78)
            d = f["data"]
            if not (len(d) >= 3 and d[0] == 0x7F and d[2] == 0x78):
                return d, raw
        return (mine[-1]["data"] if mine else None), raw

    def support(self, mode, hdr):
        sup, base = [], 0
        while base <= 0xE0:
            cmd = f"{mode:02X}{base:02X}" + ("00" if mode == 2 else "")
            d, _ = self.ask(cmd)
            if not d or d[0] != mode + 0x40 or len(d) < hdr + 4:
                break
            m = int.from_bytes(d[hdr:hdr + 4], "big")
            sup += [base + i + 1 for i in range(32) if m & (1 << (31 - i))]
            if not m & 1:
                break
            base += CHAIN_STEP
        return [p for p in sup if p % CHAIN_STEP != 0]

    # ---------- por modo ----------
    def mode01(self):
        sup = self.support(1, 2)
        vals = {}
        for p in sup:
            d, raw = self.ask(f"01{p:02X}", 1.5)
            if d and d[0] == 0x41 and len(d) >= 3:
                body = list(d[2:])
                dec = pids.decode(f"{p:02X}", body)
                vals[f"{p:02X}"] = {
                    "raw": bytes(body).hex().upper(),
                    "name": dec["name"] if dec else None,
                    "value": dec["value"] if dec else None,
                    "unit": dec["unit"] if dec else None,
                }
        return {"supported": [f"{p:02X}" for p in sup], "values": vals}

    def mode02(self):
        sup = self.support(2, 3)
        res = {"supported": [f"{p:02X}" for p in sup], "values": {}}
        for p in sup[:40]:
            d, _ = self.ask(f"02{p:02X}00", 1.5)
            if d and d[0] == 0x42:
                res["values"][f"{p:02X}"] = bytes(d[3:]).hex().upper()
        return res

    def mode06(self):
        sup = self.support(6, 2)
        res = {"supported_mids": [f"{p:02X}" for p in sup], "mids": {}}
        for mid in sup[:48]:
            d, _ = self.ask(f"06{mid:02X}", 2.5)
            if d and d[0] == 0x46:
                body, tests = d[2:], []
                for i in range(0, len(body) - 7, 8):
                    t = body[i:i + 8]
                    tests.append({"tid": f"{t[0]:02X}", "uasid": f"{t[1]:02X}",
                                  "value": int.from_bytes(t[2:4], "big"),
                                  "min": int.from_bytes(t[4:6], "big"),
                                  "max": int.from_bytes(t[6:8], "big")})
                res["mids"][f"{mid:02X}"] = {"raw": bytes(d[2:]).hex().upper(), "tests": tests}
        return res

    def mode09(self):
        sup = self.support(9, 2)
        res = {"supported": [f"{p:02X}" for p in sup], "items": {}}
        names = {2: "VIN", 4: "Calibration ID", 6: "CVN (checksum da calibração)", 8: "IUPR (diesel/gasolina)",
                 0xA: "Nome da ECU", 0xB: "IUPR (motor a gasolina)"}
        for p in sup:
            d, _ = self.ask(f"09{p:02X}", 4.0)
            if d and d[0] == 0x49:
                body = d[3:] if len(d) > 3 else b""
                item = {"name": names.get(p, "desconhecido"), "raw": bytes(body).hex().upper()}
                if p in (2, 4, 0xA):
                    item["text"] = _ascii(body)
                res["items"][f"{p:02X}"] = item
        return res

    def dtcs(self):
        res = {}
        for m in ("03", "07", "0A"):
            d, _ = self.ask(m, 3.0)
            exp = int(m, 16) + 0x40
            if d and d[0] == exp:
                body = d[2:]
                res[m] = [decode_dtc(int.from_bytes(body[i:i + 2], "big"))
                          for i in range(0, len(body) - 1, 2) if body[i:i + 2] != b"\x00\x00"]
            else:
                res[m] = None  # sem resposta (não suportado)
        return res

    def uds(self):
        res = {"dids": {}, "tester_present": None, "read_dtc_19": None}
        for did, label in UDS_DIDS.items():
            d, raw = self.ask(f"22{did}", 3.0)
            item = {"label": label}
            if d is None:
                item["status"] = "sem resposta"
            elif d[0] == 0x62:
                body = d[3:]
                item.update(status="ok", hex=bytes(body).hex().upper(), text=_ascii(body))
            elif d[0] == 0x7F and len(d) >= 3:
                item.update(status="negativa", nrc=f"{d[2]:02X}", desc=NRC.get(d[2], "código desconhecido"))
            else:
                item["status"] = f"resposta inesperada: {d.hex().upper()}"
            res["dids"][did] = item
        d, _ = self.ask("3E00", 2.0)
        res["tester_present"] = "ok" if d and d[0] == 0x7E else ("negativa" if d and d[0] == 0x7F else "sem resposta")
        d, _ = self.ask("1902FF", 3.0)
        if d is None:
            res["read_dtc_19"] = "sem resposta"
        elif d[0] == 0x59:
            res["read_dtc_19"] = {"ok": True, "hex": d.hex().upper()}
        elif d[0] == 0x7F and len(d) >= 3:
            res["read_dtc_19"] = {"ok": False, "nrc": f"{d[2]:02X}", "desc": NRC.get(d[2], "")}
        return res


def run(elm, prog):
    """Executa o diagnóstico completo. `prog(msg)` informa o andamento. Retorna dict (JSON-serializável)."""
    elm327.set_source("scan")
    report = {"started": time.time(), "adapter": {}, "ecus": [], "notes": []}
    with elm.lock:   # pausa a leitura ao vivo durante a varredura
        try:
            prog("Informações do adaptador")
            report["adapter"] = {
                "version": elm.version,
                "description": elm.send("AT@1"),
                "protocol": elm.send("ATDP"),
                "voltage": elm.send("ATRV"),
            }
            elm.send("ATH1")
            elm.send("ATSH7DF")
            prog("Procurando centrais que respondem ao OBD")
            raw = elm.send("0100", wait=4.0)
            ids = sorted({f["id"] for f in frames(raw) if f["data"][:2] == b"\x41\x00"})
            report["responding_ids"] = ids
            if not ids:
                report["notes"].append("Nenhuma central respondeu. Ligue a ignição e tente de novo.")
            for rid in ids:
                try:
                    req = f"7E{int(rid[2], 16) - 8:X}" if rid.startswith("7E") else None
                except ValueError:
                    req = None
                ecu = {"resp_id": rid, "req_id": req}
                if not req:
                    ecu["note"] = "ID fora da faixa OBD padrão (7E8-7EF); não sondado"
                    report["ecus"].append(ecu)
                    continue
                elm.send(f"ATSH{req}")
                sc = Scanner(elm, prog)
                sc.resp = rid
                for key, label, fn in (
                    ("mode01", "Modo 01 · dados ao vivo", sc.mode01),
                    ("mode02", "Modo 02 · freeze frame", sc.mode02),
                    ("dtc", "Modos 03/07/0A · falhas", sc.dtcs),
                    ("mode06", "Modo 06 · resultados de testes", sc.mode06),
                    ("mode09", "Modo 09 · identificação", sc.mode09),
                    ("uds", "UDS 0x22/0x19/0x3E · identificação estendida", sc.uds),
                ):
                    prog(f"Central {rid}: {label}")
                    try:
                        ecu[key] = fn()
                    except ELMError:
                        raise
                    except Exception as e:  # noqa — uma sonda com erro não derruba o resto
                        ecu[key] = {"error": f"{type(e).__name__}: {e}"}
                report["ecus"].append(ecu)
        finally:
            for c in ("ATH0", "ATSH7DF"):
                try:
                    elm.send(c)
                except ELMError:
                    pass
    report["finished"] = time.time()
    return report
