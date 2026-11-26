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
        os.environ.update(URL_IMAGENS="https://exemplo.test/stories", TELEGRAM_BOT_TOKEN="BOT", TELEGRAM_CHAT_ID="42",
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
        self.assertEqual(itens[0]["quando"].strftime("%H:%M"), "07:00")
        self.assertEqual(itens[-1]["quando"].strftime("%H:%M"), "21:00")
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
        self.assertIn("SEQUÊNCIA", pedido)
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
        P.rodada(ig, self.agora("2026-12-01 07:07"))
        P.rodada(ig, self.agora("2026-12-01 07:37"))
        self.assertFalse(os.path.exists(P.REGISTRO))
        self.assertEqual(sum("aguardam aprovação" in a for a in self.avisos), 1)
        # ela responde "ok menos 3": sai o 1 agora; o 3 nunca sai
        A.telegram = TelegramFalso(["ok menos 3"])
        P.rodada(ig, self.agora("2026-12-01 08:07"))
        status = [i["status"] for i in P.ler_fila()[0]]
        self.assertEqual(status.count("tirado"), 1)
        self.assertEqual(status[2], "tirado")
        with open(P.REGISTRO, encoding="utf-8") as f:
            self.assertIn("01-bom-dia.jpg,2026-12-01 07:00,publicado", f.read())
        A.telegram = TelegramFalso()
        P.rodada(ig, self.agora("2026-12-01 21:07"))
        with open(P.REGISTRO, encoding="utf-8") as f:
            reg = f.read()
        self.assertNotIn("03-noticia", reg)
        self.assertIn("07-dica.jpg", reg)

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
        self.assertEqual(itens[0]["status"], "aprovado")
        self.assertEqual(P.conferir_imagem(itens[0]["arquivo"]), [])
        self.assertFalse(any("original" in f for f in os.listdir(os.path.join(P.PASTA_STORIES, "2026-12-01"))))
        self.assertTrue(any(m == "sendPhoto" and "18:00" in c["caption"] for m, c, a in enviados))
        # cancelar
        A.ler_respostas(_tg=lambda m, c=None, a=None: {"result": [{"update_id": 6, "message": {"chat": {"id": 42}, "text": "cancelar"}}]} if m == "getUpdates" else {"ok": True})
        self.assertEqual(P.ler_fila()[0][0]["status"], "tirado")

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
        self.assertEqual(F.horario("agora", agora, []), agora + dt.timedelta(minutes=5))
        livre = F.horario("", agora, [self.agora("2026-12-01 10:00")])
        self.assertEqual(livre.strftime("%H:%M"), "11:00")


if __name__ == "__main__":
    unittest.main()
