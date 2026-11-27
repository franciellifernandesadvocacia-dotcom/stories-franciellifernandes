"""
Stories do dia a dia que vêm de coisas REAIS:

1. Relato de caso: a Dra. manda no Telegram uma mensagem começando com "CASO:" contando o que aconteceu
   (ex.: "CASO: chegou uma mãe com o BPC do filho negado por causa da renda; fomos à Justiça e saiu
   a sentença concedendo"). O Claude transforma em 2 a 4 stories com cara de rotina do escritório,
   sem nomes nem nada que identifique a pessoa, e o robô programa como um bloco.
   O robô NUNCA inventa caso: só escreve o que ela relatou.

2. Post novo no feed: quando sai um post no feed, o robô faz um story avisando, com o resumo do post
   (a figurinha de link/post não existe pela API; o story diz que o post completo está no perfil).
"""
import datetime as dt
import json
import os
import re
import urllib.request

import arte_natural as A
import publicar as P

PEDE_CASO = r"^\s*(caso|relato|hoje no escrit[oó]rio)\b\s*[:\-–]?"

ESQUEMA_CASO = {
    "type": "object",
    "properties": {
        "stories": {"type": "array", "items": {
            "type": "object",
            "properties": {"titulo": {"type": "string"}, "texto": {"type": "string"},
                           "comentario": {"type": "string"}, "fundo": {"type": "string"}},
            "required": ["titulo", "texto", "comentario", "fundo"], "additionalProperties": False}},
        "quando": {"type": "string"},
    },
    "required": ["stories", "quando"], "additionalProperties": False}

ESQUEMA_POST = {
    "type": "object",
    "properties": {"titulo": {"type": "string"}, "texto": {"type": "string"}},
    "required": ["titulo", "texto"], "additionalProperties": False}


def e_relato(texto):
    return bool(re.match(PEDE_CASO, (texto or "").lower()))


def _claude(pedido, esquema, imagem=None):
    import base64
    import gerar_dia as G
    conteudo = []
    if imagem:
        with open(imagem, "rb") as f:
            conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(f.read()).decode()}})
    conteudo.append({"type": "text", "text": pedido})
    resp = G._cliente().beta.messages.create(
        model=G.MODELO, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=G.REGRAS, output_config={"effort": "medium", "format": {"type": "json_schema", "schema": esquema}},
        messages=[{"role": "user", "content": conteudo}])
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError("o Claude não conseguiu escrever")
    return json.loads(G._texto(resp))


# ----------------------------------------------------------------- 1. relato de caso
def escrever_caso(relato):
    fundos = ", ".join(A.opcoes_de_fundo())
    pedido = f"""A Dra. mandou este relato REAL do escritório para virar stories de hoje:

\"\"\"{relato}\"\"\"

Transforme em 2 a 4 stories, em sequência, com cara de dia a dia do escritório (como ela contaria
no story, em primeira pessoa: "Hoje chegou aqui...", "Fomos à Justiça...").
- Use SÓ os fatos do relato. Não acrescente detalhe nenhum que ela não contou (nada de valores, datas,
  idades, cidades ou falas inventadas). Se faltar algo, simplesmente não diga.
- Sigilo: nenhum nome, apelido, profissão, bairro, idade exata ou detalhe que permita reconhecer a pessoa.
  Criança nunca identificável. Diga "uma mãe", "um segurado", "uma cliente".
- Conte: o que a pessoa buscava → por que o INSS negou (se ela disse) → o que foi feito → o resultado.
- O último story tira uma lição geral e informativa (ex.: "benefício negado nem sempre é a palavra final:
  vale entender o motivo"), sem prometer resultado a ninguém e sem chamar para contratar.
- titulo até 60 caracteres, texto até 170, comentario vazio (ou 1 frase curta só no último).
- "fundo": um destes: {fundos} (prefira notebook, sala, pinterest-trabalho, pinterest-justica).
- "quando": "agora", um horário "HH:MM" se ela pediu, ou "" (o robô escolhe)."""
    return _claude(pedido, ESQUEMA_CASO)


def processar_caso(texto, chat, _tg, agora=None, _escrever=None):
    import arte_sobria
    import foto_story as F
    agora = agora or dt.datetime.now(P.fuso())
    relato = re.sub(PEDE_CASO, "", texto, count=1, flags=re.I).strip()
    if len(relato) < 30:
        _tg("sendMessage", {"chat_id": chat, "text":
            "Me conta um pouco mais do caso (o que a pessoa buscava, por que foi negado e o que aconteceu) "
            "começando com CASO: que eu monto os stories."})
        return []
    dados = (_escrever or escrever_caso)(relato)
    marca = agora.strftime("%H%M%S")
    nomes = []
    for k, s in enumerate(dados["stories"][:4], start=1):
        nome = f"{agora:%Y-%m-%d}/caso-{marca}-parte{k}.jpg"
        story = {"tipo": "rotina", "rotulo": "NO ESCRITÓRIO" if k == 1 else "", "titulo": s["titulo"],
                 "texto": s["texto"], "comentario": s.get("comentario", ""), "fundo": s.get("fundo", ""),
                 "layout": ["base_esq", "topo_esq", "centro", "faixa"][k - 1]}
        arte_sobria.desenhar(story, os.path.join(P.PASTA_STORIES, nome))
        nomes.append(nome)
    quando = F._programar(nomes, dados.get("quando", ""), agora)
    for i in range(0, len(nomes), 10):
        _tg("sendMediaGroup", {"chat_id": chat, "media": json.dumps(
            [{"type": "photo", "media": f"attach://f{j}"} for j in range(len(nomes[i:i + 10]))])},
            [(f"f{j}", os.path.join(P.PASTA_STORIES, n)) for j, n in enumerate(nomes[i:i + 10])])
    _tg("sendMessage", {"chat_id": chat, "text":
        f"Caso programado para {quando:%d/%m às %H:%M} ({len(nomes)} stories, sem nomes). "
        "Confira se está tudo certo; para cancelar, responda CANCELAR."})
    return nomes


# ----------------------------------------------------------------- 2. post novo no feed
def posts_recentes(ig, limite=8):
    if not ig.user_id:
        ig.conta()
    r = ig._chamar("GET", f"{ig.user_id}/media", {
        "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,children{media_url,media_type}",
        "limit": limite})
    return r.get("data", [])


def _imagem_do_post(post):
    if post.get("media_type") == "CAROUSEL_ALBUM":
        for c in (post.get("children") or {}).get("data", []):
            if c.get("media_type") == "IMAGE" and c.get("media_url"):
                return c["media_url"]
    if post.get("media_type") == "VIDEO":
        return post.get("thumbnail_url")
    return post.get("media_url")


def resumir_post(legenda, imagem=None):
    pedido = (f"Saiu um post novo no feed do {A.PERFIL['handle']}. Legenda do post:\n\"\"\"{legenda or '(sem legenda)'}\"\"\"\n\n"
              "Escreva o story que avisa do post: titulo = o assunto do post em até 55 caracteres; texto = um "
              "resumo de até 170 caracteres que dê vontade de ver o post completo, com as palavras da legenda "
              "(não acrescente nenhuma regra ou informação que não esteja nela).")
    return _claude(pedido, ESQUEMA_POST, imagem)


def _baixar(url, destino):
    with urllib.request.urlopen(url, timeout=60) as r, open(destino, "wb") as f:
        f.write(r.read())
    return destino


def story_de_posts(ig, agora=None, _baixar_img=None, _resumir=None, _tg=None):
    """Confere o feed e cria um story para cada post novo (no máximo 2 por rodada)."""
    if not A.PERFIL.get("story_de_post") or os.environ.get("CONFERIR_FEED") == "0":
        return []
    import aprovacao
    import arte_sobria
    import foto_story as F
    agora = agora or dt.datetime.now(P.fuso())
    e = aprovacao.ler_estado()
    posts = posts_recentes(ig)
    if "posts_vistos" not in e:           # primeira vez: só anota o que já existe, sem criar nada
        e["posts_vistos"] = [p["id"] for p in posts]
        aprovacao.salvar_estado(e)
        return []
    novos = [p for p in posts if p["id"] not in e["posts_vistos"]][:2]
    nomes = []
    for p in reversed(novos):
        e["posts_vistos"] = (e["posts_vistos"] + [p["id"]])[-100:]
        url = _imagem_do_post(p)
        if not url:
            continue
        pasta = os.path.join(P.PASTA_STORIES, agora.strftime("%Y-%m-%d"))
        os.makedirs(pasta, exist_ok=True)
        orig = os.path.join(pasta, f"post-{p['id']}-original.jpg")
        (_baixar_img or _baixar)(url, orig)
        try:
            txt = (_resumir or resumir_post)(p.get("caption", ""), orig)
        except Exception as ex:      # sem Claude: usa o começo da legenda
            print("resumo do post sem Claude:", ex)
            leg = (p.get("caption") or "").strip().split("\n")[0]
            txt = {"titulo": "Post novo no feed", "texto": leg[:170]}
        nome = f"{agora:%Y-%m-%d}/post-{p['id']}.jpg"
        arte_sobria.desenhar_post(orig, txt, os.path.join(P.PASTA_STORIES, nome))
        os.remove(orig)
        F._programar([nome], "", agora + dt.timedelta(minutes=15))
        nomes.append(nome)
        if _tg or os.environ.get("TELEGRAM_BOT_TOKEN"):
            tk, chat = aprovacao._cfg()
            (_tg or aprovacao.telegram)("sendPhoto", {"chat_id": chat, "caption":
                "Vi o post novo no feed e fiz um story avisando. Para cancelar, responda CANCELAR."},
                [("photo", os.path.join(P.PASTA_STORIES, nome))])
    aprovacao.salvar_estado(e)
    return nomes
