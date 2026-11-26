"""Estilo sóbrio (perfil @franciellifernandes.adv): foto escurecida em preto, sombra preta suave e
texto branco numa serifada clássica e fina (Cormorant Garamond), centralizado, sem caixas.
Inspirado nos stories de frase com café: calmo, elegante, orgânico."""
import os
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

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
    pos = (lambda: (W / 2, "ma")) if alinh == "c" else (lambda: (x, "la"))
    camada = Image.new("L", (W, H), 0)
    dc = ImageDraw.Draw(camada)
    for i, ln in enumerate(linhas):
        px, anc = pos()
        dc.text((px, y + i * passo), ln, font=f, fill=255, anchor=anc)
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
        x0 = (W - w) / 2 if alinh == "c" else x
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


def cartao_noticia(img, story, rot):
    """Notícia com cara de notícia: cartão branco de matéria, como um link compartilhado no story."""
    cinza, preto = (110, 106, 102), (20, 19, 18)
    f_fonte, f_man, f_res = fonte("rotulo", 30), fonte("titulo", 64), fonte("texto", 40)
    larg = 820
    ml = A.quebrar(story["titulo"], f_man, larg)
    rl = A.quebrar(story["texto"], f_res, larg)
    veic, _, data = (story.get("fonte") or "Notícia").partition("·")
    alt = 70 + 40 + len(ml) * 76 + 30 + len(rl) * 54 + 90
    y0 = max(A.TOPO_SEGURO + 90, (H - alt) // 2 - 80)
    sombra = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sombra).rounded_rectangle((70, y0 + 14, W - 70, y0 + alt + 14), 30, fill=170)
    img.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sombra.filter(ImageFilter.GaussianBlur(24)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((70, y0, W - 70, y0 + alt), 30, fill=(255, 255, 255))
    d.text((120, y0 + 50), espacado(veic.strip())[:40], font=f_fonte, fill=cinza)
    if data.strip():
        d.text((W - 120, y0 + 50), data.strip(), font=f_fonte, fill=cinza, anchor="ra")
    y = y0 + 120
    d.line([(120, y - 22), (W - 120, y - 22)], fill=(225, 222, 218), width=2)
    for ln in ml:
        d.text((120, y), ln, font=f_man, fill=preto)
        y += 76
    y += 26
    for ln in rl:
        d.text((120, y), ln, font=f_res, fill=(70, 68, 66))
        y += 54
    if rot and rot.upper() not in ("NOTÍCIA",):
        faixas(img, [rot.upper()], y0 - 80, fonte("rotulo", 32), BRANCO, (0, 0, 0, 170), alinh="l", x=92)
    else:
        texto_com_sombra(img, ["Notícia do dia"], y0 - 86, fonte("detalhe", 40), BRANCO, alinh="l", x=92)


LAYOUTS = ["base_esq", "topo_esq", "centro", "faixa", "destaque"]


def _layout(story, indice):
    if story.get("layout") in LAYOUTS:
        return story["layout"]
    return LAYOUTS[(indice + len(story.get("titulo", ""))) % len(LAYOUTS)]


CONTADOR = [0]


def desenhar(story, caminho):
    tipo = story.get("tipo", "dica")
    img = foto_escura(story.get("fundo", ""))
    CONTADOR[0] += 1
    rot = A.ROTULOS.get(tipo, "")
    tipos_noticia = ("noticia", "caso_real", "jurisprudencia")

    if tipo in tipos_noticia and not story.get("comentario"):
        cartao_noticia(img, story, rot)
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


def desenhar_foto(caminho_foto, opcoes, destino):
    """Story a partir de uma foto mandada pela Dra., com as instruções dela (sombra, exposição, posição...)."""
    ft = ImageOps.exif_transpose(Image.open(caminho_foto)).convert("RGB")
    ft = ImageOps.fit(ft, (W, H), centering=(0.5, 0.45))
    expo = opcoes.get("exposicao") or A.PERFIL.get("exposicao", 0.6)
    img = ImageEnhance.Brightness(ft).enhance(expo)
    texto = "" if opcoes.get("sem_texto") else (opcoes.get("texto") or "").strip()
    if texto:
        f = fonte("titulo", 70)
        linhas = A.quebrar(texto, f, 860)
        asc, desc = f.getmetrics()
        alt = len(linhas) * int((asc + desc) * 1.18)
        pos = opcoes.get("posicao", "auto")
        if pos == "auto":
            pos = ["base", "topo", "meio"][len(texto) % 3]
        y = {"topo": A.TOPO_SEGURO + 80, "meio": int(H * 0.5 - alt / 2), "base": A.BASE_SEGURA - 180 - alt}[pos]
        alinh = "c" if pos == "meio" else "l"
        if opcoes.get("faixa"):
            faixas(img, linhas, y, f, BRANCO, (0, 0, 0, 160), alinh=alinh, x=92)
        else:
            texto_com_sombra(img, linhas, y, f, BRANCO, sombra=0.75 if opcoes.get("sombra", True) else 0, alinh=alinh, x=92)
    marca(img)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, quality=88, optimize=True)
    return destino
