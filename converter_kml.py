import xml.etree.ElementTree as ET
import json
import re
import os

BASE = os.path.dirname(os.path.abspath(__file__))

KML_FILES = [
    "MG (9).kml",
    "ES.kml",
    "RJ (1).kml",
    "SP.kml",
]

OUTPUT = os.path.join(BASE, "cobertura_mg.json")

NS = "{http://www.opengis.net/kml/2.2}"


def field(desc, label):
    m = re.search(r"<strong>" + re.escape(label) + r"</strong>\s*([^<\r\n]+)", desc)
    return m.group(1).strip() if m else ""


all_features = []

for fname in KML_FILES:
    path = os.path.join(BASE, fname)
    if not os.path.exists(path):
        print(f"AVISO: {fname} nao encontrado, pulando.")
        continue

    print(f"Processando {fname}...")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    # Corrige arquivos truncados que não têm fechamento de Document/kml
    if "</kml>" not in content:
        if "</Document>" not in content:
            content += "\n</Document>"
        content += "\n</kml>"
    root = ET.fromstring(content)
    count = 0

    for pm in root.iter(NS + "Placemark"):
        name_el = pm.find(NS + "name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""

        desc_el = pm.find(NS + "description")
        desc = desc_el.text if desc_el is not None and desc_el.text else ""

        poly = pm.find(f".//{NS}coordinates")
        if poly is None or not poly.text:
            continue

        coords = []
        for pt in poly.text.strip().split():
            parts = pt.split(",")
            if len(parts) >= 2:
                try:
                    coords.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
                except ValueError:
                    continue

        if len(coords) < 3:
            continue

        kml_color = ""
        style = pm.find(NS + "Style")
        if style is not None:
            ps = style.find(NS + "PolyStyle")
            if ps is not None:
                ce = ps.find(NS + "color")
                if ce is not None:
                    kml_color = ce.text.strip()

        all_features.append({
            "n": name,
            "s": field(desc, "Status Venda Célula: "),
            "m": field(desc, "Município: "),
            "e": field(desc, "Estação: "),
            "hc": field(desc, "HC: "),
            "hp": field(desc, "HP: "),
            "o": field(desc, "Ocup (%): "),
            "cl": field(desc, "Cluster Célula: "),
            "at": field(desc, "Atingimento/Meta (%): "),
            "kc": kml_color,
            "coords": coords,
        })
        count += 1

    print(f"  {count} regioes extraidas de {fname}")

print(f"\nTotal: {len(all_features)} regioes")

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(all_features, f, ensure_ascii=False, separators=(",", ":"))

print(f"Arquivo salvo: {OUTPUT}")
