"""
Story a partir de uma foto mandada pela Dra. no Telegram.

Ela manda a foto (academia, café, escritório...) com ou sem instruções na legenda, por exemplo:
  "segunda começando com café" (entre aspas = texto exato do story)
  sem sombra · foto sem escurecer · mais escuro · sem texto · texto em cima / no meio / embaixo
  com faixa · agora · às 18h
O robô entende as instruções (com o Claude, que também olha a foto para escrever uma frase curta
quando não vier texto), desenha o story no estilo do perfil, coloca na fila e responde no Telegram.
"""
import base64
import datetime as dt
import json
import os
import re
import urllib.request

import arte_natural as A
import publicar as P

OPCOES_PADRAO = {"texto": "", "sem_texto": False, "sombra": True, "exposicao": None,
                 "posicao": "auto", "faixa": False, "quando": ""}

ESQUEMA = {
    "type": "object",
    "properties": {
        "texto": {"type": "string"},
        "sem_texto": {"type": "boolean"},
        "sombra": {"type": "boolean"},
        "exposicao": {"type": "number"},
        "posicao": {"type": "string", "enum": ["auto", "topo", "meio", "base"]},
        "faixa": {"type": "boolean"},
        "quando": {"type": "string"},
    },
    "required": ["texto", "sem_texto", "sombra", "exposicao", "posicao", "faixa", "quando"],
    "additionalProperties": False,
}


def interpretar_simples(legenda):
    """Sem Claude: entende as instruções por palavras-chave."""
    o = dict(OPCOES_PADRAO)
    t = (legenda or "").strip()
    m = re.search(r'[“"](.+?)[”"]', t)
    if m:
        o["texto"] = m.group(1).strip()
    b = t.lower()
    o["sombra"] = not re.search(r"sem sombra", b)
    o["sem_texto"] = bool(re.search(r"sem (texto|frase|legenda)", b))
    o["faixa"] = bool(re.search(r"com faixa|com fundo", b))
    if re.search(r"sem escurecer|n[aã]o escure|foto clara|sem escuro", b):
        o["exposicao"] = 1.0
    elif re.search(r"mais escur", b):
        o["exposicao"] = 0.45
    for chave, pos in (("em cima", "topo"), ("no topo", "topo"), ("no meio", "meio"), ("embaixo", "base"), ("em baixo", "base")):
        if chave in b:
            o["posicao"] = pos
    h = re.search(r"\b(?:[àa]s?\s*)?(\d{1,2})\s*(?:h|:)\s*(\d{2})?", b)
    if "agora" in b:
        o["quando"] = "agora"
    elif h and int(h.group(1)) < 24:
        o["quando"] = f"{int(h.group(1)):02d}:{int(h.group(2) or 0):02d}"
    return o


def interpretar_com_claude(legenda, caminho_foto, cliente=None):
    """Com Claude: entende instruções em frase livre e, se não vier texto, escreve uma frase curta olhando a foto."""
    import gerar_dia as G
    cliente = cliente or G._cliente()
    with open(caminho_foto, "rb") as f:
        dados = base64.b64encode(f.read()).decode()
    pedido = (
        "A Dra. mandou esta foto para virar um story do Instagram " + A.PERFIL["handle"] + ".\n"
        f"Mensagem dela junto com a foto: {legenda or '(nenhuma)'}\n\n"
        "Transforme a mensagem em ajustes:\n"
        "- texto: se ela escreveu um texto entre aspas, copie exatamente. Se não, escreva UMA frase curta "
        "(até 90 caracteres), natural e elegante, combinando com a foto e o momento (rotina, café, treino, "
        "escritório). Nada de promessas, preços ou chamadas para contratar. Sem emojis e sem hashtags.\n"
        "- sem_texto: true só se ela pediu sem texto.\n"
        "- sombra: false só se ela pediu sem sombra.\n"
        "- exposicao: 1.0 se pediu para não escurecer; 0.45 se pediu mais escuro; caso contrário 0 (= padrão do perfil).\n"
        "- posicao: topo, meio, base ou auto.\n"
        "- faixa: true se pediu faixa/fundo atrás das letras.\n"
        "- quando: \"agora\", um horário \"HH:MM\" ou \"\" (sem pedido).")
    resp = cliente.beta.messages.create(
        model=G.MODELO, max_tokens=2000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=G.REGRAS, output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}},
            {"type": "text", "text": pedido}]}])
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError("o Claude não conseguiu ler as instruções")
    o = dict(OPCOES_PADRAO)
    o.update(json.loads(G._texto(resp)))
    if not o.get("exposicao"):
        o["exposicao"] = None
    return o


def interpretar(legenda, caminho_foto):
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return interpretar_com_claude(legenda, caminho_foto)
        except Exception as e:  # sem Claude, ainda dá para fazer pelo jeito simples
            print("Claude indisponível, uso as palavras-chave:", e)
    return interpretar_simples(legenda)


def horario(quando, agora, ocupados):
    """Publica no mínimo 5 min depois (o robô precisa guardar a imagem antes). Sem pedido: próximo horário
    redondo que fique a mais de 40 min dos outros stories do dia."""
    minimo = agora + dt.timedelta(minutes=5)
    if quando and re.match(r"^\d{2}:\d{2}$", quando):
        h, m = map(int, quando.split(":"))
        alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        return max(alvo if alvo >= agora else alvo + dt.timedelta(days=1), minimo)
    if quando == "agora":
        return minimo
    t = (agora + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    for _ in range(48):
        if 7 <= t.hour <= 21 and all(abs((t - o).total_seconds()) > 40 * 60 for o in ocupados):
            return t
        t += dt.timedelta(minutes=30)
    return minimo


def baixar_foto_telegram(file_id, destino, _tg):
    info = _tg("getFile", {"file_id": file_id})
    caminho = info["result"]["file_path"]
    tk = "".join(os.environ.get("TELEGRAM_BOT_TOKEN", "").split())
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{tk}/{caminho}", timeout=60) as r:
        with open(destino, "wb") as f:
            f.write(r.read())
    return destino


def processar(msg, chat, _tg, agora=None, _baixar=None):
    """Recebe a mensagem do Telegram com foto, cria o story e põe na fila (já aprovado: foi ela quem mandou)."""
    import aprovacao
    import arte_sobria
    agora = agora or dt.datetime.now(P.fuso())
    fotos = msg.get("photo") or []
    file_id = fotos[-1]["file_id"] if fotos else (msg.get("document") or {}).get("file_id")
    if not file_id:
        return None
    pasta = os.path.join(P.PASTA_STORIES, agora.strftime("%Y-%m-%d"))
    os.makedirs(pasta, exist_ok=True)
    marca = agora.strftime("%H%M%S")
    original = os.path.join(pasta, f"enviada-{marca}-original.jpg")
    (_baixar or baixar_foto_telegram)(file_id, original, _tg)
    opcoes = interpretar(msg.get("caption", ""), original)
    nome = f"{agora:%Y-%m-%d}/enviada-{marca}.jpg"
    arte_sobria.desenhar_foto(original, opcoes, os.path.join(P.PASTA_STORIES, nome))
    os.remove(original)                       # o original não fica guardado no repositório
    campos, linhas = aprovacao.ler_linhas()
    ocupados = []
    for l in linhas:
        try:
            ocupados.append(P._data_hora(l["data"], l["hora"]))
        except (ValueError, KeyError):
            pass
    quando = horario(opcoes.get("quando", ""), agora, ocupados)
    linhas.append({"arquivo": nome, "data": quando.strftime("%Y-%m-%d"), "hora": quando.strftime("%H:%M"),
                   "status": "aprovado", "lote": "enviada"})
    aprovacao.gravar_linhas(campos or ["arquivo", "data", "hora", "status", "lote"], linhas)
    resumo = "sem texto" if opcoes.get("sem_texto") else f'texto: "{opcoes.get("texto", "")}"'
    _tg("sendPhoto", {"chat_id": chat, "caption":
        f"Story programado para {quando:%d/%m às %H:%M} ({resumo}). Para cancelar, responda CANCELAR."},
        [("photo", os.path.join(P.PASTA_STORIES, nome))])
    return nome
