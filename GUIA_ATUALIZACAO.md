# Guia de Atualização — Sistema de Cobertura MG

## Arquivos do Projeto

| Arquivo | Local | Função |
|---|---|---|
| `MG (8).kml` | Área de Trabalho | Arquivo fonte com os polígonos de cobertura |
| `converter_kml.py` | Área de Trabalho | Converte KML → JSON |
| `gerar_html.py` | Área de Trabalho | Gera o HTML standalone com dados embutidos |
| `servidor_cobertura.py` | Área de Trabalho e GitHub | Servidor Flask com API e mapa |
| `cobertura_mg.json` | Área de Trabalho e GitHub | Dados de cobertura em JSON |
| `cobertura_mg.html` | Área de Trabalho | Página HTML standalone para teste offline |

---

## Repositório GitHub

- **URL:** https://github.com/alphatelalphatel-hub/cobertura-mg
- **Branch:** main
- **Arquivos que precisam estar no repo:** `servidor_cobertura.py`, `cobertura_mg.json`, `Dockerfile`, `docker-compose.yml`

---

## Servidor VPS (Hostinger)

- **IP:** 187.127.12.21
- **Domínio:** srv1552904.hstgr.cloud
- **URL da API:** https://srv1552904.hstgr.cloud/cobertura
- **URL do Mapa:** https://srv1552904.hstgr.cloud
- **Porta interna do container:** 5000
- **Pasta do projeto no VPS:** /docker/cobertura-mg/
- **Proxy:** Nginx com SSL (Let's Encrypt, renova automático)
- **Certificado:** expira 2026-08-28 (renova automático)

---

## APIs Utilizadas

| Serviço | Função | Chave |
|---|---|---|
| ViaCEP | CEP → endereço | Gratuita, sem chave |
| OpenCage | Endereço → lat/lng | dbf3f5f383ee4f0a8485d8810f047804 |

---

## Como Atualizar o Arquivo de Cobertura (novo KML)

### Passo 1 — Preparar o novo KML
Coloca o novo arquivo `.kml` na Área de Trabalho.

Abre o arquivo `converter_kml.py` e muda a linha 4:
```python
KML_FILE = r"C:\Users\re_kl\OneDrive\Área de Trabalho\NOVO_ARQUIVO.kml"
```

### Passo 2 — Converter na máquina local
Abre um terminal na Área de Trabalho e roda:
```bash
python converter_kml.py
python gerar_html.py
```

Isso gera o `cobertura_mg.json` e `cobertura_mg.html` atualizados.

### Passo 3 — Subir para o GitHub
```bash
cd "C:\Users\re_kl\OneDrive\Área de Trabalho\cobertura-mg-repo"
copy "..\cobertura_mg.json" .
git add cobertura_mg.json
git commit -m "Atualização de cobertura"
git push
```

### Passo 4 — Atualizar o VPS
Abre o terminal do VPS no Hostinger e cola esses comandos um por vez:

```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/alphatelalphatel-hub/cobertura-mg/main/cobertura_mg.json', '/docker/cobertura-mg/cobertura_mg.json'); print('OK')"
```

```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/alphatelalphatel-hub/cobertura-mg/main/servidor_cobertura.py', '/docker/cobertura-mg/servidor_cobertura.py'); print('OK')"
```

```bash
docker compose -f /docker/cobertura-mg/docker-compose.yml up -d --build
```

---

## Como Atualizar Só o Código do Servidor (sem mudar o KML)

### Passo 1 — Editar o servidor localmente
Edita o arquivo `servidor_cobertura.py` na Área de Trabalho.

### Passo 2 — Subir para o GitHub
```bash
cd "C:\Users\re_kl\OneDrive\Área de Trabalho\cobertura-mg-repo"
copy "..\servidor_cobertura.py" .
git add servidor_cobertura.py
git commit -m "Descrição da alteração"
git push
```

### Passo 3 — Atualizar o VPS
```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/alphatelalphatel-hub/cobertura-mg/main/servidor_cobertura.py', '/docker/cobertura-mg/servidor_cobertura.py'); print('OK')"
```

```bash
docker compose -f /docker/cobertura-mg/docker-compose.yml up -d --build
```

---

## Endpoints da API

| Endpoint | Método | Descrição |
|---|---|---|
| `/` | GET | Mapa interativo com busca por CEP |
| `/cobertura?cep=00000000` | GET | Verifica cobertura por CEP |
| `/cobertura` | POST `{"cep":"00000000"}` | Verifica cobertura por CEP |
| `/mapa-data` | GET | Retorna todos os polígonos em JSON |
| `/health` | GET | Status do servidor |

---

## Integração n8n

- **URL do nó HTTP Request:** `https://srv1552904.hstgr.cloud/cobertura`
- **Método:** GET ou POST
- **Parâmetro:** `cep` (somente números, ex: 31720260)

### Resposta da API para a IA

```json
{
  "pode_vender": true,
  "cobertura": true,
  "endereco": "Rua Exemplo, Bairro, Belo Horizonte - MG",
  "cep": "31720-260",
  "resposta": "SIM - A rua Rua Exemplo, Bairro, Belo Horizonte tem cobertura disponivel. Pode instalar.",
  "coordenadas": { "lat": -19.82, "lng": -43.94 }
}
```

---

## Verificar se o Servidor está Online

Acessa no navegador:
```
https://srv1552904.hstgr.cloud/health
```

Deve retornar:
```json
{"status": "ok", "regioes_carregadas": 6911}
```
