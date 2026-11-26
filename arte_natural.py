"""Desenha stories com cara de feitos no celular: foto de fundo ou cor lisa e texto em
'etiquetas' (o fundo arredondado atrás de cada linha, como o texto do próprio Instagram).
Só usa fontes livres (pasta fontes/) e fotos do Unsplash (pasta fundos/)."""
import json
import os
import random
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

AQUI = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
TOPO_SEGURO, BASE_SEGURA = 300, 1600   # o Instagram cobre o topo (barra/perfil) e a base (responder)

with open(os.path.join(AQUI, "perfil.json"), encoding="utf-8") as _f:
    PERFIL = json.load(_f)

CORES = {
    "papel": (231, 224, 213), "escuro": (22, 21, 21), "bordo": (117, 33, 51),
    "limao": (178, 176, 14), "oliva": (63, 75, 15), "rosa": (224, 116, 132), "creme": (246, 241, 233),
}
CORES.update({k: tuple(v) for k, v in PERFIL.get("paleta", {}).items()})
PASTAS_FOTOS = [os.path.join(AQUI, "fundos"), os.path.join(AQUI, "fotos")]   # fotos/ = fotos pessoais (cifradas no GitHub)


def _arquivos_de_fotos():
    achados = {}
    for pasta in PASTAS_FOTOS:
        if os.path.isdir(pasta):
            for f in os.listdir(pasta):
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    achados[os.path.splitext(f)[0]] = os.path.join(pasta, f)
    return achados


FUNDOS = sorted(_arquivos_de_fotos())
ROTULOS = PERFIL["tipos"]


def opcoes_de_fundo():
    """O que o Claude pode escolher em "fundo": categorias de foto (ex.: cafe) e cores lisas."""
    if PERFIL.get("categorias_fotos"):
        cats = list(PERFIL["categorias_fotos"])
    else:
        cats = FUNDOS
    return cats + ["cor:" + c for c in PERFIL.get("cores", [])]


USADAS = []   # nomes das fotos usadas recentemente (o gerador carrega do historico.json)


def escolher_foto(nome):
    """Escolhe uma foto da categoria pedida, dando preferência às que não foram usadas há mais tempo."""
    fotos = _arquivos_de_fotos()
    if nome in fotos:
        escolhida = nome
    else:
        candidatas = [n for n in fotos if n.startswith(nome + "-") or n.startswith(nome + "_")] or list(fotos)
        nunca = [n for n in candidatas if n not in USADAS]
        if nunca:
            escolhida = random.choice(nunca)
        else:                                   # todas já usadas: pega a usada há mais tempo
            escolhida = min(candidatas, key=lambda n: max(i for i, u in enumerate(USADAS) if u == n))
    USADAS.append(escolhida)
    return fotos[escolhida]


def fonte(tam, peso="Bold"):
    f = ImageFont.truetype(os.path.join(AQUI, "fontes", "Arimo.ttf"), int(tam))
    f.set_variation_by_name(peso)
    return f


def script(tam):
    return ImageFont.truetype(os.path.join(AQUI, "fontes", "PinyonScript.ttf"), int(tam))


def quebrar(texto, f, largura_max):
    linhas = []
    for par in texto.split("\n"):
        atual = ""
        for palavra in par.split():
            teste = (atual + " " + palavra).strip()
            if f.getlength(teste) <= largura_max or not atual:
                atual = teste
            else:
                linhas.append(atual)
                atual = palavra
        linhas.append(atual)
    return sem_viuva(linhas, f, largura_max)


def sem_viuva(linhas, f, largura_max):
    """Nunca deixa uma palavra sozinha na última linha: puxa a última palavra da linha de cima."""
    if len(linhas) >= 2 and len(linhas[-1].split()) == 1 and len(linhas[-2].split()) >= 3:
        cima = linhas[-2].split()
        nova = cima[-1] + " " + linhas[-1]
        if f.getlength(nova) <= largura_max:
            linhas[-2], linhas[-1] = " ".join(cima[:-1]), nova
    return linhas


def fundo(nome):
    if nome and nome.startswith("cor:"):
        cor = CORES.get(nome[4:], CORES["papel"])
        img = Image.new("RGB", (W, H), cor)
        ruido = Image.effect_noise((W, H), 18).convert("L").point(lambda v: 128 + (v - 128) // 6)
        return Image.blend(img, Image.merge("RGB", [ruido] * 3), 0.06), cor
    ft = ImageOps.exif_transpose(Image.open(escolher_foto(nome or ""))).convert("RGB")
    ft = ImageOps.fit(ft, (W, H), centering=(0.5, 0.5))
    ft = ImageEnhance.Brightness(ft).enhance(0.62)
    return ft, None


def etiquetas(d, linhas, y, f, cor_txt, cor_fundo, alinh="c", x=90, pad=(26, 14), raio=18, entre=0):
    """Texto com fundo arredondado em cada linha (estilo Instagram). Devolve o y final."""
    asc, desc = f.getmetrics()
    alt = asc + desc
    for ln in linhas:
        if not ln:
            y += alt * 0.5
            continue
        w = f.getlength(ln)
        x0 = (W - w) / 2 if alinh == "c" else x
        if cor_fundo:
            d.rounded_rectangle((x0 - pad[0], y - pad[1], x0 + w + pad[0], y + alt + pad[1]), raio, fill=cor_fundo)
        d.text((x0, y), ln, font=f, fill=cor_txt)
        y += alt + pad[1] * 2 + entre
    return y


def contraste(cor):
    r, g, b = cor
    return (22, 21, 21) if (r * 299 + g * 587 + b * 114) / 1000 > 140 else (246, 241, 233)


def desenhar(story, caminho):
    """story: dict com tipo, titulo, texto, fonte (opcional), fundo (nome da foto ou 'cor:xxx')."""
    if PERFIL.get("estilo") == "sobrio":
        import arte_sobria
        return arte_sobria.desenhar(story, caminho)
    tipo = story.get("tipo", "dica")
    img, cor_lisa = fundo(story.get("fundo", ""))
    d = ImageDraw.Draw(img)
    branco, escuro = (255, 255, 255), (22, 21, 21)

    if tipo == "bom_dia":
        f_s = script(190)
        d.text((W / 2, 560), story.get("titulo") or "Bom dia", font=f_s, fill=branco, anchor="ms")
        y = etiquetas(d, quebrar(story["texto"], fonte(46, "SemiBold"), 820), 680, fonte(46, "SemiBold"),
                      escuro, branco)
    elif tipo == "noticia":
        cor_card = (255, 255, 255)
        f_t, f_c = fonte(56, "Bold"), fonte(40, "Regular")
        tl = quebrar(story["titulo"], f_t, 800)
        cl = quebrar(story["texto"], f_c, 800)
        alt_card = 150 + len(tl) * 66 + 40 + len(cl) * 52 + 110
        y0 = max(TOPO_SEGURO + 80, (H - alt_card) // 2 - 60)
        d.rounded_rectangle((80, y0, W - 80, y0 + alt_card), 36, fill=cor_card)
        tag_cor = CORES["bordo"]
        d.rounded_rectangle((130, y0 + 50, 130 + fonte(30).getlength("NOTÍCIA") + 44, y0 + 104), 27, fill=tag_cor)
        d.text((152, y0 + 60), "NOTÍCIA", font=fonte(30), fill=branco)
        y = y0 + 150
        for ln in tl:
            d.text((130, y), ln, font=f_t, fill=escuro)
            y += 66
        y += 30
        for ln in cl:
            d.text((130, y), ln, font=f_c, fill=(60, 58, 56))
            y += 52
        if story.get("fonte"):
            d.text((130, y + 30), "Fonte: " + story["fonte"], font=fonte(30, "Regular"), fill=(130, 126, 120))
        if story.get("comentario"):
            etiquetas(d, quebrar(story["comentario"], fonte(42, "SemiBold"), 820), y0 + alt_card + 70,
                      fonte(42, "SemiBold"), escuro, CORES["limao"])
    else:
        rot = ROTULOS.get(tipo, "")
        cor_txt = contraste(cor_lisa) if cor_lisa else escuro
        fundo_etq = None if cor_lisa else branco
        f_t = fonte(68, "Bold")
        f_c = fonte(44, "Regular" if cor_lisa else "SemiBold")
        tl = quebrar(story["titulo"], f_t, 860)
        cl = quebrar(story["texto"], f_c, 840)
        alt_total = 90 + len(tl) * 100 + 50 + len(cl) * (72 if fundo_etq else 58)
        y = max(TOPO_SEGURO + 60, (H - alt_total) // 2 - 40)
        if rot:
            cor_rot = CORES["rosa"] if tipo in ("cnh_cassada", "lei_seca") else CORES["limao"]
            etiquetas(d, [rot], y, fonte(32), escuro, cor_rot, pad=(22, 10), raio=24)
            y += 110
        y = etiquetas(d, tl, y, f_t, cor_txt, fundo_etq, pad=(26, 12)) + 40
        if fundo_etq:
            etiquetas(d, cl, y, f_c, escuro, (255, 255, 255, 255), pad=(22, 10))
        else:
            for ln in cl:
                d.text((W / 2, y), ln, font=f_c, fill=cor_txt, anchor="ma")
                y += 58

    if story.get("rodape"):
        etiquetas(d, [story["rodape"]], BASE_SEGURA - 40, fonte(34, "SemiBold"), escuro, CORES["creme"], pad=(26, 14), raio=30)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    img.save(caminho, quality=86, optimize=True)
    return caminho
