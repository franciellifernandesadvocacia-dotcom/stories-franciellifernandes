"""
Aprovação pelo Telegram: o robô manda as artes do dia seguinte para o celular da Dra. e ela responde
  OK               aprova todos
  OK menos 2 5     aprova todos, menos o 2 e o 5
  NÃO              não publica nenhum daquele dia
Sem Telegram configurado, dá para aprovar editando a coluna "status" da fila.csv no GitHub
(trocar "aguardando" por "aprovado").

  python aprovacao.py --enviar 2026-12-01    manda o lote do dia para o Telegram
"""
import argparse
import csv
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import urllib.request
import uuid

import publicar as P

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(AQUI, "estado.json")


def _cfg():
    tk = "".join(os.environ.get("TELEGRAM_BOT_TOKEN", "").split())   # tira espaços e quebras de linha coladas junto
    chat = "".join(os.environ.get("TELEGRAM_CHAT_ID", "").split())
    return tk, chat


def ler_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return {"offset": 0, "ultimo_lote": "", "lembrete": ""}


def salvar_estado(e):
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1)


def ler_linhas():
    with open(P.FILA, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def gravar_linhas(campos, linhas):
    with open(P.FILA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def _multipart(campos, arquivos):
    fronteira = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{fronteira}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for nome, caminho in arquivos:
        tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        with open(caminho, "rb") as f:
            dados = f.read()
        partes.append((f'--{fronteira}\r\nContent-Disposition: form-data; name="{nome}"; '
                       f'filename="{os.path.basename(caminho)}"\r\nContent-Type: {tipo}\r\n\r\n').encode() + dados + b"\r\n")
    partes.append(f"--{fronteira}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={fronteira}"


def telegram(metodo, campos=None, arquivos=None):
    tk, _ = _cfg()
    url = f"https://api.telegram.org/bot{tk}/{metodo}"
    if arquivos:
        corpo, tipo = _multipart(campos or {}, arquivos)
        req = urllib.request.Request(url, data=corpo, headers={"Content-Type": tipo})
    else:
        req = urllib.request.Request(url, data=json.dumps(campos or {}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def enviar_lote(lote, _tg=None):
    _tg = _tg or telegram
    tk, chat = _cfg()
    if not (tk and chat):
        print("Telegram não configurado: aprove pela coluna status da fila.csv.")
        return 0
    if lote == "exemplo":  # teste: manda as artes de stories/exemplo/, que nunca são publicadas
        pasta = os.path.join(P.PASTA_STORIES, "exemplo")
        do_dia = [{"arquivo": "exemplo/" + f, "hora": "--:--"} for f in sorted(os.listdir(pasta)) if f.endswith(".jpg")]
    else:
        _, linhas = ler_linhas()
        do_dia = [l for l in linhas if l.get("lote") == lote and l.get("status") in ("aguardando", "aprovado")]
    if not do_dia:
        return 0
    textos, tema = {}, ""
    p_txt = os.path.join(P.PASTA_STORIES, lote, "textos.json")
    if os.path.exists(p_txt):
        with open(p_txt, encoding="utf-8") as f:
            dados = json.load(f)
        lista = dados["stories"] if isinstance(dados, dict) else dados
        textos = {i + 1: s for i, s in enumerate(lista)}
        tema = dados.get("tema", "") if isinstance(dados, dict) else ""
    for ini in range(0, len(do_dia), 10):
        grupo = do_dia[ini:ini + 10]
        midia = [{"type": "photo", "media": f"attach://f{i}", "caption": str(ini + i + 1)} for i in range(len(grupo))]
        arqs = [(f"f{i}", os.path.join(P.PASTA_STORIES, l["arquivo"])) for i, l in enumerate(grupo)]
        _tg("sendMediaGroup", {"chat_id": chat, "media": json.dumps(midia)}, arqs)
    resumo = "\n".join(f'{i}. {l["hora"]}  {textos.get(i, {}).get("titulo", l["arquivo"])}'
                       + (f'\n    link: {textos[i]["link"]}' if textos.get(i, {}).get("link") else "")
                       for i, l in enumerate(do_dia, start=1))
    if lote == "exemplo":
        _tg("sendMessage", {"chat_id": chat, "text": "TESTE: estas artes são só um exemplo e NÃO serão publicadas.\n\n" + resumo})
        return 0
    if all(l.get("status") == "aprovado" for l in do_dia):  # modo automático: só avisa o que vai sair
        _tg("sendMessage", {"chat_id": chat, "text":
            f"Stories de {lote[8:10]}/{lote[5:7]} programados (automático)" + (f" — tema: {tema}" if tema else "") +
            f":\n\n{resumo}\n\nVão sair sozinhos. Para cancelar algum, responda por exemplo:\n"
            "NÃO 3 = tira o 3\nNÃO = cancela todos do dia\n"
            "SÓ FOTOS HOJE = hoje só as fotos que você mandar\nSÓ FOTOS = desliga o automático\n"
            "VOCÊ COMANDA = religa"})
    else:
        _tg("sendMessage", {"chat_id": chat, "text":
            f"Stories de {lote[8:10]}/{lote[5:7]} para aprovar" + (f" (tema: {tema})" if tema else "") + f":\n\n{resumo}\n\n"
            "Responda:\nOK = aprova todos\nOK menos 2 5 = aprova todos menos esses\nNÃO = não publica nenhum"})
    e = ler_estado()
    e["ultimo_lote"] = lote
    salvar_estado(e)
    return 0


def interpretar(texto):
    """Devolve ("ok", {números a tirar}) ou ("nao", set()) ou (None, set())."""
    t = texto.strip().lower()
    if re.match(r"^(n[aã]o|nenhum)\b", t):
        nums = set(int(n) for n in re.findall(r"\d+", t))
        return ("ok", nums) if nums else ("nao", set())   # "NÃO 3" tira só o 3
    if re.match(r"^(ok|sim|aprov)", t):
        tirar = set(int(n) for n in re.findall(r"\d+", t)) if re.search(r"menos|tir|exceto|sem", t) else set()
        return "ok", tirar
    return None, set()


def comando_modo(texto):
    """Liga/desliga a sequência automática pelo Telegram.
    SÓ FOTOS HOJE  -> hoje só saem as fotos que ela mandar (amanhã volta ao normal)
    SÓ FOTOS       -> desliga a sequência automática até ela mandar VOCÊ COMANDA
    VOCÊ COMANDA   -> religa"""
    t = texto.strip().lower()
    for a, b in (("ó", "o"), ("ê", "e"), ("á", "a"), ("ç", "c"), ("ô", "o")):
        t = t.replace(a, b)
    if "deslig" not in t and re.search(r"\b(voce comanda|religa\w*|ligar|liga o automatico|volta\w* ao normal)\b", t):
        return "ligar"
    if re.search(r"\b(so fotos|so as minhas fotos|so minhas fotos|deslig\w*|pausa\w*)\b", t):
        return "hoje" if "hoje" in t else "desligar"
    return None


def _quando(l):
    try:
        return P._data_hora(l["data"], l["hora"])
    except (ValueError, KeyError):
        return None


def aplicar_modo(cmd, e, linhas, agora):
    """Pausa ou devolve os stories automáticos que ainda não saíram. Devolve o texto da resposta."""
    hoje = agora.date().isoformat()
    auto = [l for l in linhas if l.get("lote") not in ("enviada", "", None)
            and _quando(l) is not None and _quando(l) > agora]
    if cmd == "ligar":
        e["modo"] = "automatico"
        e.pop("so_fotos_dia", None)
        volta = "aprovado" if os.environ.get("APROVACAO", "obrigatoria") == "automatica" else "aguardando"
        n = 0
        for l in auto:
            if l.get("status") == "pausado":
                l["status"] = volta
                n += 1
        return ("Combinado, eu volto a comandar: a sequência automática está ligada"
                + (f" e {n} stories voltaram para a fila." if n else ".")
                + "\nSuas fotos continuam valendo: é só mandar.")
    alvo = [l for l in auto if l.get("status") in ("aprovado", "aguardando")
            and (cmd == "desligar" or l.get("data") == hoje)]
    for l in alvo:
        l["status"] = "pausado"
    if cmd == "hoje":
        e["so_fotos_dia"] = hoje
        return (f"Combinado: hoje só saem as fotos que você mandar ({len(alvo)} stories automáticos pausados). "
                "Amanhã eu volto a comandar sozinho.\nPara religar antes, mande VOCÊ COMANDA.")
    e["modo"] = "so_fotos"
    return (f"Combinado: sequência automática desligada ({len(alvo)} stories pausados). "
            "Só vão sair as fotos que você mandar.\nQuando quiser que eu volte a comandar, mande VOCÊ COMANDA.")


def ler_respostas(_tg=None, agora=None):
    """Lê as respostas novas no Telegram e atualiza a fila. Chamado a cada rodada do publicador."""
    _tg = _tg or telegram
    tk, chat = _cfg()
    if not (tk and chat):
        return
    e = ler_estado()
    r = _tg("getUpdates", {"offset": e.get("offset", 0), "timeout": 0})
    campos, linhas = ler_linhas()
    mudou = False
    albuns = {}                                     # várias fotos mandadas juntas (álbum) = uma colagem
    for upd in r.get("result", []):
        m = upd.get("message") or {}
        if m.get("media_group_id") and str(m.get("chat", {}).get("id")) == str(chat):
            albuns.setdefault(m["media_group_id"], []).append(m)
    vistos = set()
    for upd in r.get("result", []):
        e["offset"] = upd["update_id"] + 1
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(chat):
            continue
        if msg.get("photo") or (msg.get("document") or {}).get("mime_type", "").startswith("image/"):
            grupo = msg.get("media_group_id")
            if grupo and grupo in vistos:
                continue
            try:                                   # foto mandada por ela vira story
                import foto_story
                if mudou:
                    gravar_linhas(campos, linhas)
                if grupo:
                    vistos.add(grupo)
                foto_story.processar(albuns[grupo] if grupo else msg, chat, _tg)
                campos, linhas = ler_linhas()
                mudou = False
            except Exception as ex:
                P.avisar(f"não consegui montar o story da foto: {ex}")
            continue
        cmd = comando_modo(msg.get("text", ""))
        if cmd:
            resposta = aplicar_modo(cmd, e, linhas, agora or dt.datetime.now(P.fuso()))
            mudou = True
            _tg("sendMessage", {"chat_id": chat, "text": resposta})
            continue
        if msg.get("text", "").strip().lower().startswith("cancelar"):
            futuras = [l for l in linhas if l.get("lote") == "enviada" and l.get("status") == "aprovado"]
            if futuras:
                futuras[-1]["status"] = "tirado"
                mudou = True
                _tg("sendMessage", {"chat_id": chat, "text": "Cancelado: o último story enviado por você não vai sair."})
            continue
        if not e.get("ultimo_lote"):
            continue
        acao, tirar = interpretar(msg.get("text", ""))
        if not acao:
            continue
        lote = e["ultimo_lote"]
        do_dia = [l for l in linhas if l.get("lote") == lote and l.get("status") in ("aguardando", "aprovado", "tirado")]
        for i, l in enumerate(do_dia, start=1):
            l["status"] = "aprovado" if acao == "ok" and i not in tirar else "tirado"
        mudou = True
        ok = sum(l["status"] == "aprovado" for l in do_dia)
        _tg("sendMessage", {"chat_id": chat, "text": f"Combinado: {ok} de {len(do_dia)} stories aprovados."})
    if mudou:
        gravar_linhas(campos, linhas)
    salvar_estado(e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--enviar", required=True, help="lote (AAAA-MM-DD) a mandar para aprovação")
    try:
        sys.exit(enviar_lote(ap.parse_args().enviar))
    except Exception as ex:
        P.avisar(f"não consegui mandar os stories para aprovação: {ex}")
        sys.exit(1)
