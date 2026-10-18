"""Simulador de adaptador ELM327 Wi-Fi (TCP) para testar o app sem o carro.

Uso:  python3 simulator.py [porta]      (padrão 35000)
Depois rode o app com:  python3 app.py --host 127.0.0.1 --port 35000
"""
import math
import socketserver
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 35000
T0 = time.time()
DTCS = [0x0420, 0x0171]  # P0420, P0171
MIL = True
VIN = "VR7SIXXXXXXXXXXXX"[:17]
HDR = "7DF"
HDRON = False
SIM_RESET_REFUSE = "--refuse-reset" in sys.argv
ENGINE_OFF = "--engine-off" in sys.argv
TWO_ECUS = "--two-ecus" in sys.argv      # motor + outra central respondendo (como no Cactus real)
SHORT_VIN = "--short-vin" in sys.argv
ELM_TIMING = "--elm-timing" in sys.argv   # imita o atraso real do ELM327 (~200 ms por resposta; 2 centrais ~400 ms)    # clone que devolve só o 1º quadro do VIN


def pid_values():
    t = time.time() - T0
    rpm = 850 + 400 * (math.sin(t / 3) + 1) + (1500 if int(t / 20) % 2 else 0)
    spd = max(0, int(40 + 35 * math.sin(t / 8))) if int(t / 20) % 2 else 0
    if ENGINE_OFF:
        rpm, spd = 0, 0
    return {
        0x04: [int(25 * 255 / 100 + 20 * (rpm / 3000) * 2)],
        0x05: [90 + 40],
        0x06: [128 + 3], 0x07: [128 - 2],
        0x0B: [34 + int(rpm / 100)],
        0x0C: list(int(rpm * 4).to_bytes(2, "big")),
        0x0D: [spd],
        0x0E: [int((12 + rpm / 400 + 64) * 2)],
        0x0F: [28 + 40],
        0x10: list(int((rpm / 1000 * 3.2 + 2) * 100).to_bytes(2, "big")),
        0x11: [int(15 * 255 / 100 + spd)],
        0x14: [int((0.45 + 0.4 * math.sin(t * 2)) * 200), 0xFF],
        0x15: [int(0.7 * 200), 0xFF],
        0x1F: list(int(t).to_bytes(2, "big")),
        0x2F: [int(62 * 255 / 100)],
        0x33: [92],
        0x42: list(int(14100).to_bytes(2, "big")),
        0x46: [30 + 40],
    }


def mask_for(base):
    vals = pid_values()
    m = 0
    for p in vals:
        if base < p <= base + 0x20:
            m |= 1 << (32 - (p - base))
    if any(p > base + 0x20 for p in vals):
        m |= 1
    return list(m.to_bytes(4, "big"))


def hexs(bs):
    return " ".join(f"{b:02X}" for b in bs)


def _respond_one(cmd):
    global DTCS, MIL
    c = cmd.strip().upper().replace(" ", "")
    if c.startswith("ATZ"):
        return "\r\rELM327 v1.5 (SIM)"
    if c == "ATI":
        return "ELM327 v1.5 (SIM)"
    if c.startswith("ATDPN"):
        return "A6"
    if c == "ATRV":
        return "14.1V"
    if c == "AT@1":
        return "OBDII to RS232 Interpreter (SIM)"
    if c == "ATDP":
        return "ISO 15765-4 (CAN 11/500)"
    if c.startswith("ATSH"):
        global HDR
        HDR = c[4:]
        return "OK"
    if c.startswith("AT"):
        return "OK"
    if c[:2] == "11":
        if HDR == "7E0":
            return "7F 11 22" if SIM_RESET_REFUSE else "51 " + c[2:4]
        return "NO DATA"
    if c == "04":
        DTCS, MIL = [], False
        return "44"
    if c in ("03", "07", "0A"):
        mode = int(c, 16) + 0x40
        if c != "03":
            return f"{mode:02X} 00"
        body = [mode, len(DTCS)]
        for d in DTCS:
            body += list(d.to_bytes(2, "big"))
        if len(body) > 7:  # multi-frame
            h = hexs(body)
            return f"{len(body):03X}\r0: {h[:20]}\r1: {h[21:]}"
        return hexs(body)
    if c == "0902":
        body = [0x49, 0x02, 0x01] + [ord(ch) for ch in VIN]
        h = hexs(body)
        return f"014\r0: {h[:17]}\r1: {h[18:38]}\r2: {h[39:]}"
    if len(c) == 4 and c.startswith("01"):
        pid = int(c[2:], 16)
        if pid in (0x00, 0x20, 0x40, 0x60):
            return hexs([0x41, pid] + mask_for(pid))
        if pid == 0x01:
            b = (0x80 if MIL else 0) | len(DTCS)
            return hexs([0x41, 0x01, b, 0x07, 0xE5, 0x61 if MIL else 0x00])
        vals = pid_values()
        if pid in vals:
            return hexs([0x41, pid] + vals[pid])
    return "NO DATA"


def _to_bytes(out):
    """Converte a saída ATH0 (texto) do simulador em bytes de payload."""
    if not out or "NO DATA" in out:
        return None
    hx = ""
    for line in out.split("\r"):
        line = line.replace(" ", "")
        if ":" in line:
            hx += line.split(":", 1)[1]
        elif len(line) == 3:
            continue
        else:
            hx += line
    try:
        return bytes.fromhex(hx)
    except ValueError:
        return None


def _mask(*pids_):
    m = 0
    for p in pids_:
        m |= 1 << (32 - p)
    return m.to_bytes(4, "big")


def _ecu_payload(ecu, c):
    """Payload UDS/OBD da central 1 (motor) ou 2 (outra), para o modo ATH1."""
    try:
        req = bytes.fromhex(c)
    except ValueError:
        return None
    if not req:
        return None
    svc = req[0]
    if ecu == 4:   # airbag fictício (744 -> 644): UDS 19 02 com 2 falhas
        if svc == 0x19:
            return bytes([0x59, 0x02, 0xFF, 0x86, 0x10, 0x00, 0x09, 0x73, 0x63, 0x00, 0x28])
        if svc == 0x3E:
            return bytes([0x7E, 0x00])
        return bytes([0x7F, svc, 0x11])
    if ecu == 5:   # ABS fictício (6AD -> 68D): só KWP 17 FF00
        if svc == 0x17:
            return bytes([0x57, 0x02, 0x05, 0x62, 0x08, 0x06, 0x06, 0x28])
        return bytes([0x7F, svc, 0x11])
    if ecu == 3:   # módulo fictício (6A8 -> 688) só para testar a aba Módulos
        if svc == 0x3E:
            return bytes([0x7E, 0x00])
        if svc == 0x22 and req[1:3].hex().upper() == "F190":
            return bytes([0x62, 0xF1, 0x90]) + VIN.encode()
        return bytes([0x7F, svc, 0x11])
    if ecu == 2:
        if svc == 0x01 and len(req) > 1 and req[1] == 0x00:
            return bytes([0x41, 0x00]) + _mask(4)       # só o PID 04
        if svc == 0x01 and len(req) > 1 and req[1] == 0x04:
            return bytes([0x41, 0x04, 0x80])
        if svc == 0x22:
            return bytes([0x7F, 0x22, 0x31])
        return None
    if svc == 0x11 and len(req) > 1:
        return bytes([0x7F, 0x11, 0x22]) if SIM_RESET_REFUSE else bytes([0x51, req[1]])
    if svc in (0x01, 0x03, 0x07, 0x0A):
        return _to_bytes(_respond_one(c))
    if svc == 0x02:
        if req[1] == 0x00:
            return bytes([0x42, 0x00, 0x00]) + _mask(2)
        if req[1] == 0x02:
            return bytes([0x42, 0x02, 0x00, 0x00, 0x00])
        return None
    if svc == 0x06:
        if req[1] == 0x00:
            return bytes([0x46, 0x00]) + (0xC0000001).to_bytes(4, "big")
        if req[1] == 0x20:
            return bytes([0x46, 0x20, 0, 0, 0, 0])
        if req[1] == 0x01:
            return bytes([0x46, 0x01, 0x86, 0x0B, 0x00, 0x10, 0x00, 0x00, 0xFF, 0xFF])
        if req[1] == 0x02:
            return bytes([0x46, 0x02, 0x80, 0x0B, 0x00, 0x05, 0x00, 0x00, 0x00, 0x20,
                          0x81, 0x0B, 0x00, 0x02, 0x00, 0x00, 0x00, 0x20])
        return None
    if svc == 0x09:
        if req[1] == 0x00:
            return bytes([0x49, 0x00]) + bytes([0x54, 0x40, 0x00, 0x00])
        if req[1] == 0x02:
            return bytes([0x49, 0x02, 0x01]) + VIN.encode()
        if req[1] == 0x04:
            return bytes([0x49, 0x04, 0x01]) + b"SIMCAL0000000001"
        if req[1] == 0x06:
            return bytes([0x49, 0x06, 0x01, 0xDE, 0xAD, 0xBE, 0xEF])
        if req[1] == 0x0A:
            return bytes([0x49, 0x0A, 0x01]) + b"ECM-ENGINE".ljust(20, b"\x00")
        return None
    if svc == 0x22:
        did = req[1:3].hex().upper()
        if did == "F190":
            return bytes([0x62, 0xF1, 0x90]) + VIN.encode()
        if did == "F194":
            return bytes([0x62, 0xF1, 0x94]) + b"SW-SIM-1234"
        return bytes([0x7F, 0x22, 0x31])
    if svc == 0x19:
        return bytes([0x7F, 0x19, 0x11])
    if svc == 0x3E:
        return bytes([0x7E, 0x00])
    return None


def _frame(cid, p):
    if len(p) <= 7:
        return [f"{cid}{len(p):02X}{p.hex().upper()}"]
    out = [f"{cid}1{len(p) >> 8:X}{len(p) & 0xFF:02X}{p[:6].hex().upper()}"]
    rest, n = p[6:], 1
    while rest:
        out.append(f"{cid}2{n % 16:X}{rest[:7].hex().upper()}")
        rest, n = rest[7:], n + 1
    return out


def _respond_headers(c):
    if HDR == "7DF":
        ecus = [1] + ([2] if TWO_ECUS else [])
    elif HDR == "7E0":
        ecus = [1]
    elif HDR == "7E1":
        ecus = [2] if TWO_ECUS else []
    elif HDR == "6A8":
        ecus = [3]
    elif HDR == "744":
        ecus = [4]
    elif HDR == "6AD":
        ecus = [5]
    else:
        ecus = []
    lines = []
    for e in ecus:
        p = _ecu_payload(e, c)
        if p:
            lines += _frame({1: "7E8", 2: "7E9", 3: "688", 4: "644", 5: "68D"}[e], p)
    return "\r".join(lines) if lines else "NO DATA"


def _strip_count(cmd):
    """Sufixo de contagem do ELM327 (ex.: 010C1): devolve (comando sem o sufixo, True se havia)."""
    c = cmd.strip().upper().replace(" ", "")
    if len(c) == 5 and c.startswith("01"):
        return c[:4], True
    return cmd, False


def respond(cmd):
    global HDRON
    c0 = cmd.strip().upper().replace(" ", "")
    if c0 == "ATH1":
        HDRON = True
        return "OK"
    if c0 == "ATH0":
        HDRON = False
        return "OK"
    if HDRON and not c0.startswith("AT"):
        if c0 == "04":
            return _respond_one(cmd)  # (não usado no scan)
        return _respond_headers(c0)
    out = _respond_one(cmd)
    c = c0
    if SHORT_VIN and c == "0902":
        return "14490201393335"
    if TWO_ECUS:
        if c == "03":
            out += "\r43 00"
        elif c == "07":
            out += "\r47 00"
        elif c in ("0100", "0140", "0142"):
            out += "\r" + out
    return out


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        buf = b""
        print("cliente conectado:", self.client_address)
        while True:
            try:
                data = self.request.recv(1024)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                cmd = line.decode(errors="ignore")
                if not cmd.strip():
                    continue
                cmd, had = _strip_count(cmd)
                time.sleep(0.03)
                if ELM_TIMING and not cmd.strip().upper().startswith("AT"):
                    time.sleep(0.02 if had else (0.4 if TWO_ECUS else 0.2))
                out = respond(cmd)
                if had:
                    out = out.split("\r")[0]   # só a 1ª resposta
                print(f"  > {cmd}  < {out.replace(chr(13), ' | ')}")
                self.request.sendall(f"{out}\r\r>".encode())
        print("cliente desconectou")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"Simulador ELM327 em 0.0.0.0:{PORT}")
    Server(("0.0.0.0", PORT), Handler).serve_forever()
