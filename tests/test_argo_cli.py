"""Test delle funzioni pure di argo_cli (nessun account né rete necessari).

Gli oggetti in ingresso sono i modelli di ``argo_api``: se si rinomina un
campo usato dalla CLI, i test falliscono.
"""

import argparse
import contextlib
import io
import os
import tempfile
import types
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from argo_api import (
    Compito,
    ComunicazioneBacheca,
    Docente,
    EventoAppello,
    FileBachecaAlunno,
    FuoriClasse,
    NotaDisciplinare,
    Periodo,
    Promemoria,
    RegistroLezione,
    Voto,
)

import argo_cli

# Lunedì 5 ottobre 2026 ... domenica 11 ottobre 2026
LUNEDI = date(2026, 10, 5)
VENERDI = date(2026, 10, 9)
SABATO = date(2026, 10, 10)
DOMENICA = date(2026, 10, 11)


class TestDate(unittest.TestCase):
    def test_parse_data(self):
        self.assertEqual(argo_cli.parse_data("2026-10-05"), LUNEDI)
        self.assertEqual(argo_cli.parse_data("2026-10-05 08:00:00.0"), LUNEDI)
        self.assertIsNone(argo_cli.parse_data(""))
        self.assertIsNone(argo_cli.parse_data("non è una data"))

    def test_fmt(self):
        self.assertEqual(argo_cli.fmt(LUNEDI), "05-10-2026")

    def test_data_da_argomento(self):
        self.assertEqual(argo_cli.data_da_argomento("05-10-2026"), LUNEDI)
        with self.assertRaises(argparse.ArgumentTypeError):
            argo_cli.data_da_argomento("2026-10-05")

    def test_range_compiti_inizio_settimana(self):
        self.assertEqual(argo_cli.range_compiti(LUNEDI), (LUNEDI, DOMENICA))

    def test_range_compiti_giovedi(self):
        giovedi = date(2026, 10, 8)
        self.assertEqual(argo_cli.range_compiti(giovedi), (giovedi, DOMENICA))

    def test_range_compiti_venerdi_estende_alla_settimana_dopo(self):
        self.assertEqual(argo_cli.range_compiti(VENERDI), (VENERDI, date(2026, 10, 18)))
        self.assertEqual(argo_cli.range_compiti(SABATO), (SABATO, date(2026, 10, 18)))
        self.assertEqual(argo_cli.range_compiti(DOMENICA), (DOMENICA, date(2026, 10, 18)))

    def test_range_voti(self):
        self.assertEqual(argo_cli.range_voti(DOMENICA), (LUNEDI, DOMENICA))

    def test_range_ultimo_mese(self):
        self.assertEqual(argo_cli.range_ultimo_mese(DOMENICA), (date(2026, 9, 12), DOMENICA))


class TestCostruisciSezione(unittest.TestCase):
    VOCI = [
        (date(2026, 10, 6), "Storia", "cap. 3"),
        (LUNEDI, "Matematica", "es. 1-5"),
        (date(2026, 10, 6), "Italiano", "tema"),
        (LUNEDI, "Storia", "cap. 2"),
    ]

    def test_per_giorno(self):
        sezione = argo_cli.costruisci_sezione(LUNEDI, DOMENICA, self.VOCI, per_gruppo=False)
        self.assertEqual(sezione["dal"], "05-10-2026")
        self.assertEqual(sezione["al"], "11-10-2026")
        self.assertEqual(sezione["numero_materie"], 3)
        self.assertEqual(sezione["materie"], ["Italiano", "Matematica", "Storia"])
        self.assertEqual(sezione["ordinamento"], "giorno")
        self.assertEqual([g["etichetta"] for g in sezione["gruppi"]], ["05-10-2026", "06-10-2026"])
        self.assertEqual(
            sezione["gruppi"][1]["voci"],
            [{"materia": "Italiano", "testo": "tema"}, {"materia": "Storia", "testo": "cap. 3"}],
        )

    def test_per_materia(self):
        sezione = argo_cli.costruisci_sezione(LUNEDI, DOMENICA, self.VOCI, per_gruppo=True)
        self.assertEqual(sezione["ordinamento"], "materia")
        storia = next(g for g in sezione["gruppi"] if g["etichetta"] == "Storia")
        self.assertEqual(
            storia["voci"],
            [{"data": "05-10-2026", "testo": "cap. 2"}, {"data": "06-10-2026", "testo": "cap. 3"}],
        )

    def test_campo_docente(self):
        sezione = argo_cli.costruisci_sezione(
            LUNEDI, DOMENICA, [(LUNEDI, "Rossi", "verifica")], per_gruppo=False, campo="docente"
        )
        self.assertEqual(sezione["docenti"], ["Rossi"])
        self.assertEqual(sezione["numero_docenti"], 1)
        self.assertEqual(sezione["gruppi"][0]["voci"], [{"docente": "Rossi", "testo": "verifica"}])

    def test_vuota(self):
        sezione = argo_cli.costruisci_sezione(LUNEDI, DOMENICA, [], per_gruppo=False)
        self.assertEqual(sezione["materie"], [])
        self.assertEqual(sezione["gruppi"], [])


class TestRaccogli(unittest.TestCase):
    def test_compiti_filtra_per_data_di_consegna(self):
        registro = [
            RegistroLezione(
                materia="Matematica",
                compiti=[
                    Compito(compito="es. 1-5", data_consegna="2026-10-06"),
                    Compito(compito="fuori intervallo", data_consegna="2026-10-20"),
                    Compito(compito="senza data", data_consegna=""),
                ],
            )
        ]
        self.assertEqual(
            argo_cli.raccogli_compiti(registro, LUNEDI, DOMENICA),
            [(date(2026, 10, 6), "Matematica", "es. 1-5")],
        )

    def test_voti(self):
        voti = [
            Voto(
                dat_giorno="2026-10-06",
                valore=7.5,
                des_materia="Storia",
                descrizione_prova="interrogazione",
                docente="Rossi",
                des_commento="bene",
            ),
            Voto(dat_giorno="2026-10-07", descrizione_voto="+", des_materia="Inglese", docente="Bianchi"),
            Voto(dat_giorno="2026-09-01", valore=6, des_materia="Storia", docente="Rossi"),
        ]
        self.assertEqual(
            argo_cli.raccogli_voti(voti, LUNEDI, DOMENICA),
            [
                (date(2026, 10, 6), "Storia", "7.5 (interrogazione) — Rossi [bene]"),
                (date(2026, 10, 7), "Inglese", "+ — Bianchi"),
            ],
        )

    def test_promemoria(self):
        promemoria = [
            Promemoria(
                dat_giorno="2026-10-06",
                des_annotazioni="verifica",
                docente="Rossi",
                ora_inizio="10:00:00",
                ora_fine="11:00:00",
            ),
            Promemoria(
                dat_giorno="2026-10-07",
                des_annotazioni="tutto il giorno",
                docente="Bianchi",
                ora_inizio="00:00",
                ora_fine="00:00",
            ),
            Promemoria(
                dat_giorno="2026-10-07",
                des_annotazioni="nascosto",
                docente="Verdi",
                flg_visibile_famiglia=False,
            ),
        ]
        self.assertEqual(
            argo_cli.raccogli_promemoria(promemoria, LUNEDI, DOMENICA),
            [
                (date(2026, 10, 6), "Rossi", "verifica [10:00-11:00]"),
                (date(2026, 10, 7), "Bianchi", "tutto il giorno"),
            ],
        )

    def test_bacheca(self):
        bacheca = [
            ComunicazioneBacheca(
                data="2026-10-06",
                messaggio="Uscita didattica",
                autore="Dirigente",
                categoria="Circolari",
                data_scadenza="2026-10-08",
                pv_richiesta=True,
            ),
            ComunicazioneBacheca(data="2026-10-07", messaggio="Avviso"),
        ]
        self.assertEqual(
            argo_cli.raccogli_bacheca(bacheca, LUNEDI, DOMENICA),
            [
                (
                    date(2026, 10, 6),
                    "Circolari",
                    "Uscita didattica — Dirigente (scadenza 08-10-2026) [presa visione richiesta]",
                ),
                (date(2026, 10, 7), "Generale", "Avviso"),
            ],
        )

    def test_assenze(self):
        assenze = [
            EventoAppello(
                data="2026-10-06", descrizione="Assenza", da_giustificare=True, docente="Rossi"
            ),
        ]
        self.assertEqual(
            argo_cli.raccogli_assenze(assenze, LUNEDI, DOMENICA),
            [(date(2026, 10, 6), "Assenza", "da giustificare — Rossi")],
        )

    def test_note(self):
        note = [
            NotaDisciplinare(data="2026-10-06", docente="Rossi", descrizione="disturba"),
            NotaDisciplinare(data="2026-09-01", docente="Rossi", descrizione="vecchia"),
        ]
        self.assertEqual(
            argo_cli.raccogli_note(note, LUNEDI, DOMENICA),
            [(date(2026, 10, 6), "Rossi", "disturba")],
        )

    def test_fuori_classe(self):
        fuori = [
            FuoriClasse(data="2026-10-06", descrizione="Gara", nota="mattina", frequenza_on_line=True),
        ]
        self.assertEqual(
            argo_cli.raccogli_fuori_classe(fuori, LUNEDI, DOMENICA),
            [(date(2026, 10, 6), "—", "Gara (mattina) [online]")],
        )

    def test_bacheca_in_sospeso(self):
        bacheca = [
            ComunicazioneBacheca(data="2026-09-01", messaggio="Da firmare", pv_richiesta=True),
            ComunicazioneBacheca(data="2026-09-01", messaggio="Firmata", pv_richiesta=True, is_presa_visione=True),
            ComunicazioneBacheca(data="2026-09-01", messaggio="Scade", data_scadenza="2026-10-07"),
            ComunicazioneBacheca(data="2026-09-01", messaggio="Scaduta", data_scadenza="2026-10-01"),
            ComunicazioneBacheca(data="2026-10-12", messaggio="Futura"),
        ]
        self.assertEqual(
            [testo for _, _, testo in argo_cli.raccogli_bacheca(bacheca, LUNEDI, DOMENICA, LUNEDI)],
            ["Da firmare [presa visione richiesta]", "Scade (scadenza 07-10-2026)"],
        )
        # Senza ``in_sospeso_al`` (intervallo esplicito) le vecchie non compaiono.
        self.assertEqual(argo_cli.raccogli_bacheca(bacheca, LUNEDI, DOMENICA), [])

    def test_bacheca_alunno(self):
        allegati = [
            FileBachecaAlunno(data="2026-10-06", nome_file="pagella.pdf"),
            FileBachecaAlunno(data="2026-09-01", messaggio="Da scaricare", flg_download_genitore=True),
            FileBachecaAlunno(
                data="2026-09-01", messaggio="Scaricato", flg_download_genitore=True, is_presa_visione=True
            ),
        ]
        self.assertEqual(
            argo_cli.raccogli_bacheca_alunno(allegati, LUNEDI, DOMENICA, in_sospeso=True),
            [
                (date(2026, 10, 6), "Allegato", "pagella.pdf"),
                (date(2026, 9, 1), "Allegato", "Da scaricare [da scaricare]"),
            ],
        )
        self.assertEqual(len(argo_cli.raccogli_bacheca_alunno(allegati, LUNEDI, DOMENICA)), 1)


class TestEnvLocale(unittest.TestCase):
    def test_utf8_con_bom(self):
        with tempfile.TemporaryDirectory() as cartella:
            env = Path(cartella) / ".env.local"
            env.write_bytes("\ufeffDIDUP_PASSWORD='perché'\n# commento\n".encode("utf-8"))
            with mock.patch.object(argo_cli, "ENV_FILE", env), mock.patch.dict(os.environ, clear=True):
                argo_cli.carica_env_locale()
                self.assertEqual(os.environ["DIDUP_PASSWORD"], "perché")


class _Risposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TestWhatsapp(unittest.TestCase):
    def test_esito_callmebot(self):
        self.assertIsNone(argo_cli.esito_callmebot("<p>Message queued. You will receive it soon.</p>", "x"))
        self.assertEqual(
            argo_cli.esito_callmebot("<b>APIKey is invalid</b>", "x"), "APIKey is invalid"
        )
        self.assertEqual(argo_cli.esito_callmebot("", "x"), "risposta vuota")
        # Il testo inviato ripetuto nella pagina non vale come conferma.
        self.assertIsNotNone(argo_cli.esito_callmebot("Error. Text: message sent", "message sent"))

    def test_dividi_messaggio(self):
        self.assertEqual(argo_cli.dividi_messaggio("breve"), ["breve"])
        testo = "\n".join(f"riga {i} " + "x" * 80 for i in range(40))
        parti = argo_cli.dividi_messaggio(testo, 1000)
        self.assertGreater(len(parti), 1)
        self.assertTrue(all(len(p) <= 1000 for p in parti))
        self.assertTrue(parti[0].startswith(f"(1/{len(parti)})\n"))
        senza_numeri = "\n".join(p.split("\n", 1)[1] for p in parti)
        self.assertEqual(senza_numeri, testo)
        # Una riga più lunga del limite viene spezzata.
        self.assertTrue(all(len(p) <= 100 for p in argo_cli.dividi_messaggio("y" * 500, 100)))

    def _invia(self, corpi):
        risposte = iter(corpi)

        def urlopen(url, timeout=None):
            corpo = next(risposte)
            if isinstance(corpo, Exception):
                raise corpo
            return _Risposta(corpo.encode())

        errori = io.StringIO()
        with mock.patch.dict(
            os.environ, {"CALLMEBOT_PHONE": "+391, +392", "CALLMEBOT_APIKEY": "a,b"}
        ), mock.patch("urllib.request.urlopen", urlopen), contextlib.redirect_stderr(errori):
            try:
                argo_cli.invia_whatsapp("ciao")
                codice = 0
            except SystemExit as exc:
                codice = exc.code
        return codice, errori.getvalue()

    def test_invio_riuscito(self):
        codice, errori = self._invia(["Message queued", "Message queued"])
        self.assertEqual(codice, 0)
        self.assertIn("inviato a +392", errori)

    def test_errore_nel_corpo(self):
        codice, errori = self._invia(["APIKey is invalid", "Message queued"])
        self.assertEqual(codice, 1)
        self.assertIn("+391 fallito: APIKey is invalid", errori)
        self.assertIn("inviato a +392", errori)

    def test_errore_di_rete(self):
        codice, errori = self._invia([urllib.error.URLError("offline"), "Message queued"])
        self.assertEqual(codice, 1)
        self.assertIn("+391 fallito", errori)


class _DataFissa(date):
    @classmethod
    def today(cls):
        return LUNEDI


class TestMain(unittest.TestCase):
    """Esegue ``main`` con un client finto (nessuna rete)."""

    PROMEMORIA = [Promemoria(dat_giorno="2026-10-06", des_annotazioni="verifica", docente="Rossi")]

    def _esegui(self, argv, **dashboard):
        dati = dict(
            voti=[], registro=[], promemoria=self.PROMEMORIA, bacheca=[], appello=[],
            note_disciplinari=[], fuori_classe=[], bacheca_alunno=[],
            lista_docenti_classe=[], lista_periodi=[], media_generale=None,
        )
        dati.update(dashboard)
        client = mock.MagicMock()
        client.dashboard.return_value = types.SimpleNamespace(**dati)
        uscita = io.StringIO()
        with mock.patch.object(argo_cli, "ArgoClient", return_value=client), \
                mock.patch.object(argo_cli, "date", _DataFissa), \
                mock.patch.object(argo_cli, "carica_env_locale"), \
                mock.patch.dict(os.environ, {"DIDUP_SCUOLA": "s", "DIDUP_USERNAME": "u", "DIDUP_PASSWORD": "p"}), \
                mock.patch("sys.argv", ["argo_cli.py", *argv]), \
                contextlib.redirect_stdout(uscita):
            argo_cli.main()
        return uscita.getvalue()

    def test_all_rispetta_no_promemoria(self):
        self.assertIn("verifica", self._esegui(["--all"]))
        self.assertNotIn("verifica", self._esegui(["--all", "--no-promemoria"]))

    def test_all_vuoto_stampa_periodi_media_docenti(self):
        uscita = self._esegui(
            ["--all", "--no-promemoria"],
            media_generale=7.25,
            lista_periodi=[Periodo(descrizione="Primo quadrimestre", data_inizio="2026-09-15", data_fine="2027-01-31")],
            lista_docenti_classe=[Docente(des_cognome="Bianchi", des_nome="Anna", materie=["Matematica"])],
        )
        self.assertIn("Nessun elemento trovato", uscita)
        self.assertIn("Media generale: 7.25", uscita)
        self.assertIn("Primo quadrimestre", uscita)
        self.assertIn("Bianchi Anna", uscita)

    def test_intestazione_bacheca(self):
        bacheca = [ComunicazioneBacheca(data="2026-08-01", messaggio="Vecchia", pv_richiesta=True)]
        uscita = self._esegui(["--bacheca", "--no-promemoria"], bacheca=bacheca)
        self.assertIn("=== Bacheca (dal 06-09-2026 al 05-10-2026, più quelle precedenti ancora in sospeso) ===", uscita)
        self.assertIn("Vecchia", uscita)
        # Con un intervallo esplicito niente sospesi e niente nota.
        uscita = self._esegui(["--bacheca", "--dal", "01-08-2026", "--al", "02-08-2026"], bacheca=bacheca)
        self.assertIn("=== Bacheca (dal 01-08-2026 al 02-08-2026) ===", uscita)


class TestAlunno(unittest.TestCase):
    ALUNNO = {"nome": "Mario", "cognome": "Rossi", "nominativo": "ROSSI MARIO"}

    def test_nome_alunno(self):
        self.assertEqual(argo_cli.nome_alunno(self.ALUNNO), "ROSSI MARIO")
        self.assertEqual(argo_cli.nome_alunno({"nome": "Anna", "cognome": "Verdi"}), "Verdi Anna")

    def test_corrisponde(self):
        for cercato in ("mario", "Mario Rossi", "rossi  mario", "ROSSI"):
            with self.subTest(cercato=cercato):
                self.assertTrue(argo_cli.corrisponde(self.ALUNNO, cercato))
        for cercato in ("", "Luigi", "mar"):
            with self.subTest(cercato=cercato):
                self.assertFalse(argo_cli.corrisponde(self.ALUNNO, cercato))


if __name__ == "__main__":
    unittest.main()
