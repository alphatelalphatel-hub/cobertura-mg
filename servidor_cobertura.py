import json
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify

app = Flask(__name__)

import os as _os
JSON_FILE = _os.path.join(_os.path.dirname(__file__), 'cobertura_mg.json')

print("Carregando dados de cobertura...")
with open(JSON_FILE, encoding='utf-8') as f:
    raw = json.load(f)

# Pré-computa bounding boxes para busca rápida
cobertura = []
for f in raw:
    lngs = [p[0] for p in f['coords']]
    lats = [p[1] for p in f['coords']]
    cobertura.append({
        **f,
        'bb': (min(lngs), min(lats), max(lngs), max(lats))
    })

print(f"{len(cobertura)} regiões carregadas. Servidor pronto.")


def point_in_polygon(lng, lat, coords):
    inside = False
    j = len(coords) - 1
    for i in range(len(coords)):
        xi, yi = coords[i]
        xj, yj = coords[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def find_coverage(lng, lat):
    candidates = [
        f for f in cobertura
        if f['bb'][0] <= lng <= f['bb'][2] and f['bb'][1] <= lat <= f['bb'][3]
    ]
    for f in candidates:
        if point_in_polygon(lng, lat, f['coords']):
            return f
    return None


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'cobertura-checker/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


OPENCAGE_KEY = "dbf3f5f383ee4f0a8485d8810f047804"


def get_coordinates(cep_raw):
    # 1. ViaCEP → endereço completo
    via = fetch_json(f"https://viacep.com.br/ws/{cep_raw}/json/")
    if via.get('erro'):
        return None, None, None

    endereco = f"{via.get('logradouro','')} {via.get('bairro','')} {via.get('localidade')} {via.get('uf')} Brasil"

    # 2. OpenCage → lat/lng
    q = urllib.parse.quote(endereco.strip())
    url = f"https://api.opencagedata.com/geocode/v1/json?q={q}&key={OPENCAGE_KEY}&language=pt-BR&countrycode=br&limit=1&no_annotations=1"
    try:
        geo = fetch_json(url)
    except Exception as e:
        raise RuntimeError(f"OpenCage falhou: {e} | URL: {url}")

    results = geo.get('results', [])
    if not results:
        raise RuntimeError(f"OpenCage sem resultados. Status: {geo.get('status')} | Endereco: {endereco}")

    loc = results[0]['geometry']
    return loc['lat'], loc['lng'], via


@app.route('/cobertura', methods=['GET', 'POST'])
def verificar():
    # Aceita GET ?cep=XXXXXXXX ou POST {"cep": "XXXXXXXX"}
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cep_raw = data.get('cep', '')
    else:
        cep_raw = request.args.get('cep', '')

    cep_raw = ''.join(c for c in cep_raw if c.isdigit())

    if len(cep_raw) != 8:
        return jsonify({"erro": "CEP inválido. Informe 8 dígitos."}), 400

    try:
        lat, lng, via = get_coordinates(cep_raw)
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar CEP/geocoding: {str(e)}"}), 502

    if via is None or via.get('erro'):
        return jsonify({"erro": "CEP não encontrado."}), 404

    if lat is None:
        return jsonify({
            "cep": via.get('cep'),
            "municipio": via.get('localidade'),
            "uf": via.get('uf'),
            "cobertura": False,
            "motivo": "Não foi possível localizar as coordenadas do endereço."
        }), 200

    feature = find_coverage(lng, lat)

    if not feature:
        return jsonify({
            "pode_vender": False,
            "resposta": "NAO PODE VENDER - Endereço fora da área de cobertura.",
            "cep": via.get('cep'),
            "municipio": via.get('localidade'),
            "uf": via.get('uf'),
        })

    status = feature.get('s', '')
    municipio = feature.get('m') or via.get('localidade')
    estacao = feature.get('e', '')

    if 'sem restri' in status.lower():
        pode_vender = True
        resposta = f"PODE VENDER - {municipio}, Estação {estacao}"
    else:
        pode_vender = False
        resposta = f"NAO PODE VENDER - Área com restrição de vendas. {municipio}, Estação {estacao}"

    return jsonify({
        "pode_vender": pode_vender,
        "resposta": resposta,
        "status_venda": status,
        "municipio": municipio,
        "estacao": estacao,
        "cep": via.get('cep'),
        "ocupacao": feature.get('o'),
        "hc": feature.get('hc'),
        "hp": feature.get('hp'),
    })


@app.route('/', methods=['GET'])
def index():
    return """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>API Cobertura MG</title>
<style>body{font-family:sans-serif;max-width:500px;margin:60px auto;padding:20px}
input{width:100%;padding:10px;font-size:16px;margin:8px 0;border:1px solid #ccc;border-radius:6px}
button{width:100%;padding:12px;background:#2b6cb0;color:white;border:none;border-radius:6px;font-size:15px;cursor:pointer}
pre{background:#f4f4f4;padding:16px;border-radius:6px;overflow:auto;margin-top:16px}</style></head>
<body><h2>API de Cobertura MG</h2>
<input id="cep" placeholder="Digite o CEP (ex: 34006030)" maxlength="9">
<button onclick="verificar()">Verificar</button>
<pre id="res"></pre>
<script>
document.getElementById('cep').addEventListener('keydown',e=>{if(e.key==='Enter')verificar()});
async function verificar(){
  const cep=document.getElementById('cep').value.replace(/\\D/g,'');
  document.getElementById('res').textContent='Consultando...';
  const r=await fetch('/cobertura?cep='+cep);
  const d=await r.json();
  document.getElementById('res').textContent=JSON.stringify(d,null,2);
}
</script></body></html>"""


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "regioes_carregadas": len(cobertura)})


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
