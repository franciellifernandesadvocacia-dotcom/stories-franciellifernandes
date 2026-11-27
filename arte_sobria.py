"""Estilo sóbrio (perfil @franciellifernandes.adv): foto escurecida em preto, sombra preta suave e
texto branco numa serifada clássica e fina (Cormorant Garamond), centralizado, sem caixas.
Inspirado nos stories de frase com café: calmo, elegante, orgânico."""
import os
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

import arte_natural as A

W, H = A.W, A.H
BRANCO = (255, 255, 255)
CREME = (246, 236, 220)
DOURADO = (201, 164, 108)


FONTES_PADRAO = {   # papel: [arquivo, variação]; o perfil.json pode trocar ("fontes")
    "titulo": ["CormorantGaramond-Italic.ttf", "Medium Italic"],
    "texto": ["CormorantGaramond.ttf", "Medium"],
    "detalhe": ["CormorantGaramond-Italic.ttf", "Medium Italic"],
    "rotulo": ["CormorantGaramond.ttf", "SemiBold"],
}


def fonte(papel, tam):
    arq, var = A.PERFIL.get("fontes", {}).get(papel) or FONTES_PADRAO[papel]
    tam = tam * A.PERFIL.get("tamanhos", {}).get(papel, 1)
    f = ImageFont.truetype(os.path.join(A.AQUI, "fontes", arq), int(tam))
    if var:
        f.set_variation_by_name(var)
    return f


def serif(tam, peso="Medium", italico=False):
    """Compatibilidade: título/destaque em itálico, texto corrido e rótulos."""
    if italico:
        return fonte("titulo" if tam >= 70 else "detalhe", tam)
    return fonte("rotulo" if peso == "SemiBold" else "texto", tam)


def espacado(txt):
    return " ".join(txt.upper())


def foto_escura(nome, forca=0.6):
    """Foto em tela cheia só com a exposição diminuída (sem degradê, sem vinheta, cores originais)."""
    if nome and nome.startswith("cor:"):
        return Image.new("RGB", (W, H), (0, 0, 0))
    ft = ImageOps.exif_transpose(Image.open(A.escolher_foto(nome or ""))).convert("RGB")
    ft = ImageOps.fit(ft, (W, H), centering=(0.5, 0.4))
    return ImageEnhance.Brightness(ft).enhance(A.PERFIL.get("exposicao", forca))


def texto_com_sombra(img, linhas, y, f, cor=BRANCO, entre=1.18, sombra=0.75, alinh="c", x=90):
    """Escreve linhas com uma sombra preta difusa atrás (a 'sombra preta'). alinh: c (centro) ou l (esquerda)."""
    asc, desc = f.getmetrics()
    passo = int((asc + desc) * entre)
    pos = {"c": lambda: (W / 2, "ma"), "r": lambda: (W - x, "ra")}.get(alinh, lambda: (x, "la"))
    camada = Image.new("L", (W, H), 0)
    dc = ImageDraw.Draw(camada)
    for i, ln in enumerate(linhas):
        px, anc = pos()
        dc.text((px, y + i * passo), ln, font=f, fill=255, anchor=anc)
    sombra = sombra * A.PERFIL.get("sombra_texto", 1)     # 0 = sem sombra atrás das letras
    if sombra > 0:
        halo = camada.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(28))
        img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), halo.point(lambda v: int(v * sombra)))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(linhas):
        px, anc = pos()
        d.text((px, y + i * passo), ln, font=f, fill=cor, anchor=anc)
    return y + len(linhas) * passo


def faixas(img, linhas, y, f, cor=BRANCO, fundo=(0, 0, 0, 150), alinh="c", x=90):
    """Texto com o 'fundo' do Instagram: uma faixa escura arredondada atrás de cada linha."""
    asc, desc = f.getmetrics()
    alt = asc + desc
    cam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    for i, ln in enumerate(linhas):
        w = f.getlength(ln)
        x0 = (W - w) / 2 if alinh == "c" else (W - x - w if alinh == "r" else x)
        yy = y + i * (alt + 16)
        d.rounded_rectangle((x0 - 22, yy - 10, x0 + w + 22, yy + alt + 10), 16, fill=fundo)
        d.text((x0, yy), ln, font=f, fill=cor)
    img.paste(cam, (0, 0), cam)
    return y + len(linhas) * (alt + 16)


def marca(img, x=None, y=None):
    """Só a logo FF, pequena e discreta (sem o @ embaixo)."""
    logo = os.path.join(A.AQUI, "fontes", "simbolo-creme.png")
    if os.path.exists(logo):
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((58, 58))
        x = int(W / 2 - lg.width / 2) if x is None else x
        y = A.BASE_SEGURA - 40 - lg.height if y is None else y
        img.paste(lg, (x, y), lg)


def _dominio(link):
    import urllib.parse
    h = urllib.parse.urlparse(link or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def cartao_noticia(img, story, rot):
    """Notícia com cara de notícia: um cartão de matéria como link compartilhado, com o jornal no topo
    (nome e site), manchete, resumo e a linha de fonte embaixo."""
    cinza, preto = (110, 106, 102), (20, 19, 18)
    veic, _, data = (story.get("fonte") or "Notícia").partition("·")
    veic, data = veic.strip(), data.strip()
    site = _dominio(story.get("link"))
    f_veic, f_site = fonte("rotulo", 36), fonte("texto", 28)
    f_man, f_res, f_pe = fonte("titulo", 62), fonte("texto", 39), fonte("texto", 27)
    x0, x1, pad = 70, W - 70, 50
    larg = x1 - x0 - 2 * pad
    ml = A.quebrar(story["titulo"], f_man, larg)
    rl = A.quebrar(story["texto"], f_res, larg)
    topo = 124                                    # faixa escura com o nome do jornal
    alt = topo + 44 + len(ml) * 74 + 24 + len(rl) * 53 + 40 + 70
    y0 = max(A.TOPO_SEGURO + 90, (H - alt) // 2 - 60)
    sombra = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sombra).rounded_rectangle((x0, y0 + 14, x1, y0 + alt + 14), 28, fill=170)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sombra.filter(ImageFilter.GaussianBlur(24)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x1, y0 + alt), 28, fill=(255, 255, 255))
    d.rounded_rectangle((x0, y0, x1, y0 + topo), 28, fill=(28, 27, 26))
    d.rectangle((x0, y0 + topo - 30, x1, y0 + topo), fill=(28, 27, 26))
    d.text((x0 + pad, y0 + 30), veic.upper()[:34], font=f_veic, fill=(255, 255, 255))
    if site:
        d.text((x0 + pad, y0 + 78), site, font=f_site, fill=(190, 186, 180))
    if data:
        d.text((x1 - pad, y0 + 34), data, font=f_site, fill=(190, 186, 180), anchor="ra")
    y = y0 + topo + 44
    for ln in ml:
        d.text((x0 + pad, y), ln, font=f_man, fill=preto)
        y += 74
    y += 24
    for ln in rl:
        d.text((x0 + pad, y), ln, font=f_res, fill=(70, 68, 66))
        y += 53
    y += 24
    d.line([(x0 + pad, y), (x1 - pad, y)], fill=(225, 222, 218), width=2)
    pe = "Fonte: " + veic + (f" · {site}" if site else "") + (f" · {data}" if data else "")
    d.text((x0 + pad, y + 22), pe, font=f_pe, fill=cinza)
    # sempre deixa claro que é notícia; caso real e jurisprudência ganham a etiqueta ao lado
    f_nd = fonte("detalhe", 40)
    texto_com_sombra(img, ["Notícia do dia"], y0 - 86, f_nd, BRANCO, alinh="l", x=92)
    if rot and rot.upper() not in ("NOTÍCIA",):
        faixas(img, [rot.upper()], y0 - 80, fonte("rotulo", 28), BRANCO, (0, 0, 0, 170), alinh="l",
               x=92 + int(f_nd.getlength("Notícia do dia")) + 40)


def italico(texto, f, cor, largura):
    """Texto em itálico (inclina a fonte, como o itálico do Instagram)."""
    linhas = A.quebrar(texto, f, largura - 40)
    asc, desc = f.getmetrics()
    passo = int((asc + desc) * 1.3)
    cam = Image.new("RGBA", (largura + 60, passo * len(linhas) + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    for i, ln in enumerate(linhas):
        d.text((30, 10 + i * passo), ln, font=f, fill=cor)
    inc = 0.18
    return cam.transform(cam.size, Image.AFFINE, (1, inc, -inc * cam.height / 2, 0, 1, 0), Image.BICUBIC)


def bom_dia_cartao(img, story):
    """Bom dia no modelo 'cartão': máquina de escrever + cartão branco com o versículo + referência à direita
    + frase curta de fechamento."""
    texto, ref = story["texto"], ""
    if " — " in texto:
        texto, ref = texto.rsplit(" — ", 1)
    x0, larg = 250, 640
    bloco = italico("“" + texto + "”", fonte("texto", 42), (80, 78, 76), larg - 40)
    alt_card = bloco.height + 50
    y = int(H * 0.36)
    d = ImageDraw.Draw(img)
    d.text((x0, y), (story.get("titulo") or "bom dia").lower(), font=maquina(38), fill=BRANCO)
    y += 64
    d.rounded_rectangle((x0, y, x0 + larg, y + alt_card), 18, fill=(248, 248, 246))
    img.paste(bloco, (x0 + 4, y + 22), bloco)
    y += alt_card + 26
    if ref:
        f = maquina(32)
        for ln in A.quebrar(ref.lower() if ref[0].isalpha() and ref[:1].islower() else ref, f, larg):
            ImageDraw.Draw(img).text((x0 + larg, y), ln, font=f, fill=BRANCO, anchor="ra")
            y += 40
    fecho = story.get("comentario") or ""
    if fecho:
        f = maquina(36)
        yy = int(H * 0.68)
        for i, ln in enumerate(A.quebrar(fecho.lower(), f, 520)):
            ImageDraw.Draw(img).text((W / 2, yy + i * 44), ln, font=f, fill=BRANCO, anchor="ma")


LAYOUTS = ["base_esq", "diario", "topo_esq", "colagem", "centro", "faixa", "destaque"]


def maquina(tam):
    arq = A.PERFIL.get("fontes", {}).get("maquina", ["CourierPrime-Regular.ttf", None])[0]
    return ImageFont.truetype(os.path.join(A.AQUI, "fontes", arq), int(tam))


def grade(fotos, gap=8):
    """Colagem no estilo 'Layout' do Instagram: 1, 2, 3 (1+2), 4 (2+2) ou 5 (1+2+2) fotos."""
    n = max(1, min(5, len(fotos)))
    fileiras = {1: [1], 2: [1, 1], 3: [1, 2], 4: [2, 2], 5: [1, 2, 2]}[n]
    img = Image.new("RGB", (W, H), (0, 0, 0))
    alt = (H - gap * (len(fileiras) - 1)) // len(fileiras)
    i, y = 0, 0
    for cols in fileiras:
        larg = (W - gap * (cols - 1)) // cols
        for c in range(cols):
            ft = ImageOps.exif_transpose(Image.open(fotos[i])).convert("RGB")
            img.paste(ImageOps.fit(ft, (larg, alt), centering=(0.5, 0.42)), (c * (larg + gap), y))
            i += 1
        y += alt + gap
    return ImageEnhance.Brightness(img).enhance(min(1.0, A.PERFIL.get("exposicao", 0.6) + 0.2)), fileiras, alt


def texto_colagem(img, texto, fileiras, alt, gap=8):
    """Texto curtinho, minúsculo e simples, no último quadro (como no modelo de rotina)."""
    if not texto:
        return
    f = fonte("texto", 38)
    ultima_y = (len(fileiras) - 1) * (alt + gap)
    cols = fileiras[-1]
    x0 = W - (W - gap * (cols - 1)) // cols if cols > 1 else 0
    larg_q = W - x0
    linhas = A.quebrar(texto, f, larg_q - 80)
    cam = Image.new("RGBA", (larg_q, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    for k, ln in enumerate(linhas):
        d.text((larg_q / 2, 60 + k * 48), ln, font=f, fill=(255, 255, 255, 255), anchor="ma")
    sombra = cam.split()[3].filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.6))
    img.paste((0, 0, 0), (x0, ultima_y), sombra)
    img.paste(cam, (x0, ultima_y), cam)


def diario(img, story):
    """Modelo 'diário': máquina de escrever no alto à esquerda, barrinha, e frase em negrito centralizada."""
    f1, f2 = maquina(44), maquina(38)
    y = A.TOPO_SEGURO + 60
    y = texto_com_sombra(img, A.quebrar(story["titulo"], f1, 760), y, f1, BRANCO, entre=1.25, sombra=0.55, alinh="l", x=92)
    if story.get("texto"):                    # sem segundo texto, não desenha a barrinha
        d = ImageDraw.Draw(img)
        d.line([(96, y + 30), (96, y + 110)], fill=BRANCO, width=3)
        y = texto_com_sombra(img, A.quebrar(story["texto"], f2, 760), y + 150, f2, BRANCO, entre=1.3, sombra=0.55, alinh="l", x=92)
    frase = story.get("comentario") or story.get("rodape") or ""
    if frase:
        fb = fonte("titulo", 46)
        texto_com_sombra(img, A.quebrar(frase, fb, 760), max(y + 160, int(H * 0.6)), fb, BRANCO, entre=1.15, sombra=0.6)


def _layout(story, indice):
    if story.get("tipo") == "pessoal" and story.get("layout") not in LAYOUTS:
        return "diario" if indice % 2 else "base_esq"     # story pessoal: máquina de escrever ou texto solto
    if story.get("layout") in LAYOUTS:
        return story["layout"]
    return LAYOUTS[(indice + len(story.get("titulo", ""))) % len(LAYOUTS)]


CONTADOR = [0]


def desenhar(story, caminho):
    tipo = story.get("tipo", "dica")
    img = foto_escura(story.get("fundo", ""))
    CONTADOR[0] += 1
    rot = story.get("rotulo") or A.ROTULOS.get(tipo, "")
    tipos_noticia = ("noticia", "caso_real", "jurisprudencia")

    if tipo in tipos_noticia and not story.get("comentario"):
        cartao_noticia(img, story, rot)
    elif tipo == "bom_dia" and (story.get("layout") == "cartao" or (not story.get("layout") and A.PERFIL.get("bom_dia_cartao") and len(story.get("texto", "")) % 3 != 0)):
        bom_dia_cartao(img, story)
    elif tipo == "bom_dia":
        texto, ref = story["texto"], ""
        if " — " in texto:
            texto, ref = texto.rsplit(" — ", 1)
        f_bd, f_v = fonte("titulo", 74), fonte("texto", 54)
        texto_com_sombra(img, [story.get("titulo") or "Bom dia"], A.TOPO_SEGURO + 80, f_bd, BRANCO, alinh="l", x=92)
        vl = A.quebrar("“" + texto + "”", f_v, 860)
        y = int(H * 0.56 - len(vl) * 34)
        y = texto_com_sombra(img, vl, y, f_v, BRANCO)
        if ref:
            texto_com_sombra(img, [ref], y + 24, fonte("detalhe", 38), DOURADO, sombra=0.6)
    elif _layout(story, CONTADOR[0]) == "diario":
        diario(img, story)
    elif _layout(story, CONTADOR[0]) == "colagem":
        fotos = [A.escolher_foto(story.get("fundo", "")) for _ in range(5)]
        img, fil, alt = grade(fotos)
        texto_colagem(img, (story["titulo"] + " — " + story["texto"]).lower() if story.get("texto") else story["titulo"].lower(), fil, alt)
    else:
        lay = _layout(story, CONTADOR[0])
        f_t, f_c = fonte("titulo", 76), fonte("texto", 52)
        esq = lay in ("base_esq", "topo_esq", "destaque")
        largura = 880 if esq else 860
        tl = A.quebrar(story["titulo"], f_t if lay != "destaque" else fonte("titulo", 104), largura)
        cl = A.quebrar(story["texto"], f_c, largura)
        com = A.quebrar(story.get("comentario", ""), fonte("detalhe", 46), largura) if story.get("comentario") else []
        alt = (60 if rot else 0) + len(tl) * (124 if lay == "destaque" else 92) + 40 + len(cl) * 64 + (len(com) * 58 + 40 if com else 0) + (70 if story.get("rodape") else 0)
        if lay == "topo_esq":
            y = A.TOPO_SEGURO + 70
        elif lay == "base_esq":
            y = A.BASE_SEGURA - 150 - alt
        elif lay == "destaque":
            y = int(H * 0.36)
        else:
            y = int(H * 0.55 - alt / 2)
        al = "l" if esq else "c"
        if rot:
            texto_com_sombra(img, [rot], y, fonte("rotulo", 30), DOURADO, sombra=0.6, alinh=al, x=92)
            y += 60
        if lay == "faixa":
            y = faixas(img, tl, y, f_t, BRANCO, (0, 0, 0, 165)) + 24
            y = faixas(img, cl, y, f_c, BRANCO, (0, 0, 0, 140))
        else:
            ft_ = fonte("titulo", 104) if lay == "destaque" else f_t
            y = texto_com_sombra(img, tl, y, ft_, BRANCO, alinh=al, x=92) + 30
            y = texto_com_sombra(img, cl, y, f_c, BRANCO, alinh=al, x=92)
        if com:
            y = texto_com_sombra(img, com, y + 40, fonte("detalhe", 46), CREME, alinh=al, x=92)
        if story.get("rodape"):
            texto_com_sombra(img, [story["rodape"]], y + 40, fonte("detalhe", 38), DOURADO, sombra=0.6, alinh=al, x=92)

    marca(img)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    img.save(caminho, quality=88, optimize=True)
    return caminho


def desenhar_colagem(fotos, opcoes, destino):
    """Várias fotos mandadas juntas pela Dra. viram uma colagem de rotina."""
    img, fil, alt = grade(fotos)
    if not opcoes.get("sem_texto"):
        texto_colagem(img, (opcoes.get("texto") or "").strip(), fil, alt)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=88, optimize=True)
    return destino


# ----------------------------------------------------------------- fotos e vídeos mandados pela Dra.
TAMANHOS = {"pequeno": 46, "medio": 66, "grande": 96}


def _luz(img, caixa):
    """Brilho médio e variação (textura) de um pedaço da imagem."""
    x0, y0, x1, y1 = [int(v) for v in caixa]
    reg = img.crop((max(0, x0), max(0, y0), min(W, x1), min(H, y1))).convert("L")
    reg = reg.resize((64, max(1, int(64 * reg.height / max(1, reg.width)))))
    st = ImageStat.Stat(reg)
    return st.mean[0], st.stddev[0]


def melhor_y(img, alt, x0=60, x1=W - 60):
    """Procura a faixa da foto mais escura e mais lisa para o texto branco ficar visível."""
    cands = list(range(A.TOPO_SEGURO + 60, max(A.TOPO_SEGURO + 61, A.BASE_SEGURA - 140 - alt), 30))
    return min(cands, key=lambda y: sum(_luz(img, (x0, y, x1, y + alt))[k] * (1, 1.5)[k] for k in (0, 1)))


def fator_contraste(img, caixa, alvo=100, minimo=0.45):
    """Quanto escurecer a foto inteira (só exposição) para o texto branco aparecer bem."""
    m, _ = _luz(img, caixa)
    return 1.0 if m <= alvo else max(minimo, alvo / m)


def plano_texto(base, texto, o):
    """Decide fonte, linhas, posição e alinhamento do texto (seguindo as instruções ou o modelo dela)."""
    tam = TAMANHOS.get(o.get("tamanho") or "medio", 66)
    f = maquina(tam * 0.8) if o.get("fonte") == "maquina" else fonte("titulo", tam)
    if o.get("minusculas"):
        texto = texto.lower()
    caixa = o.get("caixa") or ("faixa" if o.get("faixa") else "nenhuma")
    larg = 760 if caixa == "cartao" else 860
    linhas = A.quebrar(texto, f, larg)
    asc, desc = f.getmetrics()
    passo = asc + desc + 16 if caixa == "faixa" else int((asc + desc) * 1.18)
    alt = len(linhas) * passo + (90 if caixa == "cartao" else 0)
    pos = o.get("posicao") or "auto"
    if pos == "auto":
        y = melhor_y(base, alt)
        pos = "topo" if y < H * 0.33 else ("base" if y > H * 0.55 else "meio")
    else:
        y = {"topo": A.TOPO_SEGURO + 80, "meio": int(H * 0.5 - alt / 2), "base": A.BASE_SEGURA - 180 - alt}.get(pos, int(H * 0.5 - alt / 2))
    al = {"esquerda": "l", "centro": "c", "direita": "r"}.get(o.get("alinhamento") or "", "c" if pos == "meio" else "l")
    return {"f": f, "linhas": linhas, "y": y, "alt": alt, "alinh": al, "caixa": caixa, "passo": passo}


def escrever(img, pl, sombra=0.75):
    """Desenha o texto planejado (em RGB ou numa camada transparente para vídeo)."""
    f, linhas, y, al = pl["f"], pl["linhas"], pl["y"], pl["alinh"]
    if pl["caixa"] == "faixa":
        faixas(img, linhas, y, f, BRANCO, (0, 0, 0, 160), alinh=al, x=92)
    elif pl["caixa"] == "cartao":
        larg = max(f.getlength(ln) for ln in linhas) + 90
        x0 = (W - larg) / 2 if al == "c" else (W - 92 - larg if al == "r" else 92)
        cam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(cam)
        d.rounded_rectangle((x0, y, x0 + larg, y + pl["alt"]), 22, fill=(248, 248, 246, 255))
        for i, ln in enumerate(linhas):
            d.text((x0 + 45, y + 45 + i * pl["passo"]), ln, font=f, fill=(45, 43, 41, 255))
        img.paste(cam, (0, 0), cam)
    else:
        texto_com_sombra(img, linhas, y, f, BRANCO, sombra=sombra, alinh=al, x=92)


def _caixa_texto(pl):
    return (60, pl["y"] - 20, W - 60, pl["y"] + pl["alt"] + 20)


def desenhar_foto(caminho_foto, opcoes, destino):
    """Story a partir de uma foto mandada pela Dra., com as instruções dela (posição, fonte, caixa, exposição...)."""
    if isinstance(caminho_foto, (list, tuple)):
        if len(caminho_foto) > 1:
            return desenhar_colagem(caminho_foto, opcoes, destino)
        caminho_foto = caminho_foto[0]
    ft = ImageOps.exif_transpose(Image.open(caminho_foto)).convert("RGB")
    ft = ImageOps.fit(ft, (W, H), centering=(0.5, 0.45))
    expo = opcoes.get("exposicao") or A.PERFIL.get("exposicao", 0.6)
    img = ImageEnhance.Brightness(ft).enhance(expo)
    texto = "" if opcoes.get("sem_texto") else (opcoes.get("texto") or "").strip()
    if texto:
        pl = plano_texto(img, texto, opcoes)
        if not opcoes.get("exposicao") and pl["caixa"] == "nenhuma":   # escurece mais só se precisar
            k = fator_contraste(img, _caixa_texto(pl))
            if k < 1:
                img = ImageEnhance.Brightness(img).enhance(k)
        escrever(img, pl, 0.75 if opcoes.get("sombra", True) else 0)
    marca(img)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=88, optimize=True)
    return destino


def camada_video(quadro, opcoes):
    """Para vídeo: devolve (camada transparente com texto e logo, fator de escurecimento do vídeo)."""
    base = ImageOps.fit(ImageOps.exif_transpose(Image.open(quadro)).convert("RGB"), (W, H))
    cam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    k = opcoes.get("exposicao") or 1.0
    texto = "" if opcoes.get("sem_texto") else (opcoes.get("texto") or "").strip()
    if texto:
        pl = plano_texto(ImageEnhance.Brightness(base).enhance(k), texto, opcoes)
        if not opcoes.get("exposicao") and pl["caixa"] == "nenhuma":
            k = fator_contraste(base, _caixa_texto(pl))
        escrever(cam, pl, 0.75 if opcoes.get("sombra", True) else 0)
    marca(cam)
    return cam, k


def desenhar_post(caminho_img, txt, destino):
    """Story que avisa do post novo: a arte do post em um cartão no meio, com o resumo embaixo."""
    fundo = ImageOps.fit(ImageOps.exif_transpose(Image.open(caminho_img)).convert("RGB"), (W, H))
    img = ImageEnhance.Brightness(fundo.filter(ImageFilter.GaussianBlur(40))).enhance(0.35)
    post = ImageOps.exif_transpose(Image.open(caminho_img)).convert("RGB")
    post.thumbnail((720, 720))
    x, y = (W - post.width) // 2, A.TOPO_SEGURO + 120
    sombra = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sombra).rounded_rectangle((x, y + 16, x + post.width, y + post.height + 16), 24, fill=180)
    img.paste((0, 0, 0), (0, 0), sombra.filter(ImageFilter.GaussianBlur(26)))
    masc = Image.new("L", post.size, 0)
    ImageDraw.Draw(masc).rounded_rectangle((0, 0, post.width, post.height), 24, fill=255)
    img.paste(post, (x, y), masc)
    yy = y - 80
    texto_com_sombra(img, ["post novo no feed"], yy, maquina(34), BRANCO, sombra=0, alinh="c")
    yy = y + post.height + 70
    f_t, f_c = fonte("titulo", 58), fonte("texto", 40)
    yy = texto_com_sombra(img, A.quebrar(txt.get("titulo", ""), f_t, 880), yy, f_t, BRANCO, sombra=0) + 18
    texto_com_sombra(img, A.quebrar(txt.get("texto", ""), f_c, 860), yy, f_c, CREME, sombra=0)
    texto_com_sombra(img, ["o post completo está no meu perfil"], A.BASE_SEGURA - 150, maquina(30), BRANCO, sombra=0)
    marca(img)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=88, optimize=True)
    return destino
