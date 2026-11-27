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
import subprocess
import urllib.request

import arte_natural as A
import publicar as P

OPCOES_PADRAO = {"texto": "", "sem_texto": False, "sombra": True, "exposicao": None,
                 "posicao": "auto", "faixa": False, "quando": "",
                 "alinhamento": "", "fonte": "normal", "tamanho": "pequeno", "caixa": "", "minusculas": False,
                 "modelo_indice": -1, "borda": False}
PEDE_MODELO = r"modelo|refer[eê]ncia|igual (a|à|ao|esse|essa)|mesmo estilo|nesse estilo|nessa pegada|inspira"
LIMITE_TELEGRAM = 20 * 1024 * 1024        # o Telegram só deixa o robô baixar arquivos de até 20 MB

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
        "alinhamento": {"type": "string", "enum": ["", "esquerda", "centro", "direita"]},
        "fonte": {"type": "string", "enum": ["normal", "maquina"]},
        "tamanho": {"type": "string", "enum": ["pequeno", "medio", "grande"]},
        "caixa": {"type": "string", "enum": ["", "nenhuma", "faixa", "cartao"]},
        "minusculas": {"type": "boolean"},
        "modelo_indice": {"type": "integer"},
        "borda": {"type": "boolean"},
    },
    "required": ["texto", "sem_texto", "sombra", "exposicao", "posicao", "faixa", "quando",
                 "alinhamento", "fonte", "tamanho", "caixa", "minusculas", "modelo_indice", "borda"],
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
    o["borda"] = bool(re.search(r"com borda|com espa[cç]o", b))
    if re.search(r"centraliz|no centro|no meio", b):
        o["alinhamento"] = "centro"
    if re.search(r"sem escurecer|n[aã]o escure|foto clara|sem escuro", b):
        o["exposicao"] = 1.0
    elif re.search(r"mais escur", b):
        o["exposicao"] = 0.45
    for chave, pos in (("em cima", "topo"), ("no topo", "topo"), ("no meio", "meio"), ("embaixo", "base"), ("em baixo", "base")):
        if chave in b:
            o["posicao"] = pos
    if re.search(r"sub(a|ir|ir o|e) (o )?texto", b):
        o["posicao"] = "topo"
    elif re.search(r"des[cç](a|er|e) (o )?texto", b):
        o["posicao"] = "base"
    for chave, al in (("esquerda", "esquerda"), ("direita", "direita"), ("centraliz", "centro")):
        if chave in b:
            o["alinhamento"] = al
    if re.search(r"m[aá]quina de escrever|datilograf", b):
        o["fonte"] = "maquina"
    if re.search(r"letra (pequena|menor)|texto pequeno|pequenininh", b):
        o["tamanho"] = "pequeno"
    elif re.search(r"letra (grande|maior)|texto grande|bem grande", b):
        o["tamanho"] = "grande"
    if re.search(r"cart[aã]o|caixa branca|fundo branco", b):
        o["caixa"] = "cartao"
    if re.search(r"min[uú]scul", b):
        o["minusculas"] = True
    h = re.search(r"\b(?:[àa]s?\s*)?(\d{1,2})\s*(?:h|:)\s*(\d{2})?", b)
    if "agora" in b:
        o["quando"] = "agora"
    elif h and int(h.group(1)) < 24:
        o["quando"] = f"{int(h.group(1)):02d}:{int(h.group(2) or 0):02d}"
    return o


def interpretar_com_claude(legenda, caminho_foto, cliente=None, video=False):
    """Com Claude: entende instruções em frase livre, reconhece a foto de MODELO (quando ela manda uma
    referência de posição de texto) e, se não vier texto, escreve uma frase curta olhando a foto."""
    import gerar_dia as G
    cliente = cliente or G._cliente()
    fotos = caminho_foto if isinstance(caminho_foto, (list, tuple)) else [caminho_foto]
    conteudo = []
    for k, c in enumerate(fotos):
        with open(c, "rb") as f:
            dados = base64.b64encode(f.read()).decode()
        conteudo += [{"type": "text", "text": f"Imagem {k}:"},
                     {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}}]
    pedido = (
        "A Dra. mandou " + ("um VÍDEO (a imagem 0 é um quadro do meio dele)" if video else
                            f"{len(fotos)} imagem(ns)") + " para virar story do Instagram " + A.PERFIL["handle"] + ".\n"
        f"Mensagem dela junto: {legenda or '(nenhuma)'}\n\n"
        "Transforme a mensagem em ajustes:\n"
        "- modelo_indice: se uma das imagens é só uma REFERÊNCIA de estilo/posição de texto (print de story de outra "
        "pessoa, ou ela disse 'modelo', 'igual a esse', 'nessa pegada'), o número dessa imagem; senão -1. "
        "Quando houver modelo, COPIE dele: posicao (topo/meio/base), alinhamento (esquerda/centro/direita), "
        "fonte (maquina se parecer máquina de escrever, senão normal), tamanho (pequeno/medio/grande), "
        "caixa (faixa = fundo escuro atrás de cada linha; cartao = caixa branca com letra escura; nenhuma) e "
        "minusculas (true se o texto do modelo é todo em minúsculas). NUNCA copie o texto do modelo.\n"
        "- texto: se ela escreveu um texto (entre aspas, depois de 'legenda:' ou 'escreva ...'), copie exatamente o "
        "texto dela, sem as instruções. Se não, escreva UMA frase bem curta (até 50 caracteres), do jeito que a "
        "gente escreve num story do dia a dia: simples, leve, sem cara de título ou gancho de post. Nada de "
        "promessas, preços ou chamadas para contratar. Sem emojis e sem hashtags.\n"
        "- sem_texto: true só se ela pediu sem texto.\n"
        "- sombra: false só se ela pediu sem sombra.\n"
        "- exposicao: 1.0 se pediu para não escurecer; 0.45 se pediu mais escuro; senão 0 (= automático).\n"
        "- posicao: topo, meio, base ou auto (auto = o robô acha a parte mais escura da foto).\n"
        "- alinhamento: esquerda, centro, direita ou \"\" (automático).\n"
        "- faixa: true se pediu faixa/fundo atrás das letras.\n"
        "- tamanho: pequeno (letra de story do dia a dia), a não ser que ela peça letra maior ou o modelo mostre.\n"
        "- borda: true só se ela pediu borda/espaço entre as fotos da colagem (o padrão é sem borda).\n"
        "- 'mais centralizado' = alinhamento centro; 'suba o texto' = posicao topo ou meio (o que ficar mais alto que "
        "antes sem cobrir rosto); 'desça o texto' = base. Siga cada pedido dela à risca.\n"
        "- quando: \"agora\", um horário \"HH:MM\" ou \"\" (sem pedido).")
    resp = cliente.beta.messages.create(
        model=G.MODELO, max_tokens=2000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=G.REGRAS, output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": conteudo + [{"type": "text", "text": pedido}]}])
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError("o Claude não conseguiu ler as instruções")
    o = dict(OPCOES_PADRAO)
    o.update(json.loads(G._texto(resp)))
    if not o.get("exposicao"):
        o["exposicao"] = None
    if not (0 <= o.get("modelo_indice", -1) < len(fotos)) or video:
        o["modelo_indice"] = -1
    return o


def interpretar(legenda, caminho_foto, video=False):
    fotos = caminho_foto if isinstance(caminho_foto, (list, tuple)) else [caminho_foto]
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return interpretar_com_claude(legenda, fotos, video=video)
        except Exception as e:  # sem Claude, ainda dá para fazer pelo jeito simples
            print("Claude indisponível, uso as palavras-chave:", e)
    o = interpretar_simples(legenda)
    if len(fotos) > 1 and re.search(PEDE_MODELO, (legenda or "").lower()):
        o["modelo_indice"] = len(fotos) - 1          # sem Claude: a última imagem é o modelo
    return o


def horario(quando, agora, ocupados):
    """Horário pedido por ela ("HH:MM") ou, sem pedido, o quanto antes (2 min: tempo de guardar a imagem)."""
    minimo = agora + dt.timedelta(minutes=2)
    if quando and re.match(r"^\d{2}:\d{2}$", quando):
        h, m = map(int, quando.split(":"))
        alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
        return max(alvo if alvo >= agora else alvo + dt.timedelta(days=1), minimo)
    if quando in ("agora", "", None):        # foto dela: sai assim que ela aprovar
        return minimo
    t = (agora + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    for _ in range(48):
        if 8 <= t.hour <= 21 and all(abs((t - o).total_seconds()) > 40 * 60 for o in ocupados):
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


# ----------------------------------------------------------------- vídeo
def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def info_video(caminho):
    """Devolve (duração em segundos, tem_audio) lendo a saída do ffmpeg."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", caminho], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    return dur, "Audio:" in r.stderr


PARTE_MAX = 59          # o story de vídeo aceita até 60 s
PARTES_MAX = 5


def montar_video(original, opcoes, destinos_base):
    """Vídeo do celular -> 1080x1920 H.264, escurecido só se o texto precisar, com o texto e a logo por cima.
    Vídeo longo vira partes de até 59 s (no máximo 5). Devolve a lista de arquivos .mp4."""
    import arte_sobria
    dur, tem_audio = info_video(original)
    if dur <= 0:
        raise RuntimeError("não consegui ler esse vídeo")
    pasta = os.path.dirname(destinos_base)
    quadro = destinos_base + "-quadro.jpg"
    subprocess.run([ffmpeg(), "-y", "-ss", f"{dur / 2:.2f}", "-i", original, "-frames:v", "1", quadro],
                   capture_output=True, check=True)
    cam, k = arte_sobria.camada_video(quadro, opcoes)
    os.remove(quadro)
    camada = destinos_base + "-camada.png"
    cam.save(camada)
    n = min(PARTES_MAX, max(1, int((dur - 0.5) // PARTE_MAX) + 1))
    saidas = []
    for p in range(n):
        ini = p * PARTE_MAX
        out = destinos_base + (f"-parte{p + 1}" if n > 1 else "") + ".mp4"
        filtro = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
                  + (f",lutrgb=r=val*{k:.3f}:g=val*{k:.3f}:b=val*{k:.3f}" if k < 0.999 else "")
                  + "[v];[v][1:v]overlay=0:0,format=yuv420p[o]")
        cmd = [ffmpeg(), "-y", "-ss", str(ini), "-t", str(PARTE_MAX), "-i", original, "-loop", "1", "-i", camada]
        if not tem_audio:
            cmd += ["-f", "lavfi", "-t", str(PARTE_MAX), "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += ["-filter_complex", filtro, "-map", "[o]", "-map", "0:a" if tem_audio else "2:a",
                "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-maxrate", "3M",
                "-bufsize", "6M", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart", out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("o ffmpeg não conseguiu montar o vídeo: " + r.stderr[-300:])
        saidas.append(out)
    os.remove(camada)
    return saidas, dur


def _e_video(m):
    return bool(m.get("video") or (m.get("document") or {}).get("mime_type", "").startswith("video/"))


ULTIMA = {}        # a última foto mandada (para refazer a prévia se ela pedir correção)


def _e_foto(m):
    return bool(m.get("photo") or (m.get("document") or {}).get("mime_type", "").startswith("image/"))


def processar(msg, chat, _tg, agora=None, _baixar=None):
    """Recebe a mensagem do Telegram com foto (ou um álbum: lista de mensagens), cria o story e põe na
    fila já aprovado (foi ela quem mandou). Várias fotos juntas viram uma colagem de rotina."""
    import aprovacao
    import arte_sobria
    agora = agora or dt.datetime.now(P.fuso())
    msgs = msg if isinstance(msg, list) else [msg]
    legenda = next((m.get("caption") for m in msgs if m.get("caption")), "")
    pasta = os.path.join(P.PASTA_STORIES, agora.strftime("%Y-%m-%d"))
    os.makedirs(pasta, exist_ok=True)
    marca = agora.strftime("%H%M%S")
    videos = [m for m in msgs if _e_video(m)]
    if videos:
        return processar_video(videos[0], legenda, chat, _tg, agora, pasta, marca, _baixar)
    ids = []
    for m in msgs:
        if not _e_foto(m):
            continue
        fotos = m.get("photo") or []
        fid = fotos[-1]["file_id"] if fotos else (m.get("document") or {}).get("file_id")
        if fid:
            ids.append(fid)
    if not ids:
        return None
    originais = []
    for k, fid in enumerate(ids[:6]):
        o = os.path.join(pasta, f"enviada-{marca}-original-{k}.jpg")
        (_baixar or baixar_foto_telegram)(fid, o, _tg)
        originais.append(o)
    opcoes = interpretar(legenda, originais)
    usar = list(originais)
    if 0 <= opcoes.get("modelo_indice", -1) < len(usar) and len(usar) > 1:
        usar.pop(opcoes["modelo_indice"])     # a imagem de modelo só ensina o estilo; não entra no story
    nome = f"{agora:%Y-%m-%d}/enviada-{marca}.jpg"
    arte_sobria.desenhar_foto(usar[:5] if len(usar) > 1 else usar[0], opcoes, os.path.join(P.PASTA_STORIES, nome))
    for o in originais:
        os.remove(o)                          # os originais não ficam guardados no repositório
    quando = _programar([nome], opcoes.get("quando", ""), agora, status="aguardando")
    ULTIMA.clear()
    ULTIMA.update({"ids": ids[:6], "legenda": legenda, "arquivo": nome})
    tipo = "da colagem" if len(usar) > 1 else "do story"
    _tg("sendPhoto", {"chat_id": chat, "caption": f"Prévia {tipo}. " + _pedido_ok(quando, agora)},
        [("photo", os.path.join(P.PASTA_STORIES, nome))])
    return nome


def corrigir(pend, correcao, chat, _tg, agora=None, _baixar=None):
    """Ela respondeu à prévia com uma correção ("texto menor", "texto em cima", outro texto entre aspas...):
    baixa a foto de novo do Telegram, refaz o story com a correção e manda a prévia nova.
    Devolve o nome do arquivo novo (o antigo é apagado)."""
    import arte_sobria
    agora = agora or dt.datetime.now(P.fuso())
    pasta = os.path.join(P.PASTA_STORIES, agora.strftime("%Y-%m-%d"))
    os.makedirs(pasta, exist_ok=True)
    marca = agora.strftime("%H%M%S")
    originais = []
    for k, fid in enumerate(pend["ids"]):
        o = os.path.join(pasta, f"enviada-{marca}-original-{k}.jpg")
        (_baixar or baixar_foto_telegram)(fid, o, _tg)
        originais.append(o)
    antes = pend.get("correcoes", [])
    pedido = (f"CORREÇÃO NOVA (vale mais que tudo): {correcao}\n"
              + "".join(f"Correção anterior (continua valendo): {c}\n" for c in reversed(antes))
              + f"Pedido original: {pend.get('legenda') or '(nenhum)'}")
    opcoes = interpretar(pedido, originais)
    if not re.search(r'[“"]', correcao) and not opcoes.get("sem_texto"):
        orig = interpretar_simples(pend.get("legenda", ""))     # sem texto novo entre aspas: mantém o texto dela
        if orig.get("texto"):
            opcoes["texto"] = orig["texto"]
    usar = list(originais)
    if 0 <= opcoes.get("modelo_indice", -1) < len(usar) and len(usar) > 1:
        usar.pop(opcoes["modelo_indice"])
    nome = f"{agora:%Y-%m-%d}/enviada-{marca}.jpg"
    arte_sobria.desenhar_foto(usar[:5] if len(usar) > 1 else usar[0], opcoes, os.path.join(P.PASTA_STORIES, nome))
    for o in originais:
        os.remove(o)
    antigo = os.path.join(P.PASTA_STORIES, pend["arquivo"])
    if pend["arquivo"] != nome and os.path.exists(antigo):
        os.remove(antigo)
    _tg("sendPhoto", {"chat_id": chat, "caption": "Prévia corrigida. Responda OK para postar agora, "
                      "mande outra correção ou CANCELAR."}, [("photo", os.path.join(P.PASTA_STORIES, nome))])
    return nome, opcoes


def _pedido_ok(quando, agora):
    if quando - agora > dt.timedelta(minutes=10):
        return f"Responda OK para sair às {quando:%H:%M}, mande uma correção (ex.: texto em cima) ou CANCELAR."
    return "Responda OK para postar agora, mande uma correção (ex.: texto em cima) ou CANCELAR."


def _programar(nomes, quando_pedido, agora, status="aprovado"):
    import aprovacao
    campos, linhas = aprovacao.ler_linhas()
    ocupados = []
    for l in linhas:
        if l.get("status") not in ("aprovado", "aguardando"):
            continue
        try:
            ocupados.append(P._data_hora(l["data"], l["hora"]))
        except (ValueError, KeyError):
            pass
    quando = horario(quando_pedido, agora, ocupados)
    for nome in nomes:                       # partes de um vídeo longo saem em seguida, na mesma rodada
        linhas.append({"arquivo": nome, "data": quando.strftime("%Y-%m-%d"), "hora": quando.strftime("%H:%M"),
                       "status": status, "lote": "enviada"})
    aprovacao.gravar_linhas(campos or ["arquivo", "data", "hora", "status", "lote"], linhas)
    return quando


def processar_video(m, legenda, chat, _tg, agora, pasta, marca, _baixar=None):
    v = m.get("video") or m.get("document") or {}
    if v.get("file_size", 0) > LIMITE_TELEGRAM:
        _tg("sendMessage", {"chat_id": chat, "text":
            "Esse vídeo passa de 20 MB, e o Telegram não deixa o robô baixar. Mande de novo sem marcar "
            "\"enviar como arquivo\" (o Telegram comprime) ou mande um trecho mais curto."})
        return None
    original = os.path.join(pasta, f"enviada-{marca}-original.mp4")
    (_baixar or baixar_foto_telegram)(v["file_id"], original, _tg)
    quadro = os.path.join(pasta, f"enviada-{marca}-q.jpg")
    dur, _ = info_video(original)
    subprocess.run([ffmpeg(), "-y", "-ss", f"{dur / 2:.2f}", "-i", original, "-frames:v", "1", quadro], capture_output=True)
    opcoes = interpretar(legenda, quadro, video=True)
    os.remove(quadro)
    saidas, dur = montar_video(original, opcoes, os.path.join(pasta, f"enviada-{marca}"))
    os.remove(original)
    nomes = [os.path.relpath(s, P.PASTA_STORIES).replace(os.sep, "/") for s in saidas]
    quando = _programar(nomes, opcoes.get("quando", ""), agora, status="aguardando")
    partes = f" Vai em {len(nomes)} partes de até {PARTE_MAX} s." if len(nomes) > 1 else ""
    corte = " (Vídeo longo: usei só os primeiros 5 minutos.)" if dur > PARTE_MAX * PARTES_MAX else ""
    _tg("sendVideo", {"chat_id": chat, "caption": f"Prévia do vídeo.{partes}{corte} " + _pedido_ok(quando, agora)},
        [("video", saidas[0])])
    return nomes[0]
