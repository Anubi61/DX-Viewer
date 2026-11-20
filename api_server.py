from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import json
import mysql.connector
import socket
import time

with open("config.json", "r") as f:
    config = json.load(f)

DB_CONFIG = config["db"]

def _read_until_prompt(sock, timeout=3.0):
    sock.settimeout(timeout)
    data = b""
    start = time.time()
    while (time.time() - start) < timeout:
        try:
            chunk = sock.recv(2048)
            if not chunk:
                break
            data += chunk
            if b"dxspider >" in data or b"dx>" in data or b"node>" in data:
                break
        except socket.timeout:
            break
    return data

def _is_ip(token):
    return ('.' in token or ':' in token) and any(c.isdigit() for c in token)

def _is_num_or_dash(token):
    if token == "-":
        return True
    try:
        float(token)
        return True
    except ValueError:
        return False

def fetch_cluster_users_ephemeral(cluster_host, cluster_port, temp_callsign="GU3ST"):
    users = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(4.0)
        s.connect((cluster_host, cluster_port))

        # Attende eventuale richiesta login
        _read_until_prompt(s, timeout=1.5)

        # Invia nominativo temporaneo
        s.sendall((temp_callsign + "\r\n").encode("ascii"))

        # Smaltisce il banner iniziale (incluso "Please enter your name...") fino al prompt
        _read_until_prompt(s, timeout=3.0)

        # Invia comando utenti
        s.sendall(b"who\r\n")

        raw = b""
        start = time.time()
        while (time.time() - start) < 4.0:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                raw += chunk
                # Se abbiamo già visto l'intestazione e un secondo prompt finale, possiamo chiudere
                if raw.count(b"dxspider >") >= 2 or raw.count(b"dx>") >= 2:
                    break
            except socket.timeout:
                break

        try:
            s.sendall(b"BYE\r\n")
        except Exception:
            pass
        s.close()

        lines = raw.decode("utf-8", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Salta banner, prompt, echo comando e intestazione colonne
            if (
                "login:" in line.lower()
                or line.upper() == "SH/U"
                or line.upper() == "WHO"
                or temp_callsign in line
                or "dxspider >" in line
                or line.endswith("dx>")
                or line.endswith("node>")
                or "Callsign" in line and "Type" in line
                or line.startswith("Max:")
                or line.startswith("Please enter")
                or line.startswith("with set/")
                or line.startswith("set/homenode")
            ):
                continue

            parts = line.split()
            if len(parts) < 5:
                continue

            # Rimuove IP finale se presente (Link escluso)
            if _is_ip(parts[-1]):
                parts = parts[:-1]

            if len(parts) < 5:
                continue

            call = parts[0]

            # Gestisce "USER EXT" o "NODE DXSP" oppure eventuale tipo singolo
            if len(parts) >= 6 and parts[2] in ("EXT", "DXSP", "CCCL", "INT", "LOC"):
                dx_type = f"{parts[1]} {parts[2]}"
                idx = 3
            else:
                dx_type = parts[1]
                idx = 2

            if idx + 2 >= len(parts):
                continue

            state = parts[idx]
            idx += 1

            # Started è tipicamente "19-Nov-2026 0933Z"
            if idx + 1 < len(parts) and parts[idx + 1].endswith("Z"):
                started = f"{parts[idx]} {parts[idx + 1]}"
                idx += 2
            else:
                started = parts[idx]
                idx += 1

            tail = parts[idx:]
            rtt = "-"
            ave = "-"

            if len(tail) >= 2 and _is_num_or_dash(tail[-1]) and _is_num_or_dash(tail[-2]):
                rtt = tail.pop()
                ave = tail.pop()
            elif len(tail) >= 1 and _is_num_or_dash(tail[-1]) and "." in tail[-1]:
                rtt = tail.pop()

            name = " ".join(tail).strip() if tail else "-"

            users.append({
                "call": call,
                "type": dx_type,
                "state": state,
                "started": started,
                "name": name,
                "ave": ave,
                "rtt": rtt
            })

    except Exception as e:
        print(f"[API ERROR USERS] {e}")

    return users

class APIHandler(BaseHTTPRequestHandler):
    
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/search':
            params = parse_qs(parsed_url.query)
            
            dx = params.get('dx', [''])[0].strip()
            comment = params.get('comment', [''])[0].strip()
            band = params.get('band', [''])[0].strip()
            mode = params.get('mode', [''])[0].strip()
            limit = min(int(params.get('limit', [100])[0]), 500)

            results = self.query_db(dx, comment, band, mode, limit)
            
            self._set_headers()
            self.wfile.write(json.dumps(results, default=str).encode('utf-8'))
            
        elif parsed_url.path == '/api/users':
            host = config["connector"]["host"]
            port = int(config["connector"]["port"])
            users_data = fetch_cluster_users_ephemeral(host, port, "GU3ST")
            
            self._set_headers()
            self.wfile.write(json.dumps(users_data, default=str).encode('utf-8'))
            
        else:
            self.send_error(404, "Endpoint non trovato")

    def query_db(self, dx, comment, band, mode, limit):
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor(dictionary=True)
            
            sql = "SELECT spotter, frequency, dx_call, comment, DATE_FORMAT(spot_time, '%Y-%m-%d %H:%i') as spot_time, band, mode FROM spots WHERE 1=1"
            args = []

            if dx:
                sql += " AND dx_call LIKE %s"
                args.append(f"%{dx}%")
            if comment:
                sql += " AND comment LIKE %s"
                args.append(f"%{comment}%")
            if band:
                sql += " AND band = %s"
                args.append(band)
            if mode:
                sql += " AND mode = %s"
                args.append(mode)

            sql += " ORDER BY id DESC LIMIT %s"
            args.append(limit)

            cursor.execute(sql, args)
            rows = cursor.fetchall()
            
            cursor.close()
            conn.close()
            return rows
        except Exception as e:
            print(f"[API ERROR] {e}")
            return []

def run(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, APIHandler)
    print(f"[API SERVER] In ascolto sulla porta {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run()

