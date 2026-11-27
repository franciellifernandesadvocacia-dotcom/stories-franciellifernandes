import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import corrente as C  # noqa: E402
import publicar as P  # noqa: E402


def t(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=P.fuso())


class TestCorrente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.antigo = (P.FILA, P.REGISTRO, C.ESTADO_CORRENTE)
        P.FILA = os.path.join(self.tmp, "fila.csv")
        P.REGISTRO = os.path.join(self.tmp, "registro.csv")
        C.ESTADO_CORRENTE = os.path.join(self.tmp, "corrente.json")
        with open(P.FILA, "w") as f:
            f.write("arquivo,data,hora,status,lote\n"
                    "a.jpg,2026-12-01,08:00,aprovado,2026-12-01\n"
                    "b.jpg,2026-12-01,09:20,aprovado,2026-12-01\n"
                    "c.jpg,2026-12-01,09:25,tirado,2026-12-01\n")

    def tearDown(self):
        P.FILA, P.REGISTRO, C.ESTADO_CORRENTE = self.antigo
        shutil.rmtree(self.tmp)

    def test_acorda_na_hora_do_story(self):
        prox = C.proximo_acordar(t("2026-12-01 07:55") + dt.timedelta(seconds=270))
        self.assertEqual(prox.strftime("%H:%M:%S"), "08:00:05")
        prox = C.proximo_acordar(t("2026-12-01 09:19") + dt.timedelta(seconds=30))
        self.assertEqual(prox.strftime("%H:%M:%S"), "09:20:05")

    def test_sem_story_confere_telegram_e_19h(self):
        self.assertEqual(C.proximo_acordar(t("2026-12-01 10:00")).strftime("%H:%M"), "10:02")   # de dia: feed a cada 2 min
        self.assertEqual(C.proximo_acordar(t("2026-12-01 18:59") + dt.timedelta(seconds=20)).strftime("%H:%M:%S"), "19:00:30")
        self.assertEqual(C.proximo_acordar(t("2026-12-01 23:00")).strftime("%H:%M"), "23:30")

    def test_story_ja_publicado_nao_acorda(self):
        P.anotar("publicado", "b.jpg", "2026-12-01 09:20", caminho=P.REGISTRO)
        self.assertEqual(C.proximo_acordar(t("2026-12-01 09:19")).strftime("%H:%M"), "09:21")

    def test_mensagem_no_telegram_acorda_na_hora(self):
        import aprovacao
        antigo_estado = aprovacao.ESTADO
        aprovacao.ESTADO = os.path.join(self.tmp, "estado.json")
        self.addCleanup(setattr, aprovacao, "ESTADO", antigo_estado)
        os.environ.update(TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="42")
        aprovacao.salvar_estado({"offset": 7})
        chamadas = []

        def tg(metodo, campos=None, arquivos=None):
            chamadas.append(campos)
            return {"result": [{"update_id": 7}]} if len(chamadas) >= 2 else {"result": []}
        inicio = C.time.monotonic()
        self.assertTrue(C.esperar(600, t("2026-12-01 10:00"), _tg=tg))
        self.assertLess(C.time.monotonic() - inicio, 5)
        self.assertEqual(chamadas[0]["offset"], 7)
        self.assertFalse(C.esperar(0.5, t("2026-12-01 23:00"), _tg=tg))   # de noite só dorme
        os.environ.pop("TELEGRAM_BOT_TOKEN"); os.environ.pop("TELEGRAM_CHAT_ID")

    def test_gera_as_19h_no_maximo_duas_vezes(self):
        pedidos = []
        acionar = lambda: pedidos.append(1) or True  # noqa: E731
        self.assertFalse(C.talvez_gerar(t("2026-12-01 18:30"), acionar))
        self.assertTrue(C.talvez_gerar(t("2026-12-01 19:00"), acionar))
        self.assertFalse(C.talvez_gerar(t("2026-12-01 19:30"), acionar))   # espera 1h
        self.assertTrue(C.talvez_gerar(t("2026-12-01 20:05"), acionar))
        self.assertFalse(C.talvez_gerar(t("2026-12-01 21:30"), acionar))   # no máximo 2
        self.assertEqual(len(pedidos), 2)

    def test_nao_gera_se_amanha_ja_existe(self):
        with open(P.FILA, "a") as f:
            f.write("d.jpg,2026-12-02,08:00,aprovado,2026-12-02\n")
        self.assertFalse(C.talvez_gerar(t("2026-12-01 19:00"), lambda: True))


if __name__ == "__main__":
    unittest.main()
