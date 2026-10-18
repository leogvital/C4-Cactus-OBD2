"""Decodificação dos PIDs OBD-II padrão (SAE J1979) mais úteis para um motor aspirado."""

STATUS_NAMES = {
    0: "Falha de ignição (misfire)", 1: "Sistema de combustível", 2: "Componentes abrangentes",
    4: "Catalisador", 5: "Catalisador aquecido", 6: "Sistema evaporativo (EVAP)",
    7: "Ar secundário", 8: "Sistema de A/C", 9: "Sonda lambda", 10: "Aquecedor da lambda",
}


def _a(d): return d[0]


# PID 03: só o byte do sistema 1 é usado (o 2º vem 0 em carros de um só circuito)
FUEL_SYSTEM = {0: "Desligado", 1: "Malha aberta (motor frio)", 2: "Malha fechada (usa a lambda)",
               4: "Malha aberta (carga/desaceleração)", 8: "Malha aberta (falha do sistema)",
               16: "Malha fechada (com falha na lambda)"}
# PID 51 (SAE J1979, tabela de tipo de combustível)
FUEL_TYPE = {0: "Não disponível", 1: "Gasolina", 2: "Metanol", 3: "Etanol", 4: "Diesel", 5: "GLP",
             6: "GNV", 7: "Propano", 8: "Elétrico"}


# pid: (nome, unidade, função(bytes) -> valor, bytes mínimos)
PIDS = {
    "04": ("Carga do motor", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "05": ("Temp. água", "°C", lambda d: d[0] - 40, 1),
    "06": ("Ajuste combustível curto B1", "%", lambda d: round((d[0] - 128) * 100 / 128, 1), 1),
    "07": ("Ajuste combustível longo B1", "%", lambda d: round((d[0] - 128) * 100 / 128, 1), 1),
    "0A": ("Pressão combustível", "kPa", lambda d: d[0] * 3, 1),
    "0B": ("Pressão do coletor (MAP)", "kPa", lambda d: d[0], 1),
    "0C": ("Rotação (RPM)", "rpm", lambda d: (d[0] * 256 + d[1]) / 4, 2),
    "0D": ("Velocidade", "km/h", lambda d: d[0], 1),
    "0E": ("Avanço de ignição", "°", lambda d: d[0] / 2 - 64, 1),
    "0F": ("Temp. ar admissão", "°C", lambda d: d[0] - 40, 1),
    "10": ("Vazão de ar (MAF)", "g/s", lambda d: round((d[0] * 256 + d[1]) / 100, 2), 2),
    "11": ("Posição da borboleta", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "14": ("Lambda B1S1 (tensão)", "V", lambda d: round(d[0] / 200, 3), 2),
    "15": ("Lambda B1S2 (tensão)", "V", lambda d: round(d[0] / 200, 3), 2),
    "1F": ("Tempo desde a partida", "s", lambda d: d[0] * 256 + d[1], 2),
    "21": ("Distância com MIL acesa", "km", lambda d: d[0] * 256 + d[1], 2),
    "2F": ("Nível de combustível", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "2E": ("Purga do EVAP", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "30": ("Partidas desde apagar falhas", "", lambda d: d[0], 1),
    "47": ("Borboleta absoluta B", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "4D": ("Tempo com MIL acesa", "min", lambda d: d[0] * 256 + d[1], 2),
    "52": ("Etanol no combustível", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "03": ("Estado do sistema de combustível", "", lambda d: FUEL_SYSTEM.get(d[0], f"código {d[0]:02X}"), 1),
    "1C": ("Norma OBD do veículo (código SAE J1979)", "", lambda d: d[0], 1),
    "51": ("Tipo de combustível", "", lambda d: FUEL_TYPE.get(d[0], f"código {d[0]:02X}"), 1),
    "33": ("Pressão barométrica", "kPa", lambda d: d[0], 1),
    "42": ("Tensão do módulo (ECU)", "V", lambda d: round((d[0] * 256 + d[1]) / 1000, 2), 2),
    "43": ("Carga absoluta", "%", lambda d: round((d[0] * 256 + d[1]) * 100 / 255, 1), 2),
    "44": ("Lambda comandada", "λ", lambda d: round((d[0] * 256 + d[1]) / 32768, 3), 2),
    "45": ("Posição relativa da borboleta", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "46": ("Temp. ambiente", "°C", lambda d: d[0] - 40, 1),
    "49": ("Pedal do acelerador D", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "4A": ("Pedal do acelerador E", "%", lambda d: round(d[0] * 100 / 255, 1), 1),
    "5C": ("Temp. óleo", "°C", lambda d: d[0] - 40, 1),
    "5E": ("Consumo de combustível", "L/h", lambda d: round((d[0] * 256 + d[1]) / 20, 2), 2),
}

# conjunto padrão exibido ao vivo no painel
LIVE_DEFAULT = ["0C", "0D", "05", "0F", "04", "11", "0B", "10", "0E", "06", "07", "14", "15", "42", "52", "2E", "47", "2F"]
# lidos a cada ciclo (os demais, em rodízio): rotação, velocidade, temperatura do motor e tensão
FAST = ["0C", "0D", "05", "42"]


def decode(pid, data):
    pid = pid.upper()
    if pid not in PIDS or data is None:
        return None
    name, unit, fn, n = PIDS[pid]
    if len(data) < n:
        return None
    try:
        return {"pid": pid, "name": name, "unit": unit, "value": fn(data)}
    except Exception:
        return None


def decode_status(data):
    """PID 01: MIL, nº de DTCs e monitores de prontidão (I/M)."""
    if not data or len(data) < 4:
        return None
    mil = bool(data[0] & 0x80)
    count = data[0] & 0x7F
    spark = not (data[1] & 0x08)  # bit 3: 0 = ignição por faísca (motor a gasolina/flex)
    monitors = []
    b, c, d = data[1], data[2], data[3]
    # contínuos (byte B bits 0-2: suportado; bits 4-6: incompleto)
    for bit, label in ((0, "Falha de ignição (misfire)"), (1, "Sistema de combustível"), (2, "Componentes abrangentes")):
        if b & (1 << bit):
            monitors.append({"name": label, "ready": not (b & (1 << (bit + 4)))})
    # não contínuos (faísca): C = suportado, D = incompleto
    names = ["Catalisador", "Catalisador aquecido", "Sistema evaporativo (EVAP)", "Ar secundário",
             "Sistema de A/C", "Sonda lambda", "Aquecedor da lambda", "EGR/VVT"]
    for bit, label in enumerate(names):
        if c & (1 << bit):
            monitors.append({"name": label, "ready": not (d & (1 << bit))})
    return {"mil": mil, "dtc_count": count, "monitors": monitors}


# Descrições para os DTCs genéricos mais comuns (os demais aparecem só com o código)
DTC_DESC = {
    "P0011": "Comando de came A avançado em excesso (VVT)", "P0016": "Correlação virabrequim/comando",
    "P0030": "Aquecedor da lambda B1S1", "P0036": "Aquecedor da lambda B1S2",
    "P0087": "Pressão de combustível muito baixa", "P0101": "MAF fora de faixa",
    "P0102": "MAF sinal baixo", "P0103": "MAF sinal alto", "P0106": "MAP fora de faixa",
    "P0107": "MAP sinal baixo", "P0108": "MAP sinal alto", "P0112": "Temp. ar admissão baixa",
    "P0113": "Temp. ar admissão alta", "P0116": "Temp. água fora de faixa",
    "P0117": "Temp. água sinal baixo", "P0118": "Temp. água sinal alto",
    "P0120": "Sensor posição borboleta/pedal A", "P0121": "Borboleta fora de faixa",
    "P0122": "Borboleta sinal baixo", "P0123": "Borboleta sinal alto",
    "P0125": "Temp. insuficiente p/ malha fechada", "P0128": "Termostato abaixo da temperatura",
    "P0130": "Lambda B1S1 defeito", "P0131": "Lambda B1S1 tensão baixa", "P0132": "Lambda B1S1 tensão alta",
    "P0133": "Lambda B1S1 resposta lenta", "P0134": "Lambda B1S1 sem atividade",
    "P0135": "Aquecedor lambda B1S1", "P0136": "Lambda B1S2 defeito", "P0137": "Lambda B1S2 tensão baixa",
    "P0138": "Lambda B1S2 tensão alta", "P0141": "Aquecedor lambda B1S2",
    "P0171": "Mistura pobre (banco 1)", "P0172": "Mistura rica (banco 1)",
    "P0201": "Injetor cil. 1", "P0202": "Injetor cil. 2", "P0203": "Injetor cil. 3", "P0204": "Injetor cil. 4",
    "P0300": "Falha de ignição aleatória", "P0301": "Falha de ignição cil. 1", "P0302": "Falha de ignição cil. 2",
    "P0303": "Falha de ignição cil. 3", "P0304": "Falha de ignição cil. 4",
    "P0325": "Sensor de detonação", "P0335": "Sensor de rotação (virabrequim)",
    "P0340": "Sensor de fase (comando)", "P0351": "Bobina de ignição 1", "P0352": "Bobina de ignição 2",
    "P0353": "Bobina de ignição 3", "P0354": "Bobina de ignição 4",
    "P0420": "Eficiência do catalisador abaixo do limite", "P0441": "EVAP fluxo de purga incorreto",
    "P0442": "EVAP vazamento pequeno", "P0443": "Válvula de purga EVAP", "P0455": "EVAP vazamento grande",
    "P0500": "Sensor de velocidade", "P0505": "Controle da marcha lenta", "P0506": "Marcha lenta baixa",
    "P0507": "Marcha lenta alta", "P0560": "Tensão do sistema", "P0562": "Tensão do sistema baixa",
    "P0563": "Tensão do sistema alta", "P0601": "Memória da ECU", "P0606": "Processador da ECU",
    "P0615": "Relé do motor de partida", "P0627": "Bomba de combustível", "P2101": "Atuador da borboleta",
    "P2106": "Borboleta modo limitado", "P2135": "Sensores de borboleta A/B correlação",
    "P2176": "Borboleta posição mínima não aprendida", "P2187": "Mistura pobre em marcha lenta",
    "P2188": "Mistura rica em marcha lenta",
}


def describe_dtc(code):
    return DTC_DESC.get(code, "")


# ---------- Tabela Peugeot/Citroën (gerada do PDF por tools/build_dtc_db.py) ----------
import json as _json
import os as _os

_PEUGEOT = None
# famílias de motor a gasolina primeiro (o Cactus é a gasolina/flex)
_PETROL_FIRST = ("MDE12", "MDE14", "MDE42", "MDE44", "MDE46", "MDE48")


def _peugeot():
    global _PEUGEOT
    if _PEUGEOT is None:
        path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "dtc_peugeot.json")
        try:
            with open(path, encoding="utf-8") as f:
                _PEUGEOT = _json.load(f)
        except OSError:
            _PEUGEOT = {"families": {}, "codes": {}}
    return _PEUGEOT


def peugeot_available():
    """True se a tabela local de descrições está presente (arquivo opcional, fora do repositório)."""
    return bool(_peugeot()["codes"])


def _fam(codes):
    fams = _peugeot()["families"]
    return [{"code": c, "title": fams.get(c, c)} for c in codes]


def _rank(v):
    return (0 if any(f in _PETROL_FIRST for f in v["f"]) else 1, v["f"][0])


def peugeot_lookup(code, limit=4):
    """Descrições da tabela Peugeot para um código (todas as variantes por família de módulo)."""
    vs = sorted(_peugeot()["codes"].get(code.upper().strip(), []), key=_rank)
    return [{"desc": v["d"], "families": _fam(v["f"])} for v in vs[:limit]]


def peugeot_search(q, limit=60):
    """Busca por código (exato ou prefixo) ou por texto na descrição (inglês)."""
    q = q.strip()
    if not q:
        return {"total": 0, "results": []}
    ql, qu = q.lower(), q.upper()
    out = []
    for code, vs in _peugeot()["codes"].items():
        for v in vs:
            if code.startswith(qu) or ql in v["d"].lower():
                out.append((0 if code == qu else 1, code, v))
    out.sort(key=lambda t: (t[0], t[1], _rank(t[2])))
    return {"total": len(out), "results": [
        {"code": c, "desc": v["d"], "families": _fam(v["f"])} for _, c, v in out[:limit]]}
