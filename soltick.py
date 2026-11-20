#!/usr/bin/env python3
import urllib.request
import xml.etree.ElementTree as ET

OUT_FILE = "/var/www/ticker.txt"
URL = "https://www.mapforham.com/hf-propagation/data/solar.xml"

req = urllib.request.Request(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    },
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    solardata = root.find("solardata")
    if solardata is None:
        solardata = root if root.tag == "solardata" else None

    if solardata is None:
        raise ValueError("Nodo <solardata> non trovato nella struttura XML.")

    lines = []
    for tag in ["updated", "solarflux", "sunspots", "solarwind"]:
        node = solardata.find(tag)
        val = node.text.strip() if node is not None and node.text else "N/A"
        lines.append(f"{tag.upper()}: {val}\n")
#        calc_cond = solardata.find("calculatedconditions")
#           if calc_cond is not None:
#               for band in calc_cond.findall("band"):
#                   name = band.get("name")
#                   time = band.get("time")
#                   status = band.text.strip() if band.text else "N/A"
#                   lines.append(f"'BAND {name} ({time}): {status}'\n")
    success = True



except Exception as e:
    err_msg = str(e)
    lines = [f"'ERR: {err_msg}'\n"]
    success = False

# Scrittura nel file di testo (sia in caso di successo che di errore)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.writelines(lines)

if success:
    print(f"Dati scritti con successo in {OUT_FILE}")
else:
    print(f"Errore registrato in {OUT_FILE}: {err_msg}")

