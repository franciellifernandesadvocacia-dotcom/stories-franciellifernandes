"""
Gera os stories de um dia: busca notícias recentes de trânsito na internet (Claude com busca na web),
escreve os textos seguindo a base de conhecimento e as regras da OAB, desenha as imagens e coloca
tudo na fila.csv como "aguardando" (ou "aprovado", se a aprovação for automática).

  python gerar_dia.py --para amanha            (uso do servidor, todo fim de tarde)
  python gerar_dia.py --para 2026-12-01 --exemplo   (sem Claude: usa textos de exemplo, para testar)

Configuração: ANTHROPIC_API_KEY, STORIES_POR_DIA (padrão 7), APROVACAO (obrigatoria | automatica),
MODELO (padrão claude-opus-5-5).
"""
import argparse
import csv
import datetime as dt
import json
import os
import shutil
import sys

import arte_natural
import publicar as P

AQUI = os.path.dirname(os.path.abspath(__file__))
HISTORICO = os.path.join(AQUI, "historico.json")
MODELO = os.environ.get("MODELO", "claude-opus-5-5")
DIAS_GUARDAR_IMAGENS = 21
PERFIL = arte_natural.PERFIL          # perfil.json: nome, temas, tipos, estilo e busca de notícias
TIPOS = list(PERFIL["tipos"])
TEMAS = PERFIL["temas"]

REGRAS = PERFIL["descricao"] + "\n\n" + PERFIL["tom"] + "\n\n" + PERFIL.get("regras_extra", "") + """

Regras que nunca podem ser quebradas (Código de Ética e Provimento 205/2021 da OAB):
- Conteúdo informativo. Nada de promessa ou garantia de resultado ("garantimos", "100%").
- Não falar de preço, desconto, "consulta grátis", nem pedir que contratem.
- Nada sensacionalista. Em notícia de acidente ou tragédia, nunca citar nome de vítima; tratar com respeito.
- Não dar conselho para caso concreto; falar em termos gerais.
- NUNCA inventar bastidores, reuniões, atendimentos, clientes, depoimentos ou histórias pessoais da Dra.
  (nada de "hoje atendi...", "uma cliente me contou..."). Bastidores reais só entram quando ela mesma manda.
- Regra jurídica (prazos, valores, requisitos, artigos) só pode ser afirmada se estiver na BASE DE
  CONHECIMENTO abaixo. Fato de notícia só pode vir da pesquisa de notícias. Na dúvida, não afirme.
- Resumir notícias com as próprias palavras (nunca copiar trechos) e sempre dizer o veículo.
- No máximo UM story do dia pode ter rodapé convidando: "dúvidas? manda no direct".
"""


def _cliente():
    import anthropic
    return anthropic.Anthropic()


def _texto(resp):
    return "\n".join(b.text for b in resp.content if b.type == "text")


def _urls_encontradas(conteudo):
    """Links que a busca realmente devolveu e links cujas matérias foram de fato abertas e lidas.
    Vem dos blocos de resultado da API, não do texto escrito pelo Claude (nunca link inventado)."""
    achadas, lidas = set(), set()
    for bloco in conteudo:
        tipo = getattr(bloco, "type", "")
        if tipo == "web_search_tool_result" and isinstance(bloco.content, list):
            for r in bloco.content:
                if getattr(r, "url", None):
                    achadas.add(r.url.rstrip("/"))
        elif tipo == "web_fetch_tool_result" and getattr(bloco.content, "type", "") == "web_fetch_result":
            lidas.add(bloco.content.url.rstrip("/"))
    return achadas, lidas


def pesquisar_noticias(cliente, hoje, ja_usadas):
    """Passo 1: o Claude busca notícias recentes de trânsito, ABRE E LÊ as matérias inteiras e resume.
    Devolve [{titulo, resumo, veiculo, data, link}] só com matérias que ele realmente leu."""
    pedido = (
        f"Hoje é {hoje:%d/%m/%Y}. Pesquise na web notícias publicadas nos últimos 3 dias (se houver "
        "poucas, nos últimos 7) " + PERFIL["busca"] + " Evite estas já usadas: " + ("; ".join(ja_usadas[-40:]) or "nenhuma") +
        ".\n\nEscolha as 3 melhores e ABRA CADA UMA com a ferramenta web_fetch para ler a matéria inteira. "
        "Não resuma notícia que você não abriu.\n\nNo final, liste as notícias lidas, uma por linha, "
        "exatamente neste formato:\n"
        "NOTICIA | título com suas palavras | resumo de 4 a 5 frases com suas palavras, só com fatos da "
        "matéria (o que aconteceu, onde, quando, números importantes, o que muda para o motorista), sem "
        "citar nomes de vítimas | veículo | dd/mm | link exato da matéria\n"
        "Se não achar nada confiável, escreva SEM NOTÍCIAS.")
    msgs = [{"role": "user", "content": pedido}]
    ferramentas = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6,
                    "user_location": {"type": "approximate", "country": "BR", "region": "Mato Grosso",
                                      "city": "Cuiabá", "timezone": "America/Cuiaba"}},
                   {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 4,
                    "max_content_tokens": 12000}]
    achadas, lidas = set(), set()
    for _ in range(6):  # retoma se o servidor pausar a busca/leitura (pause_turn)
        resp = cliente.beta.messages.create(
            model=MODELO, max_tokens=16000, betas=["server-side-fallback-2026-07-01"],
            fallbacks="default", output_config={"effort": "medium"}, tools=ferramentas, messages=msgs)
        a, l = _urls_encontradas(resp.content)
        achadas |= a
        lidas |= l
        if resp.stop_reason != "pause_turn":
            break
        msgs = [msgs[0], {"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        return []
    noticias = []
    for linha_ in _texto(resp).splitlines():
        partes = [x.strip() for x in linha_.split("|")]
        if len(partes) == 6 and partes[0].upper().startswith("NOTICIA"):
            link = partes[5].strip("<>() ")
            if link.rstrip("/") in lidas:          # só matéria que foi de fato aberta e lida
                noticias.append({"titulo": partes[1], "resumo": partes[2], "veiculo": partes[3],
                                 "data": partes[4], "link": link})
    return noticias


ESQUEMA = {
    "type": "object",
    "properties": {"stories": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": TIPOS},
            "titulo": {"type": "string"},
            "texto": {"type": "string"},
            "fonte": {"type": "string"},
            "comentario": {"type": "string"},
            "rodape": {"type": "string"},
            "fundo": {"type": "string"},
            "assunto": {"type": "string"},
            "noticia": {"type": "integer"},
            "bloco": {"type": "integer"},
        },
        "required": ["tipo", "titulo", "texto", "fonte", "comentario", "rodape", "fundo", "assunto", "noticia", "bloco"],
        "additionalProperties": False}},
        "tema_do_dia": {"type": "string", "enum": TEMAS}},
    "required": ["tema_do_dia", "stories"], "additionalProperties": False}


def escrever_stories(cliente, hoje, noticias, quantos, hist):
    """Passo 2: o Claude escreve a sequência do dia em formato estruturado (JSON garantido)."""
    with open(os.path.join(AQUI, "conhecimento.md"), encoding="utf-8") as f:
        base = f.read()
    fundos = ", ".join(arte_natural.opcoes_de_fundo())
    dia_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][hoje.weekday()]
    lista_noticias = "\n".join(f'{i}. {n["titulo"]} ({n["veiculo"]}, {n["data"]}): {n["resumo"]}'
                                for i, n in enumerate(noticias, start=1)) or "nenhuma notícia hoje"
    versos = ""
    if PERFIL.get("versiculos"):
        usados = hist.get("versiculos", [])[-15:]
        livres = [v for v in PERFIL["versiculos"] if v["ref"] not in usados] or PERFIL["versiculos"]
        versos = ("\nVERSÍCULO DO BOM DIA: no story 1, o texto é UM destes versículos, copiado exatamente como "
                  "está, seguido da referência entre travessões (ex.: \"... — Salmos 23:1\"). Não invente nem "
                  "altere versículos:\n" + "\n".join(f'- {v["texto"]} — {v["ref"]}' for v in livres) + "\n")
    pauta = PERFIL.get("pauta_semana", {}).get(dia_semana, "")
    if pauta:
        versos += f"\nPAUTA DE HOJE ({dia_semana}): {pauta}. Se a notícia escolhida for um caso real ou uma "\
                  "jurisprudência, os dois stories da notícia usam o tipo caso_real ou jurisprudencia.\n"
    pedido = f"""Escreva os {quantos} stories de {dia_semana}, {hoje:%d/%m/%Y}.

Eles são UMA SEQUÊNCIA que a pessoa assiste em ordem, como uma conversa com começo, meio e fim.
Cada story tem que fazer sentido depois do anterior e puxar o próximo.

1. Escolha o TEMA DO DIA entre: {", ".join(TEMAS)}. Prefira o que combina com a notícia escolhida
   e evite repetir os temas dos últimos dias: {", ".join(hist.get("temas", [])[-4:]) or "nenhum"}.
2. Story 1, tipo "bom_dia": {PERFIL["bom_dia"].replace("{dia}", dia_semana) if "titulo" in PERFIL["bom_dia"] else 'titulo "Bom dia" (ou "Boa ' + dia_semana + '"); ' + PERFIL["bom_dia"]}.
3. Stories 2 e 3, tipo "noticia": UMA notícia da lista abaixo, ligada ao tema, contada em
   DOIS stories seguidos (os dois com o mesmo número em "noticia" e a mesma "fonte" "Veículo · dd/mm"):
   - o primeiro conta o que aconteceu: titulo = manchete com suas palavras (até 70 caracteres);
     texto = resumo da matéria (até 220 caracteres); comentario vazio;
   - o segundo explica o que isso muda na vida das pessoas: titulo curto (ex.: "E o que isso muda pra
     você?"); texto até 200 caracteres; comentario = 1 frase que puxa o tema do dia (até 90).
   A pessoa não vai abrir link: o resumo tem que se bastar. Use só fatos do resumo da lista.
   Se não houver notícia adequada, faça um story "pergunta" que introduz o tema.
4. Stories do meio: desenvolvem o tema em passos lógicos (o que é → por que acontece → quanto tempo
   ou consequências → o que fazer), com tipo igual ao tema ({PERFIL["tipos_do_tema"]})
   ou "dica"/"pergunta". Use ganchos de ligação no começo do título ou
   do texto ("E se...?", "Agora, a parte que pouca gente sabe:", "Resumindo:").
5. Último story: fecha a conversa com um resumo curto e rodape "dúvidas? manda no direct".
   Só o último tem rodape; nos outros, rodape vazio.
Limites: titulo até 60 caracteres e texto até 170 (exceto bom_dia e notícia, acima).
"fonte" vazio e "noticia" = 0 quando não for notícia; "comentario" vazio quando não for notícia, exceto no
bom_dia se as instruções do bom_dia pedirem uma frase de fechamento.
"fundo": escolha um destes: {fundos} ({PERFIL["fundos_dica"]}).
"bloco": os stories saem ao longo do dia em BLOCOS; os do mesmo bloco saem juntos, um atrás do outro.
Ponha no mesmo bloco o que só faz sentido visto junto: os dois stories da notícia (manchete + o que muda)
ficam SEMPRE no mesmo bloco; uma pergunta fica no bloco da resposta; os passos de uma mesma explicação
ficam juntos. O bom_dia é sozinho no bloco 1. Numere os blocos em ordem (1, 2, 3...), de 1 a 3 stories
por bloco, entre 3 e 5 blocos no dia.
"assunto": 3 a 6 palavras resumindo cada story. Não repita estes assuntos recentes:
{"; ".join(hist.get("assuntos", [])[-40:]) or "nenhum"}.

{versos}
NOTÍCIAS PESQUISADAS HOJE:
{lista_noticias}

BASE DE CONHECIMENTO:
{base}"""
    resp = cliente.beta.messages.create(
        model=MODELO, max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=REGRAS, output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
        messages=[{"role": "user", "content": pedido}])
    if resp.stop_reason == "refusal":
        raise RuntimeError("o Claude recusou o pedido de hoje")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("a resposta do Claude veio cortada")
    dados = json.loads(_texto(resp))
    for st in dados["stories"]:        # o link vem da busca real, nunca do texto escrito pelo Claude
        n = st.get("noticia") or 0
        st["link"] = noticias[n - 1]["link"] if st["tipo"] == "noticia" and 1 <= n <= len(noticias) else ""
        # o link não aparece no story; fica só no Telegram (para conferência) e no histórico
        if st["tipo"] in ("caso_real", "jurisprudencia") and 1 <= n <= len(noticias):
            st["link"] = noticias[n - 1]["link"]
        if st["tipo"] == "noticia" and not st["link"]:
            st["tipo"] = "pergunta"
    return dados["tema_do_dia"], dados["stories"]


EXEMPLO_TEMA = "CNH suspensa"
EXEMPLO = [  # sequência de exemplo (modo --exemplo, sem Claude): um tema do começo ao fim
    {"tipo": "bom_dia", "titulo": "Bom dia", "texto": "Hoje o papo é sobre uma dúvida que chega muito aqui: o que acontece quando a CNH é suspensa?", "fundo": "cafe"},
    {"tipo": "noticia", "titulo": "(EXEMPLO) Detran amplia fiscalização no fim de semana", "texto": "Notícia de exemplo, só para testar o robô sem chamar o Claude. Aqui entra o resumo da matéria lida pelo robô: o que aconteceu, onde e quando.", "fonte": "Exemplo · 01/12", "fundo": "cor:papel", "link": "https://example.com/noticia"},
    {"tipo": "noticia", "titulo": "E o que isso muda pra você?", "texto": "Aqui entra a explicação do que a notícia muda para quem dirige, também com base na matéria.", "fonte": "Exemplo · 01/12", "comentario": "E fiscalização maior costuma significar mais processos de suspensão.", "fundo": "cor:escuro", "link": "https://example.com/noticia"},
    {"tipo": "cnh_suspensa", "titulo": "Primeiro: suspensa não é perdida", "texto": "Você fica um tempo sem poder dirigir, faz a reciclagem e volta. Quem perde a CNH é quem tem ela cassada.", "fundo": "carro-por-dentro"},
    {"tipo": "cnh_suspensa", "titulo": "E por que ela é suspensa?", "texto": "Por pontos (20, 30 ou 40 em 12 meses, conforme as gravíssimas) ou por uma infração só, como Lei Seca ou racha.", "fundo": "cor:escuro"},
    {"tipo": "cnh_cassada", "titulo": "Agora, o cuidado que muita gente não tem:", "texto": "Dirigir com a CNH suspensa leva à cassação. Aí são 2 anos de espera e habilitação do zero.", "fundo": "cor:bordo"},
    {"tipo": "dica", "titulo": "Resumindo", "texto": "Antes de qualquer suspensão existe processo e prazo de defesa. Por isso, notificação nunca se ignora.", "fundo": "cor:limao", "rodape": "dúvidas? manda no direct"},
]


if PERFIL.get("exemplo"):
    EXEMPLO_TEMA, EXEMPLO = PERFIL["exemplo"]["tema"], PERFIL["exemplo"]["stories"]


PRIMEIRO_STORY = os.environ.get("PRIMEIRO_STORY", "08:00")   # o dia começa às 8h
ULTIMO_BLOCO = os.environ.get("ULTIMO_BLOCO", "12:00")   # stories entre 8h e meio-dia


def _min(h):
    return int(h[:2]) * 60 + int(h[3:5])


def blocos(stories):
    """Agrupa os stories que precisam sair juntos. Usa o "bloco" que o Claude escolheu; sem ele (exemplo),
    junta os dois stories da mesma notícia e a pergunta com a resposta."""
    if stories and all(isinstance(s.get("bloco"), int) and s["bloco"] > 0 for s in stories):
        grupos = []
        for s_ in stories:
            if grupos and grupos[-1][-1].get("bloco") == s_["bloco"] and len(grupos[-1]) < 4:
                grupos[-1].append(s_)
            else:
                grupos.append([s_])
        return grupos
    grupos = []
    for k, s_ in enumerate(stories):
        ant = stories[k - 1] if k else None
        junto = ant is not None and grupos and len(grupos[-1]) < 3 and (
            (s_.get("tipo") in ("noticia", "caso_real", "jurisprudencia") and ant.get("tipo") == s_.get("tipo"))
            or ant.get("tipo") == "pergunta")
        if junto:
            grupos[-1].append(s_)
        else:
            grupos.append([s_])
    return grupos


def horarios(n, stories=None):
    """Primeiro story às 8h; os blocos se espalham até as 20h e, dentro do bloco, saem um atrás do outro
    (1 minuto de diferença, para a ordem ficar certa)."""
    grupos = blocos(stories) if stories else [[None]] * n
    ini, fim = _min(PRIMEIRO_STORY), _min(ULTIMO_BLOCO)
    passo = (fim - ini) // max(1, len(grupos) - 1) if len(grupos) > 1 else 0
    passo -= passo % 10
    saida = []
    for g, grupo in enumerate(grupos):
        base = ini + g * passo
        for k in range(len(grupo)):
            m = base + k
            saida.append(f"{m // 60:02d}:{m % 60:02d}")
    return saida[:n]


def ler_historico():
    if os.path.exists(HISTORICO):
        with open(HISTORICO, encoding="utf-8") as f:
            return json.load(f)
    return {"noticias": [], "assuntos": [], "dias": [], "temas": [], "links": []}


def acrescentar_fila(linhas):
    """Garante as colunas status/lote e acrescenta as linhas novas na fila.csv."""
    campos = ["arquivo", "data", "hora", "status", "lote"]
    antigas = []
    if os.path.exists(P.FILA):
        with open(P.FILA, encoding="utf-8-sig", newline="") as f:
            antigas = [{k: (r.get(k) or "") for k in campos} for r in csv.DictReader(f)]
    with open(P.FILA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(antigas + linhas)


def limpar_antigos(hoje):
    pasta = P.PASTA_STORIES
    for nome in os.listdir(pasta):
        try:
            dia = dt.date.fromisoformat(nome)
        except ValueError:
            continue
        if (hoje - dia).days > DIAS_GUARDAR_IMAGENS:
            shutil.rmtree(os.path.join(pasta, nome), ignore_errors=True)


def pagina_noticias(links, caminho=None):
    """Página simples com os links das notícias (para colocar na bio). Publicada pelo GitHub Pages."""
    import html
    caminho = caminho or os.path.join(AQUI, "docs", "index.html")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    itens = "\n".join(
        f'<li><span>{html.escape(n["dia"][8:10])}/{html.escape(n["dia"][5:7])} · {html.escape(n["fonte"])}</span>'
        f'<a href="{html.escape(n["link"], quote=True)}" rel="noopener" target="_blank">{html.escape(n["titulo"])}</a></li>'
        for n in reversed(links[-30:]))
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Notícias dos stories · Doutora das Multas</title>
<style>body{{margin:0;background:#e7e0d5;color:#161515;font:17px/1.45 -apple-system,Helvetica,Arial,sans-serif}}
main{{max-width:560px;margin:auto;padding:32px 20px}}h1{{color:#752133;font-size:26px;margin:0 0 4px}}
p{{margin:0 0 24px;color:#555}}ul{{list-style:none;padding:0;margin:0}}li{{background:#fff;border-radius:14px;padding:14px 16px;margin:0 0 12px}}
span{{display:block;font-size:13px;color:#777;margin-bottom:4px}}a{{color:#161515;font-weight:600;text-decoration:none}}</style></head>
<body><main><h1>Notícias dos stories</h1><p>@dradasmultas · os links das notícias comentadas nos stories, da mais nova para a mais antiga.</p>
<ul>
{itens}
</ul></main></body></html>
""")


def gerar_exemplo():
    """Teste grátis: desenha a sequência de exemplo em stories/exemplo/. Não entra na fila,
    não marca o dia como gerado e nunca é publicado."""
    pasta = os.path.join(P.PASTA_STORIES, "exemplo")
    shutil.rmtree(pasta, ignore_errors=True)
    for i, (s, hora) in enumerate(zip(EXEMPLO, horarios(len(EXEMPLO), EXEMPLO)), start=1):
        arte_natural.desenhar(s, os.path.join(pasta, f"{i:02d}-{s['tipo'].replace('_', '-')}.jpg"))
        print(f"{hora}  exemplo/{i:02d}  {s['titulo']}")
    with open(os.path.join(pasta, "textos.json"), "w", encoding="utf-8") as f:
        json.dump({"tema": EXEMPLO_TEMA, "stories": EXEMPLO}, f, ensure_ascii=False, indent=1)
    _saida_github("exemplo")
    return 0


def _saida_github(lote):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"lote={lote}\n")


def gerar(dia, exemplo=False):
    import aprovacao
    if aprovacao.ler_estado().get("modo") == "so_fotos":
        print("Modo SÓ FOTOS ligado pelo Telegram: não gero a sequência automática.")
        return 0
    hist = ler_historico()
    for k in ("temas", "links"):
        hist.setdefault(k, [])
    if dia.isoformat() in hist["dias"]:
        print(f"Os stories de {dia:%d/%m} já foram gerados.")
        _saida_github(dia.isoformat())
        return 0
    quantos = max(1, min(10, int(os.environ.get("STORIES_POR_DIA", "7"))))
    if exemplo:
        tema, stories = EXEMPLO_TEMA, [dict(s) for s in EXEMPLO[:quantos]]
    else:
        cli = _cliente()
        noticias = pesquisar_noticias(cli, dia, hist["noticias"])
        tema, stories = escrever_stories(cli, dia, noticias, quantos, hist)
        stories = stories[:quantos]
    print(f"Tema do dia: {tema}")
    arte_natural.USADAS[:] = hist.get("fotos", [])
    status = "aprovado" if os.environ.get("APROVACAO", "obrigatoria") == "automatica" else "aguardando"
    linhas = []
    for i, (s, hora) in enumerate(zip(stories, horarios(len(stories), stories)), start=1):
        arq = f"{dia.isoformat()}/{i:02d}-{s['tipo'].replace('_', '-')}.jpg"
        arte_natural.desenhar(s, os.path.join(P.PASTA_STORIES, arq))
        linhas.append({"arquivo": arq, "data": dia.isoformat(), "hora": hora, "status": status, "lote": dia.isoformat()})
        if s.get("assunto"):
            hist["assuntos"].append(s["assunto"])
        if s["tipo"] in ("noticia", "caso_real", "jurisprudencia") and s.get("link") and s["link"] not in [x["link"] for x in hist["links"]]:
            hist["noticias"].append(s["titulo"])
            hist["links"].append({"dia": dia.isoformat(), "titulo": s["titulo"], "fonte": s.get("fonte", ""), "link": s["link"]})
        print(f"{hora}  {arq}  {s['titulo']}" + (f"  [{s['link']}]" if s.get("link") else ""))
    with open(os.path.join(P.PASTA_STORIES, dia.isoformat(), "textos.json"), "w", encoding="utf-8") as f:
        json.dump({"tema": tema, "stories": stories}, f, ensure_ascii=False, indent=1)
    acrescentar_fila(linhas)
    hist["dias"].append(dia.isoformat())
    hist["temas"].append(tema)
    hist["fotos"] = arte_natural.USADAS[-200:]
    for v in PERFIL.get("versiculos", []):
        if stories and v["ref"] in stories[0].get("texto", ""):
            hist.setdefault("versiculos", []).append(v["ref"])
    hist = {k: (v[-200:] if k == "fotos" else v[-120:]) for k, v in hist.items()}
    with open(HISTORICO, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    pagina_noticias(hist["links"], os.path.join(os.path.dirname(HISTORICO), "docs", "index.html"))
    limpar_antigos(dia)
    _saida_github(dia.isoformat())
    return 0


def principal(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--para", default="amanha", help='"hoje", "amanha" ou AAAA-MM-DD')
    ap.add_argument("--exemplo", action="store_true", help="não chama o Claude; usa textos de exemplo")
    a = ap.parse_args(argv)
    hoje = dt.datetime.now(P.fuso()).date()
    dia = {"hoje": hoje, "amanha": hoje + dt.timedelta(days=1)}.get(a.para) or dt.date.fromisoformat(a.para)
    try:
        return gerar_exemplo() if a.exemplo else gerar(dia)
    except Exception as e:  # qualquer falha vira aviso (e-mail do GitHub + Telegram)
        P.avisar(f"não consegui gerar os stories de {dia:%d/%m}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(principal())
