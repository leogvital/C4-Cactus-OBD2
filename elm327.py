"""Cliente ELM327 via Wi-Fi (TCP). Sem dependências externas."""
import socket
import time
import threading
from collections import deque

DEFAULT_HOST = "192.168.0.10"
DEFAULT_PORT = 35000


class ELMError(Exception):
    pass


# ---------- log compartilhado (TX/RX/INFO/ERR) ----------
_LOG = deque(maxlen=5000)
_LOG_SEQ = [0]
_LOG_LOCK = threading.Lock()
_ctx = threading.local()   # origem do comando: "user" (padrão) ou "poll" (leitura ao vivo)


def set_source(src):
    _ctx.src = src


def log(kind, text, ms=None):
    with _LOG_LOCK:
        _LOG_SEQ[0] += 1
        _LOG.append({
            "id": _LOG_SEQ[0], "t": time.time(), "kind": kind,
            "src": getattr(_ctx, "src", "user"), "text": text, "ms": ms,
        })


def log_since(since=0):
    with _LOG_LOCK:
        return [e for e in _LOG if e["id"] > since]


def log_clear():
    with _LOG_LOCK:
        _LOG.clear()


class ELM327:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.lock = threading.RLock()
        self.version = ""
        self.protocol = ""
        self.fast = True          # leitura rápida: pede só 1 resposta (sufixo de contagem) nas leituras ao vivo
        self._no_count = False    # o adaptador recusou o sufixo
        self.last_raw = ""

    # ---------- conexão ----------
    def connect(self):
        self.close()
        log("INFO", f"Conectando em {self.host}:{self.port} ...")
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            self.sock = None
            log("ERR", f"Falha ao conectar em {self.host}:{self.port}: {e}")
            raise ELMError(
                f"Não foi possível conectar em {self.host}:{self.port} ({e}). "
                "Verifique se o celular/PC está na rede Wi-Fi do adaptador."
            )
        self.sock.settimeout(self.timeout)
        log("INFO", "Socket TCP aberto; inicializando adaptador")
        self._init_adapter()
        log("INFO", f"Pronto: {self.version} | protocolo ELM {self.protocol}")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    @property
    def connected(self):
        return self.sock is not None

    def _init_adapter(self):
        self.send("ATZ", wait=1.5)             # reset
        self.version = self.send("ATI").strip()
        self.send("ATE0")                      # sem eco
        self.send("ATL0")                      # sem line feed
        self.send("ATS0")                      # sem espaços
        self.send("ATH0")                      # sem headers
        self.send("ATAT1")                     # timing adaptativo
        self.send("ATSP0")                     # protocolo automático (PSA usa CAN 11bit/500k)
        # força a negociação do protocolo
        r = self.send("0100", wait=8.0)
        if "UNABLE" in r or "ERROR" in r or "NO DATA" in r and "41" not in r:
            raise ELMError(
                "Adaptador conectou, mas a ECU não respondeu. "
                "Ligue a ignição (ou ligue o motor) e tente de novo."
            )
        self.protocol = self.send("ATDPN").strip().lstrip("A")

    # ---------- E/S ----------
    def send(self, cmd, wait=None):
        """Envia comando, registra no log e devolve a resposta (texto limpo)."""
        log("TX", cmd)
        t0 = time.time()
        try:
            out = self._io(cmd, wait)
        except ELMError as e:
            log("ERR", str(e), ms=round((time.time() - t0) * 1000))
            raise
        log("RX", out.replace("\n", " | ") if out else "(vazio)", ms=round((time.time() - t0) * 1000))
        return out

    def _io(self, cmd, wait=None):
        if not self.sock:
            raise ELMError("Não conectado")
        with self.lock:
            self.sock.settimeout(wait or self.timeout)
            try:
                # descarta lixo pendente
                self.sock.setblocking(False)
                try:
                    while self.sock.recv(4096):
                        pass
                except (BlockingIOError, OSError):
                    pass
                self.sock.settimeout(wait or self.timeout)
                self.sock.sendall((cmd + "\r").encode())
                buf = b""
                deadline = time.time() + (wait or self.timeout)
                while time.time() < deadline:
                    try:
                        chunk = self.sock.recv(4096)
                    except socket.timeout:
                        break
                    if not chunk:
                        self.close()
                        raise ELMError("Conexão encerrada pelo adaptador")
                    buf += chunk
                    if b">" in buf:
                        break
            except OSError as e:
                self.close()
                raise ELMError(f"Erro de comunicação: {e}")
        text = buf.decode(errors="ignore").replace(">", "")
        lines = [l.strip() for l in text.replace("\n", "\r").split("\r") if l.strip()]
        lines = [l for l in lines if l.upper() != cmd.upper()]
        return "\n".join(lines)

    def query(self, cmd):
        """Envia comando OBD e devolve bytes de dados (já sem o cabeçalho 4x yy)."""
        r = self.send(cmd)
        self.last_raw = r
        if any(k in r for k in ("NO DATA", "UNABLE", "ERROR", "?", "STOPPED")):
            return None
        return r

    # ---------- OBD ----------
    def raw_bytes(self, cmd, expect, retries=0):
        """Retorna lista de bytes do payload após `expect` (ex.: '410C'). Usa a 1ª central que respondeu."""
        for _ in range(retries + 1):
            r = self.query(cmd)
            if not r:
                continue
            for h in self._responses(r):
                if h.startswith(expect):
                    data = h[len(expect):]
                    try:
                        return [int(data[j:j + 2], 16) for j in range(0, len(data) - 1, 2)]
                    except ValueError:
                        pass
        return None

    def read_pid(self, pid, retries=0, quick=False):
        """Lê um PID do modo 01. Com quick=True e leitura rápida ligada, acrescenta o sufixo "1" (ex.: 010C1):
        o ELM327 devolve assim que a 1ª central responde, sem esperar o tempo limite (~200 ms) por outras."""
        pid = pid.upper()
        if quick and self.fast and not self._no_count:
            for _ in range(retries + 1):
                d = self.raw_bytes("01" + pid + "1", "41" + pid)
                if d is not None:
                    return d
                if "?" in self.last_raw:        # adaptador não entende o sufixo: volta ao modo normal
                    self._no_count = True
                    log("INFO", "O adaptador não aceitou o sufixo de contagem; leitura rápida desligada")
                    break
            else:
                return None
        return self.raw_bytes("01" + pid, "41" + pid, retries)

    def supported_pids(self):
        sup = set()
        base = 0x00
        while True:
            d = self.read_pid(f"{base:02X}", retries=2)   # uma falha isolada não pode cortar a lista
            if not d or len(d) < 4:
                break
            mask = int.from_bytes(bytes(d[:4]), "big")
            for i in range(32):
                if mask & (1 << (31 - i)):
                    sup.add(base + i + 1)
            if not mask & 1:
                break
            base += 0x20
            if base > 0xC0:
                break
        return sorted(sup)

    @staticmethod
    def _responses(r):
        """Separa a resposta em uma string hex POR central (ECU) que respondeu.

        Várias centrais podem responder à mesma consulta (ex.: motor e câmbio); com ATH0
        não há como saber quem é quem, então cada linha independente é uma central.
        Multi-frame ISO-TP: linha de contagem (ex.: 014) + linhas "0:", "1:"... = UMA central.
        """
        hexd = "0123456789ABCDEF"
        out, cur = [], None
        for line in r.split("\n"):
            h = line.replace(" ", "").upper()
            if not h:
                continue
            if ":" in h:
                data = h.split(":", 1)[1]
                if cur is None:
                    out.append(data)
                    cur = len(out) - 1
                else:
                    out[cur] += data
            elif len(h) == 3 and all(c in hexd for c in h):
                out.append("")           # início de multi-frame
                cur = len(out) - 1
            else:
                out.append(h)
                cur = None
        return [x for x in out if x]

    def read_dtcs(self, mode="03"):
        """mode 03 = confirmados, 07 = pendentes, 0A = permanentes (união das centrais)."""
        expect = f"{int(mode, 16) + 0x40:02X}"
        r = self.query(mode)
        if not r:
            return []
        can = bool(self.protocol) and self.protocol[:1] in "6789ABC"
        codes = []
        for h in self._responses(r):
            if not h.startswith(expect):
                continue
            h = h[2:]
            if can:                      # CAN: 1º byte = nº de DTCs desta central
                h = h[2:]
            for i in range(0, len(h) - 3, 4):
                try:
                    w = int(h[i:i + 4], 16)
                except ValueError:
                    break
                if w:
                    c = decode_dtc(w)
                    if c not in codes:
                        codes.append(c)
        return codes

    def clear_dtcs(self):
        r = self.send("04")
        return "44" in r

    def ecu_reset(self, ecu_id="7E0", sub="01"):
        """UDS 0x11 (ECU Reset) na central do motor. Só IDs OBD 7E0–7E7 e subserviços 01 (hard) / 03 (soft).
        Devolve {"ok", "detail", "raw"}; a central pode recusar (resposta negativa) ou não responder."""
        from capabilities import frames, NRC     # import tardio: capabilities importa este módulo
        ecu, sub = str(ecu_id).strip().upper().zfill(3), str(sub).strip().upper().zfill(2)
        if ecu not in {f"7E{i}" for i in range(8)}:
            raise ELMError("Reset liberado só para centrais OBD (IDs 7E0 a 7E7)")
        if sub not in ("01", "03"):
            raise ELMError("Subserviço de reset inválido (use 01 ou 03)")
        resp = f"{int(ecu, 16) + 8:03X}"
        with self.lock:
            try:
                self.send("ATH1")
                self.send(f"ATSH{ecu}")
                self.send(f"ATCRA{resp}")
                raw = self.send("11" + sub, wait=5.0)
            finally:
                for c in ("ATAR", "ATH0", "ATSH7DF"):
                    try:
                        self.send(c)
                    except ELMError:
                        pass
        for f in frames(raw):
            d = f["data"]
            if d[:2] == bytes([0x51, int(sub, 16)]):
                return {"ok": True, "raw": raw, "detail": f"Central {ecu} aceitou o reset (resposta positiva 51 {sub})."}
            if len(d) >= 3 and d[0] == 0x7F and d[1] == 0x11:
                why = NRC.get(d[2], "motivo desconhecido")
                return {"ok": False, "raw": raw, "detail": f"Central {ecu} recusou o reset (código 0x{d[2]:02X}: {why})."}
        return {"ok": False, "raw": raw, "detail": f"Sem resposta da central {ecu}; não dá para saber se o reset ocorreu."}

    def vin(self):
        """Lê o VIN (modo 09 PID 02). Desliga o timing adaptativo durante a leitura, porque
        a resposta multi-frame é mais lenta que o timeout aprendido. Retorna texto; se vier
        incompleto, acrescenta '(parcial)'."""
        with self.lock:
            try:
                self.send("ATAT0")
                self.send("ATSTFF")
                r = self.send("0902", wait=6.0)
            finally:
                for c in ("ATAT1", "ATST32"):
                    try:
                        self.send(c)
                    except ELMError:
                        pass
        if any(k in r for k in ("NO DATA", "UNABLE", "ERROR", "?", "STOPPED")):
            return None
        best = ""
        for h in self._responses(r):
            i = h.find("4902")
            if i < 0:
                continue
            h = h[i + 6:]                # pula 49 02 01
            try:
                b = bytes.fromhex(h[: len(h) // 2 * 2])
            except ValueError:
                continue
            txt = "".join(chr(c) for c in b if 32 < c < 127)
            if len(txt) > len(best):
                best = txt
        if not best:
            return None
        best = best[:17]
        return best if len(best) == 17 else best + " (parcial — a ECU não enviou o restante)"

    def battery_voltage(self):
        r = self.send("ATRV")
        return r.strip()


def decode_dtc(word):
    letters = "PCBU"
    return f"{letters[(word >> 14) & 3]}{(word >> 12) & 3}{(word >> 8) & 0xF:X}{(word >> 4) & 0xF:X}{word & 0xF:X}"
