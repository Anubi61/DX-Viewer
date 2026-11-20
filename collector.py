import socket
import re
import json
import time
import mysql.connector
import os


with open("config.json", "r") as f:
    config = json.load(f)



HOST = config["connector"]["host"] 
PORT = int(config["connector"]["port"]) 
CALLSIGN = config["connector"]["call"]
DB_CONFIG = config["db"]
WWW_DATA = config["www"]["path"]


spots = []
# Caricamento dinamico delle bande da bands.json all'avvio
BANDS_CONFIG = []
BANDS_FILE = os.path.join(os.path.dirname(__file__), "bands.json")

try:
    with open(BANDS_FILE, "r", encoding="utf-8") as f:
        BANDS_CONFIG = json.load(f)
except Exception as e:
    print(f"Errore durante il caricamento di bands.json: {e}")

def get_band(freq_str):
    try:
        f = float(freq_str)
        for item in BANDS_CONFIG:
            if item["min_khz"] <= f <= item["max_khz"]:
                return item["band"]
    except (ValueError, TypeError):
        pass
    return "Other"
# Caricamento della mappa frequenze/modi da file esterno
try:
    with open("modes.json", "r") as f:
        MODES_DATA = json.load(f)["modes"]
except Exception as e:
    print(f"[WARN] Impossibile caricare modes.json: {e}")
    MODES_DATA = []


def get_mode(freq_str, comment):
    comment_upper = comment.upper()
    
    # 1. Parsing esplicito dal Commento (override)
    if "FT8" in comment_upper: return "FT8"
    if "FT4" in comment_upper: return "FT4"
    if "FT2" in comment_upper: return "FT2"
    if "CW" in comment_upper: return "CW"
    if any(m in comment_upper for m in ["SSB", "USB", "LSB", "PHONE"]): return "SSB"
    if "RTTY" in comment_upper: return "RTTY"
    if "PSK" in comment_upper: return "PSK"
    if "SSTV" in comment_upper: return "SSTV"
    if "JS8" in comment_upper: return "JS8CALL"

    # 2. Fallback su intervalli e punti definiti in modes.json
    try:
        f = float(freq_str)
        
        # Scandiamo tutte le definizioni in modes.json
        for mode_entry in MODES_DATA:
            mode_id = mode_entry.get("id")
            
            # Check sui singoli spot puntuali (es. FT8, WSPR con tolleranza)
            if "spots" in mode_entry:
                for spot in mode_entry["spots"]:
                    tol = spot.get("tol", 1.0)
                    if abs(f - spot["freq"]) <= tol:
                        return mode_id

            # Check sui range di frequenza (es. CW, SSB, DIGI)
            if "ranges" in mode_entry:
                for r in mode_entry["ranges"]:
                    if r["min"] <= f <= r["max"]:
                        return mode_id
                        
    except ValueError:
        pass

    return "OTHER"

def clean_text(text):
    return re.sub(r'[\x00-\x09\x0b-\x1f\x7f-\xff]', '', text)

def parse_line(line):
    line = clean_text(line).strip()
    pattern = r"^DX\s+de\s+([A-Za-z0-9\/]+):\s+([\d\.]+)\s+([A-Za-z0-9\/]+)\s*(.*?)\s+(\d{4}Z)"
    m = re.search(pattern, line, re.IGNORECASE)
    if m:
        freq = m.group(2)
        comment = m.group(4).strip()
        return {
            "spotter": m.group(1),
            "freq": freq,
            "dx": m.group(3),
            "comment": comment,
            "time": m.group(5),
            "band": get_band(freq),
            "mode": get_mode(freq, comment)  # <-- MODIFICA QUI: passa sia freq che comment
        }
    return None

def save_to_db(db_conn, spot):
    try:
        cursor = db_conn.cursor()
        query = """
            INSERT INTO spots (spotter, frequency, dx_call, comment, spot_time, band, mode)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s)
        """
        cursor.execute(query, (spot['spotter'], spot['freq'], spot['dx'], spot['comment'], spot['band'], spot['mode']))
        db_conn.commit()
        cursor.close()
    except Exception as e:
        print(f"[DB ERROR] Errore di scrittura su MariaDB: {e}")

def main():
    global spots
    
    # Connessione al DB
    try:
        db = mysql.connector.connect(**DB_CONFIG)
        print("[DB] Connesso a MariaDB.")
    except Exception as e:
        print(f"[DB] Impossibile connettersi a MariaDB: {e}")
        return

    retry_delay = 5
    max_retry_delay = 300  # Tetto massimo di 5 minuti di attesa

    while True:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(20)
            print(f"[TELNET] Tentativo di connessione a {HOST}:{PORT}...")
            s.connect((HOST, PORT))
            print(f"[TELNET] Connesso. Invio callsign...")

            s.sendall(f"{CALLSIGN}\r\n".encode('ascii'))
            buffer = ""
            
            # Connessione riuscita, azzeriamo il contatore del backoff
            retry_delay = 5

            while True:
                try:
                    data = s.recv(4096).decode('ascii', errors='ignore')
                    if not data:
                        print("[TELNET] Connessione chiusa dal server remoto.")
                        break
                    buffer += data

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        clean_l = clean_text(line)

                        if "DX de" in clean_l:
                            spot = parse_line(clean_l)
                            if spot:
                                spots.insert(0, spot)
                                spots = spots[:50]
                                with open(f"{WWW_DATA}/spots.json", "w") as f:
                                    json.dump(spots, f, indent=2)

                                # Verifica e riconnessione sicura al DB se cade
                                try:
                                    if not db.is_connected():
                                        db.reconnect(attempts=3, delay=2)
                                    save_to_db(db, spot)
                                except Exception as dbe:
                                    print(f"[DB ERROR] Impossibile scrivere su DB: {dbe}")

                                print(f"[SPOT] {spot['dx']} [{spot['band']}/{spot['mode']}] su {spot['freq']} kHz")

                except socket.timeout:
                    # Heartbeat keep-alive
                    try:
                        s.sendall(b"\r\n")
                    except Exception:
                        break

        except Exception as e:
            print(f"[SOCKET ERROR] {e}")
            
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

        # Backoff esponenziale con tetto massimo per non sovraccaricare il sistema
        print(f"[TELNET] Riconnessione tra {retry_delay} secondi...")
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, max_retry_delay)

        # Controllo di salute del DB durante le disconnessioni di rete
        try:
            if not db.is_connected():
                db.reconnect(attempts=3, delay=2)
        except Exception:
            pass

if __name__ == "__main__":
    main()

