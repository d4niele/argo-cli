"""Test delle funzioni pure di argo_cli (nessun account né rete necessari).

Gli oggetti in ingresso sono i modelli veri di ``didupwrapper``: se una nuova
versione rinomina un campo usato dalla CLI, i test falliscono.
"""

import argparse
import unittest
from datetime import date

from didupwrapper.models import (
    Compito,
    ComunicazioneBacheca,
    EventoAppello,
    FuoriClasse,
    NotaDisciplinare,
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
            [(date(2026, 10, 6), "Assenza", "Assenza (da giustificare) — Rossi")],
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
