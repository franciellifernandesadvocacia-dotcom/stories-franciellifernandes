"""
Publicador de stories do @dradasmultas.

Lê a fila (fila.csv), vê quais stories já chegaram no horário e ainda não
saíram, publica pelo Instagram Graph API e anota tudo em registro.csv.

Como usar:
  python publicar.py --teste                 confere a fila e as imagens, NÃO publica nada
  python publicar.py --teste --agora "2026-12-01 09:05"   simula outro dia/horário
  python publicar.py --verificar-token       só confere se o token funciona (não publica)
  python publicar.py                         publica o que estiver na hora (uso do servidor)
  python publicar.py --so-este ARQUIVO.jpg   publica só essa imagem, agora (1º teste)
  python publicar.py --renovar-token         renova o token do Instagram (60 dias)

Configuração (variáveis de ambiente; no GitHub ficam em Settings > Secrets):
  IG_TOKEN            token de acesso (obrigatório para publicar)
  IG_USER_ID          id da conta do Instagram (opcional: se vazio, descobre sozinho)
  API_HOST            graph.instagram.com (padrão) ou graph.facebook.com
  API_VERSAO          versão da API (padrão v24.0)
  URL_IMAGENS         endereço público da pasta stories/ (no GitHub é preenchido sozinho)
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   aviso opcional no Telegram quando der erro
"""
import argparse
import csv
import datetime as dt
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python antigo
    ZoneInfo = None

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_STORIES = os.path.join(AQUI, "stories")
FILA = os.path.join(AQUI, "fila.csv")
REGISTRO = os.path.join(AQUI, "registro.csv")
FUSO = os.environ.get("FUSO", "America/Cuiaba")
ATRASO_MAXIMO_HORAS = float(os.environ.get("ATRASO_MAXIMO_HORAS", "6"))
MAX_POR_RODADA = int(os.environ.get("MAX_POR_RODADA", "6"))   # um bloco inteiro sai na mesma rodada
TAM_MAX_BYTES = 8 * 1024 * 1024
CAMPOS_REGISTRO = ["quando", "arquivo", "agendado_para", "resultado", "id_instagram", "detalhe"]


class ErroAPI(Exception):
    pass


# ----------------------------------------------------------------- fila e registro
def fuso():
    return ZoneInfo(FUSO) if ZoneInfo else dt.timezone(dt.timedelta(hours=-4))


def ler_fila(caminho=None):
    """Cada linha: arquivo, data (AAAA-MM-DD ou DD/MM/AAAA), hora (HH:MM). Aceita ',' ou ';'."""
    with open(caminho or FILA, encoding="utf-8-sig", newline="") as f:
        texto = f.read()
    if not texto.strip():
        return [], ["a fila está vazia"]
    sep = ";" if texto.splitlines()[0].count(";") > texto.splitlines()[0].count(",") else ","
    itens, problemas = [], []
    for n, linha in enumerate(csv.DictReader(texto.splitlines(), delimiter=sep), start=2):
        linha = {(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()}
        if not any(linha.values()):
            continue
        arq, data, hora = linha.get("arquivo", ""), linha.get("data", ""), linha.get("hora", "")
        try:
            quando = _data_hora(data, hora)
        except ValueError:
            problemas.append(f"linha {n}: data/hora inválida ({data} {hora})")
            continue
        if not arq:
            problemas.append(f"linha {n}: falta o nome do arquivo")
            continue
        status = (linha.get("status") or "aprovado").lower()
        itens.append({"arquivo": arq, "quando": quando, "linha": n, "status": status})
    itens.sort(key=lambda i: i["quando"])
    return itens, problemas


def _data_hora(data, hora):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = dt.datetime.strptime(data, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(data)
    h = dt.datetime.strptime(hora or "09:00", "%H:%M")
    return d.replace(hour=h.hour, minute=h.minute, tzinfo=fuso())


def chave(item):
    return f'{item["arquivo"]}|{item["quando"].strftime("%Y-%m-%d %H:%M")}'


def ja_resolvidos(caminho=None):
    """Stories que já saíram (ou foram pulados por atraso) não são tentados de novo."""
    caminho = caminho or REGISTRO
    feitos = set()
    if not os.path.exists(caminho):
        return feitos
    with open(caminho, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("resultado") in ("publicado", "pulado-atrasado"):
                feitos.add(f'{r["arquivo"]}|{r["agendado_para"]}')
    return feitos


def anotar(resultado, arquivo, agendado, id_ig="", detalhe="", caminho=None):
    caminho = caminho or REGISTRO
    novo = not os.path.exists(caminho)
    with open(caminho, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_REGISTRO)
        if novo:
            w.writeheader()
        w.writerow({"quando": dt.datetime.now(fuso()).strftime("%Y-%m-%d %H:%M"), "arquivo": arquivo,
                    "agendado_para": agendado, "resultado": resultado, "id_instagram": id_ig,
                    "detalhe": detalhe[:300]})


def da_vez(itens, agora, feitos):
    """Separa o que deve sair agora e o que passou muito da hora (servidor ficou fora do ar)."""
    publicar, atrasados = [], []
    for it in itens:
        if chave(it) in feitos or it["quando"] > agora or it.get("status", "aprovado") != "aprovado":
            continue
        if agora - it["quando"] > dt.timedelta(hours=ATRASO_MAXIMO_HORAS):
            atrasados.append(it)
        else:
            publicar.append(it)
    return publicar[:MAX_POR_RODADA], atrasados


# ----------------------------------------------------------------- imagens
def tamanho_jpeg(caminho):
    """Lê largura x altura direto do arquivo JPEG (sem bibliotecas extras)."""
    with open(caminho, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            raise ValueError("não é JPEG (o Instagram só aceita .jpg pela API)")
        while True:
            b = f.read(1)
            while b and b != b"\xff":
                b = f.read(1)
            while b == b"\xff":
                b = f.read(1)
            if not b:
                raise ValueError("JPEG corrompido")
            marca = b[0]
            if marca in (0xD8, 0x01) or 0xD0 <= marca <= 0xD7:
                continue
            tam = struct.unpack(">H", f.read(2))[0]
            if 0xC0 <= marca <= 0xCF and marca not in (0xC4, 0xC8, 0xCC):
                f.read(1)
                h, w = struct.unpack(">HH", f.read(4))
                return w, h
            f.seek(tam - 2, 1)


def conferir_imagem(arquivo, pasta=None):
    """Devolve lista de problemas (vazia = tudo certo)."""
    p = os.path.join(pasta or PASTA_STORIES, arquivo)
    if not os.path.exists(p):
        return [f"{arquivo}: arquivo não está na pasta stories/"]
    probs = []
    if arquivo.lower().endswith(".mp4"):          # vídeo: o Instagram aceita até 100 MB e 60 s no story
        if os.path.getsize(p) > 100 * 1024 * 1024:
            probs.append(f"{arquivo}: vídeo maior que 100 MB")
        return probs
    if os.path.getsize(p) > TAM_MAX_BYTES:
        probs.append(f"{arquivo}: maior que 8 MB")
    try:
        w, h = tamanho_jpeg(p)
        if (w, h) != (1080, 1920):
            probs.append(f"{arquivo}: tem {w}x{h}, o ideal é 1080x1920")
    except ValueError as e:
        probs.append(f"{arquivo}: {e}")
    return probs


def url_da_imagem(arquivo):
    base = os.environ.get("URL_IMAGENS")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY")
        ramo = os.environ.get("GITHUB_REF_NAME", "main")
        if not repo:
            raise ErroAPI("URL_IMAGENS não configurada (endereço público da pasta stories/)")
        base = f"https://raw.githubusercontent.com/{repo}/{ramo}/stories"
    return base.rstrip("/") + "/" + urllib.parse.quote(arquivo)


# ----------------------------------------------------------------- Instagram
class Instagram:
    def __init__(self, token, user_id="", host=None, versao=None, http=None, espera=5.0):
        self.token = token
        self.host = host or os.environ.get("API_HOST", "graph.instagram.com")
        self.versao = versao or os.environ.get("API_VERSAO", "v24.0")
        self.user_id = user_id
        self._http = http or _http_real
        self.espera = espera

    def _chamar(self, metodo, caminho, params=None):
        params = dict(params or {}, access_token=self.token)
        url = f"https://{self.host}/{self.versao}/{caminho}"
        resp = self._http(metodo, url, params)
        if "error" in resp:
            e = resp["error"]
            raise ErroAPI(f'{e.get("message", "erro")} (código {e.get("code")}/{e.get("error_subcode", "-")})')
        return resp

    def conta(self):
        if "facebook" in self.host and not self.user_id and os.environ.get("PAGE_ID"):
            # descobre a conta do Instagram ligada à Página do Facebook
            pg = self._chamar("GET", os.environ["PAGE_ID"], {"fields": "instagram_business_account"})
            self.user_id = (pg.get("instagram_business_account") or {}).get("id", "")
        if "facebook" in self.host and not self.user_id:
            raise ErroAPI("com graph.facebook.com é preciso preencher IG_USER_ID (ou a variável PAGE_ID)")
        campos = "user_id,username" if "instagram" in self.host else "id,username"
        alvo = self.user_id if "facebook" in self.host else "me"
        r = self._chamar("GET", alvo, {"fields": campos})
        if not self.user_id:
            self.user_id = r.get("user_id") or r.get("id")
        return r

    def publicar_story(self, image_url):
        if not self.user_id:
            self.conta()
        video = image_url.lower().split("?")[0].endswith(".mp4")
        campo = "video_url" if video else "image_url"
        cont = self._chamar("POST", f"{self.user_id}/media", {campo: image_url, "media_type": "STORIES"})["id"]
        for _ in range(72 if video else 24):  # imagem: até ~2 min; vídeo: até ~6 min de processamento na Meta
            st = self._chamar("GET", cont, {"fields": "status_code"}).get("status_code")
            if st == "FINISHED":
                break
            if st in ("ERROR", "EXPIRED"):
                raise ErroAPI(f"a Meta não aceitou a imagem (status {st})")
            time.sleep(self.espera)
        else:
            raise ErroAPI("a Meta demorou demais para processar a imagem")
        return self._chamar("POST", f"{self.user_id}/media_publish", {"creation_id": cont})["id"]

    def renovar_token(self):
        """Só para token do 'Instagram Login' (vale 60 dias; renovar antes de vencer)."""
        url = "https://graph.instagram.com/refresh_access_token"
        r = self._http("GET", url, {"grant_type": "ig_refresh_token", "access_token": self.token})
        if "access_token" not in r:
            raise ErroAPI(f"não consegui renovar o token: {r}")
        return r["access_token"], int(r.get("expires_in", 0))


def _http_real(metodo, url, params):
    dados = urllib.parse.urlencode(params)
    if metodo == "GET":
        req = urllib.request.Request(url + "?" + dados)
    else:
        req = urllib.request.Request(url, data=dados.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except ValueError:
            return {"error": {"message": f"HTTP {e.code}", "code": e.code}}
    except urllib.error.URLError as e:
        return {"error": {"message": f"sem conexão: {e.reason}", "code": "rede"}}


# ----------------------------------------------------------------- avisos
def avisar(msg):
    print("AVISO:", msg)
    tk = "".join(os.environ.get("TELEGRAM_BOT_TOKEN", "").split())
    chat = "".join(os.environ.get("TELEGRAM_CHAT_ID", "").split())
    if tk and chat:
        try:
            _http_real("POST", f"https://api.telegram.org/bot{tk}/sendMessage",
                       {"chat_id": chat, "text": "Stories @dradasmultas: " + msg})
        except Exception as e:  # aviso nunca pode derrubar o resto
            print("não consegui avisar no Telegram:", e)


# ----------------------------------------------------------------- comandos
def modo_teste(agora):
    itens, probs = ler_fila()
    feitos = ja_resolvidos()
    print(f"Fila: {len(itens)} stories. Agora (simulado): {agora:%d/%m/%Y %H:%M} ({FUSO})")
    for it in itens:
        probs += conferir_imagem(it["arquivo"])
    agora_sai, atrasados = da_vez(itens, agora, feitos)
    print("\nSairia AGORA:", ", ".join(i["arquivo"] for i in agora_sai) or "nada")
    if atrasados:
        print("Seriam PULADOS por atraso:", ", ".join(i["arquivo"] for i in atrasados))
    esperando = [i["arquivo"] for i in itens if i.get("status") == "aguardando"]
    if esperando:
        print("Aguardando aprovação:", ", ".join(esperando))
    print("\nPróximos:")
    for it in [i for i in itens if i["quando"] > agora and chave(i) not in feitos][:10]:
        print(f'  {it["quando"]:%d/%m %H:%M}  {it["arquivo"]}')
    if probs:
        print("\nPROBLEMAS:")
        for p in probs:
            print("  -", p)
        return 1
    print("\nTudo certo com a fila e as imagens. Nada foi publicado (modo de teste).")
    return 0


def lembrar_aprovacao(itens, agora):
    """Se já passou a hora de um story que ainda aguarda aprovação, avisa uma vez por dia."""
    import aprovacao
    pendentes = [i for i in itens if i.get("status") == "aguardando" and i["quando"] <= agora]
    if not pendentes:
        return
    e = aprovacao.ler_estado()
    dia = agora.strftime("%Y-%m-%d")
    if e.get("lembrete") != dia:
        avisar(f"{len(pendentes)} story(s) de hoje ainda aguardam aprovação e não saíram. Responda OK no Telegram.")
        e["lembrete"] = dia
        aprovacao.salvar_estado(e)


def rodada(ig, agora):
    try:
        import aprovacao
        aprovacao.ler_respostas()
    except Exception as e:  # problema no Telegram não impede publicar o que já foi aprovado
        print("não consegui ler as respostas do Telegram:", e)
    try:
        import relato
        relato.story_de_posts(ig, agora)
    except Exception as e:  # conferir o feed nunca impede publicar
        print("não consegui conferir os posts do feed:", e)
    itens, probs = ler_fila()
    lembrar_aprovacao(itens, agora)
    for p in probs:
        avisar("fila com problema: " + p)
    feitos = ja_resolvidos()
    lote, atrasados = da_vez(itens, agora, feitos)
    for it in atrasados:
        ag = it["quando"].strftime("%Y-%m-%d %H:%M")
        anotar("pulado-atrasado", it["arquivo"], ag, detalhe=f"passou mais de {ATRASO_MAXIMO_HORAS:g}h da hora")
        avisar(f'{it["arquivo"]} (marcado para {ag}) não saiu a tempo e foi pulado.')
    erros = len(probs)
    if not lote:
        print("Nenhum story na hora agora.")
    for it in lote:
        ag = it["quando"].strftime("%Y-%m-%d %H:%M")
        problemas = conferir_imagem(it["arquivo"])
        if problemas:
            anotar("erro", it["arquivo"], ag, detalhe="; ".join(problemas))
            avisar("; ".join(problemas))
            erros += 1
            continue
        try:
            id_ig = ig.publicar_story(url_da_imagem(it["arquivo"]))
            anotar("publicado", it["arquivo"], ag, id_ig=id_ig)
            print(f'Publicado: {it["arquivo"]} (id {id_ig})')
        except ErroAPI as e:
            anotar("erro", it["arquivo"], ag, detalhe=str(e))
            avisar(f'erro ao publicar {it["arquivo"]}: {e}')
            erros += 1
    return 1 if erros else 0


def principal(argv=None):
    ap = argparse.ArgumentParser(description="Publica os stories do @dradasmultas")
    ap.add_argument("--teste", action="store_true", help="só confere, não publica")
    ap.add_argument("--agora", help='simula data/hora, ex.: "2026-12-01 09:05"')
    ap.add_argument("--verificar-token", action="store_true")
    ap.add_argument("--so-este", help="publica só este arquivo da pasta stories/, agora")
    ap.add_argument("--renovar-token", action="store_true")
    a = ap.parse_args(argv)

    agora = dt.datetime.now(fuso())
    if a.agora:
        agora = dt.datetime.strptime(a.agora, "%Y-%m-%d %H:%M").replace(tzinfo=fuso())
    if a.teste:
        return modo_teste(agora)

    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        normal = not (a.verificar_token or a.so_este or a.renovar_token)
        if normal and not da_vez(ler_fila()[0], agora, ja_resolvidos())[0]:
            print("IG_TOKEN ainda não configurado; nada para publicar agora.")
            return 0
        avisar("IG_TOKEN não configurado.")
        return 1
    ig = Instagram(token, os.environ.get("IG_USER_ID", "").strip())
    try:
        if a.verificar_token:
            c = ig.conta()
            print(f'Token OK. Conta: @{c.get("username")} (id {ig.user_id})')
            return 0
        if a.renovar_token:
            novo, seg = ig.renovar_token()
            with open(os.environ.get("ARQUIVO_TOKEN_NOVO", os.path.join(AQUI, ".token-novo")), "w") as f:
                f.write(novo)
            print(f"Token renovado, vale mais {seg // 86400} dias.")
            return 0
        if a.so_este:
            probs = conferir_imagem(a.so_este)
            if probs:
                print("\n".join(probs))
                return 1
            id_ig = ig.publicar_story(url_da_imagem(a.so_este))
            anotar("publicado", a.so_este, "manual", id_ig=id_ig, detalhe="publicação manual")
            print(f"Publicado: {a.so_este} (id {id_ig})")
            return 0
    except ErroAPI as e:
        avisar(str(e))
        return 1
    return rodada(ig, agora)


if __name__ == "__main__":
    sys.exit(principal())
