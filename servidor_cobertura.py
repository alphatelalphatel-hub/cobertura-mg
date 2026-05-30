import json
import os
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

JSON_FILE = os.path.join(os.path.dirname(__file__), 'cobertura_mg.json')

print("Carregando dados de cobertura...")
with open(JSON_FILE, encoding='utf-8') as f:
    raw = json.load(f)

cobertura = []
for feat in raw:
    lngs = [p[0] for p in feat['coords']]
    lats = [p[1] for p in feat['coords']]
    cobertura.append({**feat, 'bb': (min(lngs), min(lats), max(lngs), max(lats))})

# Pré-processa dados para o mapa (inverte lng/lat para lat/lng do Leaflet)
print("Preparando dados do mapa...")
mapa_features = []
for feat in cobertura:
    status = feat.get('s', '')
    color = '#38A169' if 'sem restri' in status.lower() else '#DD6B20' if status else '#4A5568'
    mapa_features.append({
        'n': feat.get('n', ''), 's': feat.get('s', ''), 'm': feat.get('m', ''),
        'e': feat.get('e', ''), 'o': feat.get('o', ''),
        'hc': feat.get('hc', ''), 'hp': feat.get('hp', ''),
        'c': color,
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
    except Exception as e:
        return jsonify({"erro": str(e)}), 502

    if via is None or via.get('erro'):
        return jsonify({"erro": "CEP nao encontrado."}), 404

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
        "coordenadas": coords
    })


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
<title>Cobertura Fibra MG</title>
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
#result{margin-top:14px;border-radius:10px;padding:12px;display:none;font-size:12px}
#result.ok{background:#1c4532;border:1px solid #38a169}
#result.no{background:#742a2a;border:1px solid #e53e3e}
#result.warn{background:#7b341e;border:1px solid #dd6b20}
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
  <h1>Cobertura Fibra MG</h1>
  <p class="sub" id="subtotal">Carregando regioes...</p>
  <label>CEP do cliente</label>
  <input type="text" id="cep" placeholder="00000-000" maxlength="9" inputmode="numeric">
  <button id="btn" onclick="buscar()">Verificar Cobertura</button>
  <div id="result"></div>
  <div class="legend" style="margin-top:20px">
    <h3>Legenda</h3>
    <div class="li"><div class="lc" style="background:#38A169;opacity:.8"></div>Pode instalar</div>
    <div class="li"><div class="lc" style="background:#DD6B20;opacity:.8"></div>Restricao de vendas</div>
  </div>
</div>
<div id="map"></div>
<div id="overlay"><span class="spinner"></span> Carregando regioes de cobertura...</div>

<script>
const map = L.map('map', {preferCanvas: true}).setView([-19.5, -44.5], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap', maxZoom: 19
}).addTo(map);

let marker = null;

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
        '<br>Status: '+f.s+'<br>HC: '+f.hc+' / HP: '+f.hp+
        '<br>Ocupacao: '+f.o,
        {maxWidth: 220}
      )
      .addTo(map);
    });
    document.getElementById('overlay').remove();
  })
  .catch(()=>document.getElementById('overlay').remove());

async function buscar(){
  const raw = document.getElementById('cep').value.replace(/\D/g,'');
  if(raw.length!==8){alert('Digite um CEP valido.');return;}
  const btn=document.getElementById('btn'), res=document.getElementById('result');
  btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Consultando...';
  res.style.display='none';
  try{
    const d = await fetch('/cobertura?cep='+raw).then(r=>r.json());
    if(marker){map.removeLayer(marker);marker=null;}
    if(d.coordenadas){
      const {lat,lng}=d.coordenadas;
      marker=L.marker([lat,lng]).addTo(map);
      map.setView([lat,lng],14);
      marker.bindPopup('<b>'+(d.resposta||'')+'</b>').openPopup();
    }
    if(d.pode_vender===true){
      res.className='result ok';
      res.innerHTML='<div class="rtitle">PODE INSTALAR</div>'+
        row('Municipio',d.municipio)+row('Estacao',d.estacao)+
        row('Status',d.status_venda)+row('HC / HP',d.hc+' / '+d.hp)+
        row('Ocupacao',d.ocupacao);
    } else if(d.cobertura===false){
      res.className='result no';
      res.innerHTML='<div class="rtitle">SEM COBERTURA</div>'+
        row('Municipio',d.municipio)+row('UF',d.uf)+
        '<div style="font-size:11px;color:#fc8181;margin-top:6px">'+(d.motivo||'')+'</div>';
    } else {
      res.className='result warn';
      res.innerHTML='<div class="rtitle">RESTRICAO DE VENDAS</div>'+
        row('Municipio',d.municipio)+row('Estacao',d.estacao)+
        row('Status',d.status_venda);
    }
    res.style.display='block';
  }catch(e){
    res.className='result no';
    res.innerHTML='<div class="rtitle">Erro ao consultar</div>';
    res.style.display='block';
  }finally{
    btn.disabled=false; btn.innerHTML='Verificar Cobertura';
  }
}

function row(l,v){
  return '<div class="row"><span>'+l+'</span><span>'+(v||'-')+'</span></div>';
}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
