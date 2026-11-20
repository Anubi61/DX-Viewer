# DX Viewer - Client Web per DX Cluster

DX Viewer è una piattaforma integrata per ambiente Linux progettata per il monitoraggio, l'archiviazione e la visualizzazione in tempo reale dello stream di spot provenienti da un nodo DX Spider (DX Cluster). Il sistema combina un'architettura backend in Python basata su demoni di servizio, un database relazionale MariaDB per lo storico degli spot, un server Web Nginx configurato come reverse proxy e un'interfaccia frontend Single Page Application (SPA) reattiva sviluppata in HTML5, Bootstrap 5 e JavaScript.

---

## Architettura di Sistema

L'architettura complessiva di DX Viewer si articola in quattro componenti principali fortemente integrati:

1. **Collector Daemon (`collector.py`)**: demone di servizio in ascolto continuo sul cluster Telnet remoto. Si occupa della pulizia dei dati ASCII, del parsing degli spot, della classificazione automatica di bande e modi di trasmissione e del salvataggio persistente su database e file JSON.
2. **API Backend Server (`api_server.py`)**: microservizio HTTP che espone endpoint JSON per la ricerca avanzata nello storico MariaDB e per l'interrogazione live delle stazioni connesse al cluster tramite connessioni Telnet estemporanee.
3. **Propagation Fetcher (`soltick.py`)**: script eseguito periodicamente per il recupero dei dati XML sulla propagazione solare e per la generazione del ticker di testo per l'interfaccia.
4. **Web Frontend (`index.html`)**: interfaccia utente responsive organizzata a tab che consente la consultazione dello stream live, la ricerca nello storico con filtri combinati e l'ispezione dello stato della rete.

---

## Componenti Backend e Script di Servizio

### 1. Collector Daemon (`collector.py`)
Il modulo `collector.py` gestisce la connessione socket Telnet verso il cluster DX Spider configurato in `config.json` (`ik4icz.dyndns.org:8000` con identificativo `IK4ICZ-98`).

* **Parsing e Normalizzazione del Testo**: la funzione `clean_text` rimuove i caratteri ASCII non stampabili o di controllo. La funzione `parse_line` applica una regolare espressione per estrarre il nominativo dello spotter, la frequenza espressa in kHz, il nominativo della stazione DX avvistata, le note o commenti e l'orario UTC (`HHMMZ`).
* **Classificazione della Banda (`get_band`)**: confronta la frequenza numerica dello spot con i limiti espressi in kHz definiti nel file `bands.json` (dalla banda dei 160 metri fino ai 3 centimetri).
* **Determinazione del Modo di Trasmissione (`get_mode`)**: analizza prioritariamente il commento dello spotter cercando parole chiave esplicite (FT8, FT4, FT2, CW, SSB, LSB, USB, PHONE, RTTY, PSK, SSTV, JS8CALL). In assenza di corrispondenze nel commento, effettua il confronto basandosi sulle frequenze puntuali (con tolleranza in kHz) o sui range definiti nel file `modes.json`.
* **Buffer Circolare e Database**: gli ultimi 50 spot ricevuti vengono scritti nel file circolare `/var/www/spots.json` per garantire una lettura immediata e a bassa latenza da parte dell'interfaccia Web. Parallelamente, ciascuno spot viene registrato nella tabella `spots` del database MariaDB.
* **Resilienza e Fault Tolerance**: il demone gestisce la riconnessione automatica al database (`db.reconnect`) in caso di caduta del link e implementa un algoritmo di backoff esponenziale per i tentativi di riconnessione alla socket Telnet (da 5 secondi fino a un massimo di 300 secondi).

### 2. API Server (`api_server.py`)
Sviluppato con la libreria nativa `http.server`, il server API risponde sulla porta TCP 8080 integrando l'abilitazione delle intestazioni CORS (`Access-Control-Allow-Origin: *`).

* **Endpoint `/api/search`**: gestisce le interrogazioni al database MariaDB accettando parametri di ricerca (`dx`, `comment`, `band`, `mode`, `limit`). Esegue query parametriche SQL ordinando i risultati per ID decrescente (fino a un massimo di 500 record per richiesta).
* **Endpoint `/api/users`**: apre una connessione Telnet temporanea verso il cluster DX Spider utilizzando il nominativo di servizio `GU3ST`. Invia il comando `who`, gestisce i prompt di sistema tramite `_read_until_prompt` ed estrae la lista degli utenti connessi compilando i campi relativi a nominativo, tipo di nodo, stato, data/ora di avvio, nome operatore, media (`ave`) e tempo di round-trip (`rtt`). La sessione viene chiusa inviando il comando `BYE`.

### 3. Solar Ticker (`soltick.py`)
Lo script `soltick.py` invia una richiesta HTTP GET all'indirizzo `https://www.mapforham.com/hf-propagation/data/solar.xml` impostando un User-Agent standard. Effettua il parsing della struttura XML recuperando i valori dei nodi `updated`, `solarflux`, `sunspots` e `solarwind`, e li scrive nel file di testo `/var/www/ticker.txt`. In caso di errore durante la connessione o l'elaborazione, registra l'eccezione con la dicitura `ERR:`.

---

## File di Configurazione e Struttura Dati

### File di Configurazione Principale (`config.json`)
E' posto nella directory di lavoro /opt/dxviewer,
assieme a bands.json e modes.json
Contiene i parametri di rete, le credenziali di accesso al database e i metadati dell'applicazione:

```json
{
  "connector": {
    "host": "indirizzo_del_dxspider",
    "port": "porta",
    "call": "Call_del_client"
  },
  "db": {
    "host": "localhost",
    "user": "dxviewer",
    "password": "123",
    "database": "dxviewer"
  },
  "www": {
    "path": "/var/www"   
  },
  "app": {
    "call": "Tuo Call",
    "title": "DX Viewer",
    "version": "1.4"
  }
}
```

### Struttura del Database MariaDB
Il sistema utilizza il database `dxviewer` e la tabella `spots` per la memorizzazione dello storico:

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `id` | INT AUTO_INCREMENT | Identificativo univoco progressivo dello spot |
| `spotter` | VARCHAR | Nominativo della stazione che ha inviato lo spot |
| `frequency` | VARCHAR / FLOAT | Frequenza della trasmissione espressa in kHz |
| `dx_call` | VARCHAR | Nominativo della stazione DX avvistata |
| `comment` | TEXT | Note o commenti forniti dallo spotter |
| `spot_time` | DATETIME | Data e ora di registrazione dello spot |
| `band` | VARCHAR | Banda radio assegnata (es. 20m, 40m, 2m) |
| `mode` | VARCHAR | Modo di trasmissione identificato (es. CW, SSB, FT8) |

### Mappatura Bande (`bands.json`)
Fornisce la definizione dei limiti di frequenza in kilohertz (kHz) per l'assegnazione automatica delle bande:
* **Bande HF / MF**: 160m (1810-2000 kHz), 80m (3500-3800 kHz), 60m (5351.5-5366.5 kHz), 40m (7000-7300 kHz), 30m (10100-10150 kHz), 20m (14000-14350 kHz), 17m (18068-18168 kHz), 15m (21000-21450 kHz), 12m (24890-24990 kHz), 10m (28000-29700 kHz).
* **Bande VHF / UHF / SHF**: 6m, 4m, 2m, 70cm, 23cm, 13cm, 3cm.

---

## Interfaccia Web Frontend (`index.html`)

L'interfaccia utente è realizzata in Bootstrap 5 con tema scuro ed è strutturata in tre schede funzionali:

1. **Header e Ticker Solare**: mostra il titolo dell'applicazione, il badge di stato (`LIVE` / `OFFLINE`) e un ticker animato CSS (`@keyframes ticker-scroll`) che aggiorna i dati dal file `ticker.txt` tramite chiamate AJAX ogni 60 secondi. Il passaggio del cursore su del ticker ne sospende l'animazione.
2. **Tab Real-time Stream**: esegue il polling del file `/spots.json` ogni 3 secondi presentando gli ultimi 50 spot ricevuti. Consente di applicare filtri istantanei su bande e modi di trasmissione (inclusa la selezione cumulativa `DIGI` per i modi digitali FT8, FT4, FT2, RTTY, PSK, SSTV, MSK144, EME).
3. **Tab Ricerca Storica & Filtri**: interroga l'API backend (`/api/search`) permettendo di combinare filtri su DX Call, Commenti, Banda e Modo. Include pulsanti di scelta rapida per le bande più attive (40m, 20m, 15m, 10m, 6m) e per i modi principali (FT8, CW, SSB, EME).
4. **Tab Stazioni Collegate**: invia una richiesta all'endpoint `/api/users` all'atto dell'apertura del tab, mostrando l'elenco degli utenti e dei nodi attualmente connessi al cluster DXSpider con relative metriche RTT ed Ave.

---

## Configurazione e Distribuibilità in Ambiente Linux

### Prerequisiti
* Sistema Operativo Linux (Debian, Ubuntu, RHEL o derivate).
* Python 3 con libreria `mysql-connector-python`.
* Database Server MariaDB / MySQL.
* Web Server Nginx.

### 1. Configurazione Reverse Proxy Nginx
Inserire il seguente blocco all'interno del file di configurazione del sito in Nginx per reindirizzare le chiamate verso l'API Python:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080;
    
    # Header HTTP trasmessi al backend
    proxy_set_header Host 127.0.0.1;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;

    # Timeouts consigliati
    proxy_connect_timeout 60s;
    proxy_read_timeout 60s;
}
```

### 2. Configurazione dei Servizi Systemd

#### Servizio Collector (`/etc/systemd/system/dx-collector.service`)
```ini
[Unit]
Description=DX Viewer Telnet Collector Service
After=network.target mariadb.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dxviewer
ExecStart=/usr/bin/python3 /opt/dxviewer/collector.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Servizio API Server (`/etc/systemd/system/dx-api.service`)
```ini
[Unit]
Description=DX Viewer API Server Service
After=network.target mariadb.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dxviewer
ExecStart=/usr/bin/python3 /opt/dxviewer/api_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Attivazione dei Servizi
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dx-collector.service
sudo systemctl enable --now dx-api.service
```

### 3. Pianificazione del Ticker Solare via Cron
Rendere eseguibile il file /opt/dxviewer/soltick.py
Aggiungere la seguente riga nel crontab di sistema per aggiornare gli indici ogni 15 minuti:

```bash
*/15 * * * * /usr/bin/python3 /opt/dxviewer/soltick.py >/dev/null 2>&1
```

---

## Licenza

Il software **DX Viewer** è distribuito sotto licenza **GNU General Public License v3.0 (GNU GPLv3)**. Copyright © 2026 IU4QTF. È garantita la libertà di utilizzare, modificare e ridistribuire il software a condizione che il codice sorgente rimanga aperto.
