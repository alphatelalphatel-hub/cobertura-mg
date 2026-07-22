import json
import os
import sqlite3
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

JSON_FILE = os.path.join(os.path.dirname(__file__), 'cobertura_mg.json')
CLARO_DB = os.path.join(os.path.dirname(__file__), 'claro.db')
CLARO_MUN_FILE = os.path.join(os.path.dirname(__file__), 'claro_municipios.json')

print("Carregando dados de cobertura...")
with open(JSON_FILE, encoding='utf-8') as f:
    raw = json.load(f)

cobertura = []
for feat in raw:
    lngs = [p[0] for p in feat['coords']]
    lats = [p[1] for p in feat['coords']]
    cobertura.append({**feat, 'bb': (min(lngs), min(lats), max(lngs), max(lats))})

# Mapeamento cor KML (AABBGGRR) → cor web + significado
KML_COR = {
    '99000000': {'hex': '#4A5568', 'label': 'Bloqueado',        'pode': False, 'desc': 'Não pode vender'},
    '990000FF': {'hex': '#E53E3E', 'label': 'Performance baixa','pode': True,  'desc': 'Pode vender — atingimento abaixo de 30%'},
    '9900FFFF': {'hex': '#D69E2E', 'label': 'Performance média','pode': True,  'desc': 'Pode vender — atingimento entre 30% e 55%'},
    '99008000': {'hex': '#38A169', 'label': 'Performance boa',  'pode': True,  'desc': 'Pode vender — atingimento entre 55% e 100%'},
    '99FF0000': {'hex': '#3182CE', 'label': 'Meta batida',      'pode': True,  'desc': 'Pode vender — meta superada (acima de 100%)'},
}
COR_PADRAO = {'hex': '#718096', 'label': 'Sem info', 'pode': False, 'desc': ''}

def cor_da_feature(feat):
    return KML_COR.get(feat.get('kc', ''), COR_PADRAO)

# Pré-processa dados para o mapa (inverte lng/lat para lat/lng do Leaflet)
print("Preparando dados do mapa...")
mapa_features = []
for feat in cobertura:
    cor = cor_da_feature(feat)
    mapa_features.append({
        'n': feat.get('n', ''), 's': feat.get('s', ''), 'm': feat.get('m', ''),
        'e': feat.get('e', ''), 'o': feat.get('o', ''),
        'hc': feat.get('hc', ''), 'hp': feat.get('hp', ''),
        'at': feat.get('at', ''),
        'cl': feat.get('cl', ''),
        'lbl': cor['label'],
        'c': cor['hex'],
        'coords': [[p[1], p[0]] for p in feat['coords']]
    })

MAPA_JSON = json.dumps(mapa_features, ensure_ascii=False, separators=(',', ':'))
TOTAL = len(cobertura)
print(f"{TOTAL} regioes carregadas. Servidor pronto.")

OPENCAGE_KEY = "dbf3f5f383ee4f0a8485d8810f047804"


def point_in_polygon(lng, lat, coords):
    inside = False
    j = len(coords) - 1
    for i in range(len(coords)):
        xi, yi = coords[i]; xj, yj = coords[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def find_coverage(lng, lat):
    for feat in cobertura:
        if feat['bb'][0] <= lng <= feat['bb'][2] and feat['bb'][1] <= lat <= feat['bb'][3]:
            if point_in_polygon(lng, lat, feat['coords']):
                return feat
    return None


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'cobertura-checker/1.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def get_coordinates(cep_raw):
    via = fetch_json(f"https://viacep.com.br/ws/{cep_raw}/json/")
    if via.get('erro'):
        return None, None, None
    endereco = f"{via.get('logradouro','')} {via.get('bairro','')} {via.get('localidade')} {via.get('uf')} Brasil"
    q = urllib.parse.quote(endereco.strip())
    geo = fetch_json(f"https://api.opencagedata.com/geocode/v1/json?q={q}&key={OPENCAGE_KEY}&language=pt-BR&countrycode=br&limit=1&no_annotations=1")
    results = geo.get('results', [])
    if not results:
        raise RuntimeError(f"Geocoding sem resultado para: {endereco}")
    loc = results[0]['geometry']
    return loc['lat'], loc['lng'], via


def geocode_endereco_numero(logradouro, numero, bairro, municipio, uf):
    partes = [logradouro]
    if numero and numero.upper() not in ('SN', 'S/N', ''):
        partes.append(numero)
    partes += [bairro, f"{municipio} - {uf}", "Brasil"]
    endereco = ", ".join(p for p in partes if p)
    q = urllib.parse.quote(endereco)
    geo = fetch_json(f"https://api.opencagedata.com/geocode/v1/json?q={q}&key={OPENCAGE_KEY}&language=pt-BR&countrycode=br&limit=1&no_annotations=1")
    results = geo.get('results', [])
    if not results:
        return None, None
    loc = results[0]['geometry']
    return loc['lat'], loc['lng']


@app.route('/mapa-data')
def mapa_data():
    return Response(MAPA_JSON, mimetype='application/json')


@app.route('/cobertura', methods=['GET', 'POST'])
def verificar():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cep_raw = data.get('cep', '')
    else:
        cep_raw = request.args.get('cep', '')

    cep_raw = ''.join(c for c in cep_raw if c.isdigit())
    if len(cep_raw) != 8:
        return jsonify({"erro": "CEP invalido."}), 400

    try:
        lat, lng, via = get_coordinates(cep_raw)
    except Exception:
        return jsonify({
            "pode_vender": False,
            "cobertura": False,
            "cep": cep_raw,
            "resposta": "NAO - Nao foi possivel verificar a cobertura para este CEP no momento.",
            "coordenadas": None
        })

    if via is None or via.get('erro'):
        return jsonify({
            "pode_vender": False,
            "cobertura": False,
            "cep": cep_raw,
            "resposta": "NAO - CEP nao encontrado na base dos Correios.",
            "coordenadas": None
        })

    coords = {"lat": lat, "lng": lng} if lat else None

    if lat is None:
        return jsonify({"cep": via.get('cep'), "municipio": via.get('localidade'),
                        "uf": via.get('uf'), "cobertura": False,
                        "motivo": "Nao foi possivel localizar as coordenadas."})

    logradouro = via.get('logradouro', '')
    bairro     = via.get('bairro', '')
    cidade     = via.get('localidade', '')
    uf         = via.get('uf', '')
    endereco_completo = f"{logradouro}, {bairro}, {cidade} - {uf}".strip(', ')

    feature = find_coverage(lng, lat)

    if not feature:
        return jsonify({
            "pode_vender": False,
            "cobertura": False,
            "endereco": endereco_completo,
            "cep": via.get('cep'),
            "resposta": f"NAO - A rua {logradouro}, {bairro}, {cidade} ainda nao tem cobertura de fibra.",
            "coordenadas": coords
        })

    status = feature.get('s', '')
    municipio = feature.get('m') or cidade
    estacao = feature.get('e', '')
    pode_vender = 'sem restri' in status.lower()
    cor = cor_da_feature(feature)

    if pode_vender:
        resposta = f"SIM - A rua {logradouro}, {bairro}, {cidade} tem cobertura disponivel. Pode instalar."
    else:
        resposta = f"NAO - A rua {logradouro}, {bairro}, {cidade} esta com restricao de vendas."

    return jsonify({
        "pode_vender": pode_vender,
        "cobertura": True,
        "endereco": endereco_completo,
        "cep": via.get('cep'),
        "resposta": resposta,
        "coordenadas": coords,
        "performance": cor['label'],
        "performance_desc": cor['desc'],
        "cor_hex": cor['hex'],
        "atingimento": feature.get('at', ''),
        "cluster": feature.get('cl', ''),
        "municipio": municipio,
        "estacao": estacao,
        "hc": feature.get('hc', ''),
        "hp": feature.get('hp', ''),
        "ocupacao": feature.get('o', ''),
    })


def claro_query(cep):
    if not os.path.exists(CLARO_DB):
        return None
    conn = sqlite3.connect(CLARO_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM claro WHERE cep = ? ORDER BY logradouro, num_fachada", (cep,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.route('/api/claro-pontos')
def api_claro_pontos():
    try:
        n = float(request.args.get('n'))
        s = float(request.args.get('s'))
        e = float(request.args.get('e'))
        w = float(request.args.get('w'))
    except (TypeError, ValueError):
        return jsonify({"erro": "Parametros de bounds invalidos."}), 400

    if not os.path.exists(CLARO_DB):
        return jsonify([])

    conn = sqlite3.connect(CLARO_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT cc.cep, cc.lat, cc.lng,
                   COUNT(c.cep) total,
                   SUM(CASE WHEN c.qtd_hc IS NOT NULL AND c.qtd_hc != '' AND c.qtd_hc != '0' THEN 1 ELSE 0 END) instalados
            FROM cep_coords cc
            JOIN claro c ON c.cep = cc.cep
            WHERE cc.status = 'ok' AND cc.lat BETWEEN ? AND ? AND cc.lng BETWEEN ? AND ?
            GROUP BY cc.cep
            LIMIT 500
            """,
            (s, n, w, e)
        )
        pontos = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        pontos = []
    conn.close()
    return jsonify(pontos)


@app.route('/api/claro-mapa')
def api_claro_mapa():
    if not os.path.exists(CLARO_MUN_FILE):
        return jsonify([])
    with open(CLARO_MUN_FILE, encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)


@app.route('/api/claro')
def api_claro():
    cep_raw = request.args.get('cep', '')
    cep_raw = ''.join(c for c in cep_raw if c.isdigit())
    if len(cep_raw) != 8:
        return jsonify({"erro": "CEP invalido."}), 400

    rows = claro_query(cep_raw)
    if rows is None:
        return jsonify({"erro": "Base Claro ainda nao foi importada neste servidor."}), 503

    resposta = {"cep": cep_raw, "total": len(rows), "resultados": rows, "coordenadas": None}

    if rows:
        numericos = sorted(
            (r for r in rows if (r.get('num_fachada') or '').isdigit()),
            key=lambda r: int(r['num_fachada'])
        )
        alvo = numericos[len(numericos) // 2] if numericos else rows[0]
        try:
            lat, lng = geocode_endereco_numero(
                alvo.get('logradouro', ''), alvo.get('num_fachada', ''),
                alvo.get('bairro', ''), alvo.get('municipio', ''), alvo.get('uf', '')
            )
            if lat is not None:
                resposta["coordenadas"] = {"lat": lat, "lng": lng}
                resposta["endereco_referencia"] = f"{alvo.get('logradouro','')}, {alvo.get('num_fachada','')}"
        except Exception:
            pass

    return jsonify(resposta)


@app.route('/claro')
def claro_page():
    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cobertura Claro · Consulta manual</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1420;color:#e2e8f0;min-height:100vh;display:flex;justify-content:center;padding:32px 16px}
.wrap{width:100%;max-width:560px}
h1{font-size:18px;font-weight:700;margin-bottom:4px}
.sub{font-size:12px;color:#718096;margin-bottom:20px}
a.back{font-size:12px;color:#4299e1;text-decoration:none;display:inline-block;margin-bottom:16px}
label{font-size:11px;font-weight:600;color:#a0aec0;margin-bottom:6px;display:block;text-transform:uppercase;letter-spacing:.5px}
input{width:100%;padding:12px 14px;border:2px solid #2d3748;border-radius:8px;background:#1a202c;color:#fff;font-size:16px;letter-spacing:2px;outline:none}
input:focus{border-color:#e53e3e}
button{width:100%;margin-top:10px;padding:12px;background:#e53e3e;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer}
button:hover{background:#c53030}
button:disabled{background:#4a5568;cursor:not-allowed}
#result{margin-top:20px}
.card{background:#1a202c;border:1px solid #2d3748;border-radius:10px;padding:12px 14px;margin-bottom:10px}
.card .tit{font-size:13px;font-weight:700;color:#fff;margin-bottom:6px}
.badge{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;margin-bottom:8px}
.badge.ok{background:#1c4532;color:#68d391;border:1px solid #38a169}
.badge.no{background:#742a2a;color:#fc8181;border:1px solid #e53e3e}
.row{display:flex;justify-content:space-between;padding:2px 0;font-size:12px}
.row span:first-child{color:#a0aec0}.row span:last-child{color:#e2e8f0;font-weight:600}
.msg{font-size:13px;color:#a0aec0;padding:14px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/">&larr; Voltar para cobertura Fibra (MG/ES/RJ/SP)</a>
  <h1>Cobertura Claro</h1>
  <p class="sub">Consulta manual por CEP — base de viabilidade por endereco</p>
  <label>CEP do cliente</label>
  <input type="text" id="cep" placeholder="00000-000" maxlength="9" inputmode="numeric">
  <button id="btn" onclick="buscar()">Verificar Cobertura Claro</button>
  <div id="result"></div>
</div>
<script>
document.getElementById('cep').addEventListener('input', function(){
  let v = this.value.replace(/\\D/g,'').slice(0,8);
  if(v.length>5) v=v.slice(0,5)+'-'+v.slice(5);
  this.value=v;
});
document.getElementById('cep').addEventListener('keydown', e=>{ if(e.key==='Enter') buscar(); });

async function buscar(){
  const raw = document.getElementById('cep').value.replace(/\\D/g,'');
  if(raw.length!==8){alert('Digite um CEP valido.');return;}
  const btn=document.getElementById('btn'), res=document.getElementById('result');
  btn.disabled=true; btn.textContent='Consultando...';
  res.innerHTML='';
  try{
    const d = await fetch('/api/claro?cep='+raw).then(r=>r.json());
    if(d.erro){
      res.innerHTML='<div class="msg">'+d.erro+'</div>';
    } else if(d.total===0){
      res.innerHTML='<div class="msg">Nenhum registro Claro encontrado para este CEP.</div>';
    } else {
      res.innerHTML = d.resultados.map(r=>{
        const viavel = (r.tipo_viabilidade||'').toLowerCase().includes('viável');
        return '<div class="card">'+
          '<span class="badge '+(viavel?'ok':'no')+'">'+(r.tipo_viabilidade||'-')+'</span>'+
          '<div class="tit">'+r.logradouro+', '+r.num_fachada+'</div>'+
          row('Bairro', r.bairro)+row('Municipio', r.municipio+' - '+r.uf)+
          row('Tipo de rede', r.tipo_rede)+row('CDO', r.nome_cdo)+
          row('HP / HC', (r.qtd_hp||'-')+' / '+(r.qtd_hc||'-'))+
        '</div>';
      }).join('');
    }
  }catch(e){
    res.innerHTML='<div class="msg">Erro ao consultar.</div>';
  }finally{
    btn.disabled=false; btn.textContent='Verificar Cobertura Claro';
  }
}
function row(l,v){
  return '<div class="row"><span>'+l+'</span><span>'+(v||'-')+'</span></div>';
}
</script>
</body>
</html>"""
    return html


@app.route('/health')
def health():
    return jsonify({"status": "ok", "regioes_carregadas": TOTAL})


@app.route('/')
def index():
    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cobertura Fibra MG · ES · RJ · SP</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;height:100vh;overflow:hidden}
#panel{width:300px;min-width:300px;background:#1a202c;color:#fff;display:flex;flex-direction:column;padding:18px;z-index:1000;overflow-y:auto}
#panel h1{font-size:15px;font-weight:700;color:#e2e8f0;margin-bottom:2px}
#panel .sub{font-size:11px;color:#718096;margin-bottom:16px}
label{font-size:11px;font-weight:600;color:#a0aec0;margin-bottom:5px;display:block;text-transform:uppercase;letter-spacing:.5px}
input{width:100%;padding:10px 12px;border:2px solid #2d3748;border-radius:8px;background:#2d3748;color:#fff;font-size:16px;letter-spacing:2px;outline:none;transition:border-color .2s}
input:focus{border-color:#4299e1}
input::placeholder{color:#4a5568;letter-spacing:1px}
button{width:100%;margin-top:8px;padding:11px;background:#3182ce;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:background .2s}
button:hover{background:#2b6cb0}
button:disabled{background:#4a5568;cursor:not-allowed}
.modo-tabs{display:flex;gap:6px;margin-bottom:14px}
.modo-btn{flex:1;margin-top:0;padding:9px;background:#2d3748;color:#a0aec0;border:2px solid #2d3748;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer}
.modo-btn.active{background:#3182ce;border-color:#3182ce;color:#fff}
#modoClaro.active{background:#e53e3e;border-color:#e53e3e}
#result{margin-top:14px;border-radius:10px;padding:12px;display:none;font-size:12px;max-height:50vh;overflow-y:auto}
#result.ok{background:#1c4532;border:1px solid #38a169}
#result.no{background:#742a2a;border:1px solid #e53e3e}
#result.warn{background:#7b341e;border:1px solid #dd6b20}
#result.claro{background:#3a1a1a;border:1px solid #e53e3e}
.rtitle{font-size:13px;font-weight:700;margin-bottom:8px}
.ok .rtitle{color:#68d391}.no .rtitle{color:#fc8181}.warn .rtitle{color:#f6ad55}
.row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.07)}
.row span:first-child{color:#a0aec0}.row span:last-child{color:#e2e8f0;font-weight:600}
.legend{margin-top:auto;padding-top:14px;border-top:1px solid #2d3748}
.legend h3{font-size:10px;color:#718096;font-weight:600;margin-bottom:8px;text-transform:uppercase;letter-spacing:.8px}
.li{display:flex;align-items:center;gap:8px;font-size:11px;color:#a0aec0;margin-bottom:5px}
.lc{width:14px;height:14px;border-radius:3px;flex-shrink:0}
#map{flex:1}
.spinner{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:5px}
@keyframes spin{to{transform:rotate(360deg)}}
#overlay{position:fixed;top:0;left:300px;right:0;bottom:0;background:rgba(15,20,30,.85);display:flex;align-items:center;justify-content:center;z-index:999;color:#fff;font-size:14px;gap:10px}
@media(max-width:640px){body{flex-direction:column}#panel{width:100%;min-width:unset}#map{min-height:55vh}#overlay{left:0}}
</style>
</head>
<body>
<div id="panel">
  <h1>Cobertura Fibra MG · ES · RJ · SP</h1>
  <p class="sub" id="subtotal">Carregando regioes...</p>
  <label>Prestadora</label>
  <div class="modo-tabs">
    <button type="button" id="modoFibra" class="modo-btn active" onclick="setModo('fibra')">Fibra</button>
    <button type="button" id="modoClaro" class="modo-btn" onclick="setModo('claro')">Claro</button>
  </div>
  <label>CEP do cliente</label>
  <input type="text" id="cep" placeholder="00000-000" maxlength="9" inputmode="numeric">
  <button id="btn" onclick="buscar()">Verificar Cobertura Fibra</button>
  <div id="result"></div>
  <div class="legend" style="margin-top:20px">
    <h3>Legenda</h3>
    <div id="legendFibra">
      <div class="li"><div class="lc" style="background:#3182CE"></div><span><b style="color:#e2e8f0">Meta batida</b> — Atingimento &gt;100%</span></div>
      <div class="li"><div class="lc" style="background:#38A169"></div><span><b style="color:#e2e8f0">Performance boa</b> — 55% a 100%</span></div>
      <div class="li"><div class="lc" style="background:#D69E2E"></div><span><b style="color:#e2e8f0">Performance média</b> — 30% a 55%</span></div>
      <div class="li"><div class="lc" style="background:#E53E3E"></div><span><b style="color:#e2e8f0">Performance baixa</b> — abaixo de 30%</span></div>
      <div class="li"><div class="lc" style="background:#4A5568"></div><span><b style="color:#e2e8f0">Bloqueado</b> — Não pode vender</span></div>
    </div>
    <div id="legendClaro" style="display:none">
      <div class="li"><div class="lc" style="background:#e53e3e;border-radius:50%"></div><span><b style="color:#e2e8f0">Bolhas Claro</b> — volume de endereços por município (visão distante)</span></div>
      <div class="li"><div class="lc" style="background:#e53e3e;border-radius:50%;width:8px;height:8px"></div><span><b style="color:#e2e8f0">Pontos Claro</b> — um por CEP, aparecem ao aproximar (geocodificação em andamento)</span></div>
      <div class="li"><div class="lc" style="background:#68d391"></div><span><b style="color:#e2e8f0">Disponível</b> — rede passa no endereço, sem cliente instalado</span></div>
      <div class="li"><div class="lc" style="background:#63b3ed"></div><span><b style="color:#e2e8f0">Já instalado</b> — já existe conexão ativa nesse endereço</span></div>
    </div>
  </div>
</div>
<div id="map"></div>
<div id="overlay"><span class="spinner"></span> Carregando regioes de cobertura...</div>

<script>
const map = L.map('map', {preferCanvas: true, zoomAnimation: false, markerZoomAnimation: false}).setView([-21.0, -44.0], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap', maxZoom: 19
}).addTo(map);

let marker = null;
let claroMarker = null;
let modo = 'fibra';
const fibraLayer = L.layerGroup().addTo(map);
const claroLayer = L.layerGroup();
const claroPinIcon = L.divIcon({
  className: 'claro-pin',
  html: '<div style="width:16px;height:16px;border-radius:50% 50% 50% 0;background:#e53e3e;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.6);transform:rotate(-45deg)"></div>',
  iconSize: [16,16],
  iconAnchor: [8,16],
  popupAnchor: [0,-16]
});

const ZOOM_LIMITE_BOLHAS = 11;
const claroPontosLayer = L.layerGroup();

async function carregarPontosClaro(){
  const b = map.getBounds();
  const params = new URLSearchParams({
    n: b.getNorth(), s: b.getSouth(), e: b.getEast(), w: b.getWest()
  });
  try{
    const pontos = await fetch('/api/claro-pontos?'+params).then(r=>r.json());
    claroPontosLayer.clearLayers();
    pontos.forEach(p=>{
      const disp = p.total - p.instalados;
      L.circleMarker([p.lat, p.lng], {
        radius:6, color:'#e53e3e', weight:1, fillColor:'#e53e3e', fillOpacity:.75
      })
      .bindPopup(
        '<b>CEP '+p.cep+'</b><br>'+p.total+' endereco(s)<br>'+
        disp+' disponivel(is) · '+p.instalados+' ja instalado(s)'
      )
      .addTo(claroPontosLayer);
    });
  }catch(e){}
}

function atualizarCamadaClaro(){
  if(modo!=='claro') return;
  if(map.getZoom() > ZOOM_LIMITE_BOLHAS){
    map.removeLayer(claroLayer);
    map.addLayer(claroPontosLayer);
    carregarPontosClaro();
  } else {
    map.addLayer(claroLayer);
    claroPontosLayer.clearLayers();
    map.removeLayer(claroPontosLayer);
  }
}

function setModo(m){
  modo = m;
  document.getElementById('modoFibra').classList.toggle('active', m==='fibra');
  document.getElementById('modoClaro').classList.toggle('active', m==='claro');
  document.getElementById('btn').textContent = m==='fibra' ? 'Verificar Cobertura Fibra' : 'Verificar Cobertura Claro';
  const res=document.getElementById('result');
  res.style.display='none'; res.innerHTML='';
  if(marker){map.removeLayer(marker);marker=null;}
  if(claroMarker){map.removeLayer(claroMarker);claroMarker=null;}
  document.getElementById('legendFibra').style.display = m==='fibra' ? 'block' : 'none';
  document.getElementById('legendClaro').style.display = m==='claro' ? 'block' : 'none';
  if(m==='fibra'){
    map.addLayer(fibraLayer);
    map.removeLayer(claroLayer);
    claroPontosLayer.clearLayers();
    map.removeLayer(claroPontosLayer);
  } else {
    map.removeLayer(fibraLayer);
    atualizarCamadaClaro();
  }
}

map.on('moveend', atualizarCamadaClaro);

document.getElementById('cep').addEventListener('input', function(){
  let v = this.value.replace(/\D/g,'').slice(0,8);
  if(v.length>5) v=v.slice(0,5)+'-'+v.slice(5);
  this.value=v;
});
document.getElementById('cep').addEventListener('keydown', e=>{ if(e.key==='Enter') buscar(); });

fetch('/mapa-data')
  .then(r=>r.json())
  .then(features=>{
    document.getElementById('subtotal').textContent = features.length + ' regioes mapeadas';
    const renderer = L.canvas();
    features.forEach(f=>{
      L.polygon(f.coords, {
        renderer, color: f.c, weight:1, opacity:.9,
        fillColor: f.c, fillOpacity:.35
      })
      .bindPopup(
        '<b>'+f.n+'</b><br>'+f.m+'<br>Estacao: '+f.e+
        '<br><span style="color:'+f.c+';font-weight:700">'+f.lbl+'</span>'+
        '<br>Atingimento: '+f.at+'<br>Cluster: '+f.cl+
        '<br>HC: '+f.hc+' / HP: '+f.hp+'<br>Ocup: '+f.o,
        {maxWidth: 240}
      )
      .addTo(fibraLayer);
    });
    document.getElementById('overlay').remove();
  })
  .catch(()=>document.getElementById('overlay').remove());

fetch('/api/claro-mapa')
  .then(r=>r.json())
  .then(municipios=>{
    municipios.forEach(m=>{
      const raio = Math.max(7, Math.min(38, Math.sqrt(m.total)/4));
      const pct = m.total ? Math.round(100*m.viaveis/m.total) : 0;
      L.circleMarker([m.lat, m.lng], {
        radius: raio, color:'#e53e3e', weight:1.5,
        fillColor:'#e53e3e', fillOpacity:.35
      })
      .bindPopup(
        '<b>Claro — '+m.municipio+' / '+m.uf+'</b><br>'+
        m.total+' endereco(s) mapeado(s)<br>'+
        m.viaveis+' viaveis ('+pct+'%)',
        {maxWidth:220}
      )
      .addTo(claroLayer);
    });
  })
  .catch(()=>{});

async function buscar(){
  if(modo==='fibra') return buscarFibra();
  return buscarClaro();
}

async function buscarFibra(){
  const raw = document.getElementById('cep').value.replace(/\D/g,'');
  if(raw.length!==8){alert('Digite um CEP valido.');return;}
  const btn=document.getElementById('btn'), res=document.getElementById('result');
  btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Consultando...';
  res.style.display='none';
  try{
    const d = await fetch('/cobertura?cep='+raw).then(r=>r.json());
    if(marker){map.removeLayer(marker);marker=null;}
    if(claroMarker){map.removeLayer(claroMarker);claroMarker=null;}
    if(d.coordenadas){
      const {lat,lng}=d.coordenadas;
      marker=L.marker([lat,lng]).addTo(map);
      map.setView([lat,lng],14);
      marker.bindPopup('<b>'+(d.resposta||'')+'</b>').openPopup();
    }
    if(d.pode_vender===true){
      res.className='result ok';
      res.innerHTML='<div class="rtitle">✔ PODE INSTALAR</div>'+
        badge(d.cor_hex, d.performance, d.performance_desc)+
        row('Município',d.municipio)+row('Estação',d.estacao)+
        row('Atingimento',d.atingimento)+row('Cluster',d.cluster)+
        row('HC / HP',d.hc+' / '+d.hp)+row('Ocupação',d.ocupacao);
    } else if(d.cobertura===false){
      res.className='result no';
      res.innerHTML='<div class="rtitle">✖ SEM COBERTURA</div>'+
        '<div style="font-size:11px;color:#fc8181;margin-top:4px">Esta rua ainda não tem cobertura de fibra.</div>'+
        row('Endereço',d.endereco);
    } else {
      res.className='result warn';
      res.innerHTML='<div class="rtitle">⚠ RESTRIÇÃO DE VENDAS</div>'+
        badge('#4A5568','Bloqueado','Não pode vender no momento')+
        row('Município',d.municipio)+row('Estação',d.estacao);
    }
    res.style.display='block';
  }catch(e){
    res.className='result no';
    res.innerHTML='<div class="rtitle">Erro ao consultar</div>';
    res.style.display='block';
  }finally{
    btn.disabled=false; btn.innerHTML='Verificar Cobertura Fibra';
  }
}

async function buscarClaro(){
  const raw = document.getElementById('cep').value.replace(/\D/g,'');
  if(raw.length!==8){alert('Digite um CEP valido.');return;}
  const btn=document.getElementById('btn'), res=document.getElementById('result');
  btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Consultando...';
  res.style.display='none';
  try{
    const claro = await fetch('/api/claro?cep='+raw).then(r=>r.json());
    if(marker){map.removeLayer(marker);marker=null;}
    if(claroMarker){map.removeLayer(claroMarker);claroMarker=null;}

    if(claro.erro){
      res.className='result no';
      res.innerHTML='<div class="rtitle">'+claro.erro+'</div>';
      res.style.display='block';
      return;
    }

    const instalados = claro.total>0 ? claro.resultados.filter(r=>r.qtd_hc && r.qtd_hc!=='0').length : 0;
    const disponiveis = claro.total - instalados;

    if(claro.coordenadas){
      const {lat,lng}=claro.coordenadas;
      map.setView([lat,lng],18);
      if(claro.total>0){
        claroMarker = L.marker([lat,lng], {icon: claroPinIcon}).addTo(map);
        claroMarker.bindPopup(
          '<b>Claro — '+claro.total+' endereco(s) neste CEP</b><br>'+
          'Referencia: '+(claro.endereco_referencia||'')+'<br>'+
          disponiveis+' disponivel(is) · '+instalados+' ja instalado(s)'
        ).openPopup();
      } else {
        marker=L.marker([lat,lng]).addTo(map);
      }
    } else if(claro.total===0){
      res.className='result claro';
      res.innerHTML='<div class="rtitle" style="color:#fc8181">Sem registro Claro</div>'+
        '<div style="font-size:11px;color:#a0aec0">Nenhum endereco desta base foi encontrado para este CEP.</div>';
      res.style.display='block';
      return;
    } else {
      res.className='result no';
      res.innerHTML='<div class="rtitle">Não foi possível localizar o endereço no mapa</div>';
      res.style.display='block';
      return;
    }

    const LIMITE = 40;
    const itens = claro.resultados.slice(0,LIMITE).map(r=>{
      const instalado = r.qtd_hc && r.qtd_hc!=='0';
      const tagCor = instalado ? '#63b3ed' : '#68d391';
      const tagTxt = instalado ? 'Já instalado' : 'Disponível';
      return '<div class="row"><span>'+r.logradouro+', '+(r.num_fachada||'-')+'</span>'+
        '<span style="color:'+tagCor+';font-weight:700">'+tagTxt+'</span></div>';
    }).join('');
    const extra = claro.total>LIMITE ? '<div style="font-size:10px;color:#718096;margin-top:6px">+ '+(claro.total-LIMITE)+' outros endereços neste CEP</div>' : '';
    res.className='result claro';
    res.innerHTML='<div class="rtitle" style="color:#fc8181">Claro — '+claro.total+' endereço(s)</div>'+
      row('Disponível (sem instalação)', disponiveis)+
      row('Já instalado', instalados)+
      '<div style="height:8px"></div>'+
      itens+extra;
    res.style.display='block';
  }catch(e){
    res.className='result no';
    res.innerHTML='<div class="rtitle">Erro ao consultar</div>';
    res.style.display='block';
  }finally{
    btn.disabled=false; btn.innerHTML='Verificar Cobertura Claro';
  }
}

function row(l,v){
  return '<div class="row"><span>'+l+'</span><span>'+(v||'-')+'</span></div>';
}
function badge(cor,label,desc){
  return '<div style="display:flex;align-items:center;gap:8px;background:rgba(0,0,0,.25);border-radius:7px;padding:7px 10px;margin-bottom:10px">'+
    '<div style="width:14px;height:14px;border-radius:3px;background:'+cor+';flex-shrink:0"></div>'+
    '<div><div style="font-weight:700;font-size:12px;color:'+cor+'">'+label+'</div>'+
    '<div style="font-size:10px;color:#a0aec0">'+desc+'</div></div></div>';
}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
