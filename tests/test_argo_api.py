"""Test di argo_api con la rete simulata (nessun account né connessione necessari)."""

import email.message
import json
import unittest
from unittest import mock

import argo_api
from argo_api import ArgoAuthError, ArgoClient, ArgoError, Dashboard


def risposta(stato=200, corpo=b"", location=None, cookie=()):
    h = email.message.Message()
    if location:
        h["Location"] = location
    for c in cookie:
        h["Set-Cookie"] = c
    return stato, h, corpo


class TestModelli(unittest.TestCase):
    def test_dashboard_camel_case_flag_e_null(self):
        d = Dashboard.da_api(
            {
                "mediaGenerale": "7.5",
                "voti": [{"datGiorno": "2026-10-06", "valore": 8, "desMateria": " Storia ", "docente": None}],
                "appello": [{"data": "2026-10-06", "giustificata": "N", "daGiustificare": True}],
                "registro": [
                    {"materia": "Italiano", "compiti": [{"compito": "es. 1", "dataConsegna": "2026-10-07"}]}
                ],
                "promemoria": [{"flgVisibileFamiglia": "N"}, {}],
                "bacheca": None,
                "bachecaAlunno": [{"flgDownloadGenitore": "S", "isPresaVisione": False}],
                "listaDocentiClasse": [{"desCognome": "Rossi", "materie": None}],
                "listaPeriodi": [{"mediaScrutinio": None, "isScrutinioFinale": True}],
            }
        )
        self.assertEqual(d.media_generale, 7.5)
        self.assertEqual(d.voti[0].valore, 8.0)
        self.assertEqual(d.voti[0].des_materia, "Storia")
        self.assertEqual(d.voti[0].docente, "")
        self.assertFalse(d.appello[0].is_giustificata)
        self.assertTrue(d.appello[0].da_giustificare)
        self.assertEqual(d.registro[0].compiti[0].data_consegna, "2026-10-07")
        self.assertFalse(d.promemoria[0].flg_visibile_famiglia)
        self.assertTrue(d.promemoria[1].flg_visibile_famiglia)  # default
        self.assertEqual(d.bacheca, [])
        self.assertTrue(d.bacheca_alunno[0].flg_download_genitore)
        self.assertEqual(d.lista_docenti_classe[0].materie, [])
        self.assertIsNone(d.lista_periodi[0].media_scrutinio)
        self.assertTrue(d.lista_periodi[0].is_scrutinio_finale)

    def test_dashboard_vuota(self):
        d = Dashboard.da_api(None)
        self.assertEqual((d.voti, d.registro, d.media_generale), ([], [], None))

    def test_estrai_dashboard(self):
        interno = {"voti": []}
        self.assertEqual(argo_api.estrai_dashboard({"data": {"dati": [interno]}}), interno)
        self.assertEqual(argo_api.estrai_dashboard({"data": interno}), interno)
        self.assertEqual(argo_api.estrai_dashboard({"data": {"dati": []}}), [])


class TestPrimitive(unittest.TestCase):
    def test_challenge_pkce_vettore_rfc7636(self):
        self.assertEqual(
            argo_api._challenge_pkce("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )

    def test_formatta_data(self):
        from datetime import datetime

        self.assertEqual(
            argo_api.formatta_data(datetime(2026, 10, 5, 8, 30, 15, 123456)),
            "2026-10-05 08:30:15.123",
        )

    def test_errore_da_stato(self):
        self.assertIsInstance(argo_api._errore(401, {"msg": "no"}), ArgoAuthError)
        e = argo_api._errore(500, None)
        self.assertNotIsInstance(e, ArgoAuthError)
        self.assertIn("HTTP 500", str(e))


class TestLogin(unittest.TestCase):
    def client(self):
        return ArgoClient("SC1", "mario", "p&ss è", versione="9.9.9")

    def test_flusso_oauth_completo(self):
        chiamate = []
        sequenza = [
            risposta(302, location="https://auth/login?login_challenge=CH", cookie=["a=1; Path=/"]),
            risposta(302, location="https://sso/1"),
            risposta(302, location="https://sso/2", cookie=["b=2; HttpOnly"]),
            risposta(302, location="https://sso/3"),
            risposta(302, location="it.argosoft.didup.famiglia.new://login-callback?code=CODE&state=x"),
            risposta(200, json.dumps({"access_token": "TOK", "expires_in": 3600}).encode()),
            risposta(200, json.dumps({"data": [{"token": "XT", "codMin": "M"}]}).encode()),
        ]

        def finta(metodo, url, **kw):
            chiamate.append((metodo, url, kw))
            return sequenza.pop(0)

        c = self.client()
        with mock.patch.object(argo_api, "_richiesta", finta):
            c.login()

        self.assertEqual(sequenza, [])
        (m0, u0, _), (m1, u1, k1), (_, u2, k2), (_, u3, k3), (_, u4, k4), (m5, u5, k5), (m6, u6, k6) = chiamate
        self.assertEqual((m0, u0.split("?")[0]), ("GET", argo_api.OAUTH_AUTH_URL))
        self.assertIn("code_challenge_method=S256", u0)
        self.assertEqual((m1, u1), ("POST", argo_api.SSO_LOGIN_URL))
        corpo = k1["corpo"].decode()
        self.assertIn("challenge=CH", corpo)
        self.assertIn("famiglia_customer_code=SC1", corpo)
        self.assertIn("password=p%26ss%20%C3%A8", corpo)
        self.assertEqual(k2["headers"], {"cookie": "a=1"})
        self.assertEqual(k3["headers"], {})
        self.assertEqual(k4["headers"], {"cookie": "a=1; b=2"})
        self.assertEqual((u2, u3, u4), ("https://sso/1", "https://sso/2", "https://sso/3"))
        self.assertEqual((m5, u5), ("POST", argo_api.OAUTH_TOKEN_URL))
        self.assertIn("code=CODE", k5["corpo"].decode())
        self.assertIn("code_verifier=", k5["corpo"].decode())
        self.assertEqual((m6, u6), ("POST", argo_api.API_BASE_URL + "login"))
        self.assertEqual(k6["headers"]["authorization"], "Bearer TOK")
        self.assertEqual(k6["headers"]["argo-client-version"], "9.9.9")
        self.assertIn("x-date-exp-auth", k6["headers"])

    def test_credenziali_errate(self):
        sequenza = [
            risposta(302, location="https://auth/login?login_challenge=CH"),
            risposta(200, b"<html>login</html>"),
        ]
        with mock.patch.object(argo_api, "_richiesta", lambda *a, **k: sequenza.pop(0)):
            with self.assertRaises(ArgoAuthError):
                self.client().login()

    def test_catena_interrotta(self):
        sequenza = [
            risposta(302, location="https://auth/login?login_challenge=CH"),
            risposta(302, location="https://sso/1"),
            risposta(200),
        ]
        with mock.patch.object(argo_api, "_richiesta", lambda *a, **k: sequenza.pop(0)):
            with self.assertRaises(ArgoError):
                self.client().login()

    def test_errore_token(self):
        sequenza = [
            risposta(302, location="https://auth/login?login_challenge=CH"),
            risposta(302, location="https://sso/1"),
            risposta(302, location="https://sso/2"),
            risposta(302, location="https://sso/3"),
            risposta(302, location="app://cb?code=C"),
            risposta(400, json.dumps({"error": "invalid_grant", "error_description": "scaduto"}).encode()),
        ]
        with mock.patch.object(argo_api, "_richiesta", lambda *a, **k: sequenza.pop(0)):
            with self.assertRaisesRegex(ArgoError, "scaduto"):
                self.client().login()


class TestDati(unittest.TestCase):
    def client(self, voci):
        c = ArgoClient("SC1", "mario", "x", versione="1")
        c._token = "TOK"
        c._voci = voci
        return c

    def test_profili_salta_disabilitati_e_legge_nome(self):
        voci = [
            {"token": "A"},
            {"token": "B", "profiloDisabilitato": True},
            {"token": "C"},
        ]
        c = self.client(voci)
        nomi = {"A": "Mario", "C": "Anna"}

        def finta(metodo, percorso, corpo=None, voce=None):
            self.assertEqual((metodo, percorso), ("GET", "profilo"))
            return {"data": {"alunno": {"nome": nomi[voce["token"]]}}}

        with mock.patch.object(c, "_api", finta):
            profili = c.profili()
        self.assertEqual([p.alunno["nome"] for p in profili], ["Mario", "Anna"])
        self.assertEqual([p.voce["token"] for p in profili], ["A", "C"])

    def test_dashboard_usa_voce_e_opzioni(self):
        voce = {"token": "T", "opzioni": [{"chiave": "k", "valore": "v"}, {"x": 1}]}
        c = self.client([{"token": "primo"}, voce])
        visto = {}

        def finta(metodo, percorso, corpo=None, voce=None):
            visto.update(metodo=metodo, percorso=percorso, corpo=corpo, voce=voce)
            return {"data": {"dati": [{"voti": [{"valore": 6}]}]}}

        with mock.patch.object(c, "_api", finta):
            d = c.dashboard(voce)
        self.assertEqual((visto["metodo"], visto["percorso"]), ("POST", "dashboard/dashboard"))
        self.assertEqual(visto["corpo"]["opzioni"], '{"k":"v"}')
        self.assertIs(visto["voce"], voce)
        self.assertEqual(d.voti[0].valore, 6.0)

    def test_headers_profilo(self):
        c = self.client([])
        h = c._headers({"token": "XT", "codMin": "M"})
        self.assertEqual((h["x-auth-token"], h["x-cod-min"]), ("XT", "M"))

    def test_api_success_false(self):
        c = self.client([])
        raw = json.dumps({"success": False, "msg": "boom"}).encode()
        with mock.patch.object(argo_api, "_richiesta", lambda *a, **k: risposta(200, raw)):
            with self.assertRaisesRegex(ArgoError, "boom"):
                c._api("GET", "x")


if __name__ == "__main__":
    unittest.main()
