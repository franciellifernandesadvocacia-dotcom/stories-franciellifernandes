"""Testes com uma 'Meta de mentira': nada sai para a internet.
Rodar:  python3 -m unittest discover -s testes -v
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import publicar as P  # noqa: E402


def jpeg(caminho, w=1080, h=1920):
    """JPEG mínimo só com o cabeçalho de tamanho (suficiente para a conferência)."""
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    with open(caminho, "wb") as f:
        f.write(b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9")


class MetaFalsa:
    def __init__(self, falhar_em=None, status="FINISHED"):
        self.chamadas, self.falhar_em, self.status, self.n = [], falhar_em, status, 0

    def __call__(self, metodo, url, params):
        assert params.get("access_token") == "TOKEN-TESTE"
        self.chamadas.append((metodo, url, dict(params)))
        if self.falhar_em and self.falhar_em in url:
            return {"error": {"message": "Invalid parameter", "code": 100, "error_subcode": 2207052}}
        if url.endswith("/PAGINA1"):
            return {"instagram_business_account": {"id": "1784PAGINA"}, "id": "PAGINA1"}
        if url.endswith("/me"):
            return {"user_id": "1784TESTE", "username": "dradasmultas"}
        if url.endswith("/media"):
            self.n += 1
            return {"id": f"CONT{self.n}"}
        if "/CONT" in url:
            return {"status_code": self.status}
        if url.endswith("/media_publish"):
            return {"id": "PUB-" + params["creation_id"]}
        if "refresh_access_token" in url:
            return {"access_token": "NOVO", "expires_in": 5184000}
        return {}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.antigo = (P.FILA, P.REGISTRO, P.PASTA_STORIES)
        P.FILA = os.path.join(self.tmp, "fila.csv")
        P.REGISTRO = os.path.join(self.tmp, "registro.csv")
        P.PASTA_STORIES = os.path.join(self.tmp, "stories")
        os.makedirs(P.PASTA_STORIES)
        os.environ["URL_IMAGENS"] = "https://exemplo.test/stories"

    def tearDown(self):
        P.FILA, P.REGISTRO, P.PASTA_STORIES = self.antigo
        shutil.rmtree(self.tmp)

    def fila(self, linhas, sep=","):
        with open(P.FILA, "w", encoding="utf-8") as f:
            f.write(sep.join(["arquivo", "data", "hora"]) + "\n")
            for l in linhas:
                f.write(sep.join(l) + "\n")

    def registro(self):
        import csv
        if not os.path.exists(P.REGISTRO):
            return []
        with open(P.REGISTRO, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def agora(self, s):
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=P.fuso())


class TestFila(Base):
    def test_le_virgula_e_ponto_e_virgula_e_data_br(self):
        self.fila([("a.jpg", "01/12/2026", "09:00"), ("b.jpg", "2026-11-30", "18:30")], sep=";")
        itens, probs = P.ler_fila()
        self.assertEqual(probs, [])
        self.assertEqual([i["arquivo"] for i in itens], ["b.jpg", "a.jpg"])  # ordena por data

    def test_aponta_linha_errada(self):
        self.fila([("a.jpg", "31/02/2026", "09:00"), ("", "2026-12-01", "09:00")])
        _, probs = P.ler_fila()
        self.assertEqual(len(probs), 2)

    def test_imagem_tamanho_errado_ou_png(self):
        jpeg(os.path.join(P.PASTA_STORIES, "ok.jpg"))
        jpeg(os.path.join(P.PASTA_STORIES, "feed.jpg"), 1080, 1350)
        with open(os.path.join(P.PASTA_STORIES, "x.jpg"), "wb") as f:
            f.write(b"\x89PNG....")
        self.assertEqual(P.conferir_imagem("ok.jpg"), [])
        self.assertIn("1080x1350", P.conferir_imagem("feed.jpg")[0])
        self.assertIn("não é JPEG", P.conferir_imagem("x.jpg")[0])
        self.assertIn("não está", P.conferir_imagem("sumiu.jpg")[0])


class TestRodada(Base):
    def preparar(self):
        for n in ("s1.jpg", "s2.jpg", "s3.jpg"):
            jpeg(os.path.join(P.PASTA_STORIES, n))
        self.fila([("s1.jpg", "2026-12-01", "09:00"), ("s2.jpg", "2026-12-01", "18:00"),
                   ("s3.jpg", "2026-12-02", "09:00")])

    def test_publica_so_o_que_chegou_na_hora_e_nao_repete(self):
        self.preparar()
        meta = MetaFalsa()
        ig = P.Instagram("TOKEN-TESTE", http=meta, espera=0)
        self.assertEqual(P.rodada(ig, self.agora("2026-12-01 09:07")), 0)
        reg = self.registro()
        self.assertEqual([(r["arquivo"], r["resultado"]) for r in reg], [("s1.jpg", "publicado")])
        self.assertEqual(reg[0]["id_instagram"], "PUB-CONT1")
        criar = [c for c in meta.chamadas if c[1].endswith("/media")][0][2]
        self.assertEqual(criar["media_type"], "STORIES")
        self.assertEqual(criar["image_url"], "https://exemplo.test/stories/s1.jpg")
        # meia hora depois: não publica de novo
        P.rodada(ig, self.agora("2026-12-01 09:37"))
        self.assertEqual(len(self.registro()), 1)
        # à noite sai o segundo
        P.rodada(ig, self.agora("2026-12-01 18:07"))
        self.assertEqual([r["arquivo"] for r in self.registro()], ["s1.jpg", "s2.jpg"])

    def test_servidor_fora_do_ar_pula_os_muito_atrasados(self):
        self.preparar()
        ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(), espera=0)
        P.rodada(ig, self.agora("2026-12-02 09:07"))
        res = {r["arquivo"]: r["resultado"] for r in self.registro()}
        self.assertEqual(res, {"s1.jpg": "pulado-atrasado", "s2.jpg": "pulado-atrasado", "s3.jpg": "publicado"})

    def test_erro_da_meta_fica_anotado_e_tenta_de_novo(self):
        self.preparar()
        avisos = []
        antigo, P.avisar = P.avisar, avisos.append
        try:
            ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(falhar_em="/media"), espera=0)
            self.assertEqual(P.rodada(ig, self.agora("2026-12-01 09:07")), 1)
            self.assertEqual(self.registro()[0]["resultado"], "erro")
            self.assertIn("2207052", self.registro()[0]["detalhe"])
            self.assertTrue(avisos)
            ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(), espera=0)
            self.assertEqual(P.rodada(ig, self.agora("2026-12-01 09:37")), 0)
            self.assertEqual(self.registro()[-1]["resultado"], "publicado")
        finally:
            P.avisar = antigo

    def test_imagem_recusada_pela_meta(self):
        ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa(status="ERROR"), espera=0)
        with self.assertRaises(P.ErroAPI):
            ig.publicar_story("https://exemplo.test/x.jpg")

    def test_facebook_exige_id(self):
        ig = P.Instagram("TOKEN-TESTE", host="graph.facebook.com", http=MetaFalsa())
        with self.assertRaises(P.ErroAPI):
            ig.conta()
        ig = P.Instagram("TOKEN-TESTE", user_id="17841472104337280", host="graph.facebook.com", http=MetaFalsa())
        ig.publicar_story("https://exemplo.test/x.jpg")

    def test_descobre_conta_pela_pagina(self):
        os.environ["PAGE_ID"] = "PAGINA1"
        try:
            ig = P.Instagram("TOKEN-TESTE", host="graph.facebook.com", http=MetaFalsa())
            ig.conta()
            self.assertEqual(ig.user_id, "1784PAGINA")
        finally:
            os.environ.pop("PAGE_ID")

    def test_renovar_token(self):
        ig = P.Instagram("TOKEN-TESTE", http=MetaFalsa())
        self.assertEqual(ig.renovar_token(), ("NOVO", 5184000))


if __name__ == "__main__":
    unittest.main()
