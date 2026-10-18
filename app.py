"""Servidor local + painel web para diagnóstico OBD2 via adaptador ELM327 Wi-Fi.

Uso:
    python3 app.py                                  # adaptador real (192.168.0.10:35000)
    python3 app.py --host 127.0.0.1 --port 35000    # simulador
Abra http://localhost:8080 no navegador.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import audit
import pids
import capabilities
import modules
import elm327
from elm327 import ELM327, ELMError, DEFAULT_HOST, DEFAULT_PORT
from version import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")


class State:
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.elm = None
        self.error = ""
        self.live = {}
        self.supported = []
        self.poll_pids = list(pids.LIVE_DEFAULT)
        self.stop = threading.Event()
        self.thread = None
        self.log = []
        self.scan = {"running": False, "step": "", "done": 0, "error": "", "result": None}
        self.connected_at = None
        self.status = None         # PID 01 (MIL, nº de falhas), lido de tempos em tempos para o painel

    def log_add(self, msg):
        elm327.log("INFO", msg)

    def connect(self, host, port):
        self.disconnect()
        self.host, self.port = host, port
        elm = ELM327(host, port)
        try:
            elm.connect()
        except ELMError as e:
            self.error = str(e)
            self.log_add(f"Falha: {e}")
            audit.record("CONECTAR_FALHA", f"{host}:{port}", e)
            elm.close()
            raise
        self.elm, self.error = elm, ""
        self.connected_at = time.time()
        audit.record("CONECTAR_OK", f"{host}:{port}", elm.version, f"protocolo {elm.protocol}")
        self.log_add(f"Conectado: {elm.version} | protocolo {elm.protocol}")
        self.supported = [f"{p:02X}" for p in elm.supported_pids()]
        self.poll_pids = [p for p in pids.LIVE_DEFAULT if p in self.supported] or pids.LIVE_DEFAULT
        self.stop.clear()
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def start_scan(self):
        if self.scan["running"]:
            raise ELMError("Diagnóstico já em andamento")
        elm = self.elm
        if not (elm and elm.connected):
            raise ELMError("Não conectado ao adaptador")
        self.scan = {"running": True, "step": "Iniciando", "done": 0, "error": "", "result": None}
        scan = self.scan

        def prog(msg):
            scan["step"] = msg
            scan["done"] += 1

        audit.record("DIAGNOSTICO_INICIO", "varredura de capacidades (somente leitura)")

        def work():
            try:
                scan["result"] = capabilities.run(elm, prog)
                scan["step"] = "Concluído"
                audit.record("DIAGNOSTICO_FIM", "concluído")
            except ELMError as e:
                scan["error"] = str(e)
                audit.record("DIAGNOSTICO_FIM", f"erro: {e}")
            except Exception as e:  # noqa
                scan["error"] = f"{type(e).__name__}: {e}"
                audit.record("DIAGNOSTICO_FIM", f"erro: {scan['error']}")
            finally:
                scan["running"] = False

        threading.Thread(target=work, daemon=True).start()

    def disconnect(self, reason="usuário"):
        if self.elm and self.connected_at:
            secs = int(time.time() - self.connected_at)
            audit.record("DESCONECTAR", f"{self.host}:{self.port}", f"motivo: {reason}", f"duração {secs // 60}min{secs % 60:02d}s")
            self.connected_at = None
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.elm:
            self.elm.close()
        self.elm, self.live, self.status = None, {}, None

    def _poll(self):
        elm327.set_source("poll")   # marca esses comandos como "leitura ao vivo" no log
        slow_i = cycles = 0
        while not self.stop.is_set() and self.elm and self.elm.connected:
            fast = [p for p in self.poll_pids if p in pids.FAST]
            slow = [p for p in self.poll_pids if p not in pids.FAST]
            batch = list(fast)
            if slow:                       # 1 PID lento por ciclo, em rodízio
                batch.append(slow[slow_i % len(slow)])
                slow_i += 1
            for pid in batch:
                if self.stop.is_set():
                    return
                try:
                    r = pids.decode(pid, self.elm.read_pid(pid, retries=1))
                except ELMError as e:
                    self.error = str(e)
                    self.log_add(f"Conexão perdida: {e}")
                    audit.record("CONEXAO_PERDIDA", f"{self.host}:{self.port}", e)
                    return
                if r:
                    r["t"] = time.time()
                    self.live[pid] = r
            cycles += 1
            if cycles % 25 == 1:                   # status (luz de injeção) a cada ~25 ciclos
                try:
                    self.status = pids.decode_status(self.elm.read_pid("01", retries=1))
                except ELMError:
                    pass
            time.sleep(0.02)


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _need(self):
            if not (state.elm and state.elm.connected):
                raise ELMError("Não conectado ao adaptador")
            return state.elm

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    with open(os.path.join(WEB, "index.html"), "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif self.path == "/api/status":
                    c = bool(state.elm and state.elm.connected)
                    self._json({
                        "connected": c, "host": state.host, "port": state.port, "error": state.error,
                        "version": state.elm.version if c else "", "protocol": state.elm.protocol if c else "",
                        "app_version": __version__, "dtc_table": pids.peugeot_available(),
                    })
                elif self.path == "/api/changelog":
                    try:
                        with open(os.path.join(HERE, "CHANGELOG.md"), encoding="utf-8") as f:
                            text = f.read()
                    except OSError:
                        text = ""
                    self._json({"version": __version__, "changelog": text})
                elif self.path == "/api/connection-log":
                    self._json({"file": audit.LOG_FILE, "events": audit.tail()})
                elif self.path.startswith("/api/dtc-search"):
                    from urllib.parse import urlparse, parse_qs
                    q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
                    self._json(pids.peugeot_search(q))
                elif self.path == "/api/scan/status":
                    sc = state.scan
                    self._json({"running": sc["running"], "step": sc["step"], "done": sc["done"],
                                "error": sc["error"], "has_result": sc["result"] is not None})
                elif self.path == "/api/scan/result":
                    if state.scan["result"] is None:
                        raise ELMError("Nenhum diagnóstico concluído ainda")
                    self._json(state.scan["result"])
                elif self.path.startswith("/api/log"):
                    since = 0
                    if "since=" in self.path:
                        try:
                            since = int(self.path.split("since=")[1].split("&")[0])
                        except ValueError:
                            pass
                    self._json({"entries": elm327.log_since(since)})
                elif self.path == "/api/live":
                    self._json({"values": list(state.live.values()), "status": state.status, "error": state.error,
                                "connected": bool(state.elm and state.elm.connected)})
                elif self.path == "/api/dtcs":
                    elm = self._need()
                    st = pids.decode_status(elm.read_pid("01"))
                    out = {"status": st}
                    for key, mode in (("confirmed", "03"), ("pending", "07"), ("permanent", "0A")):
                        out[key] = [{"code": c, "desc": pids.describe_dtc(c), "peugeot": pids.peugeot_lookup(c)}
                                    for c in elm.read_dtcs(mode)]
                    self._json(out)
                elif self.path == "/api/info":
                    elm = self._need()
                    self._json({"vin": elm.vin(), "voltage": elm.battery_voltage(),
                                "supported": state.supported, "version": elm.version,
                                "protocol": elm.protocol})
                else:
                    self._json({"error": "not found"}, 404)
            except ELMError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            try:
                b = self._body()
                if self.path == "/api/connect":
                    state.connect(b.get("host") or state.host, int(b.get("port") or state.port))
                    self._json({"ok": True})
                elif self.path == "/api/disconnect":
                    state.disconnect()
                    self._json({"ok": True})
                elif self.path == "/api/clear":
                    elm = self._need()
                    if not b.get("confirm"):
                        raise ELMError("Confirmação ausente")
                    audit.record("APAGAR_FALHAS", f"{state.host}:{state.port}", "modo 04")
                    self._json({"ok": elm.clear_dtcs()})
                elif self.path == "/api/scan/start":
                    self._need()
                    state.start_scan()
                    self._json({"ok": True})
                elif self.path == "/api/uds":
                    elm = self._need()
                    audit.record("CONSULTA_MODULO", f"{b.get('req_id')}->{b.get('resp_id')}", b.get("cmd"))
                    self._json(modules.query(elm, b.get("req_id"), b.get("resp_id"), b.get("cmd")))
                elif self.path == "/api/module-dtcs":
                    elm = self._need()
                    audit.record("FALHAS_MODULO", f"{b.get('req_id')}->{b.get('resp_id')}", b.get("hint"))
                    self._json(modules.read_dtcs(elm, b.get("req_id"), b.get("resp_id"), b.get("hint")))
                elif self.path == "/api/log/clear":
                    elm327.log_clear()
                    self._json({"ok": True})
                elif self.path == "/api/ecu-reset":
                    elm = self._need()
                    if not b.get("confirm"):
                        raise ELMError("Confirmação ausente")
                    rpm = state.live.get("0C")
                    if not rpm or time.time() - rpm["t"] > 5:
                        raise ELMError("Sem leitura recente de RPM — não é possível confirmar que o motor está parado")
                    if rpm["value"] > 50:
                        raise ELMError("Motor em funcionamento. Desligue o motor (deixe só a ignição ligada) e tente de novo.")
                    spd = state.live.get("0D")
                    if spd and spd["value"] > 0:
                        raise ELMError("Veículo em movimento — reset bloqueado")
                    ecu, sub = b.get("ecu_id") or "7E0", b.get("sub") or "01"
                    res = elm.ecu_reset(ecu, sub)
                    audit.record("RESET_ECU", f"{state.host}:{state.port}", f"ECU {ecu}", f"sub {sub}", "ok" if res.get("ok") else "sem confirmação")
                    self._json(res)
                elif self.path == "/api/raw":
                    elm = self._need()
                    cmd = str(b.get("cmd", "")).strip()
                    if not cmd:
                        raise ELMError("Comando vazio")
                    # só leitura/diagnóstico: AT* e modos OBD de consulta (01,02,03,07,09,0A)
                    c = cmd.upper().replace(" ", "")
                    if not (c.startswith("AT") or c[:2] in ("01", "02", "03", "07", "09", "0A")):
                        raise ELMError("Terminal liberado só para AT e modos de leitura (01, 02, 03, 07, 09, 0A)")
                    audit.record("TERMINAL", cmd)
                    self._json({"response": elm.send(cmd, wait=6.0)})
                else:
                    self._json({"error": "not found"}, 404)
            except ELMError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST, help="IP do adaptador Wi-Fi")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="porta TCP do adaptador")
    ap.add_argument("--web-port", type=int, default=8080)
    a = ap.parse_args()
    state = State(a.host, a.port)
    srv = ThreadingHTTPServer(("127.0.0.1", a.web_port), make_handler(state))
    print(f"psa_obd v{__version__} — painel: http://localhost:{a.web_port}   (adaptador {a.host}:{a.port})")
    print(f"Log de conexões: {audit.LOG_FILE}")
    audit.record("APP_INICIO", f"v{__version__}", f"adaptador padrão {a.host}:{a.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.disconnect("encerramento do app")
        audit.record("APP_FIM", f"v{__version__}")


if __name__ == "__main__":
    main()
