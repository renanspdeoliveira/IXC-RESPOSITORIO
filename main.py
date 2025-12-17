import os
import base64
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# carrega .env ao lado do main.py
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

IXC_HOST = os.getenv("IXC_HOST", "").rstrip("/")
IXC_TOKEN = os.getenv("IXC_TOKEN", "")
IXC_VERIFY_SSL = os.getenv("IXC_VERIFY_SSL", "1") != "0"

if not IXC_HOST or not IXC_TOKEN:
    raise RuntimeError("Configure IXC_HOST e IXC_TOKEN no .env")

if not IXC_VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def ixc_headers(ixcsoft_value: str):
    token_b64 = base64.b64encode(IXC_TOKEN.encode("utf-8")).decode("utf-8")
    h = {
        "Authorization": f"Basic {token_b64}",
        "Content-Type": "application/json",
    }
    if ixcsoft_value is not None:
        h["ixcsoft"] = ixcsoft_value
    return h

def norm_records(resp: dict):
    return resp.get("registros") or resp.get("data") or resp.get("records") or []

def ixc_list(endpoint: str, payload: dict):
    url = f"{IXC_HOST}/webservice/v1/{endpoint.lstrip('/')}"
    r = requests.post(
        url,
        headers=ixc_headers("listar"),
        json=payload,
        timeout=60,
        verify=IXC_VERIFY_SSL,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

def ixc_insert(endpoint: str, payload: dict):
    url = f"{IXC_HOST}/webservice/v1/{endpoint.lstrip('/')}"
    r = requests.post(
        url,
        headers=ixc_headers(""),  # inserir normalmente sem "listar"
        json=payload,
        timeout=60,
        verify=IXC_VERIFY_SSL,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

def get_rad_by_login(login: str) -> dict:
    rad_resp = ixc_list("radusuarios", {
        "qtype": "radusuarios.login",
        "query": login,
        "oper": "=",
        "page": "1",
        "rp": "1",
        "sortname": "radusuarios.id",
        "sortorder": "desc",
    })
    regs = norm_records(rad_resp)
    if not regs:
        raise HTTPException(status_code=404, detail="Login não encontrado em radusuarios")
    return regs[0]

def get_id_login(rad: dict):
    return rad.get("id") or rad.get("radusuarios.id") or rad.get("radusuarios_id")

def try_get_id_cliente(rad: dict):
    return (rad.get("id_cliente") or rad.get("cliente_id") or rad.get("idcliente") or rad.get("idCliente") or "")

def parse_dt(s: str):
    # IXC normalmente usa "YYYY-MM-DD HH:MM:SS"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

app = FastAPI(title="FuturaNet IXC Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restrinja
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========= RADUSUARIOS =========

@app.get("/api/radusuarios/latest")
def rad_latest(page: int = 1, rp: int = 20):
    return ixc_list("radusuarios", {
        "qtype": "radusuarios.id",
        "query": "0",
        "oper": ">",
        "page": str(page),
        "rp": str(rp),
        "sortname": "radusuarios.id",
        "sortorder": "desc",
    })

# ========= CARD (RAD + RADPOP) =========

@app.get("/api/card/by-login")
def card_by_login(login: str = Query(..., min_length=1)):
    rad = get_rad_by_login(login)
    id_login = get_id_login(rad)
    if not id_login:
        raise HTTPException(status_code=500, detail="Não consegui obter id_login do radusuarios")

    pop_resp = ixc_list("radpop_radio_cliente_fibra", {
        "qtype": "radpop_radio_cliente_fibra.id_login",
        "query": str(id_login),
        "oper": "=",
        "page": "1",
        "rp": "1",
        "sortname": "radpop_radio_cliente_fibra.id",
        "sortorder": "desc",
    })
    pop_regs = norm_records(pop_resp)
    pop = pop_regs[0] if pop_regs else {}

    return {"id_login": id_login, "login": login, "radusuarios": rad, "radpop": pop}

# ========= ATENDIMENTOS (LISTA) =========

@app.get("/api/tickets/by-login")
def tickets_by_login(login: str = Query(..., min_length=1), rp: int = 50, page: int = 1):
    rad = get_rad_by_login(login)
    id_login = get_id_login(rad)
    if not id_login:
        raise HTTPException(status_code=500, detail="Não consegui obter id_login do radusuarios")

    resp = ixc_list("su_ticket", {
        "qtype": "su_ticket.id_login",
        "query": str(id_login),
        "oper": "=",
        "page": str(page),
        "rp": str(rp),
        "sortname": "su_ticket.id",
        "sortorder": "desc",
    })
    return {"login": login, "id_login": id_login, "tickets": norm_records(resp)}

# ========= RESUMO 30 DIAS (ATENDIMENTOS + ORDENS) =========
# ORDENS fica como 0 até você me dizer qual endpoint correto (ex: su_os)

@app.get("/api/summary/by-login")
def summary_by_login(login: str = Query(..., min_length=1)):
    rad = get_rad_by_login(login)
    id_login = get_id_login(rad)
    if not id_login:
        raise HTTPException(status_code=500, detail="Não consegui obter id_login do radusuarios")

    limite = datetime.now() - timedelta(days=30)

    # -------- ATENDIMENTOS (su_ticket) --------
    resp_t = ixc_list("su_ticket", {
        "qtype": "su_ticket.id_login",
        "query": str(id_login),
        "oper": "=",
        "page": "1",
        "rp": "300",
        "sortname": "su_ticket.data_criacao",
        "sortorder": "desc",
    })
    tickets = norm_records(resp_t)

    recentes = []
    for t in tickets:
        dc = t.get("data_criacao") or ""
        d = parse_dt(dc)
        if not d:
            continue
        if d >= limite:
            recentes.append({
                "id": t.get("id", ""),
                "data_criacao": dc,
                "titulo": t.get("titulo") or "",
                "id_assunto": t.get("id_assunto") or "",
                "status": t.get("status") or "",
            })

    # -------- O.S. (su_oss_chamado) --------
    resp_o = ixc_list("su_oss_chamado", {
        "qtype": "su_oss_chamado.id_login",
        "query": str(id_login),
        "oper": "=",
        "page": "1",
        "rp": "1000",
        "sortname": "su_oss_chamado.id",
        "sortorder": "desc",
        # filtro por data_abertura > limite (igual seu cURL)
        "grid_param": (
            f'[{{"TB":"su_oss_chamado.data_abertura","OP":">","P":"{limite.strftime("%Y-%m-%d %H:%M:%S")}"}}]'
        )
    })
    oss = norm_records(resp_o)

    ordens = []
    for o in oss:
        da = o.get("data_abertura") or ""
        d = parse_dt(da)
        # se vier fora do formato, ignora; o grid_param já filtra a maioria
        if d and d >= limite:
            ordens.append({
                "id": o.get("id", ""),
                "data_abertura": da,
                "status": o.get("status") or o.get("situacao") or "",
            })

    return {
        "login": login,
        "id_login": id_login,
        "atendimentos_30d": len(recentes),
        "atendimentos": recentes[:10],
        "ordens_30d": len(ordens),
        "ordens": ordens[:10],
    }

# ========= CRIAR NOVO ATENDIMENTO (su_ticket) =========

def ticket_template() -> dict:
    """Template com TODOS os campos do seu exemplo (string vazia), igual ao request do IXC."""
    return {
        "tipo": "C",
        "id_estrutura": "",
        "protocolo": "",
        "id_circuito": "",
        "id_cliente": "",
        "id_login": "",
        "id_contrato": "",
        "id_filial": "",
        "id_assunto": "",
        "titulo": "",
        "origem_endereco": "",
        "origem_endereco_estrutura": "",
        "endereco": "",
        "latitude": "",
        "longitude": "",
        "id_wfl_processo": "",
        "id_ticket_setor": "",
        "id_responsavel_tecnico": "",
        "data_criacao": "",
        "data_ultima_alteracao": "",
        "prioridade": "",
        "data_reservada": "",
        "melhor_horario_reserva": "",
        "id_ticket_origem": "",
        "id_usuarios": "",
        "id_resposta": "",
        "menssagem": "",
        "interacao_pendente": "",
        "su_status": "",
        "id_evento_status_processo": "",
        "id_canal_atendimento": "",
        "status": "",
        "mensagens_nao_lida_cli": "",
        "mensagens_nao_lida_sup": "",
        "token": "",
        "finalizar_atendimento": "",
        "id_su_diagnostico": "",
        "status_sla": "",
        "origem_cadastro": "",
        "ultima_atualizacao": "",
        "cliente_fone": "",
        "cliente_telefone_comercial": "",
        "cliente_id_operadora_celular": "",
        "cliente_telefone_celular": "",
        "cliente_whatsapp": "",
        "cliente_ramal": "",
        "cliente_email": "",
        "cliente_contato": "",
        "cliente_website": "",
        "cliente_skype": "",
        "cliente_facebook": "",
        "latitude_cli": "",
        "longitude_cli": "",
        "latitude_login": "",
        "longitude_login": "",
    }


@app.get("/api/tickets/template/by-login")
def ticket_template_by_login(login: str = Query(..., min_length=1)):
    """Retorna o template já pré-preenchido com id_login e, se existir, id_cliente."""
    rad = get_rad_by_login(login)
    id_login = get_id_login(rad)
    if not id_login:
        raise HTTPException(status_code=500, detail="Não consegui obter id_login do radusuarios")
    id_cliente = try_get_id_cliente(rad)

    t = ticket_template()
    t["id_login"] = str(id_login)
    t["id_cliente"] = str(id_cliente) if id_cliente else ""

    # defaults seguros (você pode mudar conforme seu IXC)
    t["id_ticket_setor"] = "2"
    t["prioridade"] = "B"
    t["su_status"] = "N"

    return {"login": login, "id_login": id_login, "template": t}


class TicketCreate(BaseModel):
    # chave de busca
    login: str = Field(..., min_length=1)

    # obrigatórios (conforme seu exemplo)
    id_cliente: str | None = None
    id_assunto: str = Field(..., min_length=1)
    titulo: str = Field(..., min_length=1)
    id_ticket_setor: str = Field(..., min_length=1)
    prioridade: str = Field(..., min_length=1)
    menssagem: str = Field(..., min_length=1)
    su_status: str = Field(..., min_length=1)

    # opcionais principais (se não vier, vai como "")
    protocolo: str | None = None
    id_contrato: str | None = None
    id_filial: str | None = None
    id_estrutura: str | None = None
    origem_endereco: str | None = None
    endereco: str | None = None
    latitude: str | None = None
    longitude: str | None = None

@app.post("/api/tickets/open")
def open_ticket(data: TicketCreate):
    """Cria su_ticket (tipo C) no IXC, usando o template completo e preenchendo os campos."""
    rad = get_rad_by_login(data.login)
    id_login = get_id_login(rad)
    if not id_login:
        raise HTTPException(status_code=500, detail="Não consegui obter id_login do radusuarios")

    inferred_cliente = try_get_id_cliente(rad)
    id_cliente = (data.id_cliente or inferred_cliente or "").strip()

    payload = ticket_template()

    # sempre tipo C
    payload["tipo"] = "C"

    # obrigatórios
    payload["id_login"] = str(id_login)
    payload["id_cliente"] = str(id_cliente)
    payload["id_assunto"] = str(data.id_assunto)
    payload["titulo"] = str(data.titulo)
    payload["id_ticket_setor"] = str(data.id_ticket_setor)
    payload["prioridade"] = str(data.prioridade)
    payload["menssagem"] = str(data.menssagem)
    payload["su_status"] = str(data.su_status)

    # opcionais (se vier)
    if data.protocolo is not None:
        payload["protocolo"] = str(data.protocolo)
    if data.id_contrato is not None:
        payload["id_contrato"] = str(data.id_contrato)
    if data.id_filial is not None:
        payload["id_filial"] = str(data.id_filial)
    if data.id_estrutura is not None:
        payload["id_estrutura"] = str(data.id_estrutura)
    if data.origem_endereco is not None:
        payload["origem_endereco"] = str(data.origem_endereco)
    if data.endereco is not None:
        payload["endereco"] = str(data.endereco)
    if data.latitude is not None:
        payload["latitude"] = str(data.latitude)
    if data.longitude is not None:
        payload["longitude"] = str(data.longitude)

    created = ixc_insert("su_ticket", payload)
    return {"created": created, "login": data.login, "id_login": id_login, "payload_sent": payload}
