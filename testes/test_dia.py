"""Testes do gerador diário e da aprovação, sem internet: Claude, Telegram e Meta são de mentira.
Rodar:  python3 -m unittest discover -s testes -v
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aprovacao as A  # noqa: E402
import gerar_dia as G  # noqa: E402
import publicar as P  # noqa: E402
from test_publicar import MetaFalsa  # noqa: E402

DIA = dt.date(2026, 12, 1)


class Ambiente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.antigo = (P.FILA, P.REGISTRO, P.PASTA_STORIES, G.HISTORICO, A.ESTADO)
        P.FILA = os.path.join(self.tmp, "fila.csv")
        P.REGISTRO = os.path.join(self.tmp, "registro.csv")
        P.PASTA_STORIES = os.path.join(self.tmp, "stories")
        G.HISTORICO = os.path.join(self.tmp, "historico.json")
        A.ESTADO = os.path.join(self.tmp, "estado.json")
        os.makedirs(P.PASTA_STORIES)
        os.environ.update(CONFERIR_FEED="0", URL_IMAGENS="https://exemplo.test/stories", TELEGRAM_BOT_TOKEN="BOT", TELEGRAM_CHAT_ID="42",
                          STORIES_POR_DIA="7", APROVACAO="obrigatoria")
        self.avisos = []
        self._avisar, P.avisar = P.avisar, self.avisos.append
        self._tg, self._cli = A.telegram, G._cliente

    def tearDown(self):
        P.FILA, P.REGISTRO, P.PASTA_STORIES, G.HISTORICO, A.ESTADO = self.antigo
        P.avisar = self._avisar
        A.telegram, G._cliente = self._tg, self._cli
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "STORIES_POR_DIA", "APROVACAO"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp)

    def agora(self, s):
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=P.fuso())


class TelegramFalso:
    def __init__(self, respostas=()):
        self.enviados, self.respostas = [], list(respostas)

    def __call__(self, metodo, campos=None, arquivos=None):
        self.enviados.append((metodo, campos, arquivos))
        if metodo == "getUpdates":
            res = [{"update_id": 100 + i, "message": {"chat": {"id": 42}, "text": t}}
                   for i, t in enumerate(self.respostas)]
            self.respostas = []
            return {"ok": True, "result": res}
        return {"ok": True}


class TestGerar(Ambiente):
    def test_gera_imagens_e_fila_aguardando(self):
        self.assertEqual(G.gerar(DIA, exemplo=True), 0)
        itens, probs = P.ler_fila()
        self.assertEqual(probs, [])
        self.assertEqual(len(itens), 7)
        self.assertTrue(all(i["status"] == "aguardando" for i in itens))
        self.assertEqual(itens[0]["quando"].strftime("%H:%M"), "08:00")
        self.assertEqual(itens[-1]["quando"].strftime("%H:%M"), "11:33")
        # os dois stories da notícia saem juntos, um atrás do outro
        self.assertEqual([i["quando"].strftime("%H:%M") for i in itens[1:3]], ["08:01", "08:02"])
        for i in itens:
            self.assertEqual(P.conferir_imagem(i["arquivo"]), [])  # 1080x1920, JPEG
        self.assertEqual(G.gerar(DIA, exemplo=True), 0)  # não gera duas vezes o mesmo dia
        self.assertEqual(len(P.ler_fila()[0]), 7)

    def test_aprovacao_automatica(self):
        os.environ["APROVACAO"] = "automatica"
        G.gerar(DIA, exemplo=True)
        self.assertTrue(all(i["status"] == "aprovado" for i in P.ler_fila()[0]))

    def test_chamadas_ao_claude(self):
        """Confere o formato das chamadas e a retomada após pause_turn, com um Claude de mentira."""
        chamadas = []
        busca = types.SimpleNamespace(type="web_search_tool_result", content=[
            types.SimpleNamespace(type="web_search_result", url="https://g1.globo.com/mt/noticia-real", title="x"),
            types.SimpleNamespace(type="web_search_result", url="https://g1.globo.com/mt/nao-lida", title="y")])
        leitura = types.SimpleNamespace(type="web_fetch_tool_result", content=types.SimpleNamespace(
            type="web_fetch_result", url="https://g1.globo.com/mt/noticia-real/"))
        pausado = types.SimpleNamespace(stop_reason="pause_turn", content=[busca])
        final = types.SimpleNamespace(stop_reason="end_turn", content=[leitura, types.SimpleNamespace(type="text", text=(
            "Li estas:\n"
            "NOTICIA | Blitz em Cuiabá | Resumo real da matéria lida. | g1 | 30/11 | https://g1.globo.com/mt/noticia-real\n"
            "NOTICIA | Só achada, não lida | Resumo. | g1 | 30/11 | https://g1.globo.com/mt/nao-lida\n"
            "NOTICIA | Notícia inventada | Resumo. | site | 30/11 | https://inventado.com/x"))])
        seq = [dict(s, fonte=s.get("fonte", ""), comentario=s.get("comentario", ""), rodape=s.get("rodape", ""),
                    assunto="teste", noticia=(1 if s["tipo"] == "noticia" else 0)) for s in G.EXEMPLO]
        for s in seq:
            s.pop("link", None)
        escrito = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(
            type="text", text=json.dumps({"tema_do_dia": "CNH suspensa", "stories": seq}))])
        fila = [pausado, final, escrito]

        def create(**kw):
            chamadas.append(kw)
            return fila.pop(0)
        cli = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))
        G._cliente = lambda: cli
        self.assertEqual(G.gerar(DIA), 0)
        self.assertEqual(chamadas[0]["tools"][0]["type"], "web_search_20260209")
        self.assertEqual(chamadas[1]["messages"][1]["role"], "assistant")  # retomou a busca pausada
        pedido = chamadas[2]["messages"][0]["content"]
        self.assertIn("Blitz em Cuiabá", pedido)
        self.assertNotIn("inventada", pedido)          # link que não veio da busca é descartado
        self.assertNotIn("não lida", pedido)           # matéria que não foi aberta não entra
        self.assertEqual(chamadas[0]["tools"][1]["type"], "web_fetch_20260209")
        self.assertIn("DOIS MOMENTOS", pedido)
        self.assertEqual(chamadas[2]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(chamadas[2]["model"], "claude-opus-5-5")
        with open(G.HISTORICO, encoding="utf-8") as f:
            hist = json.load(f)
        self.assertIn("2026-12-01", hist["dias"])
        self.assertEqual(hist["temas"], ["CNH suspensa"])
        self.assertEqual(hist["links"][0]["link"], "https://g1.globo.com/mt/noticia-real")
        with open(os.path.join(self.tmp, "docs", "index.html"), encoding="utf-8") as f:
            self.assertIn("https://g1.globo.com/mt/noticia-real", f.read())

    def test_falha_do_claude_vira_aviso(self):
        def create(**kw):
            raise RuntimeError("sem crédito")
        G._cliente = lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))
        self.assertEqual(G.principal(["--para", "2026-12-01"]), 1)
        self.assertIn("sem crédito", self.avisos[0])


    def test_exemplo_nao_entra_na_fila(self):
        self.assertEqual(G.principal(["--para", "2026-12-01", "--exemplo"]), 0)
        self.assertFalse(os.path.exists(P.FILA))
        self.assertFalse(os.path.exists(G.HISTORICO))
        self.assertEqual(len([f for f in os.listdir(os.path.join(P.PASTA_STORIES, "exemplo")) if f.endswith(".jpg")]), 7)
        tg = TelegramFalso()
        A.enviar_lote("exemplo", _tg=tg)
        self.assertIn("NÃO serão publicadas", tg.enviados[-1][1]["text"])
        self.assertFalse(os.path.exists(A.ESTADO))


class TestAprovacao(Ambiente):
    def test_interpretar(self):
        self.assertEqual(A.interpretar("OK"), ("ok", set()))
        self.assertEqual(A.interpretar("ok menos 2 e 5"), ("ok", {2, 5}))
        self.assertEqual(A.interpretar("Não"), ("nao", set()))
        self.assertEqual(A.interpretar("não 3"), ("ok", {3}))
        self.assertEqual(A.interpretar("bom dia!"), (None, set()))

    def test_fluxo_completo(self):
        G.gerar(DIA, exemplo=True)
        tg = TelegramFalso()
        A.enviar_lote("2026-12-01", _tg=tg)
        self.assertEqual(tg.enviados[0][0], "sendMediaGroup")
        self.assertEqual(len(tg.enviados[0][2]), 7)
        self.assertIn("OK menos", tg.enviados[-1][1]["text"])
        self.assertIn("tema: " + G.EXEMPLO_TEMA, tg.enviados[-1][1]["text"])
        self.assertIn("link: https://example.com/noticia", tg.enviados[-1][1]["text"])

        ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(), espera=0)
        # sem resposta: nada sai e ela recebe um lembrete (só um por dia)
        A.telegram = TelegramFalso()
        P.rodada(ig, self.agora("2026-12-01 08:07"))
        P.rodada(ig, self.agora("2026-12-01 08:37"))
        self.assertFalse(os.path.exists(P.REGISTRO))
        self.assertEqual(sum("aguardam aprovação" in a for a in self.avisos), 1)
        # ela responde "ok menos 3": sai o 1 agora; o 3 nunca sai
        A.telegram = TelegramFalso(["ok menos 3"])
        P.rodada(ig, self.agora("2026-12-01 09:07"))
        status = [i["status"] for i in P.ler_fila()[0]]
        self.assertEqual(status.count("tirado"), 1)
        self.assertEqual(status[2], "tirado")
        with open(P.REGISTRO, encoding="utf-8") as f:
            self.assertIn("01-bom-dia.jpg,2026-12-01 08:00,publicado", f.read())
        A.telegram = TelegramFalso()
        P.rodada(ig, self.agora("2026-12-01 21:07"))
        with open(P.REGISTRO, encoding="utf-8") as f:
            reg = f.read()
        self.assertNotIn("03-noticia", reg)
        self.assertIn("07-dica.jpg", reg)

    def test_blocos_com_o_claude(self):
        st = [{"tipo": "bom_dia", "bloco": 1}, {"tipo": "noticia", "bloco": 2}, {"tipo": "noticia", "bloco": 2},
              {"tipo": "pergunta", "bloco": 3}, {"tipo": "dica", "bloco": 3}, {"tipo": "dica", "bloco": 4}]
        self.assertEqual(G.horarios(6, st), ["08:00", "08:01", "08:02", "11:30", "11:31", "11:32"])
        st = [{"tipo": "bom_dia"}, {"tipo": "pergunta"}, {"tipo": "dica"}]   # sem notícia
        self.assertEqual(G.horarios(3, st), ["08:00", "11:30", "11:31"])

    def test_automatico_avisa_e_deixa_cancelar(self):
        os.environ["APROVACAO"] = "automatica"
        G.gerar(DIA, exemplo=True)
        tg = TelegramFalso()
        A.enviar_lote("2026-12-01", _tg=tg)
        self.assertIn("programados (automático)", tg.enviados[-1][1]["text"])
        A.ler_respostas(_tg=TelegramFalso(["não 2"]))
        status = [i["status"] for i in P.ler_fila()[0]]
        self.assertEqual(status.count("tirado"), 1)
        self.assertEqual(status.count("aprovado"), 6)

    def test_liga_e_desliga_pelo_telegram(self):
        self.assertEqual(A.comando_modo("Só fotos hoje"), "hoje")
        self.assertEqual(A.comando_modo("SÓ FOTOS"), "desligar")
        self.assertEqual(A.comando_modo("desliga o automático"), "desligar")
        self.assertEqual(A.comando_modo("Você comanda"), "ligar")
        self.assertIsNone(A.comando_modo("ok menos 3"))
        os.environ["APROVACAO"] = "automatica"
        G.gerar(DIA, exemplo=True)
        status = lambda: [i["status"] for i in P.ler_fila()[0]]
        # hoje = 01/12 às 09:00: os 3 primeiros já passaram; os outros 4 pausam
        tg = TelegramFalso(["só fotos hoje"])
        A.ler_respostas(_tg=tg, agora=self.agora("2026-12-01 09:00"))
        self.assertEqual(status().count("pausado"), 4)
        self.assertIn("hoje só saem as fotos", tg.enviados[-1][1]["text"])
        A.ler_respostas(_tg=TelegramFalso(["você comanda"]), agora=self.agora("2026-12-01 09:10"))
        self.assertEqual(status().count("aprovado"), 7)
        # desligado de vez: pausa tudo que falta e o gerador não cria o dia seguinte
        A.ler_respostas(_tg=TelegramFalso(["SÓ FOTOS"]), agora=self.agora("2026-11-30 20:00"))
        self.assertEqual(status().count("pausado"), 7)
        self.assertEqual(A.ler_estado()["modo"], "so_fotos")
        G.gerar(DIA + dt.timedelta(days=1), exemplo=True)
        self.assertFalse(any(i["arquivo"].startswith("2026-12-02") for i in P.ler_fila()[0]))
        A.ler_respostas(_tg=TelegramFalso(["Você comanda"]), agora=self.agora("2026-11-30 20:30"))
        G.gerar(DIA + dt.timedelta(days=1), exemplo=True)
        self.assertTrue(any(i["arquivo"].startswith("2026-12-02") for i in P.ler_fila()[0]))

    def test_resposta_de_outra_pessoa_e_ignorada(self):
        G.gerar(DIA, exemplo=True)
        A.salvar_estado({"offset": 0, "ultimo_lote": "2026-12-01", "lembrete": ""})
        tg = TelegramFalso()
        tg.respostas = []
        orig = tg.__call__

        def estranho(metodo, campos=None, arquivos=None):
            if metodo == "getUpdates":
                return {"ok": True, "result": [{"update_id": 7, "message": {"chat": {"id": 999}, "text": "ok"}}]}
            return orig(metodo, campos, arquivos)
        A.ler_respostas(_tg=estranho)
        self.assertTrue(all(i["status"] == "aguardando" for i in P.ler_fila()[0]))


class TestFotoEnviada(Ambiente):
    def _foto(self, caminho):
        from PIL import Image
        Image.new("RGB", (1200, 1600), (120, 90, 70)).save(caminho)
        return caminho

    def test_foto_com_instrucoes_vira_story(self):
        import foto_story as F
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "", "lembrete": ""})
        os.environ.pop("ANTHROPIC_API_KEY", None)
        msg = {"chat": {"id": 42}, "photo": [{"file_id": "p1"}, {"file_id": "p2"}],
               "caption": '"segunda começando com café" sem sombra, texto em cima, às 18h'}
        enviados = []

        def tg(metodo, campos=None, arquivos=None):
            enviados.append((metodo, campos, arquivos))
            if metodo == "getUpdates":
                return {"result": [{"update_id": 5, "message": msg}]}
            return {"ok": True}
        agora = self.agora("2026-12-01 09:10")
        antigo = F.processar
        F.processar = lambda m, c, t: antigo(m, c, t, agora=agora, _baixar=lambda fid, dest, _t: self._foto(dest))
        try:
            A.ler_respostas(_tg=tg)
        finally:
            F.processar = antigo
        itens = P.ler_fila()[0]
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["quando"].strftime("%Y-%m-%d %H:%M"), "2026-12-01 18:00")
        self.assertEqual(itens[0]["status"], "aguardando")          # foto dela: só sai depois do OK
        self.assertEqual(P.conferir_imagem(itens[0]["arquivo"]), [])
        self.assertFalse(any("original" in f for f in os.listdir(os.path.join(P.PASTA_STORIES, "2026-12-01"))))
        self.assertTrue(any(m == "sendPhoto" and "Prévia" in c["caption"] and "18:00" in c["caption"]
                            for m, c, a in enviados))
        # OK: aprova mantendo o horário que ela pediu
        respostas = []
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 6, "message": {"chat": {"id": 42}, "text": "ok"}}]} if m == "getUpdates" else respostas.append(c) or {"ok": True},
                        agora=agora)
        it = P.ler_fila()[0][0]
        self.assertEqual((it["status"], it["quando"].strftime("%H:%M")), ("aprovado", "18:00"))
        self.assertIn("18:00", respostas[-1]["text"])
        # cancelar
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "cancelar"}}]} if m == "getUpdates" else {"ok": True})
        self.assertEqual(P.ler_fila()[0][0]["status"], "tirado")

    def test_foto_sem_horario_sai_na_hora_do_ok(self):
        import foto_story as F
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "2026-12-01", "lembrete": ""})
        os.environ.pop("ANTHROPIC_API_KEY", None)
        msg = {"chat": {"id": 42}, "photo": [{"file_id": "p1"}], "caption": "Poste agora, sem sombra."}
        agora = self.agora("2026-12-01 11:39")
        antigo = F.processar
        F.processar = lambda m, c, t: antigo(m, c, t, agora=agora, _baixar=lambda fid, dest, _t: self._foto(dest))
        try:
            A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 5, "message": msg}]} if m == "getUpdates" else {"ok": True})
        finally:
            F.processar = antigo
        self.assertEqual(P.ler_fila()[0][0]["status"], "aguardando")
        respostas = []
        ok_em = self.agora("2026-12-01 11:52")
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 6, "message": {"chat": {"id": 42}, "text": "Ok"}}]} if m == "getUpdates" else respostas.append(c) or {"ok": True},
                        agora=ok_em)
        it = P.ler_fila()[0][0]
        self.assertEqual((it["status"], it["quando"]), ("aprovado", ok_em))
        self.assertEqual(respostas[-1]["text"], "Postando agora.")
        self.assertEqual(A.ler_estado()["ultimo_lote"], "2026-12-01")      # o OK não mexeu nos stories do dia

    def test_correcao_refaz_a_previa(self):
        import foto_story as F
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "", "lembrete": ""})
        os.environ.pop("ANTHROPIC_API_KEY", None)
        msg = {"chat": {"id": 42}, "photo": [{"file_id": "p1"}], "caption": '"treino feito" sem sombra'}
        agora = self.agora("2026-12-01 11:39")
        antigo = F.processar
        baixar = lambda fid, dest, _t: self._foto(dest)  # noqa: E731
        F.processar = lambda m, c, t: antigo(m, c, t, agora=agora, _baixar=baixar)
        antigo_corr = F.corrigir
        F.corrigir = lambda pend, txt, c, t, ag=None: antigo_corr(pend, txt, c, t, self.agora("2026-12-01 11:41"), _baixar=baixar)
        enviados = []

        def tg_com(texto_ou_msg, uid):
            m = texto_ou_msg if isinstance(texto_ou_msg, dict) else {"chat": {"id": 42}, "text": texto_ou_msg}
            return lambda met, c=None, a=None: {"result": [{"update_id": uid, "message": m}]} if met == "getUpdates" else enviados.append((met, c)) or {"ok": True}
        try:
            A.ler_respostas(_tg=tg_com(msg, 5), agora=agora)
            primeiro = P.ler_fila()[0][0]["arquivo"]
            self.assertEqual(A.ler_estado()["foto_pendente"]["arquivo"], primeiro)
            A.ler_respostas(_tg=tg_com("texto em cima", 6), agora=self.agora("2026-12-01 11:41"))
        finally:
            F.processar, F.corrigir = antigo, antigo_corr
        it = P.ler_fila()[0][0]
        self.assertNotEqual(it["arquivo"], primeiro)
        self.assertEqual(it["status"], "aguardando")
        self.assertFalse(os.path.exists(os.path.join(P.PASTA_STORIES, primeiro)))
        self.assertEqual(P.conferir_imagem(it["arquivo"]), [])
        self.assertIn("corrigida", enviados[-1][1]["caption"])
        A.ler_respostas(_tg=tg_com("ok", 7), agora=self.agora("2026-12-01 11:42"))
        it = P.ler_fila()[0][0]
        self.assertEqual(it["status"], "aprovado")
        self.assertNotIn("foto_pendente", A.ler_estado())

    def test_album_vira_colagem(self):
        import foto_story as F
        from PIL import Image
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "", "lembrete": ""})
        os.environ.pop("ANTHROPIC_API_KEY", None)
        msgs = [{"chat": {"id": 42}, "media_group_id": "g1", "photo": [{"file_id": f"f{i}"}],
                 **({"caption": '"rotina de hoje"'} if i == 0 else {})} for i in range(3)]
        baixadas = []

        def baixar(fid, dest, _t):
            Image.new("RGB", (900, 1200), (60 + 40 * len(baixadas), 80, 90)).save(dest)
            baixadas.append(fid)
            return dest
        agora = self.agora("2026-12-01 09:10")
        antigo = F.processar
        F.processar = lambda m, c, t: antigo(m, c, t, agora=agora, _baixar=baixar)
        enviados = []

        def tg(metodo, campos=None, arquivos=None):
            enviados.append(metodo)
            if metodo == "getUpdates":
                return {"result": [{"update_id": 10 + i, "message": m} for i, m in enumerate(msgs)]}
            return {"ok": True}
        try:
            A.ler_respostas(_tg=tg)
        finally:
            F.processar = antigo
        itens = P.ler_fila()[0]
        self.assertEqual(len(itens), 1)                 # 3 fotos = 1 colagem
        self.assertEqual(len(baixadas), 3)
        self.assertEqual(P.conferir_imagem(itens[0]["arquivo"]), [])

    def test_instrucoes_simples(self):
        import foto_story as F
        o = F.interpretar_simples('"treino feito" mais escuro com faixa agora')
        self.assertEqual((o["texto"], o["exposicao"], o["faixa"], o["quando"]), ("treino feito", 0.45, True, "agora"))
        self.assertTrue(F.interpretar_simples("sem texto")["sem_texto"])
        agora = self.agora("2026-12-01 09:10")
        self.assertEqual(F.horario("agora", agora, []), agora + dt.timedelta(minutes=2))
        self.assertEqual(F.horario("", agora, [self.agora("2026-12-01 10:00")]), agora + dt.timedelta(minutes=2))


class TestAvisoDeMudanca(Ambiente):
    def test_reenvia_quando_muda_o_horario(self):
        os.environ["APROVACAO"] = "automatica"
        G.gerar(DIA, exemplo=True)
        A.enviar_lote("2026-12-01", _tg=TelegramFalso())
        tg = TelegramFalso()
        self.assertEqual(A.avisar_mudancas(self.agora("2026-11-30 21:00"), _tg=tg), 0)  # nada mudou
        campos, linhas = A.ler_linhas()
        linhas[1]["hora"] = "09:40"
        A.gravar_linhas(campos, linhas)
        self.assertEqual(A.avisar_mudancas(self.agora("2026-11-30 21:30"), _tg=tg), 1)
        self.assertIn("ATUALIZADO", tg.enviados[-1][1]["text"])
        self.assertIn("09:40", tg.enviados[-1][1]["text"])
        self.assertEqual(A.avisar_mudancas(self.agora("2026-11-30 22:00"), _tg=tg), 0)  # só uma vez

    def test_atualizacao_mostra_so_o_que_falta(self):
        os.environ["APROVACAO"] = "automatica"
        G.gerar(DIA, exemplo=True)
        ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(), espera=0)
        A.telegram = TelegramFalso()
        P.rodada(ig, self.agora("2026-12-01 08:07"))   # nunca avisado: manda o que falta
        textos = [c["text"] for m, c, _ in A.telegram.enviados if m == "sendMessage"]
        self.assertTrue(any("ATUALIZADO" in t for t in textos))
        self.assertFalse(any("08:00" in t for t in textos if "ATUALIZADO" in t))


if __name__ == "__main__":
    unittest.main()


class TestModeloEVideo(Ambiente):
    def setUp(self):
        super().setUp()
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "", "lembrete": ""})
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def _rodar(self, msgs, baixar):
        import foto_story as F
        enviados = []

        def tg(metodo, campos=None, arquivos=None):
            enviados.append((metodo, campos, arquivos))
            if metodo == "getUpdates":
                return {"result": [{"update_id": 10 + i, "message": m} for i, m in enumerate(msgs)]}
            return {"ok": True}
        antigo = F.processar
        F.processar = lambda m, c, t: antigo(m, c, t, agora=self.agora("2026-12-01 09:10"), _baixar=baixar)
        try:
            A.ler_respostas(_tg=tg)
        finally:
            F.processar = antigo
        return enviados

    def test_foto_de_modelo_nao_entra_no_story(self):
        from PIL import Image
        import foto_story as F
        self.assertEqual(F.interpretar_simples("máquina de escrever, à direita, minúsculas")["fonte"], "maquina")
        msgs = [{"chat": {"id": 42}, "media_group_id": "g2", "photo": [{"file_id": f"m{i}"}],
                 **({"caption": 'pegue essa foto e use o modelo abaixo, escreva "isso na foto"'} if i == 0 else {})}
                for i in range(2)]
        baixadas = []

        def baixar(fid, dest, _t):
            Image.new("RGB", (900, 1600), (90, 70, 60)).save(dest)
            baixadas.append(fid)
            return dest
        enviados = self._rodar(msgs, baixar)
        self.assertEqual(len(baixadas), 2)
        itens = P.ler_fila()[0]
        self.assertEqual(len(itens), 1)
        self.assertEqual(P.conferir_imagem(itens[0]["arquivo"]), [])
        legenda = [c["caption"] for m, c, a in enviados if m == "sendPhoto"][0]
        self.assertIn("Prévia", legenda)

    def test_video_vira_story_em_partes(self):
        import subprocess
        import foto_story as F

        def baixar(fid, dest, _t):   # vídeo de teste de 70 s sem som, deitado (vira 1080x1920)
            subprocess.run([F.ffmpeg(), "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=70",
                            "-c:v", "libx264", "-preset", "ultrafast", dest], capture_output=True, check=True)
            return dest
        msg = {"chat": {"id": 42}, "video": {"file_id": "v1", "file_size": 2_000_000}, "caption": '"bastidores" agora'}
        enviados = self._rodar([msg], baixar)
        itens = P.ler_fila()[0]
        self.assertEqual([i["arquivo"][-10:] for i in itens], ["parte1.mp4", "parte2.mp4"])
        self.assertTrue(all(i["quando"] == itens[0]["quando"] for i in itens))
        self.assertEqual(P.conferir_imagem(itens[0]["arquivo"]), [])
        dur, audio = F.info_video(os.path.join(P.PASTA_STORIES, itens[0]["arquivo"]))
        self.assertTrue(58 <= dur <= 60 and audio)
        self.assertTrue(any(m == "sendVideo" and "2 partes" in c["caption"] for m, c, a in enviados))
        self.assertFalse(any("original" in f for f in os.listdir(os.path.join(P.PASTA_STORIES, "2026-12-01"))))
        # cancelar tira as duas partes
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 30, "message": {"chat": {"id": 42}, "text": "cancelar"}}]} if m == "getUpdates" else {"ok": True})
        self.assertEqual({i["status"] for i in P.ler_fila()[0]}, {"tirado"})

    def test_video_grande_demais(self):
        msg = {"chat": {"id": 42}, "video": {"file_id": "v2", "file_size": 45_000_000}}
        enviados = self._rodar([msg], lambda *a: self.fail("não devia baixar"))
        self.assertEqual(P.ler_fila()[0], [])
        self.assertTrue(any(m == "sendMessage" and "20 MB" in c["text"] for m, c, a in enviados))

    def test_publica_video_com_video_url(self):
        from test_publicar import MetaFalsa
        meta = MetaFalsa()
        ig = P.Instagram("TOKEN-TESTE", user_id="1784", host="graph.facebook.com", http=meta, espera=0)
        ig.publicar_story("https://exemplo.test/stories/2026-12-01/enviada-1.mp4")
        post = [p for m, u, p in meta.chamadas if u.endswith("/media")][0]
        self.assertIn("video_url", post)
        self.assertNotIn("image_url", post)


class TestCasoEPost(Ambiente):
    def setUp(self):
        super().setUp()
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write("arquivo,data,hora,status,lote\n")
        A.salvar_estado({"offset": 0, "ultimo_lote": "", "lembrete": ""})

    def test_caso_mandado_pelo_telegram(self):
        import relato as R
        self.assertTrue(R.e_relato("CASO: chegou uma mãe..."))
        self.assertTrue(R.e_relato("caso - hoje"))
        self.assertFalse(R.e_relato("casou ontem"))
        recebido = []

        def escrever(texto):
            recebido.append(texto)
            return {"quando": "", "stories": [
                {"titulo": "Hoje chegou aqui uma mãe", "texto": "O BPC do filho tinha sido negado.", "comentario": "", "fundo": "sala"},
                {"titulo": "Fomos à Justiça", "texto": "E a sentença concedeu o benefício.", "comentario": "", "fundo": "notebook"},
                {"titulo": "O que fica", "texto": "Negativa do INSS nem sempre é a palavra final.", "comentario": "", "fundo": "paisagem"}]}
        enviados = []
        tg = lambda m, c=None, a=None: enviados.append((m, c, a)) or {"ok": True}
        texto = "CASO: chegou uma mãe com o BPC do filho negado por renda; fomos à Justiça e saiu a sentença concedendo"
        nomes = R.processar_caso(texto, 42, tg, agora=self.agora("2026-12-01 09:10"), _escrever=escrever)
        self.assertEqual(len(nomes), 3)
        self.assertNotIn("CASO", recebido[0])
        itens = P.ler_fila()[0]
        self.assertEqual(len({i["quando"] for i in itens}), 1)          # bloco: saem juntos
        self.assertTrue(all(P.conferir_imagem(i["arquivo"]) == [] for i in itens))
        self.assertTrue(any(m == "sendMediaGroup" for m, c, a in enviados))
        # CANCELAR tira o caso inteiro
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 40, "message": {"chat": {"id": 42}, "text": "cancelar"}}]} if m == "getUpdates" else {"ok": True})
        self.assertEqual({i["status"] for i in P.ler_fila()[0]}, {"tirado"})

    def test_post_novo_no_feed_vira_story(self):
        import relato as R
        from PIL import Image
        os.environ["CONFERIR_FEED"] = "1"
        antigo = R.A.PERFIL.get("story_de_post")
        R.A.PERFIL["story_de_post"] = True
        feed = [{"id": "111", "caption": "post antigo", "media_type": "IMAGE", "media_url": "u1"}]

        class IG:
            user_id = "1784"

            def _chamar(self, metodo, caminho, params=None):
                return {"data": list(feed)}

        def baixar(url, dest):
            Image.new("RGB", (1080, 1350), (150, 120, 100)).save(dest)
            return dest
        try:
            agora = self.agora("2026-12-01 10:00")
            self.assertEqual(R.story_de_posts(IG(), agora, baixar, lambda l, i: {}), [])   # 1ª vez: só anota
            feed.insert(0, {"id": "222", "caption": "BPC negado? Veja 3 motivos comuns.", "media_type": "CAROUSEL_ALBUM",
                            "children": {"data": [{"media_type": "IMAGE", "media_url": "u2"}]}})
            tg = []
            nomes = R.story_de_posts(IG(), agora, baixar,
                                     lambda l, i: {"titulo": "BPC negado?", "texto": "Três motivos comuns de negativa."},
                                     lambda m, c=None, a=None: tg.append(m) or {"ok": True})
            self.assertEqual(nomes, ["2026-12-01/post-222.jpg"])
            self.assertEqual(P.conferir_imagem(nomes[0]), [])
            self.assertEqual(R.story_de_posts(IG(), agora, baixar, lambda l, i: {}), [])   # não repete
            self.assertIn("sendPhoto", tg)
        finally:
            R.A.PERFIL["story_de_post"] = antigo
            os.environ["CONFERIR_FEED"] = "0"
