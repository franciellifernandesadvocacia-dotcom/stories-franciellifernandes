"""
Robô em corrente: não depende do relógio do GitHub (que atrasa ou nem dispara).

Cada rodada fica acordada até ~5h20 dentro do GitHub Actions:
  - na hora exata de cada story, publica (roda o publicar.py normal);
  - durante o dia, fica escutando o Telegram e acorda assim que ela manda algo (fotos, CASO, NÃO 3...);
  - às 19h, se amanhã ainda não tem stories, aciona a geração;
  - antes de acabar o tempo, o workflow aciona a próxima rodada (passa a vez).

  python corrente.py               roda a corrente
  python corrente.py --planejar    só mostra quando acordaria (não publica nada)
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

import publicar as P

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO_CORRENTE = os.path.join(AQUI, "corrente.json")
LIMITE_S = float(os.environ.get("CORRENTE_HORAS", "5.3")) * 3600
HORA_GERAR = 19
DIA_INI, DIA_FIM = 7, 22          # entre 7h e 22h fica escutando o Telegram
PASSO_DIA = dt.timedelta(minutes=2)     # confere o feed a cada 2 min; mensagem dela acorda na hora (esperar)
PASSO_NOITE = dt.timedelta(minutes=30)
ARQUIVOS = ("registro.csv", "fila.csv", "estado.json", "stories", "corrente.json")


def agora():
    return dt.datetime.now(P.fuso())


def _git(*args):
    return subprocess.run(["git", *args], cwd=AQUI, capture_output=True, text=True)


def sincronizar():
    """Traz o que mudou no GitHub (fila nova, código novo) antes de cada rodada."""
    r = _git("pull", "--rebase", "--autostash", "-q")
    if r.returncode:
        print("aviso: não consegui atualizar do GitHub:", r.stderr.strip()[:300])
        _git("rebase", "--abort")


def salvar(msg):
    caminhos = [c for c in ARQUIVOS if os.path.exists(os.path.join(AQUI, c))]
    if not _git("status", "--porcelain", *caminhos).stdout.strip():
        return
    _git("add", "-A", *caminhos)
    _git("commit", "-q", "-m", msg)
    for _ in range(4):
        if _git("push", "-q").returncode == 0:
            return
        r = _git("pull", "--rebase", "-X", "theirs", "-q")
        if r.returncode:
            _git("rebase", "--abort")
        time.sleep(5)
    print("aviso: não consegui salvar no GitHub depois de 4 tentativas")


def ler_corrente():
    if os.path.exists(ESTADO_CORRENTE):
        with open(ESTADO_CORRENTE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def gravar_corrente(d):
    with open(ESTADO_CORRENTE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def tem_amanha(hoje):
    amanha = (hoje + dt.timedelta(days=1)).isoformat()
    try:
        itens, _ = P.ler_fila()
    except FileNotFoundError:
        return False
    return any(i["quando"].date().isoformat() == amanha for i in itens)


def talvez_gerar(t, acionar):
    """Às 19h aciona a geração de amanhã; se em 1h ainda não chegou, tenta mais uma vez (no máximo 2)."""
    if not (HORA_GERAR <= t.hour < 23) or tem_amanha(t.date()):
        return False
    c = ler_corrente()
    pedidos = [p for p in c.get("gerar_pedidos", []) if p.startswith(t.date().isoformat())]
    if len(pedidos) >= 2:
        return False
    if pedidos and t - dt.datetime.fromisoformat(pedidos[-1]) < dt.timedelta(minutes=60):
        return False
    if not acionar():
        return False
    c["gerar_pedidos"] = (c.get("gerar_pedidos", []) + [t.isoformat(timespec="minutes")])[-6:]
    gravar_corrente(c)
    return True


def acionar_geracao():
    r = subprocess.run(["gh", "workflow", "run", "gerar-stories.yml", "--ref", "main"],
                       cwd=AQUI, capture_output=True, text=True)
    print("geração de amanhã acionada" if r.returncode == 0 else "não consegui acionar a geração: " + r.stderr[:300])
    return r.returncode == 0


def proximo_acordar(t, itens=None, feitos=None):
    """Próximo momento em que vale acordar: o próximo story, as 19h da geração, ou a conferência do Telegram."""
    if itens is None:
        try:
            itens, _ = P.ler_fila()
        except FileNotFoundError:
            itens = []
    feitos = P.ja_resolvidos() if feitos is None else feitos
    passo = PASSO_DIA if DIA_INI <= t.hour < DIA_FIM else PASSO_NOITE
    candidatos = [t + passo]
    for it in itens:
        if it["status"] == "aprovado" and it["quando"] > t and P.chave(it) not in feitos:
            candidatos.append(it["quando"] + dt.timedelta(seconds=5))
            break                                   # a fila vem em ordem: o primeiro futuro basta
    gerar = t.replace(hour=HORA_GERAR, minute=0, second=30, microsecond=0)
    if gerar > t:
        candidatos.append(gerar)
    return min(candidatos)


_ULTIMO_ACORDAR = {}


def esperar(segundos, t=None, _tg=None):
    """Dorme até a hora marcada, mas de dia fica escutando o Telegram: se ela mandar algo, acorda na hora.
    Só espia as mensagens (não marca como lidas): quem lê e responde é a rodada do publicar.py."""
    import aprovacao
    t = t or agora()
    tk, chat = aprovacao._cfg()
    if not (tk and chat) or not (DIA_INI <= t.hour < DIA_FIM):
        time.sleep(segundos)
        return False
    _tg = _tg or aprovacao.telegram
    fim = time.monotonic() + segundos
    while (resta := fim - time.monotonic()) > 1:
        try:
            offset = aprovacao.ler_estado().get("offset", 0)
            r = _tg("getUpdates", {"offset": offset, "timeout": int(min(50, resta)), "limit": 1})
            if r.get("result") and offset == _ULTIMO_ACORDAR.get("offset"):
                time.sleep(min(20, max(0, resta)))       # a rodada não conseguiu ler: não fica girando
            elif r.get("result"):
                _ULTIMO_ACORDAR["offset"] = offset
                print("mensagem nova no Telegram: acordando agora")
                return True
        except Exception as ex:          # Telegram fora do ar: só dorme um pouco e tenta de novo
            print("não consegui escutar o Telegram:", str(ex)[:200])
            time.sleep(min(20, max(0, resta)))
    return False


def rodada_publicar():
    env = dict(os.environ)
    if not env.get("API_HOST"):
        env.pop("API_HOST", None)
    r = subprocess.run([sys.executable, os.path.join(AQUI, "publicar.py")], cwd=AQUI, env=env)
    return r.returncode


def correr():
    inicio = time.monotonic()
    while True:
        sincronizar()
        rodada_publicar()
        t = agora()
        salvar(f"registro: {t:%Y-%m-%d %H:%M}")
        if talvez_gerar(t, acionar_geracao):
            salvar("corrente: geração acionada")
        prox = proximo_acordar(agora())
        espera = max(20.0, (prox - agora()).total_seconds())
        resta = LIMITE_S - (time.monotonic() - inicio)
        if resta <= 60:
            print("tempo desta rodada acabou: passando a vez para a próxima")
            return 0
        espera = min(espera, resta)
        print(f"dormindo até {(agora() + dt.timedelta(seconds=espera)):%H:%M:%S} (ou até chegar mensagem)")
        sys.stdout.flush()
        esperar(espera)


def principal(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--planejar", action="store_true")
    a = ap.parse_args(argv)
    if a.planejar:
        t = agora()
        for _ in range(8):
            t = proximo_acordar(t)
            print(t.strftime("%d/%m %H:%M:%S"))
        return 0
    return correr()


if __name__ == "__main__":
    sys.exit(principal())
