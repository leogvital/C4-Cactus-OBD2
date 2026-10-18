"""Consultas UDS/KWP SOMENTE LEITURA para qualquer módulo CAN (endereços informados pelo usuário).

Não há endereços de módulos PSA embutidos: eles devem vir do usuário (ex.: do software de
diagnóstico oficial). Serviços de escrita/atuação/reset/segurança são bloqueados.
"""
import elm327
from elm327 import ELMError
from capabilities import frames, NRC, _ascii

HEX = set("0123456789ABCDEF")

# serviços liberados (todos de leitura)
ALLOWED = {
    0x22: "UDS ReadDataByIdentifier",
    0x19: "UDS ReadDTCInformation",
    0x3E: "TesterPresent",
    0x1A: "KWP ReadECUIdentification",
    0x21: "KWP ReadDataByLocalIdentifier",
    0x18: "KWP ReadDTCByStatus",
    0x17: "KWP ReadStatusOfDTC",
}
BLOCKED_NAMES = {
    0x10: "troca de sessão", 0x11: "reset da ECU", 0x14: "apagar DTCs", 0x27: "acesso de segurança",
    0x28: "controle de comunicação", 0x2E: "escrita de dados", 0x2F: "controle de IO/atuadores",
    0x31: "rotinas", 0x34: "download", 0x35: "upload", 0x36: "transferência", 0x37: "fim de transferência",
    0x3B: "escrita KWP", 0x3D: "escrita em memória", 0x85: "controle de DTC", 0x30: "controle KWP",
}
NRC_EXTRA = {0x78: "resposta pendente", 0x21: "ocupado", 0x24: "erro de sequência", 0x35: "chave inválida",
             0x7F: "serviço não suportado na sessão atual"}


def _id(v, what):
    v = (v or "").strip().upper()
    if not (1 <= len(v) <= 3 and all(c in HEX for c in v)):
        raise ELMError(f"ID {what} inválido (use até 3 dígitos hex, ex.: 7E0)")
    v = v.zfill(3)
    if int(v, 16) > 0x7FF:
        raise ELMError(f"ID {what} fora da faixa CAN de 11 bits (000–7FF)")
    return v


def check_command(cmd):
    c = (cmd or "").replace(" ", "").upper()
    if not c or len(c) % 2 or len(c) > 16 or not all(x in HEX for x in c):
        raise ELMError("Comando inválido: use bytes em hexadecimal (ex.: 22F190), até 8 bytes")
    svc = int(c[:2], 16)
    if svc == 0x10 and c == "1001":
        return c  # sessão padrão: inofensivo
    if svc in BLOCKED_NAMES:
        raise ELMError(f"Serviço {svc:02X} ({BLOCKED_NAMES[svc]}) bloqueado: esta aba é somente leitura")
    if svc not in ALLOWED:
        raise ELMError(f"Serviço {svc:02X} não está na lista de leitura permitida "
                       f"({', '.join(f'{k:02X}' for k in sorted(ALLOWED))})")
    return c


def query(elm, req_id, resp_id, cmd):
    """Envia `cmd` ao módulo `req_id` e devolve as respostas interpretadas."""
    req = _id(req_id, "de requisição")
    c = check_command(cmd)
    resp = _id(resp_id, "de resposta") if resp_id else None
    if resp is None and not req.startswith("7E"):
        raise ELMError("Informe o ID de resposta (fora da faixa OBD 7E0–7E7 o adaptador não mostra respostas sem ele)")
    svc = int(c[:2], 16)
    with elm.lock:
        try:
            elm.send("ATH1")
            elm.send(f"ATSH{req}")
            if resp:
                elm.send(f"ATCRA{resp}")
                elm.send(f"ATFCSH{req}")      # flow control para o ID de requisição
                elm.send("ATFCSD300000")
                elm.send("ATFCSM1")
            raw = elm.send(c, wait=5.0)
        finally:
            for x in ("ATFCSM0", "ATAR", "ATH0", "ATSH7DF"):
                try:
                    elm.send(x)
                except ELMError:
                    pass
    out = []
    for f in frames(raw):
        d = f["data"]
        item = {"id": f["id"], "hex": d.hex().upper(), "complete": f["complete"]}
        if not d:
            item["kind"] = "vazia"
        elif d[0] == 0x7F and len(d) >= 3:
            n = d[2]
            item.update(kind="negativa", nrc=f"{n:02X}",
                        desc=NRC_EXTRA.get(n) or NRC.get(n) or "código desconhecido")
        elif d[0] == svc + 0x40:
            item.update(kind="positiva", ascii=_ascii(d[2:]))
        else:
            item["kind"] = "outra"
        out.append(item)
    return {"req_id": req, "resp_id": resp, "cmd": c, "service": ALLOWED.get(svc, "sessão padrão"),
            "responses": out, "raw": raw}


# ---------- leitura e interpretação de falhas (UDS 19 02 / KWP 17, 18) ----------
import pids
from elm327 import decode_dtc

# famílias da tabela Peugeot que correspondem a cada tipo de módulo (usadas para priorizar)
HINT_FAMILIES = {"airbag": ["MDS12"], "abs": ["MDT22"], "cluster": ["MDI04", "MDI056"]}

# bits do byte de status UDS (ISO 14229)
UDS_STATUS = [
    (0x01, "falha ativa agora"), (0x02, "falhou neste ciclo"), (0x04, "pendente"), (0x08, "confirmada"),
    (0x10, "teste não concluído desde a limpeza"), (0x20, "falhou desde a limpeza"),
    (0x40, "teste não concluído neste ciclo"), (0x80, "luz de aviso solicitada"),
]
# tentativas, na ordem: UDS (máscara FF e 09) e KWP (17 FF00 e 18 00 FF00)
DTC_ATTEMPTS = ["1902FF", "190209", "17FF00", "1800FF00"]


def _matches(keys, hint):
    hint_f = HINT_FAMILIES.get(hint or "", [])
    out, seen = [], set()
    for key, how in keys:
        for v in pids.peugeot_lookup(key, limit=60):
            sig = (key, v["desc"])
            if sig in seen:
                continue
            seen.add(sig)
            out.append({"key": key, "how": how, "desc": v["desc"], "families": v["families"],
                        "hinted": any(f["code"] in hint_f for f in v["families"])})
    out.sort(key=lambda x: not x["hinted"])
    return out[:6]


def _record(b, hint, uds):
    """b = bytes do registro: UDS = 3 de DTC + 1 de status; KWP = 2 de DTC + 1 de status."""
    d = b[:-1]
    status = b[-1]
    hi_lo = d[:2]
    raw4 = hi_lo.hex().upper()
    sae = decode_dtc(int.from_bytes(hi_lo, "big"))
    keys = [(raw4, "código bruto"), (sae, "formato SAE")]
    if len(d) == 3 and d[2]:
        keys.append((d.hex().upper(), "código bruto de 3 bytes"))
    rec = {"raw": b.hex().upper(), "code_raw": raw4, "code_sae": sae,
           "ftb": f"{d[2]:02X}" if len(d) == 3 else None, "status": f"{status:02X}",
           "matches": _matches(keys, hint)}
    if uds:
        rec["status_text"] = [t for bit, t in UDS_STATUS if status & bit]
    return rec


def parse_dtc_response(payload):
    """Interpreta 59 02 (UDS) ou 57/58 (KWP). Retorna (formato, registros_brutos) ou (None, [])."""
    if not payload:
        return None, []
    s = payload[0]
    if s == 0x59 and len(payload) >= 3 and payload[1] == 0x02:
        body = payload[3:]
        return "uds", [body[i:i + 4] for i in range(0, len(body) - 3, 4) if any(body[i:i + 3])]
    if s in (0x57, 0x58) and len(payload) >= 2:
        body = payload[2:]
        return "kwp", [body[i:i + 3] for i in range(0, len(body) - 2, 3) if any(body[i:i + 2])]
    return None, []


def read_dtcs(elm, req_id, resp_id, hint=None):
    """Tenta ler as falhas do módulo por UDS e KWP; interpreta a 1ª resposta positiva."""
    attempts, fmt, recs, used = [], None, [], None
    for cmd in DTC_ATTEMPTS:
        try:
            r = query(elm, req_id, resp_id, cmd)
        except ELMError as e:
            raise ELMError(str(e))
        pos = [x for x in r["responses"] if x["kind"] == "positiva"]
        neg = [x for x in r["responses"] if x["kind"] == "negativa"]
        attempts.append({"cmd": cmd,
                         "result": ("positiva: " + pos[0]["hex"][:60]) if pos else
                                   (f"negativa 0x{neg[0]['nrc']} {neg[0]['desc']}" if neg else "sem resposta")})
        if pos:
            fmt, raw_recs = parse_dtc_response(bytes.fromhex(pos[0]["hex"]))
            used = cmd
            recs = [_record(b, hint, fmt == "uds") for b in raw_recs]
            if fmt:
                break
    note = ("Interpretação PROVISÓRIA: o formato foi lido pelo padrão UDS/KWP e o significado do código "
            "bruto na tabela Peugeot ainda não foi confirmado neste carro. Confira sempre o dado bruto.")
    if not fmt:
        note = "Nenhum dos formatos teve resposta positiva (veja as tentativas)."
    return {"req_id": req_id.upper(), "resp_id": (resp_id or "").upper(), "hint": hint, "format": fmt,
            "command": used, "attempts": attempts, "records": recs, "note": note}
